from typing import Tuple, List
import os
from pathlib import Path

import ldm_patched.modules.model_management as model_management
from ldm_patched.modules.model_patcher import ModelPatcher
from modules.model_path_utils import find_model_in_dirs
from torch.hub import download_url_to_file

import numpy as np
import supervision as sv
import torch
from groundingdino.util.inference import Model
from groundingdino.util.inference import load_model, preprocess_caption, get_phrases_from_posmap


class GroundingDinoModel(Model):
    def __init__(self, model_dirs=None, download_dir=None):
        self.config_file = str(Path(__file__).resolve().parents[1] / 'config' / 'GroundingDINO_SwinT_OGC.py')
        self.model_dirs = list(model_dirs) if model_dirs is not None else None
        self.download_dir = download_dir
        self.model = None
        self.load_device = torch.device('cpu')
        self.offload_device = torch.device('cpu')

    def _resolve_checkpoint(self):
        filename = 'groundingdino_swint_ogc.pth'
        if self.model_dirs is None:
            from modules.config import paths_grounding_dino, paths_inpaint
            from modules.model_loader import load_file_from_url

            checkpoint = find_model_in_dirs(paths_grounding_dino + paths_inpaint, filename)
            if checkpoint is None:
                checkpoint = load_file_from_url(
                    url="https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth",
                    file_name=filename,
                    model_dir=paths_grounding_dino[0],
                )
            return checkpoint

        checkpoint = find_model_in_dirs(self.model_dirs, filename)
        if checkpoint is not None:
            return checkpoint
        target_dir = self.download_dir or self.model_dirs[0]
        os.makedirs(target_dir, exist_ok=True)
        checkpoint = os.path.join(target_dir, filename)
        download_url_to_file(
            "https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth",
            checkpoint,
        )
        return checkpoint

    @torch.no_grad()
    @torch.inference_mode()
    def predict_with_caption(
            self,
            image: np.ndarray,
            caption: str,
            box_threshold: float = 0.35,
            text_threshold: float = 0.25
    ) -> Tuple[sv.Detections, torch.Tensor, torch.Tensor, List[str]]:
        if self.model is None:
            filename = self._resolve_checkpoint()
            model = load_model(model_config_path=self.config_file, model_checkpoint_path=filename)

            self.load_device = model_management.text_encoder_device()
            self.offload_device = model_management.text_encoder_offload_device()

            model.to(self.offload_device)

            self.model = ModelPatcher(model, load_device=self.load_device, offload_device=self.offload_device)

        model_management.load_model_gpu(self.model)

        processed_image = GroundingDinoModel.preprocess_image(image_bgr=image).to(self.load_device)
        boxes, logits, phrases = predict(
            model=self.model,
            image=processed_image,
            caption=caption,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
            device=self.load_device)
        source_h, source_w, _ = image.shape
        detections = GroundingDinoModel.post_process_result(
            source_h=source_h,
            source_w=source_w,
            boxes=boxes,
            logits=logits)
        return detections, boxes, logits, phrases


def predict(
        model,
        image: torch.Tensor,
        caption: str,
        box_threshold: float,
        text_threshold: float,
        device: str = "cuda"
) -> Tuple[torch.Tensor, torch.Tensor, List[str]]:
    caption = preprocess_caption(caption=caption)

    # override to use model wrapped by patcher
    model = model.model.to(device)
    image = image.to(device)

    with torch.no_grad():
        outputs = model(image[None], captions=[caption])

    prediction_logits = outputs["pred_logits"].cpu().sigmoid()[0]  # prediction_logits.shape = (nq, 256)
    prediction_boxes = outputs["pred_boxes"].cpu()[0]  # prediction_boxes.shape = (nq, 4)

    mask = prediction_logits.max(dim=1)[0] > box_threshold
    logits = prediction_logits[mask]  # logits.shape = (n, 256)
    boxes = prediction_boxes[mask]  # boxes.shape = (n, 4)

    tokenizer = model.tokenizer
    tokenized = tokenizer(caption)

    phrases = [
        get_phrases_from_posmap(logit > text_threshold, tokenized, tokenizer).replace('.', '')
        for logit
        in logits
    ]

    return boxes, logits.max(dim=1)[0], phrases


default_groundingdino = GroundingDinoModel().predict_with_caption
