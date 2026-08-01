"""Atomic filesystem manifest store and event hub for resumable sessions."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import threading
import time
import queue
from types import SimpleNamespace
from pathlib import Path

from fastapi import HTTPException

from service.active_workspace.models import ActiveWorkspaceManifest, AssetRecord, JournalEvent
from service.core.config import ActiveWorkspaceSettings


class ActiveWorkspaceService:
    def __init__(self, settings: ActiveWorkspaceSettings | None = None):
        self.settings = settings or ActiveWorkspaceSettings.from_env()
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[object]] = {}

    @staticmethod
    def owner_hash(owner_sub: str) -> str:
        return hashlib.sha256(owner_sub.encode("utf-8")).hexdigest()

    def _directory(self, owner_sub: str) -> Path:
        return self.settings.root / self.owner_hash(owner_sub) / "active"

    def _manifest_path(self, owner_sub: str) -> Path:
        return self._directory(owner_sub) / "manifest.json"

    def _read(self, owner_sub: str) -> ActiveWorkspaceManifest | None:
        path = self._manifest_path(owner_sub)
        if not path.is_file():
            return None
        try:
            return ActiveWorkspaceManifest.model_validate_json(path.read_text("utf-8"))
        except Exception:
            return None

    def _write(self, owner_sub: str, manifest: ActiveWorkspaceManifest) -> None:
        directory = self._directory(owner_sub)
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / "manifest.json.tmp"
        tmp.write_text(manifest.model_dump_json(), encoding="utf-8")
        os.replace(tmp, directory / "manifest.json")

    def cleanup_owner(self, owner_sub: str) -> None:
        manifest = self._read(owner_sub)
        if manifest and manifest.expires_at < int(time.time()) and manifest.state != "generating":
            shutil.rmtree(self._directory(owner_sub), ignore_errors=True)

    def get(self, owner_sub: str) -> ActiveWorkspaceManifest | None:
        with self._lock:
            self.cleanup_owner(owner_sub)
            return self._read(owner_sub)

    def create_or_get(self, owner_sub: str, *, history_pid: str | None = None,
                      initial_snapshot: dict | None = None) -> ActiveWorkspaceManifest:
        with self._lock:
            existing = self.get(owner_sub)
            if existing and existing.state not in {"published", "failed"}:
                return existing
            self._ensure_capacity()
            now = int(time.time())
            manifest = ActiveWorkspaceManifest(
                workspace_id="aw_" + secrets.token_urlsafe(18),
                owner_hash=self.owner_hash(owner_sub),
                created_at=now, updated_at=now, expires_at=now + self.settings.ttl_seconds,
                reservation_bytes=self.settings.workspace_bytes, history_pid=history_pid,
                # Input metadata must be recoverable before the worker has a
                # result. Without it, a valid server-side recovery can replay
                # pair events but cannot recreate the upload acknowledgement.
                snapshot=dict(initial_snapshot or {}),
            )
            directory = self._directory(owner_sub)
            shutil.rmtree(directory, ignore_errors=True)
            (directory / "inputs").mkdir(parents=True, exist_ok=True)
            (directory / "generated").mkdir(parents=True, exist_ok=True)
            self._write(owner_sub, manifest)
            return manifest

    def append_event(self, owner_sub: str, name: str, data: dict) -> JournalEvent:
        with self._lock:
            manifest = self.get(owner_sub)
            if manifest is None:
                raise KeyError("active workspace not found")
            manifest.event_sequence += 1
            manifest.revision += 1
            manifest.updated_at = int(time.time())
            manifest.expires_at = manifest.updated_at + self.settings.ttl_seconds
            event = JournalEvent(sequence=manifest.event_sequence, name=name, data=data)
            manifest.events.append(event)
            self._write(owner_sub, manifest)
            for subscriber in tuple(self._subscribers.get(manifest.workspace_id, [])):
                try:
                    subscriber.put_nowait(event)
                except queue.Full:
                    # Slow subscribers recover from the authoritative journal.
                    pass
            return event

    def subscribe(self, owner_sub: str, workspace_id: str, after: int):
        """Atomically capture a replay and register a future-event subscriber."""
        with self._lock:
            manifest = self.get(owner_sub)
            if manifest is None or manifest.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Active workspace not found")
            replay = [event for event in manifest.events if event.sequence > after]
            subscriber: queue.Queue = queue.Queue(maxsize=256)
            self._subscribers.setdefault(workspace_id, []).append(subscriber)
            return replay, subscriber

    def unsubscribe(self, workspace_id: str, subscriber) -> None:
        with self._lock:
            subscribers = self._subscribers.get(workspace_id, [])
            if subscriber in subscribers:
                subscribers.remove(subscriber)
            if not subscribers:
                self._subscribers.pop(workspace_id, None)

    def set_state(self, owner_sub: str, state: str, *, snapshot: dict | None = None, published_pid: str | None = None) -> ActiveWorkspaceManifest:
        with self._lock:
            manifest = self.get(owner_sub)
            if manifest is None:
                raise KeyError("active workspace not found")
            manifest.state = state
            manifest.updated_at = int(time.time())
            manifest.expires_at = manifest.updated_at + self.settings.ttl_seconds
            manifest.revision += 1
            if snapshot is not None:
                manifest.snapshot = snapshot
            if published_pid is not None:
                manifest.published_pid = published_pid
            if state == "published":
                # Durable artifacts and workspace state now belong to the
                # S3/DynamoDB history layer. Keep only an owner-scoped receipt;
                # the caller appends one final publish event afterwards so an
                # already-connected subscriber can finish cleanly.
                for folder in ("inputs", "generated"):
                    shutil.rmtree(self._directory(owner_sub) / folder, ignore_errors=True)
                manifest.assets = []
                manifest.snapshot = {}
                manifest.events = []
                manifest.history_pid = None
                manifest.reservation_bytes = 0
            self._write(owner_sub, manifest)
            return manifest

    def stage_generated(self, owner_sub: str, session_dir: str) -> list[AssetRecord]:
        """Copy rendered session assets into the bounded recovery directory."""
        with self._lock:
            manifest = self.get(owner_sub)
            if manifest is None:
                raise KeyError("active workspace not found")
            target = self._directory(owner_sub) / "generated"
            records: list[AssetRecord] = []
            for source in Path(session_dir).iterdir():
                if not source.is_file() or source.suffix.lower() not in {".png", ".mp4", ".md"}:
                    continue
                destination = target / source.name
                shutil.copy2(source, destination)
                digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                records.append(AssetRecord(name=source.name, kind="generated", size=destination.stat().st_size, sha256=digest))
            manifest.assets = records
            manifest.revision += 1
            manifest.updated_at = int(time.time())
            self._write(owner_sub, manifest)
            return records

    def stage_input_arrays(self, owner_sub: str, arrays) -> None:
        """Persist normalized source keys so review survives browser file loss."""
        from PIL import Image
        with self._lock:
            manifest = self.get(owner_sub)
            if manifest is None:
                raise KeyError("active workspace not found")
            target = self._directory(owner_sub) / "inputs"
            inputs: list[AssetRecord] = []
            for index, array in enumerate(arrays):
                name = f"input-{index:03d}.png"
                path = target / name
                Image.fromarray(array).save(path, format="PNG")
                inputs.append(AssetRecord(name=name, kind="input-key", size=path.stat().st_size,
                                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            manifest.assets = inputs + [asset for asset in manifest.assets if asset.kind != "input-key"]
            manifest.revision += 1
            manifest.updated_at = int(time.time())
            self._write(owner_sub, manifest)

    def stage_input_video(self, owner_sub: str, content: bytes) -> None:
        """Keep the original submitted clip for exact active-workspace recovery."""
        with self._lock:
            manifest = self.get(owner_sub)
            if manifest is None:
                raise KeyError("active workspace not found")
            name = "input-video.mp4"
            path = self._directory(owner_sub) / "inputs" / name
            path.write_bytes(content)
            video = AssetRecord(
                name=name,
                kind="input-video",
                size=path.stat().st_size,
                sha256=hashlib.sha256(content).hexdigest(),
            )
            manifest.assets = [
                video if asset.kind == "input-video" else asset
                for asset in manifest.assets
                if asset.kind != "input-video" or asset.name == name
            ]
            if not any(asset.kind == "input-video" for asset in manifest.assets):
                manifest.assets.append(video)
            manifest.revision += 1
            manifest.updated_at = int(time.time())
            self._write(owner_sub, manifest)

    def discard(self, owner_sub: str, workspace_id: str) -> None:
        with self._lock:
            manifest = self.get(owner_sub)
            if manifest is None or manifest.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Active workspace not found")
            self._subscribers.pop(workspace_id, None)
            shutil.rmtree(self._directory(owner_sub), ignore_errors=True)

    def artifact(self, owner_sub: str, workspace_id: str, name: str) -> Path:
        manifest = self.get(owner_sub)
        if manifest is None or manifest.workspace_id != workspace_id or Path(name).name != name:
            raise HTTPException(status_code=404, detail="Active workspace artifact not found")
        allowed = {asset.name for asset in manifest.assets}
        if name not in allowed:
            raise HTTPException(status_code=404, detail="Active workspace artifact not found")
        for folder in ("inputs", "generated"):
            path = self._directory(owner_sub) / folder / name
            if path.is_file():
                return path
        raise HTTPException(status_code=404, detail="Active workspace artifact not found")

    def _ensure_capacity(self) -> None:
        root = self.settings.root
        root.mkdir(parents=True, exist_ok=True)
        reserved = sum(
            manifest.reservation_bytes
            for _, manifest in self.list_manifests()
            if manifest.state != "published" and manifest.expires_at >= int(time.time())
        )
        if reserved + self.settings.workspace_bytes > self.settings.global_bytes:
            raise HTTPException(status_code=507, detail="Temporary workspace capacity is full. Retry shortly.")
        usage = shutil.disk_usage(root)
        if usage.free - self.settings.free_reserve_bytes < self.settings.workspace_bytes:
            raise HTTPException(status_code=507, detail="Temporary workspace capacity is full. Retry shortly.")

    def list_manifests(self) -> list[tuple[Path, ActiveWorkspaceManifest]]:
        manifests: list[tuple[Path, ActiveWorkspaceManifest]] = []
        if not self.settings.root.is_dir():
            return manifests
        for path in self.settings.root.glob("*/active/manifest.json"):
            try:
                manifests.append((path.parent, ActiveWorkspaceManifest.model_validate_json(path.read_text("utf-8"))))
            except Exception:
                continue
        return manifests

    def purge(self, *, expired_only: bool, include_running: bool = False) -> list[str]:
        now = int(time.time())
        removed: list[str] = []
        with self._lock:
            for directory, manifest in self.list_manifests():
                if expired_only and manifest.expires_at >= now:
                    continue
                if manifest.state == "generating" and not include_running:
                    continue
                shutil.rmtree(directory, ignore_errors=True)
                removed.append(manifest.workspace_id)
        return removed

    def retry_publish(self, owner_sub: str, workspace_id: str) -> dict:
        """Retry only durable publication from the staged local output.

        The GPU pipeline has already completed. Rebuild the publisher's small
        outcome view from the validated manifest instead of re-running it.
        """
        with self._lock:
            manifest = self.get(owner_sub)
            if manifest is None or manifest.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Active workspace not found")
            if manifest.state == "published" and manifest.published_pid:
                return {"published": True, "pid": manifest.published_pid, "already_published": True}
            if manifest.state not in {"ready", "publish_pending"}:
                raise HTTPException(status_code=409, detail="Workspace is not ready to publish")
            snapshot = manifest.snapshot
            raw_result = snapshot.get("result")
            if not isinstance(raw_result, dict):
                raise HTTPException(status_code=409, detail="Workspace has no final result to publish")
            pairs = []
            for value in snapshot.get("pairs", []):
                if not isinstance(value, dict):
                    continue
                pairs.append(SimpleNamespace(
                    index=value.get("index", len(pairs)), action=value.get("action", "filled"),
                    keys_requested=value.get("keys_requested", 0), qa=None,
                ))
            result = SimpleNamespace(
                pairs=pairs,
                n_autopass=raw_result.get("n_autopass", 0),
                n_corrected=raw_result.get("n_corrected", 0),
                keys_requested_total=raw_result.get("keys_requested_total", 0),
                flagged=raw_result.get("flagged", []), abstained=raw_result.get("abstained", []),
            )
            outcome = SimpleNamespace(
                result=result,
                artifact_urls=raw_result.get("artifacts", {}),
                explanations=raw_result.get("explanations", {}),
                pair_mids=raw_result.get("pair_mids", {}),
                key_urls=raw_result.get("key_urls", {}),
                sampling=raw_result.get("sampling", {}),
                csq=raw_result.get("csq"),
                qa_degraded=raw_result.get("qa_degraded", False),
            )
            from service.infrastructure.publisher import publish_session
            published = publish_session(
                0, str(self._directory(owner_sub) / "generated"), outcome,
                owner_sub=owner_sub, pid=manifest.history_pid,
                workspace_input=snapshot.get("upload") or None,
            )
            if published.get("published"):
                self.set_state(owner_sub, "published", published_pid=published.get("pid"))
                self.append_event(owner_sub, "publish", {"published": True, "pid": published.get("pid")})
            else:
                self.set_state(owner_sub, "publish_pending")
                self.append_event(owner_sub, "publish", {"published": False, "error": published.get("error")})
            return published
