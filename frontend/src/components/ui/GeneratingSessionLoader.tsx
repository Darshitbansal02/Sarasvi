"use client";

import { useEffect, useState, useRef } from "react";
import { Loader2, Sparkles, BookOpen } from "lucide-react";
import { useRuntimeStore, RUNTIME_STATES } from "@/runtime/runtimeStore";
import { CleanPreview } from "@/components/ui/CleanPreview";

interface GeneratingSessionLoaderProps {
  topic: string;
  language: string;
  onComplete?: () => void;
  isReady: boolean;
  sessionId: string;
}

export function GeneratingSessionLoader({
  topic,
  language,
  onComplete,
  isReady,
  sessionId,
}: GeneratingSessionLoaderProps) {
  const [progress, setProgress] = useState(0);
  const [show, setShow] = useState(true);
  const shutdownStarted = useRef(false);

  // ── Real backend signals (no mock data) ──────────────────────────────
  const runtimeState = useRuntimeStore((s) => s.sessionId === sessionId ? s.runtimeState : RUNTIME_STATES.CONNECTING);
  const hasArtifact = useRuntimeStore((s) => s.sessionId === sessionId ? !!s.pedagogicalPlan?.compiled_artifact : false);

  const languageLabel =
    language === "hi-IN"
      ? "Hindi (Hybrid)"
      : language === "hinglish"
      ? "Hinglish"
      : "English";

  let target = 12;
  if (isReady) target = 100;
  else if (hasArtifact) target = 85;
  else if (runtimeState === RUNTIME_STATES.STREAMING) target = 55;
  else target = 12; // CONNECTING / IDLE

  useEffect(() => {
    const id = setInterval(() => {
      setProgress((prev) => {
        if (prev >= target) return prev;
        const step = Math.max(0.4, (target - prev) * 0.07);
        return Math.min(target, Number((prev + step).toFixed(1)));
      });
    }, 120);
    return () => clearInterval(id);
  }, [target]);

  useEffect(() => {
    if (isReady && !shutdownStarted.current) {
      shutdownStarted.current = true;
      setProgress(100);

      const timer = setTimeout(() => {
        setShow(false);
        onComplete?.();
      }, 600);

      return () => clearTimeout(timer);
    }
  }, [isReady, onComplete]);

  if (!show) return null;

  let statusText: string;
  if (progress >= 100 || isReady) {
    statusText = "Blackboard ready!";
  } else if (hasArtifact) {
    statusText = "Lesson received — preparing the whiteboard...";
  } else if (runtimeState === RUNTIME_STATES.STREAMING) {
    statusText = "Generating lesson — planning, layout & narration...";
  } else {
    statusText = "Connecting to the lesson server...";
  }

  const isDone = progress >= 100 || isReady;

  return (
    <div className="fixed inset-0 z-[100] bg-[#FAF8F5]/95 backdrop-blur-md flex items-center justify-center p-4 transition-all duration-500">
      {/* Background Grid Lines */}
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: `
            linear-gradient(to right, #0B121F 1px, transparent 1px),
            linear-gradient(to bottom, #0B121F 1px, transparent 1px)
          `,
          backgroundSize: "32px 32px"
        }}
      />

      {/* Central Thinking Panel Card */}
      <div className="w-full max-w-md bg-white border border-[#E5DEC9] rounded-sm p-8 shadow-xl relative overflow-hidden">
        {/* Soft Ambient Glow Behind Card */}
        <div className="absolute -right-20 -top-20 w-48 h-48 rounded-full bg-[#F9A01B]/5 blur-3xl pointer-events-none" />
        <div className="absolute -left-20 -bottom-20 w-48 h-48 rounded-full bg-[#F9A01B]/5 blur-3xl pointer-events-none" />

        <div className="flex flex-col items-center relative z-10">
          {/* Pulsing Brain / Book Icon Ring */}
          <div className="h-16 w-16 rounded-full bg-[#FFF5E6] border border-[#F9A01B]/20 flex items-center justify-center mb-6 relative">
            <div className="absolute inset-0 rounded-full border border-[#F9A01B]/30 animate-ping" style={{ animationDuration: "2.5s" }} />
            <img src="/logo.png" alt="Sarasvi Logo" className="h-10 w-10 object-contain relative z-10" />
          </div>

          <h2 className="font-display font-bold text-xl text-[#0B121F] tracking-tight mb-1 text-center">
            Sarasvi is thinking...
          </h2>

          {/* Correctly format and preview the question/topic with LaTeX support */}
          <div className="w-full mt-4 mb-6">
            <CleanPreview 
              text={topic} 
              className="w-full border-[#E5DEC9] bg-[#FAF8F5] text-[#0B121F]"
            />
          </div>

          {/* Realistic Progress Status */}
          <div className="h-5 flex items-center justify-center mb-6">
            {!isDone ? (
              <div className="flex items-center gap-2 text-xs font-mono text-[#5A6372]">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-[#F9A01B]" />
                <span>{statusText}</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-xs font-mono text-green-600 font-bold">
                <Sparkles className="h-3.5 w-3.5 text-green-600" />
                <span>{statusText}</span>
              </div>
            )}
          </div>

          {/* Simple Clean Progress Bar */}
          <div className="w-full space-y-2">
            <div className="h-1.5 bg-[#FAF8F5] rounded-sm overflow-hidden border border-[#E5DEC9] relative">
              <div
                className="h-full bg-[#F9A01B] transition-all duration-300 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] font-mono text-[#5A6372] px-0.5">
              <span className="uppercase tracking-wider">Locale: {languageLabel}</span>
              <span>{Math.floor(progress)}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
