"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Play,
  Pause,
  RotateCcw,
  SkipForward,
  Share2,
  Volume2,
  VolumeX,
  Volume1,
  MessageSquare,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import dynamic from "next/dynamic";

const PixiCanvas = dynamic(
  () => import("@/components/canvas/PixiCanvas"),
  { ssr: false }
);

import { getSessionEvents } from "@/lib/api_sessions";
import {
  useRuntimeStore,
  RUNTIME_STATES,
} from "@/runtime/runtimeStore";
import { ttsPlayer } from "@/runtime/audio/ttsPlayer";
import { audioTimeline } from "@/runtime/audio/audioTimeline";
import { audioEventBridge } from "@/runtime/audio/audioEventBridge";
import { teacherMotor } from "@/runtime/motion/teacherMotor";
import { CleanPreview } from "@/components/ui/CleanPreview";
import {
  getPedagogicalWriteMode,
  resolvePedagogicalBoardId,
  shouldPatchBoard,
} from "@/runtime/motion/derivationBoard";
import { toast } from "sonner";

interface SessionEvent {
  type: string;
  start_ms: number;
  payload?: {
    text?: string;
    estimated_duration_ms?: number;
    duration_ms?: number;
    [key: string]: any;
  };
  [key: string]: any;
}

export default function Replay() {
  const params = useParams();
  const id = params.id as string;
  const searchParams = useSearchParams();
  const topic = searchParams.get("topic") || "Recursion";
  const router = useRouter();

  const eventsRef = useRef<SessionEvent[]>([]);
  const planRef = useRef<any>(null);

  const [loading, setLoading] = useState(true);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState([70]);

  // Read central synchronized runtime clock and state from Zustand store
  const currentTimeMs = useRuntimeStore((s) => s.currentTimeMs);
  const runtimeState = useRuntimeStore((s) => s.runtimeState);
  const transcript = useRuntimeStore((s) => s.transcript || []);
  const playbackRate = useRuntimeStore((s) => s.playbackRate || 1.0);
  const activeSceneId = useRuntimeStore((s) => s.activeSceneId);

  const setRtState = useRuntimeStore((s) => s.setState);
  const resetRuntime = useRuntimeStore((s) => s.reset);
  const setTTSRate = useRuntimeStore((s: any) => s.setTTSRate);
  const setTTSVolume = useRuntimeStore((s: any) => s.setTTSVolume);

  const isPlaying = runtimeState === RUNTIME_STATES.REPLAYING;

  const canvasElement = useMemo(() => <PixiCanvas />, []);

  // Fetch session events from backend
  useEffect(() => {
    if (!id) return;
    
    resetRuntime();
    let mounted = true;

    (async () => {
      try {
        setLoading(true);
        // Initialize teacherMotor for this session replay
        await teacherMotor.init({ sessionId: id });
        
        const resp = await getSessionEvents(id);
        if (!mounted) return;

        eventsRef.current = Array.isArray(resp.events) ? resp.events : [];
        
        if (eventsRef.current.length > 0) {
          // Sort events chronologically
          eventsRef.current.sort((a, b) => (a.start_ms || 0) - (b.start_ms || 0));

          // Save plan/artifact
          const genStart = eventsRef.current.find(e => e.type === "generation_start");
          if (genStart?.payload) {
            planRef.current = genStart.payload;
            if (genStart.payload.compiled_artifact) {
              teacherMotor.runtime.setCompiledArtifact(genStart.payload.compiled_artifact);
              useRuntimeStore.setState({
                pedagogicalPlan: {
                  compiled_artifact: genStart.payload.compiled_artifact
                }
              });
            }
          }

          // Calculate total duration
          const lastEvent = eventsRef.current[eventsRef.current.length - 1];
          const total = (lastEvent.start_ms ?? 0) +
            (lastEvent.payload?.estimated_duration_ms ||
              lastEvent.payload?.duration_ms ||
              2000);
          setDuration(total);

          // Seed the store with initial values
          useRuntimeStore.setState({
            eventQueue: eventsRef.current.slice(),
            generationId: eventsRef.current[0]?.generation_id || null,
            playbackRate: 1.0,
          });

          // Seek to start
          seekToTime(0);
        } else {
          setDuration(1000);
        }

        setLoading(false);
      } catch (err) {
        console.error("replay load failed", err);
        toast.error("Failed to load events for replay");
        setLoading(false);
      }
    })();

    return () => {
      mounted = false;
      ttsPlayer.stop();
      audioTimeline.reset();
      resetRuntime();
    };
  }, [id]);

  // Sync mute / volume changes into the ttsPlayer backend
  useEffect(() => {
    setTTSVolume(muted ? 0 : volume[0] / 100);
  }, [muted, volume, setTTSVolume]);

  // Reconstruct the exact whiteboard state at target time
  const seekToTime = (targetMs: number) => {
    // 1. Clamp time and stop existing voice playback
    const seekTime = Math.max(0, Math.min(targetMs, duration));
    ttsPlayer.stop();
    audioTimeline.reset();

    // 2. Separate past and future events
    const evts = eventsRef.current;
    const pastEvents = evts.filter((e) => (e.start_ms || 0) <= seekTime);
    const futureEvents = evts.filter((e) => (e.start_ms || 0) > seekTime);

    // 3. Reset motor runtime synchronously (to avoid asynchronous init races)
    audioEventBridge.reset();
    teacherMotor.runtime.reset();
    teacherMotor.runtime.start();
    audioEventBridge.connect({
      temporalScheduler: teacherMotor.runtime.temporalScheduler as any,
      narrationSync: teacherMotor.runtime.narrationSync,
      cursorActor: teacherMotor.runtime.cursor,
      strokeScheduler: teacherMotor.runtime.strokeScheduler,
    });
    teacherMotor.setPlaybackRate(playbackRate);

    // 4. Reconstruct board object state (sceneObjects)
    const objs: Record<string, any> = {};
    const transcriptEntries: { t: number; who: string; text: string }[] = [];
    const scenes: any[] = [];
    let currentActiveSceneId = "scene_0";
    let activeCompiledArtifact = planRef.current?.compiled_artifact || null;

    for (const evt of pastEvents) {
      if (evt.type === "generation_start") {
        activeCompiledArtifact = evt.payload?.compiled_artifact || activeCompiledArtifact;
      }

      if (evt.payload) {
        if (evt.type === "speech") {
          transcriptEntries.push({
            t: evt.start_ms || 0,
            who: "Sarasvi",
            text: evt.payload.text || ""
          });
        }
        
        if (evt.type === "scene_start") {
          currentActiveSceneId = `scene_${evt.payload.scene_index}`;
          const existingScene = scenes.find(s => s.scene_id === currentActiveSceneId);
          if (!existingScene) {
            scenes.push({
              scene_id: currentActiveSceneId,
              label: evt.payload.label || `Page ${evt.payload.scene_index + 1}`,
              concept: evt.payload.concept || "Concept",
              confusion_level: 0,
              timeline_offset: evt.start_ms || 0,
              camera_x: evt.payload.camera_x || (evt.payload.scene_index * 1280),
            });
          }
        }

        // Enrich stroke reveals with placement coordinates
        if (evt.type === "stroke_reveal") {
          const objId = evt.payload?.object_id;
          if (activeCompiledArtifact?.layout_assets?.[objId]) {
            const asset = activeCompiledArtifact.layout_assets[objId];
            evt.payload = {
              ...evt.payload,
              latex: evt.payload?.latex || asset.latex,
              text: evt.payload?.text || asset.text,
              position: evt.payload?.position || { x: asset.x, y: asset.y },
              width: evt.payload?.width || asset.width,
              height: evt.payload?.height || asset.height,
            };
          }
        }

        // Apply drawing/whiteboard updates
        if (evt.type === "draw_stroke" || evt.type === "equation_write" || evt.type === "stroke_reveal") {
          const eqId = evt.payload?.equation_id || evt.payload?.stroke_id || evt.payload?.object_id || `auto_${evt.type}`;
          const patchBoard = evt.type === "equation_write" && shouldPatchBoard(evt.payload || {}, eqId);
          const objId = patchBoard ? resolvePedagogicalBoardId(evt.payload || {}, eqId) : eqId;
          const pgIndex = parseInt(currentActiveSceneId.split("_")[1]) || 0;

          const existingObj = objs[objId];
          if (existingObj) {
            objs[objId] = {
              ...existingObj,
              type: evt.type,
              width: evt.payload?.width ?? existingObj.width,
              height: evt.payload?.height ?? existingObj.height,
              data: { ...existingObj.data, ...evt.payload, board_id: evt.payload?.board_id || objId },
              sceneId: existingObj.sceneId || currentActiveSceneId,
              pageIndex: existingObj.pageIndex ?? pgIndex,
            };
            if (patchBoard) {
              const writeMode = getPedagogicalWriteMode(evt.payload || {});
              let nextLatex = evt.payload?.latex || "";
              if (writeMode === "append" && existingObj._mergedLatex) {
                nextLatex = existingObj._mergedLatex + " " + nextLatex;
              }
              const stepId = evt.payload?.object_id || eqId;
              const currentStepIds = existingObj._boardStepIds || [];
              const nextStepIds = currentStepIds.includes(stepId) ? currentStepIds : [...currentStepIds, stepId];
              objs[objId]._mergedLatex = nextLatex;
              objs[objId]._boardStepIds = nextStepIds;
              objs[objId]._boardId = objId;
            }
          } else {
            const nextObj: any = {
              id: objId, type: evt.type, data: evt.payload,
              position: evt.payload?.position || { x: 0, y: 0 },
              width: evt.payload?.width, height: evt.payload?.height,
              visible: true, opacity: 1, scale: 1,
              startMs: evt.start_ms ?? 0,
              sceneId: currentActiveSceneId,
              pageIndex: pgIndex,
              _inkAuthority: evt.type === "draw_stroke" ? "motion" : "static",
              _boardId: evt.payload?.board_id || evt.payload?.derivation_id || objId,
              _boardRole: evt.payload?.board_role || evt.payload?.metadata?.board_role,
              _writeMode: evt.payload?.write_mode || evt.payload?.metadata?.write_mode,
            };
            if (patchBoard) {
              const nextLatex = evt.payload?.latex || "";
              const stepId = evt.payload?.object_id || eqId;
              nextObj._mergedLatex = nextLatex;
              nextObj._boardStepIds = [stepId];
              nextObj._boardId = objId;
            }
            objs[objId] = nextObj;
          }
        }

        if (evt.type === "scene_mutation") {
          for (const m of (evt.payload?.mutations || [])) {
            if (m.action === "CREATE_OBJECT") {
              objs[m.id] = {
                id: m.id, type: m.type, data: m.data,
                position: m.position, visible: true,
                width: m.width, height: m.height,
                opacity: 1, scale: 1, _fadeTarget: 1,
                startMs: evt.start_ms ?? 0,
                sceneId: currentActiveSceneId,
                pageIndex: parseInt(currentActiveSceneId.split("_")[1]) || 0
              };
            } else if (m.action === "UPDATE_OBJECT") {
              if (objs[m.id]) {
                objs[m.id] = { ...objs[m.id], ...m.updates };
              }
            } else if (m.action === "DELETE_OBJECT") {
              if (objs[m.id]) {
                delete objs[m.id];
              }
            }
          }
        }
      }
    }

    // 5. Update the store with our reconstructed state
    useRuntimeStore.setState({
      currentTimeMs: seekTime,
      eventQueue: futureEvents,
      sceneObjects: objs,
      transcript: transcriptEntries,
      scenes,
      activeSceneId: currentActiveSceneId,
      viewedSceneId: currentActiveSceneId,
    });
  };

  const handlePlayPause = () => {
    if (isPlaying) {
      setRtState(RUNTIME_STATES.PAUSED);
      ttsPlayer.pause();
      audioTimeline.pause();
      teacherMotor.pause();
    } else {
      setRtState(RUNTIME_STATES.REPLAYING);
      ttsPlayer.resume();
      audioTimeline.resume();
      teacherMotor.resume();
    }
  };

  const handleProgressChange = (values: number[]) => {
    seekToTime(values[0]);
    if (isPlaying) {
      setRtState(RUNTIME_STATES.PAUSED);
    }
  };

  const handleSpeedChange = (rateVal: number) => {
    setTTSRate(rateVal);
    teacherMotor.setPlaybackRate(rateVal);
  };

  const skipTime = (amountMs: number) => {
    seekToTime(currentTimeMs + amountMs);
  };

  // Format milliseconds to M:SS
  const formatTime = (ms: number): string => {
    const totalSecs = Math.floor(ms / 1000);
    const m = Math.floor(totalSecs / 60);
    const s = totalSecs % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  // Find the active transcript index closest to the current playback time
  const activeTranscriptIndex = useMemo(() => {
    let activeIdx = -1;
    for (let i = 0; i < transcript.length; i++) {
      if (transcript[i].t <= currentTimeMs) {
        activeIdx = i;
      } else {
        break;
      }
    }
    return activeIdx;
  }, [transcript, currentTimeMs]);

  // Share session link
  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    toast.success("Replay session link copied to clipboard!");
  };

  if (loading) {
    return (
      <div className="w-full h-screen bg-[#FAF8F5] flex flex-col items-center justify-center gap-4">
        <LoaderSpinner className="h-8 w-8 animate-spin text-[#F9A01B]" />
        <div className="text-xs font-mono font-bold tracking-widest text-[#5A6372] uppercase animate-pulse">
          loading session replay…
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-screen bg-[#FAF8F5] flex flex-col relative overflow-hidden text-[#0B121F]">
      
      {/* Sleek Glassmorphic Header */}
      <header className="border-b border-[#E5DEC9] bg-white/80 backdrop-blur-md z-30 px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.back()}
              className="h-9 w-9 p-0 rounded-sm border border-[#E5DEC9] bg-white hover:bg-[#FAF8F5] text-[#0B121F]"
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <div className="flex items-center gap-1.5 text-[10px] font-mono font-bold tracking-widest text-[#F9A01B] uppercase">
                <Sparkles className="h-3 w-3" />
                Session Replay
              </div>
              <div className="font-display text-sm font-semibold mt-0.5 max-w-[400px] truncate text-[#0B121F]">
                <CleanPreview text={topic} plain />
              </div>
            </div>
          </div>

          <div className="text-xs font-mono font-bold text-[#5A6372] border border-[#E5DEC9] rounded px-2.5 py-1 bg-white">
            {formatTime(currentTimeMs)} / {formatTime(duration)}
          </div>
        </div>
      </header>

      {/* Main Content Area: Left Side Canvas, Right Side Interactive Transcript */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0 relative">
        {/* Canvas Area */}
        <div className="flex-1 relative bg-black min-w-0">
          {canvasElement}
        </div>

        {/* Desktop Sidebar: Narration Transcript */}
        <aside className="hidden md:flex w-[340px] border-l border-[#E5DEC9] bg-white/85 backdrop-blur-md flex-col z-20 shrink-0">
          <div className="p-4 border-b border-[#E5DEC9] flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-[#F9A01B]" />
            <span className="text-[11px] font-mono font-bold text-[#5A6372] uppercase tracking-widest">Narration Transcript</span>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
            {transcript.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-6">
                <MessageSquare className="h-8 w-8 text-[#E5DEC9] mb-2" />
                <p className="text-xs text-[#5A6372] font-mono">No voice segments recorded for this session.</p>
              </div>
            ) : (
              transcript.map((line, idx) => {
                const isActive = idx === activeTranscriptIndex;
                return (
                  <button
                    key={idx}
                    onClick={() => seekToTime(line.t)}
                    className={`w-full text-left p-3 rounded transition-all border flex flex-col gap-1 group ${
                      isActive
                        ? "bg-[#FFF5E6] border-[#F9A01B]/40 shadow-[0_0_12px_rgba(249,160,27,0.08)]"
                        : "bg-[#FAF8F5] border-[#E5DEC9] hover:bg-[#F0EDE8] hover:border-[#DDD8CC]"
                    }`}
                  >
                    <span className={`text-[10px] font-mono font-bold ${
                      isActive ? "text-[#F9A01B]" : "text-[#5A6372] group-hover:text-[#0B121F]"
                    }`}>
                      {formatTime(line.t)}
                    </span>
                    <p className={`text-xs leading-relaxed ${
                      isActive ? "text-[#0B121F] font-medium" : "text-[#5A6372]"
                    }`}>
                      {line.text}
                    </p>
                  </button>
                );
              })
            )}
          </div>
        </aside>
      </div>

      {/* Floating or Fixed Bottom Playback Controls */}
      <footer className="border-t border-[#E5DEC9] bg-[#FAF8F5]/95 backdrop-blur-md p-4 space-y-4 z-30">
        
        {/* Custom Slider Progress Bar */}
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-mono text-[#5A6372]">{formatTime(currentTimeMs)}</span>
          <Slider
            value={[currentTimeMs]}
            onValueChange={handleProgressChange}
            max={duration}
            step={100}
            className="flex-1 cursor-pointer"
          />
          <span className="text-[10px] font-mono text-[#5A6372]">{formatTime(duration)}</span>
        </div>

        {/* Controls Layout */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          
          {/* Playback Buttons Group */}
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => skipTime(-10000)}
              title="Skip backward 10s"
              className="h-9 w-9 p-0 rounded-sm border border-[#E5DEC9] bg-white text-[#5A6372] hover:bg-[#FAF8F5] hover:text-[#0B121F]"
            >
              <RotateCcw className="h-4 w-4" />
            </Button>

            <Button
              size="sm"
              onClick={handlePlayPause}
              className="h-10 px-5 rounded-sm bg-[#F9A01B] hover:bg-[#FFA51E] active:scale-[0.98] text-[#0B121F] font-bold shadow-md transition-all flex items-center gap-2"
            >
              {isPlaying ? (
                <>
                  <Pause className="h-4 w-4 fill-current text-[#0B121F]" /> Pause
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 fill-current text-[#0B121F]" /> Play
                </>
              )}
            </Button>

            <Button
              size="sm"
              variant="ghost"
              onClick={() => skipTime(10000)}
              title="Skip forward 10s"
              className="h-9 w-9 p-0 rounded-sm border border-[#E5DEC9] bg-white text-[#5A6372] hover:bg-[#FAF8F5] hover:text-[#0B121F]"
            >
              <SkipForward className="h-4 w-4" />
            </Button>
          </div>

          {/* Center Info: Current Concept Page */}
          <div className="text-[10px] font-mono text-[#5A6372] uppercase tracking-widest hidden lg:block">
            {activeSceneId ? `Viewing ${activeSceneId.replace("_", " ")}` : "Board space active"}
          </div>

          {/* Right Speed, Audio and Share Settings */}
          <div className="flex items-center gap-4">
            
            {/* Speed Control */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-mono text-[#5A6372] uppercase">Speed</span>
              <select
                value={playbackRate}
                onChange={(e) => handleSpeedChange(parseFloat(e.target.value))}
                className="h-8 px-2 text-xs font-mono font-bold border border-[#E5DEC9] rounded bg-white text-[#0B121F] hover:bg-[#FAF8F5] outline-none cursor-pointer"
              >
                <option value={0.5}>0.5x</option>
                <option value={1.0}>1.0x</option>
                <option value={1.5}>1.5x</option>
                <option value={2.0}>2.0x</option>
              </select>
            </div>

            {/* Volume / Mute Controls */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => setMuted(!muted)}
                className="p-1.5 rounded-sm hover:bg-[#FAF8F5] text-[#5A6372] hover:text-[#0B121F] transition-colors"
                title={muted ? "Unmute" : "Mute"}
              >
                {muted ? (
                  <VolumeX className="h-4 w-4 text-red-400" />
                ) : volume[0] === 0 ? (
                  <VolumeX className="h-4 w-4" />
                ) : volume[0] < 40 ? (
                  <Volume1 className="h-4 w-4" />
                ) : (
                  <Volume2 className="h-4 w-4" />
                )}
              </button>
              <Slider
                value={volume}
                onValueChange={(val) => {
                  setVolume(val);
                  if (muted) setMuted(false);
                }}
                max={100}
                step={5}
                className="w-20 cursor-pointer"
              />
            </div>

            {/* Share link */}
            <Button
              size="sm"
              variant="outline"
              onClick={handleShare}
              className="h-9 rounded-sm border-[#E5DEC9] bg-white text-[#5A6372] hover:bg-[#FAF8F5] hover:text-[#0B121F]"
            >
              <Share2 className="h-3.5 w-3.5 mr-2" /> Share
            </Button>
          </div>
        </div>
      </footer>
    </div>
  );
}

function LoaderSpinner({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}
