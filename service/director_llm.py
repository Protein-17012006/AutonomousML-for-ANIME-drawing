"""DeepSeek director reason_fn factory for the live correction loop.

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
import os
import re
import sys
import urllib.request

# DeepSeek CoT models spend max_tokens on hidden reasoning (ADR-0007): give the
# JSON answer headroom or small caps get fully consumed by the CoT.
_REASONING_MODELS = ("reasoner", "v4-pro")
_REASONING_HEADROOM = 8000
_JSON_RE = re.compile(r"\{.*\}", re.S)


def _default_poster(url: str, body: bytes, headers: dict) -> str:
    req = urllib.request.Request(url, data=body, headers=headers)
    return urllib.request.urlopen(req, timeout=120).read().decode("utf-8")


def make_reason_fn(*, api_key: str | None = None, base_url: str | None = None,
                   model: str | None = None, max_tokens: int = 256, poster=None):
    """Build the director's reason_fn, or return None when unconfigured."""
    api_key = (api_key if api_key is not None
               else os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not api_key:
        return None
    base = (base_url or os.environ.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com/v1").rstrip("/")
    model = model or os.environ.get("DEEPSEEK_MODEL", "").strip() or "deepseek-chat"
    post = poster or _default_poster
    url = base + "/chat/completions"
    eff_max = max_tokens + (_REASONING_HEADROOM
                            if any(t in model for t in _REASONING_MODELS) else 0)
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {api_key}"}
    _warned = []   # one-shot "director degraded" notice, mirrors _post_vlm

    def reason_fn(prompt: str) -> dict:
        body = json.dumps({
            "model": model, "temperature": 0, "max_tokens": eff_max,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        try:
            reply = json.loads(post(url, body, headers))
            txt = reply["choices"][0]["message"]["content"] or ""
            m = _JSON_RE.search(txt)
            return json.loads(m.group(0)) if m else {}
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
    api_key = (api_key if api_key is not None
               else os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not api_key:
        return None
    base = (base_url or os.environ.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com/v1").rstrip("/")
    model = model or os.environ.get("DEEPSEEK_MODEL", "").strip() or "deepseek-chat"
    post = poster or _default_poster
    url = base + "/chat/completions"
    eff_max = max_tokens + (_REASONING_HEADROOM
                            if any(t in model for t in _REASONING_MODELS) else 0)
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {api_key}"}
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
