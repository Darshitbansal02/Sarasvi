from __future__ import annotations
import math
from typing import Any, List, Dict
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel
from app.scene_graph.schemas import SceneEntity, SceneRelationship, SceneAnnotation
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


class VectorFieldLayoutStrategy(LayoutStrategy):
    """Layout strategy for rendering domain-agnostic vector alignments, magnitudes, and directional paths."""

    ARROW_MIN_PTS = 50

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout vectors according to the parsed representation method."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        entities = world_model.entities
        relationships = world_model.relationships
        if not entities:
            return []

        diagram_id = "vector_field"
        
        # Center-anchored vectors
        h = flow_layout.estimate_diagram_height(n_vectors=len(relationships), diagram_type="default")
        pos = flow_layout.place(h, flow_layout.content_width, align="center", gap_after=60)
        
        # Use state cache to anchor center position
        cx, cy = pos.cx, pos.cy
        center_id = entities[0].id
        cached_pos = layout_state_cache.get_position(center_id)
        if cached_pos:
            cx, cy = cached_pos
            
        layout_state_cache.set_position(center_id, cx, cy)

        scene_elements = []
        scene_elements.append(SceneEntity(
            id=center_id,
            label=entities[0].label,
            x=cx - 40,
            y=cy - 40,
            width=80,
            height=80,
            semantic_role="anchor",
            properties={
                "fill": "#2c3e50",
                "stroke": "#00D4FF",
            }
        ))

        for i, rel in enumerate(relationships):
            meta = rel.metadata
            angle = math.radians(meta.get("direction", 0))
            mag = meta.get("magnitude", 10) * 12
            tx, ty = cx + math.cos(angle) * mag, cy - math.sin(angle) * mag
            theta = math.atan2(ty - cy, tx - cx)
            ha = math.pi / 6.0
            hl = 14.0
            x1 = tx - hl * math.cos(theta - ha); y1 = ty - hl * math.sin(theta - ha)
            x2 = tx - hl * math.cos(theta + ha); y2 = ty - hl * math.sin(theta + ha)
            dense = _densify_path([(cx, cy), (tx, ty), (x1, y1), (tx, ty), (x2, y2)],
                                  min_points=self.ARROW_MIN_PTS, pixels_per_point=4.0)
            fc = meta.get("color", "coral")
            
            scene_elements.append(SceneRelationship(
                id=rel.id,
                source_id=center_id,
                target_id=rel.target_id,
                x=cx,
                y=cy,
                width=tx - cx,
                height=ty - cy,
                relation_type=rel.relation_type,
                semantic_role="vector",
                properties={
                    "path": dense,
                    "color": fc,
                    "thickness": 2.5,
                }
            ))
            
            lx = tx + 18 * math.cos(theta); ly = ty - 18 * math.sin(theta)
            scene_elements.append(SceneAnnotation(
                id=f"{rel.id}_label",
                text=meta.get("label", str(meta.get("magnitude", ""))),
                x=lx - 30,
                y=ly - 15,
                width=80,
                height=30,
                properties={
                    "color": fc,
                    "font_size": 14,
                    "duration_ms": 600
                }
            ))
            
        return scene_elements
