from __future__ import annotations

import contextlib
import functools
import importlib.util
import inspect
import io
import json
import os
import sys
import types
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import gradio as gr
from gradio.context import Context


ROOT = Path(__file__).resolve().parents[1]
SOURCE_WEBUI_ROOT = ROOT / "forge_neo" / "webui"
SOURCE_EXTENSIONS_ROOT = SOURCE_WEBUI_ROOT / "extensions"
_SOURCE_STUB_MODULE_NAMES = (
    "backend",
    "backend.args",
    "modules",
    "modules.cache",
    "modules.devices",
    "modules.hashes",
    "modules.paths",
    "modules.paths_internal",
    "modules.script_callbacks",
    "modules.scripts",
    "modules.sd_models",
    "modules.shared",
    "modules.ui",
)
_GRADIO6_PATCH_SENTINEL = "_forge_neo_source_ui_gradio6_patch"
_EVENT_NAMES = ("click", "change", "submit", "upload", "select", "clear", "release", "input")
_IGNORED_COMPONENT_KWARGS = {
    "Audio": {"show_download_button"},
    "Button": {"info"},
    "Textbox": {"show_copy_button"},
}
_SOURCE_TEXT_FIELDS = {
    "Button": {"value"},
    "Checkbox": {"label", "info"},
    "CheckboxGroup": {"label", "info"},
    "Dropdown": {"label", "info", "placeholder"},
    "Gallery": {"label"},
    "HTML": {"value"},
    "Markdown": {"value"},
    "Textbox": {"label", "info", "placeholder"},
}
_SOURCE_TEXT_FIRST_ARG_FIELDS = {
    "Accordion": "label",
    "Button": "value",
    "HTML": "value",
    "Markdown": "value",
    "Tab": "label",
    "TabItem": "label",
}


def source_extension_ui_tabs_enabled() -> bool:
    value = str(os.environ.get("FORGE_NEO_SOURCE_EXTENSION_UI_TABS", "") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


class _SafeTextWriter(io.TextIOBase):
    def __init__(self, wrapped: Any):
        self._wrapped = wrapped

    @property
    def encoding(self) -> str:
        return getattr(self._wrapped, "encoding", None) or "utf-8"

    def write(self, text: str) -> int:
        value = str(text)
        try:
            return self._wrapped.write(value)
        except UnicodeEncodeError:
            return self._wrapped.write(value.encode(self.encoding, errors="replace").decode(self.encoding, errors="replace"))

    def flush(self) -> None:
        flush = getattr(self._wrapped, "flush", None)
        if callable(flush):
            with contextlib.suppress(ValueError):
                flush()


@contextlib.contextmanager
def _safe_console() -> Iterator[None]:
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    sys.stdout = _SafeTextWriter(previous_stdout)
    sys.stderr = _SafeTextWriter(previous_stderr)
    try:
        yield
    finally:
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


@contextlib.contextmanager
def _detached_gradio_context() -> Iterator[None]:
    root_block = Context.root_block
    block = Context.block
    token = Context.token
    Context.root_block = None
    Context.block = None
    Context.token = None
    try:
        yield
    finally:
        Context.root_block = root_block
        Context.block = block
        Context.token = token


def _patch_component_init(component_cls: type[Any], ignored_kwargs: set[str]) -> None:
    sentinel = f"{_GRADIO6_PATCH_SENTINEL}_init"
    if getattr(component_cls, sentinel, False):
        return
    original_init = component_cls.__init__

    @functools.wraps(original_init)
    def patched_init(self, *args: Any, **kwargs: Any):
        for key in ignored_kwargs:
            kwargs.pop(key, None)
        return original_init(self, *args, **kwargs)

    patched_init.__signature__ = inspect.signature(original_init)
    component_cls.__init__ = patched_init
    setattr(component_cls, sentinel, True)


def _patch_event_method(component_cls: type[Any], event_name: str) -> None:
    event = getattr(component_cls, event_name, None)
    if not callable(event):
        return
    sentinel = f"{_GRADIO6_PATCH_SENTINEL}_{event_name}"
    if getattr(event, sentinel, False):
        return

    def patched_event(self, *args: Any, **kwargs: Any):
        if "_js" in kwargs and "js" not in kwargs:
            kwargs["js"] = kwargs.pop("_js")
        else:
            kwargs.pop("_js", None)
        return event(self, *args, **kwargs)

    setattr(patched_event, sentinel, True)
    setattr(component_cls, event_name, patched_event)


def ensure_source_gradio6_ui_compat() -> None:
    if not hasattr(gr, "Box"):
        gr.Box = gr.Group

    for component_name, ignored_kwargs in _IGNORED_COMPONENT_KWARGS.items():
        component_cls = getattr(gr, component_name, None)
        if isinstance(component_cls, type):
            _patch_component_init(component_cls, ignored_kwargs)

    for component_cls in {value for value in vars(gr).values() if isinstance(value, type)}:
        for event_name in _EVENT_NAMES:
            _patch_event_method(component_cls, event_name)


def _source_shared_opts() -> types.SimpleNamespace:
    output_dir = ROOT / "outputs"
    option_data = {
        "ch_autov3": False,
        "ch_civiai_api_key": "",
        "ch_clean_html": False,
        "ch_civitai_browser": True,
        "ch_dl_lyco_to_lora": False,
        "ch_dl_webui_metadata": True,
        "ch_download_examples": False,
        "ch_hide_buttons": [],
        "ch_max_size_preview": True,
        "ch_nsfw_threshold": "Blocked",
        "ch_open_url_with_js": True,
        "ch_proxy": "",
    }
    return types.SimpleNamespace(
        data=option_data,
        forge_canvas_plain=False,
        forge_canvas_plain_color="#808080",
        forge_canvas_toolbar_always=False,
        forge_canvas_height=512,
        forge_canvas_consistent_brush=False,
        outdir_samples=str(output_dir),
        outdir_txt2img_samples=str(output_dir / "txt2img-images"),
        outdir_img2img_samples=str(output_dir / "img2img-images"),
        outdir_extras_samples=str(output_dir / "extras-images"),
        add_option=lambda *args, **kwargs: None,
        onchange=lambda *args, **kwargs: None,
    )


def _ensure_root_module(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        module.__path__ = [str(SOURCE_WEBUI_ROOT / name.replace(".", os.sep))]
        sys.modules[name] = module
    return module


def _install_module(name: str, module: types.ModuleType) -> None:
    sys.modules[name] = module
    if "." in name:
        parent_name, child_name = name.rsplit(".", 1)
        parent = _ensure_root_module(parent_name)
        setattr(parent, child_name, module)


def _snapshot_source_stub_modules() -> dict[str, tuple[types.ModuleType | None, dict[str, Any]]]:
    snapshot: dict[str, tuple[types.ModuleType | None, dict[str, Any]]] = {}
    for name in _SOURCE_STUB_MODULE_NAMES:
        module = sys.modules.get(name)
        attrs: dict[str, Any] = {}
        if module is not None:
            for attr in ("__path__", "cache", "devices", "hashes", "paths", "paths_internal", "script_callbacks", "scripts", "sd_models", "shared", "ui", "args"):
                if hasattr(module, attr):
                    attrs[attr] = getattr(module, attr)
        snapshot[name] = (module, attrs)
    return snapshot


def _restore_source_stub_modules(snapshot: dict[str, tuple[types.ModuleType | None, dict[str, Any]]]) -> None:
    for name in reversed(_SOURCE_STUB_MODULE_NAMES):
        module, attrs = snapshot.get(name, (None, {}))
        if module is None:
            sys.modules.pop(name, None)
            continue
        sys.modules[name] = module
        for attr in ("__path__", "cache", "devices", "hashes", "paths", "paths_internal", "script_callbacks", "scripts", "sd_models", "shared", "ui", "args"):
            if attr in attrs:
                setattr(module, attr, attrs[attr])
            elif hasattr(module, attr):
                delattr(module, attr)


class _ScriptCallbacksModule(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("modules.script_callbacks")
        self.on_ui_tabs = self._noop
        self.on_app_started = self._noop

    @staticmethod
    def _noop(callback: Callable[..., Any] | None = None, **kwargs: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Callable[..., None]:
        if name.startswith("on_"):
            return self._noop
        raise AttributeError(name)


def _source_prompt_component(prompt_components: Mapping[str, Any] | None, key: str, elem_id: str) -> Any:
    if prompt_components is not None:
        component = prompt_components.get(key)
        if component is not None:
            return component
    return gr.Textbox(value="", visible=False, render=False, elem_id=elem_id)


def _source_runtime_lang(prompt_components: Mapping[str, Any] | None) -> str:
    value: Any = None
    if prompt_components is not None:
        value = prompt_components.get("lang")
        if isinstance(value, Mapping):
            value = value.get("__lang")
    raw = str(value or "").strip().lower()
    return "en" if raw.startswith("en") else "cn"


def _source_translation_map(prompt_components: Mapping[str, Any] | None) -> Mapping[str, str]:
    if prompt_components is None:
        return {}
    mapping = prompt_components.get("source_i18n")
    if not isinstance(mapping, Mapping):
        return {}
    normalized: dict[str, str] = {}
    for key, value in mapping.items():
        if isinstance(key, str) and isinstance(value, str):
            normalized[key] = value
            normalized[_source_text_key(key)] = value
    return normalized


def _source_text_key(value: str) -> str:
    return " ".join(value.split())


def _source_translate_text(value: Any, translations: Mapping[str, str]) -> Any:
    if not isinstance(value, str) or not translations:
        return value
    return translations.get(value) or translations.get(_source_text_key(value)) or value


def _source_runtime_arg(name: str) -> Any:
    args_manager = sys.modules.get("args_manager")
    args = getattr(args_manager, "args", None)
    return getattr(args, name, None) if args is not None else None


def _source_path_to_abs(value: Any) -> str | None:
    if not isinstance(value, (str, os.PathLike)):
        return None
    raw = os.path.expandvars(os.path.expanduser(str(value).strip()))
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    try:
        return str(path.resolve())
    except (OSError, RuntimeError, ValueError):
        return str(path.absolute())


def _source_path_values(value: Any) -> list[str]:
    if isinstance(value, (str, os.PathLike)):
        path = _source_path_to_abs(value)
        return [path] if path else []
    if isinstance(value, (list, tuple, set)):
        paths: list[str] = []
        for item in value:
            paths.extend(_source_path_values(item))
        return paths
    return []


def _source_unique_paths(paths: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        key = os.path.normcase(os.path.normpath(path))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _source_default_user_base_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "users"


def _source_config_file_paths() -> list[Path]:
    candidates: list[Path] = []
    userhome = _source_runtime_arg("userhome_path") or os.environ.get("simpleai_userhome")
    if userhome:
        userhome_abs = _source_path_to_abs(userhome)
        if userhome_abs:
            candidates.append(Path(userhome_abs) / "config.txt")
    candidates.append(_source_default_user_base_dir() / "config.txt")
    candidates.append(ROOT / "users" / "config.txt")
    env_config = os.environ.get("config_path")
    if env_config:
        config_abs = _source_path_to_abs(env_config)
        if config_abs:
            candidates.append(Path(config_abs))
    candidates.append(ROOT / "config.txt")
    return list(dict.fromkeys(candidates))


def _source_config_dict() -> Mapping[str, Any]:
    config_module = sys.modules.get("modules.config")
    loaded = getattr(config_module, "config_dict", None)
    if isinstance(loaded, Mapping):
        return loaded
    for path in _source_config_file_paths():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, Mapping):
            return data
    return {}


def _source_config_values(runtime_attrs: Sequence[str], config_keys: Sequence[str]) -> list[str]:
    values: list[str] = []
    config_module = sys.modules.get("modules.config")
    if config_module is not None:
        for attr in runtime_attrs:
            values.extend(_source_path_values(getattr(config_module, attr, None)))
    config = _source_config_dict()
    for key in config_keys:
        values.extend(_source_path_values(config.get(key)))
    return _source_unique_paths(values)


def _source_models_root() -> Path:
    candidates: list[str] = []
    candidates.extend(_source_path_values(_source_runtime_arg("models_root")))
    candidates.extend(_source_path_values(os.environ.get("simpleai_models_root")))
    candidates.extend(_source_path_values(os.environ.get("SIMPLEAI_MODELS_ROOT")))
    candidates.extend(_source_config_values(("path_models_root",), ("path_models_root",)))
    candidates.append(str(ROOT / "models"))
    return Path(_source_unique_paths(candidates)[0])


def _source_model_paths(
    runtime_attrs: Sequence[str],
    config_keys: Sequence[str],
    model_root: Path,
    default_dirs: Sequence[str],
) -> list[str]:
    paths = _source_config_values(runtime_attrs, config_keys)
    paths.extend(str(model_root / directory) for directory in default_dirs)
    return _source_unique_paths(paths)


def _source_first_path(paths: Sequence[str], fallback: Path) -> str:
    for path in paths:
        if os.path.isdir(path):
            return path
    return paths[0] if paths else str(fallback)


def _source_model_cmd_opts(model_root: Path) -> types.SimpleNamespace:
    embeddings = _source_model_paths(("paths_embeddings",), ("path_embeddings",), model_root, ("embeddings",))
    hypernetworks = [str(model_root / "hypernetworks")]
    checkpoints = _source_model_paths(("paths_diffusion_models", "paths_checkpoints"), ("path_diffusion_models", "path_checkpoints"), model_root, ("diffusion_models", "checkpoints"))
    loras = _source_model_paths(("paths_loras",), ("path_loras",), model_root, ("loras", "Lora"))
    vae = _source_model_paths(("paths_vae",), ("path_vae",), model_root, ("vae", "VAE"))
    controlnet = _source_model_paths(("paths_controlnet",), ("path_controlnet",), model_root, ("controlnet", "ControlNet"))
    detection = _source_model_paths(("paths_detection", "paths_ultralytics"), ("path_detection", "path_ultralytics"), model_root, ("detection", "ultralytics"))

    return types.SimpleNamespace(
        no_hashing=False,
        embeddings_dir=_source_first_path(embeddings, model_root / "embeddings"),
        hypernetwork_dir=_source_first_path(hypernetworks, model_root / "hypernetworks"),
        hypernetwork_dirs=hypernetworks,
        ckpt_dir=_source_first_path(checkpoints, model_root / "checkpoints"),
        ckpt_dirs=checkpoints,
        lora_dir=_source_first_path(loras, model_root / "loras"),
        lora_dirs=loras,
        lyco_dir=_source_first_path(loras, model_root / "loras"),
        lyco_dir_backcompat=_source_first_path(loras, model_root / "loras"),
        lyco_dirs=loras,
        vae_dir=_source_first_path(vae, model_root / "vae"),
        vae_dirs=vae,
        controlnet_dir=_source_first_path(controlnet, model_root / "controlnet"),
        controlnet_dirs=controlnet,
        control_net_models_path=_source_first_path(controlnet, model_root / "controlnet"),
        adetailer_models_path=_source_first_path(detection, model_root / "detection"),
        detection_dir=_source_first_path(detection, model_root / "detection"),
        detection_dirs=detection,
    )


@contextlib.contextmanager
def _source_i18n_context(prompt_components: Mapping[str, Any] | None) -> Iterator[None]:
    if _source_runtime_lang(prompt_components) != "cn":
        yield
        return
    translations = _source_translation_map(prompt_components)
    if not translations:
        yield
        return

    patched: list[tuple[type[Any], Any]] = []
    component_names = set(_SOURCE_TEXT_FIELDS) | set(_SOURCE_TEXT_FIRST_ARG_FIELDS)
    for component_name in component_names:
        component_cls = getattr(gr, component_name, None)
        if not isinstance(component_cls, type):
            continue
        original_init = component_cls.__init__
        text_fields = _SOURCE_TEXT_FIELDS.get(component_name, set())
        first_arg_field = _SOURCE_TEXT_FIRST_ARG_FIELDS.get(component_name)

        @functools.wraps(original_init)
        def patched_init(self, *args: Any, __original_init=original_init, __first_arg_field=first_arg_field, __text_fields=text_fields, **kwargs: Any):
            values = list(args)
            if __first_arg_field is not None and values:
                values[0] = _source_translate_text(values[0], translations)
            for key in __text_fields:
                if key in kwargs:
                    kwargs[key] = _source_translate_text(kwargs[key], translations)
            return __original_init(self, *values, **kwargs)

        patched_init.__signature__ = inspect.signature(original_init)
        component_cls.__init__ = patched_init
        patched.append((component_cls, original_init))

    try:
        yield
    finally:
        for component_cls, original_init in reversed(patched):
            component_cls.__init__ = original_init


def _install_source_module_stubs(prompt_components: Mapping[str, Any] | None = None) -> None:
    model_root = _source_models_root()
    models_path = str(model_root)
    output_dir = str(ROOT / "outputs")

    modules_root = _ensure_root_module("modules")
    modules_root.__path__ = list(dict.fromkeys([*getattr(modules_root, "__path__", []), str(SOURCE_WEBUI_ROOT / "modules")]))

    script_callbacks = _ScriptCallbacksModule()
    _install_module("modules.script_callbacks", script_callbacks)

    shared = types.ModuleType("modules.shared")
    shared.opts = _source_shared_opts()
    shared.models_path = models_path
    shared.cmd_opts = _source_model_cmd_opts(model_root)
    shared.OptionInfo = lambda *args, **kwargs: types.SimpleNamespace(link=lambda *a, **k: None)
    _install_module("modules.shared", shared)

    paths = types.ModuleType("modules.paths")
    paths.models_path = models_path
    paths.script_path = str(SOURCE_WEBUI_ROOT)
    paths.data_path = str(ROOT)
    paths.extensions_dir = str(SOURCE_EXTENSIONS_ROOT)
    paths.extensions_builtin_dir = str(SOURCE_WEBUI_ROOT / "extensions-builtin")
    paths.cwd = str(ROOT)
    _install_module("modules.paths", paths)

    paths_internal = types.ModuleType("modules.paths_internal")
    paths_internal.models_path = models_path
    paths_internal.script_path = str(SOURCE_WEBUI_ROOT)
    paths_internal.data_path = str(ROOT)
    paths_internal.default_output_dir = output_dir
    paths_internal.extensions_dir = str(SOURCE_EXTENSIONS_ROOT)
    paths_internal.extensions_builtin_dir = str(SOURCE_WEBUI_ROOT / "extensions-builtin")
    paths_internal.cwd = str(ROOT)
    paths_internal.normalized_filepath = lambda value: value
    paths_internal.parser = _SilentParser()
    _install_module("modules.paths_internal", paths_internal)

    devices = types.ModuleType("modules.devices")
    devices.device = "cpu"
    devices.dtype = None
    _install_module("modules.devices", devices)

    scripts = types.ModuleType("modules.scripts")
    scripts.Script = _SourceScript
    scripts.basedir = lambda: str(SOURCE_WEBUI_ROOT)
    _install_module("modules.scripts", scripts)

    ui = types.ModuleType("modules.ui")
    txt2img_prompt = _source_prompt_component(prompt_components, "txt2img_prompt", "forge_neo_source_stub_txt2img_prompt")
    txt2img_negative = _source_prompt_component(prompt_components, "txt2img_negative_prompt", "forge_neo_source_stub_txt2img_negative_prompt")
    img2img_prompt = _source_prompt_component(prompt_components, "img2img_prompt", "forge_neo_source_stub_img2img_prompt")
    img2img_negative = _source_prompt_component(prompt_components, "img2img_negative_prompt", "forge_neo_source_stub_img2img_negative_prompt")
    ui.txt2img_paste_fields = [(txt2img_prompt, "Prompt"), (txt2img_negative, "Negative prompt")]
    ui.img2img_paste_fields = [(img2img_prompt, "Prompt"), (img2img_negative, "Negative prompt")]
    ui.civitai_helper_lang = _source_runtime_lang(prompt_components)
    if prompt_components is not None:
        bridge = prompt_components.get("civitai_helper_bridge")
        if isinstance(bridge, Mapping):
            ui.civitai_helper_bridge = bridge
    modules_root.ui = ui
    _install_module("modules.ui", ui)

    hashes = types.ModuleType("modules.hashes")
    hashes.sha256_from_cache = lambda *args, **kwargs: None
    _install_module("modules.hashes", hashes)

    cache = types.ModuleType("modules.cache")
    cache.cache = lambda *args, **kwargs: {}
    cache.dump_cache = lambda *args, **kwargs: None
    _install_module("modules.cache", cache)

    sd_models = types.ModuleType("modules.sd_models")
    sd_models.read_metadata_from_safetensors = lambda *args, **kwargs: {}
    sd_models.get_closet_checkpoint_match = lambda *args, **kwargs: None
    _install_module("modules.sd_models", sd_models)

    backend_args = types.ModuleType("backend.args")
    backend_args.dynamic_args = None
    backend_args.parser = _SilentParser()
    _install_module("backend.args", backend_args)


class _SourceScript:
    def title(self) -> str:
        return self.__class__.__name__

    def show(self, is_img2img: bool) -> None:
        return None

    def ui(self, is_img2img: bool) -> list[Any]:
        return []


class _SilentParser:
    def add_argument(self, *args: Any, **kwargs: Any) -> None:
        return None

    def parse_known_args(self, *args: Any, **kwargs: Any) -> tuple[types.SimpleNamespace, list[str]]:
        return types.SimpleNamespace(), []


@contextlib.contextmanager
def _source_paths(script_path: Path) -> Iterator[None]:
    paths = [SOURCE_WEBUI_ROOT, script_path.parent, script_path.parent.parent]
    inserted: list[str] = []
    for path in paths:
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
            inserted.append(value)
    try:
        yield
    finally:
        for value in inserted:
            with contextlib.suppress(ValueError):
                sys.path.remove(value)


def _clear_script_local_modules(script_path: Path) -> None:
    extension_root = script_path.parent.parent.resolve()
    for module_name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            module_path = Path(module_file).resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if module_path == extension_root or extension_root in module_path.parents:
            sys.modules.pop(module_name, None)
    for path in script_path.parent.glob("*.py"):
        if path.stem != "__init__":
            sys.modules.pop(path.stem, None)


def _load_source_module(script_path: Path) -> types.ModuleType:
    module_name = f"_forge_neo_source_ui_{script_path.parent.parent.name}_{script_path.stem}"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load source UI script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def build_source_extension_ui_tabs(
    extension_dirname: str,
    script_relative_path: str,
    callback_name: str,
    *,
    prompt_components: Mapping[str, Any] | None = None,
) -> list[tuple[Any, str, str]]:
    ensure_source_gradio6_ui_compat()
    module_snapshot = _snapshot_source_stub_modules()
    _install_source_module_stubs(prompt_components)

    try:
        script_path = SOURCE_EXTENSIONS_ROOT / extension_dirname / script_relative_path
        if not script_path.is_file():
            raise FileNotFoundError(script_path)

        with _safe_console(), _source_paths(script_path), _detached_gradio_context(), _source_i18n_context(prompt_components):
            scripts_module = sys.modules.get("modules.scripts")
            if scripts_module is not None:
                scripts_module.basedir = lambda: str(script_path.parent.parent)
            _clear_script_local_modules(script_path)
            module = _load_source_module(script_path)
            callback = getattr(module, callback_name, None)
            if not callable(callback):
                raise AttributeError(f"{extension_dirname} has no callable {callback_name}")
            result = callback()
    finally:
        _restore_source_stub_modules(module_snapshot)

    if not isinstance(result, Sequence) or not result:
        raise ValueError(f"{extension_dirname} returned no UI tabs")
    tabs: list[tuple[Any, str, str]] = []
    translations = _source_translation_map(prompt_components) if _source_runtime_lang(prompt_components) == "cn" else {}
    for item in result:
        if not isinstance(item, Sequence) or len(item) < 3:
            continue
        interface, label, ifid = item[:3]
        tabs.append((interface, str(_source_translate_text(str(label), translations)), str(ifid)))
    if not tabs:
        raise ValueError(f"{extension_dirname} returned no usable UI tabs")
    return tabs


def build_source_extension_ui(
    extension_dirname: str,
    script_relative_path: str,
    callback_name: str,
    *,
    prompt_components: Mapping[str, Any] | None = None,
) -> tuple[Any, str, str]:
    return build_source_extension_ui_tabs(
        extension_dirname,
        script_relative_path,
        callback_name,
        prompt_components=prompt_components,
    )[0]


def render_source_extension_tabs(
    extension_dirname: str,
    script_relative_path: str,
    callback_name: str,
    *,
    visible: bool,
    require_flag: bool = True,
    prompt_components: Mapping[str, Any] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> bool:
    if not visible or (require_flag and not source_extension_ui_tabs_enabled()):
        return False
    try:
        tabs = build_source_extension_ui_tabs(
            extension_dirname,
            script_relative_path,
            callback_name,
            prompt_components=prompt_components,
        )
    except Exception as exc:
        if on_error is not None:
            on_error(exc)
        else:
            print(f"Forge Neo source UI failed for {extension_dirname}: {type(exc).__name__}: {exc}", flush=True)
        return False

    for interface, label, ifid in tabs:
        with gr.Tab(label, id=ifid, elem_id=f"tab_{ifid}", visible=visible):
            interface.render()
    return True


def render_source_extension_tab(
    extension_dirname: str,
    script_relative_path: str,
    callback_name: str,
    *,
    visible: bool,
    require_flag: bool = True,
    prompt_components: Mapping[str, Any] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> bool:
    return render_source_extension_tabs(
        extension_dirname,
        script_relative_path,
        callback_name,
        visible=visible,
        require_flag=require_flag,
        prompt_components=prompt_components,
        on_error=on_error,
    )
