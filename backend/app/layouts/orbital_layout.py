from __future__ import annotations
import math
from typing import Any, List, Dict
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel, SemanticRole
from app.scene_graph.schemas import SceneEntity, SceneRelationship
from app.layouts.layout_state import layout_state_cache
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)

class OrbitalLayoutStrategy(LayoutStrategy):
    """Layout strategy for satellite bodies revolving or organized in concentric rings around a central anchor."""

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout concentric rings of orbital satellites."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        entities = world_model.entities
        if not entities:
            return []

        h = flow_layout.estimate_diagram_height(diagram_type="default")
        pos = flow_layout.place(h, flow_layout.content_width, align="center", gap_after=60)
        cx, cy = pos.cx, pos.cy

        structure_id = "orbital"
        
        # Center Anchor Entity
        center_node = next((e for e in entities if e.semantic_role == SemanticRole.ANCHOR), entities[0])
        center_id = center_node.id
        
        cached_pos = layout_state_cache.get_position(center_id)
        if cached_pos:
            cx, cy = cached_pos
        layout_state_cache.set_position(center_id, cx, cy)

        scene_elements = []
        scene_elements.append(SceneEntity(
            id=center_id,
            label=center_node.label,
            x=cx - 35,
            y=cy - 35,
            width=70,
            height=70,
            semantic_role="anchor",
            properties={
                "fill": "#8e44ad",
                "stroke": "#00D4FF",
            }
        ))

        # Lay out satellites along the orbital rings
        satellites = [e for e in entities if e.id != center_id]
        ring_radius = 80.0
        n = max(len(satellites), 1)

        for i, sat in enumerate(satellites):
            angle = (i * (2 * math.pi / n))
            tx = cx + math.cos(angle) * ring_radius
            ty = cy - math.sin(angle) * ring_radius
            
            layout_state_cache.set_position(sat.id, tx, ty)
            
            scene_elements.append(SceneEntity(
                id=sat.id,
                label=sat.label,
                x=tx - 15,
                y=ty - 15,
                width=30,
                height=30,
                semantic_role="orbiter",
                properties={
                    "fill": "#3498db",
                    "stroke": "#00D4FF",
                }
            ))

            # Connect center to satellite
            rel = next((r for r in world_model.relationships if r.target_id == sat.id or r.source_id == sat.id), None)
            rel_id = rel.id if rel else f"orbital_rel_{center_id}_{sat.id}"
            rel_type = rel.relation_type if rel else "orbit"
            
            scene_elements.append(SceneRelationship(
                id=rel_id,
                source_id=center_id,
                target_id=sat.id,
                x=cx,
                y=cy,
                width=tx - cx,
                height=ty - cy,
                relation_type=rel_type,
                semantic_role="orbit",
                properties={
                    "directed": False,
                    "stroke": "#ecf0f1",
                }
            ))

        return scene_elements
