from __future__ import annotations

import base64
import hashlib
import re
import threading
import time
from collections import OrderedDict
from typing import Any


_DATA_URL_RE = re.compile(r"^data:(?P<mime>image/[^;,]+)(?:;[^,]*)?;base64,(?P<data>.*)$", re.IGNORECASE | re.DOTALL)
_REF_PREFIX = "simpai-sketch-cache:"
_MAX_ENTRY_BYTES = 32 * 1024 * 1024
_MAX_TOTAL_BYTES = 192 * 1024 * 1024
_MAX_ENTRIES = 96

_lock = threading.RLock()
_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
_total_bytes = 0


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    if not isinstance(data_url, str):
        raise ValueError("Sketch cache payload must be a data URL string.")
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        raise ValueError("Sketch cache payload must be an image data URL.")
    mime = (match.group("mime") or "image/png").lower()
    raw = base64.b64decode(match.group("data") or "", validate=False)
    if not raw:
        raise ValueError("Sketch cache payload is empty.")
    if len(raw) > _MAX_ENTRY_BYTES:
        raise ValueError("Sketch cache payload is too large.")
    return mime, raw


def _prune_locked() -> None:
    global _total_bytes
    while len(_cache) > _MAX_ENTRIES or _total_bytes > _MAX_TOTAL_BYTES:
        _, entry = _cache.popitem(last=False)
        _total_bytes -= int(entry.get("bytes") or 0)
    if _total_bytes < 0:
        _total_bytes = 0


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_REF_PREFIX)


def store_data_url(data_url: str, *, role: str = "image") -> dict[str, Any]:
    global _total_bytes
    mime, raw = _decode_data_url(data_url)
    digest = hashlib.sha256(raw).hexdigest()
    ref = f"{_REF_PREFIX}{digest}"
    normalized = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    now = time.time()
    with _lock:
        old = _cache.pop(ref, None)
        if old is not None:
            _total_bytes -= int(old.get("bytes") or 0)
        entry = {
            "data_url": normalized,
            "mime": mime,
            "bytes": len(raw),
            "sha256": digest,
            "role": role,
            "updated_at": now,
        }
        _cache[ref] = entry
        _total_bytes += len(raw)
        _prune_locked()
    return {
        "ref": ref,
        "sha256": digest,
        "bytes": len(raw),
        "mime": mime,
    }


def resolve_data_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower().startswith("data:image/"):
        return text
    if not text.startswith(_REF_PREFIX):
        return None
    with _lock:
        entry = _cache.get(text)
        if entry is None:
            return None
        _cache.move_to_end(text)
        entry["updated_at"] = time.time()
        return str(entry.get("data_url") or "")


def resolve_payload_source(payload: dict[str, Any], role: str) -> str | None:
    direct = resolve_data_url(payload.get(role))
    if direct:
        return direct
    return resolve_data_url(payload.get(f"{role}_ref"))


def store_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Sketch cache payload must be an object.")
    result: dict[str, Any] = {"ok": True}
    for role in ("image", "mask"):
        source = payload.get(role)
        if isinstance(source, str) and source.strip():
            stored = store_data_url(source, role=role)
            result[f"{role}_ref"] = stored["ref"]
            result[f"{role}_sha256"] = stored["sha256"]
            result[f"{role}_bytes"] = stored["bytes"]
            result[f"{role}_mime"] = stored["mime"]
        elif is_ref(payload.get(f"{role}_ref")):
            result[f"{role}_ref"] = payload.get(f"{role}_ref")
    return result


def clear_cache_for_tests() -> None:
    global _total_bytes
    with _lock:
        _cache.clear()
        _total_bytes = 0
