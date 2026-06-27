import os
import ssl
import sys
import json
import platform
import re
from importlib import metadata as importlib_metadata
from packaging import version as packaging_version
import shared
from modules.access_mode import is_local_mode
import comfy.comfy_version as comfy_version
import enhanced.version as version
import socket
import logging
import shutil
import subprocess
import torch
from build_launcher import download_if_updated
from modules.launch_util import is_installed, is_installed_version, run, python, requirements_met, delete_folder_content, index_url, extra_index_url, target_path_install
from enhanced.logger import setup_logger, now_string, get_log_file
os.environ["NO_ALBUMENTATIONS_UPDATE"] = "1"
os.environ["RUST_LOG"] = os.environ.get("SIMPAI_RUST_LOG", "off")
setup_logger(log_level='INFO')
logger = logging.getLogger(__name__)

logger.debug('[System ARGV] ' + str(sys.argv))

def _launch_arg_was_set(flag, argv=None):
    argv = sys.argv if argv is None else argv
    prefix = f"{flag}="
    return any(str(arg) == flag or str(arg).startswith(prefix) for arg in argv)

root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(root)
os.chdir(root)

ORT_CUDA13_INDEX_URL = os.environ.get(
    "ORT_CUDA13_INDEX_URL",
    "https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/ort-cuda-13-nightly/pypi/simple/",
)
ORT_CUDA13_DEFAULT_PACKAGE = "onnxruntime-gpu==1.27.0.dev20260511001"
ORT_CUDA13_DEFAULT_WHEEL_URL = (
    "https://www.modelscope.cn/models/windecay/SimpAI_dev/resolve/master/libs/"
    "onnxruntime-gpu/onnxruntime_gpu-1.27.0.dev20260511001-cp313-cp313-win_amd64.whl"
)

def _default_ort_cuda13_wheel_url():
    is_windows_cp313_amd64 = (
        platform.system() == "Windows"
        and sys.version_info[:2] == (3, 13)
        and platform.machine().lower() in ("amd64", "x86_64")
    )
    return ORT_CUDA13_DEFAULT_WHEEL_URL if is_windows_cp313_amd64 else ""

ORT_CUDA13_PACKAGE = os.environ.get("ORT_CUDA13_PACKAGE", ORT_CUDA13_DEFAULT_PACKAGE)
ORT_CUDA13_WHEEL_URL = os.environ.get(
    "ORT_CUDA13_WHEEL_URL",
    _default_ort_cuda13_wheel_url() if "ORT_CUDA13_PACKAGE" not in os.environ else "",
)
ORT_CUDA13_INFO_PREFIX = "SIMPAI_ORT_INFO="

OBSOLETE_CUSTOM_NODE_FOLDERS = ()

def cleanup_obsolete_custom_nodes():
    custom_nodes_root = os.path.join(root, "comfy", "custom_nodes")
    if not os.path.isdir(custom_nodes_root):
        return
    for folder_name in OBSOLETE_CUSTOM_NODE_FOLDERS:
        target_path = os.path.join(custom_nodes_root, folder_name)
        if not os.path.isdir(target_path):
            continue
        try:
            shutil.rmtree(target_path)
            logger.info(f"[Cleanup] Removed obsolete custom node folder: {target_path}")
        except Exception as e:
            logger.warning(f"[Cleanup] Failed to remove obsolete custom node folder: {target_path} ({e})")

# cleanup_obsolete_custom_nodes()

os.environ["SIMPAI_LOG_FILE"] = get_log_file()
os.environ.setdefault("PYOPENCL_CTX", "0")
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
os.environ["translators_default_region"] = "China"
if "GRADIO_SERVER_PORT" not in os.environ:
    os.environ["GRADIO_SERVER_PORT"] = "7865"

ssl._create_default_https_context = ssl._create_unverified_context

def _make_pip_env():
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_USER"] = "0"
    env["PIP_PROGRESS_BAR"] = "raw"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env

def install_package_with_retry(pkg_name, pkg_version=None, description=None):
    """尝试安装包，先使用阿里源，如果失败则尝试使用清华源"""
    desc = description or f'Installing {pkg_name}'
    errdesc = f"Couldn't install {pkg_name}"

    try:
        if pkg_version:
            pkg_command = f'pip install -U {pkg_name}=={pkg_version} -i {index_url}'
        else:
            pkg_command = f'pip install -U {pkg_name} -i {index_url}'

        run(f'"{python}" -s -m {pkg_command}', desc, errdesc, custom_env=_make_pip_env(), live=True)
        return True
    except Exception as e:
        logger.warning(f"阿里源安装{pkg_name}失败: {str(e)}")
        logger.info("尝试使用清华源镜像...")

    try:
        if pkg_version:
            pkg_command = f'pip install -U {pkg_name}=={pkg_version} -i {extra_index_url}'
        else:
            pkg_command = f'pip install -U {pkg_name} -i {extra_index_url}'

        run(f'"{python}" -s -m {pkg_command}', desc, errdesc, custom_env=_make_pip_env(), live=True)
        return True
    except Exception as e:
        logger.error(f"使用清华源安装{pkg_name}失败: {str(e)}")
        return False

def _simpleai_base_wheel_filename(ver_required):
    current_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    platform_os = platform.system()
    if platform_os == "Windows":
        cp313_filename = f"simpleai_base-{ver_required}-cp313-cp313-win_amd64.whl"
        if current_tag == "cp313" or os.path.exists(os.path.join(root, "enhanced", "libs", cp313_filename)):
            return cp313_filename
        return f"simpleai_base-{ver_required}-{current_tag}-{current_tag}-win_amd64.whl"

    if platform_os == "Darwin":
        if platform.machine() == "arm64":
            return f"simpleai_base-{ver_required}-{current_tag}-{current_tag}-macosx_11_0_arm64.whl"
        return f"simpleai_base-{ver_required}-{current_tag}-{current_tag}-macosx_10_12_x86_64.whl"

    return f"simpleai_base-{ver_required}-{current_tag}-{current_tag}-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"

def _simpleai_base_has_required_apis():
    required = [
        "get_local_did",
        "get_default_workspace_did",
        "can_user_generate",
        "can_user_download_models",
        "get_user_access_list",
        "approve_user_with_permissions",
        "reject_user",
        "set_user_can_generate",
        "set_user_can_download_models",
        "get_guest_can_generate",
        "set_guest_can_generate",
        "get_guest_can_download_models",
        "set_guest_can_download_models",
    ]
    code = (
        "import json, simpleai_base.simpleai_base as sb; "
        f"required={required!r}; "
        "print(json.dumps([name for name in required if not hasattr(sb.SimpleAI, name)]))"
    )
    try:
        result = subprocess.run(
            [python, "-s", "-c", code],
            capture_output=True,
            text=True,
            env=_make_pip_env(),
            timeout=30,
        )
    except Exception as e:
        logger.warning(f"检查 simpleai_base API 失败，将尝试重装: {e}")
        return False
    if result.returncode != 0:
        logger.warning(f"检查 simpleai_base API 失败，将尝试重装: {result.stderr.strip()}")
        return False
    try:
        missing = json.loads((result.stdout or "[]").strip().splitlines()[-1])
    except Exception:
        missing = []
    if missing:
        logger.warning(f"simpleai_base 缺少本地身份 API，将尝试重装: {', '.join(missing)}")
        return False
    return True

def _installed_package_version(package):
    try:
        return importlib_metadata.version(package)
    except Exception as e:
        logger.debug(f"读取 {package} 已安装版本失败: {e}")
        return None

def _installed_onnxruntime_cuda_info():
    code = r"""
import contextlib
import io
import json

info = {"version": None, "providers": [], "cuda_build": None, "debug": ""}
try:
    import onnxruntime as ort
    info["version"] = getattr(ort, "__version__", None)
    info["providers"] = list(ort.get_available_providers())
    debug_buffer = io.StringIO()
    with contextlib.redirect_stdout(debug_buffer), contextlib.redirect_stderr(debug_buffer):
        try:
            ort.print_debug_info()
        except Exception as e:
            print(f"print_debug_info failed: {e}")
    info["debug"] = debug_buffer.getvalue()
except Exception as e:
    info["debug"] = f"import onnxruntime failed: {e}"
print("SIMPAI_ORT_INFO=" + json.dumps(info, ensure_ascii=False))
"""
    try:
        result = subprocess.run(
            [python, "-s", "-X", "utf8", "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_make_pip_env(),
            timeout=60,
        )
    except Exception as e:
        logger.debug(f"检查 ONNX Runtime CUDA build 失败: {e}")
        return {}

    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    info = {}
    for line in output.splitlines():
        if not line.startswith(ORT_CUDA13_INFO_PREFIX):
            continue
        try:
            info = json.loads(line[len(ORT_CUDA13_INFO_PREFIX):])
        except Exception as e:
            logger.debug(f"解析 ONNX Runtime CUDA 信息失败: {e}")
        break

    if not info:
        logger.debug(f"无法读取 ONNX Runtime CUDA 信息: {output.strip()}")
        return {}

    debug_text = info.get("debug") or output
    match = re.search(r"CUDA version used in build:\s*([0-9.]+)", debug_text)
    if match:
        info["cuda_build"] = match.group(1)
    return info

def _onnxruntime_cuda13_ready():
    info = _installed_onnxruntime_cuda_info()
    cuda_build = str(info.get("cuda_build") or "")
    providers = info.get("providers") or []
    has_cpu_ort_package = _installed_package_version("onnxruntime") is not None
    return not has_cpu_ort_package and cuda_build.startswith("13.") and "CUDAExecutionProvider" in providers

def _onnxruntime_cuda13_install_attempts():
    attempts = []
    if ORT_CUDA13_WHEEL_URL:
        attempts.append((
            "ModelScope wheel",
            f'"{python}" -s -m pip install --pre --no-deps --force-reinstall "{ORT_CUDA13_WHEEL_URL}"',
        ))
    attempts.append((
        "ONNX Runtime nightly index",
        f'"{python}" -s -m pip install --pre --no-deps --force-reinstall --index-url {ORT_CUDA13_INDEX_URL} {ORT_CUDA13_PACKAGE}',
    ))
    return attempts

def install_onnxruntime_gpu_cuda13():
    info = _installed_onnxruntime_cuda_info()
    cuda_build = str(info.get("cuda_build") or "")
    providers = info.get("providers") or []
    has_cpu_ort_package = _installed_package_version("onnxruntime") is not None
    if not has_cpu_ort_package and cuda_build.startswith("13.") and "CUDAExecutionProvider" in providers:
        logger.info(f"ONNX Runtime CUDA 13 already installed: {info.get('version')} (CUDA build {cuda_build})")
        return True
    if has_cpu_ort_package:
        logger.info("检测到 onnxruntime 与 onnxruntime-gpu 同时存在，将重装 ONNX Runtime GPU。")

    logger.info(
        f"安装 ONNX Runtime CUDA 13 nightly。当前版本: {info.get('version') or 'missing'}, "
        f"CUDA build: {cuda_build or 'unknown'}, providers: {providers or 'unknown'}"
    )

    try:
        run(
            f'"{python}" -s -m pip uninstall -y onnxruntime onnxruntime-gpu',
            "Removing old ONNX Runtime packages",
            "Could not remove old ONNX Runtime packages",
            custom_env=_make_pip_env(),
            live=True,
        )
    except Exception as e:
        logger.warning(f"卸载旧 ONNX Runtime 包失败，将继续尝试安装 CUDA 13 版: {e}")

    for source_name, command in _onnxruntime_cuda13_install_attempts():
        try:
            run(
                command,
                f"Installing ONNX Runtime GPU CUDA 13 from {source_name}",
                f"Could not install ONNX Runtime GPU CUDA 13 from {source_name}",
                custom_env=_make_pip_env(),
                live=True,
            )
        except Exception as e:
            logger.warning(f"安装 ONNX Runtime CUDA 13 来源失败：{source_name}: {e}")
            continue

        if _onnxruntime_cuda13_ready():
            logger.info(f"ONNX Runtime CUDA 13 已从 {source_name} 安装完成。")
            return True

        installed = _installed_onnxruntime_cuda_info()
        logger.warning(
            f"ONNX Runtime CUDA 13 来源校验未通过：{source_name}, "
            f"version={installed.get('version')}, cuda_build={installed.get('cuda_build')}, "
            f"providers={installed.get('providers')}"
        )

    installed = _installed_onnxruntime_cuda_info()
    logger.error(
        f"ONNX Runtime CUDA 13 安装后校验失败: version={installed.get('version')}, "
        f"cuda_build={installed.get('cuda_build')}, providers={installed.get('providers')}"
    )
    return False

def check_base_environment():
    print(f"{now_string()} Python {sys.version}")
    print(f"{now_string()} Comfyd version: {comfy_version.version}")
    print(f'{now_string()} {version.get_branch()} version: {version.get_simpai_ver()}')
    print(f'{now_string()} ✦ | 兴趣使然的版本 | ✦ by冰華 ✦')

    base_pkg = "simpleai_base"
    ver_required = "0.3.48"
    REINSTALL_BASE = False
    base_branch = "studio"
    base_url = f"https://www.modelscope.cn/models/windecay/SimpAI_dev/resolve/master/libs/{base_branch}"
    base_file = _simpleai_base_wheel_filename(ver_required)
    base_path = os.path.abspath(os.path.join(root, f'enhanced/libs/{base_file}'))
    base_url = f'{base_url}/{base_file}'
    has_update_whl = download_if_updated(base_url, base_path)
    has_required_base_apis = _simpleai_base_has_required_apis() if is_installed(base_pkg) else False
    if has_update_whl or REINSTALL_BASE or not is_installed_version(base_pkg, ver_required) or not has_required_base_apis:
        if os.path.exists(base_path):
            if not is_installed(base_pkg):
                run(f'"{python}" -s -m pip install {base_path}', f'Install {base_pkg} {ver_required}', custom_env=_make_pip_env())
            else:
                version_installed = _installed_package_version(base_pkg)
                version_mismatch = version_installed is None or packaging_version.parse(ver_required) != packaging_version.parse(version_installed)
                if REINSTALL_BASE or version_mismatch or not has_required_base_apis:
                    logger.info(f"正在更新 {base_pkg}: {version_installed} -> {ver_required}")
                    run(f'"{python}" -s -m pip install -U {base_path}', f'Update {base_pkg} {ver_required}', custom_env=_make_pip_env())
        else:
            if not is_installed(base_pkg):
                logger.error(f"缺失必要的包 {base_pkg} 且下载失败，程序可能无法正常运行。请检查网络连接并重新启动。")
            else:
                version_installed = _installed_package_version(base_pkg) or "unknown"
                if not is_installed_version(base_pkg, ver_required):
                    logger.warning(f"无法下载更新包 {base_pkg} {ver_required}，当前版本为 {version_installed}，将尝试继续启动。")
                elif not has_required_base_apis:
                    logger.warning(f"无法下载更新包 {base_pkg} {ver_required}，当前版本 {version_installed} 缺少本地身份 API，将尝试继续启动。")
                else:
                    logger.warning(f"无法下载更新包 {base_pkg}，将继续使用当前版本 {version_installed}。")

    if torch.__version__ == '2.9.1+cu130':
        logger.info(f'当前环境：PyTorch 2.9.1+CUDA 13.0. 50系以上显卡支持Nvfp4模型加速推理.')
        if not install_onnxruntime_gpu_cuda13():
            logger.error("无法安装 ONNX Runtime CUDA 13 nightly，DWPose/ReActor 等 ONNX 节点可能降到 CPU。")
        update_pkgs = [
            ('comfyui-frontend-package', '1.45.19'),
            ('comfyui-workflow-templates', '0.10.7'),
            ('comfyui-embedded-docs', '0.5.5'),
            ('comfy-kitchen', '0.2.12'),
            ('comfy-aimdo', '0.4.10'),
            ('av', '17.0.0')
        ]
        for (update_pkg_name, update_pkg_version) in update_pkgs:
            if not is_installed_version(update_pkg_name, update_pkg_version):
                success = install_package_with_retry(update_pkg_name, update_pkg_version)
                if not success:
                    logger.error(f"无法安装{update_pkg_name}，请检查网络状态")
    else:
        logger.warning(f'Current PyTorch is {torch.__version__}; SimpAI_Studio now targets PyTorch 2.9.1+cu130.')
        logger.warning(f'当前 PyTorch 是 {torch.__version__}；SimpAI_Studio 当前启动流程只保留 PyTorch 2.9.1+cu130 路径。')

        logger.info(f'环境缺失必要组件或系统不匹配。请参考SimpAI.cn的安装说明重新部署。')
        logger.info(f'The program running environment lacks necessary components or the system does not match. Please refer to the installation instructions on SimpAI.cn to redeploy.')

    if not is_installed(base_pkg):
        logger.error(f"FATAL ERROR: {base_pkg} is not installed and could not be downloaded/installed.")
        logger.error("程序缺失必要的组件且下载失败，无法继续启动。请检查网络连接并重新启动程序。")
        sys.exit(1)

    from simpleai_base import simpleai_base
    logger.info("Checking ...")
    token = simpleai_base.init_local()
    sysinfo = json.loads(token.get_sysinfo().to_json())
    sysinfo.update(dict(did=token.get_sys_did()))
    logger.info(f'GPU: {sysinfo.get("gpu_name")}, RAM: {sysinfo.get("ram_total")}MB, SWAP: {sysinfo.get("ram_swap")}MB, VRAM: {sysinfo.get("gpu_memory")}MB, DiskFree: {sysinfo.get("disk_free")}MB, CUDA: {sysinfo.get("cuda")}, HOST: {sysinfo.get("host_type")}')
    #print(f'[SimpleAI] root: {sysinfo["root_dir"]}, sys_name: {sysinfo["root_name"]}, dev_name:{sysinfo["host_name"]}')

    cuda_raw = sysinfo.get("cuda", None) if isinstance(sysinfo, dict) else None
    min_cuda_code = 12040
    if torch.__version__ == '2.9.1+cu130':
        min_cuda_code = 13000
    cuda_code = None

    def cuda_code_to_string(code: int) -> str:
        major = code // 1000
        minor = (code % 1000) // 10
        patch = code % 10
        if patch:
            return f"{major}.{minor}.{patch}"
        return f"{major}.{minor}"

    try:
        if isinstance(cuda_raw, (int, float)) and not isinstance(cuda_raw, bool):
            cuda_code = int(cuda_raw)
        elif isinstance(cuda_raw, str):
            s = cuda_raw.strip()
            if s.isdigit():
                cuda_code = int(s)
            else:
                m = re.search(r"\bcu(\d{3})\b", s, flags=re.IGNORECASE)
                if m:
                    cu = int(m.group(1))
                    cuda_code = (cu // 10) * 1000 + (cu % 10) * 10
                else:
                    m = re.search(r"(\d+)\.(\d+)", s)
                    if m:
                        major = int(m.group(1))
                        minor = int(m.group(2))
                        cuda_code = major * 1000 + minor * 10
    except Exception:
        cuda_code = None

    if cuda_code is not None and cuda_code < min_cuda_code:
        cuda_display = cuda_code_to_string(cuda_code)
        min_display = cuda_code_to_string(min_cuda_code)
        min_cu_display = f"cu{(min_cuda_code // 1000) * 10 + ((min_cuda_code % 1000) // 10)}"
        logger.warning(f'CUDA driver/runtime version is too low (CUDA: {cuda_display}). Requires CUDA >= {min_display} ({min_cu_display}). Please update your GPU driver: https://www.nvidia.cn/drivers/')
        logger.warning(f'检测到CUDA驱动/运行时版本过低(CUDA: {cuda_display})。需要CUDA >= {min_display} ({min_cu_display})。请更新显卡驱动否则无法启动：https://www.nvidia.cn/drivers/')

    if (sysinfo.get("ram_total", 0)+sysinfo.get("ram_swap", 0))<65536 and not shared.args.disable_backend:
        logger.info(f'The total virtual memory capacity of the system is too small, which will affect the loading and computing efficiency of the model. Please expand the total virtual memory capacity of the system to be greater than 40G.')
        logger.info(f'系统虚拟内存总容量过小，容易引发后端崩溃，建议扩充系统虚拟内存总容量(RAM+SWAP)大于64G。')
        logger.info(f'有任何疑问可到SimpAI_Studio的QQ群交流: 1005085136')

    return token, sysinfo


    #Intel Arc
    #conda install pkg-config libuv
    #python -m pip install torch==2.1.0.post2 torchvision==0.16.0.post2 torchaudio==2.1.0.post2 intel-extension-for-pytorch==2.1.30 --extra-index-url https://pytorch-extension.intel.com/release-whl/stable/xpu/cn/

def prepare_environment():
    REINSTALL_ALL = False
    torch_ver = '2.9.1+cu130'
    torchvision_ver = '0.24.1+cu130'
    torchaudio_ver = '2.9.1+cu130'
    torch_index_url = os.environ.get('TORCH_INDEX_URL', 'https://download.pytorch.org/whl/cu130')
    torch_command = os.environ.get(
        'TORCH_COMMAND',
        f'pip install torch=={torch_ver} torchvision=={torchvision_ver} torchaudio=={torchaudio_ver} --extra-index-url {torch_index_url}',
    )
    requirements_file = os.environ.get('REQS_FILE', 'requirements.txt')
    torch_command += target_path_install
    torch_command += f' -i {index_url} '

    if REINSTALL_ALL or not is_installed('torch') or not is_installed('torchvision') or not is_installed('torchaudio'):
        run(f'"{python}" -m {torch_command}', 'Installing torch, torchvision and torchaudio', 'Could not install PyTorch', live=True)

    if REINSTALL_ALL or not requirements_met(requirements_file):
        logger.info('Runtime dependencies do not match requirements.txt. Please redeploy the environment if startup fails.')
    return

def create_placeholder_files():
    checkpoints_dir = config.paths_checkpoints
    if isinstance(checkpoints_dir, list) and checkpoints_dir:
        checkpoints_dir = checkpoints_dir[0]
    if not os.path.exists(checkpoints_dir):
        try:
            os.makedirs(checkpoints_dir)
            logger.info(f"Created checkpoints directory at {checkpoints_dir}")
        except Exception as e:
            logger.error(f"Failed to create checkpoints directory: {e}")
            return

    safetensors_path = os.path.join(checkpoints_dir, "placeholder.safetensors")
    if not os.path.exists(safetensors_path):
        try:
            with open(safetensors_path, 'w') as f:
                f.write("This is a placeholder file for ComfyUI workflow list.")
            logger.info(f"Created placeholder file: {safetensors_path}")
        except Exception as e:
            logger.error(f"Failed to create safetensors placeholder: {e}")

    gguf_path = os.path.join(checkpoints_dir, "placeholder.gguf")
    if not os.path.exists(gguf_path):
        try:
            with open(gguf_path, 'w') as f:
                f.write("This is a placeholder file for ComfyUI workflow list.")
            logger.info(f"Created placeholder file: {gguf_path}")
        except Exception as e:
            logger.error(f"Failed to create gguf placeholder: {e}")

    loras_dir = config.paths_loras
    if isinstance(loras_dir, list) and loras_dir:
        loras_dir = loras_dir[0]
    if not os.path.exists(loras_dir):
        try:
            os.makedirs(loras_dir)
            logger.info(f"Created loras directory at {loras_dir}")
        except Exception as e:
            logger.error(f"Failed to create loras directory: {e}")
            return

    loras_placeholder_path = os.path.join(loras_dir, "placeholder.safetensors")
    if not os.path.exists(loras_placeholder_path):
        try:
            with open(loras_placeholder_path, 'w') as f:
                f.write("This is a placeholder file for LoRA models.")
            logger.info(f"Created placeholder file: {loras_placeholder_path}")
        except Exception as e:
            logger.error(f"Failed to create loras placeholder: {e}")

    clip_dir = config.paths_clip
    if isinstance(clip_dir, list) and clip_dir:
        clip_dir = clip_dir[0]
    if not os.path.exists(clip_dir):
        try:
            os.makedirs(clip_dir)
            logger.info(f"Created clip directory at {clip_dir}")
        except Exception as e:
            logger.error(f"Failed to create clip directory: {e}")
            return

    clip_placeholder_path = os.path.join(clip_dir, "placeholder.safetensors")
    if not os.path.exists(clip_placeholder_path):
        try:
            with open(clip_placeholder_path, 'w') as f:
                f.write("This is a placeholder file for CLIP text encoder models.")
            logger.info(f"Created placeholder file: {clip_placeholder_path}")
        except Exception as e:
            logger.error(f"Failed to create clip placeholder: {e}")
def ini_args():
    import args_manager
    if not platform.system() == "Darwin" and args_manager.args.disable_backend:
        args_manager.args.always_cpu = 2
    return args_manager.args


def is_ipynb():
    return True if 'ipykernel' in sys.modules and hasattr(sys, '_jupyter_kernel') else False


def download_models(default_model, previous_default_models, checkpoint_downloads, embeddings_downloads, lora_downloads, vae_downloads):
    from modules.model_loader import load_file_from_url

    vae_approx_filenames = [
        ('xlvaeapp.pth', 'https://huggingface.co/lllyasviel/misc/resolve/main/xlvaeapp.pth'),
        ('vaeapp_sd15.pth', 'https://huggingface.co/lllyasviel/misc/resolve/main/vaeapp_sd15.pt'),
        ('xl-to-v1_interposer-v4.0.safetensors',
        'https://huggingface.co/mashb1t/misc/resolve/main/xl-to-v1_interposer-v4.0.safetensors')
    ]

    for file_name, url in vae_approx_filenames:
        load_file_from_url(url=url, model_dir=config.paths_vae_approx[0], file_name=file_name)

    load_file_from_url(
        url='https://huggingface.co/lllyasviel/misc/resolve/main/fooocus_expansion.bin',
        model_dir=config.path_fooocus_expansion,
        file_name='pytorch_model.bin'
    )

    if shared.args.disable_preset_download:
        print('Skipped model download.')
        return default_model, checkpoint_downloads

    if not shared.args.always_download_new_model:
        if not os.path.isfile(shared.modelsinfo.get_file_path_by_name('checkpoints', default_model)):
            for alternative_model_name in previous_default_models:
                if os.path.isfile(shared.modelsinfo.get_file_path_by_name('checkpoints', alternative_model_name)):
                    print(f'You do not have [{default_model}] but you have [{alternative_model_name}].')
                    print(f'SimpAI_Studio will use [{alternative_model_name}] to avoid downloading new models, '
                          f'but you are not using the latest models.')
                    print('Use --always-download-new-model to avoid fallback and always get new models.')
                    checkpoint_downloads = {}
                    default_model = alternative_model_name
                    break

    for file_name, url in checkpoint_downloads.items():
        model_dir = os.path.dirname(shared.modelsinfo.get_file_path_by_name('checkpoints', file_name))
        load_file_from_url(url=url, model_dir=model_dir, file_name=os.path.basename(file_name))
    for file_name, url in embeddings_downloads.items():
        load_file_from_url(url=url, model_dir=config.paths_embeddings[0], file_name=file_name)
    for file_name, url in lora_downloads.items():
        model_dir = os.path.dirname(shared.modelsinfo.get_file_path_by_name('loras', file_name))
        load_file_from_url(url=url, model_dir=model_dir, file_name=os.path.basename(file_name))
    for file_name, url in vae_downloads.items():
        load_file_from_url(url=url, model_dir=config.paths_vae[0], file_name=file_name)

    return default_model, checkpoint_downloads

def download_required_assets():
    from modules.model_loader import load_file_from_url

    vae_approx_filenames = [
        ('xlvaeapp.pth', 'https://huggingface.co/lllyasviel/misc/resolve/main/xlvaeapp.pth'),
        ('vaeapp_sd15.pth', 'https://huggingface.co/lllyasviel/misc/resolve/main/vaeapp_sd15.pt'),
        ('xl-to-v1_interposer-v4.0.safetensors',
        'https://huggingface.co/mashb1t/misc/resolve/main/xl-to-v1_interposer-v4.0.safetensors')
    ]

    for file_name, url in vae_approx_filenames:
        load_file_from_url(url=url, model_dir=config.paths_vae_approx[0], file_name=file_name)

def is_port_available(port, host='127.0.0.1'):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return True
    except Exception:
        return False

def find_available_port(start_port=7865, max_attempts=100, suppress_logging=False):
    excluded_ports = {7890, 8187, 8188, 8189, 8190}

    for i in range(max_attempts):
        port = start_port + i
        if port in excluded_ports:
            continue

        host = shared.args.listen if hasattr(shared.args, 'listen') else '127.0.0.1'

        if is_port_available(port, host):
            if not suppress_logging:
                if i > 0:
                    logger.info(f"端口 {start_port} 被占用，自动切换到端口: {port}")
                else:
                    logger.info(f"前端使用端口: {port}")
            return port

    return None

def reset_env_args():
    shared.sysinfo = json.loads(shared.token.get_sysinfo().to_json())
    shared.sysinfo.update(dict(did=shared.token.get_sys_did()))

    if _launch_arg_was_set('--location'):
        shared.sysinfo["location"] = args.location

    if shared.sysinfo["location"] == 'CN':
        os.environ['HF_MIRROR'] = 'hf-mirror.com'
        os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
        if not _launch_arg_was_set('--language'):
            shared.args.language='cn'

    if not _launch_arg_was_set('--listen'):
        if is_ipynb():
            shared.args.listen = '127.0.0.1'
        else:
            from enhanced.simpleai import is_fake_or_suspicious_ip, get_best_local_ip
            local_ip = shared.sysinfo["local_ip"]
            if is_fake_or_suspicious_ip(local_ip):
                best_ip = get_best_local_ip()
                if best_ip != '127.0.0.1':
                    logger.info(f"检测到 Fake IP ({local_ip})，切换到本地 IP: {best_ip}")
                    shared.args.listen = best_ip
                else:
                    shared.args.listen = local_ip
            else:
                shared.args.listen = local_ip
    if not _launch_arg_was_set('--port'):
        shared.args.port = shared.sysinfo["local_port"]

    if is_local_mode():
        if not _launch_arg_was_set('--listen'):
            shared.args.listen = '127.0.0.1'
        if not _launch_arg_was_set('--port'):
            shared.args.port = 8186

    host = shared.args.listen
    if not is_port_available(shared.args.port, host):
        available_port = find_available_port(shared.args.port + 1, suppress_logging=True)
        if available_port:
            logger.info(f"端口 {shared.args.port} 被占用，自动切换到: {available_port}")
            shared.args.port = available_port
    else:
        if _launch_arg_was_set('--port'):
            logger.info(f"使用指定的前端端口: {shared.args.port}")
        else:
            logger.info(f"使用默认前端端口: {shared.args.port}")
    if shared.args.node_type and shared.args.node_type != "online" and not _launch_arg_was_set('--listen'):
        shared.sysinfo["local_ip"] = '127.0.0.1'
        shared.args.listen = '127.0.0.1'

    from enhanced.simpleai import reset_simpleai_args
    reset_simpleai_args()

shared.args = ini_args()
shared.token, shared.sysinfo = check_base_environment()

prepare_environment()


shared.upstream_did = shared.token.get_upstream_did()

shared.upstream_did = '' if shared.args.node_type is not None and shared.args.node_type!='online' else shared.upstream_did
logger.debug(f'local_did/本地标识: {shared.token.get_sys_did()}')
logger.debug(f'nickname/用户昵称: {shared.token.get_guest_user_context().get_nickname()}, user_did/身份标识: {shared.token.get_guest_did()}')

if shared.args.node_type is not None:
    shared.token.reset_node_mode(shared.args.node_type)

if shared.args.reset_admin is not None:
    shared.token.reset_admin(shared.args.reset_admin)

if shared.args.gpu_device_id is not None:
    os.environ['CUDA_VISIBLE_DEVICES'] = str(shared.args.gpu_device_id)
    logger.info(f"Set device to: {shared.args.gpu_device_id}")

if shared.sysinfo["gpu_memory"]<4000 and not shared.args.disable_backend:
    logger.info(f'The GPU memory capacity of the system is too small to run the latest models such as Flux, SD3m, Kolors, and HyDiT properly, and the Comfyd engine will be automatically disabled.')
    logger.info(f'系统GPU显存容量太小，或是检测不到GPU实际容量，可能是操作系统阻止或需要升级硬件。')
    logger.info(f'有任何疑问可到QQ群交流: 1005085136')
    shared.args.async_cuda_allocation = False
    shared.args.disable_async_cuda_allocation = True

if shared.args.async_cuda_allocation:
    env_var = os.environ.get('PYTORCH_CUDA_ALLOC_CONF', None)
    if env_var is None:
        env_var = "backend:cudaMallocAsync"
    else:
        env_var += ",backend:cudaMallocAsync"
    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = env_var

from modules import config
from modules.hash_cache import init_cache
os.environ["U2NET_HOME"] = config.paths_inpaint[0]
os.environ["BERT_HOME"] = config.paths_llms[0]
os.environ['GRADIO_TEMP_DIR'] = config.temp_path

if shared.args.hf_mirror is not None :
    os.environ['HF_MIRROR'] = str(shared.args.hf_mirror)
    logger.info(f"Set hf_mirror to:{shared.args.hf_mirror}")

if config.temp_path_cleanup_on_launch:
    logger.info(f'Attempting to delete content of temp dir {config.temp_path}')
    result = delete_folder_content(config.temp_path, '[Cleanup] ')
    if result:
        logger.info("[Cleanup] Cleanup successful")
    else:
        logger.info(f"[Cleanup] Failed to delete content of temp dir.")

simpai_runtime_version = version.get_simpai_ver()
pyhash_key = shared.token.get_pyhash_key(simpai_runtime_version, comfy_version.version, simpai_runtime_version)
reset_env_args()
env_ready_code = shared.token.check_ready(simpai_runtime_version, comfy_version.version, simpai_runtime_version, config.path_models_root)
logger.info(f'Env_ready_code: {env_ready_code}')

if not shared.args.disable_backend:
    try:
        download_required_assets()
    except Exception as e:
        logger.error(f"下载必要资源失将在下次启动重试: {e}")

config.update_files()
init_cache(config.model_filenames, config.paths_checkpoints, config.lora_filenames, config.paths_loras)
create_placeholder_files()
from webui import *
