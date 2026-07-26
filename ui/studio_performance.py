from __future__ import annotations

import json
import logging
import math
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool


logger = logging.getLogger(__name__)

ENV_NAME = "SIMPAI_STUDIO_PERF_LOG"
LOG_DIR_ENV_NAME = "SIMPAI_STUDIO_PERF_LOG_DIR"
SCHEMA_VERSION = 1
ENDPOINT_PATH = "/simpai/studio-performance"
MAX_REQUEST_BYTES = 256 * 1024
MAX_RECORDS_PER_BATCH = 100
MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_STRING_LENGTH = 2048
_TRUE_ENV_VALUES = {"1", "true", "yes", "on", "debug"}
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
_runtime_lock = threading.Lock()
_runtime: "StudioPerformanceRuntime | None" = None


class StudioPerformancePayloadError(ValueError):
    pass


class StudioPerformanceLogFullError(RuntimeError):
    pass


def studio_performance_enabled() -> bool:
    return str(os.environ.get(ENV_NAME, "")).strip().lower() in _TRUE_ENV_VALUES


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _default_log_dir() -> Path:
    configured = str(os.environ.get(LOG_DIR_ENV_NAME, "")).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "logs"


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return value


def _sanitize_json(value: Any, depth: int = 0) -> Any:
    if depth >= 7:
        return "[max-depth]"
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _safe_number(value)
    if isinstance(value, str):
        return value[:MAX_STRING_LENGTH]
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item, depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        result = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 100:
                result["_truncated"] = True
                break
            safe_key = str(key)[:128]
            result[safe_key] = _sanitize_json(item, depth + 1)
        return result
    return str(type(value).__name__)


class StudioPerformanceRuntime:
    def __init__(self, log_dir: Path | None = None) -> None:
        started_at = datetime.now().astimezone()
        timestamp = started_at.strftime("%Y%m%d-%H%M%S")
        self.log_dir = Path(log_dir) if log_dir is not None else _default_log_dir()
        self.log_path = self.log_dir / f"studio-ui-performance-{timestamp}-{os.getpid()}.jsonl"
        self.token = secrets.token_urlsafe(24)
        self._write_lock = threading.Lock()
        self._started = False

    def frontend_config(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "schema": SCHEMA_VERSION,
            "endpointPath": ENDPOINT_PATH,
            "token": self.token,
        }

    def start(self) -> None:
        with self._write_lock:
            if self._started:
                return
            self.log_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "schema": SCHEMA_VERSION,
                "received_at": _utc_now(),
                "event": "server.start",
                "data": {
                    "pid": os.getpid(),
                    "environment_switch": ENV_NAME,
                },
            }
            self._append_lines_locked([record])
            self._started = True
        logger.info(
            "Studio performance recording enabled / Studio 性能记录已开启: %s",
            self.log_path,
        )

    def _append_lines_locked(self, records: list[dict[str, Any]]) -> None:
        encoded = [
            (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            for record in records
        ]
        pending_size = sum(len(line) for line in encoded)
        current_size = self.log_path.stat().st_size if self.log_path.exists() else 0
        if current_size + pending_size > MAX_LOG_BYTES:
            raise StudioPerformanceLogFullError("Studio performance log reached its 64 MiB limit")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("ab") as stream:
            for line in encoded:
                stream.write(line)
            stream.flush()

    def append_payload(self, payload: Any) -> int:
        if not isinstance(payload, dict):
            raise StudioPerformancePayloadError("Payload must be an object")
        token = str(payload.get("token") or "")
        if not token or not secrets.compare_digest(token, self.token):
            raise PermissionError("Invalid performance logging token")
        session_id = str(payload.get("session_id") or "")
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise StudioPerformancePayloadError("Invalid session_id")
        records = payload.get("records")
        if not isinstance(records, list) or not records:
            raise StudioPerformancePayloadError("records must be a non-empty list")
        if len(records) > MAX_RECORDS_PER_BATCH:
            raise StudioPerformancePayloadError("Too many records in one batch")

        received_at = _utc_now()
        envelopes = []
        for item in records:
            if not isinstance(item, dict):
                raise StudioPerformancePayloadError("Each record must be an object")
            event = str(item.get("event") or "")[:128]
            if not event:
                raise StudioPerformancePayloadError("Each record requires an event")
            sequence = item.get("seq")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                raise StudioPerformancePayloadError("Each record requires a non-negative integer seq")
            envelopes.append(
                {
                    "schema": SCHEMA_VERSION,
                    "received_at": received_at,
                    "session_id": session_id,
                    "seq": sequence,
                    "event": event,
                    "client_time": str(item.get("client_time") or "")[:64],
                    "page_time_ms": _safe_number(item.get("page_time_ms")),
                    "data": _sanitize_json(item.get("data") if isinstance(item.get("data"), dict) else {}),
                }
            )

        with self._write_lock:
            self._append_lines_locked(envelopes)
        return len(envelopes)


def _get_runtime() -> StudioPerformanceRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = StudioPerformanceRuntime()
        return _runtime


def studio_performance_frontend_config() -> dict[str, Any] | None:
    if not studio_performance_enabled():
        return None
    return _get_runtime().frontend_config()


async def _read_request_json(request: Request) -> Any:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            parsed_content_length = int(content_length)
        except ValueError as exc:
            raise StudioPerformancePayloadError("Invalid Content-Length") from exc
        if parsed_content_length > MAX_REQUEST_BYTES:
            raise StudioPerformancePayloadError("Request is too large")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST_BYTES:
            raise StudioPerformancePayloadError("Request is too large")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StudioPerformancePayloadError("Request body must be UTF-8 JSON") from exc


def install_studio_performance_logging(app: Any) -> bool:
    if not studio_performance_enabled():
        return False
    if getattr(app.state, "simpai_studio_performance_installed", False):
        return True

    runtime = _get_runtime()
    runtime.start()

    async def receive_studio_performance(request: Request):
        try:
            payload = await _read_request_json(request)
            accepted = await run_in_threadpool(runtime.append_payload, payload)
            return JSONResponse({"ok": True, "accepted": accepted})
        except PermissionError:
            return JSONResponse({"ok": False, "error": "Forbidden"}, status_code=403)
        except StudioPerformancePayloadError as exc:
            status_code = 413 if "too large" in str(exc).lower() else 400
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=status_code)
        except StudioPerformanceLogFullError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=507)
        except Exception:
            logger.exception("Studio performance record write failed")
            return JSONResponse({"ok": False, "error": "Performance record write failed"}, status_code=500)

    app.add_api_route(
        ENDPOINT_PATH,
        receive_studio_performance,
        methods=["POST"],
        include_in_schema=False,
    )
    app.state.simpai_studio_performance_installed = True
    return True


def _reset_studio_performance_runtime_for_tests() -> None:
    global _runtime
    with _runtime_lock:
        _runtime = None
