from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import random
import re
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from gradio.route_utils import API_PREFIX

from forge_neo.styles import load_styles


ROOT = Path(__file__).resolve().parents[1]
STYLE_GRID_EXTENSION = "sd-webui-style-organizer"
STYLE_GRID_SCRIPT_TITLE = "Style Grid"
EXT_DIR = ROOT / "forge_neo" / "webui" / "extensions" / STYLE_GRID_EXTENSION
DATA_DIR = EXT_DIR / "data"
PRESETS_FILE = DATA_DIR / "presets.json"
USAGE_FILE = DATA_DIR / "usage.json"
CATEGORY_ORDER_FILE = DATA_DIR / "category_order.json"
BACKUP_DIR = DATA_DIR / "backups"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
EDITABLE_STYLES_DIR = EXT_DIR / "styles"
EDITABLE_STYLES_FILE = EDITABLE_STYLES_DIR / "styles.csv"
STYLE_GRID_FIELDS = ("name", "prompt", "negative_prompt", "description", "category")
STYLE_GRID_REQUIRED_FILES = (
    "scripts/style_grid.py",
    "javascript/sg_prompt_utils.js",
    "javascript/style_grid.js",
    "style.css",
    "ui/dist/index.html",
)
SG_WILDCARD_RE = re.compile(r"\{sg:([^}]+)\}")
WEIGHTED_TAG_RE = re.compile(r"^\((.+?):\d+\.?\d*\)$")


def style_grid_extension_dir() -> Path:
    return EXT_DIR


def style_grid_available() -> bool:
    return EXT_DIR.is_dir() and all((EXT_DIR / rel).exists() for rel in STYLE_GRID_REQUIRED_FILES)


def prepare_style_grid_runtime_files() -> None:
    if not EXT_DIR.is_dir():
        return
    for path in (DATA_DIR, BACKUP_DIR, THUMBNAILS_DIR, EDITABLE_STYLES_DIR):
        path.mkdir(parents=True, exist_ok=True)
    if not PRESETS_FILE.exists():
        _write_json(PRESETS_FILE, {})
    if not USAGE_FILE.exists():
        _write_json(USAGE_FILE, {})


def _read_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return value if value is not None else default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def load_style_grid_usage() -> dict[str, int]:
    value = _read_json(USAGE_FILE, {})
    if not isinstance(value, dict):
        return {}
    usage: dict[str, int] = {}
    for key, item in value.items():
        try:
            usage[str(key)] = int(item)
        except Exception:
            continue
    return usage


def save_style_grid_usage(value: dict[str, int]) -> None:
    _write_json(USAGE_FILE, value)


def increment_style_grid_usage(names: list[str]) -> None:
    clean = [str(name or "").strip() for name in names if str(name or "").strip()]
    if not clean:
        return
    usage = load_style_grid_usage()
    for name in clean:
        usage[name] = int(usage.get(name, 0) or 0) + 1
    save_style_grid_usage(usage)


def load_style_grid_presets() -> dict[str, Any]:
    value = _read_json(PRESETS_FILE, {})
    return value if isinstance(value, dict) else {}


def save_style_grid_presets(value: dict[str, Any]) -> None:
    _write_json(PRESETS_FILE, value)


def load_style_grid_category_order() -> list[str]:
    value = _read_json(CATEGORY_ORDER_FILE, [])
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def save_style_grid_category_order(value: list[str]) -> None:
    _write_json(CATEGORY_ORDER_FILE, [str(item) for item in value])


def style_grid_category_order_json() -> str:
    order = load_style_grid_category_order()
    if not order:
        order = sorted(style_grid_categories().keys())
    return json.dumps(order, ensure_ascii=False)


def _style_csv_paths() -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        key = os.path.normcase(str(resolved))
        if key in seen or not resolved.is_file():
            return
        seen.add(key)
        paths.append(resolved)

    for folder_name in ("styles", "samples"):
        folder = EXT_DIR / folder_name
        if folder.is_dir():
            for path in sorted(folder.glob("*.csv")):
                add(path)
    try:
        for style in load_styles().values():
            if style.path:
                add(Path(style.path))
    except Exception:
        pass
    return paths


def _parse_style_csv(path: Path) -> list[dict[str, Any]]:
    styles: list[dict[str, Any]] = []
    if not path.is_file():
        return styles
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header_seen = False
            for row in reader:
                if not row or all(str(cell or "").strip() == "" for cell in row):
                    continue
                if not header_seen and str(row[0] or "").strip().lower() == "name":
                    header_seen = True
                    continue
                header_seen = True
                name = str(row[0] if len(row) > 0 else "").strip()
                if not name or name.startswith("#"):
                    continue
                prompt = str(row[1] if len(row) > 1 else "").strip()
                negative = str(row[2] if len(row) > 2 else "").strip()
                description = str(row[3] if len(row) > 3 else "").strip()
                category_explicit = str(row[4] if len(row) > 4 else "").strip()
                source_file = str(path)
                source = path.name
                styles.append(
                    {
                        "name": name,
                        "prompt": prompt,
                        "negative_prompt": negative,
                        "description": description,
                        "category_explicit": category_explicit,
                        "source": source,
                        "_source": source,
                        "source_file": source_file,
                    }
                )
    except Exception:
        return []
    return styles


def style_grid_styles() -> list[dict[str, Any]]:
    styles: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in _style_csv_paths():
        for style in _parse_style_csv(path):
            key = (str(style.get("source_file") or ""), str(style.get("name") or ""))
            if key in seen:
                continue
            seen.add(key)
            styles.append(style)
    return styles


def _category_from_filename(source: str) -> str:
    base = Path(str(source or "")).stem.strip()
    if not base:
        return ""
    return base[:1].upper() + base[1:]


def style_grid_categorize_styles(styles: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    categories: dict[str, list[dict[str, Any]]] = {}
    for style in styles:
        name = str(style.get("name") or "")
        source = str(style.get("source") or "")
        explicit = str(style.get("category_explicit") or "").strip()
        if explicit:
            category = explicit
            display = name.split("_", 1)[1].replace("_", " ") if "_" in name else name
        elif "_" in name:
            before, rest = name.split("_", 1)
            category = before.upper()
            display = rest.replace("_", " ")
        elif "-" in name:
            before, rest = name.split("-", 1)
            category = before
            display = rest.replace("-", " ")
        else:
            category = _category_from_filename(source) or "OTHER"
            display = name.replace("_", " ")
        style["category"] = category
        style["display_name"] = display
        style["has_placeholder"] = "{prompt}" in str(style.get("prompt") or "") or "{prompt}" in str(style.get("negative_prompt") or "")
        categories.setdefault(category, []).append(style)
    for values in categories.values():
        values.sort(key=lambda item: (str(item.get("display_name") or item.get("name") or "")).lower())
    return categories


def style_grid_categories() -> dict[str, list[dict[str, Any]]]:
    return style_grid_categorize_styles(style_grid_styles())


def style_grid_payload() -> dict[str, Any]:
    prepare_style_grid_runtime_files()
    return {
        "categories": style_grid_categories(),
        "usage": load_style_grid_usage(),
        "presets": load_style_grid_presets(),
    }


def style_grid_payload_json() -> str:
    return json.dumps(style_grid_payload(), ensure_ascii=False)


def style_grid_cache_key() -> str:
    parts: list[str] = []
    for path in [*_style_csv_paths(), PRESETS_FILE, USAGE_FILE, CATEGORY_ORDER_FILE]:
        if not path.exists():
            continue
        try:
            stat = path.stat()
            parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            continue
    return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()


def detect_style_grid_conflicts(style_names: list[str]) -> list[dict[str, Any]]:
    styles_map = {style["name"]: style for style in style_grid_styles()}
    tokens: dict[str, dict[str, set[str]]] = {}
    conflicts: list[dict[str, Any]] = []
    for name in style_names:
        style = styles_map.get(str(name or ""))
        if not style:
            continue
        tokens[str(name)] = {"positive": set(), "negative": set()}
        for token in str(style.get("prompt") or "").split(","):
            clean = token.strip().lower()
            if clean and clean != "{prompt}":
                tokens[str(name)]["positive"].add(clean)
        for token in str(style.get("negative_prompt") or "").split(","):
            clean = token.strip().lower()
            if clean and clean != "{prompt}":
                tokens[str(name)]["negative"].add(clean)
    names = list(tokens.keys())
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            overlap = tokens[left]["positive"] & tokens[right]["negative"]
            if overlap:
                sample = sorted(overlap)[:5]
                conflicts.append(
                    {
                        "styles": [left, right],
                        "type": "positive_vs_negative",
                        "tokens": sample,
                        "message": f"'{left}' adds tokens that '{right}' negates: {', '.join(sample[:3])}",
                    }
                )
            reverse = tokens[right]["positive"] & tokens[left]["negative"]
            if reverse:
                sample = sorted(reverse)[:5]
                conflicts.append(
                    {
                        "styles": [right, left],
                        "type": "positive_vs_negative",
                        "tokens": sample,
                        "message": f"'{right}' adds tokens that '{left}' negates: {', '.join(sample[:3])}",
                    }
                )
    return conflicts


def _sanitize_csv_cell(value: object) -> str:
    text = str(value or "")
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _style_target_path(source: object = None) -> Path:
    text = str(source or "").strip()
    if text:
        base = Path(text).name
        if not base.lower().endswith(".csv"):
            base += ".csv"
        for path in _style_csv_paths():
            if path.name == base:
                return path
        return EDITABLE_STYLES_DIR / base
    return EDITABLE_STYLES_FILE


def save_style_grid_style(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        return {"error": "Name required"}
    target = _style_target_path(data.get("source"))
    target.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    if target.is_file():
        try:
            with target.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    if row:
                        rows.append({field: str(row.get(field) or "") for field in STYLE_GRID_FIELDS})
        except Exception:
            rows = []
    replacement = {
        "name": name,
        "prompt": str(data.get("prompt") or ""),
        "negative_prompt": str(data.get("negative_prompt") or ""),
        "description": _sanitize_csv_cell(data.get("description")),
        "category": _sanitize_csv_cell(data.get("category")),
    }
    updated = False
    for index, row in enumerate(rows):
        if str(row.get("name") or "").strip() == name:
            rows[index] = replacement
            updated = True
            break
    if not updated:
        rows.append(replacement)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(STYLE_GRID_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return {"ok": True, "source": target.name}


def delete_style_grid_style(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        return {"error": "Name required"}
    target = _style_target_path(data.get("source"))
    if not target.is_file():
        for style in style_grid_styles():
            if style.get("name") == name:
                target = Path(str(style.get("source_file") or ""))
                break
    if not target.is_file():
        return {"ok": True}
    rows: list[dict[str, str]] = []
    try:
        with target.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if str(row.get("name") or "").strip() != name:
                    rows.append({field: str(row.get(field) or "") for field in STYLE_GRID_FIELDS})
    except Exception:
        return {"error": "Could not read source CSV"}
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(STYLE_GRID_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return {"ok": True}


def backup_style_grid_csv_files() -> bool:
    prepare_style_grid_runtime_files()
    paths = [path for path in _style_csv_paths() if path.is_file()]
    if not paths:
        return True
    target = BACKUP_DIR / f"styles_backup_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=path.name)
    return True


def _thumbnail_hash_input(style_name: str, source_file: str = "") -> str:
    if not source_file:
        return style_name
    try:
        source_path = Path(source_file).resolve()
    except OSError:
        source_path = Path(source_file).absolute()
    for base in (EDITABLE_STYLES_DIR, EXT_DIR / "samples", ROOT / "html" / "forge_neo", ROOT):
        try:
            rel = source_path.relative_to(base.resolve())
            return f"{style_name}::{rel.as_posix()}"
        except Exception:
            continue
    return f"{style_name}::{source_path.name}"


def style_grid_thumbnail_path(style_name: str, source_file: str = "") -> Path:
    digest = hashlib.md5(_thumbnail_hash_input(style_name, source_file).encode("utf-8")).hexdigest()
    return THUMBNAILS_DIR / f"{digest}.webp"


def style_grid_thumbnail_names() -> set[str]:
    if not THUMBNAILS_DIR.is_dir():
        return set()
    hashes = {path.stem for path in THUMBNAILS_DIR.glob("*.webp")}
    result: set[str] = set()
    for style in style_grid_styles():
        name = str(style.get("name") or "")
        digest = hashlib.md5(_thumbnail_hash_input(name, str(style.get("source_file") or "")).encode("utf-8")).hexdigest()
        legacy = hashlib.md5(name.encode("utf-8")).hexdigest()
        if digest in hashes or legacy in hashes:
            result.add(name)
    return result


def _selected_styles_from_json(value: object) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        text = str(value or "").strip()
        if not text or text == "[]":
            return []
        try:
            raw = json.loads(text)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


def style_grid_script_args(silent_styles_json: object = "[]", source_filter: object = "") -> list[str]:
    styles = _selected_styles_from_json(silent_styles_json)
    silent_json = json.dumps(styles, ensure_ascii=False)
    source = str(source_filter or "").strip()
    return [silent_json, source]


def style_grid_alwayson_payload(silent_styles_json: object = "[]", source_filter: object = "") -> dict[str, Any]:
    return {STYLE_GRID_SCRIPT_TITLE: {"args": style_grid_script_args(silent_styles_json, source_filter)}}


def _map_prompt_lines(prompt: str, transform: Any) -> str:
    parts = re.split(r"(\r\n|\r|\n)", str(prompt or ""))
    return "".join(part if index % 2 else transform(part) for index, part in enumerate(parts))


def _dedup_prompt_line(prompt: str) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for part in prompt.split(","):
        item = part.strip()
        if not item:
            continue
        if item.upper() == "BREAK":
            result.append(item)
            continue
        match = WEIGHTED_TAG_RE.match(item)
        key = (match.group(1).strip() if match else item).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return ", ".join(result)


def _dedup_prompt(prompt: str) -> str:
    return _map_prompt_lines(prompt, _dedup_prompt_line)


def _source_filtered_styles(source_filter: str) -> list[dict[str, Any]]:
    styles = style_grid_styles()
    source = str(source_filter or "").strip()
    if not source:
        return styles
    filtered = [
        style
        for style in styles
        if source in {str(style.get("source") or ""), str(style.get("source_file") or "")}
    ]
    return filtered or styles


def _styles_by_category(source_filter: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for category, styles in style_grid_categorize_styles(_source_filtered_styles(source_filter)).items():
        result.setdefault(category.lower(), []).extend(styles)
    return result


def resolve_style_grid_wildcards(prompt: str, source_filter: str = "") -> str:
    categories = _styles_by_category(source_filter)

    def replace_match(match: re.Match[str]) -> str:
        token = match.group(1).strip().lower()
        candidates = categories.get(token)
        if not candidates:
            return match.group(0)
        style = random.choice(candidates)
        return str(style.get("prompt") or match.group(0))

    return SG_WILDCARD_RE.sub(replace_match, str(prompt or ""))


def _append_unique_prompt(prompt: str, additions: list[str]) -> str:
    def append_to_line(line: str) -> str:
        current = [part.strip() for part in line.split(",") if part.strip()]
        seen = {part.lower() for part in current}
        result = list(current)
        for addition in additions:
            for token in str(addition or "").split(","):
                item = token.strip()
                if not item or item.lower() in seen:
                    continue
                seen.add(item.lower())
                result.append(item)
        return ", ".join(result)

    return _map_prompt_lines(prompt, append_to_line)


def _apply_prompt_template(prompt: str, template: str) -> str:
    return _map_prompt_lines(prompt, lambda line: template.replace("{prompt}", line))


def apply_style_grid_to_prompt_pair(
    prompt: str,
    negative_prompt: str,
    silent_styles_json: object = "[]",
    source_filter: object = "",
) -> tuple[str, str, list[str]]:
    source = str(source_filter or "").strip()
    positive = _dedup_prompt(resolve_style_grid_wildcards(prompt, source))
    negative = _dedup_prompt(resolve_style_grid_wildcards(negative_prompt, source))
    names = _selected_styles_from_json(silent_styles_json)
    if not names:
        return positive, negative, names
    styles_map = {str(style.get("name") or ""): style for style in style_grid_styles()}
    positive_add: list[str] = []
    negative_add: list[str] = []
    for name in names:
        style = styles_map.get(name)
        if not style:
            continue
        style_prompt = str(style.get("prompt") or "")
        style_negative = str(style.get("negative_prompt") or "")
        if style_prompt:
            if "{prompt}" in style_prompt:
                positive = _apply_prompt_template(positive, style_prompt)
            else:
                positive_add.append(style_prompt)
        if style_negative:
            if "{prompt}" in style_negative:
                negative = _apply_prompt_template(negative, style_negative)
            else:
                negative_add.append(style_negative)
    if positive_add:
        positive = _append_unique_prompt(positive, positive_add)
    if negative_add:
        negative = _append_unique_prompt(negative, negative_add)
    return positive, negative, names


def _request_style_grid_args(request: Any) -> tuple[str, str]:
    script_args = getattr(request, "script_args", None)
    if not isinstance(script_args, dict):
        return "[]", ""
    alwayson = script_args.get("alwayson_scripts")
    if not isinstance(alwayson, dict):
        return "[]", ""
    style_grid = alwayson.get(STYLE_GRID_SCRIPT_TITLE) or alwayson.get(STYLE_GRID_SCRIPT_TITLE.lower()) or alwayson.get("style grid")
    if not isinstance(style_grid, dict):
        return "[]", ""
    args = style_grid.get("args")
    if not isinstance(args, list):
        return "[]", ""
    return str(args[0] if len(args) > 0 else "[]"), str(args[1] if len(args) > 1 else "")


def request_uses_style_grid(request: Any) -> bool:
    silent_json, source_filter = _request_style_grid_args(request)
    if _selected_styles_from_json(silent_json):
        return True
    if source_filter:
        return True
    for value in (
        getattr(request, "prompt", ""),
        getattr(request, "negative_prompt", ""),
        getattr(request, "hires_prompt", ""),
        getattr(request, "hires_negative_prompt", ""),
    ):
        if SG_WILDCARD_RE.search(str(value or "")):
            return True
    return False


def apply_style_grid_to_request(request: Any) -> Any:
    if not style_grid_available() or not request_uses_style_grid(request):
        return request
    silent_json, source_filter = _request_style_grid_args(request)
    prompt, negative, names = apply_style_grid_to_prompt_pair(
        str(getattr(request, "prompt", "") or ""),
        str(getattr(request, "negative_prompt", "") or ""),
        silent_json,
        source_filter,
    )
    hires_prompt = str(getattr(request, "hires_prompt", "") or "")
    hires_negative = str(getattr(request, "hires_negative_prompt", "") or "")
    if hires_prompt or hires_negative:
        hires_prompt, hires_negative, _ = apply_style_grid_to_prompt_pair(
            hires_prompt,
            hires_negative,
            silent_json,
            source_filter,
        )
    comments = dict(getattr(request, "comments", {}) or {})
    if names:
        comments[STYLE_GRID_SCRIPT_TITLE] = ", ".join(names)
        increment_style_grid_usage(names)
    return replace(
        request,
        prompt=prompt,
        negative_prompt=negative,
        hires_prompt=hires_prompt,
        hires_negative_prompt=hires_negative,
        comments=comments,
    )


def apply_style_grid_to_processing(processing: Any, *args: Any) -> None:
    source_filter = str(args[1] if len(args) > 1 else "" or "")
    silent_json = args[0] if len(args) > 0 else "[]"
    prompts = list(getattr(processing, "all_prompts", []) or [])
    negatives = list(getattr(processing, "all_negative_prompts", []) or [])
    for index, value in enumerate(prompts):
        negative = negatives[index] if index < len(negatives) else ""
        prompt, neg, names = apply_style_grid_to_prompt_pair(str(value or ""), str(negative or ""), silent_json, source_filter)
        prompts[index] = prompt
        if index < len(negatives):
            negatives[index] = neg
    if prompts:
        processing.all_prompts = prompts
    if negatives:
        processing.all_negative_prompts = negatives
    names = _selected_styles_from_json(silent_json)
    if names:
        try:
            processing.extra_generation_params[STYLE_GRID_SCRIPT_TITLE] = ", ".join(names)
        except Exception:
            pass
        increment_style_grid_usage(names)


def _style_grid_ui_html() -> str:
    index_path = EXT_DIR / "ui" / "dist" / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Style Grid UI is not available.")
    html = index_path.read_text(encoding="utf-8")
    version = str(int(time.time()))
    base = f"{API_PREFIX}/file=forge_neo/webui/extensions/{STYLE_GRID_EXTENSION}/ui/dist"
    pattern = re.compile(
        r'(?P<attr>\b(?:src|href))=(?P<q>["\'])(?P<path>\./[^"\']+)(?P=q)',
        re.IGNORECASE,
    )

    def rewrite(match: re.Match[str]) -> str:
        rel = match.group("path")[2:]
        quote = match.group("q")
        return f'{match.group("attr")}={quote}{base}/{rel}?v={version}{quote}'

    return pattern.sub(rewrite, html)


def style_grid_status_payload() -> dict[str, Any]:
    prepare_style_grid_runtime_files()
    categories = style_grid_categories() if EXT_DIR.is_dir() else {}
    styles = [style for values in categories.values() for style in values]
    return {
        "extension": STYLE_GRID_EXTENSION,
        "display_name": STYLE_GRID_SCRIPT_TITLE,
        "available": style_grid_available(),
        "base": "/style_grid",
        "extension_dir": str(EXT_DIR),
        "style_count": len(styles),
        "category_count": len(categories),
        "thumbnail_count": len(style_grid_thumbnail_names()),
        "ui_dist": str(EXT_DIR / "ui" / "dist"),
        "javascript": [
            f"forge_neo/webui/extensions/{STYLE_GRID_EXTENSION}/javascript/sg_prompt_utils.js",
            f"forge_neo/webui/extensions/{STYLE_GRID_EXTENSION}/javascript/style_grid.js",
        ],
        "css": [f"forge_neo/webui/extensions/{STYLE_GRID_EXTENSION}/style.css"],
        "routes": [
            "/style_grid/styles",
            "/style_grid/reload",
            "/style_grid/check_update",
            "/style_grid/conflicts",
            "/style_grid/export",
            "/style_grid/import",
            "/style_grid/category_order/save",
            "/style_grid/presets",
            "/style_grid/presets/save",
            "/style_grid/presets/delete",
            "/style_grid/presets/list",
            "/style_grid/usage",
            "/style_grid/usage/increment",
            "/style_grid/style/save",
            "/style_grid/style/delete",
            "/style_grid/backup",
            "/style_grid/thumbnails/list",
            "/style_grid/thumbnail",
            "/style_grid/thumbnail/upload",
            "/style_grid/thumbnail/gen_status",
            "/style_grid/thumbnail/generate",
            "/style_grid/thumbnails/cleanup",
            "/style_grid/ui",
            "/forge-neo/extensions/style-grid-status",
        ],
    }


async def _request_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def mount_style_grid_routes(app: Any) -> None:
    if bool(getattr(getattr(app, "state", None), "forge_neo_style_grid_mounted", False)):
        return
    prepare_style_grid_runtime_files()
    setattr(app.state, "forge_neo_style_grid_mounted", True)

    @app.get("/forge-neo/extensions/style-grid-status")
    async def _forge_neo_style_grid_status():
        return style_grid_status_payload()

    @app.get("/style_grid/styles")
    async def _style_grid_styles(request: Request):
        etag = style_grid_cache_key()
        if_none_match = request.headers.get("If-None-Match", "").strip().strip('"')
        if if_none_match and if_none_match == etag:
            return Response(status_code=304)
        response = Response(
            content=json.dumps(style_grid_payload(), ensure_ascii=False),
            media_type="application/json",
        )
        response.headers["ETag"] = etag
        return response

    @app.post("/style_grid/reload")
    async def _style_grid_reload():
        payload = style_grid_payload()
        return {"categories": payload["categories"], "usage": payload["usage"]}

    @app.get("/style_grid/check_update")
    async def _style_grid_check_update():
        return {"changed": False, "etag": style_grid_cache_key()}

    @app.post("/style_grid/conflicts")
    async def _style_grid_conflicts(request: Request):
        data = await _request_json(request)
        styles = data.get("styles", [])
        return {"conflicts": detect_style_grid_conflicts(styles if isinstance(styles, list) else [])}

    @app.get("/style_grid/export")
    async def _style_grid_export():
        return {
            "styles": style_grid_styles(),
            "presets": load_style_grid_presets(),
            "usage": load_style_grid_usage(),
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    @app.post("/style_grid/import")
    async def _style_grid_import(request: Request):
        raw = await request.body()
        if not raw:
            return {"ok": True}
        if raw[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if "presets.json" in archive.namelist():
                    presets = json.loads(archive.read("presets.json").decode("utf-8"))
                    if isinstance(presets, dict):
                        merged = load_style_grid_presets()
                        merged.update(presets)
                        save_style_grid_presets(merged)
            return {"ok": True}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid JSON") from None
        if not isinstance(data, dict):
            return {"ok": True}
        if isinstance(data.get("presets"), dict):
            merged = load_style_grid_presets()
            merged.update(data["presets"])
            save_style_grid_presets(merged)
        imported_styles = data.get("styles")
        if isinstance(imported_styles, list) and imported_styles:
            target = EDITABLE_STYLES_DIR / f"imported_{time.strftime('%Y%m%d_%H%M%S')}.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(STYLE_GRID_FIELDS))
                writer.writeheader()
                for style in imported_styles:
                    if not isinstance(style, dict):
                        continue
                    writer.writerow(
                        {
                            "name": str(style.get("name") or ""),
                            "prompt": str(style.get("prompt") or ""),
                            "negative_prompt": str(style.get("negative_prompt") or ""),
                            "description": str(style.get("description") or ""),
                            "category": str(style.get("category") or style.get("category_explicit") or ""),
                        }
                    )
        return {"ok": True}

    @app.post("/style_grid/category_order/save")
    async def _style_grid_save_category_order(request: Request):
        data = await _request_json(request)
        order = data.get("order", [])
        if not isinstance(order, list):
            return {"error": "order must be a list"}
        save_style_grid_category_order([str(item) for item in order])
        return {"ok": True}

    @app.get("/style_grid/presets")
    async def _style_grid_presets():
        return load_style_grid_presets()

    @app.post("/style_grid/presets/save")
    async def _style_grid_save_preset(request: Request):
        data = await _request_json(request)
        name = str(data.get("name") or "").strip()
        if not name:
            return {"error": "Name required"}
        presets = load_style_grid_presets()
        presets[name] = {"styles": data.get("styles", []), "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
        save_style_grid_presets(presets)
        return {"ok": True, "presets": presets}

    @app.post("/style_grid/presets/delete")
    async def _style_grid_delete_preset(request: Request):
        data = await _request_json(request)
        presets = load_style_grid_presets()
        presets.pop(str(data.get("name") or ""), None)
        save_style_grid_presets(presets)
        return {"ok": True, "presets": presets}

    @app.get("/style_grid/presets/list")
    async def _style_grid_list_presets():
        return load_style_grid_presets()

    @app.get("/style_grid/usage")
    async def _style_grid_usage():
        return load_style_grid_usage()

    @app.post("/style_grid/usage/increment")
    async def _style_grid_increment_usage(request: Request):
        data = await _request_json(request)
        names = data.get("styles", [])
        increment_style_grid_usage(names if isinstance(names, list) else [])
        return {"ok": True}

    @app.post("/style_grid/style/save")
    async def _style_grid_save_style(request: Request):
        return save_style_grid_style(await _request_json(request))

    @app.post("/style_grid/style/delete")
    async def _style_grid_delete_style(request: Request):
        return delete_style_grid_style(await _request_json(request))

    @app.post("/style_grid/backup")
    async def _style_grid_backup():
        try:
            return {"ok": backup_style_grid_csv_files()}
        except Exception as exc:
            return {"error": str(exc)}

    @app.get("/style_grid/thumbnails/list")
    async def _style_grid_thumbnail_list():
        return {"has_thumbnail": sorted(style_grid_thumbnail_names())}

    @app.get("/style_grid/thumbnail")
    async def _style_grid_thumbnail(name: str = "", source: str = ""):
        candidates = [style_grid_thumbnail_path(name)]
        if source:
            candidates.append(style_grid_thumbnail_path(name, source))
        for style in style_grid_styles():
            if style.get("name") == name:
                candidates.append(style_grid_thumbnail_path(name, str(style.get("source_file") or "")))
        for path in candidates:
            if path.is_file():
                return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "no-store"})
        return Response(status_code=404)

    @app.post("/style_grid/thumbnail/upload")
    async def _style_grid_upload_thumbnail(request: Request):
        data = await _request_json(request)
        name = str(data.get("name") or "").strip()
        image_data = str(data.get("image") or "")
        if not name or not image_data:
            return {"error": "name and image required"}
        try:
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]
            raw = base64.b64decode(image_data)
        except Exception:
            return {"error": "Invalid image data"}
        if len(raw) > 2 * 1024 * 1024:
            return {"error": "Image too large (max 2MB)"}
        allowed = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF", b"GIF87a", b"GIF89a")
        if not any(raw.startswith(prefix) for prefix in allowed):
            return {"error": "Invalid image format. Allowed: JPEG, PNG, WEBP, GIF"}
        path = style_grid_thumbnail_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"ok": True}

    @app.get("/style_grid/thumbnail/gen_status")
    async def _style_grid_thumbnail_generation_status(name: str = ""):
        return {"status": "idle", "name": name}

    @app.post("/style_grid/thumbnail/generate")
    async def _style_grid_generate_thumbnail():
        return {"error": "Thumbnail generation is not configured in Forge Neo."}

    @app.delete("/style_grid/thumbnail")
    async def _style_grid_delete_thumbnail(name: str = ""):
        removed = False
        for path in [style_grid_thumbnail_path(name), *[style_grid_thumbnail_path(name, str(style.get("source_file") or "")) for style in style_grid_styles() if style.get("name") == name]]:
            if path.is_file():
                path.unlink()
                removed = True
        return {"ok": True, "removed": removed}

    @app.post("/style_grid/thumbnails/cleanup")
    async def _style_grid_cleanup_thumbnails():
        if not THUMBNAILS_DIR.is_dir():
            return {"removed": 0}
        valid = {style_grid_thumbnail_path(str(style.get("name") or ""), str(style.get("source_file") or "")).stem for style in style_grid_styles()}
        removed = 0
        for path in THUMBNAILS_DIR.glob("*.webp"):
            if path.stem not in valid:
                path.unlink()
                removed += 1
        return {"removed": removed}

    @app.get("/style_grid/ui")
    async def _style_grid_ui():
        return HTMLResponse(content=_style_grid_ui_html())
