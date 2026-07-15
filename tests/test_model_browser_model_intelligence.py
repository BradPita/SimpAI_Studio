import importlib.util
import json
import struct
import sys
import types
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_service():
    import modules

    config_stub = types.ModuleType("modules.config")
    config_stub.path_models_root = str(ROOT / "models")
    config_stub.get_path_models_root = lambda: config_stub.path_models_root
    config_stub.model_cata_map = {}
    config_stub.ARCH_FAMILY_ALGO = 4
    flags_stub = types.ModuleType("modules.flags")

    previous_config = sys.modules.get("modules.config")
    previous_flags = sys.modules.get("modules.flags")
    previous_config_attr = getattr(modules, "config", None)
    previous_flags_attr = getattr(modules, "flags", None)
    sys.modules["modules.config"] = config_stub
    sys.modules["modules.flags"] = flags_stub
    modules.config = config_stub
    modules.flags = flags_stub
    try:
        spec = importlib.util.spec_from_file_location(
            "model_browser_service_model_intelligence_test",
            ROOT / "modules" / "model_browser_service.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_config is None:
            sys.modules.pop("modules.config", None)
            delattr(modules, "config")
        else:
            sys.modules["modules.config"] = previous_config
            modules.config = previous_config_attr
        if previous_flags is None:
            sys.modules.pop("modules.flags", None)
            delattr(modules, "flags")
        else:
            sys.modules["modules.flags"] = previous_flags
            modules.flags = previous_flags_attr


SERVICE = load_service()


def test_embedded_safetensors_hashes_are_read_in_priority_order(tmp_path):
    sha256 = "a" * 64
    blake3 = "b" * 64
    header = json.dumps(
        {
            "__metadata__": {
                "modelspec.hash.blake3": blake3,
                "modelspec.hash.sha256": sha256,
                "duplicate_hash": sha256,
            },
            "tensor": {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]},
        }
    ).encode("utf-8")
    model = tmp_path / "model.safetensors"
    model.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")

    assert SERVICE._read_safetensors_embedded_hashes(str(model)) == [
        {"hash": sha256, "algorithm": "sha256", "key": "modelspec.hash.sha256"},
        {"hash": blake3, "algorithm": "blake3", "key": "modelspec.hash.blake3"},
    ]


def test_anomalous_sidecar_is_normalized_for_model_browser():
    sha256 = "c" * 64
    normalized = SERVICE._normalize_external_sidecar(
        {
            "id": 22,
            "modelId": 11,
            "name": "Version 2",
            "baseModel": "Illustrious",
            "trainedWords": ["hero", "hero", "style"],
            "description": "<p>Version <b>description</b></p>",
            "model": {
                "name": "Example Model",
                "type": "LORA",
                "creator": {"username": "alice"},
                "tags": ["anime", {"name": "character"}],
            },
            "files": [{"hashes": {"SHA256": sha256.upper()}}],
        },
        "example.civitai.info",
    )

    assert normalized["sha256"] == sha256
    assert normalized["model_name"] == "Example Model"
    assert normalized["version_name"] == "Version 2"
    assert normalized["base_model"] == "Illustrious"
    assert normalized["creator"] == "alice"
    assert normalized["description"] == "Version description"
    assert normalized["trained_words"] == ["hero", "style"]
    assert normalized["tags"] == ["anime", "character"]
    assert normalized["civitai_url"] == "https://civitai.com/models/11?modelVersionId=22"


def test_civitai_base_model_names_map_to_studio_families():
    cases = {
        "SD 1.5": "sdxl",
        "Illustrious": "sdxl",
        "Stable Diffusion 3.5": "sd3",
        "Flux.1 D": "flux",
        "Wan Video 2.2": "wan",
        "LTXV 2": "ltx2",
        "Qwen Image": "qwen",
        "Z-Image Turbo": "z_image",
        "Hunyuan Video": "hunyuan",
        "Anima Preview": "anima",
    }
    assert {name: SERVICE._arch_family_from_base_model(name) for name in cases} == cases


def test_civitai_hash_candidates_continue_after_not_found(monkeypatch):
    missing = "d" * 64
    found = "e" * 64
    calls = []

    def fake_fetch(file_hash):
        calls.append(file_hash)
        if file_hash == missing:
            raise urllib.error.HTTPError("https://civitai.test", 404, "missing", {}, None)
        return {"id": 7, "files": [{"hashes": {"SHA256": found}}]}

    monkeypatch.setattr(SERVICE, "_fetch_civitai_model_version", fake_fetch)
    remote, matched, attempted = SERVICE._try_civitai_hash_candidates(
        [
            {"hash": missing, "algorithm": "blake3", "source": "safetensors-header"},
            {"hash": found, "algorithm": "sha256", "source": "computed"},
        ]
    )

    assert remote["id"] == 7
    assert matched["hash"] == found
    assert [item["hash"] for item in attempted] == [missing, found]
    assert calls == [missing, found]


def test_hash_stamp_detects_replaced_model_file(tmp_path):
    model = tmp_path / "model.ckpt"
    model.write_bytes(b"first")
    metadata = {"hash_file_stamp": SERVICE._hash_stamp_for_model_path(str(model))}
    assert SERVICE._hash_stamp_is_current(metadata, str(model))

    model.write_bytes(b"replacement payload")
    assert not SERVICE._hash_stamp_is_current(metadata, str(model))


def test_fetch_metadata_uses_header_match_without_full_file_hash(tmp_path, monkeypatch):
    header_hash = "f" * 64
    canonical_sha256 = "1" * 64
    model = tmp_path / "fast.safetensors"
    model.write_bytes(b"model")
    item = {
        "type": "base",
        "name": "fast.safetensors",
        "path": str(model),
        "path_exists": True,
        "remote_enabled": True,
        "synthetic": False,
        "sha256": "",
        "hash_source": "missing",
    }
    persisted = {}
    saved = {}

    monkeypatch.setattr(SERVICE, "_resolve_single_item", lambda payload: dict(item))
    monkeypatch.setattr(SERVICE, "is_model_path_allowed", lambda path: True)
    monkeypatch.setattr(
        SERVICE,
        "_read_safetensors_embedded_hashes",
        lambda path: [{"hash": header_hash, "algorithm": "blake3", "key": "modelspec.hash.blake3"}],
    )
    monkeypatch.setattr(
        SERVICE,
        "_fetch_civitai_model_version",
        lambda value: {
            "id": 9,
            "name": "Fast Version",
            "baseModel": "Flux.1 D",
            "files": [{"hashes": {"SHA256": canonical_sha256.upper()}}],
            "model": {"id": 8, "name": "Fast Model", "type": "Checkpoint"},
            "images": [],
        },
    )
    monkeypatch.setattr(SERVICE, "_merge_civitai_model_detail", lambda remote: remote)
    monkeypatch.setattr(
        SERVICE,
        "_ensure_item_sha256",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full SHA256 should not run")),
    )
    monkeypatch.setattr(
        SERVICE,
        "_persist_hash_for_item",
        lambda model_item, sha256, source: persisted.update(sha256=sha256, source=source),
    )
    monkeypatch.setattr(SERVICE, "_architecture_manageable_item", lambda model_item: False)
    monkeypatch.setattr(SERVICE, "find_preview_path", lambda path: "")
    monkeypatch.setattr(SERVICE, "_save_sidecar", lambda path, metadata: saved.update(metadata))
    monkeypatch.setattr(SERVICE, "_load_models_info", lambda: {})
    monkeypatch.setattr(
        SERVICE,
        "_item_from_choice",
        lambda model_type, name, data: dict(item, sha256=canonical_sha256, preview_url=""),
    )

    result = SERVICE.fetch_metadata({"type": "base", "name": item["name"]})

    assert result["ok"]
    assert result["remote_found"]
    assert result["hash_lookup"]["hash"] == header_hash
    assert persisted == {"sha256": canonical_sha256, "source": "civitai-header-match"}
    assert saved["model_name"] == "Fast Model"
    assert saved["version_name"] == "Fast Version"
    assert saved["base_model"] == "Flux.1 D"
