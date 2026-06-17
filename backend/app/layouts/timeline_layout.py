from __future__ import annotations
from typing import Any, List, Dict
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel, SemanticRole
from app.scene_graph.schemas import SceneEntity, SceneRelationship, SceneAnnotation
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)

class TimelineLayoutStrategy(LayoutStrategy):
    """Layout strategy for arranging temporal events along a timeline axis."""

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout events along a timeline."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        entities = world_model.entities
        if not entities:
            return []

        structure_id = "timeline"
        h = 100.0
        pos = flow_layout.place(h, flow_layout.content_width, align="center", gap_after=40)

        scene_elements = []
        
        # Main timeline axis line
        scene_elements.append(SceneRelationship(
            id=f"{structure_id}_axis",
            source_id="start",
            target_id="end",
            x=pos.x,
            y=pos.cy,
            width=pos.width,
            height=0,
            relation_type="axis",
            semantic_role="axis",
            properties={
                "stroke": "#555",
                "thickness": 4,
            }
        ))

        # Arrange event labels
        n = len(entities)
        spacing = pos.width / max(n, 1)
        for i, entity in enumerate(entities):
            ex = pos.x + i * spacing + spacing / 2
            scene_elements.append(SceneAnnotation(
                id=entity.id,
                text=entity.label,
                x=ex - 50,
                y=pos.cy - 30,
                width=100,
                height=30,
                properties={
                    "color": "#00D4FF",
                    "font_size": 12,
                    "duration_ms": 500
                }
            ))

        return scene_elements
