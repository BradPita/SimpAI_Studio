from __future__ import annotations

import json

import torch


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
        overlap = min(_align_4n1(overlap_frames), 33, chunk_limit - 4)
        produced = 0
        chunk_index = 0
        previous_frames = None
        output = []
        chunks = []

        while produced < total_frames:
            has_previous = previous_frames is not None
            keep_target = min(total_frames - produced, chunk_limit if not has_previous else chunk_limit - overlap)
            generate_length = _align_4n1(keep_target + (overlap if has_previous else 0))
            generate_length = min(generate_length, chunk_limit)
            continuation = previous_frames[-overlap:].contiguous() if has_previous else None

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
                    video_frame_offset=int(produced),
                    reference_image=reference_image[:1],
                    face_video=face_video,
                    pose_video=pose_video,
                    background_video=background_video,
                    character_mask=character_mask,
                    continue_motion=continuation,
                )
            )
            if len(conditioned) != 6:
                raise RuntimeError("WanAnimateToVideo returned an unexpected result.")
            chunk_positive, chunk_negative, latent, trim_latent, _trim_image, next_offset = conditioned
            sampled = _sample(
                model,
                chunk_positive,
                chunk_negative,
                sampler,
                sigmas,
                latent,
                int(seed) + chunk_index,
                cfg,
            )
            decoded = _decode(vae, _trim_latent(sampled, trim_latent))
            discard = min(overlap, int(decoded.shape[0])) if has_previous else 0
            kept = decoded[discard : discard + keep_target].contiguous()
            if kept.shape[0] == 0:
                raise RuntimeError("Wan Animate chunk produced no usable frames.")

            output.append(kept)
            produced += int(kept.shape[0])
            previous_frames = torch.cat(output, dim=0)[-overlap:].contiguous()
            chunks.append(
                {
                    "chunk": chunk_index,
                    "generate_length": int(generate_length),
                    "discard": int(discard),
                    "kept": int(kept.shape[0]),
                    "produced": int(produced),
                    "next_offset": int(next_offset),
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
