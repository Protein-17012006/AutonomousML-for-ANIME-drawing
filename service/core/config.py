"""Validated, environment-backed settings at service boundaries.

Settings are deliberately split by consumer and are not cached.  Long-lived
runtime assets may be cached by their infrastructure adapter, but reading the
configuration itself remains deterministic and friendly to process/test env
overrides.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(RuntimeError):
    """An environment setting is missing or cannot satisfy its contract."""


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}
_REPO_ROOT = Path(__file__).resolve().parents[2]


def env_bool(name: str, default: bool = False) -> bool:
    """Compatibility flag parser used by existing feature toggles.

    Keep the historical permissive semantics here: any non-false value enables
    the flag.  New typed settings use the strict parser below.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in _FALSE


def _strict_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ConfigurationError(
        f"{name} must be one of 1/0, true/false, yes/no, or on/off"
    )


def _text(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    raw = os.environ.get(name)
    value = raw.strip() if raw is not None else default
    if required and not value:
        raise ConfigurationError(f"{name} is required")
    return value or None


def _integer(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    try:
        value = default if raw is None else int(raw.strip())
    except (AttributeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}; got {value}")
    return value


def _number(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.environ.get(name)
    try:
        value = default if raw is None else float(raw.strip())
    except (AttributeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}; got {value}")
    return value


def _bounded_number(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = _number(name, default, minimum=minimum)
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be <= {maximum}; got {value}")
    return value


def _choice(name: str, default: str, allowed: set[str]) -> str:
    value = (_text(name, default) or "").lower()
    if value not in allowed:
        choices = " or ".join(sorted(allowed))
        raise ConfigurationError(f"{name} must be {choices}; got {value!r}")
    return value


@dataclass(frozen=True)
class SessionSettings:
    max_sessions: int = 8
    sse_keepalive_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "SessionSettings":
        return cls(
            max_sessions=_integer("COPILOT_MAX_SESSIONS", 8, minimum=1),
            sse_keepalive_seconds=_number(
                "COPILOT_SSE_KEEPALIVE", 15.0, minimum=0.0
            ),
        )


@dataclass(frozen=True)
class ActiveWorkspaceSettings:
    """Bounded, box-local recovery storage for unfinished artist work."""

    root: Path
    ttl_seconds: int = 24 * 60 * 60
    workspace_bytes: int = 4 * 1024 * 1024 * 1024
    global_bytes: int = 32 * 1024 * 1024 * 1024
    free_reserve_bytes: int = 20 * 1024 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "ActiveWorkspaceSettings":
        root = Path(_text("COPILOT_ACTIVE_WORKSPACE_DIR", str(_REPO_ROOT / ".active_workspaces")) or ".active_workspaces")
        return cls(
            root=root,
            ttl_seconds=_integer("COPILOT_ACTIVE_WORKSPACE_TTL", 24 * 60 * 60, minimum=60),
            workspace_bytes=_integer("COPILOT_ACTIVE_WORKSPACE_MAX_BYTES", 4 * 1024 * 1024 * 1024, minimum=1),
            global_bytes=_integer("COPILOT_ACTIVE_WORKSPACE_GLOBAL_BYTES", 32 * 1024 * 1024 * 1024, minimum=1),
            free_reserve_bytes=_integer("COPILOT_ACTIVE_WORKSPACE_FREE_RESERVE_BYTES", 20 * 1024 * 1024 * 1024, minimum=0),
        )


@dataclass(frozen=True)
class AdmissionSettings:
    max_concurrent_sessions: int = 8
    max_concurrent_gpu_jobs: int = 1
    queue_size: int = 8
    queue_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "AdmissionSettings":
        return cls(
            max_concurrent_sessions=_integer(
                "COPILOT_MAX_CONCURRENT_SESSIONS", 8, minimum=1
            ),
            max_concurrent_gpu_jobs=_integer(
                "COPILOT_MAX_CONCURRENT_GPU_JOBS", 1, minimum=1
            ),
            queue_size=_integer("COPILOT_RUNTIME_QUEUE_SIZE", 8, minimum=0),
            queue_timeout_seconds=_number(
                "COPILOT_RUNTIME_QUEUE_TIMEOUT", 30.0, minimum=0.0
            ),
        )


@dataclass(frozen=True)
class MediaIngestSettings:
    max_keys: int = 100
    max_image_bytes: int = 16 * 1024 * 1024
    max_image_total_bytes: int = 64 * 1024 * 1024
    max_video_bytes: int = 256 * 1024 * 1024
    max_frame_pixels: int = 16_777_216
    max_key_total_pixels: int = 67_108_864
    max_frame_dimension: int = 8192
    max_video_frames: int = 7200
    autofit_max_factor: int = 4

    @classmethod
    def from_env(
        cls, defaults: "MediaIngestSettings | None" = None
    ) -> "MediaIngestSettings":
        base = defaults or cls()
        settings = cls(
            max_keys=_integer("COPILOT_MAX_KEYS", base.max_keys, minimum=2),
            max_image_bytes=_integer(
                "COPILOT_MAX_IMAGE_BYTES", base.max_image_bytes, minimum=1
            ),
            max_image_total_bytes=_integer(
                "COPILOT_MAX_IMAGE_TOTAL_BYTES",
                base.max_image_total_bytes,
                minimum=1,
            ),
            max_video_bytes=_integer(
                "COPILOT_MAX_VIDEO_BYTES", base.max_video_bytes, minimum=1
            ),
            max_frame_pixels=_integer(
                "COPILOT_MAX_FRAME_PIXELS", base.max_frame_pixels, minimum=1
            ),
            max_key_total_pixels=_integer(
                "COPILOT_MAX_KEY_TOTAL_PIXELS",
                base.max_key_total_pixels,
                minimum=1,
            ),
            max_frame_dimension=_integer(
                "COPILOT_MAX_FRAME_DIMENSION", base.max_frame_dimension, minimum=1
            ),
            max_video_frames=_integer(
                "COPILOT_MAX_VIDEO_FRAMES", base.max_video_frames, minimum=2
            ),
            autofit_max_factor=_integer(
                "COPILOT_AUTOFIT_MAX_FACTOR", base.autofit_max_factor, minimum=1
            ),
        )
        if settings.max_image_total_bytes < settings.max_image_bytes:
            raise ConfigurationError(
                "COPILOT_MAX_IMAGE_TOTAL_BYTES must be >= COPILOT_MAX_IMAGE_BYTES"
            )
        return settings


@dataclass(frozen=True)
class AgentRateLimitSettings:
    requests_per_minute: int = 20
    max_buckets: int = 1024

    @classmethod
    def from_env(cls) -> "AgentRateLimitSettings":
        return cls(
            requests_per_minute=_integer("COPILOT_AGENT_RPM", 20, minimum=1),
            max_buckets=_integer(
                "COPILOT_AGENT_RATE_BUCKETS", 1024, minimum=1
            ),
        )


@dataclass(frozen=True)
class ImageEditSettings:
    """Transport settings for the box-local image-edit worker."""

    worker_url: str
    timeout_seconds: float
    default_model: str

    @classmethod
    def from_env(cls) -> "ImageEditSettings":
        worker_url = (
            _text(
                "COPILOT_IMAGE_EDIT_WORKER_URL",
                "http://127.0.0.1:8002",
            )
            or ""
        ).rstrip("/")
        parsed = urlparse(worker_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigurationError(
                "COPILOT_IMAGE_EDIT_WORKER_URL must be an absolute http(s) URL"
            )
        return cls(
            worker_url=worker_url,
            # A cold DiffuEraser load plus inference can take several minutes.
            timeout_seconds=_number(
                "COPILOT_IMAGE_EDIT_TIMEOUT", 1200.0, minimum=1.0
            ),
            default_model=_choice(
                "COPILOT_IMAGE_EDIT_MODEL",
                "diffueraser",
                {"diffueraser"},
            ),
        )


@dataclass(frozen=True)
class AuthSettings:
    required: bool
    trust_alb_oidc: bool
    cookie_secure: bool
    region: str | None
    user_pool_id: str | None
    app_client_id: str | None
    alb_arn: str | None

    @classmethod
    def from_env(cls, *, validate_required: bool = True) -> "AuthSettings":
        required = _strict_bool("COPILOT_AUTH_REQUIRED", False)
        settings = cls(
            required=required,
            trust_alb_oidc=_strict_bool("COPILOT_TRUST_ALB_OIDC", False),
            cookie_secure=_strict_bool("COPILOT_AUTH_COOKIE_SECURE", required),
            region=_text("COPILOT_COGNITO_REGION"),
            user_pool_id=_text("COPILOT_COGNITO_USER_POOL_ID"),
            app_client_id=_text("COPILOT_COGNITO_APP_CLIENT_ID"),
            alb_arn=_text("COPILOT_ALB_ARN"),
        )
        if validate_required and (settings.required or settings.trust_alb_oidc):
            missing = [
                name for name, value in (
                    ("COPILOT_COGNITO_REGION", settings.region),
                    ("COPILOT_COGNITO_USER_POOL_ID", settings.user_pool_id),
                    ("COPILOT_COGNITO_APP_CLIENT_ID", settings.app_client_id),
                ) if not value
            ]
            if settings.trust_alb_oidc and not settings.alb_arn:
                missing.append("COPILOT_ALB_ARN")
            if missing:
                raise ConfigurationError(
                    "authentication is enabled but settings are missing: "
                    + ", ".join(missing)
                )
        allow_insecure_cookie = _strict_bool(
            "COPILOT_AUTH_ALLOW_INSECURE_COOKIE", False
        )
        if (validate_required and settings.required and not settings.cookie_secure
                and not allow_insecure_cookie):
            raise ConfigurationError(
                "COPILOT_AUTH_COOKIE_SECURE must remain enabled when "
                "COPILOT_AUTH_REQUIRED=1; local HTTP development must also set "
                "COPILOT_AUTH_ALLOW_INSECURE_COOKIE=1 explicitly"
            )
        return settings


@dataclass(frozen=True)
class DirectorSettings:
    api_key: str | None = field(repr=False)
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"

    @classmethod
    def from_env(cls) -> "DirectorSettings":
        base_url = (
            _text("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1") or ""
        ).rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigurationError(
                "DEEPSEEK_BASE_URL must be an absolute http(s) URL"
            )
        return cls(
            api_key=_text("DEEPSEEK_API_KEY"),
            base_url=base_url,
            model=_text("DEEPSEEK_MODEL", "deepseek-chat", required=True)
            or "deepseek-chat",
        )


@dataclass(frozen=True)
class WebSettings:
    directory: Path

    @classmethod
    def from_env(cls) -> "WebSettings":
        configured = Path(_text("COPILOT_WEB_DIR", "web") or "web").expanduser()
        if not configured.is_absolute():
            configured = _REPO_ROOT / configured
        return cls(directory=configured.resolve())


@dataclass(frozen=True)
class EngineSelectionSettings:
    default_engine: str = "stub"

    @classmethod
    def from_env(cls) -> "EngineSelectionSettings":
        return cls(
            default_engine=_choice(
                "COPILOT_ENGINES", "stub", {"stub", "box"}
            )
        )


@dataclass(frozen=True)
class StoreSettings:
    backend: str
    table_name: str | None
    region: str | None


def _store_settings(
    *, backend_env: str, table_env: str, default_backend: str
) -> StoreSettings:
    backend = _choice(backend_env, default_backend, {"memory", "dynamodb"})
    table_name = _text(table_env)
    if backend == "dynamodb" and not table_name:
        raise ConfigurationError(f"{table_env} is required when {backend_env}=dynamodb")
    return StoreSettings(
        backend=backend,
        table_name=table_name,
        region=_text("COPILOT_COGNITO_REGION"),
    )


def memory_store_settings(default_backend: str) -> StoreSettings:
    return _store_settings(
        backend_env="COPILOT_MEMORY_BACKEND",
        table_env="COPILOT_MEMORY_TABLE",
        default_backend=default_backend,
    )


def feedback_store_settings(default_backend: str) -> StoreSettings:
    return _store_settings(
        backend_env="COPILOT_FEEDBACK_BACKEND",
        table_env="COPILOT_FEEDBACK_TABLE",
        default_backend=default_backend,
    )


@dataclass(frozen=True)
class PublisherSettings:
    enabled: bool
    artifact_bucket: str | None
    sessions_table: str | None
    region: str
    require_owner: bool = False

    @classmethod
    def from_env(
        cls, *, require_owner: bool = False, validate_required: bool = True
    ) -> "PublisherSettings":
        enabled = _strict_bool("AWS_PUBLISH", False)
        settings = cls(
            enabled=enabled,
            artifact_bucket=_text("AWS_ARTIFACT_BUCKET"),
            sessions_table=_text("AWS_SESSIONS_TABLE"),
            region=_text("AWS_REGION", "ap-southeast-1") or "ap-southeast-1",
            require_owner=require_owner,
        )
        if validate_required and enabled:
            if not settings.artifact_bucket:
                raise ConfigurationError("AWS_ARTIFACT_BUCKET is required when AWS_PUBLISH=1")
            if not settings.sessions_table:
                raise ConfigurationError("AWS_SESSIONS_TABLE is required when AWS_PUBLISH=1")
        return settings


@dataclass(frozen=True)
class SessionHistorySettings:
    enabled: bool
    table_name: str | None
    artifact_bucket: str | None
    region: str
    owner_index: str

    @classmethod
    def from_env(cls, *, validate_required: bool = True) -> "SessionHistorySettings":
        settings = cls(
            enabled=_strict_bool("COPILOT_SESSION_HISTORY_ENABLED", False),
            table_name=_text("AWS_SESSIONS_TABLE"),
            artifact_bucket=_text("AWS_ARTIFACT_BUCKET"),
            region=_text("AWS_REGION", "ap-southeast-1") or "ap-southeast-1",
            owner_index=_text(
                "AWS_SESSIONS_OWNER_INDEX", "OwnerSessionsIndex", required=True
            ) or "OwnerSessionsIndex",
        )
        if validate_required and settings.enabled:
            if not settings.table_name:
                raise ConfigurationError(
                    "AWS_SESSIONS_TABLE is required when session history is enabled"
                )
            if not settings.artifact_bucket:
                raise ConfigurationError(
                    "AWS_ARTIFACT_BUCKET is required when session history is enabled"
                )
        return settings


@dataclass(frozen=True)
class BoxSettings:
    vlm_base_url: str
    vlm_model: str
    vlm_max_pixels: int
    rife_root: Path
    rife_model_dir: Path
    rife_device: str
    csq_artifact_path: Path

    @classmethod
    def from_env(cls) -> "BoxSettings":
        base_url = _text(
            "VISION_BASE_URL_CHECK", "http://127.0.0.1:8001/v1"
        ) or ""
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigurationError(
                "VISION_BASE_URL_CHECK must be an absolute http(s) URL"
            )

        max_pixels = _integer("VISION_MAX_PIXELS_CHECK", 320, minimum=1)
        if max_pixels != 320:
            raise ConfigurationError(
                "VISION_MAX_PIXELS_CHECK must be 320 to match the CSQ calibration"
            )

        rife_root = Path(
            _text("COPILOT_RIFE_ROOT", str(Path.home() / "Practical-RIFE")) or ""
        ).expanduser().resolve()
        rife_model_dir = Path(
            _text("COPILOT_RIFE_MODEL_DIR", str(rife_root / "train_log")) or ""
        ).expanduser().resolve()
        artifact = Path(
            _text(
                "COPILOT_CSQ_ARTIFACT_PATH",
                str(_REPO_ROOT / "inbetween_copilot" / "artifacts" / "csq_smallgap_v3.json"),
            ) or ""
        ).expanduser().resolve()

        return cls(
            vlm_base_url=base_url.rstrip("/"),
            vlm_model=_text("VISION_MODEL_CHECK", "qwen3vl-anime", required=True) or "",
            vlm_max_pixels=max_pixels,
            rife_root=rife_root,
            rife_model_dir=rife_model_dir,
            rife_device=_text("COPILOT_RIFE_DEVICE", "cuda", required=True) or "cuda",
            csq_artifact_path=artifact,
        )


@dataclass(frozen=True)
class GimmSettings:
    """Paths and inference options for the official GIMM-VFI checkout."""

    root: Path
    config_path: Path
    checkpoint_path: Path
    device: str
    ds_factor: float

    @classmethod
    def from_env(cls) -> "GimmSettings":
        root = Path(
            _text("COPILOT_GIMM_ROOT", str(Path.home() / "GIMM-VFI")) or ""
        ).expanduser().resolve()
        return cls(
            root=root,
            config_path=Path(
                _text(
                    "COPILOT_GIMM_CONFIG",
                    str(root / "configs" / "gimmvfi" / "gimmvfi_r_arb.yaml"),
                ) or ""
            ).expanduser().resolve(),
            checkpoint_path=Path(
                _text(
                    "COPILOT_GIMM_CHECKPOINT",
                    str(root / "pretrained_ckpt" / "gimmvfi_r_arb_lpips.pt"),
                ) or ""
            ).expanduser().resolve(),
            device=_text(
                "COPILOT_GIMM_DEVICE", "cuda", required=True
            ) or "cuda",
            ds_factor=_bounded_number(
                "COPILOT_GIMM_DS_FACTOR", 1.0, minimum=0.01, maximum=1.0
            ),
        )


def max_sessions() -> int:
    return SessionSettings.from_env().max_sessions


def sse_keepalive_seconds() -> float:
    return SessionSettings.from_env().sse_keepalive_seconds


def max_concurrent_sessions() -> int:
    return AdmissionSettings.from_env().max_concurrent_sessions


def max_concurrent_gpu_jobs() -> int:
    return AdmissionSettings.from_env().max_concurrent_gpu_jobs


def runtime_queue_size() -> int:
    return AdmissionSettings.from_env().queue_size


def runtime_queue_timeout_seconds() -> float:
    return AdmissionSettings.from_env().queue_timeout_seconds


def default_engine() -> str:
    return EngineSelectionSettings.from_env().default_engine
