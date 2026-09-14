from __future__ import annotations
import base64
import json
import os
import re
from typing import Any
import requests

RESPONSES_URL = "https://api.openai.com/v1/responses"

SYSTEM_GUIDANCE = """You are a conservative precious-metals listing photo analyst. Analyze only what is visibly supported. Never invent a hallmark, maker, weight, or pattern. Distinguish solid silver from silverplate and weighted/hollow-handled construction. Return JSON only."""

PROMPT = """Analyze this marketplace listing image for hidden sterling/silver value.
Return a single JSON object with exactly these keys:
{
  "hallmark_text": ["visible markings, verbatim when legible"],
  "likely_purity": null or one of [0.999,0.958,0.925,0.900,0.835,0.830,0.800],
  "silver_likelihood": integer 0-100,
  "plated_likelihood": integer 0-100,
  "weighted_likelihood": integer 0-100,
  "hollow_handle_likelihood": integer 0-100,
  "knife_or_steel_blade_likelihood": integer 0-100,
  "maker": null or short string,
  "piece_count_visible": null or integer,
  "piece_types": ["short labels"],
  "estimated_weight_low_g": null or number,
  "estimated_weight_high_g": null or number,
  "visual_confidence": integer 0-100,
  "notes": ["brief evidence or uncertainty notes"]
}
Weight estimates must be conservative and should be null unless object type/count is sufficiently visible. If the photo does not show a hallmark close enough to read, say so in notes rather than guessing. Silver-colored appearance alone is weak evidence."""


def configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _extract_output_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for item in data.get("output", []) or []:
        for c in item.get("content", []) or []:
            if isinstance(c.get("text"), str):
                return c["text"]
    raise RuntimeError("Vision response did not contain text output")


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end+1]
    return json.loads(text)


def _data_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    return f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii")


def analyze_image(image_url: str | None = None, image_bytes: bytes | None = None, mime_type: str = "image/jpeg") -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Add OPENAI_API_KEY to .env to enable AI photo analysis")
    if not image_url and not image_bytes:
        raise ValueError("Provide image_url or image_bytes")
    src = image_url or _data_url(image_bytes or b"", mime_type)
    model = os.getenv("OPENAI_VISION_MODEL", "gpt-5.6-luna")
    payload = {
        "model": model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": SYSTEM_GUIDANCE + "\n\n" + PROMPT},
                {"type": "input_image", "image_url": src, "detail": "high"},
            ],
        }],
    }
    r = requests.post(RESPONSES_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload, timeout=60)
    r.raise_for_status()
    result = _parse_json(_extract_output_text(r.json()))
    defaults = {
        "hallmark_text": [], "likely_purity": None, "silver_likelihood": 0,
        "plated_likelihood": 0, "weighted_likelihood": 0,
        "hollow_handle_likelihood": 0, "knife_or_steel_blade_likelihood": 0,
        "maker": None, "piece_count_visible": None, "piece_types": [],
        "estimated_weight_low_g": None, "estimated_weight_high_g": None,
        "visual_confidence": 0, "notes": []
    }
    defaults.update(result)
    return defaults
