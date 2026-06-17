/**
 * cameraCognition.ts — Cinematic Pedagogical Camera Engine (Stateless Interpolation Player)
 *
 * Frontend simply plays back and interpolates towards the backend-defined target viewports.
 * Direct positioning decisions and deadzones are owned authoritatively on the backend.
 */

import { useRuntimeStore } from "../runtimeStore";

export type CameraMode = "follow" | "wide" | "macro" | "cinematic";

export class CameraCognition {
  private targetX: number = 600;
  private targetY: number = 375;
  private targetZoom: number = 1.0;
  
  public currentX: number = 600;
  public currentY: number = 375;
  public currentZoom: number = 1.0;

  public mode: CameraMode = "follow";

  /**
   * Smoothly interpolate toward target coordinates defined by backend timeline events.
   */
  public update(cursor: any, sceneObjects: any, deltaMs: number): void {
    const store = useRuntimeStore.getState();
    if (!store.cameraLocked) return;

    // Smooth critical damping interpolation toward backend authoritative target
    this.currentX += (this.targetX - this.currentX) * 0.08;
    this.currentY += (this.targetY - this.currentY) * 0.08;
    this.currentZoom += (this.targetZoom - this.currentZoom) * 0.08;

    useRuntimeStore.setState({
      camera: {
        x: this.currentX,
        y: this.currentY,
        zoom: this.currentZoom
      }
    });
  }

  /**
   * Updates camera destination coordinates directly from the timeline playback events.
   */
  public triggerReveal(centerX: number, centerY: number, targetZoom: number = 1.0): void {
    this.targetX = centerX;
    this.targetY = centerY;
    this.targetZoom = targetZoom;
  }
}

export const cameraCognition = new CameraCognition();