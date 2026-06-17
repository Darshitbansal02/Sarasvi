import * as PIXI from "pixi.js";
import type { CanvasTheme } from "./canvasRenderHelpers";

export function drawBoardGrid(
  g: PIXI.Graphics,
  boardWidth: number,
  boardHeight: number,
  isLive: boolean,
  theme: CanvasTheme,
): void {
  g.clear();
  g.roundRect(-8, -8, boardWidth + 16, boardHeight + 16, 24);
  g.fill({ color: isLive ? 0xf59e0b : 0x000000, alpha: isLive ? 0.08 : 0.3 });

  g.roundRect(0, 0, boardWidth, boardHeight, 16);
  g.fill({ color: theme.bg, alpha: 0.98 });

  g.roundRect(0, 0, boardWidth, boardHeight, 16);
  if (isLive) {
    g.stroke({ width: 2, color: 0xf59e0b, alpha: 0.4 });
  } else {
    g.stroke({ width: 2, color: theme.nodeStroke || 0x334155, alpha: 0.7 });
  }

  const dotSpacing = 45;
  for (let x = dotSpacing; x < boardWidth; x += dotSpacing) {
    for (let y = dotSpacing; y < boardHeight; y += dotSpacing) {
      g.circle(x, y, 1.2);
    }
  }
  g.fill({ color: theme.grid || 0x334155, alpha: theme.gridAlpha || 0.3 });
}
