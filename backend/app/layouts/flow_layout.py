from __future__ import annotations
import math
from typing import Any, List, Dict
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel
from app.scene_graph.schemas import SceneRelationship
from app.layouts.layout_state import layout_state_cache
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)

def _densify_path(
    path: list,
    min_points: int = 40,
    pixels_per_point: float = 4.0,
) -> list:
    if not path or len(path) < 2:
        return [list(p) for p in path]

    pts = [[float(p[0]), float(p[1])] for p in path]

    arc_length = 0.0
    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        arc_length += math.sqrt(dx * dx + dy * dy)

    target = max(min_points, int(arc_length / pixels_per_point) + 1)
    if len(pts) >= target:
        return pts

    padded = [pts[0]] + pts + [pts[-1]]
    result = []
    n_segs = len(pts) - 1
    pps = max(2, target // max(1, n_segs))

    for seg in range(n_segs):
        p0, p1, p2, p3 = padded[seg], padded[seg+1], padded[seg+2], padded[seg+3]
        count = pps if seg < n_segs - 1 else pps + 1
        for k in range(count):
            t  = k / pps
            t2 = t * t; t3 = t2 * t
            x  = 0.5 * ((2*p1[0]) + (-p0[0]+p2[0])*t + (2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2 + (-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
            y  = 0.5 * ((2*p1[1]) + (-p0[1]+p2[1])*t + (2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2 + (-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
            result.append([x, y])

    if result and (result[-1][0] != pts[-1][0] or result[-1][1] != pts[-1][1]):
        result.append(list(pts[-1]))
    return result


class FlowLayoutStrategy(LayoutStrategy):
    """Layout strategy for sequential semantic flows, curves, and path movements."""

    TRAJ_MIN_PTS = 80

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout a flow path curve."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        diagram_id = "flow_path"
        color = "#E74C3C"

        h = flow_layout.estimate_diagram_height(diagram_type="default")
        pos = flow_layout.place(h, flow_layout.content_width, align="center", gap_after=60)

        # Generate a generic semantic sine curve flow across the page column
        points = [
            [pos.x + (pos.width * t / 10),
             pos.cy + 30 * math.sin(t * math.pi / 5)]
            for t in range(11)
        ]

        dense = _densify_path(points, min_points=self.TRAJ_MIN_PTS, pixels_per_point=4.0)
        
        return [SceneRelationship(
            id=diagram_id,
            source_id="start",
            target_id="end",
            x=pos.x,
            y=pos.cy,
            width=pos.width,
            height=h,
            relation_type="flow_curve",
            semantic_role="flow",
            properties={
                "path": dense,
                "color": color,
                "thickness": 2.5,
            }
        )]
