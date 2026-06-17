"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Volume2, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { useRuntimeStore } from "@/runtime/runtimeStore";
import { cn } from "@/lib/utils";
import { CleanPreview } from "@/components/ui/CleanPreview";

interface SessionSidebarProps {
  topic: string;
  muted: boolean;
  volume: number[];
  onMuteToggle: () => void;
  onVolumeChange: (val: number[]) => void;
  startedAt: number;
}

const STATE_LABELS: Record<string, { dot: string; label: string }> = {
  IDLE: { dot: "bg-muted-foreground/50", label: "Waiting" },
  CONNECTING: { dot: "bg-amber-400 animate-pulse", label: "Connecting…" },
  STREAMING: { dot: "bg-green-500 animate-pulse", label: "Live" },
  BUFFERING: { dot: "bg-amber-400 animate-pulse", label: "Buffering…" },
  PAUSED: { dot: "bg-amber-400", label: "Paused" },
  INTERRUPTING: { dot: "bg-red-400 animate-pulse", label: "Responding…" },
  COMPLETED: { dot: "bg-blue-400", label: "Finished" },
  ERROR: { dot: "bg-destructive", label: "Error" },
  REMEDIATING: { dot: "bg-primary animate-pulse", label: "Adapting…" },
};

function ElapsedTime({ startedAt }: { startedAt: number }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) return;
    const update = () => setElapsed(Date.now() - startedAt);
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  const totalSeconds = Math.floor(elapsed / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return (
    <span className="font-mono text-foreground text-sm font-semibold tabular-nums">
      {minutes}:{String(seconds).padStart(2, "0")}
    </span>
  );
}

function SpeakingIndicator() {
  const isSpeaking = useRuntimeStore((s) => s.narrationStatus.state === "speaking");

  return (
    <div className="flex items-end gap-[2px] h-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className={cn(
            "w-[3px] rounded-sm transition-all duration-150",
            isSpeaking ? "bg-primary" : "bg-muted-foreground/30 h-[3px]"
          )}
          style={
            isSpeaking
              ? {
                height: `${5 + i * 3}px`,
                animation: `pulse-bar 0.6s ease-in-out ${i * 0.15}s infinite alternate`,
              }
              : { height: "3px" }
          }
        />
      ))}
    </div>
  );
}

export default function SessionSidebar({
  topic,
  muted,
  volume,
  onMuteToggle,
  onVolumeChange,
  startedAt,
}: SessionSidebarProps) {
  const router = useRouter();
  const runtimeState = useRuntimeStore((s) => s.runtimeState) as string;
  const stateInfo = STATE_LABELS[runtimeState] ?? { dot: "bg-muted-foreground/40", label: "" };

  return (
    <aside className="hidden md:flex w-60 h-full flex-col shrink-0 bg-card border-r border-border/70 overflow-y-auto scrollbar-thin select-none font-sans">
      {/* Brand + back */}
      <div className="px-4 pt-4 pb-3 border-b border-border/60">
        <div className="label-mono text-[8px] text-primary font-bold mb-2.5 tracking-[0.18em]">
          Sarasvi · LIVE SESSION
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start text-muted-foreground hover:text-foreground hover:bg-muted gap-2 px-2 py-1.5 h-8 font-mono text-[9px] uppercase tracking-wider font-semibold rounded-sm transition-all border border-transparent hover:border-border/60"
          onClick={() => router.push("/dashboard")}
        >
          <ArrowLeft className="w-3.5 h-3.5 text-primary" />
          Dashboard
        </Button>
      </div>

      {/* Topic */}
      <div className="px-4 pt-3.5 pb-3 border-b border-border/60">
        <div className="label-mono text-[8px] text-muted-foreground mb-1.5 tracking-widest">TOPIC</div>
        <h2 className="font-display text-foreground text-sm font-bold leading-snug tracking-tight line-clamp-3">
          <CleanPreview text={topic} plain />
        </h2>
      </div>

      {/* Status */}
      <div className="px-4 py-3 border-b border-border/60">
        <div className="label-mono text-[8px] text-muted-foreground mb-2 tracking-widest">STATUS</div>
        <div className="flex items-center gap-2">
          <span className={cn("w-2 h-2 rounded-full shrink-0", stateInfo.dot)} />
          <span className="font-sans text-[13px] font-medium text-foreground">
            {stateInfo.label}
          </span>
          <span className="ml-auto">
            <SpeakingIndicator />
          </span>
        </div>
      </div>

      {/* Elapsed */}
      <div className="px-4 py-3 border-b border-border/60">
        <div className="label-mono text-[8px] text-muted-foreground mb-1.5 tracking-widest">ELAPSED</div>
        <ElapsedTime startedAt={startedAt} />
      </div>

      {/* Voice */}
      <div className="px-4 py-3">
        <div className="label-mono text-[8px] text-muted-foreground mb-2.5 tracking-widest">VOICE</div>
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            className="p-0 h-auto w-auto shrink-0"
            onClick={onMuteToggle}
          >
            {muted ? (
              <VolumeX className="w-4 h-4 text-red-500" />
            ) : (
              <Volume2 className="w-4 h-4 text-primary" />
            )}
          </Button>
          <Slider
            min={0}
            max={100}
            step={1}
            value={volume}
            onValueChange={onVolumeChange}
            className="flex-1 cursor-pointer"
          />
          <span className="font-mono text-[9px] text-muted-foreground w-6 text-right tabular-nums">
            {volume[0]}
          </span>
        </div>
      </div>
    </aside>
  );
}
