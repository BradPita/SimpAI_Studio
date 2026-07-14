from fractions import Fraction

import torch
from comfy_api.latest import io


def _ceil_div(numerator, denominator):
    return (numerator + denominator - 1) // denominator


def align_video_and_audio(images, audio, fps):
    if images is None or images.shape[0] == 0:
        raise ValueError("At least one video frame is required.")
    if audio is None:
        raise ValueError("Audio is required.")

    waveform = audio["waveform"]
    sample_rate = int(audio["sample_rate"])
    if sample_rate <= 0:
        raise ValueError("Audio sample rate must be greater than zero.")

    fps_fraction = Fraction(str(float(fps))).limit_denominator(1_000_000)
    if fps_fraction <= 0:
        raise ValueError("FPS must be greater than zero.")

    fps_numerator = fps_fraction.numerator
    fps_denominator = fps_fraction.denominator
    audio_samples = int(waveform.shape[-1])
    audio_frame_count = _ceil_div(
        audio_samples * fps_numerator,
        sample_rate * fps_denominator,
    )
    target_frame_count = max(int(images.shape[0]), audio_frame_count)

    source_frame_count = int(images.shape[0])
    cycle_length = source_frame_count * 2
    positions = torch.arange(target_frame_count, device=images.device) % cycle_length
    frame_indices = torch.where(
        positions < source_frame_count,
        positions,
        cycle_length - 1 - positions,
    ).to(dtype=torch.long)
    aligned_images = images.index_select(0, frame_indices)

    target_audio_samples = _ceil_div(
        target_frame_count * sample_rate * fps_denominator,
        fps_numerator,
    )
    if audio_samples < target_audio_samples:
        silence_shape = list(waveform.shape)
        silence_shape[-1] = target_audio_samples - audio_samples
        silence = torch.zeros(silence_shape, dtype=waveform.dtype, device=waveform.device)
        aligned_waveform = torch.cat((waveform, silence), dim=-1)
    else:
        aligned_waveform = waveform

    aligned_audio = dict(audio)
    aligned_audio["waveform"] = aligned_waveform
    duration = target_frame_count / float(fps_fraction)
    return aligned_images, aligned_audio, target_frame_count, duration


class SimpAIPingPongVideoAudioAlign(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SimpAIPingPongVideoAudioAlign",
            category="SimpAI/video",
            inputs=[
                io.Image.Input("images"),
                io.Audio.Input("audio"),
                io.Float.Input("fps", default=25.0, min=0.01, max=120.0, step=0.01),
            ],
            outputs=[
                io.Image.Output(display_name="aligned_images"),
                io.Audio.Output(display_name="aligned_audio"),
                io.Int.Output(display_name="frame_count"),
                io.Float.Output(display_name="duration"),
            ],
        )

    @classmethod
    def execute(cls, images, audio, fps=25.0):
        return io.NodeOutput(*align_video_and_audio(images, audio, fps))


NODE_CLASS_MAPPINGS = {
    "SimpAIPingPongVideoAudioAlign": SimpAIPingPongVideoAudioAlign,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIPingPongVideoAudioAlign": "SimpAI Ping-Pong Video / Audio Align",
}
