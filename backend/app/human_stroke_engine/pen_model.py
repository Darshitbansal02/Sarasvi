import math
from typing import List, Tuple, Dict, Any

class PenDynamicsModel:
    @staticmethod
    def compute_stroke_dynamics(points: List[Tuple[float, float]], base_thickness: float = 2.0, is_diagram: bool = False) -> List[Dict[str, Any]]:
        """
        Computes velocity, dynamic pressure (P = c / v), and tapering for a stroke path.
        Returns a list of point dictionaries: [{'x': x, 'y': y, 'pressure': p, 'thickness': t}]
        """
        if not points:
            return []
        if len(points) == 1:
            return [{"x": points[0][0], "y": points[0][1], "pressure": 0.7, "thickness": base_thickness}]

        output = []
        n = len(points)

        # Closed-loop detection: a silhouette outline (apple, heart, leaf, cell…) ends
        # where it began. Such strokes must NOT taper their endpoints — the start and end
        # are the same physical point on the contour, so tapering them to a thin lift-off
        # pinches a visible gap at the seam. Instead we keep full weight through the seam
        # and read curvature with wrap-around neighbours so the join is continuous.
        is_closed = (
            n >= 4
            and abs(points[0][0] - points[-1][0]) < 1.5
            and abs(points[0][1] - points[-1][1]) < 1.5
        )

        # Pre-compute segment vectors for curvature calculation
        segs: list[tuple[float, float, float]] = []  # (dx, dy, length)
        for i in range(n - 1):
            dx = points[i+1][0] - points[i][0]
            dy = points[i+1][1] - points[i][1]
            segs.append((dx, dy, math.hypot(dx, dy) or 0.001))

        for i in range(n):
            x, y = points[i]

            if is_diagram:
                # Clean diagram lines: constant moderate pressure
                pressure = 0.82
                taper_limit = 1
            else:
                # Curvature-based pressure: sharp turns → slower pen → higher pressure.
                # Raw inter-point distance was always ~4px for densified paths, giving
                # constant minimum pressure regardless of shape geometry. Curvature
                # (angular change between consecutive segments) correctly captures where
                # a real hand would press harder (corners) vs lighter (straight runs).
                if n < 3:
                    curvature = 0.0
                elif i == 0 or i == n - 1:
                    # Endpoints: on a closed loop, read curvature across the seam using
                    # wrap-around neighbours; on an open stroke there is no turn to measure.
                    if is_closed:
                        dx1, dy1, l1 = segs[-1]      # incoming segment (…→ last==first)
                        dx2, dy2, l2 = segs[0]       # outgoing segment (first → next)
                        dot = (dx1 * dx2 + dy1 * dy2) / (l1 * l2)
                        curvature = 1.0 - max(-1.0, min(1.0, dot))
                    else:
                        curvature = 0.0
                else:
                    dx1, dy1, l1 = segs[i - 1]
                    dx2, dy2, l2 = segs[i]
                    dot = (dx1 * dx2 + dy1 * dy2) / (l1 * l2)
                    # curvature: 0 = perfectly straight, 1 = 90° turn, 2 = U-turn
                    curvature = 1.0 - max(-1.0, min(1.0, dot))
                pressure = max(0.45, min(0.96, 0.55 + curvature * 0.38))
                taper_limit = 4

            # Boundary taper: lift-off at stroke start and end — but only for OPEN strokes.
            # Closed silhouettes keep full weight through the seam so the loop stays unbroken.
            if not is_closed:
                if i < taper_limit:
                    taper_factor = (i + 1) / (taper_limit + 1)
                    pressure *= taper_factor
                elif i >= n - taper_limit:
                    taper_factor = (n - i) / (taper_limit + 1)
                    pressure *= taper_factor

            thickness = base_thickness * (0.6 + 0.8 * pressure)
            
            output.append({
                "x": x,
                "y": y,
                "pressure": round(pressure, 3),
                "thickness": round(thickness, 2)
            })

        return output
