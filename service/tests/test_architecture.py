"""Executable dependency rules for the service modular-monolith boundary."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from service.sessions.repository import InMemorySessionRepository
from inbetween_copilot.pipeline.ports import CopilotPorts
from service.infrastructure.engine_bundle import EngineBundle


SERVICE_ROOT = Path(__file__).parents[1]
REMOVED_COMPAT_MODULES = (
    "agent", "annotate", "artifacts", "ask", "auth", "box_vlm", "demo",
    "director_llm", "engine_bundle", "engines", "explain", "feedback_store",
    "glossary", "ingest", "memory_store", "planted", "publisher", "runner",
    "schemas", "session_store", "state", "streaming",
)


def _imports(relative_path: str) -> set[str]:
    tree = ast.parse((SERVICE_ROOT / relative_path).read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_application_services_do_not_depend_on_fastapi():
    for module in ("sessions/service.py", "review/service.py"):
        assert not any(name.startswith("fastapi") for name in _imports(module)), module


def test_feature_apis_use_session_port_not_legacy_global_state():
    for module in (
        "assistant/api.py", "feedback/api.py", "memory/api.py",
        "review/api.py", "sessions/api.py",
    ):
        assert "service.sessions.state" not in _imports(module), module


def test_production_app_composes_durable_session_history_before_static_ui():
    source = (SERVICE_ROOT / "app.py").read_text(encoding="utf-8")
    imports = _imports("app.py")
    assert "service.session_history" in imports
    assert "service.session_history.dependencies" in imports
    assert "configure_session_history(app)" in source
    history_route = "app.include_router(session_history_routes.router)"
    static_mount = 'app.mount("/", StaticFiles('
    assert history_route in source
    assert source.index(history_route) < source.index(static_mount)


def test_optional_phase3_conversation_persistence_is_not_in_current_app():
    assert not (SERVICE_ROOT / "conversations").exists()
    source = (SERVICE_ROOT / "app.py").read_text(encoding="utf-8")
    assert "conversation_routes" not in source
    assert 'prefix="/conversations"' not in source


def test_engine_adapter_is_framework_independent():
    assert not any(
        name.startswith("fastapi") for name in _imports("infrastructure/engines.py"))


def test_service_engine_bundle_extends_core_owned_ports():
    assert issubclass(EngineBundle, CopilotPorts)


def test_compatibility_modules_are_removed():
    for name in REMOVED_COMPAT_MODULES:
        assert not (SERVICE_ROOT / f"{name}.py").exists(), name
        assert importlib.util.find_spec(f"service.{name}") is None, name
    assert not (SERVICE_ROOT / "routes").exists()
    assert not (SERVICE_ROOT / "sessions" / "state.py").exists()
    assert not (SERVICE_ROOT / "memory" / "repository.py").exists()
    assert not (SERVICE_ROOT / "feedback" / "repository.py").exists()
    # planted-error demo removed 2026-07-11 (user decision) — must not regrow
    assert not (SERVICE_ROOT / "media" / "planted.py").exists()


def test_in_memory_repository_owns_state_and_bounded_paths(tmp_path):
    repository = InMemorySessionRepository(cap=1, id_source=iter([1, 2]))
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    repository.register_path(1, str(first))
    repository.save_state(1, {"value": "old"})
    repository.register_path(2, str(second))

    assert repository.path_for(1) is None
    assert repository.state_for(1) is None
    assert not first.exists()
    assert repository.path_for(2) == str(second)
