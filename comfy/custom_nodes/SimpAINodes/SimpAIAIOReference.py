from comfy_execution.graph_utils import GraphBuilder


def _prepare_control_image(graph, image, mode, skip_preprocessor):
    if skip_preprocessor:
        return image
    if mode == 2:
        levels = graph.node(
            "LayerColor: Levels",
            image=image,
            channel="RGB",
            black_point=128,
            white_point=200,
            gray_point=1.0,
            output_black_point=0,
            output_white_point=255,
        )
        return levels.out(0)
    return image


class SimpAIAIOReferenceFlux:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "reference": ("SIMPAI_AIO_REFERENCE_CONFIG",),
            },
            "optional": {
                "control_net": ("CONTROL_NET", {"lazy": True}),
                "style_model": ("STYLE_MODEL", {"lazy": True}),
                "clip_vision": ("CLIP_VISION", {"lazy": True}),
                "pulid_flux": ("PULIDFLUX", {"lazy": True}),
                "eva_clip": ("EVA_CLIP", {"lazy": True}),
                "face_analysis": ("FACEANALYSIS", {"lazy": True}),
            },
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("model", "positive", "negative")
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/Reference"

    def check_lazy_status(self, model, positive, negative, vae, reference, control_net=None, style_model=None, clip_vision=None, pulid_flux=None, eva_clip=None, face_analysis=None):
        mode = int(reference.get("mode", 0))
        required = {
            1: ("style_model", "clip_vision"),
            4: ("pulid_flux", "eva_clip", "face_analysis"),
        }.get(mode, ("control_net",) if mode > 0 else ())
        values = {
            "control_net": control_net,
            "style_model": style_model,
            "clip_vision": clip_vision,
            "pulid_flux": pulid_flux,
            "eva_clip": eva_clip,
            "face_analysis": face_analysis,
        }
        return [name for name in required if values[name] is None]

    def expand(self, model, positive, negative, vae, reference, control_net=None, style_model=None, clip_vision=None, pulid_flux=None, eva_clip=None, face_analysis=None):
        mode = int(reference.get("mode", 0))
        if mode <= 0:
            return (model, positive, negative)
        graph = GraphBuilder()
        image = reference["image"]
        weight = float(reference.get("weight", 0.7))
        stop = float(reference.get("stop_percent", 0.6))
        if mode == 1:
            if style_model is None or clip_vision is None:
                raise ValueError("Flux image prompt requires STYLE_MODEL and CLIP_VISION")
            redux = graph.node(
                "ReduxAdvanced",
                conditioning=positive,
                style_model=style_model,
                clip_vision=clip_vision,
                image=image,
                downsampling_factor=1.5,
                downsampling_function="area",
                mode="keep aspect ratio",
                weight=weight,
                autocrop_margin=0.1,
            )
            outputs = (model, redux.out(0), negative)
        elif mode == 4:
            if pulid_flux is None or eva_clip is None or face_analysis is None:
                raise ValueError("Flux face reference requires PuLID, EVA CLIP and face analysis models")
            pulid = graph.node(
                "ApplyPulidFlux",
                model=model,
                pulid_flux=pulid_flux,
                eva_clip=eva_clip,
                face_analysis=face_analysis,
                image=image,
                weight=weight,
                start_at=0.0,
                end_at=stop,
            )
            outputs = (pulid.out(0), positive, negative)
        else:
            if control_net is None:
                raise ValueError("Flux control reference requires CONTROL_NET")
            control_image = _prepare_control_image(graph, image, mode, bool(reference.get("skip_preprocessor", False)))
            applied = graph.node(
                "ControlNetApplySD3",
                positive=positive,
                negative=negative,
                control_net=control_net,
                vae=vae,
                image=control_image,
                strength=weight * 0.7,
                start_percent=0.0,
                end_percent=stop,
            )
            outputs = (model, applied.out(0), applied.out(1))
        return {"result": outputs, "expand": graph.finalize()}


class SimpAIAIOReferenceFluxNunchaku(SimpAIAIOReferenceFlux):
    @classmethod
    def INPUT_TYPES(cls):
        types = super().INPUT_TYPES()
        types["optional"] = {
            "control_net": ("CONTROL_NET", {"lazy": True}),
            "style_model": ("STYLE_MODEL", {"lazy": True}),
            "clip_vision": ("CLIP_VISION", {"lazy": True}),
            "pulid_pipeline": ("PULID_PIPELINE", {"lazy": True}),
        }
        return types

    def check_lazy_status(self, model, positive, negative, vae, reference, control_net=None, style_model=None, clip_vision=None, pulid_pipeline=None):
        mode = int(reference.get("mode", 0))
        required = {1: ("style_model", "clip_vision"), 4: ("pulid_pipeline",)}.get(
            mode, ("control_net",) if mode > 0 else ()
        )
        values = {"control_net": control_net, "style_model": style_model, "clip_vision": clip_vision, "pulid_pipeline": pulid_pipeline}
        return [name for name in required if values[name] is None]

    def expand(self, model, positive, negative, vae, reference, control_net=None, style_model=None, clip_vision=None, pulid_pipeline=None):
        if int(reference.get("mode", 0)) != 4:
            return super().expand(model, positive, negative, vae, reference, control_net, style_model, clip_vision)
        if pulid_pipeline is None:
            raise ValueError("Nunchaku face reference requires PULID_PIPELINE")
        graph = GraphBuilder()
        applied = graph.node(
            "NunchakuFluxPuLIDApplyV2",
            model=model,
            pulid_pipline=pulid_pipeline,
            image=reference["image"],
            weight=float(reference.get("weight", 0.7)),
            start_at=0.0,
            end_at=float(reference.get("stop_percent", 0.6)),
        )
        return {"result": (applied.out(0), positive, negative), "expand": graph.finalize()}


class SimpAIAIOReferenceSDXL:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "reference": ("SIMPAI_AIO_REFERENCE_CONFIG",),
            },
            "optional": {
                "control_net": ("CONTROL_NET", {"lazy": True}),
                "ipadapter": ("IPADAPTER", {"lazy": True}),
                "clip_vision": ("CLIP_VISION", {"lazy": True}),
            },
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("model", "positive", "negative")
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/Reference"

    def check_lazy_status(self, model, positive, negative, vae, reference, control_net=None, ipadapter=None, clip_vision=None):
        mode = int(reference.get("mode", 0))
        required = ("ipadapter", "clip_vision") if mode == 1 else (("control_net",) if mode > 0 else ())
        values = {"control_net": control_net, "ipadapter": ipadapter, "clip_vision": clip_vision}
        return [name for name in required if values[name] is None]

    def expand(self, model, positive, negative, vae, reference, control_net=None, ipadapter=None, clip_vision=None):
        mode = int(reference.get("mode", 0))
        if mode <= 0:
            return (model, positive, negative)
        graph = GraphBuilder()
        image = reference["image"]
        weight = float(reference.get("weight", 0.7))
        stop = float(reference.get("stop_percent", 0.6))
        if mode == 1:
            if ipadapter is None or clip_vision is None:
                raise ValueError("SDXL image prompt requires IPADAPTER and CLIP_VISION")
            prepared = graph.node("PrepImageForClipVision", image=image, interpolation="LANCZOS", crop_position="center", sharpening=0.0)
            applied = graph.node(
                "IPAdapterAdvanced",
                model=model,
                ipadapter=ipadapter,
                image=prepared.out(0),
                clip_vision=clip_vision,
                weight=weight,
                weight_type="linear",
                combine_embeds="average",
                start_at=0.0,
                end_at=stop,
                embeds_scaling="V only",
            )
            outputs = (applied.out(0), positive, negative)
        else:
            if control_net is None:
                raise ValueError("SDXL control reference requires CONTROL_NET")
            control_image = _prepare_control_image(graph, image, mode, bool(reference.get("skip_preprocessor", False)))
            applied = graph.node(
                "ControlNetApplyAdvanced",
                positive=positive,
                negative=negative,
                control_net=control_net,
                image=control_image,
                vae=vae,
                strength=weight,
                start_percent=0.0,
                end_percent=stop,
            )
            outputs = (model, applied.out(0), applied.out(1))
        return {"result": outputs, "expand": graph.finalize()}


class SimpAIAIOReferenceChenkin(SimpAIAIOReferenceSDXL):
    @classmethod
    def INPUT_TYPES(cls):
        types = super().INPUT_TYPES()
        types["optional"] = {
            "line_control_net": ("CONTROL_NET", {"lazy": True}),
            "depth_control_net": ("CONTROL_NET", {"lazy": True}),
            "pose_control_net": ("CONTROL_NET", {"lazy": True}),
            "ipadapter": ("IPADAPTER", {"lazy": True}),
            "clip_vision": ("CLIP_VISION", {"lazy": True}),
        }
        return types

    def check_lazy_status(self, model, positive, negative, vae, reference, line_control_net=None,
                          depth_control_net=None, pose_control_net=None, ipadapter=None, clip_vision=None):
        mode = int(reference.get("mode", 0))
        required = {
            1: ("ipadapter", "clip_vision"),
            2: ("line_control_net",),
            3: ("depth_control_net",),
            5: ("pose_control_net",),
        }.get(mode, ())
        values = locals()
        return [name for name in required if values[name] is None]

    def expand(self, model, positive, negative, vae, reference, line_control_net=None,
               depth_control_net=None, pose_control_net=None, ipadapter=None, clip_vision=None):
        mode = int(reference.get("mode", 0))
        if mode <= 0 or mode == 4:
            return (model, positive, negative)
        control_net = {2: line_control_net, 3: depth_control_net, 5: pose_control_net}.get(mode)
        return super().expand(model, positive, negative, vae, reference, control_net, ipadapter, clip_vision)


class SimpAIAIOReferenceQwen:
    @classmethod
    def INPUT_TYPES(cls):
        return SimpAIAIOReferenceSDXL.INPUT_TYPES()

    RETURN_TYPES = SimpAIAIOReferenceSDXL.RETURN_TYPES
    RETURN_NAMES = SimpAIAIOReferenceSDXL.RETURN_NAMES
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/Reference"

    def check_lazy_status(self, model, positive, negative, vae, reference, control_net=None, ipadapter=None, clip_vision=None):
        mode = int(reference.get("mode", 0))
        if mode > 0 and mode not in (1, 4) and control_net is None:
            return ["control_net"]
        return []

    def expand(self, model, positive, negative, vae, reference, control_net=None, ipadapter=None, clip_vision=None):
        mode = int(reference.get("mode", 0))
        if mode <= 0 or mode in (1, 4):
            return (model, positive, negative)
        if control_net is None:
            raise ValueError("Qwen control reference requires CONTROL_NET")
        graph = GraphBuilder()
        image = _prepare_control_image(graph, reference["image"], mode, bool(reference.get("skip_preprocessor", False)))
        applied = graph.node(
            "ControlNetApplySD3",
            positive=positive,
            negative=negative,
            control_net=control_net,
            vae=vae,
            image=image,
            strength=float(reference.get("weight", 0.7)) * 1.5,
            start_percent=0.0,
            end_percent=float(reference.get("stop_percent", 0.6)),
        )
        return {"result": (model, applied.out(0), applied.out(1)), "expand": graph.finalize()}


class SimpAIAIOReferenceWan:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "reference": ("SIMPAI_AIO_REFERENCE_CONFIG",),
                "latent": ("LATENT",),
                "width": ("INT", {"default": 1024, "min": 16, "max": 32768, "step": 16}),
                "height": ("INT", {"default": 1024, "min": 16, "max": 32768, "step": 16}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/Reference"

    def expand(self, positive, negative, vae, reference, latent, width, height):
        if int(reference.get("mode", 0)) <= 0:
            return (positive, negative, latent)
        graph = GraphBuilder()
        conditioned = graph.node(
            "WanVaceToVideo",
            positive=positive,
            negative=negative,
            vae=vae,
            width=width,
            height=height,
            length=1,
            batch_size=1,
            strength=float(reference.get("weight", 1.0)),
            control_video=reference["image"],
        )
        return {"result": (conditioned.out(0), conditioned.out(1), conditioned.out(2)), "expand": graph.finalize()}


class SimpAIAIOReferenceAnima:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "positive": ("CONDITIONING",), "negative": ("CONDITIONING",),
                             "vae": ("VAE",), "reference": ("SIMPAI_AIO_REFERENCE_CONFIG",)}}
    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("model", "positive", "negative")
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/Reference"

    def expand(self, model, positive, negative, vae, reference):
        mode = int(reference.get("mode", 0))
        if mode <= 0 or mode in (1, 4):
            return (model, positive, negative)
        graph = GraphBuilder()
        image = _prepare_control_image(graph, reference["image"], mode, bool(reference.get("skip_preprocessor", False)))
        lllite_name = "anima-lllite-pose-1.safetensors" if mode == 5 else "anima-lllite-any-test-like-v2.safetensors"
        patched = graph.node("AnimaLLLiteApply", model=model, lllite_name=lllite_name,
                             image=image, strength=float(reference.get("weight", 0.7)), start_percent=0.0,
                             end_percent=float(reference.get("stop_percent", 0.6)), preserve_wrapper=True)
        return {"result": (patched.out(0), positive, negative), "expand": graph.finalize()}


class SimpAIAIOReferenceFlux2:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "positive": ("CONDITIONING",), "negative": ("CONDITIONING",),
                             "vae": ("VAE",), "reference": ("SIMPAI_AIO_REFERENCE_CONFIG",)}}
    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("model", "positive", "negative")
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/Reference"

    def expand(self, model, positive, negative, vae, reference):
        mode = int(reference.get("mode", 0))
        if mode <= 0 or mode == 1 or mode in (4, 5):
            return (model, positive, negative)
        graph = GraphBuilder()
        image = _prepare_control_image(graph, reference["image"], mode, bool(reference.get("skip_preprocessor", False)))
        latent = graph.node("VAEEncode", pixels=image, vae=vae)
        conditioned = graph.node("ReferenceLatent", conditioning=positive, latent=latent.out(0))
        return {"result": (model, conditioned.out(0), negative), "expand": graph.finalize()}


class SimpAIAIOReferenceZImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "model_patch": ("MODEL_PATCH", {"lazy": True}),
                "reference": ("SIMPAI_AIO_REFERENCE_CONFIG",),
            }
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("model", "positive", "negative")
    FUNCTION = "expand"
    CATEGORY = "SimpAI/AIO/Reference"

    def check_lazy_status(self, model, positive, negative, vae, model_patch, reference):
        mode = int(reference.get("mode", 0))
        if mode > 0 and mode not in (1, 4) and model_patch is None:
            return ["model_patch"]
        return []

    def expand(self, model, positive, negative, vae, model_patch, reference):
        mode = int(reference.get("mode", 0))
        if mode <= 0 or mode in (1, 4):
            return (model, positive, negative)
        graph = GraphBuilder()
        image = _prepare_control_image(graph, reference["image"], mode, bool(reference.get("skip_preprocessor", False)))
        applied = graph.node(
            "ZImageFunControlnet",
            model=model,
            model_patch=model_patch,
            vae=vae,
            image=image,
            strength=float(reference.get("weight", 0.7)),
        )
        return {"result": (applied.out(0), positive, negative), "expand": graph.finalize()}


NODE_CLASS_MAPPINGS = {
    "SimpAIAIOReferenceFlux": SimpAIAIOReferenceFlux,
    "SimpAIAIOReferenceFluxNunchaku": SimpAIAIOReferenceFluxNunchaku,
    "SimpAIAIOReferenceSDXL": SimpAIAIOReferenceSDXL,
    "SimpAIAIOReferenceChenkin": SimpAIAIOReferenceChenkin,
    "SimpAIAIOReferenceQwen": SimpAIAIOReferenceQwen,
    "SimpAIAIOReferenceWan": SimpAIAIOReferenceWan,
    "SimpAIAIOReferenceAnima": SimpAIAIOReferenceAnima,
    "SimpAIAIOReferenceFlux2": SimpAIAIOReferenceFlux2,
    "SimpAIAIOReferenceZImage": SimpAIAIOReferenceZImage,
}


NODE_DISPLAY_NAME_MAPPINGS = {
    name: name.replace("SimpAIAIO", "SimpAI AIO ") for name in NODE_CLASS_MAPPINGS
}
