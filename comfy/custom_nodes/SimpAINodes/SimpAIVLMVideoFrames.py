import torch
import torch.nn.functional as F
from comfy_api.latest import io


def _unique_ordered(indices, frame_count):
    seen = set()
    out = []
    for index in indices:
        index = int(max(0, min(frame_count - 1, index)))
        if index not in seen:
            seen.add(index)
            out.append(index)
    return out


def _limit_evenly(indices, max_frames):
    if len(indices) <= max_frames:
        return indices
    if max_frames <= 1:
        return [indices[0]]
    last = len(indices) - 1
    return [indices[round(i * last / (max_frames - 1))] for i in range(max_frames)]


MODE_PRACTICAL = "practical"
MODE_GEMMA4_COMPATIBLE = "gemma4_compatible"


def _sample_video_indices(frame_count, source_fps, sample_fps, max_frames, include_last_frame, mode=MODE_PRACTICAL):
    frame_count = max(0, int(frame_count))
    if frame_count <= 0:
        return []

    source_fps = max(0.0, float(source_fps))
    if mode == MODE_GEMMA4_COMPATIBLE:
        fps = source_fps if source_fps > 0.0 else 24.0
        step = max(1, round(fps))
        return list(range(0, frame_count, step))

    max_frames = max(1, int(max_frames))
    sample_fps = max(0.0, float(sample_fps))

    if source_fps > 0.0 and sample_fps > 0.0:
        step = max(1, round(source_fps / sample_fps))
        indices = list(range(0, frame_count, step))
    else:
        indices = list(range(frame_count))

    if include_last_frame and indices[-1] != frame_count - 1:
        indices.append(frame_count - 1)

    indices = _unique_ordered(indices, frame_count)
    return _limit_evenly(indices, max_frames)


def _resize_image_batch_max_side(images, max_side, stride=32):
    max_side = int(max(0, max_side))
    if max_side <= 0:
        return images

    height, width = int(images.shape[1]), int(images.shape[2])
    long_side = max(height, width)
    if long_side <= max_side:
        return images

    scale = max_side / long_side
    target_height = max(stride, round(height * scale / stride) * stride)
    target_width = max(stride, round(width * scale / stride) * stride)
    if target_height == height and target_width == width:
        return images

    resized = F.interpolate(
        images.movedim(-1, 1),
        size=(target_height, target_width),
        mode="bilinear",
        align_corners=False,
    )
    return resized.movedim(1, -1)


class SimpAIVLMVideoFrames(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SimpAIVLMVideoFrames",
            display_name="SimpAI VLM Video Frames",
            category="image/video",
            description="Sample video frames into an IMAGE batch for multimodal text encoders that only expose image input.",
            inputs=[
                io.Image.Input("video"),
                io.Combo.Input(
                    "mode",
                    options=[MODE_PRACTICAL, MODE_GEMMA4_COMPATIBLE],
                    default=MODE_PRACTICAL,
                    tooltip="gemma4_compatible matches Generate Text's Gemma4 video sampling: range(0, frames, round(source_fps)).",
                ),
                io.Float.Input("source_fps", default=24.0, min=0.0, max=240.0, step=0.01),
                io.Float.Input("sample_fps", default=1.0, min=0.0, max=60.0, step=0.01),
                io.Int.Input("max_frames", default=8, min=1, max=64, step=1),
                io.Int.Input("max_side", default=640, min=0, max=4096, step=32, tooltip="Resize selected frames before VLM input. 0 disables resizing."),
                io.Boolean.Input("include_last_frame", default=True),
            ],
            outputs=[
                io.Image.Output(display_name="vlm_images"),
                io.Int.Output(display_name="selected_count"),
            ],
        )

    @classmethod
    def execute(cls, video, mode, source_fps, sample_fps, max_frames, max_side=640, include_last_frame=True) -> io.NodeOutput:
        frame_count = int(video.shape[0])
        indices = _sample_video_indices(
            frame_count,
            source_fps,
            sample_fps,
            max_frames,
            include_last_frame,
            mode,
        )
        if not indices:
            return io.NodeOutput(video, 0)

        index_tensor = torch.tensor(indices, dtype=torch.long, device=video.device)
        images = video.index_select(0, index_tensor)
        images = _resize_image_batch_max_side(images, max_side)
        return io.NodeOutput(images, len(indices))


NODE_CLASS_MAPPINGS = {
    "SimpAIVLMVideoFrames": SimpAIVLMVideoFrames,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIVLMVideoFrames": "SimpAI VLM Video Frames",
}
