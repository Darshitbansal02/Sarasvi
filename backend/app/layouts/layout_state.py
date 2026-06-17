from typing import Dict, Tuple, Optional

class LayoutStateCache:
    """Caches previously calculated entity coordinate layouts to prevent visual jumps."""
    
    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[float, float]] = {}

    def get_position(self, entity_id: str) -> Optional[Tuple[float, float]]:
        return self._cache.get(entity_id)

    def set_position(self, entity_id: str, x: float, y: float) -> None:
        self._cache[entity_id] = (x, y)

    def remove(self, entity_id: str) -> None:
        self._cache.pop(entity_id, None)

    def clear(self) -> None:
        self._cache.clear()

layout_state_cache = LayoutStateCache()
