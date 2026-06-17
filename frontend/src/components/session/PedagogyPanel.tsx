import React, { ReactNode, useRef, useEffect } from "react";
import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRuntimeStore } from "@/runtime/runtimeStore";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import { CleanPreview } from "@/components/ui/CleanPreview";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PedagogyPanelProps {
  onInterrupt: () => void;
}

const PEDAGOGY_MODES = ["Analogy", "Visual", "Formal", "Socratic"] as const;
type PedagogyMode = (typeof PEDAGOGY_MODES)[number];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

const t = (key: string) => key;

export default function PedagogyPanel({ onInterrupt }: PedagogyPanelProps): ReactNode {
  const transcript = useRuntimeStore((s) => s.transcript);
  const pedagogicalState = useRuntimeStore((s) => s.pedagogicalState);
  const activeMetaphor = useRuntimeStore((s) => s.activeMetaphor);
  const detectedMisconceptions = useRuntimeStore((s) => s.detectedMisconceptions);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new transcript entries arrive or text updates,
  // but only if the user was already near the bottom (allows scrolling up to read).
  // Delaying by 30ms lets the DOM render the new word elements and calculate scrollHeight correctly.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      const threshold = 150; // pixels from bottom
      const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
      if (isNearBottom) {
        const id = setTimeout(() => {
          el.scrollTop = el.scrollHeight;
        }, 30);
        return () => clearTimeout(id);
      }
    }
  }, [transcript]);

  // Temporarily commented out while Explanation feature is hidden
  // const handleModeClick = (mode: PedagogyMode) => {
  //   useRuntimeStore.setState({ activeMetaphor: mode.toLowerCase() });
  // };

  /* Derive the active mode label for the header sub-label */
  // const activeModeLabel =
  //   PEDAGOGY_MODES.find((m) => m.toLowerCase() === activeMetaphor) ?? "Formal";

  return (
    <aside
      className="hidden lg:flex flex-col h-full w-[280px] min-w-[280px] border-l border-border bg-card select-none font-sans"
    >
      {/* ── Interrupt Button ──────────────────────────────────────── */}
      <div className="p-4 border-b border-border/60 bg-muted/30">
        <Button
          onClick={onInterrupt}
          className={cn(
            "w-full h-12 rounded-sm text-sm font-display font-semibold text-primary-foreground transition-all duration-300",
            "bg-primary hover:bg-primary/90 active:scale-[0.98] border-none shadow-md shadow-primary/20",
            "flex items-center justify-center gap-2"
          )}
        >
          <MessageSquare className="h-4.5 w-4.5" strokeWidth={2} />
          Ask a Question
        </Button>
      </div>

      {/* ── Pedagogy Mode Section ─────────────────────────────────── */}
      {/* Temporarily hidden explanation feature to let transcript expand */}

      {/* ── Misconceptions Detected ───────────────────────────────── */}
      {detectedMisconceptions.length > 0 && (
        <div className="px-3 pt-3 pb-2 border-b border-border bg-red-500/5">
          <span className="font-mono text-[9px] uppercase tracking-wider text-red-600 dark:text-red-400 font-semibold flex items-center gap-1.5 mb-2">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
            Concepts to Clarify
          </span>
          <div className="space-y-1">
            {detectedMisconceptions.map((mc) => (
              <div key={mc.id} className="text-xs font-mono bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20 px-2 py-1.5 rounded truncate">
                {mc.concept}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Transcript Section ────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-h-0 bg-muted/5">
        <div className="px-4 pt-4 pb-2">
          <span className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground font-semibold">{t("Transcript")}</span>
        </div>

        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-4 pb-4 space-y-3 scrollbar-thin"
        >
          {transcript.length === 0 && (
            <div className="flex items-center justify-center h-24">
              <p className="text-xs font-mono text-muted-foreground/60 italic">
                {t("Waiting for session…")}
              </p>
            </div>
          )}

          <AnimatePresence initial={false}>
            {transcript.map((entry, i) => {
              const isLast = i === transcript.length - 1;

              return (
                <motion.div
                  key={`${entry.t}-${i}`}
                  initial={{ opacity: 0, y: 12, scale: 0.98 }}
                  animate={{
                    opacity: isLast ? 1 : 0.75,
                    y: 0,
                    scale: 1,
                    borderColor: isLast ? "rgba(249, 160, 27, 0.4)" : "hsl(var(--border))",
                    backgroundColor: isLast ? "hsl(var(--card))" : "hsl(var(--muted) / 0.3)"
                  }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 0.25, ease: "easeOut" }}
                  className={cn(
                    "rounded-sm p-4 border text-left transition-all duration-300 shadow-sm",
                    isLast ? "shadow-md shadow-primary/8" : ""
                  )}
                >
                  {/* Speaker label */}
                  <div className="flex items-center justify-between mb-2 select-none">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "w-1.5 h-1.5 rounded-full relative flex",
                        isLast ? "bg-primary" : "bg-muted-foreground"
                      )}>
                        {isLast && (
                          <span className="absolute inline-flex h-full w-full rounded-full bg-primary opacity-75 animate-ping" />
                        )}
                      </span>
                      <span className={cn(
                        "text-[9px] font-mono tracking-wider uppercase font-bold",
                        isLast ? "text-primary" : "text-muted-foreground"
                      )}>
                        {entry.who === "Sarasvi" || entry.who === "Sarasvi" || entry.who === "Sarasvi" || entry.who === "Sarasvi"
                          ? "Sarasvi"
                          : entry.who}
                      </span>
                    </div>
                    <span className="text-[8px] font-mono text-muted-foreground/60">
                      {entry.t ? `${Math.round(entry.t / 1000)}s` : ""}
                    </span>
                  </div>

                  {/* Content */}
                  <div className={cn(
                    "text-xs leading-relaxed font-sans font-medium",
                    isLast ? "text-foreground" : "text-muted-foreground"
                  )}>
                    {entry.text ? (
                      <CleanPreview text={entry.text} plain className="text-xs font-sans font-medium leading-relaxed block w-full" />
                    ) : (
                      isLast ? (
                        <span className="inline-block w-1.5 h-3.5 bg-primary/80 animate-pulse align-text-bottom" />
                      ) : null
                    )}
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      </div>
    </aside>
  );
}
