import base64
import importlib
import importlib.util
import io
import json
import os
import re
import sys
import threading
import time
import types
from pathlib import Path
from urllib.parse import unquote

import modules.canvas_workbench_assets as canvas_workbench_assets


LIVEPORTRAIT_PACKAGE_NAME = "simpai_comfyui_advanced_liveportrait"
DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]+)?(?:;[^,]*)?;base64,(?P<data>.*)$", re.DOTALL)
_PREVIEW_LOCK = threading.Lock()
_EXPRESSION_EDITOR = None


MODEL_FILES = (
    ("liveportrait", "appearance_feature_extractor.safetensors", 3361936),
    ("liveportrait", "motion_extractor.safetensors", 112496256),
    ("liveportrait", "warping_module.safetensors", 182158564),
    ("liveportrait", "spade_generator.safetensors", 221771768),
    ("liveportrait", "stitching_retargeting_module.safetensors", 911836),
    ("ultralytics", "face_yolov8n.pt", 6230011),
)


def _repo_root():
    return Path(__file__).resolve().parents[2]


def _comfy_root():
    return _repo_root() / "comfy"


def _advanced_liveportrait_root():
    return _comfy_root() / "custom_nodes" / "ComfyUI-AdvancedLivePortrait"


def _parser_node_path():
    return _comfy_root() / "custom_nodes" / "SimpAINodes" / "SimpAILivePortraitExpression.py"


def _resolve_path(value):
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if not path.is_absolute():
        path = _repo_root() / path
    return path.resolve()


def _dedupe_paths(paths):
    seen = set()
    out = []
    for path in paths:
        if path is None:
            continue
        key = os.path.normcase(os.path.normpath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(path))
    return out


def _category_dirs(category):
    paths = []
    try:
        import modules.config as config

        for value in (getattr(config, "model_cata_map", {}) or {}).get(category, []) or []:
            resolved = _resolve_path(value)
            if resolved is not None:
                paths.append(resolved)
        attr = f"paths_{category.replace('-', '_')}"
        for value in getattr(config, attr, []) or []:
            resolved = _resolve_path(value)
            if resolved is not None:
                paths.append(resolved)
        models_root = _resolve_path(getattr(config, "path_models_root", "") or config.get_path_models_root())
        if models_root is not None:
            folder = "ultralytics" if category == "ultralytics" else category
            paths.append(models_root / folder)
    except Exception:
        pass

    if category == "liveportrait":
        paths.extend([
            _repo_root() / "models" / "liveportrait",
            _comfy_root() / "models" / "liveportrait",
        ])
    elif category == "ultralytics":
        paths.extend([
            _repo_root() / "models" / "ultralytics",
            _comfy_root() / "models" / "ultralytics",
        ])
    return _dedupe_paths(paths)


def _file_info(category, filename, expected_size=0):
    candidates = []
    for directory in _category_dirs(category):
        path = directory / filename
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        ok = exists and (not expected_size or size == int(expected_size))
        candidates.append({
            "category": category,
            "filename": filename,
            "path": str(path),
            "exists": exists,
            "size": size,
            "expected_size": int(expected_size or 0),
            "ok": ok,
            "size_mismatch": exists and bool(expected_size) and size != int(expected_size),
        })
    if not candidates:
        fallback = _repo_root() / "models" / category / filename
        candidates.append({
            "category": category,
            "filename": filename,
            "path": str(fallback),
            "exists": False,
            "size": 0,
            "expected_size": int(expected_size or 0),
            "ok": False,
            "size_mismatch": False,
        })
    best = next((item for item in candidates if item["ok"]), None)
    if best is None:
        best = next((item for item in candidates if item["exists"]), candidates[0])
    best = dict(best)
    best["candidates"] = candidates
    return best


def _category_ready_dir(category):
    specs = [(filename, size) for current, filename, size in MODEL_FILES if current == category]
    for directory in _category_dirs(category):
        ready = True
        for filename, expected_size in specs:
            path = directory / filename
            if not path.is_file():
                ready = False
                break
            if expected_size and path.stat().st_size != int(expected_size):
                ready = False
                break
        if ready:
            return directory
    return None


def _module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _load_params_module():
    spec = importlib.util.spec_from_file_location("_simpai_liveportrait_expression_params", _parser_node_path())
    if spec is None or spec.loader is None:
        raise RuntimeError("LivePortraitExpressionParams node is unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_expression_state(value):
    return _load_params_module().parse_liveportrait_expression_state(value)


def resource_status(payload=None):
    files = [_file_info(category, filename, size) for category, filename, size in MODEL_FILES]
    missing = [item for item in files if not item.get("ok")]
    node_root = _advanced_liveportrait_root()
    node_files = [
        node_root / "nodes.py",
        node_root / "LivePortrait" / "config" / "models.yaml",
        node_root / "LivePortrait" / "utils" / "resources" / "mask_template.png",
    ]
    node_missing = [str(path) for path in node_files if not path.is_file()]
    dependencies = {
        "torch": _module_available("torch"),
        "numpy": _module_available("numpy"),
        "PIL": _module_available("PIL"),
        "cv2": _module_available("cv2"),
        "yaml": _module_available("yaml"),
        "dill": _module_available("dill"),
        "ultralytics": _module_available("ultralytics"),
        "folder_paths": _module_available("folder_paths") or (_comfy_root() / "folder_paths.py").is_file(),
    }
    dependency_missing = [name for name, ok in dependencies.items() if not ok]
    ready = not missing and not node_missing and not dependency_missing
    return {
        "ok": True,
        "ready": ready,
        "auto_download": False,
        "files": files,
        "missing": missing,
        "node_root": str(node_root),
        "node_missing": node_missing,
        "dependencies": dependencies,
        "dependency_missing": dependency_missing,
        "message": "ready" if ready else "resource_missing",
    }


def _ensure_comfy_import_path():
    for path in (_repo_root(), _comfy_root()):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _register_model_dirs():
    _ensure_comfy_import_path()
    import folder_paths

    for category in ("liveportrait", "ultralytics"):
        path = _category_ready_dir(category)
        if path is not None and path.is_dir():
            folder_paths.add_model_folder_path(category, str(path), is_default=True)


def _load_advanced_liveportrait_nodes():
    _ensure_comfy_import_path()
    root = _advanced_liveportrait_root()
    if not root.is_dir():
        raise FileNotFoundError(f"ComfyUI-AdvancedLivePortrait was not found: {root}")
    package = sys.modules.get(LIVEPORTRAIT_PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(LIVEPORTRAIT_PACKAGE_NAME)
        package.__path__ = [str(root)]
        package.__package__ = LIVEPORTRAIT_PACKAGE_NAME
        sys.modules[LIVEPORTRAIT_PACKAGE_NAME] = package
    return importlib.import_module(f"{LIVEPORTRAIT_PACKAGE_NAME}.nodes")


def _value_from_payload(payload, *keys):
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = payload.get(key)
        if value:
            return value
    return ""


def _decode_source_to_bytes(value):
    if isinstance(value, dict):
        value = _value_from_payload(value, "image_data_url", "data_url", "path", "url", "preview_url")
    text = str(value or "").strip()
    if not text:
        return b""
    match = DATA_URL_RE.match(text)
    if match:
        return base64.b64decode(match.group("data"))
    if text.startswith("/file="):
        text = unquote(text[len("/file="):])
    path = Path(text)
    if path.is_file():
        return path.read_bytes()
    return b""


def _image_source_to_tensor(value):
    raw = _decode_source_to_bytes(value)
    if not raw:
        return None
    import numpy as np
    import torch
    from PIL import Image

    image = Image.open(io.BytesIO(raw)).convert("RGB")
    array = np.asarray(image).astype(np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _tensor_to_data_url(tensor):
    import numpy as np
    from PIL import Image

    if tensor is None:
        return ""
    if hasattr(tensor, "detach"):
        tensor = tensor.detach().cpu().numpy()
    array = np.asarray(tensor)
    if array.ndim == 4:
        array = array[0]
    array = np.clip(array * 255.0, 0, 255).astype(np.uint8)
    image = Image.fromarray(array)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _render_expression(payload):
    global _EXPRESSION_EDITOR

    status = resource_status(payload)
    if not status.get("ready"):
        return {
            "ok": False,
            "error": "LivePortrait Expression resources are missing.",
            "code": "resource_missing",
            "status": status,
        }

    expression_state = _value_from_payload(payload, "expression_state", "state", "params_json")
    if not expression_state and isinstance(payload, dict) and isinstance(payload.get("params"), dict):
        expression_state = json.dumps({"params": payload.get("params")})
    params = parse_expression_state(expression_state)
    source_tensor = _image_source_to_tensor(_value_from_payload(payload, "source_image", "source_image_data_url", "image_data_url"))
    if source_tensor is None:
        return {
            "ok": False,
            "error": "Source image is required.",
            "code": "source_image_required",
            "status": status,
            "params": params,
        }
    reference_tensor = _image_source_to_tensor(_value_from_payload(payload, "reference_image", "reference_image_data_url", "sample_image"))

    _register_model_dirs()
    nodes = _load_advanced_liveportrait_nodes()
    with _PREVIEW_LOCK:
        if _EXPRESSION_EDITOR is None:
            _EXPRESSION_EDITOR = nodes.ExpressionEditor()
        result = _EXPRESSION_EDITOR.run(
            params["rotate_pitch"],
            params["rotate_yaw"],
            params["rotate_roll"],
            params["blink"],
            params["eyebrow"],
            params["wink"],
            params["pupil_x"],
            params["pupil_y"],
            params["aaa"],
            params["eee"],
            params["woo"],
            params["smile"],
            params["src_ratio"],
            params["sample_ratio"],
            params["sample_parts"],
            params["crop_factor"],
            src_image=source_tensor,
            sample_image=reference_tensor,
        )

    output_tensor = None
    ui_images = []
    if isinstance(result, dict):
        values = result.get("result") or ()
        if values:
            output_tensor = values[0]
        ui_images = ((result.get("ui") or {}).get("images") or [])
    elif isinstance(result, (tuple, list)) and result:
        output_tensor = result[0]
    image_data_url = _tensor_to_data_url(output_tensor)
    if not image_data_url:
        return {
            "ok": False,
            "error": "Expression preview did not return an image.",
            "code": "empty_preview",
            "status": status,
            "params": params,
            "ui_images": ui_images,
        }
    return {
        "ok": True,
        "image_data_url": image_data_url,
        "expression_image": {"data_url": image_data_url},
        "params": params,
        "status": status,
        "ui_images": ui_images,
    }


def preview(payload):
    try:
        return _render_expression(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        return {"ok": False, "error": str(exc), "code": "preview_error", "status": resource_status(payload)}


def export_image(payload, state_params=None):
    payload = payload if isinstance(payload, dict) else {}
    state_params = state_params if isinstance(state_params, dict) else {}
    data_url = str(payload.get("image_data_url") or payload.get("data_url") or "").strip()
    rendered = {}
    if data_url.startswith("data:image/"):
        params = payload.get("params") if isinstance(payload.get("params"), dict) else parse_expression_state(_value_from_payload(payload, "expression_state", "state", "params_json"))
    else:
        rendered = preview(payload)
        if not rendered.get("ok"):
            return rendered
        data_url = str(rendered.get("image_data_url") or (rendered.get("expression_image") or {}).get("data_url") or "").strip()
        params = rendered.get("params") if isinstance(rendered.get("params"), dict) else {}
    if not data_url.startswith("data:image/"):
        return {"ok": False, "error": "LivePortrait Expression export requires an image data URL."}

    project_id = str(payload.get("project_id") or "default")
    node_id = str(payload.get("node_id") or "liveportrait_expression")
    source_asset = payload.get("source_asset") if isinstance(payload.get("source_asset"), dict) else None
    reference_asset = payload.get("reference_asset") if isinstance(payload.get("reference_asset"), dict) else None
    metadata = {
        "mime": "image/png",
        "width": payload.get("width") or (payload.get("source_size") or {}).get("width"),
        "height": payload.get("height") or (payload.get("source_size") or {}).get("height"),
        "generation_metadata": {
            "tool": "LivePortrait Exp",
            "params": params,
            "sample_parts": params.get("sample_parts"),
            "source_asset_id": (source_asset or {}).get("asset_id") or "",
            "reference_asset_id": (reference_asset or {}).get("asset_id") or "",
        },
    }
    try:
        asset_ref = canvas_workbench_assets.save_data_url_asset(
            data_url,
            project_id,
            state_params,
            node_id=node_id,
            role="liveportrait_expression",
            metadata=metadata,
        )
    except Exception as err:
        return {"ok": False, "error": "LivePortrait Expression export failed.", "details": f"{type(err).__name__}: {err}"}
    if not asset_ref:
        return {"ok": False, "error": "LivePortrait Expression export produced no asset."}
    return {
        "ok": True,
        "asset_ref": asset_ref,
        "expression_image": asset_ref,
        "params": params,
        "source_asset": source_asset,
        "reference_asset": reference_asset,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
