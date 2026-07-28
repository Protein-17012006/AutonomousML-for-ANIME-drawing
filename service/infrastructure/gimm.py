"""Process-local adapter for the official GIMM-VFI implementation.

The upstream project exposes a research/demo script rather than an importable
service API.  This module turns its model into the same ``[a, mid, b]`` callable
contract used by the co-pilot's existing RIFE adapter.  Heavy imports and model
loading stay lazy so non-GPU development and tests remain box-free.
"""
from __future__ import annotations

import importlib
import sys
import threading
from functools import partial
from pathlib import Path
from typing import Callable

import numpy as np

from service.core.config import ConfigurationError, GimmSettings


def _require_file(path: Path, setting: str) -> None:
    if not path.is_file():
        raise ConfigurationError(f"{setting} is not a file: {path}")


def _official_modules(root: Path):
    """Import GIMM's top-level ``models`` and ``utils`` packages safely."""
    # Upstream GIMM calls CuPy's old private compile_with_cache helper. CuPy 13+
    # removed that alias (needed on the box's Python 3.12/CUDA 12 stack), while
    # RawModule provides the same compiled-module/get_function interface.
    import cupy

    if not hasattr(cupy.cuda, "compile_with_cache"):
        def compile_with_cache(source, options=()):
            return cupy.RawModule(code=source, options=options)

        cupy.cuda.compile_with_cache = compile_with_cache

    source = root / "src"
    if not source.is_dir():
        raise ConfigurationError(
            f"COPILOT_GIMM_ROOT must contain src/: {source}"
        )
    source_text = str(source)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)

    models = importlib.import_module("models")
    utils = importlib.import_module("utils.utils")
    config_utils = importlib.import_module("utils.config")
    for module, label in (
        (models, "models"),
        (utils, "utils"),
        (config_utils, "utils.config"),
    ):
        module_file = Path(getattr(module, "__file__", "")).resolve()
        if source not in module_file.parents:
            raise ConfigurationError(
                f"Python module collision for {label!r}: imported {module_file}, "
                f"expected a module under {source}"
            )
    return (
        models.create_model,
        utils.InputPadder,
        config_utils.load_config,
        config_utils.augment_defaults,
    )


def _configure_upstream_asset_paths(root: Path, config) -> None:
    """Resolve GIMM's flow-estimator checkpoints without changing process cwd."""
    model_type = str(config.arch.type).lower()
    checkpoints = root / "pretrained_ckpt"
    if model_type == "gimmvfi_r":
        raft_path = checkpoints / "raft-things.pth"
        _require_file(raft_path, "GIMM RAFT checkpoint")
        raft = importlib.import_module("models.generalizable_INR.raft")
        gimmvfi_r = importlib.import_module(
            "models.generalizable_INR.gimmvfi_r"
        )
        gimmvfi_r.initialize_RAFT = partial(
            raft.initialize_RAFT,
            model_path=str(raft_path),
        )
    elif model_type == "gimmvfi_f":
        flowformer_path = checkpoints / "flowformer_sintel.pth"
        _require_file(flowformer_path, "GIMM FlowFormer checkpoint")
        submission = importlib.import_module(
            "models.generalizable_INR.flowformer.configs.submission"
        )
        submission._CN.model = str(flowformer_path)


def build_gimm_engine(
    settings: GimmSettings | None = None,
) -> tuple[Callable, tuple[str, str, str, str, float]]:
    """Load GIMM-VFI once and return the standard midpoint-engine callable."""
    settings = settings or GimmSettings.from_env()
    _require_file(settings.config_path, "COPILOT_GIMM_CONFIG")
    _require_file(settings.checkpoint_path, "COPILOT_GIMM_CHECKPOINT")

    import torch
    try:
        device = torch.device(settings.device)
    except (RuntimeError, ValueError) as exc:
        raise ConfigurationError(
            f"COPILOT_GIMM_DEVICE is invalid: {settings.device!r}"
        ) from exc
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            f"COPILOT_GIMM_DEVICE={settings.device!r} requires CUDA, "
            "but torch.cuda.is_available() is false"
        )

    create_model, input_padder, load_config, augment_defaults = (
        _official_modules(settings.root)
    )
    # GIMM's YAML files intentionally omit dataclass defaults.  Use the
    # upstream config pipeline rather than passing the raw YAML to create_model.
    config = augment_defaults(load_config(settings.config_path))
    _configure_upstream_asset_paths(settings.root, config)
    model, _ = create_model(config.arch)
    checkpoint = torch.load(
        settings.checkpoint_path,
        map_location="cpu",
        weights_only=False,
    )
    state_dict = (
        checkpoint["state_dict"]
        if isinstance(checkpoint, dict) and "state_dict" in checkpoint
        else checkpoint
    )
    model.load_state_dict(state_dict, strict=True)
    model = model.to(device)
    model.eval()
    inference_lock = threading.Lock()

    def gimm_engine(a, b):
        """uint8 RGB HxWx3 arrays -> ``[a, midpoint, b]``."""
        a_array = np.asarray(a, dtype=np.uint8)
        b_array = np.asarray(b, dtype=np.uint8)
        if a_array.shape != b_array.shape:
            raise ValueError(
                f"GIMM input shapes must match: {a_array.shape} != {b_array.shape}"
            )
        if a_array.ndim != 3 or a_array.shape[2] != 3:
            raise ValueError(
                f"GIMM expects RGB HxWx3 inputs; got {a_array.shape}"
            )

        def prep(frame):
            tensor = torch.from_numpy(frame.copy()).permute(2, 0, 1)
            return (tensor.to(device=device, dtype=torch.float32) / 255.0).unsqueeze(0)

        with inference_lock, torch.inference_mode():
            frame0, frame1 = prep(a_array), prep(b_array)
            padder = input_padder(frame0.shape, 32)
            frame0, frame1 = padder.pad(frame0, frame1)
            inputs = torch.cat(
                (frame0.unsqueeze(2), frame1.unsqueeze(2)), dim=2
            )
            batch_size = inputs.shape[0]
            spatial_shape = inputs.shape[-2:]
            coords = [(
                model.sample_coord_input(
                    batch_size,
                    spatial_shape,
                    [0.5],
                    device=inputs.device,
                    upsample_ratio=settings.ds_factor,
                ),
                None,
            )]
            timesteps = [
                torch.full(
                    (batch_size,),
                    0.5,
                    device=inputs.device,
                    dtype=torch.float32,
                )
            ]
            outputs = model(
                inputs,
                coords,
                t=timesteps,
                ds_factor=settings.ds_factor,
            )
            midpoint = padder.unpad(outputs["imgt_pred"][0])
            midpoint = (
                midpoint[0]
                .clamp(0.0, 1.0)
                .mul(255.0)
                .round()
                .to(torch.uint8)
                .cpu()
                .permute(1, 2, 0)
                .numpy()
            )
        return [a, midpoint, b]

    signature = (
        str(settings.root),
        str(settings.config_path),
        str(settings.checkpoint_path),
        settings.device,
        settings.ds_factor,
    )
    return gimm_engine, signature
