from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum

class OntologicalRole(str, Enum):
    ENTITY = "Entity"
    CONTAINER = "Container"
    FLOW = "Flow"
    ACTOR = "Actor"
    RESOURCE = "Resource"
    STATE = "State"
    PROCESS = "Process"
    CONCEPT = "Concept"

class SemanticRole(str, Enum):
    ANCHOR = "Anchor"
    ORBITER = "Orbiter"
    CONTAINER_HEADER = "ContainerHeader"
    SLOT = "Slot"
    POINTER = "Pointer"
    PARENT = "Parent"
    CHILD = "Child"
    SOURCE = "Source"
    TARGET = "Target"
    AXIS = "Axis"
    EVENT = "Event"
    GENERIC = "Generic"

class WorldEntity(BaseModel):
    id: str
    role: OntologicalRole
    semantic_role: SemanticRole = SemanticRole.GENERIC
    label: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class WorldRelationship(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation_type: str
    semantic_role: SemanticRole = SemanticRole.GENERIC
    metadata: Dict[str, Any] = Field(default_factory=dict)

class WorldConstraint(BaseModel):
    type: str
    targets: List[str]
    parameters: Dict[str, Any] = Field(default_factory=dict)

class WorldModel(BaseModel):
    entities: List[WorldEntity]
    relationships: List[WorldRelationship]
    constraints: List[WorldConstraint]
