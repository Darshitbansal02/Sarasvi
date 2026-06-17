/**
 * PixiCanvas.tsx — Procedural Teaching Canvas (Phase 2 - High Efficiency)
 *
 * Implements the high-fidelity rendering layer using PixiJS v8.
 * Optimized for low-end hardware via strategic geometry caching,
 * math AST memoization, and throttled state synchronization.
 */

import React, { useEffect, useRef } from "react";
import * as PIXI from "pixi.js";
import { useRuntimeStore } from "@/runtime/runtimeStore";
import { audioTimeline } from "@/runtime/audio/audioTimeline";
import { browserProfiler } from "@/runtime/browserProfiler";
import { pointerOwnership } from "@/runtime/interaction/pointerOwnership";
import { StudentDrawingController } from "./controllers/StudentDrawingController";
import { drawBoardGrid } from "./renderers/gridRenderHelpers";
import { renderCanvasScene } from "./renderers/sceneRenderer";
import {
  CanvasTheme,
  centerStrokePoints,
  clipPointsForReveal,
  drawLegacyStroke,
  drawStackFrameProcedural,
  resolveStrokeStateForRender,
  shouldDrawStrokeForTiming,
} from "./renderers/canvasRenderHelpers";

const THEMES = {
  light: {
    bg: 0xfaf8f5,
    node: 0xffffff,
    nodeStroke: 0xd5cec2,
    nodeText: 0x24201e,
    edge: 0x8c8273,
    grid: 0xe5e0da,
    annotation: 0x24201e,
    equation: 0xac4815,
    stackFrame: 0xffffff,
    stackFrameStroke: 0xa8a29e,
    studentInk: 0x1b365d,
    stroke: 0x24201e,
    highlight: 0xf59e0b,
    gridAlpha: 0.4,
  },
  dark: {
    bg: 0x000000,
    node: 0x111827,
    nodeStroke: 0x334155,
    nodeText: 0xf8fafc,
    edge: 0xcbd5e1,
    grid: 0x222222,
    annotation: 0xe2e8f0,
    equation: 0x7dd3fc,
    stackFrame: 0x111827,
    stackFrameStroke: 0x475569,
    studentInk: 0xf8fafc,
    stroke: 0xe2e8f0,
    highlight: 0xf59e0b,
    gridAlpha: 0.18,
  },
};

const COLORS = {
  highlight: 0xf59e0b,
};

const SCALE_X = 1;
const SCALE_Y = 1;

function resolveHexColor(value: string | number | null | undefined, fallback: number): number {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "number") {
    return (Number.isFinite(value) && !Number.isNaN(value)) ? value : fallback;
  }
  if (typeof value === "string") {
    const normalized = value.trim();
    if (normalized.startsWith("#")) {
      const parsed = Number.parseInt(normalized.slice(1), 16);
      if (!Number.isNaN(parsed)) return parsed;
    }
    if (normalized.startsWith("0x") || normalized.startsWith("0X")) {
      const parsed = Number.parseInt(normalized.slice(2), 16);
      if (!Number.isNaN(parsed)) return parsed;
    }
  }
  return fallback;
}

function PixiCanvas(): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const layersRef = useRef<Record<string, any>>({});
  const nodeMapRef = useRef<Record<string, any>>({});
  const studentGfxRef = useRef<Record<string, PIXI.Graphics>>({});
  const motionGfxRef = useRef<Record<string, PIXI.Graphics>>({});
  const gestureGfxRef = useRef<Record<string, PIXI.Graphics>>({});
  const nodeConstructionRef = useRef<Record<string, any>>({});
  const cursorMotionRef = useRef({ x: 0, y: 0, angle: 0.55, initialized: false, speed: 0 });
  const studentDrawingControllerRef = useRef<StudentDrawingController | null>(null);

  useEffect(() => {
    let mounted = true;
    let metricThrottleTimer = 0; // Throttling tracker allocation

    // Subscribe to boardTheme changes transiently to avoid React re-renders entirely
    const unsubscribe = useRuntimeStore.subscribe((state) => {
      if (!containerRef.current) return;
      const isDark = true;
      containerRef.current.style.background = isDark
        ? "#000000"
        : "#faf8f5";
    });

    // Fire immediately to set the initial background style on mount
    if (containerRef.current) {
      const isDark = true;
      containerRef.current.style.background = isDark
        ? "#000000"
        : "#faf8f5";
    }

    const init = async () => {
      const app = new PIXI.Application();
      await app.init({
        backgroundAlpha: 0,
        antialias: true,
        resolution: Math.min(window.devicePixelRatio || 1, 2), // Clamp higher retina displays down to maximum factor 2
        autoDensity: true,
        resizeTo: containerRef.current || undefined,
        eventMode: "passive"
      });

      if (!mounted) { app.destroy(true); return; }

      app.canvas.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;";
      containerRef.current?.appendChild(app.canvas);
      appRef.current = app;

      browserProfiler.auditPixiJSGPU(app);

      const gridGfx = new PIXI.Graphics();
      const edgeLayer = new PIXI.Container();
      const strokeLayer = new PIXI.Container();
      const mStrokeLayer = new PIXI.Container();
      const gestureLayer = new PIXI.Container();
      const nodeLayer = new PIXI.Container();
      const annLayer = new PIXI.Container();
      const studentLayer = new PIXI.Container();
      studentLayer.label = "studentLayer";
      const focusLayer = new PIXI.Container();
      const cursorLayer = new PIXI.Container();

      app.stage.addChild(gridGfx);
      app.stage.addChild(edgeLayer);
      app.stage.addChild(strokeLayer);
      app.stage.addChild(mStrokeLayer);
      app.stage.addChild(gestureLayer);
      app.stage.addChild(nodeLayer);
      app.stage.addChild(annLayer);
      app.stage.addChild(studentLayer);
      app.stage.addChild(focusLayer);
      app.stage.addChild(cursorLayer);

      const cursorGfx = new PIXI.Graphics();
      const cursorGlow = new PIXI.Graphics();
      const cursorTrail = new PIXI.Graphics();
      cursorLayer.addChild(cursorTrail);
      cursorLayer.addChild(cursorGlow);
      cursorLayer.addChild(cursorGfx);

      layersRef.current = {
        edgeLayer, nodeLayer, annLayer, strokeLayer, mStrokeLayer,
        gestureLayer, studentLayer, focusLayer, cursorLayer,
        cursorGfx, cursorGlow, cursorTrail, gridGfx
      };

      const studentDrawingController = new StudentDrawingController({
        app,
        boardWidth: 1200,
        boardHeight: 750,
      });
      studentDrawingController.attach();
      studentDrawingControllerRef.current = studentDrawingController;

      const BOARD_WIDTH = 1200;
      const BOARD_HEIGHT = 750;

      const drawGrid = () => {
        const state = useRuntimeStore.getState();
        const activeSceneId = state.activeSceneId || "scene_0";
        const viewedSceneId = state.viewedSceneId || activeSceneId;
        const isLive = (viewedSceneId === activeSceneId);
        const theme = THEMES.dark;

        drawBoardGrid(gridGfx, BOARD_WIDTH, BOARD_HEIGHT, isLive, theme);
      };
      drawGrid();
      app.renderer.on("resize", drawGrid);

      let lastMs = performance.now();
      let lastViewedId: string | null = null;
      let lastActiveId: string | null = null;

      app.ticker.add(() => {
        const now = performance.now();
        // Clamp to 100 ms max so tab-switch gaps or GC stalls don't flush
        // the entire event queue in one frame and overlap audio.
        const delta = Math.min(now - lastMs, 100);
        lastMs = now;

        pointerOwnership.tick(now);

        const state = useRuntimeStore.getState();
        state.tick(delta);

        // Insulated high frequency state metric updates from choking the React render tree
        metricThrottleTimer += delta;
        if (metricThrottleTimer >= 500) {
          state.setMetrics({ frameTime: delta });
          metricThrottleTimer = 0;
        }

        const curViewed = state.viewedSceneId || state.activeSceneId;
        const curActive = state.activeSceneId;
        if (curViewed !== lastViewedId || curActive !== lastActiveId) {
          drawGrid();
          lastViewedId = curViewed;
          lastActiveId = curActive;
        }

        renderScene(app, layersRef.current, now);
      });

    };

    init();

    return () => {
      mounted = false;
      studentDrawingControllerRef.current?.detach();
      studentDrawingControllerRef.current = null;
      unsubscribe();
      if (appRef.current) {
        appRef.current.destroy(true, { children: true, texture: true });
        appRef.current = null;
      }
      nodeMapRef.current = {};
      nodeConstructionRef.current = {};
    };
  }, []);

  const renderScene = (app: PIXI.Application, layers: Record<string, any>, nowMs: number) =>
    renderCanvasScene(app, layers, nowMs, {
      scaleX: SCALE_X,
      scaleY: SCALE_Y,
      themes: THEMES,
      colors: COLORS,
      boardWidth: 1200,
      boardHeight: 750,
      resolveHexColor,
      drawStackFrameProcedural,
      drawLegacyStroke,
      resolveStrokeStateForRender,
      clipPointsForReveal,
      centerStrokePoints,
      shouldDrawStrokeForTiming,
      nodeMapRef,
      nodeConstructionRef,
      studentGfxRef,
      motionGfxRef,
      gestureGfxRef,
      cursorMotionRef,
    });

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 transition-all duration-500"
    />
  );
}

export default React.memo(PixiCanvas);
