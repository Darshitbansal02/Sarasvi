"use client";

import {
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
  memo,
} from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Pause,
  Play,
  Pen,
  Eraser,
  Maximize2,
  Minimize2,
  ChevronLeft,
  ChevronRight,
  Activity,
  LogOut,
  RotateCcw,
  SkipBack,
  SkipForward,
  Paperclip,
  X,
  Loader2,
  MessageSquare,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import dynamic from "next/dynamic";
import { CleanPreview } from "@/components/ui/CleanPreview";

const PixiCanvas = memo(
  dynamic(
    () => import("@/components/canvas/PixiCanvas"),
    {
      ssr: false,
      loading: () => (
        <div className="w-full h-full bg-canvas animate-pulse flex items-center justify-center text-muted-foreground font-mono text-sm">
          {t("initializing pedagogical space…")}
        </div>
      ),
    }
  )
);

import {
  useRuntimeStore,
  RUNTIME_STATES,
} from "@/runtime/runtimeStore";
import { sceneManager } from "@/runtime/sceneManager";
import { toast } from "sonner";
import { MotionWSClient } from "@/lib/wsClient";
import { interruptSession, teachTopic, sendInteractionSignal } from "@/lib/api_sessions";
import { audioTimeline, AUDIO_TIMELINE_STATE } from "@/runtime/audio/audioTimeline";
import { ttsPlayer } from "@/runtime/audio/ttsPlayer";
import { teacherMotor } from "@/runtime/motion/teacherMotor";
import SessionSidebar from "@/components/session/SessionSidebar";
import PedagogyPanel from "@/components/session/PedagogyPanel";
import CheckpointOverlay from "@/components/session/CheckpointOverlay";
import { cn } from "@/lib/utils";
import { GeneratingSessionLoader } from "@/components/ui/GeneratingSessionLoader";

const EMPTY_ARRAY: any[] = [];

function ElapsedTimer({ startedAt, isRunning }: { startedAt: number; isRunning: boolean }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!isRunning) return;
    const timerId = setInterval(() => {
      setElapsed(Date.now() - startedAt);
    }, 500);
    return () => clearInterval(timerId);
  }, [isRunning, startedAt]);

  const elapsedSec = Math.floor(elapsed / 1000);
  const elapsedMin = Math.floor(elapsedSec / 60);
  const elapsedRemSec = elapsedSec % 60;

  return (
    <span className="text-xs font-mono text-muted-foreground tabular-nums min-w-[32px] text-center">
      {elapsedMin}:{String(elapsedRemSec).padStart(2, '0')}
    </span>
  );
}

const t = (key: string) => key;

export default function LiveSession() {
  const params = useParams();
  const id = params.id as string;
  const searchParams = useSearchParams();
  const topic = searchParams.get("topic") || "Recursion";
  const lang = searchParams.get("lang") || "en-US";
  const router = useRouter();

  const wsClientRef = useRef<MotionWSClient | null>(null);
  const startedAtRef = useRef<number>(Date.now());
  const audioInitRef = useRef<boolean>(false);
  const wasPlayingRef = useRef<boolean>(false);

  const runtimeState = useRuntimeStore((s) => s.runtimeState);
  const scenes = useRuntimeStore((s) => s.scenes || EMPTY_ARRAY);
  // Real "lesson is on the board" signal — counts actual rendered objects, not
  // raw events (control events like session_init must NOT dismiss the loader).
  const hasBoardContent = useRuntimeStore((s) => Object.keys(s.sceneObjects).length > 0);
  const viewedSceneId = useRuntimeStore((s) => s.viewedSceneId);
  const activeSceneId = useRuntimeStore((s) => s.activeSceneId);
  const interactionTool = useRuntimeStore((s) => s.interactionTool);
  const setInteractionTool = useRuntimeStore((s) => s.setInteractionTool);
  const errorMessage = useRuntimeStore((s) => s.errorMessage);
  const storeSessionId = useRuntimeStore((s) => s.sessionId);
  const hasArtifact = useRuntimeStore((s) => !!s.pedagogicalPlan?.compiled_artifact);

  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState([70]);
  const [interrupting, setInterrupting] = useState(false);
  const [showInterruptModal, setShowInterruptModal] = useState(false);
  const [modalPlaceholder, setModalPlaceholder] = useState("Ask what you don't understand...");
  const [modalTitle, setModalTitle] = useState("Ask a Doubt");
  const [modalInputText, setModalInputText] = useState("");
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const [attachedPreview, setAttachedPreview] = useState<string | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);
  const hasStartedRef = useRef<boolean>(false);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setAttachedFile(file);
      const url = URL.createObjectURL(file);
      setAttachedPreview(url);
    }
  };

  const handleRemoveFile = () => {
    if (attachedPreview) {
      URL.revokeObjectURL(attachedPreview);
    }
    setAttachedFile(null);
    setAttachedPreview(null);
  };

  const handleModalPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData.items;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf("image") !== -1) {
        const file = items[i].getAsFile();
        if (file) {
          e.preventDefault();
          setAttachedFile(file);
          const url = URL.createObjectURL(file);
          setAttachedPreview(url);
          toast.success("Image pasted successfully!");
          break;
        }
      }
    }
  };

  useEffect(() => {
    return () => {
      if (attachedPreview) {
        URL.revokeObjectURL(attachedPreview);
      }
    };
  }, [attachedPreview]);

  const [isFullscreen, setIsFullscreen] = useState(false);

  const lastStudentGesture = useRuntimeStore((s: any) => s.lastStudentGesture);

  useEffect(() => {
    if (lastStudentGesture) {
      const rawType: string = lastStudentGesture.target_type || "area";
      const isEq = rawType === "equation" || rawType === "equation_write";
      const isAnnotation = rawType === "annotation";
      const typeStr = isEq ? "equation" : isAnnotation ? "annotation" : rawType === "area" ? "board area" : "diagram";
      setModalTitle(`Doubt about ${typeStr}`);
      setModalPlaceholder(
        lastStudentGesture.target_id
          ? `What don't you understand about this ${typeStr}?`
          : `What don't you understand about this area?`
      );
      setModalInputText("");
      setShowInterruptModal(true);
    }
  }, [lastStudentGesture]);

  const canvasElement = useMemo(() => <PixiCanvas />, []);

  const initAudio = useCallback(async () => {
    if (audioInitRef.current) return;
    audioInitRef.current = true;
    try {
      await audioTimeline.init();
      const currentStore = useRuntimeStore.getState();
      if ('setTTSVolume' in currentStore && typeof currentStore.setTTSVolume === 'function') {
        (currentStore.setTTSVolume as (v: number) => void)(muted ? 0 : volume[0] / 100);
      }
    } catch (err) {
      console.warn("[Page] Audio init failed:", err);
    }
  }, [muted, volume]);

  useEffect(() => {
    initAudio();
  }, [initAudio]);

  useEffect(() => {
    const resumeAudio = async () => {
      const ctx = (audioTimeline as any)._audioContext as AudioContext | null;
      if (ctx && ctx.state === "suspended") {
        try {
          await ctx.resume();
        } catch (e) {
          // Retry
        }
      }
      if (ctx && ctx.state === "running") {
        window.removeEventListener("click", resumeAudio, true);
        window.removeEventListener("keydown", resumeAudio, true);
        window.removeEventListener("touchstart", resumeAudio, true);
      }
    };
    window.addEventListener("click", resumeAudio, true);
    window.addEventListener("keydown", resumeAudio, true);
    window.addEventListener("touchstart", resumeAudio, true);
    return () => {
      window.removeEventListener("click", resumeAudio, true);
      window.removeEventListener("keydown", resumeAudio, true);
      window.removeEventListener("touchstart", resumeAudio, true);
    };
  }, []);

  useEffect(() => {
    const handleVisibilityChange = () => {
      const store = useRuntimeStore.getState();
      const state = store.runtimeState;
      const isCurrentlyActive = (
        state === RUNTIME_STATES.STREAMING ||
        state === RUNTIME_STATES.REPLAYING ||
        state === RUNTIME_STATES.REMEDIATING
      );

      if (document.hidden) {
        if (isCurrentlyActive && audioTimeline.state === AUDIO_TIMELINE_STATE.PLAYING) {
          console.info("[SessionPage] Tab backgrounded, auto-pausing audio clock.");
          wasPlayingRef.current = true;
          audioTimeline.pause();
          ttsPlayer.pause();
          teacherMotor.pause();
        }
      } else {
        if (wasPlayingRef.current) {
          console.info("[SessionPage] Tab focused, auto-resuming audio clock.");
          wasPlayingRef.current = false;
          audioTimeline.resume();
          ttsPlayer.resume();
          teacherMotor.resume();
        }
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  useEffect(() => {
    if (!id) return;

    const store = useRuntimeStore.getState();
    store.reset();
    store.initSession(id);
    store.setState(RUNTIME_STATES.CONNECTING);
    useRuntimeStore.setState({ sessionTopic: topic });
    startedAtRef.current = Date.now();
    hasStartedRef.current = false;
    setConnectionLost(false);

    const wsClient = new MotionWSClient();
    wsClient.connect(id, {
      onopen: () => {
        const currentStore = useRuntimeStore.getState();
        currentStore.setState(RUNTIME_STATES.STREAMING);
        setConnectionLost(false);
        // Only kick off lesson synthesis on the FIRST connection. A reconnect
        // must not re-call /teach — that would cancel and restart the whole
        // lesson from scratch.
        if (hasStartedRef.current) return;
        hasStartedRef.current = true;
        teachTopic(id, topic).catch((err) => {
          console.error("Failed to start lesson", err);
          toast.error("Failed to start lesson synthesis.");
        });
      },
      onMotionEvent: (evt) => { useRuntimeStore.getState().ingestEvent(evt); },
      onBufferedEvent: (evt) => { useRuntimeStore.getState().ingestEvent(evt); },
      onclose: () => {
        const currentStore = useRuntimeStore.getState();
        if (currentStore.runtimeState === RUNTIME_STATES.STREAMING ||
          currentStore.runtimeState === RUNTIME_STATES.CONNECTING ||
          currentStore.runtimeState === RUNTIME_STATES.INTERRUPTING) {
          setConnectionLost(true);
        }
      },
      onerror: () => {
        const metrics = wsClient.getMetrics();
        if (metrics.reconnectAttempts >= 3) {
          useRuntimeStore.getState().setState(RUNTIME_STATES.ERROR);
          toast.error("WebSocket connection failed.");
        }
      },
      onServerClock: () => { },
    });
    wsClientRef.current = wsClient;

    return () => {
      wsClient.close();
    };
  }, [id, topic]);

  const handleInterrupt = useCallback(async (text: string) => {
    if (interrupting || !id) return;
    setInterrupting(true);
    try {
      const store = useRuntimeStore.getState();
      const gesture = store.lastStudentGesture;
      const rawStrokes = store.studentStrokes || [];
      const viewedSceneId = store.viewedSceneId || store.activeSceneId || "scene_0";

      // If the student paged back to a past scene before asking, tell the
      // backend which page they're looking at so the answer is anchored to that
      // page's content (the backend reads snapshot.viewed_page_context).
      const viewedScene = store.scenes.find((sc: any) => sc.scene_id === viewedSceneId);
      const viewedPageContext = viewedScene
        ? {
          label: viewedScene.label,
          page_index: store.scenes.findIndex((sc: any) => sc.scene_id === viewedSceneId),
          concept: viewedScene.concept,
        }
        : null;

      // Filter strokes belonging to the current page/scene
      const currentStrokes = rawStrokes.filter(
        (s: any) => (s.sceneId || "scene_0") === viewedSceneId
      );

      // Downsample coordinates to prevent token bloat
      const processedStrokes = currentStrokes.map((s: any) => {
        const path = s.path || [];
        const downsampledPath = path.filter((_: any, idx: number) => idx % 5 === 0);
        // Include last point if we skipped it
        if (path.length > 0 && (path.length - 1) % 5 !== 0) {
          downsampledPath.push(path[path.length - 1]);
        }

        // Compute bounding box
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        path.forEach(([x, y]: [number, number]) => {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        });

        return {
          id: s.id,
          color: s.color,
          path: downsampledPath,
          bounds: minX !== Infinity ? { minX, maxX, minY, maxY } : null,
        };
      });

      const rawSnapshot = await sceneManager.takeSnapshot(store);
      const snapshot = rawSnapshot ? {
        ...rawSnapshot,
        student_strokes: processedStrokes.length > 0 ? processedStrokes : undefined,
        viewed_page_context: viewedPageContext || undefined,
      } : (processedStrokes.length > 0 || viewedPageContext ? {
        student_strokes: processedStrokes.length > 0 ? processedStrokes : undefined,
        viewed_page_context: viewedPageContext || undefined,
      } : undefined);

      await interruptSession(
        id,
        text,
        gesture || undefined,
        snapshot || undefined,
        null,
        attachedFile
      );

      // Only record the signal after the interrupt actually succeeded
      sendInteractionSignal(id, "session_interrupt", {}, "general");

      store.setState(RUNTIME_STATES.INTERRUPTING);
      store.clearStudentStrokes();

      toast.success("Sarasvi is analyzing your doubt…");
      setModalInputText("");
      handleRemoveFile();
      setShowInterruptModal(false);
      useRuntimeStore.setState({ lastStudentGesture: null });
    } catch (err) {
      toast.error("Failed to process doubt.");
    } finally {
      setInterrupting(false);
    }
  }, [id, interrupting, attachedFile]);

  const handleInterruptClick = useCallback(() => {
    setModalTitle("Ask a Doubt");
    setModalPlaceholder("Type what you don't understand...");
    setModalInputText("");
    setShowInterruptModal(true);
  }, []);

  const handleFullscreenToggle = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().then(() => {
        setIsFullscreen(true);
      }).catch((err) => {
        toast.error(`Error enabling fullscreen: ${err.message}`);
      });
    } else {
      document.exitFullscreen().then(() => {
        setIsFullscreen(false);
      });
    }
  };

  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFsChange);
    return () => document.removeEventListener("fullscreenchange", handleFsChange);
  }, []);

  useEffect(() => {
    const handler = (e: Event) => {
      wsClientRef.current?.send((e as CustomEvent).detail);
    };
    window.addEventListener("runtime:send-ws-message", handler);
    return () => window.removeEventListener("runtime:send-ws-message", handler);
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") router.push("/dashboard");
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router]);

  const currentPageIndex = useMemo(() =>
    scenes.findIndex((s) => s.scene_id === (viewedSceneId || activeSceneId)),
    [scenes, viewedSceneId, activeSceneId]
  );

  const totalPages = Math.max(1, scenes.length);
  const currentPage = Math.max(1, currentPageIndex + 1);
  const isRunning = runtimeState === RUNTIME_STATES.STREAMING;

  return (
    <div
      className="w-full h-screen bg-background flex relative overflow-hidden"
      role="main"
    >
      {runtimeState !== RUNTIME_STATES.ERROR && (
        <GeneratingSessionLoader
          topic={topic}
          language={lang}
          sessionId={id}
          isReady={storeSessionId === id && hasArtifact && (scenes.length > 0 || hasBoardContent)}
        />
      )}

      {/* Reconnecting banner — shown while the WS drops and auto-retries. */}
      {connectionLost && runtimeState !== RUNTIME_STATES.ERROR && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2.5 bg-card border border-status-paused/40 text-status-paused rounded-full pl-3 pr-4 py-1.5 shadow-lg">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span className="text-xs font-mono">Connection lost — reconnecting…</span>
        </div>
      )}

      {/* Terminal connection failure — give the student a way out, not a blank board. */}
      {runtimeState === RUNTIME_STATES.ERROR && (
        <div className="absolute inset-0 z-[60] bg-background/95 backdrop-blur-sm flex items-center justify-center">
          <div className="text-center max-w-sm px-6">
            <h3 className="font-display text-xl tracking-tight text-foreground">
              {errorMessage ? "Lesson generation failed" : "Connection failed"}
            </h3>
            <p className="text-sm text-muted-foreground mt-2">
              {errorMessage || "We couldn't reach the lesson server. Check your connection and try again."}
            </p>
            <div className="flex items-center justify-center gap-2 mt-6">
              <Button onClick={() => window.location.reload()} className="premium-gradient text-primary-foreground">
                <RotateCcw className="h-4 w-4 mr-2" /> Retry
              </Button>
              <Button variant="outline" onClick={() => router.push("/dashboard")}>
                Back to dashboard
              </Button>
            </div>
          </div>
        </div>
      )}

      <SessionSidebar
        topic={topic}
        muted={muted}
        volume={volume}
        onMuteToggle={() => setMuted(!muted)}
        onVolumeChange={setVolume}
        startedAt={startedAtRef.current}
      />

      {/* Center Whiteboard Space */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-background">
        {/* ── Top Bar ─────────────────────────────────────────────── */}
        <div className="h-11 bg-card border-b border-border/60 flex items-center justify-between px-3 shrink-0 shadow-sm">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/dashboard")}
              className="h-7 px-2.5 rounded-sm border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-surface-hover flex items-center gap-1.5 text-[10px] font-mono tracking-wide"
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Dashboard
            </Button>

            <div className="flex items-center gap-1.5 bg-primary/8 border border-primary/20 rounded-sm px-2.5 py-1 text-[9px] font-mono tracking-widest font-bold">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              <span className="text-primary uppercase">{runtimeState}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-0.5 bg-background border border-border rounded-sm px-1 py-0.5">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 rounded text-muted-foreground hover:text-foreground hover:bg-surface-hover"
                onClick={() => {
                  const prevScene = scenes.at(currentPageIndex - 1);
                  if (prevScene) useRuntimeStore.getState().pinViewedScene(prevScene.scene_id);
                }}
                disabled={currentPageIndex <= 0}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <span className="text-[9px] font-mono font-bold text-foreground px-2 tabular-nums">
                {currentPage} / {totalPages}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 rounded text-muted-foreground hover:text-foreground hover:bg-surface-hover"
                onClick={() => {
                  const nextScene = scenes.at(currentPageIndex + 1);
                  if (nextScene) {
                    if (nextScene.scene_id === activeSceneId) {
                      useRuntimeStore.getState().unpinViewedScene();
                    } else {
                      useRuntimeStore.getState().pinViewedScene(nextScene.scene_id);
                    }
                  }
                }}
                disabled={currentPageIndex >= scenes.length - 1}
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={handleFullscreenToggle}
              className="h-7 w-7 p-0 rounded-sm border border-border bg-background text-muted-foreground hover:text-primary hover:border-primary/30 hover:bg-surface-hover transition-all"
              title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            >
              {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            </Button>
          </div>
        </div>

        {/* ── Canvas (fills remaining space) ───────────────────────── */}
        <div className="flex-1 bg-[#1a1a1a] flex flex-col overflow-hidden">
          <div className="w-full h-full relative overflow-hidden bg-canvas shadow-[inset_0_0_60px_rgba(0,0,0,0.4)]">
            {canvasElement}
            <CheckpointOverlay />
          </div>
        </div>

        {/* ── Bottom Control Bar ───────────────────────────────────── */}
        <div className="h-14 flex items-center justify-center bg-card border-t border-border/60 shrink-0 relative px-4 shadow-[0_-2px_12px_rgba(0,0,0,0.04)]">
          {/* Centered control pill strip */}
          <div className="flex items-center gap-1.5 bg-background border border-border rounded-sm px-2 py-1.5 shadow-md">

            {/* Drawing tools */}
            <button
              onClick={() => setInteractionTool("pen")}
              className={cn(
                "h-8 w-8 rounded-sm flex items-center justify-center transition-all duration-150",
                interactionTool === "pen"
                  ? "bg-primary text-primary-foreground shadow-md shadow-primary/20"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
              title="Pen Tool"
            >
              <Pen className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setInteractionTool("eraser")}
              className={cn(
                "h-8 w-8 rounded-sm flex items-center justify-center transition-all duration-150",
                interactionTool === "eraser"
                  ? "bg-primary text-primary-foreground shadow-md shadow-primary/20"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
              title="Eraser Tool"
            >
              <Eraser className="h-3.5 w-3.5" />
            </button>

            <div className="w-px h-5 bg-border mx-0.5" />

            {/* Page navigation */}
            <button
              onClick={() => {
                const prevScene = scenes.at(currentPageIndex - 1);
                if (prevScene) useRuntimeStore.getState().pinViewedScene(prevScene.scene_id);
              }}
              disabled={currentPageIndex <= 0}
              className="h-8 w-8 rounded-sm flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 transition-all"
              title="Previous Page"
            >
              <SkipBack className="h-3.5 w-3.5" />
            </button>

            <button
              onClick={() => {
                const nextScene = scenes.at(currentPageIndex + 1);
                if (nextScene) {
                  if (nextScene.scene_id === activeSceneId) {
                    useRuntimeStore.getState().unpinViewedScene();
                  } else {
                    useRuntimeStore.getState().pinViewedScene(nextScene.scene_id);
                  }
                }
              }}
              disabled={currentPageIndex >= scenes.length - 1}
              className="h-8 w-8 rounded-sm flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 transition-all"
              title="Next Page"
            >
              <SkipForward className="h-3.5 w-3.5" />
            </button>

            <button
              onClick={() => {
                const xTarget = currentPageIndex * 1200;
                useRuntimeStore.setState({ camera: { x: xTarget, y: 0, zoom: 1 } });
                toast.info("Camera reset");
              }}
              className="h-8 w-8 rounded-sm flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-all"
              title="Reset Camera"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>

            <div className="w-px h-5 bg-border mx-0.5" />

            {/* Play/Pause + Timer */}
            <button
              onClick={() => useRuntimeStore.getState().togglePlayback()}
              className={cn(
                "h-8 px-3 rounded-sm flex items-center justify-center gap-1.5 text-[10px] font-mono font-bold tracking-wider transition-all duration-150",
                isRunning
                  ? "text-foreground hover:bg-muted hover:text-foreground"
                  : "text-primary hover:bg-primary/10"
              )}
              title={isRunning ? "Pause" : "Resume"}
            >
              {isRunning ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              <span>{isRunning ? "LIVE" : "PAUSED"}</span>
            </button>

            <div className="w-px h-5 bg-border mx-0.5" />

            {/* Ask Question (Visible only on mobile/tablet) */}
            <button
              onClick={handleInterruptClick}
              className="h-8 px-2.5 rounded-sm flex lg:hidden items-center justify-center gap-1.5 bg-primary text-primary-foreground font-mono font-bold text-[9px] tracking-wider transition-all duration-150 active:scale-[0.97]"
              title="Ask a Question"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              <span>ASK</span>
            </button>

            <div className="lg:hidden w-px h-5 bg-border mx-0.5" />

            <ElapsedTimer startedAt={startedAtRef.current} isRunning={isRunning} />
          </div>

        </div>
      </div>

      <PedagogyPanel onInterrupt={handleInterruptClick} />

      <AnimatePresence>
        {showInterruptModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95, y: 15 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.95, y: 15 }}
              transition={{ type: "spring", duration: 0.35, bounce: 0.15 }}
              className="w-full max-w-md bg-card border border-border rounded-lg p-6 shadow-2xl relative"
            >
              <h3 className="font-display text-lg font-bold text-foreground mb-1.5">
                {modalTitle}
              </h3>
              <p className="text-xs text-muted-foreground mb-4">
                Ask your question and Sarasvi will pivot the lesson to explain it.
              </p>

              <textarea
                value={modalInputText}
                onChange={(e) => setModalInputText(e.target.value)}
                onPaste={handleModalPaste}
                onKeyDown={(e) => {
                  // Ctrl+Enter or Cmd+Enter submits the form
                  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                    e.preventDefault();
                    if ((modalInputText.trim() || attachedFile) && !interrupting) {
                      handleInterrupt(modalInputText);
                    }
                  }
                }}
                placeholder={modalPlaceholder}
                className="w-full h-24 bg-background border border-border rounded-sm p-3.5 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary transition-all resize-none font-sans font-medium"
                autoFocus
              />

              {attachedPreview && (
                <div className="relative mt-2 border border-border rounded-sm overflow-hidden max-h-32 bg-muted/20 flex items-center justify-center">
                  <img src={attachedPreview} className="max-h-28 object-contain" alt="Attached preview" />
                  <button
                    onClick={handleRemoveFile}
                    className="absolute top-1.5 right-1.5 h-5 w-5 rounded-full bg-black/60 hover:bg-black/80 flex items-center justify-center text-white transition-colors"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              )}

              {modalInputText.trim() && (
                <div className="mt-3 max-h-48 overflow-y-auto">
                  <CleanPreview text={modalInputText} />
                </div>
              )}

              <div className="flex items-center justify-between mt-4">
                <div className="flex items-center">
                  <label className="cursor-pointer text-muted-foreground hover:text-primary transition-colors flex items-center justify-center p-2 rounded-sm hover:bg-muted/50" title="Attach an image">
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={handleFileChange}
                    />
                    <Paperclip className="h-4 w-4" />
                  </label>
                  {attachedFile && (
                    <span className="text-[10px] font-mono text-muted-foreground ml-1.5 max-w-[150px] truncate">
                      {attachedFile.name}
                    </span>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      handleRemoveFile();
                      setShowInterruptModal(false);
                      useRuntimeStore.setState({ lastStudentGesture: null });
                    }}
                    className="text-muted-foreground hover:text-foreground rounded-sm text-xs font-mono h-9 px-3"
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    disabled={(!modalInputText.trim() && !attachedFile) || interrupting}
                    onClick={() => handleInterrupt(modalInputText)}
                    className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-sm font-display text-xs font-bold shadow-md shadow-[#F9A01B]/15 px-4 h-9 active:scale-[0.98] transition-all"
                  >
                    {interrupting ? "Analyzing..." : "Ask Question"}
                  </Button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}