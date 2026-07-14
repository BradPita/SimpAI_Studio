from comfy_execution.graph_utils import GraphBuilder


_FAMILY_DEFAULTS = {
    "anima": {
        "beta": 15.0,
        "high_scale_start": 0.0,
        "high_scale_end": 0.5,
        "low_scale_start": 0.9,
        "rf_verbose": True,
        "untwisting_verbose": False,
    },
    "flux2": {
        "beta": 2.5,
        "high_scale_start": 1.0,
        "high_scale_end": 0.0,
        "low_scale_start": 1.0,
        "rf_verbose": True,
        "untwisting_verbose": False,
    },
    "qwen": {
        "beta": 2.5,
        "high_scale_start": 1.0,
        "high_scale_end": 0.0,
        "low_scale_start": 1.0,
        "rf_verbose": False,
        "untwisting_verbose": False,
    },
    "z_image": {
        "beta": 2.5,
        "high_scale_start": 1.0,
        "high_scale_end": 0.0,
        "low_scale_start": 1.0,
        "rf_verbose": False,
        "untwisting_verbose": True,
    },
}

_UNOFFICIAL_EXTENSION_DEFAULTS = {
    "post_attention_adain_strength": 0.5,
    "axis0_rope_mode": "match_axes",
    "axis0_rope_scale": 1.0,
    "cosine_gated_v_injection": 0.5,
    "variance_gated_v_adain": 1.0,
    "key_subspace_alignment": 0.1,
}

_DEFAULT_LOW_SCALE_END = 1.4


class SimpAIAIOStyleTransfer:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",), "positive": ("CONDITIONING",), "vae": ("VAE",),
            "reference_1": ("SIMPAI_AIO_REFERENCE_CONFIG",), "reference_2": ("SIMPAI_AIO_REFERENCE_CONFIG",),
            "reference_3": ("SIMPAI_AIO_REFERENCE_CONFIG",), "reference_4": ("SIMPAI_AIO_REFERENCE_CONFIG",),
            "family": (["anima", "flux2", "qwen", "z_image"],),
            "width": ("INT", {"default": 1024, "min": 16, "max": 32768, "step": 16}),
            "height": ("INT", {"default": 1024, "min": 16, "max": 32768, "step": 16}),
        }}

    RETURN_TYPES = ("MODEL", "BOOLEAN")
    RETURN_NAMES = ("model", "active")
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/Reference"

    def expand(self, model, positive, vae, reference_1, reference_2, reference_3, reference_4, family, width, height):
        references = [r for r in (reference_1, reference_2, reference_3, reference_4) if int(r.get("mode", 0)) == 1]
        if not references:
            return (model, False)
        graph = GraphBuilder()
        weights = [max(0.0, float(r.get("weight", 0.7))) for r in references]
        if sum(weights) <= 0.0:
            weights = [1.0] * len(references)
        latents = []
        for reference in references:
            scaled = graph.node("ImageScale", image=reference["image"], upscale_method="lanczos",
                                width=int(width), height=int(height), crop="center")
            latents.append(graph.node("VAEEncode", pixels=scaled.out(0), vae=vae).out(0))
        merged = latents[0]
        cumulative = weights[0]
        for latent, weight in zip(latents[1:], weights[1:]):
            factor = weight / (cumulative + weight)
            merged = graph.node("LatentBlend", samples1=merged, samples2=latent, blend_factor=factor).out(0)
            cumulative += weight
        rf = graph.node("RFInversion", model=model, reference_latent=merged, ref_conditioning=positive,
                        rf_mode="flowturbo_pc", gamma=0.5, pmi_alpha=0.0, otip_strength=0.0,
                        otip_clip_norm=20.0, verbose=_FAMILY_DEFAULTS[family]["rf_verbose"])
        strength = max(weights)
        defaults = _FAMILY_DEFAULTS[family]
        extensions = graph.node("UnofficialExtensions", **_UNOFFICIAL_EXTENSION_DEFAULTS)
        patched = graph.node("UntwistingRoPE", model=rf.out(0), rf_inversion=rf.out(1),
                             beta=defaults["beta"],
                             high_scale_start=defaults["high_scale_start"],
                             high_scale_end=defaults["high_scale_end"],
                             low_scale_start=defaults["low_scale_start"],
                             low_scale_end=min(_DEFAULT_LOW_SCALE_END, strength * 2.0),
                             adain_strength=0.5, blocks="0-999",
                             verbose=defaults["untwisting_verbose"],
                             unofficial_extensions=extensions.out(0))
        return {"result": (patched.out(0), True), "expand": graph.finalize()}


NODE_CLASS_MAPPINGS = {"SimpAIAIOStyleTransfer": SimpAIAIOStyleTransfer}
NODE_DISPLAY_NAME_MAPPINGS = {"SimpAIAIOStyleTransfer": "SimpAI AIO ImagePrompt Style Transfer"}
