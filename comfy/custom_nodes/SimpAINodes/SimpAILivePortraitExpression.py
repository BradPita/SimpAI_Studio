import json
import re


SAMPLE_PARTS = ["OnlyExpression", "OnlyRotation", "OnlyMouth", "OnlyEyes", "All"]

FLOAT_SPECS = {
    "rotate_pitch": (0.0, -20.0, 20.0),
    "rotate_yaw": (0.0, -20.0, 20.0),
    "rotate_roll": (0.0, -20.0, 20.0),
    "blink": (0.0, -20.0, 5.0),
    "eyebrow": (0.0, -10.0, 15.0),
    "wink": (0.0, 0.0, 25.0),
    "pupil_x": (0.0, -15.0, 15.0),
    "pupil_y": (0.0, -15.0, 15.0),
    "aaa": (0.0, -30.0, 120.0),
    "eee": (0.0, -20.0, 15.0),
    "woo": (0.0, -20.0, 15.0),
    "smile": (0.0, -0.3, 1.3),
    "src_ratio": (1.0, 0.0, 1.0),
    "sample_ratio": (1.0, -0.2, 1.2),
    "crop_factor": (1.7, 1.5, 2.5),
}

RETURN_ORDER = (
    "rotate_pitch",
    "rotate_yaw",
    "rotate_roll",
    "blink",
    "eyebrow",
    "wink",
    "pupil_x",
    "pupil_y",
    "aaa",
    "eee",
    "woo",
    "smile",
    "src_ratio",
    "sample_ratio",
    "sample_parts",
    "crop_factor",
    "source_face_bbox",
    "reference_face_bbox",
)

SAMPLE_PART_ALIASES = {
    "expression": "OnlyExpression",
    "onlyexpression": "OnlyExpression",
    "rotation": "OnlyRotation",
    "onlyrotation": "OnlyRotation",
    "mouth": "OnlyMouth",
    "onlymouth": "OnlyMouth",
    "eyes": "OnlyEyes",
    "eye": "OnlyEyes",
    "onlyeyes": "OnlyEyes",
    "all": "All",
}


def _read_json_object(value):
    if isinstance(value, dict):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _lookup_value(data, key):
    if key in data:
        return data.get(key)
    params = data.get("params")
    if isinstance(params, dict) and key in params:
        return params.get(key)
    expression = data.get("expression")
    if isinstance(expression, dict) and key in expression:
        return expression.get(key)
    return None


def _coerce_float(value, default, minimum, maximum):
    try:
        if isinstance(value, bool) or value is None or value == "":
            number = default
        else:
            number = float(value)
    except Exception:
        number = default
    if number < minimum:
        number = minimum
    if number > maximum:
        number = maximum
    return float(number)


def _coerce_sample_parts(value):
    text = str(value or "").strip()
    if text in SAMPLE_PARTS:
        return text
    key = re.sub(r"[^a-zA-Z]+", "", text).lower()
    return SAMPLE_PART_ALIASES.get(key, "OnlyExpression")


def _coerce_face_bbox(value):
    if value is None or value == "":
        return ""
    data = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            data = json.loads(text)
        except Exception:
            return ""
    if isinstance(data, dict):
        if all(key in data for key in ("x", "y", "width", "height")):
            out = {key: data.get(key) for key in ("x", "y", "width", "height")}
        elif all(key in data for key in ("x1", "y1", "x2", "y2")):
            out = {key: data.get(key) for key in ("x1", "y1", "x2", "y2")}
        else:
            return ""
    elif isinstance(data, (list, tuple)) and len(data) >= 4:
        out = [data[0], data[1], data[2], data[3]]
    else:
        return ""
    try:
        return json.dumps(out, separators=(",", ":"))
    except Exception:
        return ""


def parse_liveportrait_expression_state(value):
    data = _read_json_object(value)
    parsed = {}
    for key, (default, minimum, maximum) in FLOAT_SPECS.items():
        parsed[key] = _coerce_float(_lookup_value(data, key), default, minimum, maximum)
    parsed["sample_parts"] = _coerce_sample_parts(_lookup_value(data, "sample_parts"))
    parsed["source_face_bbox"] = _coerce_face_bbox(_lookup_value(data, "source_face_bbox"))
    parsed["reference_face_bbox"] = _coerce_face_bbox(_lookup_value(data, "reference_face_bbox"))
    parsed["version"] = str(data.get("version") or "1")
    return parsed


def _is_empty_image_name(value):
    text = str(value or "").strip()
    return not text or text.lower() == "none"


class LivePortraitExpressionParams:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "expression_state": ("STRING", {"default": "{}", "multiline": True}),
            }
        }

    RETURN_TYPES = (
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        "FLOAT",
        SAMPLE_PARTS,
        "FLOAT",
        "STRING",
        "STRING",
    )
    RETURN_NAMES = RETURN_ORDER
    FUNCTION = "parse"
    CATEGORY = "SimpAI/LivePortrait"

    def parse(self, expression_state):
        parsed = parse_liveportrait_expression_state(expression_state)
        return tuple(parsed[name] for name in RETURN_ORDER)


class LivePortraitOptionalReferenceImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_name": ("STRING", {"default": "None", "multiline": False}),
            },
            "optional": {
                "image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("sample_image",)
    FUNCTION = "select"
    CATEGORY = "SimpAI/LivePortrait"

    def select(self, image_name, image=None):
        if _is_empty_image_name(image_name):
            return (None,)
        return (image,)


NODE_CLASS_MAPPINGS = {
    "LivePortraitExpressionParams": LivePortraitExpressionParams,
    "LivePortraitOptionalReferenceImage": LivePortraitOptionalReferenceImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LivePortraitExpressionParams": "LivePortrait Expression Params",
    "LivePortraitOptionalReferenceImage": "LivePortrait Optional Reference Image",
}
