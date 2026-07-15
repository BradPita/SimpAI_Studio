# 🎛️ ComfyUI Krea 2 Conditioning Control

**Quality-preserving per-layer conditioning control for Krea 2 — rebalance the 12 Qwen3-VL taps without the artifacts and likeness drift the ×4 default introduces.**

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)
![ComfyUI](https://img.shields.io/badge/ComfyUI-custom%20node-7b3fce.svg)
![Krea 2](https://img.shields.io/badge/Krea%202-Raw%20%7C%20Turbo-fa8c16.svg)

A single, fast ComfyUI node that gives you direct control over the multi-layer text conditioning Krea 2 feeds to its denoiser — and does it **without the quality collapse the original "rebalance" approach can cause when pushed.**

> Forked from — and crediting — [`nova452/ComfyUI-ConditioningKrea2Rebalance`](https://github.com/nova452/ComfyUI-ConditioningKrea2Rebalance) (Apache-2.0), which introduced the per-layer-weighting idea. This fork fixes its main flaw (below), adds presets, and hardens the engineering.

---

## The problem this fixes

The original rebalance node reweights Krea 2's 12 Qwen3-VL conditioning taps — then hits the *entire* tensor with a global **multiplier** (default `4.0`). The two compound: with the default weights the conditioning magnitude is inflated **~8.7×** (`4×` multiplier × ~`2.2×` from the per-layer gains). That doesn't just "boost" — it destabilises the conditioning. That magnitude blowup is the setup-independent part; *how it presents* depends on your setup. Some report it as **oversaturation**. In **our** tests (Krea 2 Turbo) it showed up as **skin artifacts (scarring + a birthmark-style spot) and likeness drift (a younger face, head and body tilt)**, with no visible saturation shift. We're not claiming oversaturation doesn't occur — only that in our setup the dominant symptom was different. Either way the root cause is the same inflated magnitude, and the rebalance works against itself.

This node flips the default: **RMS-renormalised per-layer rebalancing.** It shifts the *ratios* between taps (boost the deep detail layers relative to the shallow ones) while **holding the overall conditioning magnitude constant** — so the denoiser sees a rebalanced signal rather than an inflated one (in our tests: no artifacts, no likeness drift).

## Proof — real A/B on Krea 2 Turbo

Same prompt, same seed (`123`), 8-step Turbo. The **only** difference is the conditioning node.

![Krea 2 Turbo A/B — baseline / quality mode / legacy ×4](assets/krea2_ab_trio.png)

| variant | mean diff vs baseline | what actually changed (human eye) |
|---|---|---|
| **our quality mode** (`renormalize=true`, `multiplier=1.0`) | **8.0 / 255** — 96.9% similar | stays true to baseline — clean, no artifacts |
| **legacy ×4** (`renormalize=false`, `multiplier=4.0` = nova default) | **21.8 / 255** — 91.4% | skin scarring + a birthmark-style spot, a younger face, head and body tilt |

In this test there was **no visible saturation shift** between the three — but that's just our test (Turbo, 8 steps), not a claim that oversaturation never occurs. It's a commonly reported symptom on other setups (Raw, different weights, quantisation); here the magnitude blowup presented as **artifacts and likeness drift** instead. Renormalising holds the magnitude — which is the part that actually matters.

*Reproduced on a second, independent render* (a different prompt at 1024² / 8-step Turbo): **10.2 / 255 — 96.0% similar**, still clean. The quality-preserving behaviour is prompt-stable, not a one-off.

## Why it works

Krea 2 doesn't condition on a single text embedding. Its DiT runs a small **`txtfusion`** module that turns **12 selected Qwen3-VL hidden-state layers** (packed as `(B, seq, 12·2560)`) into one refined embedding, in three stages [(mapped by fblissjr, verified against the code)](https://github.com/fblissjr/krea-explorations): **(1) layerwise blocks** — cross-*layer* attention where the 12 taps attend across the layer axis and **L20 is the hub** every layer attends to; **(2) projector** — a learned `Linear(12 → 1)` collapse whose weights are **contrastive** (positive on the mid layers, peak **L14**; negative on the deep ones **L23/26/29/32**) — roughly "mid minus deep"; **(3) refiner blocks** — cross-*token* self-attention that refines the now-single embedding per token before the DiT sees it. The deep detail is **actively subtracted** at stage 2 — the mechanism behind the under-representation.

This node **intervenes upstream of all three stages**: it reshapes the packed tensor to expose the layer axis and reweights each tap before `txtfusion` runs, boosting the deep taps to recover what the projector will subtract. Because that boost is then re-mixed through the L20-centric layerwise attention, its effect is indirect and gentle — a 5× deep-tap boost shifts the image only ~10/255 — which is why this is the forgiving lever. The [weight-space alternative](https://github.com/fblissjr/krea-explorations) edits the projector (stage 2) directly and reaches a comparable magnitude at ~⅛ the strength; different insertion point relative to the L20 re-mix, so the two read as complementary (see [Related work](#related-work)).

```
 conditioning   (B, seq, 12·2560)
      │   reshape to expose the layer axis
      ▼
               (B, seq, 12, 2560)
      │   × per-layer gain   (boost deep taps 7–10)
      ▼
      │   RMS renormalise  → ratios change, magnitude held   ← on by default
      ▼
      │   × global multiplier                                ← 1.0 by default
      ▼
 conditioning   (B, seq, 12·2560)    ← masks & pooled output untouched
```

## Features

- **⚖️ Quality-preserving by default** — RMS renormalise is ON and the global multiplier defaults to `1.0`. Shift tap ratios, hold magnitude. Reproduce the original node's behavior anytime with `renormalize = false`, `multiplier = 4.0`.
- **🎛️ Presets** — `balanced` (the classic profile), `detail`, `subtle`, `uniform`, or `custom`.
- **🧱 Structure-safe** — recurses the ComfyUI CONDITIONING structure; masks, pooled outputs, and arbitrary payloads pass through unchanged.
- **🔢 Tap-agnostic** — defaults target Krea 2's 12 taps, but the math generalises to any multi-layer-tap conditioning.
- **⚡ Zero dependencies** — pure PyTorch, nothing extra to install.

## Install

**ComfyUI Manager** — search `Krea 2 Conditioning` → Install.

**Manual**
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/huwhitememes/comfyui-krea2-conditioning.git
# restart ComfyUI
```

## Node — `🎛️ Krea 2 Conditioning Control`

| Input | Type | Default | Description |
|---|---|---|---|
| `conditioning` | CONDITIONING | — | The text conditioning to rebalance. |
| `preset` | enum | `balanced` | Named per-layer weight profile. `custom` uses `per_layer_weights`. |
| `per_layer_weights` | string | `1, 1, … 4.0` | Comma-separated gains, one per tap (12 for Krea 2). Used only when `preset = custom`. |
| `multiplier` | float | `1.0` | Global gain applied after per-layer weighting. Keep ~1.0 with renormalize on; >1 amplifies the whole tensor and can introduce artifacts/likeliness drift. |
| `renormalize` | boolean | `true` | Hold the input RMS after per-layer weighting — rebalance ratios without inflating magnitude. The quality-preserving mode; on by default. |

### Presets

| Preset | Profile (12 taps, shallow → deep) | Use when |
|---|---|---|
| `balanced` | `1, 1, 1, 1, 1, 1, 1, 2.5, 5.0, 1.1, 4.0, 1.0` | Default starting point — the classic profile. |
| `detail` | `0.8, 0.8, 0.9, 0.9, 1.0, 1.0, 1.2, 3.0, 6.0, 1.5, 5.0, 1.2` | Maximum fine-detail adherence. |
| `subtle` | `1, 1, 1, 1, 1, 1, 1, 1.5, 2.0, 1.0, 1.5, 1.0` | The base model only needs a light touch. |
| `uniform` | `1 × 12` | No per-layer change — pair with `multiplier > 1` for a clean global boost. |
| `custom` | *(your weights)* | You know your stack. |

## Tips

- **Start with the default** (`balanced`, `renormalize = true`, `multiplier = 1.0`) — that's pure ratio rebalance with magnitude held. This is where the quality lives.
- **Want it louder?** Raise `multiplier` — but expect artifacts/likeliness drift past ~2–3×.
- **Cleanest A/B against the un-rebalanced conditioning:** `multiplier = 1.0`, `renormalize = true`.
- **Reproduce the original node exactly:** `renormalize = false`, `multiplier = 4.0`.
- Drop the node between your `CLIPTextEncode` (or Krea 2 text encode) and the sampler.

## vs the original Rebalance node

| | Original (nova452) | This fork |
|---|---|---|
| Global multiplier | `4.0` default — amplifies **all** taps | `1.0` default — magnitude held |
| Quality when pushed | destabilises — artifacts + likeness drift | preserved (RMS renormalise) |
| Per-layer control | raw CSV string | presets + custom, validated |
| Typing, parsing, docs | minimal | full |

Full credit to **nova452** for the per-layer-weighting technique.

## Compatibility

- **Krea 2** (Raw / Turbo) — primary target.
- Generalises to any diffusion model that conditions on a flattened multi-layer hidden-state stack; just match the weight count to the tap count.

## Related work

- **nova452 — [`ComfyUI-ConditioningKrea2Rebalance`](https://github.com/nova452/ComfyUI-ConditioningKrea2Rebalance)**: introduced per-layer conditioning reweighting for Krea 2 — the activation-space technique this node refines with magnitude-preserving defaults.
- **fblissjr — [`krea-explorations`](https://github.com/fblissjr/krea-explorations)**: interpretability + a **weight-space** complement. Rather than scaling the conditioning activations, it edits the learned `txtfusion.projector` weight (the `[1,12]` combiner over the taps), and shows that projector is **contrastive** (mid-minus-deep) and that **L20** is a universal attention hub. The two approaches sit at different stages of the pipeline — ours pre-scales the input taps; theirs re-weights the combination — and are combinable.

This node is the activation-space, magnitude-preserving entry in that lineage.

**Cross-tested** (same seed/prompt, Krea 2 Turbo): the activation-space lever is the more forgiving of the two — a 5× deep-tap boost shifts the image ~10/255 and stays coherent, while a 4-band projector-weight edit only reaches a comparable magnitude around strength ~0.1 and breaks by 1.0 (the projector coefficients *are* the combination, so they're ~8× more sensitive). The two read as **complementary, not redundant**.

## Credits

Per-layer conditioning rebalancing technique by **nova452** — [`ComfyUI-ConditioningKrea2Rebalance`](https://github.com/nova452/ComfyUI-ConditioningKrea2Rebalance). This fork extends it with quality-preserving defaults, RMS renormalisation, presets, and hardened parsing.

## License

Apache-2.0. Krea 2 weights are released under the Krea 2 Community License — verify it covers your use case.
