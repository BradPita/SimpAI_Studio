import os
import anyio
import httpx
from tqdm import tqdm
import threading
import queue
import json
import ast
import time
import shared
from urllib.parse import urlparse
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from torch.hub import download_url_to_file

import logging
from enhanced.logger import format_name
logger = logging.getLogger(format_name(__name__))

thread_pool = ThreadPoolExecutor(max_workers=6)
download_tasks = set()
download_cancel_requests = set()
download_progress = {}
download_task_metadata = {}
task_lock = threading.Lock()

LEGACY_CATEGORY_SEARCH_PATHS = {
    "sams": ("inpaint",),
    "grounding-dino": ("inpaint",),
    "ipadapter": ("controlnet",),
}
DEFAULT_MODEL_CATEGORIES = {"checkpoints", "diffusion_models", "unet"}
PREVIOUS_DEFAULT_MODEL_FIELDS = (
    ("default_model", "previous_default_models"),
    ("default_refiner", "previous_default_refiners"),
)


class DownloadCancelled(Exception):
    pass


def _is_download_cancelled(task_id):
    with task_lock:
        return task_id in download_cancel_requests


def _mark_download_cancelled(task_id, file_name=""):
    if not task_id:
        return
    current = download_progress.get(task_id)
    if not isinstance(current, dict):
        current = {}
    current.update({
        "cancelled": True,
        "file_name": file_name or current.get("file_name") or os.path.basename(str(task_id)),
    })
    download_progress[task_id] = current


def _mark_download_error(task_id, message, file_name=""):
    if not task_id:
        return
    current = download_progress.get(task_id)
    if not isinstance(current, dict):
        current = {}
    current.update({
        "error": str(message or "download failed"),
        "file_name": file_name or current.get("file_name") or os.path.basename(str(task_id)),
    })
    download_progress[task_id] = current


def _remember_download_task(task_id, *, file_name="", model_dir="", url="", size=0):
    if not task_id:
        return
    download_task_metadata[task_id] = {
        "task_id": task_id,
        "file_name": file_name or os.path.basename(str(task_id)),
        "model_dir": model_dir or "",
        "url": url or "",
        "size": _normalize_expected_size(size),
        "created_at": time.time(),
    }


def _split_download_urls(url):
    if isinstance(url, (list, tuple)):
        raw_items = url
    else:
        raw_items = str(url or "").split(",")
    return [str(item or "").strip().strip("`") for item in raw_items if str(item or "").strip().strip("`")]


def _apply_hf_mirror(url):
    url = str(url or "")
    if 'HF_MIRROR' in os.environ:
        return str.replace(url, "huggingface.co", os.environ["HF_MIRROR"].rstrip('/'), 1)
    return url


def cancel_download_task(task_id):
    task_id = str(task_id or "").replace("\\", "/").strip("/")
    if not task_id:
        return False
    with task_lock:
        active = task_id in download_tasks or task_id in download_progress
        download_cancel_requests.add(task_id)
    _mark_download_cancelled(task_id)
    logger.info("下载任务已请求停止: %s", task_id)
    return active


def has_active_download_tasks():
    with task_lock:
        return bool(download_tasks)

def _normalize_expected_size(size):
    try:
        return int(size or 0)
    except Exception:
        return 0

def _file_size_matches(file_path, size):
    expected_size = _normalize_expected_size(size)
    if not os.path.exists(file_path):
        return False
    if expected_size <= 0:
        return True
    try:
        return os.path.getsize(file_path) == expected_size
    except Exception:
        return False

def _file_size_mismatch(file_path, size):
    expected_size = _normalize_expected_size(size)
    return os.path.exists(file_path) and expected_size > 0 and not _file_size_matches(file_path, expected_size)


def get_download_queue_snapshot():
    rows = []
    with task_lock:
        task_ids = set(download_task_metadata.keys()) | set(download_tasks) | set(download_progress.keys())
        for task_id in task_ids:
            meta = dict(download_task_metadata.get(task_id) or {})
            progress = dict(download_progress.get(task_id) or {})
            active = task_id in download_tasks
            cancelled = bool(progress.get("cancelled") or task_id in download_cancel_requests)
            error = str(progress.get("error") or "")
            try:
                current = int(progress.get("current", 0) or 0)
            except Exception:
                current = 0
            try:
                total = int(progress.get("total", 0) or meta.get("size", 0) or 0)
            except Exception:
                total = 0
            try:
                percent = float(progress.get("percent", 0.0) or 0.0)
            except Exception:
                percent = 0.0
            if total > 0 and current > 0:
                percent = max(0.0, min(100.0, (current / total) * 100.0))
            else:
                percent = max(0.0, min(100.0, percent))
            if error:
                status = "error"
            elif cancelled:
                status = "stopped"
            elif active and current <= 0:
                status = "queued"
            elif active:
                status = "downloading"
            else:
                status = "done"
            rows.append(
                {
                    "task_id": task_id,
                    "file_name": progress.get("file_name") or meta.get("file_name") or os.path.basename(str(task_id)),
                    "model_dir": meta.get("model_dir", ""),
                    "url": meta.get("url", ""),
                    "current": current,
                    "total": total,
                    "percent": percent,
                    "status": status,
                    "error": error,
                    "active": active,
                    "created_at": float(meta.get("created_at") or 0.0),
                }
            )
    return sorted(rows, key=lambda item: (item.get("created_at", 0.0), item.get("task_id", "")))

async def download_file_with_progress(url: str, file_path: str, size: int=0, task_id: Optional[str] = None):
    global download_progress
    file_name = os.path.basename(file_path)
    progress_key = task_id or file_name
    size = _normalize_expected_size(size)
    timeout = int(max(60.0, size / (1024 * 1024)))
    logger.info(f'the download file timeout: {timeout}s')
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        try:
            url = _apply_hf_mirror(url)
            model_dir = os.path.dirname(file_path)
            if not os.path.exists(model_dir):
                os.makedirs(model_dir, exist_ok=True)

            partial_file_path = file_path + ".partial"

            resume_size = 0
            if os.path.exists(partial_file_path):
                resume_size = os.path.getsize(partial_file_path)
                logger.info(f"发现部分下载的文件，将从 {resume_size} 字节处继续下载")

            if _is_download_cancelled(progress_key):
                _mark_download_cancelled(progress_key, file_name)
                raise DownloadCancelled(f"下载任务已停止: {progress_key}")

            headers = {}
            if resume_size > 0:
                headers["Range"] = f"bytes={resume_size}-"

            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()

                content_range = response.headers.get("Content-Range")
                if resume_size > 0 and response.status_code == 200 and not content_range:
                    logger.info("服务器未接受断点续传请求，将重新下载完整文件")
                    resume_size = 0
                if content_range:
                    try:
                        total_size = int(content_range.split("/")[-1])
                    except Exception:
                        total_size = 0
                else:
                    try:
                        total_size = int(response.headers.get("Content-Length", 0) or 0)
                    except Exception:
                        total_size = 0
                if total_size <= 0 and size:
                    try:
                        total_size = int(size or 0)
                    except Exception:
                        total_size = 0
                download_progress[progress_key] = {
                    "percent": 0.0 if total_size > 0 else 0.0,
                    "current": resume_size,
                    "total": total_size,
                    "file_name": file_name,
                }

                with tqdm(
                    total=total_size if total_size > 0 else None,
                    initial=resume_size,
                    unit="iB",
                    unit_scale=True,
                    desc=''
                ) as progress_bar:
                    mode = "ab" if resume_size > 0 else "wb"
                    with open(partial_file_path, mode) as f:
                        async for chunk in response.aiter_bytes():
                            if _is_download_cancelled(progress_key):
                                _mark_download_cancelled(progress_key, file_name)
                                raise DownloadCancelled(f"下载任务已停止: {progress_key}")
                            f.write(chunk)
                            chunk_len = len(chunk)
                            progress_bar.update(chunk_len)

                            current_size = progress_bar.n
                            percent = (current_size / total_size) * 100 if total_size > 0 else 0.0
                            download_progress[progress_key] = {
                                "percent": percent,
                                "current": current_size,
                                "total": total_size,
                                "file_name": file_name,
                            }

            downloaded_size = os.path.getsize(partial_file_path)
            if downloaded_size == total_size or downloaded_size == size:
                os.replace(partial_file_path, file_path)
                shared.modelsinfo.refresh_file('add', file_path, url)
                _clear_missing_model_list_cache()
                logger.info(f"文件下载完成: {file_path}")
                if progress_key in download_progress:
                    del download_progress[progress_key]
            else:
                logger.error(f"下载的文件大小不符，预期 {total_size} 字节，实际 {downloaded_size} 字节")
                raise Exception(f"下载的文件大小不符，预期 {total_size} 字节，实际 {downloaded_size} 字节")
        except DownloadCancelled:
            logger.info("下载任务已停止: %s", progress_key)
            _mark_download_cancelled(progress_key, file_name)
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"下载失败: {e}")
            logger.error(f"请求 URL: {e.request.url}")
            logger.error(f"重定向 URL: {e.response.headers.get('Location')}")
            if progress_key in download_progress:
                download_progress[progress_key]["error"] = str(e)
            raise
        except Exception as e:
            logger.error(f"下载过程中发生错误: {e}")
            if progress_key in download_progress:
                download_progress[progress_key]["error"] = str(e)
            raise


def load_file_from_url(
        url: str,
        *,
        model_dir: str,
        progress: bool = True,
        file_name: Optional[str] = None,
        async_task: bool = False,
        size: int = 0,
        task_id: Optional[str] = None,
) -> str:
    global download_queue

    """
    Download a file from `url` into `model_dir`, using the file present if possible.

    Returns the path to the downloaded file.
    """
    download_urls = _split_download_urls(url)
    if not download_urls:
        download_urls = [str(url or "")]
    primary_url = _apply_hf_mirror(download_urls[0])
    if not os.path.exists(model_dir):
        os.makedirs(model_dir, exist_ok=True)
    if not file_name:
        parts = urlparse(primary_url)
        file_name = os.path.basename(parts.path)
    cached_file = os.path.abspath(os.path.join(model_dir, file_name))
    effective_task_id = task_id or file_name
    expected_size = _normalize_expected_size(size)
    cached_file_exists = os.path.exists(cached_file)
    cached_file_size_mismatch = _file_size_mismatch(cached_file, expected_size)
    if cached_file_exists and not cached_file_size_mismatch:
        _clear_missing_model_list_cache()
        return cached_file

    if cached_file_size_mismatch:
        try:
            current_size = os.path.getsize(cached_file)
        except Exception:
            current_size = "unknown"
        logger.info(f'模型文件大小不符，将重新下载: {cached_file} current={current_size}, expected={expected_size}')

    if (not cached_file_exists) or cached_file_size_mismatch:
        #logger.info(f'Downloading: "{url}" to {cached_file}')
        logger.info(f'正在下载文件: "{url}"。如果速度慢，建议自行用工具下载后保存到: {cached_file}。')
        def _download_with_progress_from_urls():
            last_error = None
            for candidate_url in download_urls:
                candidate_url = _apply_hf_mirror(candidate_url)
                try:
                    anyio.run(download_file_with_progress, candidate_url, cached_file, expected_size, effective_task_id)
                    return
                except DownloadCancelled:
                    raise
                except Exception as e:
                    last_error = e
                    logger.warning("模型下载地址失败，准备尝试下一个地址: %s", candidate_url)
            if last_error is not None:
                raise last_error
            raise RuntimeError("No download URL available")

        def _download_direct_from_urls():
            last_error = None
            for candidate_url in download_urls:
                candidate_url = _apply_hf_mirror(candidate_url)
                try:
                    download_url_to_file(candidate_url, cached_file, progress=progress)
                    shared.modelsinfo.refresh_file('add', cached_file, candidate_url)
                    _clear_missing_model_list_cache()
                    return
                except Exception as e:
                    last_error = e
                    logger.warning("模型下载地址失败，准备尝试下一个地址: %s", candidate_url)
            if last_error is not None:
                raise last_error
            raise RuntimeError("No download URL available")

        def _download_task():
            try:
                _download_with_progress_from_urls()
            except DownloadCancelled as e:
                print(f'下载任务:{effective_task_id} 已停止: {e}')
            except Exception as e:
                print(f'下载任务:{effective_task_id} 失败, 错误为: {e}')
            finally:
                with task_lock:
                    download_tasks.discard(effective_task_id)
                    download_cancel_requests.discard(effective_task_id)
                    if effective_task_id not in download_progress:
                        download_task_metadata.pop(effective_task_id, None)
                    logger.info(f"下载任务:{effective_task_id} 已完成, 从任务队列中清除.")
        if async_task:
            with task_lock:
                if effective_task_id in download_tasks:
                    print(f"下载任务:{effective_task_id} 已经在任务队列中.")
                    return
                try:
                    if effective_task_id in download_progress and isinstance(download_progress.get(effective_task_id), dict) and ("error" in download_progress.get(effective_task_id, {}) or download_progress.get(effective_task_id, {}).get("cancelled")):
                        del download_progress[effective_task_id]
                except Exception:
                    pass
                download_cancel_requests.discard(effective_task_id)
                _remember_download_task(
                    effective_task_id,
                    file_name=file_name,
                    model_dir=model_dir,
                    url=url,
                    size=expected_size,
                )
                download_progress[effective_task_id] = {
                    "percent": 0.0,
                    "current": 0,
                    "total": expected_size,
                    "file_name": file_name,
                    "queued": True,
                }
                download_tasks.add(effective_task_id)
                print(f"启动新的下载任务:{effective_task_id}.")
            thread_pool.submit(_download_task)
        else:
            if cached_file_size_mismatch:
                _download_with_progress_from_urls()
            else:
                _download_direct_from_urls()
    return cached_file


presets_model_list = {}
presets_previous_default_models = {}
presets_mtime = {}
missing_model_list_cache = {}
missing_model_list_cache_ttl = 12.0

def _clear_missing_model_list_cache():
    missing_model_list_cache.clear()

def _get_cached_preset_model_list(preset_name, user_did=None):
    arch_str = get_gpu_arch_str_in_preset_name()
    cache_names = []

    if preset_name.endswith('.'):
        if user_did:
            cache_names.append(f'{preset_name}{user_did[:7]}')
    else:
        if arch_str:
            cache_names.append(f'{preset_name}{arch_str}')
        cache_names.append(preset_name)

    for cache_name in cache_names:
        model_list = presets_model_list.get(cache_name)
        if model_list:
            return cache_name, model_list, presets_mtime.get(cache_name, 0)

    return None, None, 0

def _clean_model_name(value):
    return str(value or "").strip().replace('\\', os.sep).replace('/', os.sep).lstrip(os.sep)

def _clean_previous_model_list(values):
    if isinstance(values, str):
        values = [values]
    previous = []
    for value in values or []:
        name = _clean_model_name(value)
        if name and name not in previous:
            previous.append(name)
    return previous


def _preset_previous_default_model_info(config_preset):
    if not isinstance(config_preset, dict):
        return {}
    info = {}
    for current_key, previous_key in PREVIOUS_DEFAULT_MODEL_FIELDS:
        info[current_key] = _clean_model_name(config_preset.get(current_key))
        info[previous_key] = _clean_previous_model_list(config_preset.get(previous_key, []))
    return info


def _iter_previous_default_model_entries(previous_default_info):
    if isinstance(previous_default_info, dict):
        for current_key, previous_key in PREVIOUS_DEFAULT_MODEL_FIELDS:
            current_model = _clean_model_name(previous_default_info.get(current_key))
            previous_models = _clean_previous_model_list(previous_default_info.get(previous_key, []))
            if current_model and previous_models:
                yield current_model, previous_models
        return
    if isinstance(previous_default_info, (list, tuple)) and len(previous_default_info) >= 2:
        current_model = _clean_model_name(previous_default_info[0])
        previous_models = _clean_previous_model_list(previous_default_info[1])
        if current_model and previous_models:
            yield current_model, previous_models

def _same_model_name(left, right):
    left_name = _clean_model_name(left)
    right_name = _clean_model_name(right)
    if not left_name or not right_name:
        return False
    return left_name.casefold() == right_name.casefold() or os.path.basename(left_name).casefold() == os.path.basename(right_name).casefold()

def _is_default_model_entry(cata, path_file, default_model):
    if str(cata or "").strip().casefold() not in DEFAULT_MODEL_CATEGORIES:
        return False
    return _same_model_name(path_file, default_model)

def _existing_previous_default_model(cata, previous_default_info, path_file=None):
    if str(cata or "").strip().casefold() not in DEFAULT_MODEL_CATEGORIES:
        return ""
    for current_model, previous_models in _iter_previous_default_model_entries(previous_default_info):
        if path_file is not None and not _same_model_name(path_file, current_model):
            continue
        for previous_model in previous_models:
            file_path = _resolve_model_filepath(cata, previous_model)
            if file_path and os.path.exists(file_path):
                return previous_model
    return ""

def resolve_preset_default_model_choice(default_model, previous_default_models=None, catalogs=("checkpoints", "diffusion_models", "unet")):
    current = _clean_model_name(default_model)
    if not current:
        return current
    search_catalogs = [str(cata or "").strip() for cata in catalogs or () if str(cata or "").strip()]
    for cata in search_catalogs:
        file_path = _resolve_model_filepath(cata, current)
        if file_path and os.path.exists(file_path):
            return current
    for previous_model in previous_default_models or []:
        previous_name = _clean_model_name(previous_model)
        if not previous_name:
            continue
        for cata in search_catalogs:
            file_path = _resolve_model_filepath(cata, previous_name)
            if file_path and os.path.exists(file_path):
                return previous_name
    return current

def _get_preset_file_for_missing_models(preset_name, user_did=None):
    if preset_name.endswith('.'):
        if user_did is None:
            return ''
        try:
            from enhanced.simpleai import get_path_in_user_dir
            return os.path.abspath(os.path.join(get_path_in_user_dir('presets', user_did), f'{preset_name}json'))
        except Exception:
            return ''

    arch_str = get_gpu_arch_str_in_preset_name()
    preset_path = os.path.abspath(f'./presets/{preset_name}.json')
    if not os.path.exists(preset_path) and arch_str:
        preset_path_with_arch = os.path.abspath(f'./presets/{preset_name}{arch_str}.json')
        if os.path.exists(preset_path_with_arch):
            return preset_path_with_arch
    return preset_path

def _parse_model_list_entries(raw_model_list):
    model_list = []
    for model_entry in raw_model_list or []:
        if isinstance(model_entry, str):
            parts = model_entry.split(',')
            if len(parts) < 5:
                continue
            cata, path_file, size, hash10 = parts[:4]
            url = ",".join(parts[4:])
        elif isinstance(model_entry, (list, tuple)) and len(model_entry) >= 5:
            cata, path_file, size, hash10 = model_entry[:4]
            url = ",".join(str(part) for part in model_entry[4:] if str(part).strip())
        else:
            continue

        cata = str(cata).strip()
        path_file = str(path_file).strip()
        url = str(url).strip().strip('`')
        try:
            size = int(str(size).strip())
        except Exception:
            size = 0
        hash10 = str(hash10).strip()
        model_list.append((cata, path_file, size, hash10, url))
    return model_list

def _build_missing_model_details(model_list, previous_default_info=None):
    missing_models_with_details = []
    previous_default_info = previous_default_info or {}

    for cata, path_file, size, hash10, url in model_list:
        url = str(url or '').strip().strip('`')

        if path_file[:1] == '[' and path_file[-1:] == ']':
            result = shared.modelsinfo.get_model_names(cata, [f'{path_file[1:-1]}/'], casesensitive=True)
            if result is not None and len(result) >= size:
                continue
        else:
            file_path = _resolve_model_filepath(cata, path_file)
            if file_path and os.path.exists(file_path):
                if not size or os.path.getsize(file_path) == size:
                    continue
            if _existing_previous_default_model(cata, previous_default_info, path_file):
                continue

        human_size = format_size(size)
        if not url:
            url = f'{default_download_url_prefix}/{cata}/{path_file}'
        missing_models_with_details.append((cata, path_file, human_size, url, size))

    return missing_models_with_details

def _resolve_model_filepath(cata: str, path_file: str) -> str:
    try:
        file_path = shared.modelsinfo.get_model_filepath(cata, path_file)
    except Exception:
        file_path = ''
    if file_path and os.path.exists(file_path):
        return file_path

    if path_file and os.path.isabs(path_file) and os.path.exists(path_file):
        return os.path.abspath(path_file)

    normalized_rel = str(path_file or "").replace("\\", "/").lstrip("/")
    rel_parts = [p for p in normalized_rel.split("/") if p]

    try:
        from modules.config import model_cata_map, path_models_root
    except Exception:
        model_cata_map = {}
        path_models_root = "models"

    roots = model_cata_map.get(cata, [])
    if isinstance(roots, str):
        roots = [roots]
    elif not isinstance(roots, list):
        try:
            roots = list(roots)
        except Exception:
            roots = []

    legacy_roots = []
    for legacy_cata in LEGACY_CATEGORY_SEARCH_PATHS.get(cata, ()):
        legacy_values = model_cata_map.get(legacy_cata, [])
        if isinstance(legacy_values, str):
            legacy_values = [legacy_values]
        elif not isinstance(legacy_values, list):
            try:
                legacy_values = list(legacy_values)
            except Exception:
                legacy_values = []
        legacy_roots.extend(legacy_values)
        legacy_roots.append(os.path.join(path_models_root, legacy_cata))

    roots = list(roots) + [os.path.join(path_models_root, cata)] + legacy_roots
    for base_dir in roots:
        if not base_dir:
            continue
        candidate = os.path.abspath(os.path.join(base_dir, *rel_parts))
        if os.path.exists(candidate):
            return candidate

    try:
        manual_path = os.path.abspath(os.path.join('..', '..', 'SimpleModels', cata, *rel_parts))
        if os.path.exists(manual_path):
            return manual_path
    except Exception:
        pass

    return ''

def refresh_model_list(presets, user_did=None):
    from enhanced.simpleai import get_path_in_user_dir
    global presets_model_list, presets_mtime

    path_preset = os.path.abspath(f'./presets/')
    if user_did:
        user_path_preset = get_path_in_user_dir('presets', user_did)
    if len(presets)>0:
        for preset in presets:
            if preset.endswith('.'):
                if user_did is None:
                    continue
                preset_file = os.path.join(user_path_preset, f'{preset}json')
                preset = f'{preset}{user_did[:7]}'
            else:
                preset_file = os.path.join(path_preset, f'{preset}.json')
            try:
                mtime = os.path.getmtime(preset_file)
                if preset not in presets_mtime:
                    presets_mtime[preset] = 0
                if mtime>presets_mtime[preset]:
                    presets_mtime[preset] = mtime
                    with open(preset_file, "r", encoding="utf-8") as json_file:
                        config_preset = json.load(json_file)
                    if 'model_list' in config_preset:
                        model_list = _parse_model_list_entries(config_preset.get('model_list', []))
                        presets_model_list[preset] = model_list
                        presets_previous_default_models[preset] = _preset_previous_default_model_info(config_preset)
                        _clear_missing_model_list_cache()
            except Exception as e:
                logger.info(f'load preset file failed: {preset_file}')
                continue
    return
            

def check_models_exists(preset, user_did=None):
    from modules.config import path_models_root
    global presets_model_list

    if preset.endswith('.'):
        if user_did is None:
            return False
        preset = f'{preset}{user_did[:7]}'
    model_list = [] if preset not in presets_model_list else presets_model_list[preset]
    previous_default_info = presets_previous_default_models.get(preset, {})
    if len(model_list)>0:
        for cata, path_file, size, hash10, url in model_list:
            if path_file[:1]=='[' and path_file[-1:]==']':
                path_file = [f'{path_file[1:-1]}/']
                result = shared.modelsinfo.get_model_names(cata, path_file, casesensitive=True)
                if result is None or len(result)<size:
                    logger.debug(f'Missing model dir in preset({preset}): {cata}, filter={path_file}, len={size}\nresult={result}')
                    return False
            else:
                file_path = _resolve_model_filepath(cata, path_file)

                if file_path is None or file_path == '' or not _file_size_matches(file_path, size):
                    if _existing_previous_default_model(cata, previous_default_info, path_file):
                        continue
                    logger.debug(f'Missing model file in preset({preset}): {cata}, {path_file}')
                    return False
        return True
    return False
def get_gpu_arch_str_in_preset_name():
    if shared.gpu_arch:
        if shared.gpu_arch.lower() == 'sm120':
            return '_fp4'
        else:
            return '_int4'
    return ''
def is_models_file_absent(preset_name, user_did=None):
    global presets_model_list
    if shared.args.disable_backend:
        return False
    if preset_name in presets_model_list:
        if check_models_exists(preset_name, user_did):
            return False
        else:
            return True

    # 先尝试原始路径
    preset_path = os.path.abspath(f'./presets/{preset_name}.json')

    # 如果原始路径不存在，尝试根据GPU架构添加_fp4或_int4后缀
    if not os.path.exists(preset_path):
        arch_str = get_gpu_arch_str_in_preset_name()
        if arch_str:
            preset_path_with_arch = os.path.abspath(f'./presets/{preset_name}{arch_str}.json')
            if os.path.exists(preset_path_with_arch):
                preset_path = preset_path_with_arch

    if os.path.exists(preset_path):
        with open(preset_path, "r", encoding="utf-8") as json_file:
            config_preset = json.load(json_file)
        previous_default_info = _preset_previous_default_model_info(config_preset)

        if config_preset.get("model_list"):
            for model_entry in config_preset["model_list"]:
                # 处理不同格式的model_entry
                if isinstance(model_entry, list) and len(model_entry) >= 2:
                    cata = model_entry[0]
                    path_file = model_entry[1]

                    # 检查文件是否存在
                    file_path = _resolve_model_filepath(cata, path_file)
                    if file_path is None or file_path == '' or not os.path.exists(file_path):
                        if _existing_previous_default_model(cata, previous_default_info, path_file):
                            continue
                        # 记录缺失的文件信息
                        logger.debug(f'Missing model file in preset({preset_name}): {cata}, {path_file}')
                        return True
                elif isinstance(model_entry, str):
                    # 处理字符串格式的条目
                    parts = model_entry.split(',')
                    if len(parts) >= 2:
                        cata = parts[0].strip()
                        path_file = parts[1].strip()

                        # 检查文件是否存在
                        file_path = _resolve_model_filepath(cata, path_file)
                        if file_path is None or file_path == '' or not os.path.exists(file_path):
                            if _existing_previous_default_model(cata, previous_default_info, path_file):
                                continue
                            # 记录缺失的文件信息
                            logger.debug(f'Missing model file in preset({preset_name}): {cata}, {path_file}')
                            return True

    return False

def format_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    size_name = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024
        i += 1
    return f"{size_bytes:.2f} {size_name[i]}"

def get_missing_model_list(preset_name, user_did=None):
    global missing_model_list_cache

    cached_name, model_list, source_mtime = _get_cached_preset_model_list(preset_name, user_did)
    preset_path = ''
    source_key = cached_name or preset_name

    if model_list is None:
        preset_path = _get_preset_file_for_missing_models(preset_name, user_did)
        if not preset_path or not os.path.exists(preset_path):
            return []
        source_mtime = os.path.getmtime(preset_path)
        source_key = preset_path

    cache_key = (source_key, user_did or '', source_mtime, len(model_list or ()))
    now = time.monotonic()
    cached = missing_model_list_cache.get(cache_key)
    if cached and now - cached[0] <= missing_model_list_cache_ttl:
        return list(cached[1])

    previous_default_info = {}
    if cached_name:
        previous_default_info = presets_previous_default_models.get(cached_name, {})

    if model_list is None:
        with open(preset_path, "r", encoding="utf-8") as json_file:
            config_preset = json.load(json_file)
        model_list = _parse_model_list_entries(config_preset.get('model_list', []))
        previous_default_info = _preset_previous_default_model_info(config_preset)

    missing_models_with_details = _build_missing_model_details(model_list, previous_default_info)
    missing_model_list_cache[cache_key] = (now, tuple(missing_models_with_details))

    if len(missing_model_list_cache) > 64:
        oldest_keys = sorted(missing_model_list_cache, key=lambda key: missing_model_list_cache[key][0])[:16]
        for old_key in oldest_keys:
            missing_model_list_cache.pop(old_key, None)

    return missing_models_with_details

def get_missing_model_list_from_entries(preset_name, raw_model_list, user_did=None, source_mtime=0, previous_default_info=None):
    global missing_model_list_cache

    if not raw_model_list:
        return []

    if isinstance(previous_default_info, dict):
        previous_default_info = _preset_previous_default_model_info(previous_default_info)
    elif previous_default_info is None:
        previous_default_info = {}

    cache_key = (f'inline:{preset_name}', user_did or '', source_mtime or 0, len(raw_model_list or ()), repr(previous_default_info))
    now = time.monotonic()
    cached = missing_model_list_cache.get(cache_key)
    if cached and now - cached[0] <= missing_model_list_cache_ttl:
        return list(cached[1])

    model_list = _parse_model_list_entries(raw_model_list)
    missing_models_with_details = _build_missing_model_details(model_list, previous_default_info)
    missing_model_list_cache[cache_key] = (now, tuple(missing_models_with_details))
    return missing_models_with_details

def get_download_status(file_name):
    global download_progress
    return download_progress.get(file_name)

default_download_url_prefix = 'https://huggingface.co/metercai/SimpleSDXL2/resolve/main/SimpleModels'

def download_model_entry(cata, path_file, size=0, url=None, user_did=None, async_task=True):
    from modules.config import path_models_root, model_cata_map
    global default_download_url_prefix

    if user_did is None:
        logger.warning("download_model_entry skipped: user_did is None")
        return False
    if shared.args.disable_backend:
        logger.warning("download_model_entry skipped: backend is disabled")
        return False

    cata = str(cata or "").strip()
    path_file = str(path_file or "").strip()
    if not cata or not path_file:
        return False

    try:
        size = int(size or 0)
    except Exception:
        size = 0

    if path_file[:1] == '[' and path_file[-1:] == ']':
        task_id = f"{cata}/{path_file}".replace("\\", "/").strip("/")
        _mark_download_error(
            task_id,
            "Folder-package zip downloads are no longer supported. Please install this model folder manually.",
            path_file.strip("[]"),
        )
        return False
    else:
        file_name = path_file.replace('\\', '/').replace(os.sep, '/')

    task_id = f"{cata}/{file_name}".replace("\\", "/").strip("/")

    if cata in model_cata_map:
        model_dirs = model_cata_map[cata]
    else:
        model_dirs = [os.path.join(path_models_root, cata)]

    if isinstance(model_dirs, str):
        model_dirs = [model_dirs]
    elif not isinstance(model_dirs, list):
        model_dirs = list(model_dirs)

    preferred_dir = None
    for base_dir in model_dirs:
        try:
            if os.path.basename(os.path.normpath(base_dir)).lower() == str(cata).lower():
                preferred_dir = base_dir
                break
        except Exception:
            continue
    if preferred_dir is None:
        preferred_dir = model_dirs[0] if model_dirs else os.path.join(path_models_root, cata)

    mismatch_path = None
    for base_dir in model_dirs:
        candidate_path = os.path.abspath(os.path.join(base_dir, file_name))
        if not os.path.exists(candidate_path):
            continue
        if _file_size_matches(candidate_path, size):
            _clear_missing_model_list_cache()
            return task_id
        if mismatch_path is None:
            mismatch_path = candidate_path

    full_path_file = mismatch_path or os.path.abspath(os.path.join(preferred_dir, file_name))

    if url is None or url == '':
        url = f'{default_download_url_prefix}/{cata}/{path_file}'

    if mismatch_path:
        logger.info(f'The model file size mismatches, ready to redownload single: {file_name} -> {full_path_file} from {url}')
    else:
        logger.info(f'The model file is not exists, ready to download single: {file_name} -> {full_path_file} from {url}')
    load_file_from_url(
        url=url,
        model_dir=os.path.dirname(full_path_file),
        file_name=os.path.basename(full_path_file),
        async_task=async_task,
        size=size,
        task_id=task_id,
    )
    return task_id

def download_model_files(preset, user_did=None, async_task=False):
    from modules.config import path_models_root, model_cata_map
    global presets_model_list, default_download_url_prefix, download_queue

    if user_did is None:
        logger.warning("download_model_files skipped: user_did is None")
        return False
    if shared.args.disable_backend:
        return False
    if preset.endswith('.'):
        if user_did is None:
            return False
        preset = f'{preset}{user_did[:7]}'
    # 尝试根据GPU架构获取合适的预置包名称
    arch_str = get_gpu_arch_str_in_preset_name()
    model_list = []

    # 首先尝试使用架构特定的预置包名称
    if arch_str and f'{preset}{arch_str}' in presets_model_list:
        model_list = presets_model_list[f'{preset}{arch_str}']
    # 如果没有找到，尝试使用原始预置包名称
    elif preset in presets_model_list:
        model_list = presets_model_list[preset]

    if len(model_list)>0:
        for cata, path_file, size, hash10, url in model_list:
            if path_file[:1]=='[' and path_file[-1:]==']':
                result = shared.modelsinfo.get_model_names(cata, [f'{path_file[1:-1]}/'], casesensitive=True)
                if result and len(result)>=size:
                    continue
                task_id = f"{cata}/{path_file}".replace("\\", "/").strip("/")
                _mark_download_error(
                    task_id,
                    "Folder-package zip downloads are no longer supported. Please install this model folder manually.",
                    path_file.strip("[]"),
                )
                continue
            else:
                file_name = path_file.replace('\\', '/').replace(os.sep, '/')
                task_id = f"{cata}/{file_name}".replace("\\", "/")

            if cata in model_cata_map:
                model_dirs = model_cata_map[cata]
            else:
                model_dirs = [os.path.join(path_models_root, cata)]

            if isinstance(model_dirs, str):
                model_dirs = [model_dirs]
            elif not isinstance(model_dirs, list):
                model_dirs = list(model_dirs)

            found_existing = False
            mismatch_path = None
            for base_dir in model_dirs:
                candidate_path = os.path.abspath(os.path.join(base_dir, file_name))
                if os.path.exists(candidate_path):
                    if not _file_size_matches(candidate_path, size):
                        if mismatch_path is None:
                            mismatch_path = candidate_path
                        continue
                    found_existing = True
                    break
            if found_existing:
                _clear_missing_model_list_cache()
                continue

            preferred_dir = None
            for base_dir in model_dirs:
                try:
                    if os.path.basename(os.path.normpath(base_dir)).lower() == str(cata).lower():
                        preferred_dir = base_dir
                        break
                except Exception:
                    continue
            if preferred_dir is None:
                preferred_dir = model_dirs[0] if model_dirs else os.path.join(path_models_root, cata)

            full_path_file = mismatch_path or os.path.abspath(os.path.join(preferred_dir, file_name))
            model_dir = os.path.dirname(full_path_file)
            file_name = os.path.basename(full_path_file)
            if url is None or url == '':
                url = f'{default_download_url_prefix}/{cata}/{path_file}'
            if mismatch_path:
                logger.info(f'The model file size mismatches, ready to redownload: {file_name} -> {full_path_file} from {url}')
            else:
                logger.info(f'The model file is not exists, ready to download: {file_name} -> {full_path_file} from {url}')
            if not async_task:
                load_file_from_url(
                    url=url,
                    model_dir=model_dir,
                    file_name=file_name,
                    task_id=task_id
                )
            else:
                load_file_from_url(
                    url=url,
                    model_dir=model_dir,
                    file_name=file_name,
                    async_task=True,
                    size=size,
                    task_id=task_id
                )
    return
