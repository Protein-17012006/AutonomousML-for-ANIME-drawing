"""Tier-routed Anthropic vision client (ADR-0010).

One shared copy — Orchestrator (Character Spec derivation) and EDA's image
pack (frame checks) both import this. Leaf package: depends on the anthropic
SDK and Pillow only, never on any agent package.

Tiers map to the budget plan in ADR-0010:
  "spec"     -> claude-sonnet-4-6  (once per character; quality matters most)
  "check"    -> claude-haiku-4-5   (bulk per-frame checks)
  "escalate" -> claude-sonnet-4-6  (second look at borderline findings)
Each is overridable via VISION_MODEL_SPEC / VISION_MODEL_CHECK /
VISION_MODEL_ESCALATE so the team can swap tiers without code changes.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re

from PIL import Image

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

_TIER_ENV = {
    "spec": ("VISION_MODEL_SPEC", "claude-sonnet-4-6"),
    "check": ("VISION_MODEL_CHECK", "claude-haiku-4-5"),
    "escalate": ("VISION_MODEL_ESCALATE", "claude-sonnet-4-6"),
}

_TIER_URL_ENV = {
    "spec": "VISION_BASE_URL_SPEC",
    "check": "VISION_BASE_URL_CHECK",
    "escalate": "VISION_BASE_URL_ESCALATE",
}

_openai_clients: dict = {}


def _base_url_for(tier: str) -> str | None:
    """An OpenAI-compatible endpoint for this tier (e.g. Ollama on the team's
    RTX 5090), or None to use Anthropic. Unset by default — paid API remains
    the default behavior."""
    return os.getenv(_TIER_URL_ENV.get(tier, ""), "") or None


def _get_openai_client(base_url: str):
    """Lazy per-URL OpenAI client (same SDK the DeepSeek clients use).
    Function-level so tests can monkeypatch it."""
    if base_url not in _openai_clients:
        from openai import OpenAI
        # explicit per-request timeout + retries: the local box link (Tailscale
        # relay) can blip mid-call; without this the SDK default (600s) hangs the
        # whole benchmark on a single dropped request. Override via VISION_TIMEOUT.
        _openai_clients[base_url] = OpenAI(
            base_url=base_url,
            api_key=os.getenv("VISION_LOCAL_API_KEY", "ollama"),
            timeout=float(os.getenv("VISION_TIMEOUT", "90")),
            max_retries=int(os.getenv("VISION_MAX_RETRIES", "2")))
    return _openai_clients[base_url]


def _encode_image_data_uri(path: str) -> str:
    block = _encode_image(path)
    mime = block["source"]["media_type"]
    return f"data:{mime};base64," + block["source"]["data"]


def _vision_text_openai(prompt: str, image_paths: list[str], *, base_url: str,
                        model: str, system: str, max_tokens: int) -> str:
    content = [{"type": "image_url",
                "image_url": {"url": _encode_image_data_uri(p)}}
               for p in image_paths]
    content.append({"type": "text", "text": prompt})
    try:
        resp = _get_openai_client(base_url).chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": content}],
        )
    except Exception as exc:
        raise RuntimeError(
            f"vision_common: OpenAI-compatible backend at {base_url!r} "
            f"failed: {exc}") from exc
    return resp.choices[0].message.content or ""


# Downscale cap keeps a frame around ~1.6k image tokens.
MAX_LONG_EDGE = 1092

_DEFAULT_SYSTEM = (
    "You are a precise visual QA assistant for 2D animation. "
    "Answer only from what is visible in the supplied images."
)

_client = None


def _model_for(tier: str) -> str:
    env_name, default = _TIER_ENV.get(tier, _TIER_ENV["check"])
    return os.getenv(env_name, default)


def _get_client():
    """Lazy singleton. Kept as a function so tests can monkeypatch it."""
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError(
                "vision_common: ANTHROPIC_API_KEY is not set — add it to .env "
                "before running vision checks.")
        from anthropic import Anthropic
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _encode_image(path: str) -> dict:
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if max(img.size) > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / max(img.size)
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))),
                         resample=Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/png",
                       "data": data}}


def _parse_json(text: str) -> dict:
    """Same forgiving parse as the agents' chat_json: strip fences, then
    fall back to the first {...} block."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def vision_text(prompt: str, image_paths: list[str], *, tier: str = "check",
                system: str | None = None, max_tokens: int = 2000) -> str:
    base_url = _base_url_for(tier)
    if base_url:
        return _vision_text_openai(prompt, image_paths, base_url=base_url,
                                   model=_model_for(tier),
                                   system=system or _DEFAULT_SYSTEM,
                                   max_tokens=max_tokens)
    content = [_encode_image(p) for p in image_paths]
    content.append({"type": "text", "text": prompt})
    msg = _get_client().messages.create(
        model=_model_for(tier),
        max_tokens=max_tokens,
        system=system or _DEFAULT_SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    return next((b.text for b in msg.content if b.type == "text"), "")


def vision_json(prompt: str, image_paths: list[str], *, tier: str = "check",
                system: str | None = None, max_tokens: int = 2000,
                retries: int = 1) -> dict:
    ask = prompt + "\n\nRespond with a single JSON object and nothing else."
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        text = vision_text(ask, image_paths, tier=tier, system=system,
                           max_tokens=max_tokens)
        try:
            return _parse_json(text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("vision_json parse failure (attempt %d): %s", attempt + 1, e)
            last_err = e
    raise ValueError(f"vision_json: unparseable LLM reply: {last_err}")
