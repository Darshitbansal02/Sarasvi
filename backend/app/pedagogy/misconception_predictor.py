from __future__ import annotations
from typing import Dict, Any, List, Optional
from app.student_model.cognitive_tracker import StudentProfile

class MisconceptionPredictor:
    """
    MisconceptionPredictor — Preemptively predicts conceptual student hurdles
    by analyzing interactive biomechanical signals (mouse hesitations, response delays,
    and partial text inputs) alongside cognitive status profiles.
    """
    def __init__(self):
        # Database of known conceptual misconceptions across domains
        self.misconception_db = {
            "tcp_handshake": [
                {
                    "id": "unacknowledged_syn",
                    "indicators": ["long_latency", "hover_on_packet"],
                    "description": "Student fails to understand that the server must acknowledge the SYN packet before connection proceeds."
                },
                {
                    "id": "stateless_protocols",
                    "indicators": ["fast_quiz_error"],
                    "description": "Student assumes TCP connection is stateless, forgetting it maintains sequence numbers."
                }
            ],
            "recursion": [
                {
                    "id": "missing_base_case",
                    "indicators": ["infinite_execution_worry", "circular_movement"],
                    "description": "Student believes recursive calls execute infinitely without ever hitting the terminal base case."
                },
                {
                    "id": "stack_unwinding_confusion",
                    "indicators": ["slow_response_latency"],
                    "description": "Student does not understand how values return back up the call stack after the base case is reached."
                }
            ],
            "paging": [
                {
                    "id": "virtual_address_conflation",
                    "indicators": ["hover_on_translation", "long_latency"],
                    "description": "Student conflates the virtual address index range with actual physical memory boundaries."
                }
            ],
            "general": [
                {
                    "id": "incomplete_division",
                    "indicators": ["hover_on_numerator", "fast_quiz_error"],
                    "description": "Student Cancels only a single numerator term, neglecting to distribute the division correctly."
                }
            ]
        }

    def predict_misconceptions(
        self,
        profile: StudentProfile,
        recent_interactions: List[Dict[str, Any]],
        current_concept: str
    ) -> List[str]:
        """
        Preemptively evaluates if student cursor circling, pauses, or response delay
        correlate with known misconceptions for the active topic.
        """
        predicted = []
        
        # 1. Extract active indicators from biomechanical signals
        active_indicators = set()
        for evt in recent_interactions:
            etype = evt.get("type", "")
            epayload = evt.get("payload", {})
            
            if etype == "hesitation_indicator" and epayload.get("intensity", 0) > 0.7:
                active_indicators.add("hover_on_numerator")
                active_indicators.add("hover_on_packet")
                active_indicators.add("hover_on_translation")
            if etype == "response_latency" and epayload.get("delay_seconds", 0) > 8.0:
                active_indicators.add("long_latency")
                active_indicators.add("slow_response_latency")
            if etype == "quiz_outcome" and not epayload.get("is_correct", True):
                active_indicators.add("fast_quiz_error")

        # 2. Check current concept in database
        concept_misconceptions = self.misconception_db.get(current_concept, []) + self.misconception_db["general"]
        
        # 3. Predict misconceptions if indicators match or if student confusion is highly spiked
        for m in concept_misconceptions:
            matched_indicators = [ind for ind in m["indicators"] if ind in active_indicators]
            
            # Predict if matched or if confusion score is extreme (>0.75) and topic matches
            if len(matched_indicators) >= 1 or (profile.confusion_index > 0.75 and m["id"] not in predicted):
                predicted.append(m["id"])
                
        return predicted
