"""Box-free tests for the DeepSeek director reason_fn factory (design: vault
'DeepSeek Director Wiring'). No network: the poster seam is injected."""
import json

from service.infrastructure.director_llm import make_reason_fn


def _api_reply(content: str) -> str:
    """Fabricate a raw OpenAI-compatible chat/completions HTTP body."""
    return json.dumps({"choices": [{"message": {"content": content}}]})


def test_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert make_reason_fn() is None                      # -> decide_fixed path


def test_parses_json_action_from_reply():
    calls = {}

    def poster(url, body, headers):
        calls["url"] = url
        calls["body"] = json.loads(body)
        calls["headers"] = headers
        return _api_reply('Reasoning...\n{"action": "ask_key", "method": "", "reason": "gap too large"}')

    fn = make_reason_fn(api_key="k", base_url="https://api.deepseek.com/v1",
                        model="deepseek-chat", poster=poster)
    out = fn("prompt text")
    assert out == {"action": "ask_key", "method": "", "reason": "gap too large"}
    assert calls["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert calls["body"]["temperature"] == 0
    assert calls["body"]["messages"] == [{"role": "user", "content": "prompt text"}]
    assert calls["headers"]["Authorization"] == "Bearer k"


def test_reasoning_model_gets_headroom():
    seen = {}

    def poster(url, body, headers):
        seen["max_tokens"] = json.loads(body)["max_tokens"]
        return _api_reply("{}")

    make_reason_fn(api_key="k", model="deepseek-v4-pro", max_tokens=256, poster=poster)("p")
    assert seen["max_tokens"] == 256 + 8000              # ADR-0007

    make_reason_fn(api_key="k", model="deepseek-chat", max_tokens=256, poster=poster)("p")
    assert seen["max_tokens"] == 256                     # non-reasoning: no headroom


def test_poster_failure_returns_empty_dict():
    def poster(url, body, headers):
        raise OSError("connection refused")

    fn = make_reason_fn(api_key="k", model="deepseek-chat", poster=poster)
    assert fn("p") == {}                                 # decide() falls back that round


def test_non_json_reply_returns_empty_dict():
    fn = make_reason_fn(api_key="k", model="deepseek-chat",
                        poster=lambda u, b, h: _api_reply("no json here"))
    assert fn("p") == {}
