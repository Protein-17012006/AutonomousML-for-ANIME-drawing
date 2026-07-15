"""Infrastructure adapter: DeepSeek director factory for the live correction loop.

make_reason_fn() -> reason_fn(prompt)->dict for director.decide, or None when no
API key is configured (box_engines then falls back to the deterministic
decide_fixed ladder — today's behaviour). FAIL-SAFE: any endpoint failure or
malformed reply returns {} so decide() falls back for that round; a run can
never crash or regress below the fixed ladder. Design: vault 'Animation QA -
DeepSeek Director Wiring (live path) - Design'. Kept legacy-free on purpose —
do not import the quarantined legacy/*/llm/deepseek_client.py.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from service.core.json_tools import first_json_object
from service.core.config import ConfigurationError, DirectorSettings

# DeepSeek CoT models spend max_tokens on hidden reasoning (ADR-0007): give the
# JSON answer headroom or small caps get fully consumed by the CoT.
_REASONING_MODELS = ("reasoner", "v4-pro")
_REASONING_HEADROOM = 8000


def _default_poster(url: str, body: bytes, headers: dict) -> str:
    req = urllib.request.Request(url, data=body, headers=headers)
    return urllib.request.urlopen(req, timeout=120).read().decode("utf-8")


def _client_config(api_key: str | None, base_url: str | None,
                   model: str | None, max_tokens: int):
    """Resolve the shared OpenAI-compatible endpoint contract once."""
    settings = DirectorSettings.from_env()
    key = (api_key if api_key is not None else settings.api_key or "").strip()
    if not key:
        return None
    base = (base_url or settings.base_url).rstrip("/")
    from urllib.parse import urlparse
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError("DeepSeek base URL must be absolute http(s)")
    selected_model = model or settings.model
    effective_max = max_tokens + (
        _REASONING_HEADROOM
        if any(token in selected_model for token in _REASONING_MODELS) else 0
    )
    return {
        "url": base + "/chat/completions",
        "model": selected_model,
        "max_tokens": effective_max,
        "headers": {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    }


def make_reason_fn(*, api_key: str | None = None, base_url: str | None = None,
                   model: str | None = None, max_tokens: int = 256, poster=None):
    """Build the director's reason_fn, or return None when unconfigured."""
    client = _client_config(api_key, base_url, model, max_tokens)
    if client is None:
        return None
    post = poster or _default_poster
    url, model = client["url"], client["model"]
    eff_max, headers = client["max_tokens"], client["headers"]
    _warned = []   # one-shot "director degraded" notice, mirrors _post_vlm

    def reason_fn(prompt: str) -> dict:
        body = json.dumps({
            "model": model, "temperature": 0, "max_tokens": eff_max,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        try:
            reply = json.loads(post(url, body, headers))
            txt = reply["choices"][0]["message"]["content"] or ""
            return first_json_object(txt) or {}
        except Exception as e:
            if not _warned:
                print(f"[director_llm] DeepSeek at {url} unavailable ({e!r}); "
                      f"director falls back to the fixed ladder.",
                      file=sys.stderr, flush=True)
                _warned.append(True)
            return {}

    return reason_fn


def make_ask_fn(*, api_key: str | None = None, base_url: str | None = None,
                model: str | None = None, max_tokens: int = 512, poster=None):
    """Text-reply sibling of make_reason_fn for the grounded Q&A endpoint
    (vault 'Chat-First Copilot Surface' §3). Returns the reply TEXT; '' on any
    failure (the route then serves the deterministic fallback). None when no
    API key is configured."""
    client = _client_config(api_key, base_url, model, max_tokens)
    if client is None:
        return None
    post = poster or _default_poster
    url, model = client["url"], client["model"]
    eff_max, headers = client["max_tokens"], client["headers"]
    _warned = []

    def ask_fn(prompt: str) -> str:
        body = json.dumps({
            "model": model, "temperature": 0, "max_tokens": eff_max,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        try:
            reply = json.loads(post(url, body, headers))
            return str(reply["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:
            if not _warned:
                print(f"[director_llm] DeepSeek /ask at {url} unavailable ({e!r}); "
                      f"serving the deterministic fallback answer.",
                      file=sys.stderr, flush=True)
                _warned.append(True)
            return ""

    return ask_fn


def _default_stream_opener(url: str, body: bytes, headers: dict):
    req = urllib.request.Request(url, data=body, headers=headers)
    resp = urllib.request.urlopen(req, timeout=120)
    yield from resp


def make_ask_stream_fn(*, api_key: str | None = None, base_url: str | None = None,
                       model: str | None = None, max_tokens: int = 512, opener=None):
    """Streaming sibling of make_ask_fn (UIA /agent/stream): returns a function
    that yields reply-text deltas from DeepSeek's SSE (`stream: true`). Yields
    nothing on any failure (the caller then serves the fallback decision);
    None when no API key is configured."""
    client = _client_config(api_key, base_url, model, max_tokens)
    if client is None:
        return None
    op = opener or _default_stream_opener
    url, model = client["url"], client["model"]
    eff_max, headers = client["max_tokens"], client["headers"]
    _warned = []

    def ask_stream_fn(prompt: str):
        body = json.dumps({
            "model": model, "temperature": 0, "max_tokens": eff_max, "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        try:
            for line in op(url, body, headers):
                if isinstance(line, bytes):
                    line = line.decode("utf-8", "replace")
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                delta = (json.loads(payload)["choices"][0]
                         .get("delta", {}).get("content") or "")
                if delta:
                    yield delta
        except Exception as e:
            if not _warned:
                print(f"[director_llm] DeepSeek stream at {url} died ({e!r}); "
                      f"the agent stream serves its fallback decision.",
                      file=sys.stderr, flush=True)
                _warned.append(True)
            return

    return ask_stream_fn
