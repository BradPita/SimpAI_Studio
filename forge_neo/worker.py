from __future__ import annotations

import gc
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from forge_neo.i18n import t
from forge_neo.runtime import ForgeNeoExtrasRequest, ForgeNeoRequest, ForgeNeoResult, generate, run_extras


def _unload_parent_model_weights() -> dict[str, object]:
    result: dict[str, object] = {
        "attempted": False,
        "unload_model_weights_called": False,
        "memory_management_called": False,
        "error": "",
    }
    sd_models = (
        sys.modules.get("modules.sd_models")
        or sys.modules.get("forge_neo.runtime_backend.modules.sd_models")
        or sys.modules.get("forge_neo.webui.modules.sd_models")
    )
    unload_model_weights = getattr(sd_models, "unload_model_weights", None) if sd_models is not None else None
    try:
        if callable(unload_model_weights):
            result["attempted"] = True
            unload_model_weights()
            result["unload_model_weights_called"] = True
            return result

        memory_management = (
            sys.modules.get("backend.memory_management")
            or sys.modules.get("forge_neo.runtime_backend.backend.memory_management")
            or sys.modules.get("forge_neo.webui.backend.memory_management")
        )
        unload_all_models = getattr(memory_management, "unload_all_models", None) if memory_management is not None else None
        if callable(unload_all_models):
            result["attempted"] = True
            unload_all_models()
            result["memory_management_called"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _unload_source_backend_model_weights() -> dict[str, object]:
    try:
        from forge_neo.runtime_backend.source_runtime import unload_source_backend_models

        return unload_source_backend_models()
    except Exception as exc:
        return {
            "ok": False,
            "status": "unavailable",
            "model_unload_requested": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


@dataclass
class ForgeNeoWorker:
    events: list[dict[str, object]] = field(default_factory=list)
    _stop_requested: bool = False
    _skip_requested: bool = False
    status: str = "idle"
    progress: float = 0.0
    message: str = ""
    message_en: str = ""
    message_cn: str = ""
    sampling_step: int = 0
    sampling_steps: int = 0
    eta_relative: float = 0.0
    current_image: object | None = None
    id_live_preview: int = 0
    job_timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S"))
    _started_at: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def stop(self) -> None:
        with self._lock:
            self._stop_requested = True

    def skip(self) -> None:
        with self._lock:
            self._skip_requested = True

    def reset(self) -> None:
        with self._lock:
            self._stop_requested = False
            self._skip_requested = False
            self.events.clear()
            self.status = "running"
            self.progress = 0.0
            self.message = ""
            self.message_en = ""
            self.message_cn = ""
            self.sampling_step = 0
            self.sampling_steps = 0
            self.eta_relative = 0.0
            self.current_image = None
            self.id_live_preview = 0
            self.job_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            self._started_at = time.monotonic()

    def _estimated_eta(self, event: dict[str, object], progress: float) -> float:
        try:
            incoming_eta = float(event.get("eta_relative", 0.0) or 0.0)
        except (TypeError, ValueError):
            incoming_eta = 0.0
        if incoming_eta > 0:
            return incoming_eta
        if event.get("event") == "finish" or progress >= 1.0:
            return 0.0
        if progress <= 0.0:
            return self.eta_relative
        elapsed = max(0.0, time.monotonic() - self._started_at)
        if elapsed <= 0.0:
            return self.eta_relative
        return max(0.0, elapsed * (1.0 - progress) / progress)

    def should_stop(self) -> bool:
        with self._lock:
            return self._stop_requested

    def should_skip(self) -> bool:
        with self._lock:
            return self._skip_requested

    def control_status(self) -> str | None:
        with self._lock:
            if self._stop_requested:
                return "stopped"
            if self._skip_requested:
                return "skipped"
        return None

    def _progress(self, event: dict[str, object]) -> None:
        entry = dict(event)
        current_image = entry.pop("current_image", None)
        with self._lock:
            self.events.append(entry)
            incoming_progress = float(entry.get("progress", self.progress) or 0.0)
            incoming_sampling_step = int(entry.get("sampling_step", self.sampling_step) or 0)
            incoming_sampling_steps = int(entry.get("sampling_steps", self.sampling_steps) or 0)
            has_sampling_update = incoming_sampling_steps > 0 and (incoming_sampling_step > 0 or current_image is not None)
            if entry.get("event") == "finish":
                self.progress = incoming_progress
            elif has_sampling_update:
                self.progress = incoming_progress
            else:
                self.progress = max(self.progress, incoming_progress)
            self.message_en = str(entry.get("message_en", self.message_en) or "")
            self.message_cn = str(entry.get("message_cn", self.message_cn) or "")
            self.message = str(entry.get("message", self.message_en or self.message_cn or self.message) or "")
            self.sampling_step = incoming_sampling_step
            self.sampling_steps = incoming_sampling_steps
            self.eta_relative = self._estimated_eta(entry, self.progress)
            if current_image is not None:
                self.current_image = current_image
                self.id_live_preview = int(entry.get("id_live_preview", self.id_live_preview + 1) or self.id_live_preview + 1)
            if entry.get("event") == "finish":
                self.status = self.message if self.message in {"stopped", "skipped", "backend_pending", "backend_unavailable", "error"} else "finished"

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "status": self.status,
                "progress": self.progress,
                "message": self.message,
                "message_en": self.message_en,
                "message_cn": self.message_cn,
                "stop_requested": self._stop_requested,
                "skip_requested": self._skip_requested,
                "events": list(self.events),
                "sampling_step": self.sampling_step,
                "sampling_steps": self.sampling_steps,
                "eta_relative": self.eta_relative,
                "current_image": self.current_image,
                "id_live_preview": self.id_live_preview,
                "job_timestamp": self.job_timestamp,
            }

    def unload_runtime_state(self) -> dict[str, object]:
        with self._lock:
            previous_status = self.status
            events_cleared = len(self.events)
            self._stop_requested = False
            self._skip_requested = False
            self.events.clear()
            self.status = "idle"
            self.progress = 0.0
            self.message = ""
            self.message_en = ""
            self.message_cn = ""
            self.sampling_step = 0
            self.sampling_steps = 0
            self.eta_relative = 0.0
            self.current_image = None
            self.id_live_preview = 0
            self.job_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        result: dict[str, object] = {
            "previous_status": previous_status,
            "events_cleared": events_cleared,
            "parent_model_unload": _unload_parent_model_weights(),
            "source_backend": _unload_source_backend_model_weights(),
            "gc_collected": gc.collect(),
            "torch_available": False,
            "cuda_available": False,
            "cuda_empty_cache_called": False,
            "cuda_ipc_collect_called": False,
            "torch_error": "",
        }
        try:
            import torch

            result["torch_available"] = True
            cuda = getattr(torch, "cuda", None)
            if cuda is not None:
                try:
                    result["cuda_available"] = bool(cuda.is_available())
                except Exception as exc:
                    result["torch_error"] = f"{type(exc).__name__}: {exc}"
                if hasattr(cuda, "empty_cache"):
                    cuda.empty_cache()
                    result["cuda_empty_cache_called"] = True
                if result["cuda_available"] and hasattr(cuda, "ipc_collect"):
                    cuda.ipc_collect()
                    result["cuda_ipc_collect_called"] = True
        except Exception as exc:
            result["torch_error"] = f"{type(exc).__name__}: {exc}"
        return result

    def _finish(self, result: ForgeNeoResult) -> ForgeNeoResult:
        with self._lock:
            self.status = result.status
            self.progress = 1.0 if result.status in {"finished", "backend_pending", "backend_unavailable"} else self.progress
            messages = {
                "finished": ("Finished.", "已完成。"),
                "backend_pending": ("Backend pending.", "后端待迁移。"),
                "backend_unavailable": ("Backend unavailable.", "后端不可用。"),
                "stopped": ("Stopped.", "已停止。"),
                "skipped": ("Skipped.", "已跳过。"),
                "error": ("Error.", "错误。"),
            }
            message_en, message_cn = messages.get(result.status, (result.status, result.status))
            self.message_en = message_en
            self.message_cn = message_cn
            self.message = message_en
            self.eta_relative = 0.0
            if result.status in {"finished", "backend_pending", "backend_unavailable"}:
                self.sampling_step = 0
                self.sampling_steps = 0
            if result.images:
                self.current_image = result.images[0]
                self.id_live_preview += 1
        return result

    def run(self, request: ForgeNeoRequest, state: Mapping[str, object] | None = None) -> ForgeNeoResult:
        self.reset()
        result = generate(request, progress_callback=self._progress, control_callback=self.control_status)
        return self._finish(result)

    def run_extras(self, request: ForgeNeoExtrasRequest, state: Mapping[str, object] | None = None) -> ForgeNeoResult:
        self.reset()
        result = run_extras(request, progress_callback=self._progress, control_callback=self.control_status)
        return self._finish(result)


worker = ForgeNeoWorker()


def stop_current(state: Mapping[str, object] | None = None) -> str:
    worker.stop()
    return t(state, "Stop requested.", "已请求停止。")


def skip_current(state: Mapping[str, object] | None = None) -> str:
    worker.skip()
    return t(state, "Skip requested.", "已请求跳过。")


def progress_snapshot() -> dict[str, object]:
    return worker.snapshot()


def unload_runtime_state() -> dict[str, object]:
    return worker.unload_runtime_state()
