"""Resolve domain simulation engines without importing agent orchestration layers."""

from __future__ import annotations

import asyncio
from typing import Any

_ENGINE_MAP: dict[str, type] | None = None


def _engine_map() -> dict[str, type]:
    global _ENGINE_MAP
    if _ENGINE_MAP is None:
        from app.domains.universal.engine import UniversalSimulationEngine

        _ENGINE_MAP = {
            "mathematics": UniversalSimulationEngine,
            "physics": UniversalSimulationEngine,
            "chemistry": UniversalSimulationEngine,
            "computer_science": UniversalSimulationEngine,
            "electrical_engineering": UniversalSimulationEngine,
            "biology": UniversalSimulationEngine,
            "economics": UniversalSimulationEngine,
            "history": UniversalSimulationEngine,
            "geography": UniversalSimulationEngine,
            "linguistics": UniversalSimulationEngine,
            "philosophy": UniversalSimulationEngine,
            "psychology": UniversalSimulationEngine,
            "law": UniversalSimulationEngine,
            "music": UniversalSimulationEngine,
            "art": UniversalSimulationEngine,
            "general": UniversalSimulationEngine,
        }
    return _ENGINE_MAP


def resolve_engine_for_domain(domain: str) -> Any:
    """
    Return an instantiated domain engine for an ALREADY-detected domain.

    Pure, synchronous, no LLM call, no event loop. This is the correct entry
    point for the teaching pipeline, which has already classified the domain via
    the SemanticDecompositionEngine — re-classifying here was both wasteful and,
    inside the running pipeline loop, a guaranteed crash (see resolve_engine_for_query
    history). Unknown / future domains map to the UniversalSimulationEngine.
    """
    from app.domains.universal.engine import UniversalSimulationEngine

    engine_class = _engine_map().get((domain or "general").lower(), UniversalSimulationEngine)
    return engine_class()



