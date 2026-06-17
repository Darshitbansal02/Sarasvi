# teacher_motion_planner.py — Authoritative Pointer & Camera Attention Planner

import math
import uuid
from typing import Any, Dict, List, Tuple, Optional

class TeacherMotionPlanner:
    """
    Authoritative Motion Trajectory Planner:
    Coordinates cursor tracks, hesitation wobbles, gesture shapes,
    and viewport camera panning, incorporating physics modulators
    and context-derived emotion profiles.
    """

    def derive_emotion_from_context(self, difficulty: float, action: str, speech_stress: float = 0.0) -> Dict[str, float]:
        """Ported from emotionEngine.ts deriveEmotionFromContext."""
        if difficulty > 0.65:
            return {
                "calmness": 0.85,
                "confidence": 0.6,
                "energy": 0.35,
                "urgency": 0.15,
                "enthusiasm": min(1.0, 0.4 + speech_stress * 0.3)
            }
        elif difficulty < 0.3:
            return {
                "calmness": 0.25,
                "confidence": 0.9,
                "energy": 0.85,
                "urgency": 0.55,
                "enthusiasm": 0.5
            }
        elif speech_stress > 0.6 or action in ["underline", "emphasize", "highlight"]:
            return {
                "calmness": 0.3,
                "confidence": 0.8,
                "energy": 0.75,
                "urgency": 0.35,
                "enthusiasm": 0.95
            }
        else:
            return {
                "energy": 0.5,
                "urgency": 0.3,
                "calmness": 0.6,
                "confidence": 0.7,
                "enthusiasm": 0.5
            }

    def get_physics_modulators(self, emotion: Dict[str, float], pacing: str = "normal") -> Dict[str, float]:
        """Ported from emotionEngine.ts getModulators."""
        energy = emotion.get("energy", 0.5)
        urgency = emotion.get("urgency", 0.3)
        calmness = emotion.get("calmness", 0.6)
        confidence = emotion.get("confidence", 0.7)
        enthusiasm = emotion.get("enthusiasm", 0.5)

        spring_stiffness = (1.0 + energy * 0.45 + urgency * 0.35) * (1.0 - calmness * 0.3)
        spring_damping = (1.0 + calmness * 0.35) * (1.0 - urgency * 0.25)
        spring_mass = (1.0 - energy * 0.25) * (1.0 + calmness * 0.2)
        stroke_dur = max(0.55, min(1.6, (1.25 - energy * 0.35 - urgency * 0.2) * (1.0 + calmness * 0.3)))
        move_dur = max(0.55, min(1.5, (1.15 - energy * 0.3 - confidence * 0.2)))
        hesitation_dur = max(0.25, min(1.85, (1.35 - confidence * 0.55) * (1.0 + calmness * 0.35)))
        gesture_amplitude = max(0.5, min(1.7, 0.75 + enthusiasm * 0.65 + energy * 0.25))
        wobble_intensity = max(0.15, min(1.9, 1.05 - confidence * 0.65 + urgency * 0.45))

        pacing_factor = 1.0
        pacing_str = str(pacing).lower()
        if pacing_str == "slow":
            pacing_factor = 1.3
        elif pacing_str == "fast":
            pacing_factor = 0.8

        return {
            "springStiffnessMultiplier": spring_stiffness,
            "springDampingMultiplier": spring_damping,
            "springMassMultiplier": spring_mass,
            "strokeDurationMultiplier": stroke_dur * pacing_factor,
            "moveDurationMultiplier": move_dur * pacing_factor,
            "hesitationDurationMultiplier": hesitation_dur * pacing_factor,
            "gestureAmplitudeMultiplier": gesture_amplitude,
            "wobbleIntensity": wobble_intensity
        }

    def plan_cursor_move(self, start: Tuple[float, float], end: Tuple[float, float], duration_ms: int, modulators: Optional[Dict[str, float]] = None) -> List[Tuple[float, float]]:
        """Generates a smooth critical-damped path between two points with emotional drift/wobble."""
        path = []
        steps = max(5, duration_ms // 16)  # ~60fps ticks
        wobble = modulators.get("wobbleIntensity", 1.0) if modulators else 0.5
        
        for i in range(steps + 1):
            t = i / steps
            eased_t = 3 * t * t - 2 * t * t * t
            x = start[0] + (end[0] - start[0]) * eased_t
            y = start[1] + (end[1] - start[1]) * eased_t
            
            # Inject subtle tremor wobble based on active physics modulators
            if i > 0 and i < steps:
                tremor = math.sin(i * 1.5) * 1.2 * wobble
                x += tremor
                y += tremor * 0.5

            # Clamp coordinates to canvas board boundary limits
            x = max(0.0, min(1200.0, x))
            y = max(0.0, min(750.0, y))
            path.append((x, y))
            
        return path

    def plan_gesture_circle(self, cx: float, cy: float, rx: float, ry: float, duration_ms: int) -> List[Tuple[float, float]]:
        """Generates trajectory points around an elliptical bounds target."""
        path = []
        steps = max(12, duration_ms // 16)
        
        for i in range(steps + 1):
            angle = (i / steps) * math.pi * 2 - math.pi / 2
            wobble = math.sin(i * 1.7) * 2.0
            px = cx + (rx + wobble) * math.cos(angle)
            py = cy + (ry + wobble * 0.7) * math.sin(angle)
            px = max(0.0, min(1200.0, px))
            py = max(0.0, min(750.0, py))
            path.append((px, py))
            
        return path

    def plan_gesture_underline(self, start_x: float, y: float, width: float) -> List[Tuple[float, float]]:
        """Generates coordinate path for underline gesture."""
        path = []
        steps = max(5, int(width // 20))
        for i in range(steps + 1):
            t = i / steps
            wobble = math.sin(t * math.pi * 3) * 1.5
            px = start_x + t * width
            py = y + wobble
            px = max(0.0, min(1200.0, px))
            py = max(0.0, min(750.0, py))
            path.append((px, py))
        return path

    def plan_gesture_arrow(self, x1: float, y1: float, x2: float, y2: float) -> List[Tuple[float, float]]:
        """Generates arrow gesture coordinate paths."""
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length == 0:
            return [(x1, y1)]
        nx = dx / length
        ny = dy / length

        points = [
            (x1, y1),
            (x2 - nx * 15, y2 - ny * 15),
            (x2 - nx * 15 - ny * 8, y2 - ny * 15 + nx * 8),
            (x2, y2),
            (x2 - nx * 15 + ny * 8, y2 - ny * 15 - nx * 8),
            (x2 - nx * 15, y2 - ny * 15)
        ]
        return [(max(0.0, min(1200.0, p[0])), max(0.0, min(750.0, p[1]))) for p in points]

    def plan_gesture_bracket(self, x: float, y: float, height: float) -> List[Tuple[float, float]]:
        """Bracket bounds path coordinates."""
        return [
            (max(0.0, min(1200.0, x + 10)), max(0.0, min(750.0, y))),
            (max(0.0, min(1200.0, x)), max(0.0, min(750.0, y))),
            (max(0.0, min(1200.0, x)), max(0.0, min(750.0, y + height))),
            (max(0.0, min(1200.0, x + 10)), max(0.0, min(750.0, y + height)))
        ]

    def plan_gesture_path(self, gesture_type: str, bounds: Dict[str, float]) -> List[Tuple[float, float]]:
        """Generates dynamic coordinates for standard gestures."""
        x = bounds.get("x", 0.0)
        y = bounds.get("y", 0.0)
        width = bounds.get("width", 100.0)
        height = bounds.get("height", 50.0)
        cx = x + width / 2.0
        cy = y + height / 2.0
        rx = width / 2.0 + 15.0
        ry = height / 2.0 + 15.0

        g_type = gesture_type.lower()
        if g_type == "circle":
            return self.plan_gesture_circle(cx, cy, rx, ry, 600)
        elif g_type == "underline":
            return self.plan_gesture_underline(x - 10, y + height + 8, width + 20)
        elif g_type == "arrow":
            return self.plan_gesture_arrow(x, cy, x + width, cy)
        elif g_type == "bracket":
            return self.plan_gesture_bracket(x - 20, y - 10, height + 20)
        else: # Fallback circle
            return self.plan_gesture_circle(cx, cy, rx, ry, 600)

    def plan_camera_panning(self, current_pos: Tuple[float, float], target_pos: Tuple[float, float], duration_ms: int) -> List[Dict[str, Any]]:
        """Generates camera timeline panned events."""
        events = []
        steps = max(5, duration_ms // 100)
        
        for i in range(steps + 1):
            t = i / steps
            eased_t = 3 * t * t - 2 * t * t * t
            cx = current_pos[0] + (target_pos[0] - current_pos[0]) * eased_t
            cy = current_pos[1] + (target_pos[1] - current_pos[1]) * eased_t
            events.append({
                "x": max(0.0, min(1200.0, cx)),
                "y": max(0.0, min(750.0, cy)),
                "zoom": 1.0
            })
            
        return events

teacher_motion_planner = TeacherMotionPlanner()

