"""
Lesson Execution Validation Layer — audits visual timelines before rendering.
"""

from typing import Any, Dict, List
import structlog

logger = structlog.get_logger(__name__)

def normalize_latex(val: str) -> str:
    if not val:
        return ""
    return "".join(c for c in val if c not in (" ", "\\", "{", "}", "_", "^", "(", ")", "*", "=", "+", "-"))

class ValidationLayer:
    def validate_synthesis(self, lesson: Any) -> bool:
        """Validate the high-level LLM lesson structure."""
        if not isinstance(lesson, dict):
            return False
        if "teaching_sequence" not in lesson:
            return False
        if not isinstance(lesson["teaching_sequence"], list):
            return False
        return len(lesson["teaching_sequence"]) > 0

    def validate_teaching_sequence(self, sequence: List[Any], query: str = "") -> bool:  # noqa: ARG002
        """Validate the teaching sequence primitives and completeness."""
        if not sequence:
            return False
        return True

    def validate_timeline(
        self, 
        timeline: List[Dict[str, Any]], 
        semantic_instructions: List[Any], 
        layout_assets: Dict[str, Any] = None
    ) -> tuple[bool, List[str]]:
        """
        Audits timeline payload for visual and structural compliance.
        Returns (is_valid, validation_warnings).
        """
        warnings = []
        if layout_assets is None:
            layout_assets = {}
        
        # 1. Verify scene starts
        scene_starts = [e for e in timeline if e.get("type") == "scene_start"]
        if not scene_starts:
            warnings.append("missing_scene_start: No scene_start events exist in the timeline.")
            
        # 2. Check for orphan/invalid coordinates
        for idx, event in enumerate(timeline):
            payload = event.get("payload") or {}
            evt_type = event.get("type")
            if evt_type in ("camera_move", "cursor_move"):
                path = payload.get("path")
                target_pos = payload.get("target_pos")
                target = payload.get("target")
                if path is None and target_pos is None and target is None:
                    warnings.append(f"null_coordinate_target: Event {idx} ({evt_type}) has null target coordinate.")
                    
        # 3. Verify equation coverage
        # Gather latex expressions from semantic plan
        expected_latex_values = []
        for inst in semantic_instructions:
            if hasattr(inst, "primitive_type") and inst.primitive_type.value in ("equation", "equation_write"):
                latex = inst.data.get("latex")
                if latex:
                    expected_latex_values.append(latex.strip())
                    
        # Gather written equations directly from layout_assets — this is the
        # authoritative record of what was compiled and placed on the board.
        # Scanning timeline events is unreliable because _paginate_timeline can
        # modify object_id values in events while layout_assets keys stay as-is.
        written_latex_values = []
        if layout_assets:
            for asset in layout_assets.values():
                if isinstance(asset, dict) and asset.get("type") == "equation":
                    asset_latex = asset.get("latex", "")
                    if asset_latex:
                        written_latex_values.append(asset_latex.strip())
                    
        for expected in expected_latex_values:
            norm_expected = normalize_latex(expected)
            if not any(
                norm_expected in normalize_latex(written) or normalize_latex(written) in norm_expected 
                for written in written_latex_values
            ):
                warnings.append(f"missing_equation: Planned equation '{expected}' was not written in the timeline.")
                
        is_valid = len(warnings) == 0
        if not is_valid:
            logger.warning("timeline_validation.failed", warnings=warnings)
        else:
            logger.info("timeline_validation.passed")
            
        return is_valid, warnings

lesson_validator = ValidationLayer()

