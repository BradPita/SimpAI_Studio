import os


PLACEHOLDER_LORA_NAME = "placeholder.safetensors"
_LORA_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".bin", ".pth"}


def normalize_lora_model_name(name, path_separator="/"):
    normalized = str(name or "").strip().replace("\\", "/").lstrip("/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if path_separator != "/":
        normalized = normalized.replace("/", path_separator)
    return normalized


def _drop_lora_extension(name):
    root, ext = os.path.splitext(name)
    if ext.casefold() in _LORA_EXTENSIONS:
        return root
    return name


def _lora_lookup_key(name):
    return normalize_lora_model_name(name).casefold()


def _is_empty_lora_name(name):
    key = _lora_lookup_key(name)
    return key in ("", "none", PLACEHOLDER_LORA_NAME.casefold())


def _lora_item_name(lora):
    try:
        return lora[0]
    except Exception:
        return None


def resolve_lora_filename(lora_name, lora_filenames):
    candidate = normalize_lora_model_name(lora_name)
    if _is_empty_lora_name(candidate):
        return None

    candidate_key = candidate.casefold()
    candidate_without_ext_key = _drop_lora_extension(candidate).casefold()
    stem_matches = []

    for filename in lora_filenames or []:
        normalized_filename = normalize_lora_model_name(filename)
        if _is_empty_lora_name(normalized_filename):
            continue

        filename_key = normalized_filename.casefold()
        filename_without_ext_key = _drop_lora_extension(normalized_filename).casefold()
        if candidate_key in (filename_key, filename_without_ext_key):
            return filename

        filename_stem_key = _drop_lora_extension(os.path.basename(normalized_filename)).casefold()
        if candidate_without_ext_key == filename_stem_key:
            stem_matches.append(filename)

    if stem_matches:
        return stem_matches[0]
    return None


def merge_loras_preserving_slots(loras: list, prompt_loras: list, max_lora_number: int = 10, deduplicate: bool = True):
    try:
        max_lora_number = int(max_lora_number)
    except (TypeError, ValueError):
        max_lora_number = 0
    if max_lora_number <= 0:
        return []

    merged = list(loras or [])[:max_lora_number]
    while len(merged) < max_lora_number:
        merged.append(("None", 1.0))

    existing_names = {
        _lora_lookup_key(_lora_item_name(lora))
        for lora in merged
        if not _is_empty_lora_name(_lora_item_name(lora))
    }

    for prompt_lora in prompt_loras or []:
        try:
            lora_name, lora_strength = prompt_lora
        except (TypeError, ValueError):
            continue
        if _is_empty_lora_name(lora_name):
            continue
        lora_key = _lora_lookup_key(lora_name)
        if deduplicate and lora_key in existing_names:
            continue
        insert_index = next(
            (
                index
                for index, current_lora in enumerate(merged)
                if _is_empty_lora_name(_lora_item_name(current_lora))
            ),
            None,
        )
        if insert_index is None:
            break
        merged[insert_index] = (lora_name, lora_strength)
        existing_names.add(lora_key)

    return merged


def sync_loras_to_params_backend(params_backend: dict, loras: list, max_lora_number: int = 10, lora_filenames=None):
    if not isinstance(params_backend, dict):
        return params_backend

    try:
        max_lora_number = int(max_lora_number)
    except (TypeError, ValueError):
        max_lora_number = 0
    if max_lora_number <= 0:
        return params_backend

    loras = list(loras or [])
    resolved_loras = []
    for i in range(max_lora_number):
        key = f"lora_{i + 1}"
        strength_key = f"lora_{i + 1}_strength"
        lora_name = "None"
        lora_strength = 1.0

        if i < len(loras):
            try:
                lora_name, lora_strength = loras[i]
            except (TypeError, ValueError):
                lora_name, lora_strength = "None", 1.0

        if _is_empty_lora_name(lora_name):
            params_backend[key] = PLACEHOLDER_LORA_NAME
            params_backend[strength_key] = 0.0
            continue

        if lora_filenames is not None:
            resolved_lora_name = resolve_lora_filename(lora_name, lora_filenames)
            if resolved_lora_name is None:
                params_backend[key] = PLACEHOLDER_LORA_NAME
                params_backend[strength_key] = 0.0
                continue
            lora_name = resolved_lora_name

        try:
            lora_strength = float(lora_strength)
        except (TypeError, ValueError):
            lora_strength = 1.0

        lora_name = normalize_lora_model_name(lora_name, os.sep).lstrip(os.sep)
        resolved_loras.append([lora_name, lora_strength])
        params_backend[key] = lora_name
        params_backend[strength_key] = lora_strength

    if "loras" in params_backend:
        params_backend["loras"] = resolved_loras
    if "use_lora" in params_backend:
        params_backend["use_lora"] = bool(resolved_loras)

    return params_backend
