import torch
import torch.nn.functional as F

import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview


def _as_spatial_batch(tensor):
    if tensor.ndim == 4:
        return tensor, None
    if tensor.ndim == 5:
        batch, channels, frames, height, width = tensor.shape
        spatial = tensor.permute(0, 2, 1, 3, 4).reshape(batch * frames, channels, height, width)
        return spatial, (batch, frames)
    raise ValueError(f"SimpAILatentDetailSampler expects a 4D or 5D latent, got {tensor.ndim}D")


def _restore_spatial_batch(tensor, layout):
    if layout is None:
        return tensor
    batch, frames = layout
    _, channels, height, width = tensor.shape
    return tensor.reshape(batch, frames, channels, height, width).permute(0, 2, 1, 3, 4)


def _box_blur(tensor, kernel_size):
    padding = kernel_size // 2
    padded = F.pad(tensor, (padding, padding, padding, padding), mode="replicate")
    return F.avg_pool2d(padded, kernel_size=kernel_size, stride=1)


def _detail_update(prediction, previous_prediction, previous_focus, sampling_noise, detail_strength, texture_strength, focus_persistence, schedule):
    prediction_2d, layout = _as_spatial_batch(prediction)
    blurred = _box_blur(prediction_2d, 3)
    high_frequency = prediction_2d - blurred
    activity = high_frequency.abs().mean(dim=1, keepdim=True)

    if previous_prediction is not None:
        previous_2d, _ = _as_spatial_batch(previous_prediction)
        activity = activity + (prediction_2d - previous_2d).abs().mean(dim=1, keepdim=True) * 0.35

    activity = _box_blur(activity, 5)
    centered = activity - activity.mean(dim=(-2, -1), keepdim=True)
    scale = centered.square().mean(dim=(-2, -1), keepdim=True).sqrt().clamp_min(1e-6)
    focus = torch.sigmoid(centered / scale * 1.25)
    focus = _box_blur(focus, 3)

    if previous_focus is not None:
        focus = previous_focus * focus_persistence + focus * (1.0 - focus_persistence)

    update = high_frequency * focus * (detail_strength * 0.12 * schedule)
    if texture_strength > 0.0:
        noise_2d, _ = _as_spatial_batch(sampling_noise)
        texture = noise_2d - _box_blur(noise_2d, 3)
        texture_scale = texture.square().mean(dim=(-2, -1), keepdim=True).sqrt().clamp_min(1e-6)
        update = update + texture / texture_scale * focus * (texture_strength * 0.006 * schedule)

    return _restore_spatial_batch(update, layout), focus


class SimpAILatentDetailSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF, "control_after_generate": True}),
                "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
                "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS,),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "latent_image": ("LATENT",),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "enhance_detail": ("BOOLEAN", {"default": True}),
                "detail_strength": ("FLOAT", {"default": 0.25, "min": 0.0, "max": 2.0, "step": 0.01}),
                "texture_strength": ("FLOAT", {"default": 0.05, "min": 0.0, "max": 1.0, "step": 0.01}),
                "focus_persistence": ("FLOAT", {"default": 0.65, "min": 0.0, "max": 0.95, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "sample"
    CATEGORY = "SimpAI/sampling"
    DESCRIPTION = "Enhances spatial detail in active latent regions before the next denoising step."

    def sample(
        self,
        model,
        seed,
        steps,
        cfg,
        sampler_name,
        scheduler,
        positive,
        negative,
        latent_image,
        denoise,
        enhance_detail,
        detail_strength,
        texture_strength,
        focus_persistence,
    ):
        latent_dict = latent_image.copy()
        latent = comfy.sample.fix_empty_latent_channels(
            model,
            latent_dict["samples"],
            latent_dict.get("downscale_ratio_spacial"),
            latent_dict.get("downscale_ratio_temporal"),
        )
        batch_indices = latent_dict.get("batch_index")
        noise = comfy.sample.prepare_noise(latent, seed, batch_indices)
        noise_mask = latent_dict.get("noise_mask")
        preview_callback = latent_preview.prepare_callback(model, steps)

        previous_prediction = None
        previous_focus = None
        detail_noise = None
        enabled = bool(enhance_detail and (detail_strength > 0.0 or texture_strength > 0.0))

        def detail_callback(step, prediction, current, total_steps):
            nonlocal previous_prediction, previous_focus, detail_noise

            # The final sampler callback has no later model pass to integrate an update.
            if enabled and step < total_steps - 1:
                if detail_noise is None:
                    detail_noise = noise.to(device=current.device, dtype=current.dtype)
                schedule = ((total_steps - step - 1) / max(total_steps - 1, 1)) ** 0.5
                update, previous_focus = _detail_update(
                    prediction,
                    previous_prediction,
                    previous_focus,
                    detail_noise,
                    detail_strength,
                    texture_strength,
                    focus_persistence,
                    schedule,
                )
                current.add_(update)
                previous_prediction = prediction.detach()

            preview_callback(step, prediction, current, total_steps)

        samples = comfy.sample.sample(
            model,
            noise,
            steps,
            cfg,
            sampler_name,
            scheduler,
            positive,
            negative,
            latent,
            denoise=denoise,
            disable_noise=False,
            start_step=None,
            last_step=None,
            force_full_denoise=False,
            noise_mask=noise_mask,
            callback=detail_callback,
            disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
            seed=seed,
        )

        output = latent_dict.copy()
        output.pop("downscale_ratio_spacial", None)
        output.pop("downscale_ratio_temporal", None)
        output["samples"] = samples
        return (output,)


NODE_CLASS_MAPPINGS = {
    "SimpAILatentDetailSampler": SimpAILatentDetailSampler,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAILatentDetailSampler": "SimpAI Latent Detail Sampler",
}
