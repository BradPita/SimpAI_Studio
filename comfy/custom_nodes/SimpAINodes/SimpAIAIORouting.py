import torch


class SimpAIAIOImageRoute:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "function": ("INT", {"default": 1, "min": 0, "max": 3, "step": 1}),
                "generated": ("IMAGE", {"lazy": True}),
                "uov": ("IMAGE", {"lazy": True}),
                "inpaint": ("IMAGE", {"lazy": True}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "select"
    CATEGORY = "SimpAI/AIO"

    @staticmethod
    def _selected_input(function):
        return {2: "uov", 3: "inpaint"}.get(int(function), "generated")

    def check_lazy_status(self, function, generated=None, uov=None, inpaint=None):
        selected = self._selected_input(function)
        if {"generated": generated, "uov": uov, "inpaint": inpaint}[selected] is None:
            return [selected]
        return []

    def select(self, function, generated=None, uov=None, inpaint=None):
        selected = self._selected_input(function)
        if selected == "uov":
            return (uov,)
        if selected == "inpaint":
            return (inpaint,)
        return (generated,)


class SimpAIAIOOutputBatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "original": ("IMAGE",),
                "enhanced": ("IMAGE",),
                "enhance_active": ("BOOLEAN", {"default": False}),
                "save_final_only": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "combine"
    CATEGORY = "SimpAI/AIO"

    def combine(self, original, enhanced, enhance_active, save_final_only):
        if not enhance_active:
            return (original,)
        if save_final_only:
            return (enhanced,)
        if original.shape[1:] != enhanced.shape[1:]:
            return (enhanced,)
        return (torch.cat((original, enhanced), dim=0),)


NODE_CLASS_MAPPINGS = {
    "SimpAIAIOImageRoute": SimpAIAIOImageRoute,
    "SimpAIAIOOutputBatch": SimpAIAIOOutputBatch,
}


NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIAIOImageRoute": "SimpAI AIO Image Route",
    "SimpAIAIOOutputBatch": "SimpAI AIO Output Batch",
}
