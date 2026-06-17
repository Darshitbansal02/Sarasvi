import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useRuntimeStore } from "@/runtime/runtimeStore";
import { Button } from "@/components/ui/button";

export default function CheckpointOverlay() {
  const checkpointState = useRuntimeStore((s) => s.checkpointState);
  const submitCheckpointAnswer = useRuntimeStore((s) => s.submitCheckpointAnswer);
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!checkpointState?.active) return null;

  const handleSubmit = async () => {
    if (!answer.trim() || submitting) return;
    setSubmitting(true);
    await submitCheckpointAnswer(answer);
    setAnswer("");
    setSubmitting(false);
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 20 }}
        className="absolute bottom-6 left-1/2 -translate-x-1/2 w-full max-w-lg z-50 bg-[#09090b] border border-zinc-800 rounded-lg p-5 shadow-2xl"
      >
        <div className="flex items-center gap-2 mb-3">
          <span className="flex h-2 w-2 rounded-full bg-[#ff9f0a] animate-pulse"></span>
          <h3 className="font-mono text-sm font-semibold text-[#ff9f0a] uppercase tracking-widest">
            Socratic Checkpoint
          </h3>
        </div>
        <p className="text-sm text-foreground font-medium mb-4">
          {checkpointState.questionText}
        </p>

        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Type your answer here..."
          className="w-full h-24 bg-[#121212] border border-zinc-800 rounded p-3 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-[#ff9f0a] transition-all resize-none font-sans"
          autoFocus
        />

        <div className="flex justify-end mt-4">
          <Button
            size="sm"
            disabled={!answer.trim() || submitting}
            onClick={handleSubmit}
            className="bg-[#ff9f0a] text-black hover:bg-[#ff9f0a]/90 font-mono text-xs font-bold px-6"
          >
            {submitting ? "Evaluating..." : "Submit Answer"}
          </Button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
