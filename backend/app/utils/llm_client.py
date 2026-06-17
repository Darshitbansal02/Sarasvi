"""
Sarasvi LLM Client — rate-limited, resilient, connection-pooled.

Key guarantees:
  • Concurrency capped by a semaphore (llm_max_concurrent, default 1 = serialized)
  • Minimum inter-call gap enforced (llm_min_interval_sec, default 0.1s)
  • Automatic retry with exponential backoff on HTTP 429 / 5xx
  • Reusable httpx.AsyncClient (connection pooling, no per-request overhead)
  • maxOutputTokens=65536 for Gemini (supports deep, full-length lessons)
  • 120s timeout for large responses
"""

import asyncio
import time
import httpx
import structlog
import re
import json
import io
from PIL import Image, ImageOps, ImageEnhance
from typing import Any, Dict, Optional
from app.config.settings import get_settings

logger = structlog.get_logger(__name__)


def _preprocess_image(file_content: bytes) -> bytes:
    """
    Applies image preprocessing to improve OCR accuracy:
    1. EXIF auto-rotation.
    2. Resizes large images (max 1600px width/height).
    3. Sharpens/increases contrast slightly.
    """
    try:
        image = Image.open(io.BytesIO(file_content))
        # 1. EXIF auto-rotate
        image = ImageOps.exif_transpose(image)
        
        orig_format = image.format or "JPEG"
        
        # 2. Resize if too large
        image.thumbnail((1600, 1600))
        
        # Convert RGBA to RGB for JPEG compatibility if format matches
        if image.mode == 'RGBA' and orig_format in ("JPEG", "JPG"):
            image = image.convert('RGB')
        
        # 3. Enhance contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.2)
        
        out_bytes = io.BytesIO()
        image.save(out_bytes, format=orig_format)
        return out_bytes.getvalue()
    except Exception as e:
        logger.warning("llm.image_preprocessing_failed", error=str(e))
        return file_content


# ---------------------------------------------------------------------------
# Fallback rate-limit constants. The live values come from settings
# (llm_max_concurrent / llm_min_interval_sec); these only apply if those are
# somehow absent. Defaults serialize calls with a permissive sub-second gap.
# ---------------------------------------------------------------------------
_MAX_CONCURRENT = 1        # Serialize all LLM calls
_MIN_INTERVAL_SEC = 0.1    # Sub-second gap between calls
_MAX_RETRIES = 3
_BASE_BACKOFF_SEC = 2.0   # Short retry backoff for quick recovery
_REQUEST_TIMEOUT = 120.0   # 2 minutes for large responses


class LLMClient:
    """
    Unified LLM Client supporting both Groq and Gemini APIs using httpx.
    Dynamically routes based on configured API keys in the environment.
    Rate-limited and resilient against 429 errors.
    """
    def __init__(self):
        settings = get_settings()
        self.groq_api_key = settings.groq_api_key
        self.groq_model = settings.groq_model_strong
        self.gemini_api_key = settings.gemini_api_key
        self.gemini_model = settings.gemini_model

        # Rate limiter state — concurrency + min interval are config-driven so
        # higher-quota keys / more users aren't bottlenecked by a hardcoded "1".
        self._max_concurrent = max(1, int(getattr(settings, "llm_max_concurrent", _MAX_CONCURRENT)))
        self._min_interval = float(getattr(settings, "llm_min_interval_sec", _MIN_INTERVAL_SEC))
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._last_call_time: float = 0.0

        # Reusable HTTP client (connection pooling)
        self._client: httpx.AsyncClient | None = None

        # Token tracking (Priority 1)
        self.last_prompt_tokens: int = 0
        self.last_completion_tokens: int = 0
        self.last_total_tokens: int = 0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_total_tokens: int = 0

    def reset_token_usage(self) -> None:
        """Reset accumulated token metrics."""
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_total_tokens = 0

    def _is_valid_key(self, key: str) -> bool:
        return bool(key and key.strip() not in ("stub", "your_key_here", "your_gemini_key_here", ""))

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init a reusable AsyncClient with connection pooling."""
        if self._client is None or self._client.is_closed:
            # Scale the connection pool with the configured concurrency so a higher
            # llm_max_concurrent isn't bottlenecked by a fixed 5-connection cap.
            max_conns = max(10, self._max_concurrent * 2)
            self._client = httpx.AsyncClient(
                timeout=_REQUEST_TIMEOUT,
                limits=httpx.Limits(
                    max_connections=max_conns,
                    max_keepalive_connections=max(2, self._max_concurrent),
                ),
            )
        return self._client

    async def _enforce_rate_limit(self) -> None:
        """Wait until the minimum interval since the last call has elapsed."""
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug("llm.rate_limit_wait", wait_seconds=round(wait, 1))
            await asyncio.sleep(wait)

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Dict[str, Any]:
        """
        Dynamically routes JSON requests to Gemini or Groq API.
        Rate-limited with retry on 429.
        
        Args:
            max_output_tokens: Override the default token limit for this call.
            temperature: Override the default temperature for this call.
        """
        use_gemini = self._is_valid_key(self.gemini_api_key)
        use_groq = self._is_valid_key(self.groq_api_key)

        if not use_gemini and not use_groq:
            error_msg = (
                "No valid LLM API key detected. Please configure GEMINI_API_KEY or "
                "GROQ_API_KEY in backend/.env to activate the real AI whiteboard."
            )
            logger.error("llm.keys_missing", message=error_msg)
            raise ValueError(error_msg)

        # Acquire semaphore → serialize calls
        async with self._semaphore:
            await self._enforce_rate_limit()

            last_error: Exception | None = None
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    if use_gemini:
                        result = await self._call_gemini(
                            system_prompt, user_prompt,
                            max_output_tokens=max_output_tokens,
                            temperature=temperature,
                        )
                    else:
                        result = await self._call_groq(
                            system_prompt, user_prompt,
                            temperature=temperature,
                        )
                    self._last_call_time = time.monotonic()
                    return result

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 or 500 <= e.response.status_code < 600:
                        backoff = _BASE_BACKOFF_SEC * (2 ** (attempt - 1))
                        logger.warning(
                            "llm.api_error_retry",
                            status_code=e.response.status_code,
                            attempt=attempt,
                            backoff_seconds=backoff,
                            provider="gemini" if use_gemini else "groq",
                        )
                        last_error = e
                        await asyncio.sleep(backoff)
                        continue
                    # Non-retriable HTTP error
                    raise
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    backoff = _BASE_BACKOFF_SEC * attempt
                    logger.warning(
                        "llm.network_error",
                        attempt=attempt,
                        backoff_seconds=backoff,
                        error=str(e),
                    )
                    last_error = e
                    await asyncio.sleep(backoff)
                    continue

            # All retries exhausted
            raise RuntimeError(
                f"LLM call failed after {_MAX_RETRIES} retries"
            ) from last_error

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Dict[str, Any]:
        """Calls Google Gemini API for JSON generation."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent"
        )
        
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.gemini_api_key
        }

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": temperature if temperature is not None else 0.1,
                "maxOutputTokens": max_output_tokens or 65536,
            }
        }

        logger.info("llm.calling_gemini", model=self.gemini_model)
        client = await self._get_client()
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except Exception:
            from app.utils.observability import record_llm_call
            record_llm_call("gemini", ok=False)
            raise
        from app.utils.observability import record_llm_call
        record_llm_call("gemini", ok=True)
        data = response.json()

        # Track token usage (Priority 1)
        usage = data.get("usageMetadata", {})
        self.last_prompt_tokens = usage.get("promptTokenCount", 0)
        self.last_completion_tokens = usage.get("candidatesTokenCount", 0)
        self.last_total_tokens = usage.get("totalTokenCount", 0)
        
        self.total_prompt_tokens += self.last_prompt_tokens
        self.total_completion_tokens += self.last_completion_tokens
        self.total_total_tokens += self.last_total_tokens
        
        parts = data["candidates"][0]["content"]["parts"]
        # Filter out 'thought' parts emitted by Gemini thinking models so only the
        # final answer text is parsed.
        non_thought_parts = [part["text"] for part in parts if not part.get("thought")]
        content = "".join(non_thought_parts) if non_thought_parts else parts[-1]["text"]
        return self._extract_json(content)

    async def _call_groq(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
    ) -> Dict[str, Any]:
        """Calls Groq API for JSON generation."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature if temperature is not None else 0.5,
        }

        logger.info("llm.calling_groq", model=self.groq_model)
        client = await self._get_client()
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except Exception:
            from app.utils.observability import record_llm_call
            record_llm_call("groq", ok=False)
            raise
        from app.utils.observability import record_llm_call
        record_llm_call("groq", ok=True)
        data = response.json()
        
        # Track token usage (Priority 1)
        usage = data.get("usage", {})
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)
        
        self.total_prompt_tokens += self.last_prompt_tokens
        self.total_completion_tokens += self.last_completion_tokens
        self.total_total_tokens += self.last_total_tokens
        
        content = data["choices"][0]["message"]["content"]
        return self._extract_json(content)

    @staticmethod
    def _try_load(text: str) -> Optional[Dict[str, Any]]:
        """Strict parse, then first-object parse. Returns a dict or None."""
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
        try:
            obj, _ = json.JSONDecoder().raw_decode(text.lstrip())
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Extract a JSON object from an LLM response.

        Hardened ordering: parse the RAW text strictly first so already-valid
        output (including legitimate LaTeX escapes like \\frac, \\int) is never
        mangled. Backslash sanitization is applied ONLY as a last resort, after
        strict parsing has failed — the old code sanitized unconditionally and
        could corrupt valid content.
        """
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1).strip()

        # 1) Strict / first-object parse on the unmodified text.
        result = self._try_load(text)
        if result is not None:
            return result

        # 2) Last resort: escape lone backslashes that break JSON, then retry.
        sanitize_pattern = r'(\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})|(\\)'
        sanitized = re.sub(sanitize_pattern, lambda m: m.group(1) if m.group(1) else "\\\\", text)
        result = self._try_load(sanitized)
        if result is not None:
            return result

        safe_text = text.encode('ascii', 'backslashreplace').decode('ascii')
        logger.error("llm.json_decode_failed", text=safe_text)
        raise ValueError(f"Failed to parse LLM output as JSON: {safe_text[:200]}")

    async def generate_json_vision(
        self,
        system_prompt: str,
        user_prompt: str,
        base64_image: str,
        mime_type: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Dict[str, Any]:
        """
        Routes vision JSON requests to Gemini API under rate-limits.
        """
        use_gemini = self._is_valid_key(self.gemini_api_key)
        if not use_gemini:
            raise ValueError("Gemini API key is required for image processing.")

        async with self._semaphore:
            await self._enforce_rate_limit()

            last_error: Exception | None = None
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{self.gemini_model}:generateContent"
                    )
                    headers = {
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.gemini_api_key
                    }
                    payload = {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [
                                    {"text": user_prompt},
                                    {
                                        "inlineData": {
                                            "mimeType": mime_type,
                                            "data": base64_image
                                        }
                                    }
                                ]
                            }
                        ],
                        "systemInstruction": {
                            "parts": [{"text": system_prompt}]
                        },
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "temperature": temperature if temperature is not None else 0.1,
                            "maxOutputTokens": max_output_tokens or 4096,
                        }
                    }

                    logger.info("llm.calling_gemini_vision", model=self.gemini_model)
                    client = await self._get_client()
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    
                    # Track token usage
                    usage = data.get("usageMetadata", {})
                    self.last_prompt_tokens = usage.get("promptTokenCount", 0)
                    self.last_completion_tokens = usage.get("candidatesTokenCount", 0)
                    self.last_total_tokens = usage.get("totalTokenCount", 0)
                    
                    self.total_prompt_tokens += self.last_prompt_tokens
                    self.total_completion_tokens += self.last_completion_tokens
                    self.total_total_tokens += self.last_total_tokens
                    
                    parts = data["candidates"][0]["content"]["parts"]
                    content = "".join([part["text"] for part in parts if not part.get("thought")])
                    self._last_call_time = time.monotonic()
                    return self._extract_json(content)

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 or 500 <= e.response.status_code < 600:
                        backoff = _BASE_BACKOFF_SEC * (2 ** (attempt - 1))
                        logger.warning("llm.vision_api_error_retry", status_code=e.response.status_code, attempt=attempt, backoff_seconds=backoff)
                        last_error = e
                        await asyncio.sleep(backoff)
                        continue
                    raise
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    backoff = _BASE_BACKOFF_SEC * attempt
                    logger.warning("llm.vision_network_error", attempt=attempt, backoff_seconds=backoff, error=str(e))
                    last_error = e
                    await asyncio.sleep(backoff)
                    continue

            raise RuntimeError(f"Vision LLM call failed after {_MAX_RETRIES} retries") from last_error

    async def extract_question_from_image(self, file_content: bytes, mime_type: str) -> dict:
        """
        Stage 1: Preprocesses image and calls Gemini Multimodal to extract question text & diagrams.
        """
        import base64
        preprocessed = _preprocess_image(file_content)
        base64_image = base64.b64encode(preprocessed).decode("utf-8")
        
        system_prompt = (
            "You are Sarasvi's high-fidelity Academic Vision Extractor. "
            "Analyze the image and extract the question details exactly. This can be a math question, "
            "a theoretical question, a coding problem, a science diagram, or any other academic query across any subject "
            "(humanities, sciences, engineering, coding, music, arts, etc.). Extract all text, equations, code, or diagram descriptions exactly. "
            "Always return a valid JSON object matching the requested schema."
        )
        user_prompt = (
            "Analyze this image and extract: \n"
            "1. The exact question or problem text (if it contains math, use LaTeX and wrap the mathematical formulas/expressions/equations in '$' delimiters, e.g. $\\int \\sin(\\log x) dx$; if it contains code, extract the code block exactly; if it is a theoretical/text question, transcribe the text exactly). \n"
            "2. Confidence level of the transcription (0.0 to 1.0). \n"
            "3. Any diagram/figure descriptions, labels, key points, chart details, or illustrations. \n"
            "4. Academic entities (concepts, topics, variables) and relations (equations, definitions, logical connections). \n"
            "Return JSON matching the schema:\n"
            "{\n"
            "  \"question_text\": \"The exact transcribed question/problem text.\",\n"
            "  \"confidence\": 0.95,\n"
            "  \"contains_math\": true,\n"
            "  \"contains_diagram\": false,\n"
            "  \"diagram_description\": \"Detailed description of visual elements, charts, diagrams, structures, drawings, or empty string.\",\n"
            "  \"entities\": [\"concept1\", \"concept2\"],\n"
            "  \"relations\": [\"relation1\", \"relation2\"]\n"
            "}"
        )
        
        try:
            return await self.generate_json_vision(system_prompt, user_prompt, base64_image, mime_type)
        except Exception as e:
            logger.error("llm.extract_question_failed", error=str(e))
            return {
                "question_text": "",
                "confidence": 0.0,
                "contains_math": False,
                "contains_diagram": False,
                "diagram_description": "",
                "entities": [],
                "relations": []
            }

    async def verify_extracted_question(self, extracted_data: dict) -> dict:
        """
        Stage 2: Verification pass using Gemini text API.
        Checks for syntax errors, missing symbols, incomplete equations, cropped sentences, and multiple questions.
        """
        system_prompt = (
            "You are Sarasvi's Extraction Verifier. Analyze the extracted question data "
            "to identify completeness, syntax correctness, or readability issues across any subject. "
            "This includes checking for mathematical syntax errors, broken code/syntax, incomplete sentences, "
            "cropped diagrams, or cases where multiple distinct questions are present. "
            "Always return a valid JSON object conforming to the schema."
        )
        user_prompt = (
            f"Review this extracted question data:\n{json.dumps(extracted_data, indent=2)}\n\n"
            "Check for:\n"
            "- Text completeness (cropped sentences, abruptly ending text)\n"
            "- Mathematical or coding syntax errors (unbalanced brackets, trailing operators, open code tags, broken LaTeX)\n"
            "- Ambiguities (letters or symbols that might be misread, blurry segments)\n"
            "- Multiple questions (does the image contain more than one distinct question/problem?)\n\n"
            "Return JSON matching the schema:\n"
            "{\n"
            "  \"is_valid\": true/false,\n"
            "  \"errors\": [\"List of syntax, completeness, or ambiguity errors discovered, or empty list\"],\n"
            "  \"needs_user_review\": true/false,\n"
            "  \"has_multiple_questions\": true/false,\n"
            "  \"confidence_adjustment\": -0.1 (reduction in confidence if errors found, or 0.0)\n"
            "}"
        )
        
        try:
            verification = await self.generate_json(system_prompt, user_prompt)
            orig_conf = extracted_data.get("confidence", 1.0)
            adjustment = verification.get("confidence_adjustment", 0.0)
            new_conf = max(0.0, min(1.0, orig_conf + adjustment))
            
            needs_review = (
                verification.get("needs_user_review", False) or
                not verification.get("is_valid", True) or
                new_conf < 0.75
            )
            
            verified_data = {**extracted_data}
            verified_data["confidence"] = round(new_conf, 2)
            verified_data["needs_user_review"] = needs_review
            verified_data["verification_errors"] = verification.get("errors", [])
            verified_data["has_multiple_questions"] = verification.get("has_multiple_questions", False)
            return verified_data
        except Exception as e:
            logger.error("llm.verify_question_failed", error=str(e))
            fallback = {**extracted_data}
            fallback["needs_user_review"] = True
            fallback["verification_errors"] = ["Verification runner crashed"]
            return fallback

    async def convert_to_semantic(self, verified_data: dict) -> dict:
        """
        Stage 3: Semantic conversion pass.
        Translates raw question text and diagram entities into structured pedagogical parameters.
        """
        system_prompt = (
            "You are Sarasvi's Semantic Converter. Translate raw question transcriptions and visual diagrams "
            "from any subject area into structured learning parameters for the pedagogical lesson planner. "
            "Always return a valid JSON object matching the requested schema."
        )
        user_prompt = (
            f"Review this verified question data:\n{json.dumps(verified_data, indent=2)}\n\n"
            "Convert it into structured pedagogical parameters. Output JSON matching this schema:\n"
            "{\n"
            "  \"learning_goal\": \"Clear learning goal or objective for a lesson addressing this question.\",\n"
            "  \"math_entities\": [\"List of mathematical terms, equations, symbols, or code constructs involved.\"],\n"
            "  \"diagram_entities\": [\"List of visual, physical, geometric, structural, or diagrammatic elements to render on the whiteboard (e.g. flowchart blocks, timeline, coordinate system, molecules, circuit components, labels, charts).\"]\n"
            "}"
        )
        
        try:
            semantic = await self.generate_json(system_prompt, user_prompt)
            converted = {**verified_data}
            converted["learning_goal"] = semantic.get("learning_goal", verified_data.get("question_text", ""))
            converted["math_entities"] = semantic.get("math_entities", [])
            converted["diagram_entities"] = semantic.get("diagram_entities", [])
            return converted
        except Exception as e:
            logger.error("llm.semantic_conversion_failed", error=str(e))
            fallback = {**verified_data}
            fallback["learning_goal"] = verified_data.get("question_text", "")
            fallback["math_entities"] = []
            fallback["diagram_entities"] = []
            return fallback

    async def run_vision_pipeline(self, file_content: bytes, mime_type: str) -> dict:
        """
        The full 3-stage vision pipeline (extract → conditional verify → semantic),
        shared by the /extract-image endpoint and the interrupt handler so the flow
        lives in one place. The confidence gate is config-driven (settings).
        """
        settings = get_settings()
        extracted = await self.extract_question_from_image(file_content, mime_type)
        if extracted.get("confidence", 0.0) >= settings.vision_confidence_high:
            verified = {
                **extracted,
                "needs_user_review": False,
                "verification_errors": [],
                "has_multiple_questions": False,
            }
        else:
            verified = await self.verify_extracted_question(extracted)
        return await self.convert_to_semantic(verified)

    async def validate_configured_model(self) -> tuple[bool, str]:
        """
        Verify the configured Gemini model exists. Returns (ok, detail).
        Best-effort: when no real key is set, returns ok=True (nothing to check).
        Network failures return ok=True with a note (don't block startup on a
        transient outage); only a definitively-missing model returns ok=False.
        """
        if not self._is_valid_key(self.gemini_api_key):
            return True, "no valid Gemini key; skipping model validation"
        try:
            client = await self._get_client()
            resp = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": self.gemini_api_key},
            )
            resp.raise_for_status()
            names = [m.get("name", "").split("/")[-1] for m in resp.json().get("models", [])]
            if self.gemini_model in names:
                return True, f"model '{self.gemini_model}' available"
            return False, (
                f"configured GEMINI_MODEL '{self.gemini_model}' is not among the "
                f"{len(names)} models this key can access"
            )
        except Exception as e:
            return True, f"model validation skipped (provider unreachable: {e})"

    async def close(self) -> None:
        """Shutdown the reusable HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


llm_client = LLMClient()
