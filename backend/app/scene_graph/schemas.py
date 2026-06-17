from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class SceneEntity(BaseModel):
    id: str
    label: str
    x: float
    y: float
    width: float
    height: float
    semantic_role: str = "generic"
    properties: Dict[str, Any] = Field(default_factory=dict)

    def __getitem__(self, item: str) -> Any:
        # Backward compatibility with dictionary access
        if item == "props":
            return self.properties
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        if item == "props":
            return self.properties
        return getattr(self, item, default)

class SceneRelationship(BaseModel):
    id: str
    source_id: str
    target_id: str
    x: float
    y: float
    width: float
    height: float
    relation_type: str
    semantic_role: str = "generic"
    properties: Dict[str, Any] = Field(default_factory=dict)

    def __getitem__(self, item: str) -> Any:
        if item == "props":
            return self.properties
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        if item == "props":
            return self.properties
        return getattr(self, item, default)

class SceneAnnotation(BaseModel):
    id: str
    text: str
    x: float
    y: float
    width: float
    height: float
    properties: Dict[str, Any] = Field(default_factory=dict)

    def __getitem__(self, item: str) -> Any:
        if item == "props":
            return self.properties
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        if item == "props":
            return self.properties
        return getattr(self, item, default)
