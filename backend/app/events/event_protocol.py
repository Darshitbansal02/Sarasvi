"""
Event Protocol — Pydantic models for the complete Sarasvi event system.

Every event MUST be independently parsable (NDJSON rule).
Every event MUST contain generation_id for interruption invalidation.
Every event MUST contain sequence_number for deterministic ordering.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Callable, Coroutine, Union

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """All supported timeline event types."""

    # ── Speech & Audio ───────────────────────────────────────────
    SPEECH = "speech"
    AUDIO_CHUNK = "audio_chunk"

    # ── Drawing / Visual DSL ─────────────────────────────────────
    DRAW = "draw"
    CAMERA_MOVE = "camera_move"
    ZOOM_FOCUS = "zoom_focus"
    HIGHLIGHT = "highlight"
    CLEAR_REGION = "clear_region"
    ANNOTATION = "annotation"
    CALLOUT = "callout"

    # ── Data Structure Visuals ───────────────────────────────────
    BINARY_TREE = "binary_tree"
    LINKED_LIST = "linked_list"
    GRAPH = "graph"
    STACK = "stack"
    QUEUE = "queue"
    HEAP = "heap"
    ARRAY = "array"
    HASH_TABLE = "hash_table"
    CREATE_BINARY_TREE = "create_binary_tree"
    CREATE_LINKED_LIST = "create_linked_list"
    CREATE_GRAPH = "create_graph"
    CREATE_STACK = "create_stack"
    CREATE_QUEUE = "create_queue"
    CREATE_HEAP = "create_heap"
    CREATE_ARRAY = "create_array"

    # ── Algorithm Visualization ──────────────────────────────────
    GRAPH_TRAVERSAL = "graph_traversal"
    RECURSION_TRACE = "recursion_trace"
    EXECUTION_FLOW = "execution_flow"
    STATE_TRANSITION = "state_transition"
    NODE_FOCUS = "node_focus"

    # ── Memory Operations ────────────────────────────────────────
    STACK_FRAME = "stack_frame"
    MEMORY_OP = "memory_op"
    PUSH_FRAME = "push_frame"
    POP_FRAME = "pop_frame"
    UPDATE_LOCAL_VARIABLE = "update_local_variable"
    UPDATE_ARGUMENT = "update_argument"
    HIGHLIGHT_VARIABLE = "highlight_variable"
    MOVE_STACK_POINTER = "move_stack_pointer"
    STACK_POINTER = "stack_pointer"
    SHOW_RETURN_VALUE = "show_return_value"
    BUBBLE_RETURN_VALUE = "bubble_return_value"
    ALLOCATE_HEAP_OBJECT = "allocate_heap_object"
    POINTER_REFERENCE = "pointer_reference"

    # ── Code ─────────────────────────────────────────────────────
    CODE_BLOCK = "code_block"
    CODE_HIGHLIGHT_LINE = "code_highlight_line"
    CODE_EXPLANATION_FLOW = "code_explanation_flow"
    ALGORITHM_STEP = "algorithm_step"
    COMPLEXITY_LABEL = "complexity_label"

    # ── Domain Semantics ─────────────────────────────────────────
    # Mathematics
    GRAPH_FUNCTION = "graph_function"
    TRANSFORM_EQUATION = "transform_equation"
    HIGHLIGHT_DERIVATIVE = "highlight_derivative"
    INTEGRAL_AREA = "integral_area"
    VECTOR_VISUALIZATION = "vector_visualization"
    GEOMETRIC_CONSTRUCTION = "geometric_construction"

    # Physics
    GRAVITY_FIELD = "gravity_field"
    FORCE_VECTOR = "force_vector"
    TRAJECTORY_SIMULATION = "trajectory_simulation"
    WAVE_PROPAGATION = "wave_propagation"
    ELECTRIC_FIELD = "electric_field"
    PLANETARY_ORBIT = "planetary_orbit"
    PHYSICS_DIAGRAM = "physics_diagram"
    FREE_BODY_DIAGRAM = "free_body_diagram"
    TRAJECTORY_DIAGRAM = "trajectory_diagram"

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
    # Equation events
    EQUATION = "equation"
    EQUATION_WRITE = "equation_write"
    EQUATION_HIGHLIGHT = "equation_highlight"

    # ── Embodied Motion Events ───────────────────────────────────
    CURSOR_MOVE = "cursor_move"
    PEN_STATE = "pen_state"
    STROKE_SEGMENT = "stroke_segment"
    CONSTRUCTION_STEP = "construction_step"
    COGNITIVE_PAUSE = "cognitive_pause"
    ATTENTION_FOCUS = "attention_focus"
    NARRATION_SYNC = "narration_sync"
    TEACHER_GESTURE = "teacher_gesture"
    MOTOR_SEQUENCE = "motor_sequence"
    GESTURE_EMPHASIS = "gesture_emphasis"
    HOVER_INDICATION = "hover_indication"
    FOCUS_PULSE = "focus_pulse"

    # ── Simulation Primitives ────────────────────────────────────
    SIMULATION_START = "simulation_start"
    SIMULATION_STEP = "simulation_step"

    # ── Universal Procedural Sketching ───────────────────────────
    PROCEDURAL_SKETCH = "procedural_sketch"
    SCENE_START = "scene_start"

    # ── Timeline Markers ─────────────────────────────────────────
    TIMELINE_MARKER = "timeline_marker"
    TIMELINE_MUTATION = "timeline_mutation"
    CHECKPOINT = "checkpoint"

    # ── System Events ────────────────────────────────────────────
    GENERATION_START = "generation_start"
    GENERATION_END = "generation_end"
    INTERRUPTION = "interruption"
    BRANCH_CREATE = "branch_create"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    HEARTBEAT = "heartbeat"
    ERROR = "error"

    # ── Scene Graph Operations ────────────────────────────────────
    SCENE_MUTATION = "scene_mutation"
    DEALLOCATE_HEAP_OBJECT = "deallocate_heap_object"

    # ── Missing Compiler Event Types ──────────────────────────────
    CURSOR_PAUSE = "cursor_pause"
    SIMULATION_UPDATE = "simulation_update"
    STROKE_REVEAL = "stroke_reveal"
    GESTURE = "gesture"
    SPEECH_PAUSE = "speech_pause"
    SCENE_END = "scene_end"
    STROKE = "stroke"


# ── Specific Payload Schemas ─────────────────────────────────────

class EquationPayload(BaseModel):
    equation_id: Optional[str] = None
    latex: str
    display: bool = False
    font_size: Optional[int] = 28
    board_id: Optional[str] = None
    board_role: Optional[str] = None
    write_mode: Optional[str] = None
    append_latex: Optional[str] = None
    full_latex: Optional[str] = None
    parent_board_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EquationWritePayload(BaseModel):
    equation_id: str
    latex: str
    start_offset_ms: int = 0
    total_duration_ms: int = 800
    per_char_ms: Optional[int] = None
    board_id: Optional[str] = None
    board_role: Optional[str] = None
    write_mode: Optional[str] = None
    append_latex: Optional[str] = None
    full_latex: Optional[str] = None
    parent_board_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EquationHighlightPayload(BaseModel):
    equation_id: str
    latex_substring: str
    start_ms: int = 0
    duration_ms: int = 1000
    color: str = "#FFFF00"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PhysicsDiagramPayload(BaseModel):
    diagram_id: str
    title: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    vectors: list[dict[str, Any]] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)


class FreeBodyDiagramPayload(BaseModel):
    diagram_id: str
    object_name: str
    forces: list[dict[str, Any]] = Field(default_factory=list)


class AlgorithmStepPayload(BaseModel):
    step_id: str
    title: str
    explanation: str
    code_snippet: Optional[str] = None
    complexity: Optional[str] = None


class CodeExplanationFlowPayload(BaseModel):
    flow_id: str
    language: str = "python"
    code: str
    explanation: str
    highlight_lines: list[int] = Field(default_factory=list)


class ComplexityLabelPayload(BaseModel):
    label_id: str
    big_o: str
    description: str = ""


class SpeechPayload(BaseModel):
    """Payload for speech events."""
    text: str
    voice: str = "en-US-AriaNeural"
    emotion: Optional[str] = None
    pace: str = "normal"  # slow, normal, fast
    audio_data: Optional[str] = None
    speech_marks: Optional[list[dict[str, Any]]] = None
    provider: Optional[str] = None


class DrawPayload(BaseModel):
    """Payload for draw events — semantic DSL, NOT pixel coordinates."""
    action: str  # create, update, delete, animate
    shape_type: str  # from DSL primitives
    shape_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class CameraMovePayload(BaseModel):
    """Payload for camera movement — targets a logical region or shape."""
    target: str  # shape_id, region name, or "overview"
    zoom_level: Optional[float] = None
    duration_ms: int = 500
    easing: str = "ease-in-out"


class MemoryOpPayload(BaseModel):
    """Payload for memory operations (stack/heap visualization)."""
    action: str  # push_frame, pop_frame, update_local_variable, etc.
    frame_id: Optional[str] = None
    function_name: Optional[str] = None
    args: Optional[dict[str, Any]] = None
    locals: Optional[dict[str, Any]] = None
    variable: Optional[str] = None
    value: Optional[Any] = None
    return_address: Optional[str] = None
    base_address: Optional[str] = None
    from_frame: Optional[str] = None
    to_frame: Optional[str] = None
    object_id: Optional[str] = None
    object_type: Optional[str] = None
    fields: Optional[dict[str, Any]] = None
    source: Optional[str] = None
    target: Optional[str] = None


class InterruptionPayload(BaseModel):
    """Payload for interruption events."""
    reason: str  # "user_text", "user_voice", "system"
    message: Optional[str] = None
    previous_generation_id: str
    new_generation_id: str


class BranchCreatePayload(BaseModel):
    """Payload for branch creation events."""
    parent_branch_id: str
    branch_point_sequence: int
    reason: str


class DataStructurePayload(BaseModel):
    """Payload for creating data structure visualizations."""
    structure_id: str
    nodes: list[Any] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    highlight_nodes: list[Any] = Field(default_factory=list)
    region: str = "MAIN_VISUAL_REGION"


class TimelineEventData(BaseModel):
    """
    The canonical event structure. Every event in Sarasvi follows this schema.
    Each event is independently parsable as a single NDJSON line.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generation_id: str = Field(
        ...,
        description="Changes on each interruption cycle. Stale generation events are rejected.",
    )
    branch_id: str = Field(
        default="main",
        description="Cognitive timeline branch. New branches created on interruption.",
    )
    version_id: str = Field(default="v1")
    parent_event_id: Optional[str] = Field(
        default=None,
        description="Parent event for tree-structured timelines.",
    )
    sequence_number: int = Field(
        ...,
        description="Monotonically increasing per generation. Determines replay order.",
    )
    start_ms: int = Field(
        default=0,
        description="Milliseconds from session start. Used by timeline scheduler.",
    )
    server_timestamp: int = Field(
        default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000),
        description="Server UTC timestamp in milliseconds.",
    )
    type: EventType = Field(..., description="Event type from the Socratic DSL.")
    payload: Union[
        dict[str, Any],
        EquationPayload,
        EquationWritePayload,
        EquationHighlightPayload,
        PhysicsDiagramPayload,
        FreeBodyDiagramPayload,
        AlgorithmStepPayload,
        CodeExplanationFlowPayload,
        ComplexityLabelPayload,
        SpeechPayload,
        DrawPayload,
        CameraMovePayload,
        MemoryOpPayload,
        InterruptionPayload,
        BranchCreatePayload,
        DataStructurePayload,
    ] = Field(
        default_factory=dict,
        description="Type-specific payload data.",
    )

    model_config = {
        "use_enum_values": True
    }


# ── Event Bus interfaces ────────────────────────
EventHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventBusInterface:
    """
    Abstract interface for the event bus.
    Future implementations: RedisEventBus, KafkaEventBus, NATSEventBus.
    """

    async def start(self) -> None:
        raise NotImplementedError

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        raise NotImplementedError

    async def subscribe(self, channel: str, handler: EventHandler) -> str:
        raise NotImplementedError

    async def unsubscribe(self, subscription_id: str) -> None:
        raise NotImplementedError

    async def flush_channel(self, channel: str) -> None:
        raise NotImplementedError

    async def shutdown(self) -> None:
        raise NotImplementedError
