from typing import Any, Dict, List
from app.world_model.schemas import WorldModel, WorldEntity, WorldRelationship, WorldConstraint, OntologicalRole, SemanticRole
from app.world_model.builder import WorldModelBuilder
from app.dsl.primitives import (
    DSLInstruction,
    DSLPrimitiveType,
    BinaryTreePrimitive,
    LinkedListPrimitive,
    GraphPrimitive,
    PhysicsDiagramPrimitive,
    MolecularGeometryPrimitive
)

class LegacyAdapter:
    @staticmethod
    def adapt(instruction: DSLInstruction) -> WorldModel:
        prim_type = instruction.primitive_type
        data = instruction.data or {}
        
        if prim_type == DSLPrimitiveType.BINARY_TREE:
            prim = BinaryTreePrimitive(
                structure_id=data.get("structure_id", "tree"),
                nodes=data.get("nodes", []),
                edges=data.get("edges", []),
                labels=data.get("labels", {}),
                highlight_nodes=data.get("highlight_nodes", [])
            )
            return LegacyAdapter.adapt_binary_tree(prim)
            
        elif prim_type == DSLPrimitiveType.LINKED_LIST:
            prim = LinkedListPrimitive(
                structure_id=data.get("structure_id", "list"),
                nodes=data.get("nodes", []),
                highlight_nodes=data.get("highlight_nodes", [])
            )
            return LegacyAdapter.adapt_linked_list(prim)
            
        elif prim_type == DSLPrimitiveType.GRAPH:
            prim = GraphPrimitive(
                structure_id=data.get("structure_id", "graph"),
                nodes=data.get("nodes", []),
                edges=data.get("edges", []),
                layout_algorithm=data.get("layout_algorithm", "force_directed")
            )
            return LegacyAdapter.adapt_graph(prim)

        elif prim_type == DSLPrimitiveType.HEAP:
            # A heap is a complete binary tree stored as an array (level order);
            # render it through the tree adapter. Previously HEAP fell through to
            # the generic fallback and laid out to nothing.
            prim = BinaryTreePrimitive(
                structure_id=data.get("structure_id", "heap"),
                nodes=data.get("values", data.get("nodes", [])),
            )
            return LegacyAdapter.adapt_binary_tree(prim)
            
        elif prim_type in (DSLPrimitiveType.PHYSICS_DIAGRAM, DSLPrimitiveType.FREE_BODY_DIAGRAM):
            prim = PhysicsDiagramPrimitive(
                diagram_id=data.get("diagram_id", data.get("structure_id", "physics")),
                title=data.get("title", ""),
                entities=data.get("entities", [{"id": data.get("object_name", "center"), "label": data.get("object_name", "center")}]),
                vectors=data.get("vectors", data.get("forces", []))
            )
            return LegacyAdapter.adapt_physics_diagram(prim)
            
        elif prim_type == DSLPrimitiveType.MOLECULAR_GEOMETRY:
            prim = MolecularGeometryPrimitive(
                molecule=data.get("molecule", "H2O")
            )
            return LegacyAdapter.adapt_molecular_geometry(prim)
            
        elif prim_type == DSLPrimitiveType.PROCEDURAL_SKETCH:
            return LegacyAdapter.adapt_procedural_sketch(instruction)
            
        # Default fallback adapter
        builder = WorldModelBuilder()
        builder.add_entity(
            entity_id=data.get("id", "generic_entity"),
            label=data.get("text", data.get("label", "entity")),
            role=OntologicalRole.ENTITY
        )
        builder.add_constraint(
            constraint_type="generic",
            targets=[data.get("id", "generic_entity")]
        )
        return builder.build()

    @staticmethod
    def adapt_binary_tree(primitive: BinaryTreePrimitive) -> WorldModel:
        builder = WorldModelBuilder()
        
        for idx, node_val in enumerate(primitive.nodes):
            node_id = f"{primitive.structure_id}_node_{idx}"
            sem_role = SemanticRole.PARENT if idx == 0 else SemanticRole.CHILD
            builder.add_entity(
                entity_id=node_id,
                label=str(node_val),
                role=OntologicalRole.ENTITY,
                semantic_role=sem_role,
                metadata={
                    "structure_id": primitive.structure_id,
                    "highlight": node_val in primitive.highlight_nodes,
                    "label": primitive.labels.get(node_id, str(node_val))
                }
            )

        for edge_idx, edge in enumerate(primitive.edges):
            builder.add_relationship(
                rel_id=f"{primitive.structure_id}_edge_{edge_idx}",
                source_id=str(edge.get("from")),
                target_id=str(edge.get("to")),
                relation_type="branch",
                semantic_role=SemanticRole.CHILD
            )

        builder.add_constraint(
            constraint_type="hierarchical",
            targets=[f"{primitive.structure_id}_node_{i}" for i in range(len(primitive.nodes))],
            parameters={
                "structure_id": primitive.structure_id,
                "layout_preference": {
                    "orientation": "top-down",
                    "spacing": 80.0,
                    "alignment": "center"
                }
            }
        )

        return builder.build()

    @staticmethod
    def adapt_linked_list(primitive: LinkedListPrimitive) -> WorldModel:
        builder = WorldModelBuilder()
        
        for idx, node in enumerate(primitive.nodes):
            node_id = node.get("id", f"{primitive.structure_id}_node_{idx}")
            builder.add_entity(
                entity_id=node_id,
                label=str(node.get("value", "")),
                role=OntologicalRole.ENTITY,
                semantic_role=SemanticRole.SLOT,
                metadata={
                    "structure_id": primitive.structure_id,
                    "highlight": node_id in primitive.highlight_nodes
                }
            )
            
            next_id = node.get("next_id")
            if next_id:
                builder.add_relationship(
                    rel_id=f"{primitive.structure_id}_flow_{idx}",
                    source_id=node_id,
                    target_id=next_id,
                    relation_type="points_to",
                    semantic_role=SemanticRole.POINTER
                )

        builder.add_constraint(
            constraint_type="linear",
            targets=[n.get("id", f"{primitive.structure_id}_node_{idx}") for idx, n in enumerate(primitive.nodes)],
            parameters={
                "structure_id": primitive.structure_id,
                "layout_preference": {
                    "orientation": "horizontal",
                    "spacing": 60.0
                }
            }
        )
        
        return builder.build()

    @staticmethod
    def adapt_graph(primitive: GraphPrimitive) -> WorldModel:
        builder = WorldModelBuilder()
        
        for node in primitive.nodes:
            builder.add_entity(
                entity_id=node.get("id"),
                label=node.get("label", ""),
                role=OntologicalRole.ENTITY,
                semantic_role=SemanticRole.GENERIC,
                metadata={"structure_id": primitive.structure_id}
            )
            
        for edge_idx, edge in enumerate(primitive.edges):
            builder.add_relationship(
                rel_id=f"{primitive.structure_id}_edge_{edge_idx}",
                source_id=edge.get("from"),
                target_id=edge.get("to"),
                relation_type="connected_to",
                semantic_role=SemanticRole.GENERIC,
                metadata={"directed": edge.get("directed", False), "weight": edge.get("weight")}
            )
            
        builder.add_constraint(
            constraint_type="graph",
            targets=[n.get("id") for n in primitive.nodes],
            parameters={
                "structure_id": primitive.structure_id,
                "layout_algorithm": primitive.layout_algorithm
            }
        )
        
        return builder.build()

    @staticmethod
    def adapt_physics_diagram(primitive: PhysicsDiagramPrimitive) -> WorldModel:
        builder = WorldModelBuilder()
        
        for ent in primitive.entities:
            builder.add_entity(
                entity_id=ent.get("id"),
                label=ent.get("label", ""),
                role=OntologicalRole.ACTOR if ent.get("role") == "actor" else OntologicalRole.ENTITY,
                semantic_role=SemanticRole.ANCHOR,
                metadata={"type": ent.get("type")}
            )
            
        for idx, vec in enumerate(primitive.vectors):
            rel_id = f"{primitive.diagram_id}_vector_{idx}"
            builder.add_relationship(
                rel_id=rel_id,
                source_id=vec.get("origin_id", primitive.diagram_id),
                target_id=vec.get("target_id", rel_id),
                relation_type="force_vector",
                semantic_role=SemanticRole.POINTER,
                metadata={
                    "magnitude": vec.get("magnitude"),
                    "direction": vec.get("direction"),
                    "color": vec.get("color"),
                    "label": vec.get("label")
                }
            )
            
        builder.add_constraint(
            constraint_type="vector_field",
            targets=[e.get("id") for e in primitive.entities],
            parameters={"diagram_id": primitive.diagram_id}
        )
        
        return builder.build()

    @staticmethod
    def adapt_molecular_geometry(primitive: MolecularGeometryPrimitive) -> WorldModel:
        builder = WorldModelBuilder()
        
        formula = primitive.molecule or "X"
        center_atom = formula[0] if formula else "X"
        center_id = f"center_node_{center_atom}"
        
        builder.add_entity(
            entity_id=center_id,
            label=center_atom,
            role=OntologicalRole.ENTITY,
            semantic_role=SemanticRole.ANCHOR
        )
        
        outer_idx = 0
        for char in formula[1:]:
            if char.isalpha():
                outer_id = f"outer_node_{char}_{outer_idx}"
                builder.add_entity(
                    entity_id=outer_id,
                    label=char,
                    role=OntologicalRole.ENTITY,
                    semantic_role=SemanticRole.ORBITER
                )
                builder.add_relationship(
                    rel_id=f"link_{outer_idx}",
                    source_id=center_id,
                    target_id=outer_id,
                    relation_type="link",
                    semantic_role=SemanticRole.POINTER
                )
                outer_idx += 1
                
        builder.add_constraint(
            constraint_type="orbital",
            targets=[center_id] + [f"outer_node_{char}_{i}" for i in range(outer_idx)],
            parameters={"structure_id": primitive.molecule}
        )
        
        return builder.build()

    @staticmethod
    def _entities_to_shapes(data: dict) -> list[dict]:
        shapes = []
        entities = data.get("entities", [])
        relationships = data.get("relationships", [])
        
        import math
        n = len(entities)
        positions = {}
        for idx, ent in enumerate(entities):
            ent_id = ent.get("id", f"ent_{idx}")
            pos = ent.get("position") or ent.get("center")
            if pos and isinstance(pos, (list, tuple)) and len(pos) >= 2:
                x, y = pos[0], pos[1]
            else:
                if n > 1:
                    angle = 2 * math.pi * idx / n
                    x = 0.5 + 0.3 * math.cos(angle)
                    y = 0.5 + 0.3 * math.sin(angle)
                else:
                    x, y = 0.5, 0.5
            positions[ent_id] = [x, y]
            
            label_text = ent.get("label") or ent.get("name") or ent_id
            shapes.append({
                "type": "rect",
                "center": [x, y],
                "width": 0.18,
                "height": 0.08,
                "color": "#FFFFFF"
            })
            shapes.append({
                "type": "label",
                "position": [x, y],
                "text": label_text,
                "font_size": 14,
                "color": "#E0E0E0"
            })
            
        for idx, rel in enumerate(relationships):
            src = rel.get("source") or rel.get("from")
            tgt = rel.get("target") or rel.get("to")
            if src in positions and tgt in positions:
                start = positions[src]
                end = positions[tgt]
                shapes.append({
                    "type": "arrow",
                    "start": start,
                    "end": end,
                    "color": "#00D4FF"
                })
                rel_label = rel.get("label") or rel.get("type")
                if rel_label:
                    mid_x = (start[0] + end[0]) / 2.0
                    mid_y = (start[1] + end[1]) / 2.0
                    shapes.append({
                        "type": "label",
                        "position": [mid_x, mid_y - 0.03],
                        "text": rel_label,
                        "font_size": 12,
                        "color": "#FFB74D"
                    })
        return shapes

    @staticmethod
    def adapt_procedural_sketch(instruction: DSLInstruction) -> WorldModel:
        builder = WorldModelBuilder()
        data = instruction.data or {}
        sketch_id = data.get("sketch_id", "sketch")
        shapes = data.get("shapes", [])
        
        if not shapes and data.get("entities"):
            shapes = LegacyAdapter._entities_to_shapes(data)
            
        builder.add_entity(
            entity_id=sketch_id,
            label=sketch_id,
            role=OntologicalRole.CONTAINER,
            semantic_role=SemanticRole.GENERIC,
            metadata={"shapes": shapes}
        )
        
        builder.add_constraint(
            constraint_type="flow" if "path" in data or "points" in data else "regional",
            targets=[sketch_id],
            parameters={"sketch_id": sketch_id}
        )
        
        return builder.build()

