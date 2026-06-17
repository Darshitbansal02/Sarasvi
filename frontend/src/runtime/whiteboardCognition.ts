/**
 * whiteboardCognition.ts — Whiteboard Cognition & Spatial Memory Engine
 *
 * Manages spatial layouts, region occupancy, camera panning to clean panels,
 * and choreographed erasures to prevent visual clutter.
 */

import { useRuntimeStore } from "./runtimeStore";

interface SpatialRegion {
  id: number;
  name: string;
  xRange: [number, number];
  yRange: [number, number];
  occupied: boolean;
  lastUsedMs: number;
  objects: Set<string>;
}

class WhiteboardCognition {
  private regions: SpatialRegion[] = [];
  private currentRegionId: number = 0;

  constructor() {
    // 2D Spatial Panels (Memory Regions)
    this.regions = [
      {
        id: 0,
        name: "Panel A",
        xRange: [0, 800],
        yRange: [0, 600],
        occupied: false,
        lastUsedMs: 0,
        objects: new Set(),
      },
      {
        id: 1,
        name: "Panel B",
        xRange: [950, 1750],
        yRange: [0, 600],
        occupied: false,
        lastUsedMs: 0,
        objects: new Set(),
      },
      {
        id: 2,
        name: "Panel C",
        xRange: [1900, 2700],
        yRange: [0, 600],
        occupied: false,
        lastUsedMs: 0,
        objects: new Set(),
      },
      {
        id: 3,
        name: "Panel D",
        xRange: [0, 800],
        yRange: [750, 1350],
        occupied: false,
        lastUsedMs: 0,
        objects: new Set(),
      },
      {
        id: 4,
        name: "Panel E",
        xRange: [950, 1750],
        yRange: [750, 1350],
        occupied: false,
        lastUsedMs: 0,
        objects: new Set(),
      },
      {
        id: 5,
        name: "Panel F",
        xRange: [1900, 2700],
        yRange: [750, 1350],
        occupied: false,
        lastUsedMs: 0,
        objects: new Set(),
      },
    ];
  }

  /**
   * Register a scene object into a spatial memory region.
   */
  registerObject(objId: string, x: number, y: number): void {
    if (x === undefined || y === undefined) return;

    const region =
      this.regions.find(
        (r) => x >= r.xRange[0] && x <= r.xRange[1] && y >= r.yRange[0] && y <= r.yRange[1]
      ) || this.regions[this.currentRegionId];

    region.objects.add(objId);
    region.occupied = true;
    region.lastUsedMs = Date.now();
  }

  /**
   * Monitor visual density and manage board clutter.
   *
   * Page advancement and clutter clearing are AUTHORITATIVE on the backend
   * (whiteboard_manager scene transitions + explicit clear/delete events, which the
   * renderer already plays back). The frontend therefore no longer makes autonomous
   * pan/erase *decisions* — doing so double-controlled paging and could fight the
   * backend's page-lock. registerObject() still tracks spatial memory (passive).
   * Flip FRONTEND_AUTONOMOUS_CLUTTER back to true only to restore client-side
   * clutter management (e.g. if the backend stops emitting transitions).
   */


  /**
   * Clear region contents
   */
  clearRegion(regionId: number): void {
    if (regionId >= 0 && regionId < this.regions.length) {
      this.regions[regionId].objects.clear();
      this.regions[regionId].occupied = false;
    }
  }

  /**
   * Get current region
   */
  getCurrentRegion(): SpatialRegion {
    return this.regions[this.currentRegionId];
  }

  /**
   * Reset all regions
   */
  reset(): void {
    this.regions.forEach((r) => {
      r.objects.clear();
      r.occupied = false;
      r.lastUsedMs = 0;
    });
    this.currentRegionId = 0;
  }
}

export const whiteboardCognition = new WhiteboardCognition();
