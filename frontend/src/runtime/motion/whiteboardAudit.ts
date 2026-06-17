import type { NarrationStatus } from "./narrationSync";

export interface WhiteboardAuditFinding {
  ruleId: string;
  objectId: string;
  objectType: string;
  message: string;
  evidence: string;
}

export interface WhiteboardAuditEntry {
  obj: Record<string, any>;
  entry?: Record<string, any> | null;
  currentTimeMs: number;
  narrationStatus?: NarrationStatus | null;
}

const REPORTED_KEYS = new Set<string>();

function isVisibleTextNode(node: any): boolean {
  if (!node) return false;
  const visible = node.visible !== false;
  const alpha = typeof node.alpha === "number" ? node.alpha : 1;
  return visible && alpha > 0.001;
}

function pushOnce(findings: WhiteboardAuditFinding[], finding: WhiteboardAuditFinding): void {
  const key = `${finding.ruleId}:${finding.objectId}:${finding.evidence}`;
  if (REPORTED_KEYS.has(key)) return;
  REPORTED_KEYS.add(key);
  findings.push(finding);
}

export function collectWhiteboardAuditFindings(entry: WhiteboardAuditEntry): WhiteboardAuditFinding[] {
  const findings: WhiteboardAuditFinding[] = [];
  const { obj, currentTimeMs } = entry;
  const objType = String(obj?.type || "unknown");
  const objectId = String(obj?.id || "unknown");
  const hasConstructionHistory = Boolean(
    (obj?._charStates?.length || 0) > 0 ||
    (obj?._strokesLayout?.length || 0) > 0 ||
    (obj?._constructionSequence?.length || 0) > 0
  );

  const visibleTextNodes = [
    obj?.txt,
    obj?.right,
    obj?.titleTxt,
    ...(Array.isArray(obj?.glyphs) ? obj.glyphs.map((glyph: any) => glyph?.txt) : []),
    ...(Array.isArray(obj?.vectorLabels) ? obj.vectorLabels : []),
  ].filter(isVisibleTextNode);

  if (visibleTextNodes.length > 0) {
    pushOnce(findings, {
      ruleId: "runtime.no_visible_text_escape_hatch",
      objectId,
      objectType: objType,
      message: "Visible educational text must be authored through construction, not direct text rendering.",
      evidence: `${visibleTextNodes.length} visible PIXI.Text node(s) at ${currentTimeMs}ms`,
    });
  }

  if (
    ["annotation", "equation", "equation_write", "code_block", "graph_function", "physics_diagram", "node", "edge", "stack", "stack_frame"].includes(objType) &&
    visibleTextNodes.length > 0 &&
    !hasConstructionHistory
  ) {
    pushOnce(findings, {
      ruleId: "runtime.missing_construction_history",
      objectId,
      objectType: objType,
      message: "Visible board content lacks a stroke-based birth history.",
      evidence: `type=${objType} at ${currentTimeMs}ms`,
    });
  }

  if (visibleTextNodes.length > 0 && !hasConstructionHistory) {
    pushOnce(findings, {
      ruleId: "runtime.construction_fidelity_gap",
      objectId,
      objectType: objType,
      message: "Backend intent is not manifesting as visible construction on the board.",
      evidence: `no stroke history at ${currentTimeMs}ms`,
    });
  }

  if (entry.narrationStatus?.isAudioSynced && visibleTextNodes.length > 0 && !hasConstructionHistory) {
    pushOnce(findings, {
      ruleId: "runtime.audio_construction_coupling_gap",
      objectId,
      objectType: objType,
      message: "Narration is playing without a causally aligned board construction history.",
      evidence: `audioSynced=true at ${currentTimeMs}ms`,
    });
  }

  return findings;
}

export function reportWhiteboardAuditFindings(findings: WhiteboardAuditFinding[], scope: string): void {
  if (!findings.length) return;
  for (const finding of findings) {
    console.warn("[whiteboard-audit]", scope, finding.ruleId, finding.objectId, finding.message, finding.evidence);
  }
}
