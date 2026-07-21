import os


def resolve_existing_path_case_insensitive(path):
    if not isinstance(path, str) or not path.strip():
        return None
    expanded = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    if os.path.exists(expanded):
        return os.path.normpath(expanded)
    normalized = os.path.normpath(expanded)
    drive, tail = os.path.splitdrive(normalized)
    parts = [part for part in tail.replace("\\", "/").split("/") if part]
    current = drive + os.sep if drive else os.sep if normalized.startswith(os.sep) else ""
    if current and not os.path.exists(current):
        return expanded
    for part in parts:
        candidate = os.path.join(current, part) if current else part
        if os.path.exists(candidate):
            current = candidate
            continue
        parent = current or os.sep
        try:
            entries = os.listdir(parent)
        except OSError:
            return expanded
        match = next((entry for entry in entries if entry.lower() == part.lower()), None)
        if match is None:
            return expanded
        current = os.path.join(parent, match)
    return os.path.normpath(current) if current else expanded


def _normalize_dir(path):
    if not isinstance(path, str) or not path.strip():
        return None
    return resolve_existing_path_case_insensitive(path)


def normalize_model_dirs(dirs):
    if isinstance(dirs, str):
        dirs = [dirs]
    if not isinstance(dirs, (list, tuple)):
        return []
    result = []
    seen = set()
    for path in dirs:
        normalized = _normalize_dir(path)
        if not normalized:
            continue
        key = os.path.normcase(os.path.normpath(normalized))
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def find_model_in_dirs(dirs, filename):
    if not filename:
        return None
    relative = str(filename).replace("\\", os.sep).replace("/", os.sep).lstrip(os.sep)
    for directory in normalize_model_dirs(dirs):
        candidate = os.path.join(directory, relative)
        if os.path.exists(candidate):
            return candidate
    return None


def find_dir_containing_model(dirs, filename, fallback=None):
    found = find_model_in_dirs(dirs, filename)
    if found:
        return os.path.dirname(found)
    normalized = normalize_model_dirs(dirs)
    if fallback:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(fallback)))
    return normalized[0] if normalized else os.getcwd()


def first_model_dir(dirs, fallback=None):
    normalized = normalize_model_dirs(dirs)
    if normalized:
        return normalized[0]
    if fallback:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(fallback)))
    return os.getcwd()
