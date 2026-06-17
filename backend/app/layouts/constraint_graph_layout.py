from __future__ import annotations
import math
import random
from typing import Any, List, Dict
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel
from app.scene_graph.schemas import SceneEntity, SceneRelationship
from app.layouts.spatial_region_manager import Rect
from app.layouts.layout_state import layout_state_cache
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)

class ConstraintGraphLayoutStrategy(LayoutStrategy):
    """Deterministic, configurable graph layout strategy with circular, radial, hierarchical and force-directed algorithms."""

    NODE_RADIUS = 30
    EDGE_LENGTH = 150

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout a graph using the parsed representation method."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        entities = world_model.entities
        relationships = world_model.relationships
        if not entities:
            return []

        layout_algorithm = descriptor.representation

        if layout_algorithm == "radial":
            h = flow_layout.estimate_diagram_height(diagram_type="default")
            pos = flow_layout.place(h, flow_layout.content_width, align="center", gap_after=60)
            cx, cy = pos.cx, pos.cy
            radius = min(110.0, pos.width / 3)
            return self._layout_radial(entities, relationships, cx, cy, radius)

        # General layouts
        h = flow_layout.estimate_tree_height(len(entities))
        pos = flow_layout.place(h, flow_layout.content_width, align="center", gap_after=60)
        region = Rect(pos.x, pos.y, pos.width, h)

        if layout_algorithm == "circular":
            positions = self._circular_layout(entities, region)
        elif layout_algorithm == "hierarchical":
            positions = self._hierarchical_layout(entities, relationships, region)
        else:
            positions = self._force_directed_layout(entities, relationships, region)

        scene_elements = []

        # Create node entities
        for entity in entities:
            pos_coord = positions.get(entity.id, (region.center_x, region.center_y))
            # Cache coordinate state
            layout_state_cache.set_position(entity.id, pos_coord[0], pos_coord[1])
            scene_elements.append(SceneEntity(
                id=entity.id,
                label=entity.label,
                x=pos_coord[0] - self.NODE_RADIUS,
                y=pos_coord[1] - self.NODE_RADIUS,
                width=self.NODE_RADIUS * 2,
                height=self.NODE_RADIUS * 2,
                semantic_role="entity",
                properties={
                    "fill": "#1a1a2e",
                    "stroke": "#00D4FF",
                }
            ))

        # Create relationship connectors
        for i, rel in enumerate(relationships):
            from_pos = positions.get(rel.source_id, (0, 0))
            to_pos = positions.get(rel.target_id, (0, 0))
            scene_elements.append(SceneRelationship(
                id=rel.id,
                source_id=rel.source_id,
                target_id=rel.target_id,
                x=from_pos[0],
                y=from_pos[1],
                width=to_pos[0] - from_pos[0],
                height=to_pos[1] - from_pos[1],
                relation_type=rel.relation_type,
                semantic_role="network",
                properties={
                    "stroke": "#555",
                    "directed": rel.metadata.get("directed", False),
                    "weight": rel.metadata.get("weight"),
                }
            ))

        return scene_elements

    def _layout_radial(
        self,
        entities: List[Any],
        relationships: List[Any],
        cx: float,
        cy: float,
        radius: float
    ) -> List[Any]:
        """Compute coordinates for central satellite/radial graph relationships without chemistry hardcodings."""
        scene_elements = []
        center_node = entities[0]
        center_id = center_node.id
        center_label = center_node.label
        
        # Check cache for central anchor coordinate stability
        cached_center = layout_state_cache.get_position(center_id)
        if cached_center:
            cx, cy = cached_center
            
        layout_state_cache.set_position(center_id, cx, cy)

        scene_elements.append(SceneEntity(
            id=center_id,
            label=center_label,
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

        outer_nodes = entities[1:]
        n = max(len(outer_nodes), 1)
        for i, node in enumerate(outer_nodes):
            nid = node.id
            nlabel = node.label
            
            angle = (i * (2 * math.pi / n)) + (math.pi / 2 if n == 2 else 0)
            tx = cx + math.cos(angle) * radius
            ty = cy - math.sin(angle) * radius
            
            layout_state_cache.set_position(nid, tx, ty)

            scene_elements.append(SceneEntity(
                id=nid,
                label=nlabel,
                x=tx - 25,
                y=ty - 25,
                width=50,
                height=50,
                semantic_role="orbiter",
                properties={
                    "fill": "#3498db",
                    "stroke": "#00D4FF",
                }
            ))
            
            # Find the corresponding relationship
            rel = next((r for r in relationships if r.target_id == nid or r.source_id == nid), None)
            rel_id = rel.id if rel else f"radial_edge_{center_id}_{nid}"
            rel_type = rel.relation_type if rel else "covalent_bond"
            scene_elements.append(SceneRelationship(
                id=rel_id,
                source_id=center_id,
                target_id=nid,
                x=cx,
                y=cy,
                width=tx - cx,
                height=ty - cy,
                relation_type=rel_type,
                semantic_role="network",
                properties={
                    "directed": False,
                    "stroke": "#ecf0f1",
                }
            ))

        return scene_elements

    def _circular_layout(
        self, entities: List[Any], region: Rect
    ) -> Dict[str, tuple[float, float]]:
        positions = {}
        n = len(entities)
        radius = min(region.width, region.height) * 0.35
        cx, cy = region.center_x, region.center_y

        for i, ent in enumerate(entities):
            angle = 2 * math.pi * i / n - math.pi / 2
            positions[ent.id] = (
                cx + radius * math.cos(angle),
                cy + radius * math.sin(angle),
            )
        return positions

    def _hierarchical_layout(
        self, entities: List[Any], relationships: List[Any], region: Rect
    ) -> Dict[str, tuple[float, float]]:
        positions = {}
        node_ids = [e.id for e in entities]
        levels: Dict[str, int] = {nid: 0 for nid in node_ids}

        for rel in relationships:
            if rel.target_id in levels and rel.source_id in levels:
                levels[rel.target_id] = max(levels[rel.target_id], levels[rel.source_id] + 1)

        level_groups: Dict[int, List[str]] = {}
        for nid, lvl in levels.items():
            level_groups.setdefault(lvl, []).append(nid)

        max_level = max(level_groups.keys()) if level_groups else 0
        v_spacing = region.height / (max_level + 2)

        for lvl, nids in level_groups.items():
            h_spacing = region.width / (len(nids) + 1)
            for i, nid in enumerate(nids):
                positions[nid] = (
                    region.x + h_spacing * (i + 1),
                    region.y + v_spacing * (lvl + 1),
                )
        return positions

    def _force_directed_layout(
        self, entities: List[Any], relationships: List[Any], region: Rect,
        iterations: int = 50,
    ) -> Dict[str, tuple[float, float]]:
        rng = random.Random(42)
        positions: Dict[str, List[float]] = {}
        node_ids = []

        for ent in entities:
            node_ids.append(ent.id)
            cached_pos = layout_state_cache.get_position(ent.id)
            if cached_pos:
                positions[ent.id] = [cached_pos[0], cached_pos[1]]
            else:
                positions[ent.id] = [
                    region.x + rng.random() * region.width,
                    region.y + rng.random() * region.height,
                ]

        edge_pairs = []
        for rel in relationships:
            edge_pairs.append((rel.source_id, rel.target_id))

        k = math.sqrt(region.width * region.height / max(len(entities), 1))
        temp = region.width / 10

        for _ in range(iterations):
            disp = {nid: [0.0, 0.0] for nid in node_ids}
            for i, u in enumerate(node_ids):
                for v in node_ids[i + 1:]:
                    dx = positions[u][0] - positions[v][0]
                    dy = positions[u][1] - positions[v][1]
                    dist = max(math.sqrt(dx * dx + dy * dy), 0.01)
                    force = k * k / dist
                    fx, fy = force * dx / dist, force * dy / dist
                    disp[u][0] += fx
                    disp[u][1] += fy
                    disp[v][0] -= fx
                    disp[v][1] -= fy

            for u, v in edge_pairs:
                if u in positions and v in positions:
                    dx = positions[u][0] - positions[v][0]
                    dy = positions[u][1] - positions[v][1]
                    dist = max(math.sqrt(dx * dx + dy * dy), 0.01)
                    force = dist * dist / k
                    fx, fy = force * dx / dist, force * dy / dist
                    disp[u][0] -= fx
                    disp[u][1] -= fy
                    disp[v][0] += fx
                    disp[v][1] += fy

            for nid in node_ids:
                dx, dy = disp[nid]
                dist = max(math.sqrt(dx * dx + dy * dy), 0.01)
                positions[nid][0] += min(dx / dist, temp) * (dx / dist)
                positions[nid][1] += min(dy / dist, temp) * (dy / dist)
                positions[nid][0] = max(region.x + 50, min(region.right - 50, positions[nid][0]))
                positions[nid][1] = max(region.y + 50, min(region.bottom - 50, positions[nid][1]))

            temp *= 0.95

        return {nid: (pos[0], pos[1]) for nid, pos in positions.items()}
