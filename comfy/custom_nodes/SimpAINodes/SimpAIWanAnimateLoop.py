from __future__ import annotations

import json

import torch


_TAIL_GUARD_FRAMES = 4
_BACKGROUND_CALIBRATION_STRENGTH = 1.0
_BACKGROUND_CALIBRATION_MAX_LUMA_SCALE = 0.10
_BACKGROUND_CALIBRATION_MAX_LUMA_SHIFT = 0.08
_BACKGROUND_CALIBRATION_MAX_CHROMA_SHIFT = 0.05
_BACKGROUND_CALIBRATION_MIN_SAMPLES = 32


def _node_result(value):
    if hasattr(value, "result"):
        return tuple(value.result or ())
    if isinstance(value, tuple):
        return value
    return (value,)


def _align_4n1(value):
    value = max(1, int(value))
    return value + ((1 - value) % 4)


def _sample(model, positive, negative, sampler, sigmas, latent, seed, cfg):
    from comfy_extras.nodes_custom_sampler import SamplerCustom

    sampled = _node_result(
        SamplerCustom.execute(
            model,
            True,
            int(seed),
            float(cfg),
            positive,
            negative,
            sampler,
            sigmas,
            latent,
        )
    )
    if not sampled:
        raise RuntimeError("SamplerCustom returned no latent output.")
    result = sampled[1] if len(sampled) > 1 else sampled[0]
    if not isinstance(result, dict) or "samples" not in result:
        raise RuntimeError("SamplerCustom returned an invalid latent output.")
    return result


def _trim_latent(latent, amount):
    amount = max(0, int(amount))
    if amount == 0:
        return latent
    trimmed = latent.copy()
    trimmed["samples"] = latent["samples"][:, :, amount:].contiguous()
    return trimmed


def _decode(vae, latent):
    import nodes

    return nodes.VAEDecode().decode(vae, latent)[0].detach().cpu().contiguous().clamp(0, 1)


def _prepare_edit_mask(character_mask, start, count, frames):
    if not isinstance(character_mask, torch.Tensor) or character_mask.numel() == 0:
        return None

    mask = character_mask.detach()
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    elif mask.ndim == 4:
        if mask.shape[-1] <= 4:
            mask = mask[..., 0]
        elif mask.shape[1] <= 4:
            mask = mask[:, 0]
    if mask.ndim != 3 or int(mask.shape[0]) == 0:
        return None

    count = max(1, int(count))
    start = max(0, int(start))
    if int(mask.shape[0]) == 1:
        mask = mask.repeat(count, 1, 1)
    elif start < int(mask.shape[0]):
        mask = mask[start : start + count]
        if int(mask.shape[0]) < count:
            mask = torch.cat((mask, mask[-1:].repeat(count - int(mask.shape[0]), 1, 1)), dim=0)
    else:
        mask = mask[-1:].repeat(count, 1, 1)

    import torch.nn.functional as F

    mask = mask.unsqueeze(1).to(device=frames.device, dtype=torch.float32)
    if mask.shape[-2:] != frames.shape[1:3]:
        mask = F.interpolate(mask, size=frames.shape[1:3], mode="bilinear", align_corners=False)
    return mask.movedim(1, -1).clamp(0, 1).contiguous()


def _prepare_reference_frames(driving_video, start, count, frames):
    reference = _slice_condition_window(
        driving_video,
        start,
        count,
        int(driving_video.shape[0]),
        repeat_single=True,
    )
    if not isinstance(reference, torch.Tensor) or reference.ndim != 4 or int(reference.shape[-1]) < 3:
        return None

    import torch.nn.functional as F

    reference = reference[..., :3].to(device=frames.device, dtype=torch.float32)
    if reference.shape[1:3] != frames.shape[1:3]:
        reference = F.interpolate(
            reference.movedim(-1, 1),
            size=frames.shape[1:3],
            mode="bilinear",
            align_corners=False,
        ).movedim(1, -1)
    return reference.contiguous()


def _rgb_to_ycbcr(rgb):
    red, green, blue = rgb.unbind(dim=-1)
    luma = red * 0.299 + green * 0.587 + blue * 0.114
    cb = (blue - luma) / 1.772
    cr = (red - luma) / 1.402
    return luma, cb, cr


def _calibrate_to_original_background(frames, reference, edit_mask, strength=None):
    strength = (
        _BACKGROUND_CALIBRATION_STRENGTH if strength is None else float(strength)
    )
    if not isinstance(edit_mask, torch.Tensor):
        return frames, {"applied": False, "reason": "missing_character_mask"}
    if (
        not isinstance(reference, torch.Tensor)
        or reference.shape[:3] != frames.shape[:3]
        or int(reference.shape[-1]) < 3
    ):
        return frames, {"applied": False, "reason": "missing_original_frames"}

    import torch.nn.functional as F

    # The expanded mask is used only to reject boundary pixels from the statistics.
    margin = max(1, min(8, int(round(min(frames.shape[1:3]) * 0.01))))
    time_step = max(1, (int(frames.shape[0]) + 15) // 16)
    sample_height = min(64, int(frames.shape[1]))
    sample_width = min(64, int(frames.shape[2]))
    sample_size = (sample_height, sample_width)
    generated_rgb = F.adaptive_avg_pool2d(
        frames[::time_step, ..., :3].movedim(-1, 1).to(torch.float32),
        sample_size,
    ).movedim(1, -1)
    original_rgb = F.adaptive_avg_pool2d(
        reference[::time_step, ..., :3]
        .movedim(-1, 1)
        .to(device=frames.device, dtype=torch.float32),
        sample_size,
    ).movedim(1, -1)
    sampled_edit_mask = F.adaptive_max_pool2d(
        edit_mask[::time_step].movedim(-1, 1).to(torch.float32),
        sample_size,
    )
    sample_margin = max(
        1,
        (margin * sample_height + int(frames.shape[1]) - 1) // int(frames.shape[1]),
        (margin * sample_width + int(frames.shape[2]) - 1) // int(frames.shape[2]),
    )
    expanded_edit_mask = F.max_pool2d(
        sampled_edit_mask,
        kernel_size=sample_margin * 2 + 1,
        stride=1,
        padding=sample_margin,
    ).movedim(1, -1)
    unchanged = expanded_edit_mask[..., 0] <= 0.01

    generated_luma, generated_cb, generated_cr = _rgb_to_ycbcr(generated_rgb)
    original_luma, original_cb, original_cr = _rgb_to_ycbcr(original_rgb)
    valid = unchanged
    valid &= torch.isfinite(generated_rgb).all(dim=-1)
    valid &= torch.isfinite(original_rgb).all(dim=-1)
    valid &= (generated_luma > 0.005) & (generated_luma < 0.995)
    valid &= (original_luma > 0.005) & (original_luma < 0.995)
    sample_count = int(valid.sum())
    if sample_count < _BACKGROUND_CALIBRATION_MIN_SAMPLES:
        return frames, {
            "applied": False,
            "reason": "insufficient_unchanged_background",
            "sample_count": sample_count,
            "mask_used_for_statistics_only": True,
        }

    generated_luma = generated_luma[valid]
    original_luma = original_luma[valid]
    generated_luma_median = generated_luma.median()
    original_luma_median = original_luma.median()
    generated_luma_mad = (generated_luma - generated_luma_median).abs().median()
    original_luma_mad = (original_luma - original_luma_median).abs().median()
    if float(generated_luma_mad) > 0.005 and float(original_luma_mad) > 0.005:
        requested_luma_scale = original_luma_mad / generated_luma_mad
    else:
        requested_luma_scale = torch.ones_like(generated_luma_mad)
    requested_luma_scale = requested_luma_scale.clamp(
        1.0 - _BACKGROUND_CALIBRATION_MAX_LUMA_SCALE,
        1.0 + _BACKGROUND_CALIBRATION_MAX_LUMA_SCALE,
    )
    requested_luma_shift = (
        original_luma - generated_luma * requested_luma_scale
    ).median().clamp(
        -_BACKGROUND_CALIBRATION_MAX_LUMA_SHIFT,
        _BACKGROUND_CALIBRATION_MAX_LUMA_SHIFT,
    )
    requested_chroma_shift = torch.stack(
        (
            (original_cb[valid] - generated_cb[valid]).median(),
            (original_cr[valid] - generated_cr[valid]).median(),
        )
    ).clamp(
        -_BACKGROUND_CALIBRATION_MAX_CHROMA_SHIFT,
        _BACKGROUND_CALIBRATION_MAX_CHROMA_SHIFT,
    )

    applied_luma_scale = 1.0 + (requested_luma_scale - 1.0) * strength
    applied_luma_shift = requested_luma_shift * strength
    applied_chroma_shift = requested_chroma_shift * strength

    corrected = frames.clone()
    full_rgb = frames[..., :3].to(torch.float32)
    luma_delta = (
        full_rgb[..., 0] * 0.299
        + full_rgb[..., 1] * 0.587
        + full_rgb[..., 2] * 0.114
    ) * (applied_luma_scale - 1.0) + applied_luma_shift
    luma_delta = luma_delta.to(frames.dtype)
    cb_shift = float(applied_chroma_shift[0].detach().cpu())
    cr_shift = float(applied_chroma_shift[1].detach().cpu())
    corrected[..., 0].add_(luma_delta).add_(1.402 * cr_shift)
    corrected[..., 1].add_(luma_delta).add_(-0.344136 * cb_shift - 0.714136 * cr_shift)
    corrected[..., 2].add_(luma_delta).add_(1.772 * cb_shift)
    corrected[..., :3].clamp_(0, 1)
    return corrected.contiguous(), {
        "applied": True,
        "sample_count": sample_count,
        "mask_used_for_statistics_only": True,
        "mask_margin_pixels": margin,
        "strength": float(strength),
        "luma_scale": float(applied_luma_scale.detach().cpu()),
        "luma_shift": float(applied_luma_shift.detach().cpu()),
        "chroma_shift": [
            float(value) for value in applied_chroma_shift.detach().cpu()
        ],
    }


def _slice_condition_window(value, start, length, source_limit, repeat_single=False):
    if not isinstance(value, torch.Tensor) or value.ndim == 0 or int(value.shape[0]) == 0:
        return value

    available = min(int(value.shape[0]), max(1, int(source_limit)))
    source = value[:available]
    start = max(0, int(start))
    length = max(1, int(length))

    if available == 1 and not repeat_single:
        return source if start == 0 else None
    if start < available:
        window = source[start : start + length]
    else:
        window = source[-1:]
    if int(window.shape[0]) < length:
        window = torch.cat(
            (window, window[-1:].repeat((length - int(window.shape[0]),) + (1,) * (window.ndim - 1))),
            dim=0,
        )
    return window.contiguous()


def _replace_output_tail(output, replacement):
    remaining = int(replacement.shape[0])
    replacement_end = remaining
    for frames in reversed(output):
        if remaining <= 0:
            break
        take = min(remaining, int(frames.shape[0]))
        replacement_start = replacement_end - take
        frames[-take:] = replacement[replacement_start:replacement_end]
        remaining -= take
        replacement_end = replacement_start
    if remaining != 0:
        raise RuntimeError("Wan Animate overlap exceeds the available output frames.")


def _output_tail(output, count):
    remaining = max(0, int(count))
    pieces = []
    for frames in reversed(output):
        if remaining <= 0:
            break
        take = min(remaining, int(frames.shape[0]))
        pieces.insert(0, frames[-take:])
        remaining -= take
    if not pieces:
        return None
    return torch.cat(pieces, dim=0).contiguous()


def _blend_output_overlap(output, current_overlap):
    count = int(current_overlap.shape[0])
    if count <= 0:
        return 0
    previous_overlap = _output_tail(output, count)
    if previous_overlap is None or int(previous_overlap.shape[0]) != count:
        raise RuntimeError("Wan Animate overlap exceeds the available output frames.")
    if count == 1:
        weights = torch.ones((1, 1, 1, 1), device=current_overlap.device, dtype=torch.float32)
    else:
        weights = torch.linspace(0.0, 1.0, count, device=current_overlap.device, dtype=torch.float32)
        weights = (weights * weights * (3.0 - 2.0 * weights)).view(count, 1, 1, 1)
    blended = torch.lerp(
        previous_overlap.to(torch.float32),
        current_overlap.to(torch.float32),
        weights,
    ).to(previous_overlap.dtype)
    _replace_output_tail(output, blended.contiguous())
    return count


class SimpAIWanAnimateLoop:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "sampler": ("SAMPLER",),
                "sigmas": ("SIGMAS",),
                "reference_image": ("IMAGE",),
                "driving_video": ("IMAGE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 16384, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 16384, "step": 16}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1}),
                "max_frames": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1}),
                "max_chunk_frames": ("INT", {"default": 77, "min": 17, "max": 97, "step": 4}),
                "overlap_frames": ("INT", {"default": 5, "min": 1, "max": 33, "step": 4}),
            },
            "optional": {
                "face_video": ("IMAGE",),
                "pose_video": ("IMAGE",),
                "background_video": ("IMAGE",),
                "character_mask": ("MASK",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("frames", "summary")
    FUNCTION = "generate"
    CATEGORY = "SimpAI/video"

    def generate(
        self,
        model,
        positive,
        negative,
        vae,
        sampler,
        sigmas,
        reference_image,
        driving_video,
        width,
        height,
        seed,
        cfg,
        max_frames,
        max_chunk_frames,
        overlap_frames,
        face_video=None,
        pose_video=None,
        background_video=None,
        character_mask=None,
    ):
        if not isinstance(driving_video, torch.Tensor) or driving_video.ndim != 4:
            raise ValueError("driving_video must be a ComfyUI IMAGE tensor.")
        if not isinstance(reference_image, torch.Tensor) or reference_image.ndim != 4 or reference_image.shape[0] == 0:
            raise ValueError("reference_image must contain at least one image.")

        from comfy_extras.nodes_wan import WanAnimateToVideo

        total_frames = int(driving_video.shape[0])
        if int(max_frames) > 0:
            total_frames = min(total_frames, int(max_frames))
        if total_frames <= 0:
            raise ValueError("driving_video has no frames to generate.")

        chunk_limit = min(97, _align_4n1(max_chunk_frames))
        overlap = min(
            _align_4n1(overlap_frames),
            33,
            chunk_limit - _TAIL_GUARD_FRAMES - 4,
        )
        produced = 0
        chunk_index = 0
        previous_frames = None
        output = []
        chunks = []

        while produced < total_frames:
            has_previous = previous_frames is not None
            discard_head = overlap if has_previous else 0
            max_keep = chunk_limit - discard_head - _TAIL_GUARD_FRAMES
            if max_keep <= 0:
                raise RuntimeError("Wan Animate chunk has no room for output frames.")
            keep_target = min(total_frames - produced, max_keep)
            generate_length = _align_4n1(
                discard_head + keep_target + _TAIL_GUARD_FRAMES
            )
            generate_length = min(generate_length, chunk_limit)
            continuation = previous_frames[-overlap:].contiguous() if has_previous else None
            source_start = max(0, produced - discard_head)
            conditioning_offset = discard_head if has_previous else 0
            chunk_face_video = _slice_condition_window(
                face_video,
                source_start,
                generate_length,
                total_frames,
            )
            chunk_pose_video = _slice_condition_window(
                pose_video,
                source_start,
                generate_length,
                total_frames,
            )
            chunk_background_video = _slice_condition_window(
                background_video,
                source_start,
                generate_length,
                total_frames,
            )
            chunk_character_mask = _slice_condition_window(
                character_mask,
                source_start,
                generate_length,
                total_frames,
                repeat_single=True,
            )

            conditioned = _node_result(
                WanAnimateToVideo.execute(
                    positive=positive,
                    negative=negative,
                    vae=vae,
                    width=int(width),
                    height=int(height),
                    length=int(generate_length),
                    batch_size=1,
                    continue_motion_max_frames=int(overlap),
                    video_frame_offset=int(conditioning_offset),
                    reference_image=reference_image[:1],
                    face_video=chunk_face_video,
                    pose_video=chunk_pose_video,
                    background_video=chunk_background_video,
                    character_mask=chunk_character_mask,
                    continue_motion=continuation,
                )
            )
            if len(conditioned) != 6:
                raise RuntimeError("WanAnimateToVideo returned an unexpected result.")
            chunk_positive, chunk_negative, latent, trim_latent, _trim_image, _next_offset = conditioned
            sampled = _sample(
                model,
                chunk_positive,
                chunk_negative,
                sampler,
                sigmas,
                latent,
                int(seed),
                cfg,
            )
            decoded = _decode(vae, _trim_latent(sampled, trim_latent))
            required_frames = discard_head + keep_target + _TAIL_GUARD_FRAMES
            if int(decoded.shape[0]) < required_frames:
                raise RuntimeError(
                    "Wan Animate chunk did not produce enough tail guard frames."
                )
            kept_end = discard_head + keep_target
            usable = decoded[:kept_end].contiguous()
            if int(usable.shape[0]) <= discard_head:
                raise RuntimeError("Wan Animate chunk produced no usable frames.")
            discard_tail = int(decoded.shape[0]) - kept_end

            edit_mask = _prepare_edit_mask(
                character_mask,
                source_start,
                int(usable.shape[0]),
                usable,
            )
            original_frames = _prepare_reference_frames(
                driving_video,
                source_start,
                int(usable.shape[0]),
                usable,
            )
            usable, calibration_summary = _calibrate_to_original_background(
                usable,
                original_frames,
                edit_mask,
            )

            blend_frames = 0
            if discard_head > 0:
                blend_frames = _blend_output_overlap(output, usable[:discard_head].contiguous())
            kept = usable[discard_head:kept_end].contiguous()

            output.append(kept)
            produced += int(kept.shape[0])
            previous_frames = _output_tail(output, overlap)
            chunks.append(
                {
                    "chunk": chunk_index,
                    "generate_length": int(generate_length),
                    "discard": int(discard_head),
                    "discard_tail": int(discard_tail),
                    "kept": int(kept.shape[0]),
                    "produced": int(produced),
                    "source_start": int(source_start),
                    "next_offset": int(source_start + generate_length),
                    "blend_frames": int(blend_frames),
                    "background_calibration": calibration_summary,
                }
            )
            chunk_index += 1

        frames = torch.cat(output, dim=0)[:total_frames].contiguous()
        summary = json.dumps(
            {
                "total_frames": total_frames,
                "width": int(width),
                "height": int(height),
                "max_chunk_frames": chunk_limit,
                "overlap_frames": overlap,
                "tail_guard_frames": _TAIL_GUARD_FRAMES,
                "seed_strategy": "fixed_per_video",
                "background_calibration": {
                    "enabled": True,
                    "reference": "time_aligned_driving_video_outside_character_mask",
                    "applies_to": "whole_chunk",
                    "pixel_compositing": False,
                    "strength": _BACKGROUND_CALIBRATION_STRENGTH,
                    "max_luma_scale": _BACKGROUND_CALIBRATION_MAX_LUMA_SCALE,
                    "max_luma_shift": _BACKGROUND_CALIBRATION_MAX_LUMA_SHIFT,
                    "max_chroma_shift": _BACKGROUND_CALIBRATION_MAX_CHROMA_SHIFT,
                },
                "chunks": chunks,
            },
            ensure_ascii=False,
        )
        return frames, summary


NODE_CLASS_MAPPINGS = {
    "SimpAIWanAnimateLoop": SimpAIWanAnimateLoop,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIWanAnimateLoop": "SimpAI Wan Animate Loop",
}
