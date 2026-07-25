from __future__ import annotations

import copy
import json
from typing import Any


FORGE_COUPLE_SCRIPT_NAME = "Forge Couple"

FORGE_COUPLE_SETTING_DEFAULTS: dict[str, bool] = {
    "fc_do_interrupt": True,
    "fc_no_presets": False,
    "fc_no_tile": False,
    "fc_adv_newline": False,
}
FORGE_COUPLE_SETTING_KEYS = tuple(FORGE_COUPLE_SETTING_DEFAULTS)

FORGE_COUPLE_ARG_KEYS = (
    "enable",
    "disable_hr",
    "mode",
    "separator",
    "direction",
    "background",
    "background_weight",
    "mapping",
    "common_parser",
    "common_debug",
    "def_in_prompt",
    "tile_enabled",
    "tile_columns",
    "tile_rows",
    "tile_threshold",
    "tile_replacements",
    "tile_debug",
)

FORGE_COUPLE_ARG_LABELS = {
    "enable": "Enable",
    "disable_hr": "Compatibility",
    "mode": "Region Assignment",
    "separator": "Couple Separator",
    "direction": "Tile Direction",
    "background": "Global Effect",
    "background_weight": "Global Effect Weight",
    "mapping": "Mapping",
    "common_parser": "Common Prompt Syntax",
    "common_debug": "Common Prompt Debug",
    "def_in_prompt": "Include Definitions in Prompt",
    "tile_enabled": "Enable Tile Mode",
    "tile_columns": "Column Count",
    "tile_rows": "Row Count",
    "tile_threshold": "Inclusion Threshold",
    "tile_replacements": "Subject Replacement",
    "tile_debug": "Debug Tiles",
}

FORGE_COUPLE_DEFAULT_MAPPING = [
    [0.0, 0.5, 0.0, 1.0, 1.0],
    [0.5, 1.0, 0.0, 1.0, 1.0],
]

FORGE_COUPLE_ARG_DEFAULTS: dict[str, Any] = {
    "enable": False,
    "disable_hr": True,
    "mode": "Basic",
    "separator": "",
    "direction": "Horizontal",
    "background": "None",
    "background_weight": 0.5,
    "mapping": FORGE_COUPLE_DEFAULT_MAPPING,
    "common_parser": "{ }",
    "common_debug": False,
    "def_in_prompt": True,
    "tile_enabled": False,
    "tile_columns": -1,
    "tile_rows": -1,
    "tile_threshold": 0.75,
    "tile_replacements": "",
    "tile_debug": False,
}

FORGE_COUPLE_ARG_ALIASES = {
    "active": "enable",
    "enabled": "enable",
    "compatibility": "disable_hr",
    "disable_hires": "disable_hr",
    "region_mode": "mode",
    "couple_separator": "separator",
    "tile_direction": "direction",
    "global_effect": "background",
    "global_effect_weight": "background_weight",
    "common_prompt_parser": "common_parser",
    "include_definitions": "def_in_prompt",
    "use_tile": "tile_enabled",
    "tile_h": "tile_columns",
    "tile_v": "tile_rows",
    "subject_replacement": "tile_replacements",
    "debug_tiles": "tile_debug",
}


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled"}:
            return False
    return bool(value)


def _float_value(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _int_value(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _mapping_value(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        return value["data"]
    return value


def normalize_advanced_mapping(value: Any, *, use_default: bool = True) -> list[list[float]]:
    rows = _mapping_value(value)
    if not isinstance(rows, (list, tuple)):
        rows = []
    normalized: list[list[float]] = []
    for row in rows:
        if isinstance(row, dict):
            items = [
                row.get("x_from", row.get("x1", 0.0)),
                row.get("x_to", row.get("x2", 1.0)),
                row.get("y_from", row.get("y1", 0.0)),
                row.get("y_to", row.get("y2", 1.0)),
                row.get("weight", row.get("w", 1.0)),
            ]
        elif isinstance(row, (list, tuple)) and len(row) >= 5:
            items = list(row[:5])
        else:
            continue
        x1 = _float_value(items[0], 0.0, minimum=0.0, maximum=1.0)
        x2 = _float_value(items[1], 1.0, minimum=0.0, maximum=1.0)
        y1 = _float_value(items[2], 0.0, minimum=0.0, maximum=1.0)
        y2 = _float_value(items[3], 1.0, minimum=0.0, maximum=1.0)
        weight = _float_value(items[4], 1.0, minimum=0.0, maximum=5.0)
        normalized.append([x1, max(x1, x2), y1, max(y1, y2), weight])
    if normalized or not use_default:
        return normalized
    return copy.deepcopy(FORGE_COUPLE_DEFAULT_MAPPING)


def normalize_mask_mapping(value: Any) -> list[dict[str, Any]]:
    rows = _mapping_value(value)
    if not isinstance(rows, (list, tuple)):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            mask = row.get("mask", row.get("image"))
            weight = row.get("weight", 1.0)
        else:
            mask = row
            weight = 1.0
        if mask is None or (isinstance(mask, str) and not mask.strip()):
            continue
        normalized.append(
            {
                "mask": mask,
                "weight": _float_value(weight, 1.0, minimum=0.0, maximum=5.0),
            }
        )
    return normalized


def forge_couple_args_active(value: Any) -> bool:
    if isinstance(value, dict):
        for key in ("enable", "enabled", "active"):
            if key in value:
                return _bool_value(value.get(key), False)
        return bool(value)
    if isinstance(value, (list, tuple)):
        return _bool_value(value[0], False) if value else False
    return False


def forge_couple_arg_dict(
    value: Any = None,
    *,
    enabled: bool | None = None,
    is_img2img: bool | None = None,
) -> dict[str, Any]:
    data = copy.deepcopy(FORGE_COUPLE_ARG_DEFAULTS)
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = FORGE_COUPLE_ARG_ALIASES.get(str(raw_key), str(raw_key))
            if key in data:
                data[key] = item
    elif isinstance(value, (list, tuple)):
        for key, item in zip(FORGE_COUPLE_ARG_KEYS, value):
            data[key] = item

    if enabled is not None:
        data["enable"] = bool(enabled)
    data["enable"] = _bool_value(data.get("enable"), False)
    data["disable_hr"] = _bool_value(data.get("disable_hr"), True)

    mode = str(data.get("mode") or "Basic").strip().title()
    data["mode"] = mode if mode in {"Basic", "Advanced", "Mask"} else "Basic"
    data["separator"] = str(data.get("separator") or "")

    direction = str(data.get("direction") or "Horizontal").strip().title()
    data["direction"] = direction if direction in {"Horizontal", "Vertical"} else "Horizontal"

    background_aliases = {
        "none": "None",
        "first": "First Line",
        "first line": "First Line",
        "last": "Last Line",
        "last line": "Last Line",
    }
    background = str(data.get("background") or "None").strip()
    data["background"] = background_aliases.get(background.casefold(), "None")
    data["background_weight"] = _float_value(data.get("background_weight"), 0.5, minimum=0.1, maximum=1.0)

    if data["mode"] == "Mask":
        data["mapping"] = normalize_mask_mapping(data.get("mapping"))
    else:
        data["mapping"] = normalize_advanced_mapping(data.get("mapping"))

    common_parser = str(data.get("common_parser") or "off").strip()
    data["common_parser"] = common_parser if common_parser in {"off", "{ }", "< >"} else "off"
    data["common_debug"] = _bool_value(data.get("common_debug"), False)
    data["def_in_prompt"] = _bool_value(data.get("def_in_prompt"), True)

    data["tile_enabled"] = _bool_value(data.get("tile_enabled"), False)
    if is_img2img is False:
        data["tile_enabled"] = False
    data["tile_columns"] = _int_value(data.get("tile_columns"), -1, minimum=-1, maximum=64)
    data["tile_rows"] = _int_value(data.get("tile_rows"), -1, minimum=-1, maximum=64)
    data["tile_threshold"] = _float_value(data.get("tile_threshold"), 0.75, minimum=0.0, maximum=1.0)
    data["tile_replacements"] = str(data.get("tile_replacements") or "")
    data["tile_debug"] = _bool_value(data.get("tile_debug"), False)
    return data


def forge_couple_arg_list(
    value: Any = None,
    *,
    enabled: bool | None = None,
    is_img2img: bool | None = None,
) -> list[Any]:
    data = forge_couple_arg_dict(value, enabled=enabled, is_img2img=is_img2img)
    return [data[key] for key in FORGE_COUPLE_ARG_KEYS]


def forge_couple_default_args(*, enabled: bool = False, is_img2img: bool = False) -> list[Any]:
    return forge_couple_arg_list(enabled=enabled, is_img2img=is_img2img)


def forge_couple_script_arg_specs(*, is_img2img: bool = False) -> list[dict[str, Any]]:
    values = forge_couple_default_args(is_img2img=is_img2img)
    specs: list[dict[str, Any]] = []
    for key, value in zip(FORGE_COUPLE_ARG_KEYS, values):
        choices: list[Any] | None = None
        minimum: float | int | None = None
        maximum: float | int | None = None
        step: float | int | None = None
        if key == "mode":
            choices = ["Basic", "Advanced", "Mask"]
        elif key == "direction":
            choices = ["Horizontal", "Vertical"]
        elif key == "background":
            choices = ["None", "First Line", "Last Line"]
        elif key == "common_parser":
            choices = ["off", "{ }", "< >"]
        elif key == "background_weight":
            minimum, maximum, step = 0.1, 1.0, 0.1
        elif key in {"tile_columns", "tile_rows"}:
            minimum, maximum, step = -1, 64, 1
        elif key == "tile_threshold":
            minimum, maximum, step = 0.0, 1.0, 0.05
        specs.append(
            {
                "label": FORGE_COUPLE_ARG_LABELS[key],
                "value": value,
                "choices": choices,
                "minimum": minimum,
                "maximum": maximum,
                "step": step,
            }
        )
    return specs


def forge_couple_schema_payload() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key, value in forge_couple_arg_dict().items():
        properties[key] = {
            "title": FORGE_COUPLE_ARG_LABELS[key],
            "default": value,
            "type": _json_schema_type(value),
        }
    return {
        "title": "ForgeCoupleArgs",
        "type": "object",
        "additionalProperties": True,
        "properties": properties,
        "args_order": list(FORGE_COUPLE_ARG_KEYS),
    }


def _json_schema_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"
