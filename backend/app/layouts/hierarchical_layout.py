from __future__ import annotations
from typing import Any, List, Dict
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel, SemanticRole
from app.scene_graph.schemas import SceneEntity, SceneRelationship
from app.layouts.layout_state import layout_state_cache
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)

class HierarchicalLayoutStrategy(LayoutStrategy):
    """Deterministic, configurable tree layout strategy utilizing layout state cache."""

    NODE_WIDTH = 80
    NODE_HEIGHT = 50
    H_SPACING = 40
    V_SPACING = 80

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout tree nodes using structural relations and layout preferences."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        entities = world_model.entities
        if not entities:
            return []

        # Read configuration from layout preferences
        prefs = descriptor.layout_preferences
        v_spacing = prefs.get("spacing", self.V_SPACING)

        # Estimate heights and position tree bounding area
        h = flow_layout.estimate_tree_height(len(entities))
        pos = flow_layout.place(h, flow_layout.content_width, align="center", gap_after=60)
        origin_x = pos.cx
        origin_y = pos.y + 60

        # Map parents to children from relationships
        parent_child_map: Dict[str, List[str]] = {}
        child_to_parent: Dict[str, str] = {}
        for rel in world_model.relationships:
            if rel.semantic_role == SemanticRole.CHILD or rel.relation_type == "branch":
                parent_child_map.setdefault(rel.source_id, []).append(rel.target_id)
                child_to_parent[rel.target_id] = rel.source_id

        # Find roots (entities with no parent)
        entity_ids = [e.id for e in entities]
        roots = [eid for eid in entity_ids if eid not in child_to_parent]
        if not roots and entity_ids:
            roots = [entity_ids[0]]

        positions: Dict[str, tuple[float, float, int]] = {}
        
        # Incremental Layout State support: if root is already cached, reuse or anchor nearby
        if roots and layout_state_cache.get_position(roots[0]) is not None:
            cached_root_pos = layout_state_cache.get_position(roots[0])
            if cached_root_pos:
                origin_x, origin_y = cached_root_pos

        # Compute positions recursively
        def position_tree(node_id: str, level: int, x: float, y: float, h_spread: float) -> None:
            positions[node_id] = (x, y, level)
            layout_state_cache.set_position(node_id, x, y)
            
            children = parent_child_map.get(node_id, [])
            if not children:
                return
            
            next_y = y + self.NODE_HEIGHT + v_spacing
            next_spread = h_spread * 0.55
            
            # Position children symmetrically
            num_children = len(children)
            if num_children == 1:
                position_tree(children[0], level + 1, x, next_y, next_spread)
            elif num_children > 1:
                start_x = x - h_spread * (num_children - 1) / 2
                for i, child_id in enumerate(children):
                    child_x = start_x + i * h_spread
                    position_tree(child_id, level + 1, child_x, next_y, next_spread)

        for root in roots:
            position_tree(root, 0, origin_x, origin_y, 250.0)

        scene_elements = []
        for entity in entities:
            pos_info = positions.get(entity.id, (origin_x, origin_y, 0))
            scene_elements.append(SceneEntity(
                id=entity.id,
                label=entity.label,
                x=pos_info[0] - self.NODE_WIDTH / 2,
                y=pos_info[1],
                width=self.NODE_WIDTH,
                height=self.NODE_HEIGHT,
                semantic_role="entity",
                properties={
                    "highlighted": entity.metadata.get("highlight", False),
                    "fill": "#00D4FF" if entity.metadata.get("highlight") else "#1a1a2e",
                    "stroke": "#00D4FF",
                }
            ))

        # Create relationships using SceneRelationship
        for idx, rel in enumerate(world_model.relationships):
            source_pos = positions.get(rel.source_id)
            target_pos = positions.get(rel.target_id)
            if source_pos and target_pos:
                scene_elements.append(SceneRelationship(
                    id=rel.id,
                    source_id=rel.source_id,
                    target_id=rel.target_id,
                    x=source_pos[0],
                    y=source_pos[1] + self.NODE_HEIGHT,
                    width=target_pos[0] - source_pos[0],
                    height=target_pos[1] - source_pos[1] - self.NODE_HEIGHT,
                    relation_type=rel.relation_type,
                    semantic_role="hierarchical",
                    properties={"stroke": "#444"}
                ))

        return scene_elements
