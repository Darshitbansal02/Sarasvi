"use client";

import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

export default function TermsPage() {
  const router = useRouter();

  const handleBack = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    // Go back in history if possible, otherwise navigate to /welcome
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
    } else {
      router.push("/welcome");
    }
  };

  return (
    <div className="min-h-screen bg-black text-white">
      <div className="max-w-3xl mx-auto px-6 py-12">
        {/* Header */}
        <div className="mb-10">
          <a
            href="/welcome"
            onClick={handleBack}
            className="inline-flex items-center gap-2 text-xs font-mono text-[#8B95A5] hover:text-white transition-colors mb-8"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to sign up
          </a>
          <div className="text-xs font-mono font-semibold tracking-widest text-[#F9A01B] uppercase mb-2">
            Legal
          </div>
          <h1 className="font-display text-4xl font-bold tracking-tight text-white">
            Terms of Service &amp; AI Disclaimer
          </h1>
          <p className="text-sm text-[#8B95A5] mt-3">
            Last updated: June 2026 · Sarasvi v0.1
          </p>
        </div>

        <div className="space-y-10 text-sm text-[#C8D0DC] leading-relaxed">

          {/* 1 */}
          <section>
            <h2 className="text-base font-semibold text-white mb-3">1. How to Use Sarasvi</h2>
            <p>
              Sarasvi is an interactive AI-powered whiteboard learning platform. You can type any
              topic, concept, equation, or question into the lesson prompt, and Sarasvi will
              dynamically generate an explanation — drawing it on a virtual chalkboard with
              synchronized narration, diagrams, formulas, and visual examples.
            </p>
            <ul className="mt-3 list-disc list-inside space-y-1.5 text-[#8B95A5]">
              <li>
                <strong className="text-[#C8D0DC]">Ask doubts in real time.</strong>{" "}
                During any live lesson, click <em>Ask a Doubt</em> or circle a part of the board
                with your cursor to interrupt and ask a clarifying question. The AI will pause,
                read your question, and pivot the explanation to address it before resuming.
              </li>
              <li>
                <strong className="text-[#C8D0DC]">Lessons are AI-generated on demand.</strong>{" "}
                No content is pre-recorded. Every lesson is synthesized live from large language
                models at the moment you request it.
              </li>
              <li>
                <strong className="text-[#C8D0DC]">Learning style personalization.</strong>{" "}
                Your selected grade level, pace, and analogy themes influence how content is
                explained, but these are best-effort guides to the AI — not guarantees.
              </li>
              <li>
                <strong className="text-[#C8D0DC]">Student data.</strong>{" "}
                Your name, email, age, grade level, and learning preferences are stored to
                personalize your sessions. Lesson transcripts may be retained to improve the
                platform. We do not sell your personal data to third parties.
              </li>
            </ul>
          </section>

          {/* 2 */}
          <section>
            <h2 className="text-base font-semibold text-white mb-3">2. AI Disclaimer — What the AI Can and Cannot Do</h2>
            <p>
              Sarasvi is powered by generative AI models (currently Google Gemini and/or Groq-hosted
              open models). These models can produce high-quality explanations across mathematics,
              physics, chemistry, computer science, and other domains — but they are not infallible.
            </p>
            <ul className="mt-3 list-disc list-inside space-y-1.5 text-[#8B95A5]">
              <li>AI models may generate factually incorrect or mathematically wrong answers.</li>
              <li>
                Diagrams and proofs are algorithmically constructed and may contain visual or logical
                errors.
              </li>
              <li>
                The platform includes built-in verification modules for common STEM claims, but
                verification is not exhaustive and may miss errors.
              </li>
              <li>
                Sarasvi should be used as a supplementary learning tool, not as a primary or sole
                source of information for critical decisions (exams, medical, legal, financial, etc.).
              </li>
            </ul>
          </section>

          {/* 3 */}
          <section>
            <h2 className="text-base font-semibold text-white mb-3">3. Limitation of Liability</h2>
            <p>
              <strong className="text-white">
                We are not responsible for any answer, fact, formula, explanation, calculation,
                diagram, code snippet, or other content generated by the platform.
              </strong>{" "}
              By using Sarasvi, you acknowledge that:
            </p>
            <ul className="mt-3 list-disc list-inside space-y-1.5 text-[#8B95A5]">
              <li>
                All AI-generated content should be independently verified before relying on it for
                academic submissions, professional work, or any high-stakes purpose.
              </li>
              <li>
                The developers and operators of Sarasvi accept no liability for losses, damages,
                academic penalties, or other harm arising from incorrect AI-generated content.
              </li>
              <li>
                The platform is provided &ldquo;as is&rdquo; without warranties of accuracy,
                fitness for a particular purpose, or uninterrupted availability.
              </li>
            </ul>
          </section>

          {/* 4 */}
          <section>
            <h2 className="text-base font-semibold text-white mb-3">4. Appropriate Use</h2>
            <ul className="list-disc list-inside space-y-1.5 text-[#8B95A5]">
              <li>You must be at least 5 years old to use this platform.</li>
              <li>
                You may not attempt to extract, abuse, or reverse-engineer the underlying AI models
                or platform infrastructure.
              </li>
              <li>
                You may not use Sarasvi to generate content that violates any applicable law,
                infringes intellectual property rights, or is harmful, deceptive, or abusive.
              </li>
              <li>
                Academic integrity: use Sarasvi as a learning aid. Submitting AI-generated answers
                as your own original work may violate your institution&apos;s honor code — that
                responsibility rests entirely with you.
              </li>
            </ul>
          </section>

          {/* 5 */}
          <section>
            <h2 className="text-base font-semibold text-white mb-3">5. Changes to These Terms</h2>
            <p>
              We may update these terms as the platform evolves. Material changes will be notified
              on the platform. Continued use after notification constitutes acceptance of the updated
              terms.
            </p>
          </section>
        </div>

        {/* Footer CTA */}
        <div className="mt-14 pt-8 border-t border-white/10 text-center">
          <a
            href="/welcome"
            onClick={handleBack}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-sm bg-[#F9A01B] hover:bg-[#FFA51E] text-white text-sm font-semibold transition-colors"
          >
            <ArrowLeft className="h-4 w-4" /> Return to sign up
          </a>
        </div>
      </div>
    </div>
  );
}
