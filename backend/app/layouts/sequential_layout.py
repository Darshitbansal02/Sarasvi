from __future__ import annotations
from typing import Any, List, Dict
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel
from app.scene_graph.schemas import SceneEntity, SceneRelationship
from app.layouts.layout_state import layout_state_cache
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)

class SequentialLayoutStrategy(LayoutStrategy):
    """Deterministic, configurable sequential/linear layout strategy utilizing layout state cache."""

    NODE_WIDTH = 120
    NODE_HEIGHT = 60
    POINTER_SECTION_WIDTH = 40
    H_SPACING = 60

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout entities horizontally in sequential flow order."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        entities = world_model.entities
        if not entities:
            return []

        # Read configuration from layout preferences
        prefs = descriptor.layout_preferences
        h_spacing = prefs.get("spacing", self.H_SPACING)

        # Estimate heights and position linear layout
        h = flow_layout.estimate_list_height(len(entities))
        pos = flow_layout.place(h, flow_layout.content_width, align="left", gap_after=60)
        origin_x = pos.x + 40
        origin_y = pos.cy

        total_width = self.NODE_WIDTH + self.POINTER_SECTION_WIDTH

        # Check layout state cache to anchor start position if previously rendered
        if entities and layout_state_cache.get_position(entities[0].id) is not None:
            cached_pos = layout_state_cache.get_position(entities[0].id)
            if cached_pos:
                origin_x, _ = cached_pos

        scene_elements = []

        # Calculate coordinate maps
        positions: Dict[str, tuple[float, float]] = {}
        for i, entity in enumerate(entities):
            x = origin_x + i * (total_width + h_spacing)
            y = origin_y - self.NODE_HEIGHT / 2
            positions[entity.id] = (x, y)
            layout_state_cache.set_position(entity.id, x, y)

            is_highlighted = entity.metadata.get("highlight", False)
            scene_elements.append(SceneEntity(
                id=entity.id,
                label=entity.label,
                x=x,
                y=y,
                width=total_width,
                height=self.NODE_HEIGHT,
                semantic_role="slot",
                properties={
                    "index": i,
                    "highlighted": is_highlighted,
                    "fill": "#00D4FF" if is_highlighted else "#1a1a2e",
                    "stroke": "#00D4FF",
                    "pointer_section_width": self.POINTER_SECTION_WIDTH
                }
            ))

        # Create sequential flow relationships
        for idx, rel in enumerate(world_model.relationships):
            src_pos = positions.get(rel.source_id)
            tgt_pos = positions.get(rel.target_id)
            if src_pos and tgt_pos:
                arrow_start_x = src_pos[0] + total_width
                arrow_end_x = tgt_pos[0]
                scene_elements.append(SceneRelationship(
                    id=rel.id,
                    source_id=rel.source_id,
                    target_id=rel.target_id,
                    x=arrow_start_x,
                    y=origin_y,
                    width=arrow_end_x - arrow_start_x,
                    height=0,
                    relation_type=rel.relation_type,
                    semantic_role="pointer",
                    properties={
                        "stroke": "#555",
                        "directed": True
                    }
                ))

        return scene_elements
