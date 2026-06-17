from __future__ import annotations
from enum import Enum
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field
from app.world_model.schemas import WorldModel, SemanticRole
from app.dsl.primitives import DSLInstruction

class TopologyType(str, Enum):
    LINEAR = "linear"
    HIERARCHICAL = "hierarchical"
    GRAPH = "graph"
    CONTAINMENT = "containment"
    REGIONAL = "regional"
    FLOW = "flow"
    VECTOR_FIELD = "vector_field"
    TEMPORAL = "temporal"
    ORBITAL = "orbital"

class SpatialConstraint(BaseModel):
    type: str  # e.g., "adjacent_to", "inside", "above", "below", "contains", "aligned_with"
    targets: List[str]
    parameters: Dict[str, Any] = Field(default_factory=dict)

class TopologyDescriptor(BaseModel):
    topologies: List[TopologyType]
    representation: str
    constraints: List[SpatialConstraint] = Field(default_factory=list)
    confidence: float = 1.0
    layout_preferences: Dict[str, Any] = Field(default_factory=dict)

class LayoutStrategy:
    """Base strategy for performing visual topology positioning."""
    def layout(self, world_model: WorldModel, descriptor: TopologyDescriptor, flow_layout: Any, region_mgr: Any) -> List[Any]:
        raise NotImplementedError

class TopologyResolver:
    """Resolves abstract layout topology descriptors from WorldModel structures."""
    
    @staticmethod
    def resolve(model_or_inst: Any) -> TopologyDescriptor:
        if isinstance(model_or_inst, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(model_or_inst)
        else:
            world_model = model_or_inst

        topologies: List[TopologyType] = []
        representation = "generic"
        constraints: List[SpatialConstraint] = []
        layout_prefs = {}
        
        # 1. Extract layout preferences and target topologies from constraints first
        for constraint in world_model.constraints:
            ctype = constraint.type.lower()
            if ctype in ("hierarchical", "tree"):
                topologies.append(TopologyType.HIERARCHICAL)
                representation = "tree"
                layout_prefs = constraint.parameters.get("layout_preference", {})
            elif ctype in ("linear", "sequence"):
                topologies.append(TopologyType.LINEAR)
                representation = "linked_list"
                layout_prefs = constraint.parameters.get("layout_preference", {})
            elif ctype == "graph":
                topologies.append(TopologyType.GRAPH)
                representation = constraint.parameters.get("layout_algorithm", "graph")
            elif ctype == "vector_field":
                topologies.append(TopologyType.VECTOR_FIELD)
                representation = "vectors"
            elif ctype == "orbital":
                topologies.append(TopologyType.ORBITAL)
                representation = "radial"
            elif ctype == "flow":
                topologies.append(TopologyType.FLOW)
                representation = "curve"
            elif ctype == "containment":
                topologies.append(TopologyType.CONTAINMENT)
                representation = "nested_memory"
            elif ctype == "temporal":
                topologies.append(TopologyType.TEMPORAL)
                representation = "timeline"
            elif ctype == "regional":
                topologies.append(TopologyType.REGIONAL)
                representation = "sketch"
                
            constraints.append(SpatialConstraint(
                type=constraint.type,
                targets=constraint.targets,
                parameters=constraint.parameters
            ))

        # 2. Derive topology implicitly if no explicit constraint was resolved
        if not topologies:
            # Check roles in entities
            has_parent = any(e.semantic_role == SemanticRole.PARENT for e in world_model.entities)
            has_child = any(e.semantic_role == SemanticRole.CHILD for e in world_model.entities)
            has_orbiter = any(e.semantic_role == SemanticRole.ORBITER for e in world_model.entities)
            
            if has_parent and has_child:
                topologies = [TopologyType.HIERARCHICAL]
                representation = "tree"
            elif has_orbiter:
                topologies = [TopologyType.ORBITAL]
                representation = "radial"
            elif any(r.semantic_role == SemanticRole.POINTER for r in world_model.relationships):
                topologies = [TopologyType.LINEAR]
                representation = "linked_list"
            else:
                topologies = [TopologyType.REGIONAL]
                representation = "sketch"

        return TopologyDescriptor(
            topologies=topologies,
            representation=representation,
            constraints=constraints,
            layout_preferences=layout_prefs
        )

class LayoutStrategyRegistry:
    """Registry to resolve LayoutStrategy by matching topology and representation."""
    
    def __init__(self) -> None:
        self._strategies: Dict[str, LayoutStrategy] = {}
        
    def register(self, topologies: List[TopologyType], representation: str, strategy: LayoutStrategy) -> None:
        key = self._make_key(topologies, representation)
        self._strategies[key] = strategy
        
    def resolve(self, descriptor: TopologyDescriptor) -> Optional[LayoutStrategy]:
        # Try finding exact match
        key = self._make_key(descriptor.topologies, descriptor.representation)
        if key in self._strategies:
            return self._strategies[key]

        # Fallback to matching by first topology
        if descriptor.topologies:
            fallback_key = self._make_key([descriptor.topologies[0]], "*")
            if fallback_key in self._strategies:
                return self._strategies[fallback_key]

            # General fallback: any strategy registered under the same PRIMARY
            # topology, regardless of representation. Without this, a graph whose
            # representation is its layout_algorithm ("force_directed",
            # "hierarchical", "circular" — the common/default case) produced a key
            # like "graph:force_directed" that was never registered, so the graph
            # silently rendered nothing. Matching on topology alone guarantees a
            # graph always gets a graph layout strategy.
            primary = descriptor.topologies[0].value
            for k, strat in self._strategies.items():
                topo_part = k.split(":", 1)[0]
                if primary in topo_part.split(","):
                    return strat

        return None
        
    def _make_key(self, topologies: List[TopologyType], representation: str) -> str:
        topo_str = ",".join(sorted([t.value for t in topologies]))
        return f"{topo_str}:{representation}"
