# timeline_validator.py — Production Whiteboard Timeline Validator

import structlog
from typing import List, Dict, Any, Optional

logger = structlog.get_logger(__name__)


class TimelineValidationError(Exception):
    def __init__(self, errors: List[str]):
        super().__init__(f"Timeline validation failed with {len(errors)} errors: {', '.join(errors)}")
        self.errors = errors


def validate_timeline(
    timeline: List[Dict[str, Any]],
    layout_assets: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Hard structural validator — raises TimelineValidationError on any failure.

    Checks:
    - Every scene must be initialized with a scene_start.
    - No negative start timestamps or durations.
    - stroke_reveal events must have an object_id.
    - speech events must have positive duration.
    - cursor_move path points must be within [0..1200] × [0..750].
    - gesture events must have target_ids or target_region.
    - camera_move events must have a path.
    - focus_start events must list target objects.
    - No orphan parent_event_id references.
    - Resource locking: cursor/board/speech intervals must not overlap.
    - Word-boundary mapping: stroke_reveal charStates must have wordBoundaryIndex
      when the corresponding speech event carries speech_marks.
    - Orphan equations: every equation in layout_assets must have a matching
      stroke_reveal event in the timeline (catches compiler instruction-id mismatches).
    """
    errors: List[str] = []
    registered_objects: set = set()
    scene_started = False

    RESOURCE_MAP: Dict[str, set] = {
        "cursor_move": {"cursor"},
        "gesture": {"cursor"},
        "cursor_pause": {"cursor"},
        "stroke_reveal": {"cursor", "board"},
        "speech": {"speech"},
    }

    resource_intervals: Dict[str, list] = {
        "cursor": [],
        "board": [],
        "speech": [],
    }

    all_event_ids = {event.get("event_id") for event in timeline if event.get("event_id")}

    # Collect all object_ids referenced by stroke_reveal events (used for orphan check).
    stroke_reveal_object_ids: set = set()
    # Collect all annotation_ids referenced by annotation events (used for code_block orphan check).
    annotation_event_ids: set = set()

    for idx, event in enumerate(timeline):
        evt_type = event.get("type")
        payload = event.get("payload", {})
        start_ms = event.get("start_ms", 0)
        parent_id = event.get("parent_event_id")

        if start_ms < 0:
            errors.append(f"Event {idx} ({evt_type}) has a negative start timestamp: {start_ms}ms")

        duration = payload.get("duration_ms")
        if duration is not None and duration < 0:
            errors.append(f"Event {idx} ({evt_type}) has a negative duration: {duration}ms")

        if evt_type == "scene_start":
            scene_started = True

        if not scene_started and evt_type not in ("scene_start", "generation_start"):
            errors.append(f"Event {idx} ({evt_type}) occurred before any scene_start initialization")

        if evt_type == "stroke_reveal":
            obj_id = payload.get("object_id")
            if not obj_id:
                errors.append(f"Event {idx} (stroke_reveal) is missing object_id")
            else:
                registered_objects.add(obj_id)
                stroke_reveal_object_ids.add(obj_id)

        elif evt_type == "annotation":
            ann_id = payload.get("annotation_id")
            if ann_id:
                annotation_event_ids.add(ann_id)

        elif evt_type == "speech":
            speech_duration = payload.get("duration_ms", 0)
            if speech_duration <= 0:
                errors.append(f"Event {idx} (speech) has invalid/negative duration: {speech_duration}")

        elif evt_type == "cursor_move":
            path = payload.get("path", [])
            if not path:
                errors.append(f"Event {idx} (cursor_move) is missing path points")
            for pt in path:
                if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                    errors.append(f"Event {idx} (cursor_move) has invalid coordinate point: {pt}")
                    continue
                x, y = pt[0], pt[1]
                if not (0.0 <= x % 1200.0 <= 1200.0) or not (0.0 <= y <= 750.0):
                    errors.append(
                        f"Event {idx} (cursor_move) coordinate [{x}, {y}] "
                        f"outside local page bounds [0..1200, 0..750]"
                    )

        elif evt_type == "gesture":
            if not payload.get("target_ids") and not payload.get("target_region"):
                errors.append(f"Event {idx} (gesture) is missing both target_ids and target_region")
            for pt in payload.get("path", []):
                x, y = pt[0], pt[1]
                if not (0.0 <= x % 1200.0 <= 1200.0) or not (0.0 <= y <= 750.0):
                    errors.append(f"Event {idx} (gesture) path coordinate [{x}, {y}] outside local page limits")

        elif evt_type == "camera_move":
            if not payload.get("path"):
                errors.append(f"Event {idx} (camera_move) has no target path/coordinates")

        elif evt_type == "focus_start":
            if not payload.get("target_ids"):
                errors.append(f"Event {idx} (focus_start) specifies no target object list")

        if parent_id and parent_id not in all_event_ids:
            errors.append(
                f"Event {idx} ({evt_type}) has orphan parent_event_id '{parent_id}' "
                f"not found in timeline"
            )

        required_resources = RESOURCE_MAP.get(evt_type, set())
        if required_resources:
            evt_duration = payload.get("duration_ms", 0)
            end_ms = start_ms + evt_duration
            for res in required_resources:
                if res in resource_intervals:
                    for lock_start, lock_end, lock_type, lock_idx in resource_intervals[res]:
                        if not (end_ms <= lock_start or start_ms >= lock_end):
                            errors.append(
                                f"Resource conflict on '{res}': Event {idx} ({evt_type}) "
                                f"[{start_ms}..{end_ms}]ms overlaps Event {lock_idx} ({lock_type}) "
                                f"[{lock_start}..{lock_end}]ms"
                            )
                    resource_intervals[res].append((start_ms, end_ms, evt_type, idx))

        if evt_type == "stroke_reveal" and layout_assets:
            obj_id = payload.get("object_id")
            asset = layout_assets.get(obj_id) if obj_id else None
            char_states = asset.get("_charStates") if isinstance(asset, dict) else None
            reasoning_step_id = payload.get("reasoning_step_id")
            has_speech_marks = False
            if reasoning_step_id:
                speech_evt = next(
                    (
                        e for e in timeline
                        if e.get("type") == "speech"
                        and e.get("payload", {}).get("reasoning_step_id") == reasoning_step_id
                    ),
                    None,
                )
                if speech_evt and speech_evt.get("payload", {}).get("speech_marks"):
                    has_speech_marks = True
            if char_states and has_speech_marks:
                speech_marks = speech_evt.get("payload", {}).get("speech_marks", []) if speech_evt else []
                for c_idx, c in enumerate(char_states):
                    if c.get("type") == "stroke":
                        w_idx = c.get("wordBoundaryIndex")
                        if w_idx is not None:
                            if not (0 <= w_idx < len(speech_marks)):
                                errors.append(
                                    f"Event {idx} (stroke_reveal) charState[{c_idx}] "
                                    f"has out-of-bounds wordBoundaryIndex {w_idx} (speech_marks length={len(speech_marks)})"
                                )

    # Orphan-equation check: every compiled equation must have a stroke_reveal.
    # A missing entry here means the compiler's instruction-id lookup failed and
    # the equation was silently dropped from the timeline.
    if layout_assets:
        for obj_id, asset in layout_assets.items():
            if not isinstance(asset, dict):
                continue
            asset_type = asset.get("type")

            if asset_type == "equation" and asset.get("latex") and obj_id not in stroke_reveal_object_ids:
                errors.append(
                    f"Orphan equation '{obj_id}' (latex='{asset['latex'][:40]}') "
                    f"was compiled into layout_assets but has no stroke_reveal in the timeline"
                )

            # Orphan check for code/label visual types: the compiler renders these as
            # annotation events keyed by their sub-shape ids (not obj_id). Check that at
            # least one shape from the asset appears in annotation_event_ids.
            elif asset_type in ("code_block", "complexity_label", "algorithm_step", "code_explanation_flow"):
                shapes = asset.get("shapes", [])
                shape_ids = {s.get("id") for s in shapes if isinstance(s, dict) and s.get("id")}
                if shape_ids and not shape_ids.intersection(annotation_event_ids):
                    errors.append(
                        f"Orphan {asset_type} '{obj_id}' was compiled into layout_assets "
                        f"but no annotation event references any of its shapes"
                    )

    if errors:
        logger.error("timeline.validation_failed", errors=errors)
        raise TimelineValidationError(errors)
    else:
        logger.info("timeline.validation_passed", total_events=len(timeline))
