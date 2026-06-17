/**
 * types.ts — Core TypeScript Definitions for Sarasvi
 */

export type Point = [number, number];

export interface Position {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export enum CursorState {
  IDLE = "idle",
  MOVING = "moving",
  HOVERING = "hovering",
  DRAWING = "drawing",
  PAUSING = "pausing",
  HIDDEN = "hidden",
  GESTURING = "gesturing",
  THINKING = "thinking"
}

export interface CursorSnapshot {
  visible: boolean;
  x: number;
  y: number;
  state: CursorState;
  pressure: number;
  penDown: boolean;
}

export interface Stroke {
  strokeId: string;
  path: Point[];
  color: string | number;
  thickness: number;
  alpha: number;
  state: "pending" | "growing" | "completed";
  progress: number;
  sceneId: string;
}

export interface SceneObject {
  id: string;
  type: string;
  data: any;
  position: Position;
  width?: number;
  height?: number;
  visible: boolean;
  opacity: number;
  scale: number;
  startMs: number;
  sceneId: string;
  pageIndex: number;
  _fadeTarget?: number;
  _charStates?: any[];
  _glyphsLayout?: any[];
  _strokesLayout?: any[];
  _constructionSequence?: Array<{ type: string; index: number }>;
  _mergedLatex?: string;
  _boardCompletedStrokeMaxIndex?: number;
  _boardStepIds?: string[];
  _totalTextWidth?: number;
  _textProgress?: number;
}

export interface TimelineEvent {
  type: string;
  start_ms: number;
  payload: any;
  generation_id?: string;
}

export interface PedagogicalState {
  active_concept: string;
  teaching_mode: string;
  pacing_mode: string;
  confusion_level: number;
  explanation_depth: number;
  metaphor_strategy: string;
  remediation_active: boolean;
}

export interface MotionState {
  cursor: CursorSnapshot;
  strokes: Stroke[];
  gestures: any[];
  focusState: {
    activeEffects: any[];
    globalDimLevel: number;
    focusedObjectIds: Set<string>;
  };
  narrationStatus: {
    progress: number;
    state: string;
    isAudioSynced: boolean;
  };
  phase: string;
}

export interface CheckpointState {
  active: boolean;
  questionText: string;
  nodeId: string;
  timestamp: number;
}

export interface ReviewState {
  active: boolean;
  concept: string;
  timestamp: number;
}

export interface MisconceptionEntry {
  id: string;
  concept: string;
  detectedAt: number;
}
