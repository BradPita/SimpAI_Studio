from __future__ import annotations

import base64
import json
from io import BytesIO
from types import MethodType

import gradio as gr
import numpy as np
from PIL import Image as PILImage

from ui.components import sketch_cache


DEFAULT_SKETCH_BRUSH_RADIUS = 64
MAX_SKETCH_BRUSH_RADIUS = 512


def create_sketch_image(*args, **kwargs):
    return _create_gradio6_sketch_image(*args, **kwargs)


def _normalize_brush_radius(value):
    if value is None:
        value = DEFAULT_SKETCH_BRUSH_RADIUS
    try:
        radius = int(float(value))
    except Exception:
        radius = DEFAULT_SKETCH_BRUSH_RADIUS
    return max(2, min(radius, MAX_SKETCH_BRUSH_RADIUS))


def _normalize_sketch_textbox_kwargs(kwargs):
    normalized = dict(kwargs)
    brush_color = normalized.pop("brush_color", "#FFFFFF")
    brush_radius = _normalize_brush_radius(normalized.pop("brush_radius", None))
    preserve_mask_color = bool(normalized.pop("preserve_mask_color", False))
    canvas_height = normalized.pop("height", None)
    canvas_width = normalized.pop("width", None)
    normalized.setdefault("lines", 1)
    normalized.setdefault("visible", True)
    normalized.setdefault("interactive", True)
    normalized.setdefault("show_label", False)
    if normalized.get("elem_classes") is None:
        normalized["elem_classes"] = []
    if isinstance(normalized["elem_classes"], str):
        normalized["elem_classes"] = [normalized["elem_classes"]]
    normalized["elem_classes"].append("simpai-custom-sketch-source")
    if canvas_height:
        normalized["elem_classes"].append(f"simpai-sketch-height-{int(canvas_height)}")
    if canvas_width:
        normalized["elem_classes"].append(f"simpai-sketch-width-{int(canvas_width)}")
    normalized["elem_classes"].append(f"simpai-sketch-radius-{int(brush_radius)}")
    if isinstance(brush_color, str):
        normalized["elem_classes"].append(f"simpai-sketch-brush-{brush_color.strip('#')}")
    if preserve_mask_color:
        normalized["elem_classes"].append("simpai-sketch-preserve-mask-color")
    return normalized, brush_color, brush_radius, preserve_mask_color, canvas_height, canvas_width


def _sketch_textbox_get_config(self):
    config = gr.Textbox.get_config(self, gr.Textbox)
    config["simpai_custom_sketch"] = {
        "brush_color": self.brush_color,
        "brush_radius": self.brush_radius,
        "height": self.canvas_height,
        "width": self.canvas_width,
        "image_mode": self.image_mode,
        "preserve_mask_color": self.preserve_mask_color,
    }
    return config


def _sketch_textbox_preprocess(self, payload):
    text = gr.Textbox.preprocess(self, payload)
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    image_source = sketch_cache.resolve_payload_source(data, "image")
    mask_source = sketch_cache.resolve_payload_source(data, "mask")
    image = _decode_data_url_to_value(image_source, self.image_type, self.image_mode)
    mask = _decode_mask_data_url_to_value(mask_source, self.image_type, self.preserve_mask_color)
    if image is None and mask is None:
        return None
    return {"image": image, "mask": mask}


def _sketch_textbox_postprocess(self, value):
    if value is None:
        return None
    if isinstance(value, str):
        return value

    image = None
    mask = None
    if isinstance(value, dict):
        image = value.get("image")
        if image is None:
            image = value.get("background")
        if image is None:
            image = value.get("composite")
        layers = value.get("layers") or []
        mask = value.get("mask")
        if mask is None and layers:
            mask = layers[0]
    else:
        image = value
        mask = value

    payload = {
        "image": _encode_image_value_to_data_url(image),
        "mask": _encode_image_value_to_data_url(mask),
    }
    return json.dumps(payload)


def _sketch_textbox_change(self, *args, **kwargs):
    return self.change(*args, **kwargs)


def _attach_simpai_sketch_bridge(
    component,
    *,
    image_type,
    image_mode,
    brush_color,
    brush_radius,
    preserve_mask_color,
    canvas_height,
    canvas_width,
):
    component.image_type = image_type
    component.image_mode = image_mode
    component.brush_color = brush_color
    component.brush_radius = brush_radius
    component.preserve_mask_color = preserve_mask_color
    component.canvas_height = canvas_height
    component.canvas_width = canvas_width
    component.get_config = MethodType(_sketch_textbox_get_config, component)
    component.preprocess = MethodType(_sketch_textbox_preprocess, component)
    component.postprocess = MethodType(_sketch_textbox_postprocess, component)
    component.upload = MethodType(_sketch_textbox_change, component)
    component.clear = MethodType(_sketch_textbox_change, component)
    return component


def _decode_data_url_to_pil(data_url: str | None, image_mode: str | None = None):
    if not isinstance(data_url, str) or "," not in data_url:
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
        image = PILImage.open(BytesIO(raw))
        if image_mode:
            image = image.convert(image_mode)
        return image
    except Exception:
        return None


def _decode_data_url_to_value(data_url: str | None, image_type: str, image_mode: str | None = None):
    image = _decode_data_url_to_pil(data_url, image_mode)
    if image is None:
        return None
    if image_type == "pil":
        return image
    if image_type == "filepath":
        return None
    return np.array(image)


def _decode_mask_data_url_to_value(data_url: str | None, image_type: str, preserve_color: bool = False):
    image = _decode_data_url_to_pil(data_url, "RGBA")
    if image is None:
        return None
    if preserve_color:
        if image_type == "pil":
            return image
        if image_type == "filepath":
            return None
        return np.array(image)
    alpha = np.array(image.getchannel("A"))
    if np.any(alpha < 255):
        mask = np.where(alpha > 0, 255, 0).astype(np.uint8)
        mask_rgb = np.repeat(mask[:, :, None], 3, axis=2)
    else:
        mask_rgb = np.array(image.convert("RGB"))
    if image_type == "pil":
        return PILImage.fromarray(mask_rgb, mode="RGB")
    if image_type == "filepath":
        return None
    return mask_rgb


def _encode_image_value_to_data_url(value):
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        array = value
        if array.dtype != np.uint8:
            array = np.clip(array, 0, 255).astype(np.uint8)
        image = PILImage.fromarray(array)
    elif isinstance(value, PILImage.Image):
        image = value
    else:
        return None
    if image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _create_gradio6_sketch_image(*args, **kwargs):
    normalized = dict(kwargs)
    image_type = normalized.pop("type", "numpy")
    image_mode = normalized.pop("image_mode", "RGBA")
    normalized, brush_color, brush_radius, preserve_mask_color, canvas_height, canvas_width = _normalize_sketch_textbox_kwargs(normalized)
    component = gr.Textbox(*args, **normalized)
    return _attach_simpai_sketch_bridge(
        component,
        image_type=image_type,
        image_mode=image_mode,
        brush_color=brush_color,
        brush_radius=brush_radius,
        preserve_mask_color=preserve_mask_color,
        canvas_height=canvas_height,
        canvas_width=canvas_width,
    )
