"use client";

import React, { useEffect, useState } from "react";

interface CleanPreviewProps {
  text: string;
  className?: string;
  /** Render just the content with no surrounding card or header */
  plain?: boolean;
}

// Strip internal pipeline markers before showing text to users.
// [Diagram: ...] and "Key expressions: ..." are injected by the image
// extraction pipeline for the LLM — they should never appear raw in the UI.
function stripPipelineMarkers(raw: string): string {
  return raw
    .replace(/\[Diagram:[^\]]*\]/gi, "")
    .replace(/^Key expressions:.*$/gim, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// Insert logical line breaks for extracted question text that arrives as one
// long line: MCQ options (A)–(D), "Given:", "The value of …" etc.
function insertLogicalBreaks(text: string): string {
  if (text.includes("\n")) return text; // already has line structure
  return text
    // Break before each MCQ option: " (A) " → "\n(A) "
    .replace(/\s+\(([A-D])\)\s+/g, "\n($1) ")
    // Break before "Given" / "Find" / "Calculate" / "The value of"
    .replace(/([.?])\s+(Given\b|Find\b|Calculate\b|Determine\b|The value of\b)/g, "$1\n$2")
    // Break before standalone sentence after closing $ "… $. Word"
    .replace(/(\$)\.\s+([A-Z])/g, "$1.\n$2");
}

// Restore LaTeX control characters that get mangled by JSON/network transport.
function restoreLatexEscapes(raw: string): string {
  return raw
    .replace(//g, "\\f")   // form-feed → \frac
    .replace(//g, "\\b")   // backspace → \beta
    .replace(//g, "\\v");  // vertical-tab → \v
}

const MATH_KEYWORDS = [
  "\\int", "\\frac", "\\sqrt", "\\sin", "\\cos", "\\tan", "\\log", "\\lim",
  "\\sum", "\\prod", "\\text", "\\alpha", "\\beta", "\\theta", "\\pi",
  "\\infty", "\\delta", "\\Delta", "\\lambda", "\\mu", "\\sigma", "\\omega",
  "\\phi", "\\psi", "\\gamma", "\\epsilon", "\\nabla", "\\partial",
  "\\vec", "\\hat", "\\dot", "\\ddot", "\\rightarrow", "\\Rightarrow",
  "\\leftarrow", "\\leftrightarrow", "\\pm", "\\times", "\\cdot", "\\leq",
  "\\geq", "\\neq", "\\approx", "\\equiv",
];

function useKatex() {
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if ((window as any).katex) { setLoaded(true); return; }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css";
    document.head.appendChild(link);
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js";
    script.onload = () => setLoaded(true);
    document.head.appendChild(script);
  }, []);
  return loaded;
}

function renderMath(text: string, katexLoaded: boolean): React.ReactNode {
  if (!katexLoaded || typeof window === "undefined" || !(window as any).katex) {
    return <span className="whitespace-pre-wrap leading-relaxed">{text}</span>;
  }
  const katex = (window as any).katex;

  // Split on $...$ and $$...$$ delimiters
  if (text.includes("$")) {
    const parts = text.split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/g);
    return (
      <>
        {parts.map((part, i) => {
          if (part.startsWith("$$") && part.endsWith("$$")) {
            try {
              return (
                <span
                  key={i}
                  className="block my-1 overflow-x-auto"
                  dangerouslySetInnerHTML={{
                    __html: katex.renderToString(part.slice(2, -2), { displayMode: true, throwOnError: false }),
                  }}
                />
              );
            } catch { return <span key={i} className="font-mono text-xs">{part}</span>; }
          }
          if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
            try {
              return (
                <span
                  key={i}
                  className="inline-block align-middle px-0.5"
                  dangerouslySetInnerHTML={{
                    __html: katex.renderToString(part.slice(1, -1), { displayMode: false, throwOnError: false }),
                  }}
                />
              );
            } catch { return <span key={i} className="font-mono text-xs">{part}</span>; }
          }
          return <span key={i} className="whitespace-pre-wrap leading-relaxed">{part}</span>;
        })}
      </>
    );
  }

  // No $ delimiters — try rendering full string as LaTeX if it looks like math
  const looksLikeMath =
    MATH_KEYWORDS.some((k) => text.includes(k)) || /\\[a-zA-Z{]/.test(text);
  if (looksLikeMath) {
    // If there's plain prose before the first backslash, split there
    const firstBS = text.indexOf("\\");
    if (firstBS > 0) {
      const prose = text.slice(0, firstBS);
      const mathPart = text.slice(firstBS);
      try {
        return (
          <span>
            <span className="whitespace-pre-wrap">{prose}</span>
            <span
              className="inline-block align-middle px-0.5"
              dangerouslySetInnerHTML={{
                __html: katex.renderToString(mathPart, { displayMode: false, throwOnError: false }),
              }}
            />
          </span>
        );
      } catch { /* fall through */ }
    } else {
      try {
        return (
          <span
            className="inline-block align-middle"
            dangerouslySetInnerHTML={{
              __html: katex.renderToString(text, { displayMode: false, throwOnError: false }),
            }}
          />
        );
      } catch { /* fall through */ }
    }
  }

  // Implicit math: chemistry/physics notation without $ delimiters.
  // Detects subscripts (_2, _{cell}) and superscripts (^+, ^{2+}, ^x).
  // Renders line-by-line: math-heavy lines through KaTeX, prose lines as text.
  const hasImplicitMath = /[_^]\{|[_^][A-Za-z0-9+\-]/.test(text);
  if (hasImplicitMath) {
    const lines = text.split("\n");
    return (
      <>
        {lines.map((line, idx) => {
          if (!line.trim()) return <br key={idx} />;
          if (/[_^]\{|[_^][A-Za-z0-9+\-]/.test(line)) {
            return (
              <span key={idx} className="block my-0.5">
                <span
                  dangerouslySetInnerHTML={{
                    __html: katex.renderToString(line.trim(), {
                      displayMode: false,
                      throwOnError: false,
                      strict: "ignore",
                    }),
                  }}
                />
              </span>
            );
          }
          return (
            <span key={idx} className="block whitespace-pre-wrap leading-relaxed">
              {line}
            </span>
          );
        })}
      </>
    );
  }

  return <span className="whitespace-pre-wrap leading-relaxed">{text}</span>;
}

export function CleanPreview({ text, className = "", plain = false }: CleanPreviewProps) {
  const katexLoaded = useKatex();

  if (!text?.trim()) return null;

  const cleaned = insertLogicalBreaks(restoreLatexEscapes(stripPipelineMarkers(text)));
  if (!cleaned) return null;

  const content = renderMath(cleaned, katexLoaded);

  if (plain) {
    return (
      <div className={`text-sm text-[#1A2433] leading-relaxed ${className}`}>
        {content}
      </div>
    );
  }

  return (
    <div className={`p-3 rounded border border-[#F9A01B]/20 bg-[#FFF5E6]/60 text-sm text-[#1A2433] font-sans leading-relaxed ${className}`}>
      {content}
    </div>
  );
}
