import os
import sys

import numpy as np
import onnxruntime as ort
import torch
from segment_anything import sam_model_registry
from segment_anything.utils.amg import remove_small_regions

from .sam_predictor import SamPredictor


def _hwc3(image):
    if image.ndim == 2:
        image = image[:, :, None]
    channels = image.shape[2]
    if channels == 3:
        return image
    if channels == 1:
        return np.concatenate([image, image, image], axis=2)
    color = image[:, :, :3].astype(np.float32)
    alpha = image[:, :, 3:4].astype(np.float32) / 255.0
    return (color * alpha + 255.0 * (1.0 - alpha)).clip(0, 255).astype(np.uint8)


def _load_rembg():
    try:
        from rembg import new_session, remove
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"RMBG/自动蒙版依赖加载失败。RMBG / automatic mask dependencies failed to load. Original error: {exc}") from exc
    return remove, new_session


def _ort_providers():
    available = set(ort.get_available_providers())
    preferred = ["CUDAExecutionProvider", "DirectMLExecutionProvider", "DmlExecutionProvider",
                 "ROCMExecutionProvider", "CoreMLExecutionProvider", "CPUExecutionProvider"]
    if os.environ.get("SIMPAI_REMBG_ENABLE_TENSORRT") == "1":
        preferred.insert(0, "TensorrtExecutionProvider")
    return [provider for provider in preferred if provider in available] or ["CPUExecutionProvider"]


class SAMOptions:
    def __init__(self, dino_prompt="", dino_box_threshold=0.3, dino_text_threshold=0.25,
                 dino_erode_or_dilate=0, dino_debug=False, max_detections=2, model_type="vit_b"):
        self.dino_prompt = dino_prompt
        self.dino_box_threshold = dino_box_threshold
        self.dino_text_threshold = dino_text_threshold
        self.dino_erode_or_dilate = dino_erode_or_dilate
        self.dino_debug = dino_debug
        self.max_detections = max_detections
        self.model_type = model_type


def _optimize_masks(masks):
    fine_masks = [remove_small_regions(mask[0], 400, mode="holes")[0] for mask in masks.cpu().numpy()]
    return torch.from_numpy(np.stack(fine_masks, axis=0)[:, np.newaxis])


def generate_mask_from_image(image, mask_model="sam", extras=None, sam_options=None, backend=None):
    if image is None:
        return None, 0, 0, 0
    extras = extras or {}
    image = _hwc3(image["image"] if isinstance(image, dict) and "image" in image else image)
    if mask_model != "sam" or sam_options is None:
        remove, new_session = _load_rembg()
        os.environ["U2NET_HOME"] = backend.resolve_rembg_home(mask_model)
        result = remove(image, session=new_session(mask_model, providers=_ort_providers(), **extras), only_mask=True, **extras)
        return result, 0, 0, 0
    _, boxes, logits, _ = backend.groundingdino(
        image=image,
        caption=sam_options.dino_prompt,
        box_threshold=sam_options.dino_box_threshold,
        text_threshold=sam_options.dino_text_threshold,
    )
    height, width = image.shape[:2]
    boxes = boxes * torch.tensor([width, height, width, height])
    boxes[:, :2] -= boxes[:, 2:] / 2
    boxes[:, 2:] += boxes[:, :2]
    predictor = SamPredictor(sam_model_registry[sam_options.model_type](checkpoint=backend.resolve_sam_model(sam_options.model_type)))
    final_mask = torch.zeros((height, width))
    dino_count = boxes.size(0)
    sam_count = applied_count = 0
    if dino_count > 0:
        predictor.set_image(image)
        transformed_boxes = predictor.transform.apply_boxes_torch(boxes, image.shape[:2])
        masks, _, _ = predictor.predict_torch(None, None, boxes=transformed_boxes, multimask_output=False)
        masks = _optimize_masks(masks)
        sam_count = len(masks)
        maximum = sys.maxsize if sam_options.max_detections == 0 else sam_options.max_detections
        for index in range(min(len(logits), maximum)):
            final_mask += masks[index][0]
            applied_count += 1
    final_mask = (final_mask > 0).cpu().numpy()
    return np.dstack((final_mask, final_mask, final_mask)).astype(np.uint8) * 255, dino_count, sam_count, applied_count
