import * as PIXI from "pixi.js";
import type { MutableRefObject } from "react";
import { audioTimeline } from "@/runtime/audio/audioTimeline";
import { cleanLatexToMath, GlyphMetadata, StrokeEntry } from "@/runtime/motion/glyphLayoutEngine";
import { useRuntimeStore } from "@/runtime/runtimeStore";
import { drawInkPhysicsRibbon, renderMotionStroke } from "./inkPhysics";
import { collectWhiteboardAuditFindings, reportWhiteboardAuditFindings } from "@/runtime/motion/whiteboardAudit";
import {
  canRevealStrokeYet,
  drawLegacyStroke,
  getEquationWriteEndMs,
  getRevealOrder,
  maxRevealOrderIndexAtTime,
  resolveActiveWritingEquationId,
} from "./canvasRenderHelpers";
import { shouldHideSupersededBoardObject } from "@/runtime/motion/derivationBoard";
import { drawNodeComplete, drawNodeProcedural, drawTreeEdge } from "./scenePrimitives";
import type { CanvasTheme as PrimitiveCanvasTheme } from "./scenePrimitives";

export interface CanvasTheme extends PrimitiveCanvasTheme {
  bg: number;
  nodeText: number;
  annotation: number;
  equation: number;
  edge: number;
  stroke: number;
}

// Glyph strokes are the motion-authoritative ink path.
// PIXI.Text remains enabled as the static completed-state fallback so
// node labels are never invisible when glyph layout fails.
const FORCE_DISABLE_TEXT_RENDERING = false;

export interface SceneRenderDependencies {
  scaleX: number;
  scaleY: number;
  themes: { light: CanvasTheme; dark: CanvasTheme };
  colors: { highlight: number };
  boardWidth: number;
  boardHeight: number;
  resolveHexColor: (value: any, fallback: number) => number;
  drawStackFrameProcedural: (g: PIXI.Graphics, theme: CanvasTheme, w?: number, h?: number, progress?: number, highlight?: boolean, showBorder?: boolean) => void;
  drawLegacyStroke: (g: PIXI.Graphics, path: [number, number][], progress: number, opts?: { id?: string; color?: number; thickness?: number; alpha?: number }) => void;
  resolveStrokeStateForRender: (strokeIndex: number, stroke: StrokeEntry, strokes: StrokeEntry[], charStates: any[] | undefined, currentTimeMs: number) => any | null;
  clipPointsForReveal: (pts: number[][], cState: { startMs: number; endMs: number } | null, currentTimeMs: number) => number[][];
  centerStrokePoints: (pts: number[][], halfWidth: number) => number[][];
  shouldDrawStrokeForTiming: (cState: { startMs: number; endMs: number } | null, charStates: any[] | undefined, currentTimeMs: number, objStartMs: number) => boolean;
  nodeMapRef: MutableRefObject<Record<string, any>>;
  nodeConstructionRef: MutableRefObject<Record<string, any>>;
  studentGfxRef: MutableRefObject<Record<string, PIXI.Graphics>>;
  motionGfxRef: MutableRefObject<Record<string, PIXI.Graphics>>;
  gestureGfxRef: MutableRefObject<Record<string, PIXI.Graphics>>;
  cursorMotionRef: MutableRefObject<{ x: number; y: number; angle: number; initialized: boolean; speed: number }>;
}

export function renderCanvasScene(app: PIXI.Application, layers: Record<string, any>, nowMs: number, deps: SceneRenderDependencies): void {
  if (!app) return;

  const state = useRuntimeStore.getState();
  const { sceneObjects, boardTheme, motionState, studentStrokes } = state;

  const activeSceneId = state.activeSceneId || "scene_0";
  const viewedSceneId = state.viewedSceneId || activeSceneId;
  const isLive = (viewedSceneId === activeSceneId);
  const viewedPageIndex = parseInt(viewedSceneId.split("_")[1]) || 0;
  const viewedXOffset = viewedPageIndex * 1200;  // PAGE_W = 1200
  const xOffset = viewedXOffset;

  const currentTimeMs = (audioTimeline.state === "playing")
    ? audioTimeline.currentTimeMs
    : (state.currentTimeMs || 0);

  const theme = boardTheme === "light" ? deps.themes.light : deps.themes.dark;
  const {
    edgeLayer, nodeLayer, annLayer, strokeLayer, mStrokeLayer,
    gestureLayer, studentLayer, cursorLayer, cursorGfx, cursorGlow, cursorTrail
  } = layers;
  const map = deps.nodeMapRef.current;
  const nodeConst = deps.nodeConstructionRef.current;

  app.renderer.background.color = theme.bg;

  const padding = 12;
  const scaleX = (app.screen.width - padding * 2) / deps.boardWidth;
  const scaleY = (app.screen.height - padding * 2) / deps.boardHeight;
  const fitScale = Math.min(scaleX, scaleY, 1.45);

  const targetX = (app.screen.width - deps.boardWidth * fitScale) / 2;
  const targetY = (app.screen.height - deps.boardHeight * fitScale) / 2;

  app.stage.scale.x += (fitScale - app.stage.scale.x) * 0.15;
  app.stage.scale.y = app.stage.scale.x;
  app.stage.position.x += (targetX - app.stage.position.x) * 0.15;
  app.stage.position.y += (targetY - app.stage.position.y) * 0.15;

  const hasActiveStroke = (motionState.strokes || []).some((stroke: any) => stroke.state === "growing" || stroke.state === "pending" || stroke.progress < 1);
  cursorLayer.visible = Boolean(motionState?.cursor?.visible);
  mStrokeLayer.visible = isLive || hasActiveStroke;
  gestureLayer.visible = isLive || (motionState.gestures || []).length > 0;

  for (const id of Object.keys(map)) {
    if (!Reflect.get(sceneObjects, id)) {
      Reflect.get(map, id)?.container?.destroy({ children: true });
      Reflect.deleteProperty(map, id);
      Reflect.deleteProperty(nodeConst, id);
    }
  }

  const focusState = motionState?.focusState;
  const focusedIds = focusState?.focusedObjectIds || new Set();
  const globalDim = focusState?.globalDimLevel || 0;

  for (const obj of Object.values(sceneObjects)) {
    const objSceneId = obj.sceneId || "scene_0";
    const isVisibleOnCurrentPage = (objSceneId === viewedSceneId);

    if (obj.visible === false) {
      const hidden = Reflect.get(map, obj.id);
      if (hidden) hidden.container.visible = false;
      continue;
    }

    if (shouldHideSupersededBoardObject(obj, sceneObjects)) {
      const superseded = Reflect.get(map, obj.id);
      if (superseded) superseded.container.visible = false;
      continue;
    }

    let entry = Reflect.get(map, obj.id);
    if (entry) entry.container.visible = isVisibleOnCurrentPage;
    if (!isVisibleOnCurrentPage) continue;

    if (!entry) {
      const container = new PIXI.Container();
      container.visible = isVisibleOnCurrentPage;
      container.alpha = 0;
      const typeStr = obj.type || "";
      const isNode = typeStr === "node" || typeStr.endsWith("_node") || typeStr === "rectangle";
      const isConnector = typeStr === "connector" || typeStr === "arrow" || typeStr === "flow" || typeStr === "edge" || typeStr.endsWith("_edge");
      const isContainer = typeStr === "container" || typeStr === "stack" || typeStr.endsWith("_stack");
      const isStroke = typeStr === "stroke" || typeStr === "draw_stroke" || typeStr.endsWith("_stroke");

      const layer = isConnector
          ? edgeLayer
          : (obj.type === "annotation" || obj.type === "label")
            ? annLayer
            : isStroke
              ? strokeLayer
              : nodeLayer;
      layer.addChild(container);

      if (isNode) {
        const g = new PIXI.Graphics();
        const txt = new PIXI.Text({
          text: "",
          style: { fontFamily: "JetBrains Mono, monospace", fontSize: 14, fill: theme.nodeText, fontWeight: "500" }
        });
        txt.anchor.set(0.5);
        container.addChild(g);
        container.addChild(txt);
        entry = { container, kind: "node", g, txt };

        Reflect.set(nodeConst, obj.id, {
          startMs: obj.startMs ?? ((audioTimeline.state === "playing") ? audioTimeline.currentTimeMs : (useRuntimeStore.getState().currentTimeMs || 0)),
          phase: "drawing",
        });

      } else if (isConnector) {
        const g = new PIXI.Graphics();
        const txt = new PIXI.Text({
          text: "",
          style: { fontFamily: "JetBrains Mono, monospace", fontSize: 13, fill: theme.nodeText, fontWeight: "bold" }
        });
        txt.anchor.set(0.5);
        container.addChild(g);
        container.addChild(txt);
        entry = { container, kind: "edge", g, txt };
        Reflect.set(nodeConst, obj.id, {
          startMs: obj.startMs ?? ((audioTimeline.state === "playing") ? audioTimeline.currentTimeMs : (useRuntimeStore.getState().currentTimeMs || 0)),
        });

      } else if (isContainer) {
        const role = obj.data?.visual_role || obj.visual_role || "";
        if (role === "memory_region") {
          const g = new PIXI.Graphics();
          const txt = new PIXI.Text({ text: "", style: { fontFamily: "JetBrains Mono, monospace", fontSize: 13, fill: theme.nodeText } });
          const right = new PIXI.Text({ text: "", style: { fontFamily: "JetBrains Mono, monospace", fontSize: 13, fill: deps.colors.highlight } });
          txt.anchor.set(0.5);
          right.anchor.set(1, 0.5);
          right.position.set(95, 0);
          container.addChild(g); container.addChild(txt); container.addChild(right);
          entry = { container, kind: "stack", g, txt, right };
        } else {
          const g = new PIXI.Graphics();
          container.addChild(g);
          entry = { container, kind: "container", g };
        }

      } else if (obj.type === "annotation" || obj.type === "label") {
        const txt = new PIXI.Text({
          text: "",
          style: { fontFamily: "Outfit, sans-serif", fontSize: obj.data?.size || obj.font_size || obj.data?.font_size || 24, fill: deps.resolveHexColor(obj.color || obj.data?.color, theme.annotation), fontWeight: "500", align: "center" }
        });
        txt.anchor.set(0.5);
        container.addChild(txt);
        entry = { container, kind: "annotation", txt };

      } else if (obj.type === "code_block") {
        const width = Math.max(260, obj.width || 420);
        const height = Math.max(160, obj.height || 220);
        const bg = new PIXI.Graphics();
        const txt = new PIXI.Text({
          text: "",
          style: {
            fontFamily: "JetBrains Mono, monospace",
            fontSize: obj.data?.font_size || obj.data?.size || 18,
            fill: deps.resolveHexColor(obj.data?.color, theme.annotation),
            fontWeight: "500",
            align: "left",
            wordWrap: true,
            wordWrapWidth: Math.max(180, width - 40),
            breakWords: true,
          }
        });
        bg.roundRect(-width / 2, -height / 2, width, height, 14);
        bg.fill({ color: boardTheme === "light" ? 0xf1f5f9 : 0x0f172a, alpha: 0.88 });
        bg.stroke({ color: deps.resolveHexColor(obj.data?.color, theme.annotation), alpha: 0.18, width: 1.25 });
        txt.anchor.set(0, 0);
        txt.position.set(-width / 2 + 20, -height / 2 + 18);
        container.addChild(bg);
        container.addChild(txt);
        entry = { container, kind: "code_block", bg, txt };

      } else if (isStroke) {
        const g = new PIXI.Graphics();
        container.addChild(g);
        entry = { container, kind: "stroke", g };

      } else if (obj.type === "equation_write" || obj.type === "equation") {
        const txt = new PIXI.Text({
          text: "",
          style: { fontFamily: "JetBrains Mono, monospace", fontSize: obj.data?.font_size || 32, fill: theme.equation, align: "center" }
        });
        txt.anchor.set(0.5);
        container.addChild(txt);
        entry = { container, kind: "equation", txt };

      }

      if (entry) {
        Reflect.set(map, obj.id, entry);
        console.log(`🎨 [PixiCanvas] Drawing element added:`, {
          id: obj.id,
          type: obj.type,
          semantic_target: obj.semantic_target || obj.data?.semantic_target || obj.data?.semantic_id || "",
          teaching_step: obj.teaching_step || obj.data?.teaching_step || obj.startMs || 0,
          focus_priority: obj.focus_priority || obj.data?.focus_priority || obj.opacity || 1.0,
          position: obj.position
        });
      }
      if (process.env.NODE_ENV !== "production") {
        reportWhiteboardAuditFindings(
          collectWhiteboardAuditFindings({ obj, entry, currentTimeMs }),
          "sceneRenderer"
        );
      }
    }

    if (!entry) continue;

    const isStroke = entry.kind === "stroke";
    const isEdge = entry.kind === "edge";
    let posX = (isStroke || isEdge) ? 0 : (((obj.position?.x ?? 0) - xOffset) * deps.scaleX);
    let posY = (isStroke || isEdge) ? 0 : ((obj.position?.y ?? 0) * deps.scaleY);

    entry.container.position.set(posX, posY);

    const isFocused = focusedIds.has(obj.id);
    const dimAlpha = globalDim > 0 && !isFocused ? Math.max(0.15, 1 - globalDim * 0.75) : 1;
    entry.container.alpha = Math.max(0, Math.min(1, (obj.opacity ?? 1))) * dimAlpha;
    entry.container.scale.set(obj.scale ?? 1);

    if (entry.kind === "node") {
      const constr = Reflect.get(nodeConst, obj.id) || { startMs: currentTimeMs };
      const elapsed = currentTimeMs - constr.startMs;
      const NODE_DRAW_MS = 700;
      const progress = Math.min(1, Math.max(0, elapsed / NODE_DRAW_MS));

      const focusIntensity = isFocused
        ? (focusState?.activeEffects?.find((e: any) => e.targetIds?.includes(obj.id))?.intensity || 0.6)
        : 0;

      let nodeR = (obj.data?.r || 40) * 0.85;
      let dynamicWidth = null;
      let dynamicHeight = null;

      if (obj.width !== undefined && obj.height !== undefined) {
        dynamicWidth = obj.width * deps.scaleX;
        dynamicHeight = obj.height * deps.scaleY;
        nodeR = dynamicHeight / 2;
      }

      const fullText = String(obj.data?.value ?? obj.data?.label ?? obj.data?.text ?? "");
      const displayText = obj.visitIndex ? `${fullText}  ·${obj.visitIndex}` : fullText;

      if (!FORCE_DISABLE_TEXT_RENDERING) {
        entry.txt.text = displayText;
      }
      const paddingX = 24;
      const calculatedWidth = Math.max(nodeR * 2, entry.txt.width + paddingX);
      const finalWidth = dynamicWidth !== null ? dynamicWidth : calculatedWidth;

      // Prepare ink container for node label if strokes layout is pre-computed
      try {
        if (!entry.inkContainer) {
          entry.inkContainer = new PIXI.Container();
          entry.container.addChild(entry.inkContainer);
        }
      } catch (e) {
        console.warn("node ink container setup failed", e);
      }

      if (obj.data?.pointer_section_width) {
        const pW = obj.data.pointer_section_width * deps.scaleX;
        entry.txt.position.set(-pW / 2, 0);
      } else {
        entry.txt.position.set(0, 0);
      }

      if (progress < 1) {
        const isLiveConstruction = !!(motionState && motionState.phase !== "idle");

        drawNodeProcedural(entry.g, theme, {
          progress,
          r: nodeR,
          highlight: obj.highlight,
          fill: obj.isReview ? 0x2e1065 : (obj.data?.fill || undefined),
          stroke: obj.isReview ? 0xa855f7 : (obj.data?.stroke || undefined),
          dynamicWidth: finalWidth,
          type: obj.type || undefined,
          pointerSectionWidth: obj.data?.pointer_section_width || undefined,
          showPerimeter: !isLiveConstruction
        });

        const textProgress = obj._textProgress !== undefined
          ? obj._textProgress
          : Math.max(0, (progress - 0.85) / 0.15);

        if (!FORCE_DISABLE_TEXT_RENDERING) {
          entry.txt.alpha = textProgress;
          entry.txt.style.fill = obj.highlight ? deps.colors.highlight : theme.nodeText;
        }

      // Render stroke-driven ink for the node label (motion-authoritative)
      if (entry.inkContainer) {
        entry.inkContainer.removeChildren().forEach((child: PIXI.Container) => child.destroy());
        const strokes: StrokeEntry[] = obj._strokesLayout || [];
        const charStates = obj._charStates;
        const layoutHalfW = (obj._totalTextWidth || finalWidth) / 2;

        const revealOrder = getRevealOrder(strokes, obj._constructionSequence);
        for (let orderIdx = 0; orderIdx < revealOrder.length; orderIdx++) {
          const j = revealOrder[orderIdx]!;
          const s = strokes.at(j);
          if (!s) continue;
          const cState = deps.resolveStrokeStateForRender(j, s, strokes, charStates, currentTimeMs);
          if (!deps.shouldDrawStrokeForTiming(cState, charStates, currentTimeMs, obj.startMs || 0)) continue;

          let centered: number[][] = [];
          if (s.points && s.points.length >= 2) {
            centered = s.points as number[][];
          } else {
            centered = [[s.x1, s.y1], [s.x2, s.y2]];
          }

          let visiblePts: number[][] = [];
          if (s.points && s.points.length >= 2) {
            visiblePts = deps.clipPointsForReveal(centered, cState, currentTimeMs);
          } else {
            let [ptStart, ptEnd] = centered;
            if (cState && currentTimeMs < cState.endMs) {
              const localProgress = (currentTimeMs - cState.startMs) / (cState.endMs - cState.startMs || 1);
              const eased = localProgress * localProgress * (3 - 2 * localProgress);
              const xEnd = ptStart[0] + eased * (ptEnd[0] - ptStart[0]);
              const yEnd = ptStart[1] + eased * (ptEnd[1] - ptStart[1]);
              ptEnd = [xEnd, yEnd];
            }
            visiblePts = [ptStart, ptEnd];
          }

          if (visiblePts.length >= 2) {
            // Use backend pressure/thickness if present (indices 2 and 3).
            // Fall back to synthetic direction-based pressure only when missing.
            const hasBE = visiblePts[0]!.length >= 4;
            let beWidths: number[] | undefined;
            let bePressures: number[] | undefined;
            if (hasBE) {
              bePressures = visiblePts.map((pt) => pt[2] ?? 0.8);
              beWidths    = visiblePts.map((pt) => pt[3] ?? (s.thickness || 2));
            } else {
              const synPressures: number[] = [];
              let lPrev: number[] | null = null;
              for (const pt of visiblePts) {
                if (lPrev === null) synPressures.push(0.72);
                else {
                  const dy = pt[1] - lPrev[1];
                  const sl = Math.hypot(pt[0] - lPrev[0], dy) || 1;
                  synPressures.push(Math.max(0.42, Math.min(0.92, 0.68 + 0.28 * (dy / sl))));
                }
                lPrev = pt;
              }
              bePressures = synPressures;
            }
            const strokeGfx = new PIXI.Graphics();
            entry.inkContainer.addChild(strokeGfx);
            drawInkPhysicsRibbon(strokeGfx, visiblePts as [number, number][], {
              baseWidth: Math.max(3, (s.thickness || 2) * 1.8),
              color: deps.resolveHexColor(theme.nodeText, 0xffffff),
              alpha: 0.98,
              pressures: bePressures,
              widths: beWidths,
              taperStart: hasBE ? 0.0 : 0.03,
              taperEnd:   hasBE ? 0.0 : 0.03,
              wobbleAmount: hasBE ? 0.0 : 0.018,
            });
          }
        }
      }
      } else {
        if (entry.inkContainer) {
          entry.inkContainer.removeChildren().forEach((child: PIXI.Container) => child.destroy());
        }
        drawNodeComplete(entry.g, theme, {
          r: nodeR,
          highlight: obj.highlight,
          focusIntensity,
          timeMs: currentTimeMs,
          fill: obj.isReview ? 0x2e1065 : (obj.data?.fill || undefined),
          stroke: obj.isReview ? 0xa855f7 : (obj.data?.stroke || undefined),
          dynamicWidth: finalWidth,
          type: obj.type || undefined,
          pointerSectionWidth: obj.data?.pointer_section_width || undefined
        });
        if (!FORCE_DISABLE_TEXT_RENDERING) {
          entry.txt.alpha = 1;
          entry.txt.style.fill = obj.highlight ? deps.colors.highlight : theme.nodeText;
        }
      }

    } else if (entry.kind === "edge") {
      const constr = Reflect.get(nodeConst, obj.id) || { startMs: currentTimeMs };
      const elapsed = currentTimeMs - constr.startMs;
      const progress = Math.min(1, Math.max(0, elapsed / 600));

      const fromId = obj.data?.from || obj.data?.from_node;
      const toId = obj.data?.to || obj.data?.to_node;

      const fromObj = sceneObjects[fromId];
      const toObj = sceneObjects[toId];

      if (fromObj && toObj && fromObj.position && toObj.position) {
        const strokeColor = obj.data?.stroke || obj.data?.color || null;
        const strokeHex = deps.resolveHexColor(strokeColor, theme.edge);
        const isDirected = obj.type === "arrow" || (obj.data && Object.prototype.hasOwnProperty.call(obj.data, "directed") ? !!obj.data.directed : false);

        drawTreeEdge(
          entry.g, theme,
          { x: ((fromObj.position.x - xOffset) * deps.scaleX), y: (fromObj.position.y * deps.scaleY) },
          { x: ((toObj.position.x - xOffset) * deps.scaleX), y: (toObj.position.y * deps.scaleY) },
          progress,
          isDirected,
          strokeHex,
          entry.txt,
          obj.data?.weight || ""
        );
      }

    } else if (entry.kind === "stack") {
      const elapsed = currentTimeMs - (obj.startMs || 0);
      const progress = Math.min(1, Math.max(0, elapsed / 1500));
      const isLiveConstruction = !!(motionState && motionState.phase !== "idle");

      deps.drawStackFrameProcedural(entry.g, theme, 220, 60, progress, obj.highlight, !isLiveConstruction);
      if (progress > 0.75) {
        const tp = obj._textProgress !== undefined ? obj._textProgress : (progress - 0.75) / 0.25;
        if (!FORCE_DISABLE_TEXT_RENDERING) {
          entry.txt.text = obj.data?.label || obj.data?.function_name || "";
          entry.txt.alpha = tp;
          entry.right.text = obj.data?.result || obj.result || "";
          entry.right.alpha = tp;
          entry.txt.style.fill = theme.nodeText;
        }
      } else {
        if (!FORCE_DISABLE_TEXT_RENDERING) { entry.txt.text = ""; entry.right.text = ""; }
      }

    } else if (entry.kind === "stroke") {
      // Diagram strokes (draw_stroke) reveal progressively on THIS static layer,
      // driven by the audio clock — the same mechanism text uses, which is reliable.
      // We no longer defer to the motion layer for the ink (that path left the board
      // blank); the motion layer still runs for the pen-nib feel, and a small amount
      // of overlap is harmless. progress = audio-elapsed / backend stroke duration.
      const elapsed = currentTimeMs - (obj.startMs || 0);
      const dur = obj.data?.duration_ms || 800;
      const targetProgress = Math.min(1, Math.max(0, elapsed / dur));

      // Eased reveal — draw the line on like a pen instead of popping a chunk.
      // A stroke's object often first renders ~250 ms AFTER its start_ms (dispatch
      // + audio-gate latency), so a raw progress would already be ~0.25 on the very
      // first frame and SNAP the first quarter of the line down at once. We instead
      // remember the last-shown progress per stroke and let it CATCH UP a bounded
      // amount per frame, so the ink always grows smoothly from where it was — the
      // same idea as the clock's per-frame step clamp. Steady playback (target rises
      // ~1-3%/frame) is unaffected; only the initial catch-up is paced.
      const revealMap: Map<string, number> =
        ((globalThis as any).__strokeReveal ||= new Map());
      const prevShown = revealMap.get(obj.id) ?? 0;
      // Locked objects (preserved across generation boundary) show instantly.
      // Past-window strokes snap only after they've already been substantially
      // revealed — prevents a "popped full" first frame when batch-released from
      // the audio gate. While catching up past the window, use a faster step
      // (20%/frame ≈ 5 frames to full) so it still feels like a pen sweep.
      const lockedComplete = Boolean((obj as any)._lockedComplete);
      const fullyDone = lockedComplete || (elapsed > dur + 200 && prevShown > 0.9);
      let progress: number;
      if (fullyDone) {
        progress = 1;
      } else {
        const maxStep = elapsed > dur + 200 ? 0.20 : 0.07;
        progress = Math.max(prevShown, Math.min(targetProgress, prevShown + maxStep));
      }
      revealMap.set(obj.id, progress);

      const rawColor = deps.resolveHexColor(obj.data?.color, theme.stroke);
      const finalColor = (boardTheme === "light" && rawColor === 0xffffff) ? 0x000000 : rawColor;
      const fullPath = (obj.data?.path || [])
        .filter((pt: any) => pt && pt[0] !== undefined && pt[1] !== undefined);
      const clipCount = Math.max(2, Math.floor(fullPath.length * progress));
      const visPtsRaw = fullPath.slice(0, clipCount);
      const visPts = visPtsRaw.map((pt: any) => [(pt[0] - xOffset) * deps.scaleX, pt[1] * deps.scaleY] as [number, number]);
      entry.g.clear();
      if (visPts.length >= 2) {
        // Synthetic pressure fallback
        const synPressures: number[] = [];
        let sPrev: [number, number] | null = null;
        for (const pt of visPts) {
          if (sPrev === null) { synPressures.push(0.72); }
          else {
            const dy = pt[1] - sPrev[1];
            const sl = Math.hypot(pt[0] - sPrev[0], dy) || 1;
            synPressures.push(Math.max(0.42, Math.min(0.92, 0.68 + 0.28 * (dy / sl))));
          }
          sPrev = pt;
        }

        let pressures: number[] | undefined = undefined;
        let widths: number[] | undefined = undefined;
        const hasBackendDynamics = visPtsRaw.some((pt: any) => pt && pt.length >= 4);
        if (hasBackendDynamics) {
          pressures = visPtsRaw.map((pt: any) => pt[2] ?? 0.8);
          widths = visPtsRaw.map((pt: any) => (pt[3] ?? (obj.data?.thickness ?? 2.0)) * deps.scaleY);
        }

        drawInkPhysicsRibbon(entry.g, visPts, {
          baseWidth: Math.max(3.5, (obj.data?.thickness || 2) * 2.0),
          color: finalColor,
          alpha: 0.92,
          pressures: pressures || synPressures,
          widths: widths,
          taperStart: hasBackendDynamics ? 0.0 : 0.04,
          taperEnd: hasBackendDynamics ? 0.0 : 0.06,
          wobbleAmount: hasBackendDynamics ? 0.0 : 0.016,
        });
      }

    } else if (entry.kind === "equation" || entry.kind === "annotation" || entry.kind === "code_block") {
      const isEq = entry.kind === "equation";
      const elapsed = currentTimeMs - (obj.startMs || 0);
      const isCode = entry.kind === "code_block";
      const rawDuration = isEq ? (obj.data?.total_duration_ms || 1000) : (isCode ? (obj.data?.duration_ms || 1800) : (obj.data?.duration_ms || 1500));
      const duration = Math.min(2000, rawDuration * 0.65);
      const progress = Math.min(1, Math.max(0, elapsed / duration));

      entry.txt.style.fill = isEq
        ? deps.resolveHexColor(obj.data?.color, theme.equation)
        : isCode
          ? deps.resolveHexColor(obj.data?.color, theme.annotation)
          : (obj.isReview ? 0xa855f7 : deps.resolveHexColor(obj.data?.color, theme.annotation));
      const textStr = isEq
        ? cleanLatexToMath(obj.data?.latex || obj.data?.text || "")
        : isCode
          ? (obj.data?.code || obj.data?.text || obj.data?.body || "")
          : (obj.text || obj.data?.text || "");

      entry.txt.visible = false;

      if (entry.lastText !== textStr) {
        entry.lastText = textStr;
        const toRemove: PIXI.Container[] = [];
        entry.container.children.forEach((child: PIXI.Container) => {
          if (child !== entry.txt) toRemove.push(child);
        });
        toRemove.forEach(child => child.destroy());

        entry.glyphs = [];
        entry.inkContainer = new PIXI.Container();
        entry.container.addChild(entry.inkContainer);

        // ── Single source of truth: the AST glyph-stroke engine ──────
        // Every equation and annotation is laid out through layoutGlyphsForText
        // (recursive LaTeX AST → positioned glyphs + handwritten strokes).
        // There is NO PIXI.Text character-splitting fallback: that path could
        // not parse \sin, \frac, \int, … and silently garbled them into
        // artifacts like "(x)" / "²(x)". If a glyph is unknown the engine
        // draws a neutral mark rather than corrupting the whole expression.
        // Visual layout metrics must be fully pre-calculated on the backend
        // and fetched directly from obj._glyphsLayout and obj._strokesLayout.

        if (isCode) {
          entry.txt.style.wordWrapWidth = Math.max(180, (obj.width || 420) - 40);
          entry.txt.style.fontSize = obj.data?.font_size || obj.data?.size || 18;
          entry.txt.style.align = "left";
        }

        // Code blocks remain PIXI.Text (monospace, word-wrapped). Everything
        // else (equations, annotations) renders from the AST glyph layout.
        if (!isCode && obj._glyphsLayout) {
          const baseStyle = entry.txt.style;
          for (let i = 0; i < obj._glyphsLayout.length; i++) {
            const gDesc: GlyphMetadata = (obj._glyphsLayout as GlyphMetadata[]).at(i)!;
            const charStyle = new PIXI.TextStyle({
              fill: baseStyle.fill,
              fontFamily: baseStyle.fontFamily,
              fontWeight: baseStyle.fontWeight,
              align: baseStyle.align,
              fontSize: gDesc.isSuperscript ? (baseStyle.fontSize as number) * 0.65 : baseStyle.fontSize
            });

            const txt = new PIXI.Text({ text: gDesc.char, style: charStyle });
            txt.anchor.set(0, 0.75);
            txt.position.set(gDesc.scaledX, gDesc.scaledY);
            txt.visible = false;
            entry.container.addChild(txt);

            entry.glyphs.push({
              txt, char: gDesc.char, x: gDesc.scaledX, y: gDesc.scaledY, width: gDesc.width
            });
          }
          entry.fullWidth = obj._totalTextWidth;
        } else {
          entry.txt.text = textStr;
          entry.txt.visible = true;
          entry.txt.alpha = 1;
        }
      }

      const fullWidth = entry.fullWidth || 300;
      const estimatedHalfW = fullWidth / 2;
      const safeMinX = estimatedHalfW + 15;
      const safeMaxX = deps.boardWidth - estimatedHalfW - 15;
      const safeMinY = 15;
      const safeMaxY = deps.boardHeight - 15;
      const safePosX = obj._safeTextX !== undefined
        ? ((obj._safeTextX - xOffset) * deps.scaleX)
        : Math.max(safeMinX, Math.min(safeMaxX, posX));
      const safePosY = obj._safeTextY !== undefined
        ? (obj._safeTextY * deps.scaleY)
        : Math.max(safeMinY, Math.min(safeMaxY, posY));
      entry.container.position.set(safePosX, safePosY);

      if (entry.glyphs) {
        const strokes: StrokeEntry[] = obj._strokesLayout || [];
        const charStates = obj._charStates;

        for (let i = 0; i < entry.glyphs.length; i++) {
          const g = entry.glyphs.at(i)!;
          const charStrokes = strokes.filter(s => s.charIndex === i);
          let charFinished = false;

          if (charStrokes.length > 0) {
            charFinished = charStrokes.every(s => {
              const j = strokes.indexOf(s);
              const cState = deps.resolveStrokeStateForRender(j, s, strokes, charStates, currentTimeMs);
              if (cState) {
                return currentTimeMs >= cState.endMs;
              }
              return currentTimeMs - (obj.startMs || 0) > 400;
            });
          } else {
            charFinished = currentTimeMs - (obj.startMs || 0) > 400;
          }
          if (charStrokes.length === 0) {
            // No handwritten strokes — char has no vector glyph. Render as
            // styled PIXI.Text (correct Unicode, matching color + font size).
            const isLocked = Boolean((obj as any)._lockedComplete);
            const shouldShow = isLocked || charFinished;
            g.txt.visible = shouldShow;
            g.txt.alpha = shouldShow ? 0.92 : 0;
          } else {
            // Ink strokes handle rendering; keep the PIXI.Text label hidden.
            g.txt.visible = false;
            g.txt.alpha = 0;
          }
        }
      }

      if (entry.inkContainer) {
        entry.inkContainer.removeChildren().forEach((child: PIXI.Container) => child.destroy());
        const strokes: StrokeEntry[] = obj._strokesLayout || [];
        const charStates = obj._charStates;
        const layoutHalfW = estimatedHalfW;
        const activeWritingId = resolveActiveWritingEquationId(
          sceneObjects,
          motionState as { activeWritingEquationId?: string | null },
          currentTimeMs
        );
        const lastWriteEndMs = getEquationWriteEndMs(obj);
        const isWriteComplete = currentTimeMs >= lastWriteEndMs;
        const isActiveWriter = Boolean(activeWritingId && obj.id === activeWritingId);
        const revealOrder = getRevealOrder(strokes, obj._constructionSequence);
        const nibMaxOrderIndex = isActiveWriter
          ? maxRevealOrderIndexAtTime(revealOrder, strokes, charStates, currentTimeMs)
          : revealOrder.length - 1;

        if (strokes.length > 0) {
          // Per-equation ordered catch-up: when an equation is past its write window
          // (or locked from a prior generation), reveal strokes in sequential order
          // at ~3 per frame rather than all-at-once. Prevents the "pop" that occurs
          // when the audio gate batch-releases late events into an already-advanced clock.
          const eqRevMap: Map<string, number> = ((globalThis as any).__eqReveal ||= new Map());
          const isObjLocked = Boolean((obj as any)._lockedComplete);
          if (isObjLocked) {
            eqRevMap.set(obj.id, revealOrder.length); // always fully revealed
          } else if (isWriteComplete && !isActiveWriter && charStates?.length) {
            const prev = eqRevMap.get(obj.id) ?? 0;
            eqRevMap.set(obj.id, Math.min(revealOrder.length, prev + 3));
          } else if (!isWriteComplete || isActiveWriter) {
            eqRevMap.delete(obj.id);
          }
          const eqRevealedCount = eqRevMap.get(obj.id) ?? revealOrder.length;

          if (charStates?.length && activeWritingId && !isActiveWriter && !isWriteComplete && !isObjLocked) {
            // Queued equations: no progressive ink until this equation becomes the active writer.
          } else {
          for (let orderIdx = 0; orderIdx < revealOrder.length; orderIdx++) {
            const j = revealOrder[orderIdx]!;
            const s = strokes.at(j)!;
            const cState = deps.resolveStrokeStateForRender(j, s, strokes, charStates, currentTimeMs);
            const forceFullInk = Boolean(
              isObjLocked ||
              (charStates?.length && !isActiveWriter && isWriteComplete && orderIdx < eqRevealedCount)
            );
            const segmentFullInk =
              obj._boardCompletedStrokeMaxIndex !== undefined &&
              j <= obj._boardCompletedStrokeMaxIndex;

            if (isActiveWriter && orderIdx > nibMaxOrderIndex) {
              continue;
            }

            if (
              !forceFullInk &&
              !segmentFullInk &&
              !canRevealStrokeYet(j, revealOrder, strokes, charStates, currentTimeMs)
            ) {
              continue;
            }

            if (
              !forceFullInk &&
              !segmentFullInk &&
              !deps.shouldDrawStrokeForTiming(cState, charStates, currentTimeMs, obj.startMs || 0)
            ) {
              continue;
            }

            let centered: number[][] = [];
            if (s.points && s.points.length >= 2) {
              centered = s.points as number[][];
            } else {
              centered = [[s.x1, s.y1], [s.x2, s.y2]];
            }

            let visiblePts: number[][] = [];
            if (forceFullInk || segmentFullInk) {
              visiblePts = centered;
            } else if (s.points && s.points.length >= 2) {
              visiblePts = deps.clipPointsForReveal(centered, cState, currentTimeMs);
            } else {
              let [ptStart, ptEnd] = centered;
              if (cState && currentTimeMs < cState.endMs) {
                const localProgress = (currentTimeMs - cState.startMs) / (cState.endMs - cState.startMs || 1);
                const eased = localProgress * localProgress * (3 - 2 * localProgress);
                const xEnd = ptStart[0] + eased * (ptEnd[0] - ptStart[0]);
                const yEnd = ptStart[1] + eased * (ptEnd[1] - ptStart[1]);
                ptEnd = [xEnd, yEnd];
              }
              visiblePts = [ptStart, ptEnd];
            }

              if (visiblePts.length >= 2) {
                // Use backend pressure/thickness if present (indices 2 and 3).
                // Fall back to synthetic direction-based pressure only when missing.
                const hasBE = visiblePts[0]!.length >= 4;
                let beWidths: number[] | undefined;
                let bePressures: number[] | undefined;
                if (hasBE) {
                  bePressures = visiblePts.map((pt) => pt[2] ?? 0.8);
                  beWidths    = visiblePts.map((pt) => pt[3] ?? (s.thickness || 2));
                } else {
                  const synPressures: number[] = [];
                  let lPrev: number[] | null = null;
                  for (const pt of visiblePts) {
                    if (lPrev === null) { synPressures.push(0.72); }
                    else {
                      const dy = pt[1] - lPrev[1];
                      const sl = Math.hypot(pt[0] - lPrev[0], dy) || 1;
                      synPressures.push(Math.max(0.42, Math.min(0.92, 0.68 + 0.28 * (dy / sl))));
                    }
                    lPrev = pt;
                  }
                  bePressures = synPressures;
                }
                const strokeGfx = new PIXI.Graphics();
                entry.inkContainer.addChild(strokeGfx);
                drawInkPhysicsRibbon(strokeGfx, visiblePts as [number, number][], {
                  baseWidth: Math.max(5, (s.thickness || 2) * 2.6),
                  color: deps.resolveHexColor(entry.txt.style.fill, 0xffffff),
                  alpha: 1.0,
                  pressures: bePressures,
                  widths: beWidths,
                  taperStart: hasBE ? 0.0 : 0.02,
                  taperEnd:   hasBE ? 0.0 : 0.02,
                  velocityDamping: hasBE ? 0.0 : 0.002,
                  wobbleAmount:    hasBE ? 0.0 : 0.018,
                });
              }
          }
          }
        }
      }

    }
  }

  if (motionState) {
    const liveOffset = xOffset;

    const cursor = motionState.cursor;
    if (cursor?.visible) {
      cursorLayer.alpha = cursor.alpha ?? 1;
      const SAFE_MARGIN = 12;
      const rawCX = (cursor.x - liveOffset) * deps.scaleX;
      const rawCY = cursor.y * deps.scaleY;
      const clampedCX = Math.max(SAFE_MARGIN, Math.min(deps.boardWidth - SAFE_MARGIN, rawCX));
      const clampedCY = Math.max(SAFE_MARGIN, Math.min(deps.boardHeight - SAFE_MARGIN, rawCY));

      const penState = deps.cursorMotionRef.current;
      const activeMotionStroke = (motionState.strokes || []).find((stroke: any) => stroke.state === "growing" && (stroke.points?.length || 0) >= 2) as any;
      const writingTip = (cursor as { writingTip?: { x: number; y: number } | null }).writingTip;
      const useStaticWritingTip = Boolean(writingTip) && !activeMotionStroke;
      let targetAngle = penState.angle;
      let targetX = useStaticWritingTip
        ? Math.max(SAFE_MARGIN, Math.min(deps.boardWidth - SAFE_MARGIN, (writingTip!.x - liveOffset) * deps.scaleX))
        : clampedCX;
      let targetY = useStaticWritingTip
        ? Math.max(SAFE_MARGIN, Math.min(deps.boardHeight - SAFE_MARGIN, writingTip!.y * deps.scaleY))
        : clampedCY;
      let motionSpeed = 0;

      if (useStaticWritingTip) {
        const dx = targetX - penState.x;
        const dy = targetY - penState.y;
        motionSpeed = Math.hypot(dx, dy);
        if (motionSpeed > 0.08) {
          const strokeAngle = Math.atan2(dy, dx) + Math.PI / 2;
          targetAngle = strokeAngle * 0.38 + (-0.4) * 0.62;
        } else {
          targetAngle = -0.4;
        }
      } else if (!useStaticWritingTip && activeMotionStroke?.points?.length >= 2) {
        const activeStroke = activeMotionStroke;
        const tipPoint = activeStroke.points.at(-1);
        const prevPoint = activeStroke.points.at(-2);
        if (tipPoint && prevPoint) {
          const dx = tipPoint[0] - prevPoint[0];
          const dy = tipPoint[1] - prevPoint[1];
          motionSpeed = Math.hypot(dx, dy);
          if (motionSpeed > 0.0001) {
            targetAngle = Math.atan2(dy, dx) + Math.PI / 2;
            const trailBackoff = Math.min(9, Math.max(2.5, motionSpeed * 0.85));
            targetX -= Math.cos(targetAngle - Math.PI / 2) * trailBackoff;
            targetY -= Math.sin(targetAngle - Math.PI / 2) * trailBackoff;
          }
        }
      }
      
      const penLerp = useStaticWritingTip ? 0.94 : 0.28;

      if (!penState.initialized) {
        penState.x = targetX;
        penState.y = targetY;
        penState.angle = targetAngle;
        penState.initialized = true;
      } else {
        penState.x += (targetX - penState.x) * penLerp;
        penState.y += (targetY - penState.y) * penLerp;
        const angleDelta = Math.atan2(Math.sin(targetAngle - penState.angle), Math.cos(targetAngle - penState.angle));
        penState.angle += angleDelta * (useStaticWritingTip ? 0.45 : 0.22);
      }
      penState.speed = penState.speed * 0.72 + motionSpeed * 0.28;

      cursorLayer.position.set(penState.x, penState.y);

      let cColorHex = theme.nodeStroke || theme.edge;
      if (cursor.state === "drawing") {
        const activeStroke = motionState?.strokes?.find((s: any) => s.state === "growing" || s.state === "pending" || s.progress < 1);
        if (activeStroke && activeStroke.color) {
          cColorHex = deps.resolveHexColor(activeStroke.color, 0xf59e0b);
        } else {
          cColorHex = 0xf59e0b;
        }
      }
      const cColor = cColorHex;
      cursorGfx.clear();
      cursorGfx.rotation = penState.angle;

      cursorTrail.clear();

      cursorGfx.moveTo(0, 0);
      cursorGfx.lineTo(-2.5, -6);
      cursorGfx.lineTo(2.5, -6);
      cursorGfx.closePath();
      cursorGfx.fill({ color: 0x1e293b });

      cursorGfx.moveTo(0, 0);
      cursorGfx.lineTo(0, -5);
      cursorGfx.stroke({ width: 0.8, color: 0x64748b });

      cursorGfx.moveTo(-2.5, -6);
      cursorGfx.lineTo(-3.5, -10);
      cursorGfx.lineTo(3.5, -10);
      cursorGfx.lineTo(2.5, -6);
      cursorGfx.closePath();
      cursorGfx.fill({ color: 0xcbd5e1 });

      cursorGfx.moveTo(-3.5, -10);
      cursorGfx.lineTo(-4, -18);
      cursorGfx.lineTo(4, -18);
      cursorGfx.lineTo(3.5, -10);
      cursorGfx.closePath();
      cursorGfx.fill({ color: 0x334155 });

      cursorGfx.moveTo(-4, -18);
      cursorGfx.lineTo(-3.5, -36);
      cursorGfx.lineTo(3.5, -36);
      cursorGfx.lineTo(4, -18);
      cursorGfx.closePath();
      cursorGfx.fill({ color: cColor });

      cursorGfx.moveTo(-4, -18).lineTo(4, -18);
      cursorGfx.stroke({ width: 1.0, color: 0xd97706 });

      cursorGfx.moveTo(-3.5, -36);
      cursorGfx.lineTo(-3, -42);
      cursorGfx.lineTo(3, -42);
      cursorGfx.lineTo(3.5, -36);
      cursorGfx.closePath();
      cursorGfx.fill({ color: 0xd97706 });

      cursorGfx.moveTo(3, -22);
      cursorGfx.lineTo(5, -23);
      cursorGfx.lineTo(4.5, -35);
      cursorGfx.lineTo(3.2, -35);
      cursorGfx.closePath();
      cursorGfx.fill({ color: 0x94a3b8 });

      cursorGlow.clear();
      if (cursor.state === "drawing") {
        cursorGlow.circle(0, 0, 6);
        cursorGlow.fill({ color: cColor, alpha: 0.35 });
      } else {
        cursorGlow.circle(0, 0, 4);
        cursorGlow.fill({ color: cColor, alpha: 0.2 });
      }
    } else {
      cursorLayer.alpha = 0;
    }

    const mMap = deps.motionGfxRef.current;
    const activeMotionIds = new Set();
    for (const stroke of (motionState.strokes || [])) {
      // Diagram (draw_stroke) ink is revealed progressively by the static stroke
      // layer against the audio clock — the SAME way text writes. If the motion
      // layer also painted it, a fast scheduler force-complete would slap the whole
      // stroke down at once and make the diagram look like it appears automatically
      // instead of being drawn. So skip draw_stroke ink here; the pen nib still
      // tracks the growing tip via the separate cursor layer.
      if ((sceneObjects as any)[stroke.strokeId]?.type === "draw_stroke") {
        const stale = Reflect.get(mMap, stroke.strokeId);
        if (stale) { stale.destroy(); Reflect.deleteProperty(mMap, stroke.strokeId); }
        continue;
      }
      activeMotionIds.add(stroke.strokeId);
      let g = Reflect.get(mMap, stroke.strokeId);
      if (!g) {
        g = new PIXI.Graphics();
        mStrokeLayer.addChild(g);
        Reflect.set(mMap, stroke.strokeId, g);
      }
      const translatedStroke = {
        ...stroke,
        points: (stroke.points || [])
          .filter((pt: any) => pt && pt[0] !== undefined && pt[1] !== undefined)
          .map((pt: any) => [(pt[0] - liveOffset) * deps.scaleX, pt[1] * deps.scaleY])
      };
      renderMotionStroke(g, translatedStroke, boardTheme);
    }
    for (const id of Object.keys(mMap)) {
      if (!activeMotionIds.has(id)) { Reflect.get(mMap, id)?.destroy(); Reflect.deleteProperty(mMap, id); }
    }

    const gMap = deps.gestureGfxRef.current;
    const activeGestureIds = new Set();
    for (const gesture of (motionState.gestures || [])) {
      activeGestureIds.add(gesture.gestureId);
      let g = Reflect.get(gMap, gesture.gestureId);
      if (!g) {
        g = new PIXI.Graphics();
        gestureLayer.addChild(g);
        Reflect.set(gMap, gesture.gestureId, g);
      }
      if (gesture.path?.length > 1) {
        const validPath = gesture.path.filter((pt: any) => pt && pt[0] !== undefined && pt[1] !== undefined);
        if (validPath.length > 1) {
          g.clear();
          const progressVal = Math.max(0, Math.min(1, gesture.progress ?? 1));
          const limit = Math.min(validPath.length, Math.max(1, Math.floor(validPath.length * progressVal)));
          const ptStart = validPath.at(0);
          if (ptStart) g.moveTo((ptStart[0] - liveOffset) * deps.scaleX, ptStart[1] * deps.scaleY);
          for (let gi = 1; gi < limit; gi++) {
            const pt = validPath.at(gi);
            if (pt) g.lineTo((pt[0] - liveOffset) * deps.scaleX, pt[1] * deps.scaleY);
          }
        }
      }
      g.stroke({
        width: gesture.thickness || 3,
        color: gesture.color || 0xf2cc60,
        cap: "round",
        join: "round",
        alpha: gesture.alpha || 0.75
      });
    }
    for (const id of Object.keys(gMap)) {
      if (!activeGestureIds.has(id)) { Reflect.get(gMap, id)?.destroy(); Reflect.deleteProperty(gMap, id); }
    }
  }

  const sMap = deps.studentGfxRef.current;
  const activeStudentIds = new Set(
    studentStrokes
      .filter(s => (s.sceneId || "scene_0") === viewedSceneId)
      .map(s => s.id)
  );
  for (const id of Object.keys(sMap)) {
    if (!activeStudentIds.has(id)) { Reflect.get(sMap, id)?.destroy(); Reflect.deleteProperty(sMap, id); }
  }
  for (const stroke of studentStrokes) {
    if ((stroke.sceneId || "scene_0") !== viewedSceneId) continue;
    let g = Reflect.get(sMap, stroke.id);
    if (!g) {
      g = new PIXI.Graphics();
      studentLayer.addChild(g);
      Reflect.set(sMap, stroke.id, g);
    }
    g.clear();
    if (stroke.path?.length >= 2) {
      drawInkPhysicsRibbon(g, stroke.path as [number, number][], {
        baseWidth: Math.max(3, (stroke.thickness || 2) * 1.8),
        color: (stroke.color as number) || 0xffffff,
        alpha: 0.9,
        taperStart: 0.02,
        taperEnd: 0.04,
        wobbleAmount: 0.006,
      });
    }
  }
}
