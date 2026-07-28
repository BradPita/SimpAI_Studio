import re


TAG_UNDERSCORE_EXCLUSIONS = frozenset({
    "0_0",
    "(o)_(o)",
    "+_+",
    "+_-",
    "._.",
    "<o>_<o>",
    "<|>_<|>",
    "=_=",
    ">_<",
    "3_3",
    "6_9",
    ">_o",
    "@_@",
    "^_^",
    "o_o",
    "u_u",
    "x_x",
    "|_|",
    "||_||",
})

_TAG_PART_SPLIT_RE = re.compile(r"([,;\n]+)")
_TAG_ALLOWED_RE = re.compile(r"^[A-Za-z0-9_\\()\[\]{}:+.!?'*#@&|<>=~^\-\s]+$")
_TAG_WEIGHT_RE = re.compile(
    r"^(?P<open>[\(\[\{]*)(?P<body>.*?)(?P<weight>:\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*)(?P<close>[\)\]\}]+)$"
)
_WRAPPER_PAIRS = {"(": ")", "[": "]", "{": "}"}


def _tag_structural_variants(value):
    current = str(value or "").strip()
    variants = []
    while current:
        variants.append(current)
        weighted = _TAG_WEIGHT_RE.fullmatch(current)
        if weighted:
            body = str(weighted.group("body") or "").strip()
            if body and body not in variants:
                variants.append(body)
        if len(current) < 2 or _WRAPPER_PAIRS.get(current[0]) != current[-1]:
            break
        current = current[1:-1].strip()
    return variants


def _tag_part_core(part):
    match = re.fullmatch(r"(\s*)(.*?)(\s*)", str(part or ""), flags=re.DOTALL)
    if not match:
        return "", "", ""
    leading, core, trailing = match.groups()
    if not core or not _TAG_ALLOWED_RE.fullmatch(core):
        return leading, "", trailing
    variants = _tag_structural_variants(core)
    if any(value in TAG_UNDERSCORE_EXCLUSIONS for value in variants):
        return leading, "", trailing
    if any(
        (value.startswith("<") and value.endswith(">"))
        or (value.startswith("__") and value.endswith("__"))
        or "://" in value
        for value in variants
    ):
        return leading, "", trailing
    return leading, core, trailing


def _replace_tag_part(core, direction):
    if direction == "to_spaces":
        return core.replace("_", " ")
    weighted = _TAG_WEIGHT_RE.fullmatch(core)
    if weighted:
        body = re.sub(r"[ \t]+", "_", str(weighted.group("body") or "").strip())
        return "".join((weighted.group("open"), body, weighted.group("weight"), weighted.group("close")))
    return re.sub(r"[ \t]+", "_", core)


def convert_tag_separators(value, direction="auto"):
    original = str(value or "")
    parts = _TAG_PART_SPLIT_RE.split(original)
    candidates = []
    for index in range(0, len(parts), 2):
        leading, core, trailing = _tag_part_core(parts[index])
        if core:
            candidates.append((index, leading, core, trailing))

    requested = str(direction or "auto").strip().lower().replace("-", "_")
    aliases = {
        "spaces": "to_spaces",
        "space": "to_spaces",
        "underscores": "to_underscores",
        "underscore": "to_underscores",
    }
    selected = aliases.get(requested, requested)
    if selected == "auto":
        selected = "to_spaces" if any("_" in core for _index, _leading, core, _trailing in candidates) else "to_underscores"
    if selected not in {"to_spaces", "to_underscores"}:
        raise ValueError(f"Unsupported tag separator direction: {direction}")

    changed = 0
    for index, leading, core, trailing in candidates:
        converted = _replace_tag_part(core, selected)
        if converted == core:
            continue
        parts[index] = f"{leading}{converted}{trailing}"
        changed += 1
    return "".join(parts), selected, changed


def tag_underscores_to_spaces(value):
    return convert_tag_separators(value, "to_spaces")[0]
