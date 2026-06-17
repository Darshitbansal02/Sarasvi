from __future__ import annotations
from typing import Any, List, Dict, Optional
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel
from app.scene_graph.schemas import SceneEntity, SceneAnnotation
from app.layouts.layout_state import layout_state_cache
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)

class ContainmentLayoutStrategy(LayoutStrategy):
    """Layout strategy for containment-based nested container structures, generalized from stack memory regions."""

    CONTAINER_WIDTH = 280
    HEADER_HEIGHT = 30
    SLOT_ROW_HEIGHT = 25
    CONTAINER_PADDING = 10
    CONTAINER_SPACING = 15
    INDICATOR_WIDTH = 20
    INDICATOR_HEIGHT = 15

    def __init__(self) -> None:
        self._containers: List[Dict[str, Any]] = []
        self._positions: Dict[str, tuple[float, float]] = {}

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout containment structures within a generic sub-region."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        region_rect = region_mgr.get_region_rect("STACK_REGION") if region_mgr else None
        if region_rect is None:
            from app.layouts.spatial_region_manager import Rect
            region_rect = Rect(x=2500, y=100, width=600, height=2000)

        entities = world_model.entities
        if not entities:
            return []
            
        entity = entities[0]
        meta = entity.metadata

        container_id = entity.id
        header = entity.label or meta.get("object_type", "Container")
        slots = meta.get("fields", meta.get("locals", {}))
        indicators = meta.get("address", meta.get("return_address", ""))

        num_rows = len(slots) + 2
        container_height = (
            self.HEADER_HEIGHT
            + num_rows * self.SLOT_ROW_HEIGHT
            + self.CONTAINER_PADDING * 2
        )

        container_index = len(self._containers)
        x = region_rect.x + (region_rect.width - self.CONTAINER_WIDTH) / 2
        y = region_rect.y + 60

        for existing in self._containers:
            y += existing.get("height", self.HEADER_HEIGHT + 60) + self.CONTAINER_SPACING

        self._containers.append({
            "container_id": container_id,
            "height": container_height,
            "y": y,
        })
        self._positions[container_id] = (x, y)
        layout_state_cache.set_position(container_id, x, y)

        scene_elements = []

        # Outer containment container
        scene_elements.append(SceneEntity(
            id=container_id,
            label=header,
            x=x,
            y=y,
            width=self.CONTAINER_WIDTH,
            height=container_height,
            semantic_role="container",
            properties={
                "header": header,
                "slots": slots,
                "indicators": indicators,
                "container_index": container_index,
                "fill": "#0d1117",
                "stroke": "#30363d",
                "header_fill": "#161b22",
            }
        ))

        # Top tracking pointer/indicator annotation
        ind_x = x - self.INDICATOR_WIDTH - 10
        ind_y = y + container_height / 2 - self.INDICATOR_HEIGHT / 2
        scene_elements.append(SceneAnnotation(
            id=f"indicator_{container_id}",
            text="SP →",
            x=ind_x,
            y=ind_y,
            width=self.INDICATOR_WIDTH,
            height=self.INDICATOR_HEIGHT,
            properties={
                "target_container": container_id,
                "fill": "#FF6B6B",
                "color": "#FF6B6B",
                "visual_role": "pointer",
            }
        ))

        return scene_elements

    def pop_container(self) -> Optional[Dict[str, Any]]:
        """Remove the top (most recent) containment structure."""
        if self._containers:
            container = self._containers.pop()
            self._positions.pop(container["container_id"], None)
            layout_state_cache.remove(container["container_id"])
            return container
        return None

    def get_container_position(self, container_id: str) -> Optional[tuple[float, float]]:
        return self._positions.get(container_id)

    def get_return_bubble_path(
        self, from_container_id: str, to_container_id: str
    ) -> List[tuple[float, float]]:
        from_pos = self._positions.get(from_container_id)
        to_pos = self._positions.get(to_container_id)
        if not from_pos or not to_pos:
            return []

        mid_x = from_pos[0] + self.CONTAINER_WIDTH + 40
        return [
            (from_pos[0] + self.CONTAINER_WIDTH / 2, from_pos[1]),
            (mid_x, (from_pos[1] + to_pos[1]) / 2),
            (to_pos[0] + self.CONTAINER_WIDTH / 2, to_pos[1]),
        ]

    def reset(self) -> None:
        self._containers.clear()
        self._positions.clear()
