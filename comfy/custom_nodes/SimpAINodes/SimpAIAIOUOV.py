from comfy.samplers import SAMPLER_NAMES, SCHEDULER_NAMES
from comfy_execution.graph_utils import GraphBuilder


class _SimpAIAIOUOVBase:
    FAMILY = "base"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {"lazy": True}),
                "positive": ("CONDITIONING", {"lazy": True}),
                "negative": ("CONDITIONING", {"lazy": True}),
                "vae": ("VAE", {"lazy": True}),
                "upscale_model": ("UPSCALE_MODEL", {"lazy": True}),
                "uov": ("SIMPAI_AIO_UOV_CONFIG",),
                "seed": ("INT", {"default": 0, "min": 0, "max": 1125899906842624}),
                "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0}),
                "sampler_name": (SAMPLER_NAMES,),
                "scheduler": (SCHEDULER_NAMES,),
            },
            "optional": {
                "progress_node_id": ("STRING", {"default": ""}),
                "denoise": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/UOV"

    def check_lazy_status(self, model, positive, negative, vae, upscale_model, uov, seed, steps, cfg, sampler_name, scheduler, progress_node_id="", denoise=-1.0):
        mode = int(uov.get("mode", 0))
        if mode <= 0:
            return []
        if mode == 1:
            required = ("upscale_model",)
        elif mode in (2, 3):
            required = ("model", "positive", "negative", "vae")
        else:
            required = ("model", "positive", "negative", "vae", "upscale_model")
        values = {
            "model": model,
            "positive": positive,
            "negative": negative,
            "vae": vae,
            "upscale_model": upscale_model,
        }
        return [name for name in required if values[name] is None]

    def expand(self, model, positive, negative, vae, upscale_model, uov, seed, steps, cfg, sampler_name, scheduler, progress_node_id="", denoise=-1.0):
        mode = int(uov.get("mode", 0))
        image = uov["image"]
        if mode <= 0:
            return (image,)

        graph = GraphBuilder()
        multiple = float(uov.get("multiple", 1.5))
        denoise_override = float(denoise)
        if mode == 1:
            upscaled = graph.node("ImageUpscaleWithModel", upscale_model=upscale_model, image=image)
            scaled = graph.node("ImageScaleBy", image=upscaled.out(0), upscale_method="lanczos", scale_by=multiple)
            output = scaled.out(0)
        elif mode in (2, 3):
            effective_denoise = denoise_override if denoise_override >= 0.0 else (0.5 if mode == 2 else 0.85)
            encoded = graph.node("VAEEncode", pixels=image, vae=vae)
            sampled = graph.node(
                "KSampler",
                model=model,
                positive=positive,
                negative=negative,
                latent_image=encoded.out(0),
                seed=seed,
                steps=steps,
                cfg=cfg,
                sampler_name=sampler_name,
                scheduler=scheduler,
                denoise=effective_denoise,
            )
            if progress_node_id:
                sampled.set_override_display_id(progress_node_id)
            decoded = graph.node("VAEDecode", samples=sampled.out(0), vae=vae)
            output = decoded.out(0)
        else:
            tiled = graph.node(
                "UltimateSDUpscale",
                image=image,
                model=model,
                positive=positive,
                negative=negative,
                vae=vae,
                upscale_model=upscale_model,
                upscale_by=multiple,
                seed=seed,
                steps=int(uov.get("tile_steps", steps)),
                cfg=cfg,
                sampler_name=sampler_name,
                scheduler=scheduler,
                denoise=denoise_override if denoise_override >= 0.0 else 0.5,
                mode_type="Chess",
                tile_width=int(uov.get("tile_width", 1024)),
                tile_height=int(uov.get("tile_height", 1024)),
                mask_blur=64 if self.FAMILY in ("sdxl", "wan") else 32,
                tile_padding=128,
                seam_fix_mode="None",
                seam_fix_denoise=1.0,
                seam_fix_width=64,
                seam_fix_mask_blur=8,
                seam_fix_padding=16,
                force_uniform_tiles=True,
                tiled_decode=False,
            )
            if progress_node_id:
                tiled.set_override_display_id(progress_node_id)
            output = tiled.out(0)

        return {"result": (output,), "expand": graph.finalize()}


def _family_node(name, family):
    return type(name, (_SimpAIAIOUOVBase,), {"FAMILY": family})


SimpAIAIOUOVFlux = _family_node("SimpAIAIOUOVFlux", "flux")
SimpAIAIOUOVSDXL = _family_node("SimpAIAIOUOVSDXL", "sdxl")
SimpAIAIOUOVQwen = _family_node("SimpAIAIOUOVQwen", "qwen")
SimpAIAIOUOVWan = _family_node("SimpAIAIOUOVWan", "wan")
SimpAIAIOUOVZImage = _family_node("SimpAIAIOUOVZImage", "z_image")
SimpAIAIOUOVFlux2 = _family_node("SimpAIAIOUOVFlux2", "flux2")


class SimpAIAIOUOVAnima(_SimpAIAIOUOVBase):
    FAMILY = "anima"

    def expand(self, model, positive, negative, vae, upscale_model, uov, seed, steps, cfg, sampler_name, scheduler, progress_node_id="", denoise=-1.0):
        if int(uov.get("mode", 0)) != 4:
            return super().expand(model, positive, negative, vae, upscale_model, uov, seed, steps, cfg, sampler_name, scheduler, progress_node_id, denoise)
        graph = GraphBuilder()
        patched = graph.node("AnimaLLLiteApply", model=model, lllite_name="animaTileRepair_v20.safetensors",
                             image=uov["image"], strength=1.0, start_percent=0.0, end_percent=1.0, preserve_wrapper=True)
        tiled = graph.node("UltimateSDUpscale", image=uov["image"], model=patched.out(0), positive=positive,
                           negative=negative, vae=vae, upscale_model=upscale_model, upscale_by=float(uov.get("multiple", 1.5)),
                           seed=seed, steps=int(uov.get("tile_steps", steps)), cfg=cfg, sampler_name=sampler_name,
                           scheduler=scheduler, denoise=float(denoise) if float(denoise) >= 0.0 else 0.5,
                           mode_type="Chess", tile_width=int(uov.get("tile_width", 1024)),
                           tile_height=int(uov.get("tile_height", 1024)), mask_blur=32, tile_padding=128,
                           seam_fix_mode="None", seam_fix_denoise=1.0, seam_fix_width=64, seam_fix_mask_blur=8,
                           seam_fix_padding=16, force_uniform_tiles=True, tiled_decode=False)
        if progress_node_id:
            tiled.set_override_display_id(progress_node_id)
        return {"result": (tiled.out(0),), "expand": graph.finalize()}


class SimpAIAIOUOVChenkin(_SimpAIAIOUOVBase):
    FAMILY = "sdxl"

    @classmethod
    def INPUT_TYPES(cls):
        types = super().INPUT_TYPES()
        types["optional"]["tile_control_net"] = ("CONTROL_NET", {"lazy": True})
        return types

    def check_lazy_status(self, model, positive, negative, vae, upscale_model, uov, seed, steps, cfg,
                          sampler_name, scheduler, progress_node_id="", denoise=-1.0, tile_control_net=None):
        missing = super().check_lazy_status(model, positive, negative, vae, upscale_model, uov, seed, steps,
                                            cfg, sampler_name, scheduler, progress_node_id, denoise)
        if int(uov.get("mode", 0)) == 4 and tile_control_net is None:
            missing.append("tile_control_net")
        return missing

    def expand(self, model, positive, negative, vae, upscale_model, uov, seed, steps, cfg, sampler_name,
               scheduler, progress_node_id="", denoise=-1.0, tile_control_net=None):
        if int(uov.get("mode", 0)) != 4:
            return super().expand(model, positive, negative, vae, upscale_model, uov, seed, steps, cfg,
                                  sampler_name, scheduler, progress_node_id, denoise)
        graph = GraphBuilder()
        applied = graph.node("ControlNetApplyAdvanced", positive=positive, negative=negative,
                             control_net=tile_control_net, image=uov["image"], vae=vae, strength=0.3,
                             start_percent=0.0, end_percent=1.0)
        tiled = graph.node("UltimateSDUpscale", image=uov["image"], model=model, positive=applied.out(0),
                           negative=applied.out(1), vae=vae, upscale_model=upscale_model,
                           upscale_by=float(uov.get("multiple", 1.5)), seed=seed,
                           steps=int(uov.get("tile_steps", steps)), cfg=cfg, sampler_name=sampler_name,
                           scheduler=scheduler, denoise=float(denoise) if float(denoise) >= 0.0 else 0.5,
                           mode_type="Chess",
                           tile_width=int(uov.get("tile_width", 1024)), tile_height=int(uov.get("tile_height", 1024)),
                           mask_blur=64, tile_padding=128, seam_fix_mode="None", seam_fix_denoise=1.0,
                           seam_fix_width=64, seam_fix_mask_blur=8, seam_fix_padding=16,
                           force_uniform_tiles=True, tiled_decode=False)
        if progress_node_id:
            tiled.set_override_display_id(progress_node_id)
        return {"result": (tiled.out(0),), "expand": graph.finalize()}


NODE_CLASS_MAPPINGS = {
    cls.__name__: cls for cls in (
        SimpAIAIOUOVFlux,
        SimpAIAIOUOVSDXL,
        SimpAIAIOUOVQwen,
        SimpAIAIOUOVWan,
        SimpAIAIOUOVZImage,
        SimpAIAIOUOVFlux2,
        SimpAIAIOUOVAnima,
        SimpAIAIOUOVChenkin,
    )
}


NODE_DISPLAY_NAME_MAPPINGS = {
    name: name.replace("SimpAIAIO", "SimpAI AIO ") for name in NODE_CLASS_MAPPINGS
}
