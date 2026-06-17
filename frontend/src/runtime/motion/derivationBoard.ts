/**
 * derivationBoard.ts — State and Page Tracking Core
 *
 * Manages spatial page boundaries, board visibility status,
 * and page completion locks. All geometric layout calculations
 * have been migrated to the backend (whiteboard_manager.py).
 */

export const LESSON_DERIVATION_ID = "lesson_derivation";

export interface DerivationSceneSlice {
  _mergedLatex?: string;
  _boardStepIds?: string[];
  _boardId?: string;
  _boardRole?: string;
  _writeMode?: string;
  startMs?: number;
}

export function resolvePedagogicalBoardId(payload: Record<string, any>, eqId: string): string {
  return (
    payload.board_id ||
    payload.derivation_id ||
    payload.metadata?.board_id ||
    payload.metadata?.derivation_id ||
    eqId ||
    LESSON_DERIVATION_ID
  );
}

export function getPedagogicalWriteMode(payload: Record<string, any>): string {
  return (
    payload.write_mode ||
    payload.metadata?.write_mode ||
    (payload.full_latex || payload.metadata?.full_latex
      ? "replace"
      : payload.append_latex || payload.metadata?.append_latex
        ? "append"
        : payload.accumulate === true || payload.metadata?.accumulate
          ? "append"
          : "create")
  );
}

export function shouldPatchBoard(payload: Record<string, any>, eqId: string): boolean {
  const writeMode = getPedagogicalWriteMode(payload);
  if (writeMode === "create") {
    return false;
  }
  if (["append", "replace", "transform"].includes(writeMode)) {
    return true;
  }
  if (payload.accumulate === true || payload.metadata?.accumulate) {
    return true;
  }
  const boardId =
    payload.board_id ||
    payload.derivation_id ||
    payload.metadata?.board_id ||
    payload.metadata?.derivation_id;
  if (boardId && boardId !== eqId) {
    return true;
  }
  return false;
}

export function shouldAccumulateDerivation(payload: Record<string, any>, eqId: string): boolean {
  return shouldPatchBoard(payload, eqId);
}

export function resolveDerivationBoardId(payload: Record<string, any>): string {
  return resolvePedagogicalBoardId(payload, LESSON_DERIVATION_ID);
}

export function resolveSceneObjectBoardId(obj: {
  id?: string;
  _boardId?: string;
  data?: Record<string, any>;
}): string | undefined {
  return obj._boardId || obj.data?.board_id || obj.data?.derivation_id;
}

export function shouldHideSupersededBoardObject(
  obj: { id: string; _boardId?: string; data?: Record<string, any>; _mergedLatex?: string },
  sceneObjects: Record<string, { id?: string; _boardStepIds?: string[]; _mergedLatex?: string }>
): boolean {
  if (obj._mergedLatex) return false;
  const boardId = resolveSceneObjectBoardId(obj);
  if (!boardId || obj.id === boardId) return false;
  const board = sceneObjects[boardId];
  if (!board?._mergedLatex) return false;
  const stepIds = board._boardStepIds;
  if (stepIds?.includes(obj.id)) return true;
  return resolveSceneObjectBoardId(board) === boardId;
}

export function pruneSupersededBoardObjects(
  sceneObjects: Record<string, any>,
  boardId: string,
  stepIds: string[],
  currentTimeMs?: number
): void {
  const board = sceneObjects[boardId];
  if (!board) return;

  for (const key of Object.keys(sceneObjects)) {
    if (key === boardId) continue;
    const obj = sceneObjects[key];
    
    // Playback guard: if object is still in its animation window, do not prune it yet
    if (currentTimeMs !== undefined && typeof obj.startMs === 'number') {
      const durationMs = obj.data?.duration_ms || obj.data?.total_duration_ms || 1000;
      const endMs = obj.startMs + durationMs;
      if (currentTimeMs < endMs) {
        continue;
      }
    }

    if (stepIds.includes(key)) {
      delete sceneObjects[key];
      continue;
    }
    const objBoardId = resolveSceneObjectBoardId(obj);
    if (objBoardId === boardId && !obj._mergedLatex) {
      delete sceneObjects[key];
    }
  }
}

export function resolveSceneStampFromPayload(
  payload: Record<string, any>,
  existing?: { sceneId?: string; pageIndex?: number }
): { sceneId?: string; pageIndex?: number } {
  const sceneIndex =
    payload.scene_index ?? payload.metadata?.scene_index ?? payload.sceneIndex;
  const sceneId =
    payload.scene_id ??
    payload.metadata?.scene_id ??
    (sceneIndex !== undefined ? `scene_${sceneIndex}` : existing?.sceneId);
  const pageIndex =
    sceneIndex !== undefined ? sceneIndex : existing?.pageIndex;
  return { sceneId, pageIndex };
}
