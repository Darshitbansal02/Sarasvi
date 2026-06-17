"use client";

import { useEffect, useRef, useState, useMemo, ReactNode } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Play,
  Pause,
  SkipForward,
  Share2,
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
import { toast } from "sonner";

interface SessionEvent {
  type: string;
  start_ms: number;
  payload?: {
    text?: string;
    estimated_duration_ms?: number;
    duration_ms?: number;
  };
}

export default function Replay() {
  const params = useParams();
  const id = params.id as string;
  const searchParams = useSearchParams();
  const topic = searchParams.get("topic") || "Recursion";
  const router = useRouter();

  const eventsRef = useRef<SessionEvent[]>([]);
  const playStartRef = useRef<number>(0);
  const baseClockRef = useRef<number>(0);
  const rafRef = useRef<number | null>(null);

  const [playing, setPlaying] = useState(true);
  const [rate, setRate] = useState(1);
  const [progress, setProgress] = useState(0); // ms
  const [loading, setLoading] = useState(true);
  const [duration, setDuration] = useState(0);

  const setRtState = useRuntimeStore((s) => s.setState);
  const resetRuntime = useRuntimeStore((s) => s.reset);

  const canvasElement = useMemo(() => <PixiCanvas />, []);

  // Fetch session events from backend
  useEffect(() => {
    if (!id) return;
    console.debug('[replay] useEffect start for session', id);
    resetRuntime();
    console.debug('[replay] resetRuntime called');
    // Start in BUFFERING so we can seed events into the runtime without
    // `ingestEvent` diverting them to the live buffer (ingestEvent behaves
    // specially when already in REPLAYING state).
    setRtState(RUNTIME_STATES.BUFFERING);
    let mounted = true;

    (async () => {
      try {
        setLoading(true);
        console.debug('[replay] fetching session events', id);
        const resp = await getSessionEvents(id);
        console.debug('[replay] fetched session events', resp?.total);
        if (!mounted) return;

        eventsRef.current = Array.isArray(resp.events)
          ? resp.events
          : [];
        if (eventsRef.current.length > 0) {
          eventsRef.current.sort(
            (a, b) => (a.start_ms || 0) - (b.start_ms || 0)
          );
          const lastEvent =
            eventsRef.current[eventsRef.current.length - 1];
          const total =
            (lastEvent.start_ms ?? 0) +
            (lastEvent.payload?.estimated_duration_ms ||
              lastEvent.payload?.duration_ms ||
              2000);
          baseClockRef.current = total;
          // Seed the runtime store with the fetched events so the regular
          // `tick()` loop can process them and drive rendering.
          try {
            // Zustand exposes `setState` on the hook function itself.
            (useRuntimeStore as any).setState({
              eventQueue: resp.events.slice(),
              metrics: { ...(useRuntimeStore.getState().metrics || {}), eventsReceived: resp.events.length, queueDepth: resp.events.length },
              generationId: resp.events[0]?.generation_id || null,
            });
            // Transition to REPLAYING so `tick()` runs playback.
            setRtState(RUNTIME_STATES.REPLAYING);
          } catch (e) {
            console.warn('[replay] failed to seed runtime store', e);
          }
          setDuration(total);
        } else {
          baseClockRef.current = 1000;
          setDuration(1000);
        }

        rebuildStateAtTime(0);
        setLoading(false);
      } catch (err) {
        console.warn("replay load failed", err);
        toast.error("Failed to load events for replay");
        setLoading(false);
      }
    })();

    return () => {
      mounted = false;
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
      ttsPlayer.stop();
    };
  }, [id, resetRuntime, setRtState]);

  // Rebuild state at specific time
  const rebuildStateAtTime = (elapsed: number) => {
    const evts = eventsRef.current;
    const objs: Record<string, any> = {};
    const transcript: { t: number; who: string; text: string }[] = [];
    const scenes: any[] = [];

    for (const evt of evts) {
      if ((evt.start_ms || 0) > elapsed) break;
      if (evt.payload) {
        if (evt.type === "speech") {
          transcript.push({ t: evt.start_ms || 0, who: "Sarasvi", text: evt.payload.text || "" });
        }
        if (evt.type === "scene_start") {
          scenes.push(evt.payload);
        }
      }
    }

    // Update runtime store
    useRuntimeStore.setState({
      transcript,
      scenes,
      currentTimeMs: elapsed,
    });
  };

  // Playback loop
  useEffect(() => {
    if (!playing) return;

    playStartRef.current = Date.now() - progress;

    const tick = () => {
      if (!playing) return;
      const now = Date.now();
      const newProgress = (now - playStartRef.current) * rate;

      if (newProgress >= baseClockRef.current) {
        setProgress(baseClockRef.current);
        setPlaying(false);
      } else {
        setProgress(newProgress);
        rebuildStateAtTime(newProgress);
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [playing, rate]);

  // Format time
  const formatTime = (ms: number): string => {
    const m = Math.floor(ms / 60000);
    const s = Math.floor((ms % 60000) / 1000);
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  const handleProgressChange = (values: number[]) => {
    setProgress(values[0]);
    rebuildStateAtTime(values[0]);
    setPlaying(false);
  };

  if (loading) {
    return (
      <div className="w-full h-screen bg-background flex items-center justify-center">
        <div className="animate-pulse label-mono">loading session replay…</div>
      </div>
    );
  }

  return (
    <div className="w-full h-screen bg-background flex flex-col relative overflow-hidden">
      {/* Header */}
      <div className="border-b border-border bg-background/80 backdrop-blur-sm z-30 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.back()}
              className="h-9 w-9 p-0 rounded-sm hover:bg-surface-hover"
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <div className="font-mono text-xs text-muted-foreground">
                Session Replay
              </div>
              <div className="font-display text-sm font-medium">{topic}</div>
            </div>
          </div>

          <div className="text-sm font-mono text-muted-foreground">
            {formatTime(progress)} / {formatTime(duration)}
          </div>
        </div>
      </div>

      {/* Canvas Area */}
      <div className="flex-1">
        {canvasElement}
      </div>

      {/* Playback Controls */}
      <div className="border-t border-border bg-background/80 backdrop-blur-sm p-4 space-y-3">
        {/* Progress Bar */}
        <Slider
          value={[progress]}
          onValueChange={handleProgressChange}
          max={duration}
          step={100}
          className="w-full"
        />

        {/* Controls */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant={playing ? "default" : "secondary"}
              onClick={() => setPlaying(!playing)}
              className="h-9 rounded-sm"
            >
              {playing ? (
                <>
                  <Pause className="h-3.5 w-3.5 mr-2" /> Pause
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5 mr-2" /> Play
                </>
              )}
            </Button>

            <div className="flex items-center gap-2 ml-2">
              <span className="text-xs text-muted-foreground">Speed:</span>
              <select
                value={rate}
                onChange={(e) => setRate(parseFloat(e.target.value))}
                className="h-8 px-2 text-xs font-mono border border-border rounded-sm bg-background text-foreground"
              >
                <option value={0.5}>0.5x</option>
                <option value={1}>1x</option>
                <option value={1.5}>1.5x</option>
                <option value={2}>2x</option>
              </select>
            </div>
          </div>

          <Button
            size="sm"
            variant="outline"
            className="h-9 rounded-sm border-border hover:bg-surface-hover"
          >
            <Share2 className="h-3.5 w-3.5 mr-2" /> Share
          </Button>
        </div>
      </div>
    </div>
  );
}
