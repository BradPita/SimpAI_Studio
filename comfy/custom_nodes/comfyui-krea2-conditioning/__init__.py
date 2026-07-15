"""ComfyUI custom node: Krea 2 conditioning rebalance."""
try:
    from .nodes import (
        PRESET_NAMES,
        PRESET_WEIGHTS,
        ConditioningKrea2Rebalance,
        parse_weights,
    )
except ImportError:  # imported outside a package context (e.g. by pytest collection)
    from nodes import (
        PRESET_NAMES,
        PRESET_WEIGHTS,
        ConditioningKrea2Rebalance,
        parse_weights,
    )

NODE_CLASS_MAPPINGS = {
    "ConditioningKrea2Rebalance": ConditioningKrea2Rebalance,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ConditioningKrea2Rebalance": "🎛️ Krea 2 Conditioning Control",
}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "ConditioningKrea2Rebalance",
    "PRESET_WEIGHTS",
    "PRESET_NAMES",
    "parse_weights",
]

__version__ = "1.0.0"
