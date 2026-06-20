/**
 * boardConstants.ts — Single source of truth for whiteboard geometry.
 *
 * These MUST stay identical to the backend layout engine
 * (`backend/app/layouts/document_flow.py`: PAGE_W / PAGE_H). The backend
 * assigns every absolute coordinate in this 1200×750 board space and arranges
 * pages horizontally at x = pageIndex × PAGE_W. The frontend is a pure
 * renderer of those coordinates, so any divergence here silently desyncs
 * rendering from layout. Change in lockstep with the backend.
 */

/** Visible board width in canvas units (backend PAGE_W). 1 unit = 1 px at fitScale 1. */
export const BOARD_WIDTH = 1200;

/** Visible board height in canvas units (backend PAGE_H). */
export const BOARD_HEIGHT = 750;

/** Horizontal page stride: page N starts at canvas x = N × PAGE_W. Equals BOARD_WIDTH. */
export const PAGE_W = BOARD_WIDTH;

/** Canvas x-offset of a given page's left edge. */
export const pageOffsetX = (pageIndex: number): number => pageIndex * PAGE_W;
