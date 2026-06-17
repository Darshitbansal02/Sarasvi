"""
Socratic Educational DSL — all semantic primitives for visual reasoning.

The AI NEVER emits rendering APIs or pixel coordinates.
ONLY these semantic educational primitives are emitted.
The layout engine then computes deterministic coordinates.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Visual Ontology Types ───────────────────────────────────────

class VisualPrimitiveType(str, Enum):
    NODE = "node"
    CONNECTOR = "connector"
    GROUP = "group"
    CONTAINER = "container"
    REGION = "region"
    ANNOTATION = "annotation"
    STROKE = "stroke"


class VisualRole(str, Enum):
    ENTITY = "entity"
    MEMORY_REGION = "memory_region"
    POINTER_CONTAINER = "pointer_container"
    TERMINATION_MARKER = "termination_marker"
    FLOW_SOURCE = "flow_source"
    FLOW_TARGET = "flow_target"
    CALLOUT = "callout"
    POINTER = "pointer"


# ── DSL Primitive Types ──────────────────────────────────────────

class DSLPrimitiveType(str, Enum):
    """All supported visual primitives in the Socratic DSL."""

    # Data Structures
    BINARY_TREE = "binary_tree"
    LINKED_LIST = "linked_list"
    GRAPH = "graph"
    STACK = "stack"
    QUEUE = "queue"
    HEAP = "heap"
    ARRAY = "array"
    HASH_TABLE = "hash_table"

    # Algorithm Visualization
    RECURSION_TRACE = "recursion_trace"
    GRAPH_TRAVERSAL = "graph_traversal"
    EXECUTION_FLOW = "execution_flow"
    STATE_TRANSITION = "state_transition"

    # Memory Visualization
    STACK_FRAME = "stack_frame"
    HEAP_OBJECT = "heap_object"
    POINTER = "pointer"
    STACK_POINTER = "stack_pointer"

    # Code
    CODE_BLOCK = "code_block"

    # ── Domain Semantics ─────────────────────────────────────────
    # Mathematics
    GRAPH_FUNCTION = "graph_function"
    TRANSFORM_EQUATION = "transform_equation"
    EQUATION = "equation"
    EQUATION_WRITE = "equation_write"
    EQUATION_HIGHLIGHT = "equation_highlight"
    HIGHLIGHT_DERIVATIVE = "highlight_derivative"
    INTEGRAL_AREA = "integral_area"
    VECTOR_VISUALIZATION = "vector_visualization"
    GEOMETRIC_CONSTRUCTION = "geometric_construction"

    # Computer Science / DSA / programming explanations
    ALGORITHM_STEP = "algorithm_step"
    CODE_EXPLANATION_FLOW = "code_explanation_flow"
    COMPLEXITY_LABEL = "complexity_label"

    # Physics
    PHYSICS_DIAGRAM = "physics_diagram"
    FREE_BODY_DIAGRAM = "free_body_diagram"
    TRAJECTORY_DIAGRAM = "trajectory_diagram"

    # Physics
    GRAVITY_FIELD = "gravity_field"
    FORCE_VECTOR = "force_vector"
    TRAJECTORY_SIMULATION = "trajectory_simulation"
    WAVE_PROPAGATION = "wave_propagation"
    ELECTRIC_FIELD = "electric_field"
    PLANETARY_ORBIT = "planetary_orbit"

    # Chemistry
    ELECTRON_SHELL = "electron_shell"
    BOND_VISUALIZATION = "bond_visualization"
    REACTION_SIMULATION = "reaction_simulation"
    MOLECULAR_GEOMETRY = "molecular_geometry"
    ORBITAL_VISUALIZATION = "orbital_visualization"
    PERIODIC_TREND = "periodic_trend"

    # ── Procedural / Stroke Primitives ───────────────────────────
    DRAW_STROKE = "draw_stroke"
    STROKE_CURVE = "stroke_curve"
    PEN_MOVE = "pen_move"
    PAUSE_EMPHASIS = "pause_emphasis"
    PROGRESSIVE_REVEAL = "progressive_reveal"
    TEACHER_HIGHLIGHT = "teacher_highlight"

    # ── Embodied Motion Primitives ───────────────────────────────
    CURSOR_MOVE = "cursor_move"
    PEN_STATE = "pen_state"
    STROKE_SEGMENT = "stroke_segment"
    CONSTRUCTION_STEP = "construction_step"
    COGNITIVE_PAUSE = "cognitive_pause"
    ATTENTION_FOCUS = "attention_focus"
    NARRATION_SYNC = "narration_sync"
    SCENE_START = "scene_start"
    CAMERA_MOVE = "camera_move"
    SCENE_MUTATION = "scene_mutation"
    TEACHER_GESTURE = "teacher_gesture"
    MOTOR_SEQUENCE = "motor_sequence"
    GESTURE_EMPHASIS = "gesture_emphasis"
    HOVER_INDICATION = "hover_indication"
    FOCUS_PULSE = "focus_pulse"

    # ── Simulation Primitives ────────────────────────────────────
    SIMULATION_START = "simulation_start"
    SIMULATION_STEP = "simulation_step"

    # Universal Procedural Sketching Primitives
    PROCEDURAL_SKETCH = "procedural_sketch"

    # Annotations
    ANNOTATION = "annotation"
    CALLOUT = "callout"
    TIMELINE_MARKER = "timeline_marker"


# ── Data Structure Primitives ────────────────────────────────────

class BinaryTreeNode(BaseModel):
    """A node in a binary tree."""
    value: Any
    label: Optional[str] = None
    highlight: bool = False
    highlight_color: str = "#00D4FF"


class BinaryTreePrimitive(BaseModel):
    """Binary tree visualization primitive."""
    type: str = DSLPrimitiveType.BINARY_TREE
    structure_id: str
    nodes: list[Any]  # Values — layout engine computes positions
    edges: list[dict[str, Any]] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    highlight_nodes: list[Any] = Field(default_factory=list)
    highlight_color: str = "#00D4FF"
    region: str = "MAIN_VISUAL_REGION"


class LinkedListPrimitive(BaseModel):
    """Linked list visualization primitive."""
    type: str = DSLPrimitiveType.LINKED_LIST
    structure_id: str
    nodes: list[dict[str, Any]]  # [{value, next_id, label}]
    highlight_nodes: list[str] = Field(default_factory=list)
    show_null_terminator: bool = True
    region: str = "MAIN_VISUAL_REGION"


class GraphPrimitive(BaseModel):
    """Graph visualization primitive."""
    type: str = DSLPrimitiveType.GRAPH
    structure_id: str
    nodes: list[dict[str, Any]]  # [{id, label, value}]
    edges: list[dict[str, Any]]  # [{from, to, weight, directed}]
    layout_algorithm: str = "force_directed"  # force_directed, hierarchical, circular
    highlight_nodes: list[str] = Field(default_factory=list)
    highlight_edges: list[dict[str, str]] = Field(default_factory=list)
    region: str = "MAIN_VISUAL_REGION"


class StackPrimitive(BaseModel):
    """Stack visualization primitive."""
    type: str = DSLPrimitiveType.STACK
    structure_id: str
    items: list[Any]  # top is last element
    max_visible: int = 10
    highlight_top: bool = False
    region: str = "MAIN_VISUAL_REGION"


class QueuePrimitive(BaseModel):
    """Queue visualization primitive."""
    type: str = DSLPrimitiveType.QUEUE
    structure_id: str
    items: list[Any]  # front is first element
    highlight_front: bool = False
    highlight_rear: bool = False
    region: str = "MAIN_VISUAL_REGION"


class HeapPrimitive(BaseModel):
    """Heap visualization (as tree) primitive."""
    type: str = DSLPrimitiveType.HEAP
    structure_id: str
    values: list[Any]  # Array representation of heap
    heap_type: str = "min"  # min or max
    highlight_indices: list[int] = Field(default_factory=list)
    region: str = "MAIN_VISUAL_REGION"


class ArrayPrimitive(BaseModel):
    """Array visualization primitive."""
    type: str = DSLPrimitiveType.ARRAY
    structure_id: str
    values: list[Any]
    labels: dict[int, str] = Field(default_factory=dict)  # index → label
    highlight_indices: list[int] = Field(default_factory=list)
    highlight_color: str = "#00D4FF"
    show_indices: bool = True
    region: str = "MAIN_VISUAL_REGION"


# ── Memory Visualization Primitives ─────────────────────────────

class StackFramePrimitive(BaseModel):
    """Stack frame for memory visualization."""
    type: str = DSLPrimitiveType.STACK_FRAME
    frame_id: str
    function_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    locals: dict[str, Any] = Field(default_factory=dict)
    return_address: Optional[str] = None
    base_address: Optional[str] = None
    is_active: bool = True
    highlight_variable: Optional[str] = None


class HeapObjectPrimitive(BaseModel):
    """Heap object for memory visualization."""
    type: str = DSLPrimitiveType.HEAP_OBJECT
    object_id: str
    object_type: str  # LinkedListNode, TreeNode, etc.
    fields: dict[str, Any] = Field(default_factory=dict)
    address: Optional[str] = None


class PointerPrimitive(BaseModel):
    """Pointer arrow for memory visualization."""
    type: str = DSLPrimitiveType.POINTER
    pointer_id: str
    source: str  # frame_id.variable or object_id.field
    target: str  # object_id or address
    label: Optional[str] = None
    color: str = "#FF6B6B"


# ── Code Primitives ─────────────────────────────────────────────

class CodeBlockPrimitive(BaseModel):
    """Code block with syntax highlighting and line execution tracking."""
    type: str = DSLPrimitiveType.CODE_BLOCK
    code_id: str
    language: str = "python"
    code: str
    highlight_line: Optional[int] = None
    highlight_range: Optional[tuple[int, int]] = None
    annotations: dict[int, str] = Field(default_factory=dict)  # line → annotation
    region: str = "CODE_REGION"


# ── Annotation Primitives ───────────────────────────────────────

class AnnotationPrimitive(BaseModel):
    """Text annotation on the whiteboard."""
    type: str = DSLPrimitiveType.ANNOTATION
    annotation_id: str
    text: str
    target: Optional[str] = None  # attach to a shape
    style: str = "default"  # default, emphasis, question, note
    color: Optional[str] = None


class CalloutPrimitive(BaseModel):
    """Callout box for important information."""
    type: str = DSLPrimitiveType.CALLOUT
    callout_id: str
    title: str
    body: str
    style: str = "info"  # info, warning, tip, important
    target: Optional[str] = None


# ── Domain Semantics Primitives (Examples) ──────────────────────

class GraphFunctionPrimitive(BaseModel):
    type: str = DSLPrimitiveType.GRAPH_FUNCTION
    equation: str
    region: str = "GRAPH_REGION"


class EquationPrimitive(BaseModel):
    type: str = DSLPrimitiveType.EQUATION
    latex: str
    display: bool = False
    region: str = "FORMULA_REGION"
    board_id: Optional[str] = None
    board_role: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EquationWritePrimitive(BaseModel):
    type: str = DSLPrimitiveType.EQUATION_WRITE
    equation_id: str
    latex: str
    start_offset_ms: int = 0
    total_duration_ms: int = 800
    per_char_ms: Optional[int] = None
    board_id: Optional[str] = None
    board_role: Optional[str] = None
    write_mode: str = "create"
    append_latex: Optional[str] = None
    full_latex: Optional[str] = None
    parent_board_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EquationHighlightPrimitive(BaseModel):
    type: str = DSLPrimitiveType.EQUATION_HIGHLIGHT
    equation_id: str
    latex_substring: str
    start_ms: int = 0
    duration_ms: int = 1000
    color: str = "#FFFF00"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ForceVectorPrimitive(BaseModel):
    type: str = DSLPrimitiveType.FORCE_VECTOR
    magnitude: float
    direction: float
    origin: tuple[float, float]
    region: str = "VECTOR_REGION"


class MolecularGeometryPrimitive(BaseModel):
    type: str = DSLPrimitiveType.MOLECULAR_GEOMETRY
    molecule: str
    region: str = "MOLECULE_REGION"


class PhysicsDiagramPrimitive(BaseModel):
    type: str = DSLPrimitiveType.PHYSICS_DIAGRAM
    diagram_id: str
    title: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    vectors: list[dict[str, Any]] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    region: str = "FIELD_REGION"


class FreeBodyDiagramPrimitive(BaseModel):
    type: str = DSLPrimitiveType.FREE_BODY_DIAGRAM
    diagram_id: str
    object_name: str
    forces: list[dict[str, Any]] = Field(default_factory=list)
    region: str = "FIELD_REGION"


class TrajectoryDiagramPrimitive(BaseModel):
    type: str = DSLPrimitiveType.TRAJECTORY_DIAGRAM
    diagram_id: str
    points: list[tuple[float, float]] = Field(default_factory=list)
    region: str = "FIELD_REGION"


class AlgorithmStepPrimitive(BaseModel):
    type: str = DSLPrimitiveType.ALGORITHM_STEP
    step_id: str
    title: str
    explanation: str
    code_snippet: Optional[str] = None
    complexity: Optional[str] = None
    region: str = "CODE_REGION"


class CodeExplanationFlowPrimitive(BaseModel):
    type: str = DSLPrimitiveType.CODE_EXPLANATION_FLOW
    flow_id: str
    language: str = "python"
    code: str
    explanation: str
    highlight_lines: list[int] = Field(default_factory=list)
    region: str = "CODE_REGION"


class ComplexityLabelPrimitive(BaseModel):
    type: str = DSLPrimitiveType.COMPLEXITY_LABEL
    label_id: str
    big_o: str
    description: str = ""
    region: str = "CODE_REGION"


# ── Procedural Stroke Primitives ────────────────────────────────

class DrawStrokePrimitive(BaseModel):
    """A literal stroke to be drawn over time."""
    type: str = DSLPrimitiveType.DRAW_STROKE
    stroke_id: str
    path: list[tuple[float, float]]  # List of [x, y] coordinates
    duration_ms: int = 400
    pressure: float = 0.8
    color: str = "#FFFFFF"
    thickness: float = 2.0


class StrokeCurvePrimitive(BaseModel):
    """A Bezier curve stroke."""
    type: str = DSLPrimitiveType.STROKE_CURVE
    stroke_id: str
    control_points: list[tuple[float, float]]
    duration_ms: int = 600
    color: str = "#FFFFFF"


class PenMovePrimitive(BaseModel):
    """Invisible pen movement to reposition for the next stroke."""
    type: str = DSLPrimitiveType.PEN_MOVE
    from_pos: tuple[float, float]
    to_pos: tuple[float, float]
    duration_ms: int = 200


class PauseEmphasisPrimitive(BaseModel):
    """A pedagogical pause to let a concept sink in."""
    type: str = DSLPrimitiveType.PAUSE_EMPHASIS
    duration_ms: int


class ProgressiveRevealPrimitive(BaseModel):
    """Gradually fade in a complex structure."""
    type: str = DSLPrimitiveType.PROGRESSIVE_REVEAL
    target_id: str
    duration_ms: int = 500


class TeacherHighlightPrimitive(BaseModel):
    """Transient visual emphasis on a concept."""
    type: str = DSLPrimitiveType.TEACHER_HIGHLIGHT
    target_id: str
    color: str = "#FFFF00"
    duration_ms: int = 1000


# ── Embodied Motion Primitives ──────────────────────────────────

class CursorMovePrimitive(BaseModel):
    """Move the embodied teacher cursor to a target position."""
    type: str = DSLPrimitiveType.CURSOR_MOVE
    cursor_id: str = "teacher_main"
    target: tuple[float, float]
    duration_ms: int = 300
    easing: str = "human_accel_decel"  # human_accel_decel, anticipation, settle, linear
    anticipation_px: float = 0.0  # pre-motion overshoot distance
    settle_duration_ms: int = 0  # post-motion settle wobble


class PenStatePrimitive(BaseModel):
    """Pen state transitions (pen up/down, pressure changes)."""
    type: str = DSLPrimitiveType.PEN_STATE
    cursor_id: str = "teacher_main"
    state: str = "down"  # down, up, hover
    pressure: float = 0.8
    transition_ms: int = 50


class StrokeSegmentPrimitive(BaseModel):
    """A micro-segment of an ongoing stroke — streamed incrementally."""
    type: str = DSLPrimitiveType.STROKE_SEGMENT
    stroke_id: str
    segment_index: int
    points: list[tuple[float, float]]
    pressure: list[float] = Field(default_factory=list)
    velocity: float = 1.0  # normalized drawing speed
    color: str = "#FFFFFF"
    thickness: float = 2.0


class ConstructionStepPrimitive(BaseModel):
    """A discrete step in a multi-phase construction choreography."""
    type: str = DSLPrimitiveType.CONSTRUCTION_STEP
    step_id: str
    action: str  # draw_node, draw_edge, draw_label, highlight, annotate
    target_ids: list[str] = Field(default_factory=list)
    narration_anchor: Optional[str] = None  # speech text to sync with
    duration_ms: int = 500
    emphasis_targets: list[str] = Field(default_factory=list)
    difficulty: float = 0.5  # 0=trivial, 1=complex — affects pacing


class CognitivePausePrimitive(BaseModel):
    """A deliberate cognitive pause — the teacher 'thinks' before acting."""
    type: str = DSLPrimitiveType.COGNITIVE_PAUSE
    duration_ms: int = 400
    reason: str = "thinking"  # thinking, emphasis, difficulty, transition
    hesitation_strength: float = 0.5  # 0=no hesitation, 1=heavy hesitation
    cursor_drift: bool = True  # cursor drifts slightly during pause


class AttentionFocusPrimitive(BaseModel):
    """Direct student attention to a specific region or object."""
    type: str = DSLPrimitiveType.ATTENTION_FOCUS
    focus_id: str
    target_ids: list[str]
    strategy: str = "pulse"  # pulse, dim_others, circle, underline, glow
    duration_ms: int = 800
    intensity: float = 0.7


class NarrationSyncPrimitive(BaseModel):
    """Synchronization anchor between narration and visual actions."""
    type: str = DSLPrimitiveType.NARRATION_SYNC
    anchor_id: str
    speech_text: str  # the phrase being spoken
    visual_action: str  # what to do visually: draw, highlight, focus, pause
    visual_target_ids: list[str] = Field(default_factory=list)
    offset_ms: int = 0  # offset from speech start
    duration_ms: int = 500


class TeacherGesturePrimitive(BaseModel):
    """High-level teacher gesture: circling, underlining, pointing, tapping."""
    type: str = DSLPrimitiveType.TEACHER_GESTURE
    gesture_id: str
    gesture_type: str  # circle, underline, point, tap, bracket, arrow
    target_ids: list[str] = Field(default_factory=list)
    target_region: Optional[tuple[float, float, float, float]] = None  # x, y, w, h
    duration_ms: int = 600
    emphasis: float = 0.7
    color: str = "#FFFF00"


class MotorSequencePrimitive(BaseModel):
    """An ordered sequence of micro-motor actions for complex constructions."""
    type: str = DSLPrimitiveType.MOTOR_SEQUENCE
    sequence_id: str
    actions: list[dict[str, Any]] = Field(default_factory=list)
    replay_safe: bool = True
    total_duration_ms: int = 1000
    pacing_mode: str = "adaptive"  # adaptive, constant, speech_sync


class GestureEmphasisPrimitive(BaseModel):
    """Apply emphasis gesture dynamics to a visual element."""
    type: str = DSLPrimitiveType.GESTURE_EMPHASIS
    target_id: str
    emphasis_type: str = "scale_pulse"  # scale_pulse, glow, shake, underline
    intensity: float = 0.6
    duration_ms: int = 500
    repeat: int = 1


# ── Camera Primitives ───────────────────────────────────────────

class CameraAction(str, Enum):
    MOVE = "move"
    ZOOM = "zoom"
    FOCUS = "focus"
    OVERVIEW = "overview"
    FOCUS_MEMORY = "focus_memory"
    ZOOM_MEMORY_REGION = "zoom_memory_region"


class CameraPrimitive(BaseModel):
    """Camera control primitive — semantic, not pixel-based."""
    action: CameraAction
    target: Optional[str] = None  # shape_id or region name
    zoom_level: Optional[float] = None
    duration_ms: int = 500
    easing: str = "ease-in-out"


# ── Memory Operation Actions ────────────────────────────────────

class MemoryAction(str, Enum):
    PUSH_FRAME = "push_frame"
    POP_FRAME = "pop_frame"
    UPDATE_LOCAL_VARIABLE = "update_local_variable"
    UPDATE_ARGUMENT = "update_argument"
    HIGHLIGHT_VARIABLE = "highlight_variable"
    MOVE_STACK_POINTER = "move_stack_pointer"
    SHOW_RETURN_VALUE = "show_return_value"
    BUBBLE_RETURN_VALUE = "bubble_return_value"
    ALLOCATE_HEAP_OBJECT = "allocate_heap_object"
    POINTER_REFERENCE = "pointer_reference"
    DEALLOCATE_HEAP_OBJECT = "deallocate_heap_object"


# ── Simulation Operation Actions ────────────────────────────────────

class SimulationStartPrimitive(BaseModel):
    """Start a continuous physics or algorithmic simulation on scene objects."""
    type: str = DSLPrimitiveType.SIMULATION_START
    simulation_id: str
    simulation_type: str  # force_directed, wave, planetary, custom_equation
    target_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 5000  # How long the simulation runs before pausing


class SimulationStepPrimitive(BaseModel):
    """A discrete update to an ongoing simulation state."""
    type: str = DSLPrimitiveType.SIMULATION_STEP
    simulation_id: str
    updates: dict[str, Any]
    duration_ms: int = 200

class ProceduralSketchPrimitive(BaseModel):
    """
    A universal procedural sketch composed of arbitrary abstract shapes.
    Completely eliminates hardcoded domain-specific diagram widgets.
    """
    type: str = DSLPrimitiveType.PROCEDURAL_SKETCH
    sketch_id: str
    shapes: list[dict[str, Any]] # [{"type": "circle|rect|arrow|wavy_line|blob|label", "props": {...}}]
    region: str = "MAIN_VISUAL_REGION"

class DSLInstruction(BaseModel):
    """
    A single DSL instruction from the AI.
    The layout engine consumes these and produces Tldraw shapes with coordinates.
    """
    instruction_id: str = Field(default_factory=lambda: f"dsl_{__import__('uuid').uuid4().hex[:8]}")
    primitive_type: DSLPrimitiveType
    action: str = "create"  # create, update, delete, animate, highlight
    data: dict[str, Any] = Field(default_factory=dict)
    region: str = "MAIN_VISUAL_REGION"
    duration_ms: int = 0
    depends_on: Optional[str] = None  # instruction_id of dependency
    # ── Motion metadata ──
    motion_phase: str = ""  # construction, emphasis, transition, idle
    difficulty: float = 0.5  # concept difficulty: affects hesitation/pacing
    narration_anchor: Optional[str] = None  # speech text this instruction syncs with
    reasoning_step_id: Optional[str] = None
