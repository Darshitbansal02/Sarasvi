from typing import List, Dict, Any, Optional
from app.world_model.schemas import WorldModel, WorldEntity, WorldRelationship, WorldConstraint, OntologicalRole, SemanticRole

class WorldModelBuilder:
    def __init__(self) -> None:
        self.entities: List[WorldEntity] = []
        self.relationships: List[WorldRelationship] = []
        self.constraints: List[WorldConstraint] = []

    def add_entity(
        self,
        entity_id: str,
        label: str,
        role: OntologicalRole = OntologicalRole.ENTITY,
        semantic_role: SemanticRole = SemanticRole.GENERIC,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "WorldModelBuilder":
        self.entities.append(WorldEntity(
            id=entity_id,
            label=label,
            role=role,
            semantic_role=semantic_role,
            metadata=metadata or {}
        ))
        return self

    def add_relationship(
        self,
        rel_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        semantic_role: SemanticRole = SemanticRole.GENERIC,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "WorldModelBuilder":
        self.relationships.append(WorldRelationship(
            id=rel_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            semantic_role=semantic_role,
            metadata=metadata or {}
        ))
        return self

    def add_constraint(
        self,
        constraint_type: str,
        targets: List[str],
        parameters: Optional[Dict[str, Any]] = None
    ) -> "WorldModelBuilder":
        self.constraints.append(WorldConstraint(
            type=constraint_type,
            targets=targets,
            parameters=parameters or {}
        ))
        return self

    def build(self) -> WorldModel:
        return WorldModel(
            entities=self.entities,
            relationships=self.relationships,
            constraints=self.constraints
        )
