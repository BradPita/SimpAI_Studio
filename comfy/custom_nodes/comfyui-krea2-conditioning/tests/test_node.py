"""Contract + end-to-end tests for the Krea 2 Conditioning Control node.

Validates the node the way ComfyUI loads and runs it: import as a custom-node
package, the ComfyUI node contract (INPUT_TYPES / RETURN_TYPES / FUNCTION /
CATEGORY), and execution on realistic Krea 2-shaped conditioning (shape, RMS
magnitude, presets, parsing, structure-safe passthrough, pipeline insertion).

Run:  pytest tests/ -v      (or:  python tests/test_node.py)
"""
import importlib.util
import os
import sys

import pytest
import torch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import nodes  # noqa: E402

TAPS, TAP_DIM = 12, 2560


def _cond(batch=1, seq=77, extras=None):
    return [[torch.randn(batch, seq, TAPS * TAP_DIM), dict(extras or {})]]


def _rms(t):
    return t.pow(2).mean().sqrt().item()


# --- import + ComfyUI contract -------------------------------------------------

def test_nodes_module_importable():
    for attr in ("ConditioningKrea2Rebalance", "PRESET_WEIGHTS", "PRESET_NAMES", "parse_weights"):
        assert hasattr(nodes, attr), f"nodes.{attr} missing"


def test_init_loads_as_comfyui_package():
    """Import __init__.py the way ComfyUI discovers a custom node (as a package)."""
    pkg = "ck2c_test_pkg"
    spec = importlib.util.spec_from_file_location(
        pkg, os.path.join(REPO, "__init__.py"),
        submodule_search_locations=[REPO],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg] = mod
    spec.loader.exec_module(mod)
    assert "ConditioningKrea2Rebalance" in mod.NODE_CLASS_MAPPINGS
    assert "ConditioningKrea2Rebalance" in mod.NODE_DISPLAY_NAME_MAPPINGS


def test_node_contract():
    cls = nodes.ConditioningKrea2Rebalance
    assert "required" in cls.INPUT_TYPES()
    for attr in ("RETURN_TYPES", "RETURN_NAMES", "FUNCTION", "CATEGORY"):
        assert hasattr(cls, attr), f"node missing {attr}"
    assert cls.RETURN_TYPES == ("CONDITIONING",)
    assert cls.FUNCTION == "rebalance"
    assert callable(getattr(cls, cls.FUNCTION))


def test_input_types_and_defaults():
    req = nodes.ConditioningKrea2Rebalance.INPUT_TYPES()["required"]
    assert req["conditioning"][0] == "CONDITIONING"
    assert req["preset"][0] == nodes.PRESET_NAMES
    assert req["multiplier"][1]["default"] == 1.0
    assert req["renormalize"][1]["default"] is True


# --- presets + parsing ---------------------------------------------------------

def test_presets_all_twelve_taps():
    for name, weights in nodes.PRESET_WEIGHTS.items():
        assert len(weights) == 12, f"{name} has {len(weights)} taps"
        assert all(isinstance(w, (int, float)) for w in weights)
    assert "custom" in nodes.PRESET_NAMES
    for p in ("balanced", "detail", "subtle", "uniform"):
        assert p in nodes.PRESET_WEIGHTS


def test_parse_weights_valid():
    assert nodes.parse_weights("1, 2, 3") == [1.0, 2.0, 3.0]
    assert nodes.parse_weights("1.5;2.5;3.5") == [1.5, 2.5, 3.5]


def test_parse_weights_invalid():
    for bad in ("", "1", "1,oops,3", None):
        with pytest.raises(ValueError):
            nodes.parse_weights(bad)


# --- execution + math ----------------------------------------------------------

def test_rebalance_preserves_shape():
    out = nodes.ConditioningKrea2Rebalance().rebalance(_cond(batch=2, seq=77))[0]
    assert out[0][0].shape == (2, 77, TAPS * TAP_DIM)


def test_renormalize_holds_magnitude():
    c = _cond()
    in_rms = _rms(c[0][0])
    out = nodes.ConditioningKrea2Rebalance().rebalance(c, multiplier=1.0)[0]
    assert _rms(out[0][0]) == pytest.approx(in_rms, rel=0.01)


def test_multiplier_is_sole_magnitude_control():
    c = _cond()
    in_rms = _rms(c[0][0])
    out = nodes.ConditioningKrea2Rebalance().rebalance(c, multiplier=2.0)[0]  # renormalize default True
    assert _rms(out[0][0]) == pytest.approx(2.0 * in_rms, rel=0.01)


def test_legacy_mode_inflates():
    c = _cond()
    in_rms = _rms(c[0][0])
    out = nodes.ConditioningKrea2Rebalance().rebalance(c, multiplier=4.0, renormalize=False)[0]
    assert _rms(out[0][0]) > 5.0 * in_rms  # ~8.7x with balanced weights — the flaw the default avoids


def test_extras_preserved_structure_safe():
    pooled = torch.randn(1, 768)
    mask = torch.ones(1, 77)
    c = [[torch.randn(1, 77, TAPS * TAP_DIM), {"pooled_output": pooled, "mask": mask}]]
    out = nodes.ConditioningKrea2Rebalance().rebalance(c)[0]
    assert torch.equal(out[0][1]["pooled_output"], pooled)  # untouched
    assert torch.equal(out[0][1]["mask"], mask)  # untouched
    assert out[0][0].shape == (1, 77, TAPS * TAP_DIM)


def test_e2e_pipeline_insertion():
    """Encode -> [this node] -> sampler-prep: output stays a valid conditioning structure."""
    encoded = _cond(batch=1, seq=77, extras={"pooled_output": torch.randn(1, 768)})
    for preset in ("balanced", "detail", "subtle", "uniform"):
        out = nodes.ConditioningKrea2Rebalance().rebalance(encoded, preset=preset)[0]
        assert isinstance(out, list) and isinstance(out[0], list)
        assert out[0][0].shape == (1, 77, TAPS * TAP_DIM)
        assert torch.isfinite(out[0][0]).all()


if __name__ == "__main__":
    # Standalone runner (no pytest needed): collect test_* and run.
    failed = 0
    glb = globals()
    for name in sorted(n for n in glb if n.startswith("test_")):
        try:
            glb[name]()
            print(f"PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{'ALL PASS' if not failed else f'{failed} FAILED'}")
    sys.exit(1 if failed else 0)
