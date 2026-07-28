import mimetypes
import math
import os

import numpy as np
from PIL import Image

from modules import prompt_actions


IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}


def media_path(value):
    return prompt_actions.normalize_media_path(value)


def media_type(value):
    if isinstance(value, (Image.Image, np.ndarray)):
        return "image"
    path = media_path(value)
    mime = str(mimetypes.guess_type(path)[0] or "").lower()
    suffix = os.path.splitext(path)[1].lower()
    if mime.startswith("image/") or suffix in IMAGE_EXTENSIONS:
        return "image"
    if mime.startswith("video/") or suffix in VIDEO_EXTENSIONS:
        return "video"
    return ""


def normalize_image(value):
    if isinstance(value, np.ndarray):
        array = value
        if array.dtype != np.uint8:
            array = np.clip(array, 0, 255).astype(np.uint8)
        try:
            return np.array(Image.fromarray(array).convert("RGB"))
        except Exception:
            return None
    if isinstance(value, Image.Image):
        return np.array(value.convert("RGB"))
    path = media_path(value)
    if not path or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as image:
            return np.array(image.convert("RGB"))
    except Exception:
        return None


def format_image_size(width, height, aspect_ratios=None):
    width = int(width)
    height = int(height)
    divisor = math.gcd(width, height)
    label = f"{width} x {height} | {width // divisor}:{height // divisor}"
    ratios = list(aspect_ratios or [])
    if ratios:
        ratio = round(width / height, 2)
        closest = min(ratios, key=lambda value: abs(ratio - float(value.split("*")[0]) / float(value.split("*")[1])))
        recommended_width, recommended_height = map(int, closest.split("*"))
        recommended_divisor = math.gcd(recommended_width, recommended_height)
        label += (
            f"     /     {recommended_width} x {recommended_height} | "
            f"{recommended_width // recommended_divisor}:{recommended_height // recommended_divisor}"
        )
    return label


def media_properties(value, aspect_ratios=None):
    kind = media_type(value)
    path = media_path(value)
    if kind == "image":
        image = normalize_image(value)
        if image is None:
            return {"type": kind, "ok": False, "error": "Image could not be decoded."}
        height, width = image.shape[:2]
        label = format_image_size(width, height, aspect_ratios)
        return {"type": kind, "ok": True, "width": width, "height": height, "label": label}

    if kind == "video" and path and os.path.isfile(path):
        capture = None
        try:
            import cv2

            capture = cv2.VideoCapture(path)
            if capture is None or not capture.isOpened():
                raise ValueError("Video could not be opened.")
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = float(frame_count) / fps if fps > 0 and frame_count > 0 else 0.0
            dimensions = f"{width} x {height}" if width > 0 and height > 0 else "Unknown resolution"
            duration_label = f"{duration:.2f}s" if duration > 0 else "Unknown duration"
            fps_label = f"{fps:.2f} FPS" if fps > 0 else "Unknown FPS"
            return {
                "type": kind,
                "ok": True,
                "width": width,
                "height": height,
                "fps": round(fps, 3),
                "duration_seconds": round(duration, 3),
                "label": f"Video | {dimensions} | {duration_label} | {fps_label}",
            }
        except Exception as exc:
            return {"type": kind, "ok": False, "error": str(exc)}
        finally:
            try:
                if capture is not None:
                    capture.release()
            except Exception:
                pass

    return {"type": kind, "ok": False, "error": "Choose a supported image or video file."}


def prepare_visual_input(value, *, use_multi_frame=False, max_frames=prompt_actions.PROMPT_ACTION_VIDEO_FRAMES):
    kind = media_type(value)
    if kind == "image":
        image = normalize_image(value)
        if image is None:
            raise ValueError("Image could not be decoded.")
        return image, {"media_type": "image", "video_used": False, "sampled_frames": 0}

    if kind != "video":
        raise ValueError("Choose a supported image or video file.")
    path = media_path(value)
    if not path or not os.path.isfile(path):
        raise ValueError("Video file is unavailable.")

    if use_multi_frame:
        frames, meta = prompt_actions.build_video_frame_sequence(path, max_frames=max_frames)
        visual_input = frames
    else:
        sheet, meta = prompt_actions.build_video_contact_sheet(path, max_frames=max_frames)
        visual_input = sheet
    if visual_input is None or (isinstance(visual_input, list) and not visual_input):
        raise ValueError("No decodable video frames were found.")

    meta = dict(meta or {})
    meta.update({
        "media_type": "video",
        "video_used": True,
        "video_source": "describe_upload",
    })
    return visual_input, meta


def build_instruction(media_kind, *, output_tags=False, output_chinese=False, output_artist=False, additional_prompt="", media_meta=None):
    is_video = str(media_kind or "").lower() == "video"
    output_tags = bool(output_tags and not is_video)
    if output_tags:
        instruction = (
            "Analyze the visible media and output only concise comma-separated English generator tags. "
            "Cover subjects, appearance, actions, setting, composition, camera, lighting, and style. "
            "Do not add headings, prose, explanations, or unverifiable details."
        )
    else:
        instruction = (
            "Reverse-engineer the visible media into one generator-ready prompt. "
            "Describe subjects, appearance, actions, setting, spatial relationships, composition, camera, lighting, mood, materials, and visual style. "
            "Output only the prompt without a heading or explanation."
        )
    if is_video:
        instruction += (
            " Treat the visual inputs as chronological video evidence. Describe visible motion, temporal development, and camera movement, "
            "while preserving continuity. Do not infer audio, dialogue, or events that are not visible."
        )
    elif output_artist:
        instruction += " Include a concise visual artist or art-direction reference only when it is visibly supportable."
    if output_chinese:
        instruction += " Write the final result in Chinese."
    extra = str(additional_prompt or "").strip()
    if extra:
        instruction += f"\n\nAdditional user instruction:\n{extra}"
    if is_video:
        media_note = prompt_actions.prompt_action_media_note(media_meta or {})
        if media_note:
            instruction += f"\n\n{media_note}"
    return instruction
