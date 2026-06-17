"""
Spatial Region Manager — allocates deterministic board regions.

The whiteboard is divided into dedicated spatial regions:
- MAIN_VISUAL_REGION: Primary explanation and diagram area
- STACK_REGION: Stack frame memory visualization
- HEAP_REGION: Heap object visualization
- CODE_REGION: Code display area
- OUTPUT_REGION: Program output

Prevents overlap between educational diagrams and memory visualizations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Rect:
    """A rectangular region on the board."""
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.right and self.y <= y <= self.bottom

    def overlaps(self, other: "Rect") -> bool:
        return not (
            self.right < other.x
            or other.right < self.x
            or self.bottom < other.y
            or other.bottom < self.y
        )

    def expand(self, padding: float) -> "Rect":
        return Rect(
            x=self.x - padding,
            y=self.y - padding,
            width=self.width + 2 * padding,
            height=self.height + 2 * padding,
        )


@dataclass
class RegionConfig:
    """Configuration for a spatial region."""
    name: str
    rect: Rect
    max_objects: int = 50
    is_expandable: bool = False  # Can grow vertically (e.g., stack)
    z_index: int = 0


class SpatialRegionManager:
    """
    Manages spatial regions on the whiteboard.
    Reserves board areas and enforces layout boundaries.
    """

    # Default board size — matches frontend boardWidth/boardHeight (1200 × 750).
    BOARD_WIDTH = 1200
    BOARD_HEIGHT = 750
    PADDING = 15

    def __init__(self):
        self._regions: dict[str, RegionConfig] = {}
        self._allocations: dict[str, list[str]] = {}  # region → [shape_ids]
        self._initialize_default_regions()

    def _initialize_default_regions(self):
        """
        Set up default regions.

        Layout philosophy (1200 × 750 board per page — matches frontend boardWidth/boardHeight):
        - MAIN_VISUAL_REGION covers the full usable writing area.
          CS lessons additionally reserve STACK_REGION / CODE_REGION on the right;
          for all other domains those right-side columns are available to MAIN.
        - Overflow detection (_maybe_advance_scene_for_shapes) fires when content
          exceeds MAIN_VISUAL_REGION.bottom, triggering a new page.
          With 675px of usable height and ~30px average annotation rows,
          that gives ~22 annotation rows per page before overflow.
        """

        # Main visual region — full usable board width × height.
        # Right 270px reserved for STACK/CODE in CS; all other domains use full width.
        self._register_region(
            RegionConfig(
                name="MAIN_VISUAL_REGION",
                rect=Rect(x=24, y=20, width=840, height=675),
                max_objects=200,
                is_expandable=False,
                z_index=1,
            )
        )

        # Equation / formula column — centre-left, deep vertical for derivations.
        self._register_region(
            RegionConfig(
                name="FORMULA_REGION",
                rect=Rect(x=24, y=20, width=840, height=675),
                max_objects=100,
                is_expandable=False,
                z_index=3,
            )
        )

        # Stack region — far right, expandable downward for call-stack visualisation.
        self._register_region(
            RegionConfig(
                name="STACK_REGION",
                rect=Rect(x=870, y=20, width=270, height=675),
                max_objects=40,
                is_expandable=True,
                z_index=2,
            )
        )

        # Heap region — bottom-right corner for heap object visualisation.
        self._register_region(
            RegionConfig(
                name="HEAP_REGION",
                rect=Rect(x=870, y=500, width=270, height=200),
                max_objects=30,
                z_index=2,
            )
        )

        # Code region — right column for code blocks and pseudocode.
        self._register_region(
            RegionConfig(
                name="CODE_REGION",
                rect=Rect(x=870, y=20, width=270, height=450),
                max_objects=8,
                z_index=3,
            )
        )

        # Output / result region — bottom strip.
        self._register_region(
            RegionConfig(
                name="OUTPUT_REGION",
                rect=Rect(x=24, y=575, width=810, height=115),
                max_objects=20,
                z_index=1,
            )
        )

        # Field region — lower-left for physics / force diagrams.
        self._register_region(
            RegionConfig(
                name="FIELD_REGION",
                rect=Rect(x=24, y=150, width=840, height=475),
                max_objects=60,
                z_index=2,
            )
        )

        # Algorithm / graph / molecular diagram region.
        self._register_region(
            RegionConfig(
                name="ALGORITHM_REGION",
                rect=Rect(x=24, y=75, width=840, height=550),
                max_objects=60,
                z_index=2,
            )
        )

        # Graph region — for mathematical function plots and charts.
        self._register_region(
            RegionConfig(
                name="GRAPH_REGION",
                rect=Rect(x=24, y=75, width=840, height=550),
                max_objects=30,
                z_index=2,
            )
        )

    def configure_for_domain(self, domain: str) -> None:
        """
        Reconfigure region widths for the active teaching domain.

        CS domains (computer_science, algorithms) use right-side columns
        for STACK_REGION and CODE_REGION; all other domains give the full
        width to MAIN_VISUAL_REGION so diagrams and prose have more space.
        """
        cs_domains = {"computer_science", "algorithms", "data_structures"}
        if domain.lower() in cs_domains:
            # CS layout: left 810px for content, right 270px for stack/code
            self._regions["MAIN_VISUAL_REGION"].rect = Rect(
                x=24, y=20, width=810, height=675
            )
            self._regions["FORMULA_REGION"].rect = Rect(
                x=24, y=20, width=810, height=675
            )
        else:
            # Universal layout: MAIN uses full usable width (1128px)
            self._regions["MAIN_VISUAL_REGION"].rect = Rect(
                x=24, y=20, width=1128, height=675
            )
            self._regions["FORMULA_REGION"].rect = Rect(
                x=24, y=20, width=1128, height=675
            )

    def _register_region(self, config: RegionConfig):
        """Register a region."""
        self._regions[config.name] = config
        self._allocations[config.name] = []

    def get_region(self, name: str) -> Optional[RegionConfig]:
        """Get region config by name."""
        return self._regions.get(name)

    def get_region_rect(self, name: str) -> Optional[Rect]:
        """Get the bounding rect for a region."""
        region = self._regions.get(name)
        return region.rect if region else None

    def allocate_in_region(
        self, region_name: str, shape_id: str
    ) -> bool:
        """Register a shape allocation in a region."""
        region = self._regions.get(region_name)
        if not region:
            logger.warning("spatial.unknown_region", region=region_name)
            return False

        if len(self._allocations[region_name]) >= region.max_objects:
            logger.warning(
                "spatial.region_full",
                region=region_name,
                max=region.max_objects,
            )
            return False

        self._allocations[region_name].append(shape_id)
        return True

    def deallocate(self, shape_id: str) -> None:
        """Remove a shape allocation."""
        for region_name, shapes in self._allocations.items():
            if shape_id in shapes:
                shapes.remove(shape_id)
                return

    def get_region_occupancy(self, region_name: str) -> int:
        """Get number of objects in a region."""
        return len(self._allocations.get(region_name, []))

    def get_next_position_in_region(
        self, region_name: str, object_width: float, object_height: float
    ) -> Optional[tuple[float, float]]:
        """
        Get the next available position in a region using grid-based allocation.
        Returns (x, y) or None if region is full.
        """
        region = self._regions.get(region_name)
        if not region:
            return None

        rect = region.rect
        count = len(self._allocations.get(region_name, []))

        # Grid-based positioning within the region
        cols = max(1, int(rect.width / (object_width + self.PADDING)))
        row = count // cols
        col = count % cols

        x = rect.x + col * (object_width + self.PADDING) + self.PADDING
        y = rect.y + row * (object_height + self.PADDING) + self.PADDING

        # Check if within bounds
        if x + object_width > rect.right or y + object_height > rect.bottom:
            if region.is_expandable:
                # Expand region downward
                needed_height = y + object_height - rect.y + self.PADDING
                region.rect = Rect(
                    x=rect.x,
                    y=rect.y,
                    width=rect.width,
                    height=max(rect.height, needed_height),
                )
                return (x, y)
            return None

        return (x, y)

    def clear_region(self, region_name: str) -> None:
        """Clear all allocations in a region."""
        if region_name in self._allocations:
            self._allocations[region_name].clear()

    def get_camera_target_for_region(
        self, region_name: str
    ) -> dict[str, float]:
        """Get camera position to center on a region."""
        region = self._regions.get(region_name)
        if not region:
            return {"x": 0, "y": 0, "zoom": 1.0}

        return {
            "x": region.rect.center_x,
            "y": region.rect.center_y,
            "zoom": min(
                self.BOARD_WIDTH / region.rect.width,
                self.BOARD_HEIGHT / region.rect.height,
            )
            * 0.8,  # 80% fill
        }

    def to_dict(self) -> dict:
        """Serialize region state (for debugging)."""
        return {
            name: {
                "rect": {
                    "x": r.rect.x,
                    "y": r.rect.y,
                    "width": r.rect.width,
                    "height": r.rect.height,
                },
                "occupancy": len(self._allocations.get(name, [])),
                "max_objects": r.max_objects,
            }
            for name, r in self._regions.items()
        }
