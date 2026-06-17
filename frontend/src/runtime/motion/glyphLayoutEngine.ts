/**
 * glyphLayoutEngine.ts — Simplified Math Layout & Measurement Stub
 *
 * All recursive Math AST Parsing, layout box solving, and cursive connections
 * have migrated to backend compilers (glyph_compiler.py, stroke_compiler.py).
 * This frontend stub only exports base type declarations and asset schemas.
 */

export interface FontStyle {
  fontFamily?: string;
  fontSize?: number;
  fontWeight?: string | number;
}

export interface GlyphMetadata {
  char: string;
  scaledX: number;
  scaledY: number;
  width: number;
  fontSize: number;
  isSuperscript: boolean;
}

export interface StrokeEntry {
  strokeId: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  points?: [number, number][];
  thickness: number;
  charIndex?: number;
}

export interface ConstructionStep {
  type: "stroke" | "glyph" | string;
  index: number;
}

export interface LayoutBox {
  width: number;
  height: number;
  ascent: number;
  descent: number;
  glyphs: GlyphMetadata[];
  strokes: StrokeEntry[];
  constructionSequence: ConstructionStep[];
  totalWidth?: number;
}

/**
 * Normalization helper left intact for input stream sanitize checks.
 */
export function cleanLatexToMath(latex: string): string {
  if (!latex) return "";
  return latex
    .replace(/\\text\{([^}]+)\}/g, "$1")
    .replace(/\\mathrm\{([^}]+)\}/g, "$1")
    .replace(/\\left/g, "")
    .replace(/\\right/g, "")
    .replace(/\\/g, "")
    .replace(/[{}]/g, "")
    .trim();
}
