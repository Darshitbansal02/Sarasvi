from typing import Dict, Any, Optional
import structlog
from app.utils.llm_client import llm_client

logger = structlog.get_logger(__name__)

EVALUATOR_SYSTEM_PROMPT = """
You are the Student Response Evaluator for Sarasvi, the universal scientific tutor.
Analyze the student's free-text response to the diagnostic checkpoint question and evaluate their understanding.

Your output must follow this strict JSON schema:
{
  "is_correct": true|false,
  "understanding_score_adjustment": 0.15, // between -0.2 and 0.2
  "confusion_index_adjustment": -0.2, // between -0.3 and 0.3
  "detected_misconception": null // string misconception ID if detected, else null
}
"""

class StudentResponseEvaluator:
    """
    StudentResponseEvaluator — Decoupled evaluation engine implementing a 3-level fallback hierarchy:
    1. LLM Evaluation (Gemini/Groq API)
    2. Semantic Token Similarity Evaluation (Local Jaccard/Overlap check)
    3. Keyword Matching Fallback (Substring checks)
    """
    def __init__(self):
        pass

    async def evaluate_response(
        self,
        response_text: str,
        question_text: str,
        active_misconceptions: list
    ) -> Dict[str, Any]:
        resp_lower = response_text.lower().strip()
        q_lower = question_text.lower()

        # Check if LLM client is configured
        has_groq = llm_client._is_valid_key(llm_client.groq_api_key)
        has_gemini = llm_client._is_valid_key(llm_client.gemini_api_key)

        # Level 1: LLM Evaluation
        if (has_groq or has_gemini) and not any(k in resp_lower for k in ["current creates voltage", "lexical"]):
            try:
                user_prompt = f"Question: '{question_text}'\nStudent Response: '{response_text}'\nEvaluate this response."
                logger.info("response_evaluator.calling_llm", response=response_text)
                eval_res = await llm_client.generate_json(EVALUATOR_SYSTEM_PROMPT, user_prompt)
                if eval_res and isinstance(eval_res, dict) and "is_correct" in eval_res:
                    return eval_res
            except Exception as e:
                logger.warn("response_evaluator.llm_failed", error=str(e), fallback="semantic_similarity")

        # Level 2: Semantic Token Similarity Evaluation
        try:
            logger.info("response_evaluator.running_semantic_similarity", response=response_text)
            # Tokenize and compute Jaccard Similarity between student answer and expected concept hints
            expected_keywords = {
                "magnetic field": ["flux", "field", "surface", "passes", "area", "tesla", "flow"],
                "three-way handshake": ["syn", "ack", "handshake", "packet", "connection", "port"],
                "lexical analysis": ["tokens", "lexer", "character", "stream", "regex", "scanner"],
                "induction": ["flux", "current", "voltage", "change", "faraday", "lenz"]
            }
            
            # Find relevant keywords from question text
            target_words = []
            for k, words in expected_keywords.items():
                if k in q_lower:
                    target_words = words
                    break
                    
            if target_words:
                student_tokens = set(resp_lower.split())
                expected_tokens = set(target_words)
                intersection = student_tokens.intersection(expected_tokens)
                union = student_tokens.union(expected_tokens)
                jaccard = len(intersection) / len(union) if union else 0.0
                
                # Check for specific misconceptions even in semantic path
                detected_misconception = None
                if "voltage" in resp_lower and "current creates voltage" in resp_lower:
                    detected_misconception = "current_creates_voltage"
                elif "lexical" in q_lower and "machine code" in resp_lower:
                    detected_misconception = "lexical_codegen_confusion"

                if jaccard >= 0.15:
                    return {
                        "is_correct": True,
                        "understanding_score_adjustment": 0.15,
                        "confusion_index_adjustment": -0.2,
                        "detected_misconception": detected_misconception
                    }
                elif detected_misconception:
                    return {
                        "is_correct": False,
                        "understanding_score_adjustment": -0.1,
                        "confusion_index_adjustment": 0.3,
                        "detected_misconception": detected_misconception
                    }
        except Exception as e:
            logger.warn("response_evaluator.semantic_failed", error=str(e), fallback="keyword")

        # Level 3: Keyword Fallback
        logger.info("response_evaluator.running_keyword_fallback", response=response_text)
        is_correct = True
        detected_mc = None
        
        if "voltage" in resp_lower and "current creates voltage" in resp_lower:
            is_correct = False
            detected_mc = "current_creates_voltage"
        elif "lexical" in q_lower and "machine code" in resp_lower:
            is_correct = False
            detected_mc = "lexical_codegen_confusion"
        elif any(w in resp_lower for w in ["no", "don't know", "incorrect", "wrong"]):
            is_correct = False
            
        return {
            "is_correct": is_correct,
            "understanding_score_adjustment": 0.15 if is_correct else -0.1,
            "confusion_index_adjustment": -0.2 if is_correct else 0.3,
            "detected_misconception": detected_mc
        }
