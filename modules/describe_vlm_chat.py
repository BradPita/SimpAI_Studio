import json
import os
import re
import sys
import threading
import time

import modules.canvas_danbooru_service as canvas_danbooru_service
import modules.vlm_system_prompt_templates as vlm_system_prompt_templates


ALLOWED_PROMPT_ACTIONS = {"set_prompt", "append_prompt", "refine_prompt", "describe_image_to_prompt", "text_to_prompt"}
GENERATION_ACTION_ALIASES = {
    "text_to_image",
    "generate_image",
    "image_generation",
    "create_image",
    "make_image",
    "draw_image",
}
CREATIVE_ASPECT_RATIOS = {"auto", "1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2", "7:4", "4:7"}
_CANCEL_TTL_SECONDS = 1800
_CANCELLED_REQUESTS = {}
_CANCELLED_REQUESTS_LOCK = threading.Lock()


DESCRIBE_CHAT_BASE_SYSTEM = (
    "You are the SimpAI Describe Image VLM chat assistant. This chat is a standalone wrapper, not the infinite canvas. "
    "You can discuss images, prompts, model behavior, visual ideas, and ordinary user questions. "
    "You cannot operate canvas nodes. Creative mode may return a structured media-generation request that the UI executes according to the user's creative preference. "
    "Never claim that an image is queued, running, or finished before the UI reports that state. "
    "Answer naturally in the user's UI language unless the user asks for another language."
)

CREATIVE_ASSISTANT_SYSTEM = (
    "Creative mode for SimpAI Studio VLM chat. The UI may already show a session preference card for anime, realistic, automatic, or a specific Preset. "
    "When the user asks to draw, create, render, generate, or edit an image, return exactly one JSON object: "
    "{\"reply\":\"short user-facing reply\",\"actions\":[{\"type\":\"generate_image\",\"prompt\":\"complete generation prompt\","
    "\"preset\":\"Z-imageT\",\"task\":\"text_to_image|image_edit|multi_image_edit\",\"media_refs\":[],"
    "\"aspect_ratio\":\"auto\",\"image_number\":1}]}. "
    "If the user explicitly names a preferred style or Preset for this conversation, also return a set_creative_preference action before generate_image: "
    "{\"type\":\"set_creative_preference\",\"style\":\"anime|realistic|auto|custom\",\"preset\":\"exact Preset name when known\",\"scope\":\"session\"}. "
    "An unqualified request such as `use Anima to generate it` counts as a session preference. "
    "Do not return that preference action only when the user explicitly says the choice is for this image or one time. "
    "The generate_image action is a request, not proof that generation has started. The UI decides whether it needs confirmation. "
    "For image editing, include the exact attached media refs in visual input order. Use image_edit for one referenced image and multi_image_edit for two or more. "
    "Choose a Preset whose max_images is at least the number of media_refs. Never invent media refs. "
    "Use the active session preference when present; otherwise use Z-imageT. Supported aspect_ratio values are auto, 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 7:4, and 4:7. "
    "image_number must be an integer from 1 to 4. Do not invent API routes, canvas node IDs, run IDs, file paths, or completed image URLs. "
    "For ordinary conversation that does not request an image or prompt, answer normally without action JSON."
)

CREATIVE_DIRECTOR_SYSTEM = (
    "You are the independent visual director for SimpAI Studio Creative chat. "
    "The main assistant reply has already been shown, so do not continue the roleplay, answer the user, or rewrite that reply. "
    "Decide whether the latest exchange contains a newly established, visually distinctive story moment worth offering to illustrate. "
    "Strong reasons are scene_change, emotional_peak, climax, visual_reveal, and character_moment. "
    "Do not offer for greetings, setup questions, ordinary exposition, meta discussion, prompt/model settings, repeated scenes, or a direct image request that already received a generation card. "
    "Prefer false. Return true only when score is at least 0.72 and the image would add entertainment or story value. "
    "Return exactly one JSON object. For no offer: "
    "{\"offer\":false,\"score\":0.0,\"reason\":\"none\",\"scene_key\":\"\"}. "
    "For an offer: {\"offer\":true,\"score\":0.85,\"reason\":\"scene_change\","
    "\"scene_key\":\"short stable lowercase scene identity\",\"offer_text\":\"one short sentence offering to draw this moment\","
    "\"prompt\":\"complete image-generation prompt\",\"preset\":\"exact preferred Preset name when available\","
    "\"aspect_ratio\":\"16:9\",\"image_number\":1}. "
    "Never invent API routes, run IDs, files, completed images, or extra actions."
)

CREATIVE_OFFER_REASONS = {
    "scene_change",
    "emotional_peak",
    "climax",
    "visual_reveal",
    "character_moment",
}
CREATIVE_OFFER_MIN_SCORE = 0.72

PROMPT_ASSISTANT_SYSTEM = (
    "Prompt-writing mode for SimpAI Web Describe Image chat. This is the regular SimpAI web prompt helper, not the infinite canvas. "
    "There is no send/generate button in this chat. Its executable prompt action can only show a prompt card that writes text to the main prompt box. "
    "Allowed action types are set_prompt and append_prompt. "
    "When the user asks to create, refine, translate, rewrite, fill, replace, append, send, or prepare a generation prompt, return exactly one JSON object: "
    "{\"reply\":\"short user-facing reply\",\"actions\":[{\"type\":\"set_prompt\",\"prompt\":\"final prompt text\"}]}. "
    "Use append_prompt only when the user asks to add onto the current prompt. "
    "Follow-up prompt requests such as another version, Chinese/English rewrite, more detail, shorter text, or style changes must also return the same action JSON shape. "
    "If you write a usable prompt, put the complete prompt only in actions[0].prompt, not only in normal prose. "
    "Do not use canvas action schemas, markdown tool calls, or prose-only completion notices for prompt-writing requests in this mode. "
    "Write the prompt in the style requested by the user; otherwise use concise image-generation prompt language. "
    "The visible reply must be short; the full final prompt must be in actions[0].prompt so the chat UI can show it for review."
)

GUIDE_MODE_SYSTEM = """
SimpAI UI guide skill:
- You guide users to the most suitable SimpAI Studio main-interface workflow, preset, or mode based on their goal.
- Do not claim you can click buttons, operate the UI, queue jobs, or inspect hidden interface state. Recommend where to go and what to try.
- In Describe Image chat, Creative mode can run image Presets through Canvas Runner for text-to-image, single-image editing, and multi-image editing. Guide mode recommends workflows and Presets but does not start generation; direct users to Creative mode when they want the chat to generate or edit images.
- Text-to-image / first image:
  - For realistic / general text-to-image, recommend Z-image, Krea2-Turbo, Wan(T2I), Flux, or Qwen2512. These are mainly realistic/general-purpose routes, but can handle some simple anime or illustration requests.
  - For anime, illustration, 二次元, character art, or tag-style workflows, recommend Anima, Illustrious / 光辉, NoobAI, or SDXL-class anime presets first. Treat these as the dedicated anime-oriented choices.
  - Anima is a DiT anime model. It is slower than SDXL / Illustrious routes, but better for multi-character scenes, body structure, and limbs. Its style control is weaker; strict style direction normally needs targeted LoRA, so if Anima LoRA support is not yet available, recommend Illustrious / NoobAI / SDXL LoRA routes for strong artist/style control.
  - Illustrious / 光辉 and NoobAI are SDXL-branch anime models. They are fast, good with artist names and Danbooru-style prompts, and have a rich LoRA ecosystem. Their precision can be lower than heavier DiT routes, so users may need multiple samples plus hand/face repair to get a satisfying result.
  - FooocusSDXL is the native Fooocus-engine preset package. SimpAI now also relies heavily on specialized Comfy-engine presets to support more model families and directed workflows.
  - If the user says "realistic", "photo", "portrait", "product", "commercial", "写实", "真人", or "摄影", prefer Z-image / Krea2-Turbo / Flux / Qwen2512 / Wan(T2I) over anime presets.
  - If the user says "anime", "manga", "二次元", "插画", "动漫", "光辉", "Illustrious", "Danbooru", or wants tag-style prompting, prefer Anima / SDXL anime / Illustrious over realistic/general presets.
  - For general photo/realistic generation, recommend the main generation preset that matches the active style; if unsure, ask whether they want 写实向 or 动漫向 before choosing.
  - For prompt writing, prompt cleanup, translation, or Danbooru tags, recommend Prompt Assistant mode in this chat or the Prompt Helper Starter canvas.
- Prompt language / model routing:
  - For Chinese prompts, prefer Z-image, Wan-series, Qwen-series, or Flux2-Klein-series. For Chinese text rendering/output inside generated images, Qwen2512 is the strongest choice; other models are secondary.
  - For English natural-language prompts, prefer Krea2-Turbo or the Flux family.
  - For Danbooru tag workflows, recommend SDXL, Illustrious / 光辉, NoobAI, Tile, SD1.5, or ChenkinXL.
  - For the Anima branch, use Danbooru tags plus lightweight English natural language; do not promise Anima LoRA/ControlNet support yet because it is planned for later.
  - For speed, SD1.5, Z-image, and SDXL-family routes are fast; Flux2-Klein is also fast and resource-light. Wan and Qwen models are heavier and need more VRAM.
  - LoRA and ControlNet are broadly supported across model families, with the Anima exception above.
- Input Image / reference controls:
  - Image Prompt is usually a style/reference semantic-vector input. Some model families hide it because they do not have the matching module.
  - For ControlNet choices, Canny / PyraCanny preserves line contours, Depth preserves spatial relationships, OpenPose preserves human pose, and FaceSwap converts a face into a conditioning vector. Mention that many newer model families no longer support the old FaceSwap module.
  - Vary (Subtle) and Vary (Strong) use the original image as the base, encode it into latent space, then lightly or strongly redraw it depending on prompt and denoise/redraw strength.
  - Upscale (Fast 2x) is a quick model upscale with lower quality and low resource cost. Upscale (1.5x) and Upscale (2x) encode into latent space for inference upscaling and expose redraw-strength control.
- Editing model boundaries:
  - Flux2-Klein is a fast, resource-light, 4-step distilled model with slightly lower precision. If it does not follow the instruction once, suggest trying again or using a more stable editor.
  - Krea2-Turbo is a Krea 2 Turbo text-to-image preset for realistic/general images from natural-language prompts. It is not an instruction-editing or reference-image route.
  - Bernini-ImageEdit is the Bernini-R still-image editing route for instruction edits, style conversion, replacement, inpainting, and color matching on an input image.
  - QwenEdit+ is heavier, slower, and more stable for image editing, with stronger reference consistency.
  - Nun/Nunchaku presets are 4-bit quantized variants that trade precision for speed and lower resource use. Use fp4 on RTX 50-series or newer GPUs; use int4 on older GPUs.
  - Directional Klein and Qwen presets are built for specific subjects or operations and usually include purpose-specific LoRAs.
  - QwenNSFW is a community-merged single-checkpoint route aimed at unlocking restricted editing cases that the original QwenEdit may filter.
- Image editing / retouching:
  - For instruction-based image editing, object add/remove/replace, text editing, style conversion, inpainting, or optional mask editing, recommend QwenEdit+ / Qwen-Edit-2511 first.
  - For image object transfer / item migration (图像物品迁移 / 物品替换 / 把一个物体迁移到另一张图), recommend Swap+ when the user wants strong painted-mask control. Swap+ uses the Flux1.Fill model and is suited for brush-mask-directed object migration or replacement. Flux2-Klein and QwenEdit are multimodal editors that can take multiple input images and replace objects by instruction, with optional brush masks; their mask function is useful but weaker than Swap+ for precise masked transfer.
  - For broad one-click commercial/product retouching, recommend OneKeyKontext. Rough submode guidance: product repair / 3C / home appliances / jewelry / metal for commercial product polish; face / body for portrait or figure cleanup; clothing / clothing extraction / take clothes for garment workflows; angle edit / IP 3-View / depth reference for view, structure, and multi-view control; remove anything / object insertion / clear background / composite / scene / pattern for local replacement, background, and layout work.
  - For manual detail repair of hands, faces, or eyes (修手 / 修脸 / 修眼 / 精修细节), recommend the inpaint/outpaint mode inside the relevant text-to-image model family: choose the detail-improvement option (提升细节), write the extra/additional prompt for the area, then tune redraw/denoise strength (重绘幅度) and feathering (羽化).
  - For automatic detail repair of hands, faces, or eyes, recommend Enhance / 增强修图. Explain that it can optionally upscale once, then run three region-recognition refinement passes; by default the regions are detected and processed in order: face, hands, eyes. It can be chained after text-to-image generation or used directly with an uploaded image.
  - For background removal / cutout, recommend Removebg.
  - For relighting or matching foreground/background lighting, recommend Relight or Flux2-AngleLight.
  - For anime-to-real or stylized-to-real character conversion, recommend Flux2-A2R.
  - For style transfer, recommend StyleTransfer+ with its 110 prompt-style presets. Do not recommend the older SDXL style-transfer preset route.
  - For erasing unwanted areas or cleanup, recommend Eraser or QwenEdit+ with a mask.
  - For seamless outpainting / image-edge expansion (无缝扩图 / 边缘拓展), recommend OneKey-Outpaint first. It uses the Flux1.Fill model for general-purpose image boundary extension across subjects, and is often used to change composition, change aspect ratio, or add missing surrounding elements.
- Face, body, pose, and camera:
  - For face swap on still images, recommend Swapface or Swap+.
  - For expression editing on still portraits, recommend LivePortrait Exp. It edits face rotation, eyes, mouth, smile, and optional reference-expression strength; treat it as an expression editor, not an identity face-swap route.
  - For pose transfer or pose-driven edits, recommend OneKeyPose, QwenPose, Flux2-KleinPose, or SDPose depending on the selected preset family.
  - For camera angle / multi-view control, recommend QwenMultiAngle; for product or character three-view sheets, recommend OneKeyKontext IP 3-View.
  - For Gaussian blur cleanup or detail-oriented Qwen edits, recommend QwenGaussian / QwenEdit+ when relevant.
- Image-to-video / video generation:
  - When the user asks for image-to-video or wants to animate a still image, recommend Wan image-to-video as the general/default route.
  - For anime, illustration, 二次元, 动漫向, manhua, cel-shaded, or character-art image-to-video requests, recommend Dasiwa image-to-video first.
  - For text-to-video, recommend Wan(T2V); for image-to-video, recommend Wan(I2V); for video extension, recommend Wan-Extent or Dasiwa-Extent for anime.
  - For video outpainting / expanding video frame boundaries, recommend Wan-Outpaint.
  - For video object/person/face replacement with masks, recommend Wan-Animate with SAM3; for video removal/inpainting, recommend Wan-Remover with SAM3.
  - For video face swap, recommend ReActor-FaceSwap / ReActor Face Swap for a direct source-face-index workflow with a reference face image and source video. Offer Wan-Swap / Wan-Animate Face Swap when the user wants the Animate-style multimodal face-replacement route.
  - For motion transfer, character replacement, pose-following, or reusing a reference motion, recommend Wan-SCAIL2 or Wan-Swap motion transfer depending on whether identity/face replacement is involved. Wan-SCAIL2 separates the modes into two themes: Character Motion Transfer and Character Replacement; use Wan-Swap / Wan-Animate Motion Transfer as the Animate-style alternative.
  - For Bernini-R video routes, recommend Bernini-MultiI2V for multi-reference image-to-video and Bernini-VideoEdit for video editing with optional image references and Duration limit.
  - For face replacement in video, recommend ReActor-FaceSwap first for the ReActor route, or Wan-Swap when the Animate-style route fits better.
  - Wan video routes have strong consistency, many specialized extensions, and strong directed workflows, but T2V/I2V duration is limited and VRAM requirements are high.
  - LTX2.3 is better when the user needs more flexible duration, dynamic VRAM use, or text/audio multimodal video input/output. It can still consume a lot of system RAM.
  - LTX-Outpaint is a specialized IC-LoRA-enhanced video outpaint route.
  - For LTX2.3 video restoration, HD enhancement, watermark removal, or subtitle removal, recommend LTX2.3(InsightTool). Its themes are Video Restore, Video Upscale, Remove Watermark, and Remove Subtitles; it requires a source video and uses task-specific IC-LoRA adapters.
  - Wan-Animate and Wan-Swap are directed presets based on Animate-style multimodal reference ability; they cover object replacement, pose/motion transfer, character or face replacement, with SAM3-mask and no-SAM3-mask variants.
  - For conventional video upscaling / super-resolution without restoration or cleanup goals, recommend Nvidia-VSR.
- Audio, speech, and talking video:
  - For text-to-speech, voice design, voice clone, custom voice, or multi-role dialogue, recommend Qwen TTS canvas templates.
  - For turning a portrait/image plus audio into lip-sync/talking video, recommend InfiniteTalk image+audio-to-video.
  - For adding sound effects or Foley to a video, recommend Hunyuan-Foley.
  - For mixing generated speech with video/audio timelines, recommend TTS Timeline or Timeline Composite templates in the infinite canvas.
- Infinite canvas / advanced workflow:
  - Recommend the main WebUI directly for a single simple generation, a one-off edit, or quick parameter experiments. Recommend the infinite canvas when the user needs multi-step composition, local edits, references, comparing generations, arranging assets, timelines, result reuse, or chaining image/video/audio nodes.
  - For learning canvas basics, recommend Canvas Quick Start; for Preset nodes, recommend Preset Node Basics; for queue/results, recommend Run Queue & Result Basics; for model download/status, recommend Model Readiness Basics.
  - For reusing an output as the next input, recommend Result Reuse Image Chain.
  - For batching or repeated reusable chains, suggest using canvas Preset nodes, Result nodes, user templates, and Timeline templates rather than asking the user to manually repeat main-UI steps.
- Model readiness:
  - If the user asks why a preset cannot run or models are missing, recommend checking the preset model status/download button and the Model Readiness Basics canvas.
  - If the issue is not model readiness, mention possible identity/permission state: guest users or unapproved identities may be unable to generate, download models, or manage personal resources; admins can manage downloads and user access.
- If several workflows could fit, give a short ranked recommendation and one reason for each.
- If critical information is missing, ask one concise clarifying question before recommending.
- Keep answers practical and concise in the user's UI language.
"""

SIMPAI_PRESET_GUIDE_SKILL_FILE = "simpai_preset_guide.md"
ANIMA_PROMPT_SKILL_FILE = "anima_prompting.md"


def _cancel_key(conversation_id="", request_id=""):
    return (str(conversation_id or "").strip(), str(request_id or "").strip())


def _prune_cancelled_requests(now=None):
    current = time.monotonic() if now is None else now
    expired = [key for key, stamp in _CANCELLED_REQUESTS.items() if current - stamp > _CANCEL_TTL_SECONDS]
    for key in expired:
        _CANCELLED_REQUESTS.pop(key, None)


def request_describe_vlm_chat_cancel(conversation_id="", request_id=""):
    key = _cancel_key(conversation_id, request_id)
    if not key[0] and not key[1]:
        return {"ok": True, "cancelled": True, "conversation_id": "", "request_id": ""}
    with _CANCELLED_REQUESTS_LOCK:
        _prune_cancelled_requests()
        _CANCELLED_REQUESTS[key] = time.monotonic()
    return {"ok": True, "cancelled": True, "conversation_id": key[0], "request_id": key[1]}


def clear_describe_vlm_chat_cancel(conversation_id="", request_id=""):
    key = _cancel_key(conversation_id, request_id)
    with _CANCELLED_REQUESTS_LOCK:
        _CANCELLED_REQUESTS.pop(key, None)


def is_describe_vlm_chat_cancelled(conversation_id="", request_id=""):
    key = _cancel_key(conversation_id, request_id)
    conversation_key = (key[0], "")
    with _CANCELLED_REQUESTS_LOCK:
        _prune_cancelled_requests()
        return key in _CANCELLED_REQUESTS or (bool(key[0]) and conversation_key in _CANCELLED_REQUESTS)

NATURAL_PROMPT_SKILL = """
Natural-language prompt skill for Describe Image chat:
- Expand a short request into one coherent visual moment, not a loose noun list.
- Preserve the user's subject, count, prop, action, mood, setting, and any negative constraint.
- Add concrete visible design: hairstyle, clothing, colors, accessories, hands, gaze, expression, body orientation, prop use, environment, time, weather, camera distance, angle, lighting, atmosphere, and texture.
- For Chinese requests, write fluent Chinese unless the user explicitly asks for English. For English natural targets, write fluent English.
- Avoid bare topic restatements and empty filler such as "高清细节", "艺术风格", "高质量", "beautiful woman" without visible design.
- Keep generation controls, seed, steps, CFG, size, model names, markdown, and comments out of the prompt.
- Example for "画美女撑伞图": "雨后的青石巷里，一位身穿淡青色汉服的年轻女子侧身撑着油纸伞缓步前行，长发被银簪挽起，宽袖被细雨和微风轻轻带起，伞面落着水珠，远处暖色灯笼映在湿润石板路上，半身到膝上的电影感构图，柔和逆光，朦胧水汽，古风插画质感。"
"""

DANBOORU_TAG_PROMPT_SKILL = """
Danbooru tag prompt skill for Describe Image chat:
- Use this when the Describe Image panel has Output with tags enabled.
- The final prompt must be comma-separated English Danbooru-style tags, not Chinese prose.
- Put important content first: subject count, identity, composition, action, prop, expression, clothing, setting, weather, lighting, rendering/style, quality.
- Use compact atom tags. Do not fabricate long prose tags by replacing spaces with underscores.
- Preserve explicit count, action, prop, setting, relationship, and composition. Do not add conflicting count tags.
- For named characters, include each character tag once. Do not create pseudo-character outfit tags such as klee_(genshin_impact_outfit) or nahida_(genshin_impact_outfit); use ordinary clothing tags only when needed.
- Avoid sentence punctuation, markdown, generation controls, negative phrases, comments, and translated Chinese tags.
- Example for "画美女撑伞图": "1girl, solo, holding_umbrella, umbrella, rain, walking, from_side, looking_to_the_side, long_hair, hair_ornament, hanfu, wide_sleeves, wet_pavement, stone_path, lantern, reflection, mist, depth_of_field, soft_lighting, backlighting, cinematic_composition, detailed_background"
"""

ANIMA_DESCRIBE_PROMPT_ADAPTER = """
Anima prompt skill adapter for SimpAI Web Describe Image chat:
- Use the Anima rules below to format only `actions[0].prompt`.
- The Web chat output JSON still must be `{"reply":"short reply","actions":[{"type":"set_prompt","prompt":"final Anima positive prompt"}]}`.
- Do not output top-level `generate_image`, `subject_counts`, `draft_prompt`, or canvas confirmation-card payloads in this Web prompt helper.
- The final prompt must be an English Anima positive prompt, not a generic natural-language paragraph and not Chinese prose.
"""
ANIMA_CREATIVE_PROMPT_ADAPTER = """
Anima prompt skill adapter for SimpAI Studio Creative chat:
- Use the Anima rules below to format only the `prompt` field in the active Creative JSON contract.
- Keep the outer `generate_image` or visual-director offer schema required by the active system prompt.
- The final prompt must be an English Anima positive prompt, not a generic natural-language paragraph and not Chinese prose.
"""
PROMPT_TARGET_OPTION_KEYS = (
    "preset",
    "preset_name",
    "selected_preset",
    "backend_engine",
    "engine",
    "engine_type",
    "task_method",
    "method",
    "prompt_format",
    "target_key",
    "prompt_target",
    "text_encoder",
    "clip_model",
    "clip",
    "base_model",
    "model",
    "checkpoint",
    "workflow",
    "workflow_name",
)

PROMPT_INTENT_RE = re.compile(
    r"("
    r"提示词|正向提示|反推|生图|图生文|文生图|出图|生成图|画一|画个|画张|画幅|画.{0,30}(图|画|插画|美女|人物|场景)|绘制|"
    r"整理.*图|整理.*prompt|整理.*tag|优化.*prompt|优化.*提示|改写.*prompt|改写.*提示|"
    r"\bprompt\b|\bprompts\b|\btag\b|\btags\b|\bdanbooru\b|"
    r"\bdraw\b|\bgenerate\b|\bcreate\b|\bmake\b.{0,24}\b(image|picture|illustration|artwork)\b|"
    r"\bimage prompt\b|\btext to image\b"
    r")",
    re.I,
)
def _clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _data_url_mime(data_url):
    match = re.match(r"^data:([^;,]+)", str(data_url or ""))
    return match.group(1) if match else "application/octet-stream"


def _normalize_lang(value):
    text = str(value or "").strip().lower()
    return "en" if text.startswith("en") else "cn"


def _describe_vlm_skills_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "vlm_skills")


def _describe_read_vlm_skill_file(filename, max_chars=24000):
    clean = str(filename or "").replace("\\", "/").strip()
    if not clean or clean.startswith("/") or ".." in clean.split("/"):
        return ""
    path = os.path.join(_describe_vlm_skills_dir(), clean)
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except Exception:
        return ""
    if max_chars and len(content) > int(max_chars):
        return content[: int(max_chars)].rstrip() + "\n..."
    return content


def _describe_preset_guide_skill():
    return _describe_read_vlm_skill_file(SIMPAI_PRESET_GUIDE_SKILL_FILE) or GUIDE_MODE_SYSTEM.strip()


def _describe_anima_prompt_skill(adapter=None):
    content = _describe_read_vlm_skill_file(ANIMA_PROMPT_SKILL_FILE, 16000)
    if content and "## Output Contract" in content and "## Positive Prompt Shape" in content:
        intro = content.split("## Output Contract", 1)[0].strip()
        body = "## Positive Prompt Shape\n" + content.split("## Positive Prompt Shape", 1)[1].strip()
        content = f"{intro}\n\n{body}".strip()
    prompt_adapter = ANIMA_DESCRIBE_PROMPT_ADAPTER if adapter is None else str(adapter or "")
    return "\n\n".join(part for part in (prompt_adapter.strip(), content) if part).strip()


def _normalize_chat_mode(value):
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"creative", "create", "creation", "creative_mode", "image_generation"}:
        return "creative"
    if text in {"prompt", "prompt_assistant", "assistant"}:
        return "prompt"
    if text in {"guide", "guide_mode", "wizard", "ui_guide", "workflow_guide"}:
        return "guide"
    if text in {"raw", "raw_model", "model"}:
        return "raw"
    return "chat"


def _clean_multiline_text(value, limit=4000):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text[: max(200, int(limit or 4000))].strip()


def _localized_default_reply(action_type, lang):
    if _normalize_lang(lang) == "en":
        if action_type == "generate_image":
            return "I prepared an image-generation proposal. Review the options and confirm when ready."
        if action_type == "append_prompt":
            return "I prepared prompt text to append."
        return "I prepared prompt text for the main prompt box."
    if action_type == "generate_image":
        return "已准备生图方案，请检查选项后确认生成。"
    if action_type == "append_prompt":
        return "已整理可追加到主提示词框的内容。"
    return "已整理可写入主提示词框的内容。"


def _history_image_placeholder(item):
    image_count = item.get("image_count")
    if image_count is None and isinstance(item.get("images"), list):
        image_count = len(item.get("images") or [])
    try:
        image_count = int(image_count or 0)
    except Exception:
        image_count = 0
    if image_count <= 0:
        return ""
    return f"[{image_count} previous visual media reference(s); full media bytes omitted from history.]"


def _normalize_history(messages, limit=24, budget=6000):
    normalized = []
    for item in messages if isinstance(messages, list) else []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant", "system"}:
            continue
        content = str(item.get("content") or item.get("reply") or "").strip()
        image_placeholder = _history_image_placeholder(item)
        if image_placeholder:
            content = f"{content}\n{image_placeholder}".strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content[:3000]})

    selected = []
    used = 0
    max_items = max(1, int(limit or 24))
    max_budget = max(1200, int(budget or 6000))
    for item in reversed(normalized):
        content = item["content"]
        max_one = max(500, min(1800, max_budget // 3))
        if len(content) > max_one:
            content = content[-max_one:].lstrip()
        cost = len(item["role"]) + len(content) + 16
        if len(selected) >= max_items or (selected and used + cost > max_budget):
            continue
        selected.append({"role": item["role"], "content": content})
        used += cost
    selected.reverse()
    return selected


def _media_source_from_payload(media, conversation_id, index=0):
    media = media if isinstance(media, dict) else {}
    data_url = str(media.get("data_url") or "").strip()
    if not data_url:
        return None
    mime = str(media.get("mime") or _data_url_mime(data_url)).strip().lower()
    media_type = "video" if mime.startswith("video/") else "image" if mime.startswith("image/") else ""
    if not media_type:
        return None
    asset_id = str(media.get("id") or f"describe_vlm_chat_{int(time.time() * 1000)}")
    return {
        "node_id": f"describe_vlm_chat:{conversation_id}:{media_type}:{index}",
        "type": media_type,
        "title": str(media.get("name") or f"Describe chat {media_type}"),
        "asset": {
            "kind": "browser_upload",
            "asset_id": asset_id,
            "mime": mime,
            "width": media.get("width") or None,
            "height": media.get("height") or None,
            "duration": media.get("duration") or None,
            "size": media.get("size") or None,
            "data_url": data_url,
            "thumb": media.get("thumb") or "",
        },
        "mask": None,
        "source": {"kind": "describe_vlm_chat"},
    }


def _media_sources_from_payload(payload, conversation_id, limit=5):
    raw_images = []
    if isinstance(payload.get("images"), list):
        raw_images.extend(payload.get("images") or [])
    elif isinstance(payload.get("image"), dict):
        raw_images.append(payload.get("image"))

    seen = set()
    sources = []
    for image in raw_images:
        if not isinstance(image, dict) or image.get("placeholder"):
            continue
        data_url = str(image.get("data_url") or "").strip()
        if not data_url:
            continue
        key = str(image.get("id") or data_url[:160])
        if key in seen:
            continue
        seen.add(key)
        source = _media_source_from_payload(image, conversation_id, len(sources))
        if source:
            sources.append(source)
        if len(sources) >= max(1, int(limit or 5)):
            break
    return sources


def _media_manifest_from_payload(payload, limit=5):
    raw_media = payload.get("images") if isinstance(payload.get("images"), list) else []
    if not raw_media and isinstance(payload.get("image"), dict):
        raw_media = [payload.get("image")]
    manifest = []
    seen = set()
    for item in raw_media:
        if not isinstance(item, dict) or item.get("placeholder"):
            continue
        data_url = str(item.get("data_url") or "").strip()
        mime = str(item.get("mime") or _data_url_mime(data_url)).strip().lower()
        media_type = "video" if mime.startswith("video/") else "image" if mime.startswith("image/") else ""
        ref = _clean_text(item.get("id"))[:160]
        if not ref or not media_type or ref in seen:
            continue
        seen.add(ref)
        manifest.append(
            {
                "ref": ref,
                "index": len(manifest) + 1,
                "type": media_type,
                "name": _clean_text(item.get("name"))[:160] or f"{media_type} {len(manifest) + 1}",
            }
        )
        if len(manifest) >= max(1, min(5, int(limit or 5))):
            break
    return manifest


def _normalize_preset_capabilities(value, limit=100):
    normalized = []
    seen = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = re.sub(r"[\x00-\x1f\x7f]+", "", str(item.get("name") or "")).strip()[:120]
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        try:
            max_images = max(0, min(5, int(item.get("max_images") or 0)))
        except Exception:
            max_images = 0
        try:
            min_images = max(0, min(max_images, int(item.get("min_images") or 0)))
        except Exception:
            min_images = 0
        normalized.append(
            {
                "name": name,
                "min_images": min_images,
                "max_images": max_images,
                "output_type": "video" if str(item.get("output_type") or "").strip().lower() == "video" else "image",
            }
        )
        if len(normalized) >= max(1, min(200, int(limit or 100))):
            break
    return normalized


def _preset_capability_map(capabilities):
    return {
        str(item.get("name") or "").strip().lower(): item
        for item in (capabilities if isinstance(capabilities, list) else [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }


def _truthy(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "支持", "是"}


def _runtime_default_prompt_target_options():
    config = sys.modules.get("modules.config")
    if config is None:
        return {}

    preset = str(getattr(config, "preset", "") or "").strip()
    preset_content = {}
    if preset:
        try:
            preset_content = config.try_get_preset_content(preset) or {}
        except (Exception, SystemExit):
            preset_content = {}
    if not isinstance(preset_content, dict):
        preset_content = {}

    default_engine = preset_content.get("default_engine")
    if not isinstance(default_engine, dict):
        default_engine = getattr(config, "default_engine", {})
    if not isinstance(default_engine, dict):
        default_engine = {}
    backend_params = default_engine.get("backend_params", {})
    if not isinstance(backend_params, dict):
        backend_params = {}

    return {
        "preset": preset,
        "backend_engine": default_engine.get("backend_engine") or getattr(config, "backend_engine", ""),
        "task_method": backend_params.get("task_method") or "",
        "prompt_format": backend_params.get("prompt_format") or "",
        "text_encoder": (
            backend_params.get("text_encoder")
            or backend_params.get("clip_model")
            or preset_content.get("default_clip_model")
            or getattr(config, "default_clip_model", "")
        ),
        "base_model": (
            preset_content.get("default_model")
            or getattr(config, "default_base_model_name", "")
            or getattr(config, "default_model", "")
        ),
    }


def _has_prompt_target_options(options):
    if not isinstance(options, dict):
        return False
    return any(str(options.get(key) or "").strip() for key in PROMPT_TARGET_OPTION_KEYS)


def _merge_prompt_target_options(options, use_runtime_defaults=False):
    merged = _runtime_default_prompt_target_options() if use_runtime_defaults and not _has_prompt_target_options(options) else {}
    for key, value in (options if isinstance(options, dict) else {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            merged[key] = value
            continue
        if str(value or "").strip():
            merged[key] = value
    return merged


def _prompt_target_field(options, *names):
    for name in names:
        value = options.get(name) if isinstance(options, dict) else None
        if value is None:
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _prompt_target_haystack(options):
    options = options if isinstance(options, dict) else {}
    fields = [
        _prompt_target_field(options, "preset", "preset_name", "selected_preset"),
        _prompt_target_field(options, "backend_engine", "engine", "engine_type"),
        _prompt_target_field(options, "task_method", "method"),
        _prompt_target_field(options, "prompt_format", "target_key", "prompt_target"),
        _prompt_target_field(options, "text_encoder", "clip_model", "clip"),
        _prompt_target_field(options, "base_model", "model", "checkpoint", "workflow", "workflow_name"),
    ]
    return " ".join(field for field in fields if field).lower()


def _is_anima_prompt_target(options):
    haystack = _prompt_target_haystack(options)
    if not haystack:
        return False
    return bool(
        re.search(r"(^|[^a-z0-9])anima([^a-z0-9]|$)", haystack)
        or "anima_aio" in haystack
        or "anima-base" in haystack
        or "anima_base" in haystack
    )


def _prompt_mode_from_options(options):
    options = options if isinstance(options, dict) else {}
    if _is_anima_prompt_target(options):
        return "anima"
    return "danbooru_tags" if options.get("output_tags") else "natural"


def _prompt_options_from_payload(payload, lang):
    raw_options = payload.get("prompt_options") if isinstance(payload.get("prompt_options"), dict) else {}
    chat_mode = _normalize_chat_mode(payload.get("chat_mode") or payload.get("describe_chat_mode"))
    options = _merge_prompt_target_options(raw_options, use_runtime_defaults=chat_mode == "prompt")
    output_tags = _truthy(options.get("output_tags", payload.get("output_tags")), False)
    output_chinese = _truthy(options.get("output_chinese", payload.get("output_chinese")), _normalize_lang(lang) != "en")
    output_artist = _truthy(options.get("output_artist", payload.get("output_artist")), False)
    message = str(payload.get("message") or payload.get("prompt") or "")
    prompt_intent = _truthy(payload.get("prompt_intent"), False) or bool(PROMPT_INTENT_RE.search(message))
    include_current_prompt = chat_mode == "prompt"
    normalized_options = dict(options)
    normalized_options.update({"output_tags": output_tags, "output_chinese": output_chinese, "output_artist": output_artist})
    mode = _prompt_mode_from_options(normalized_options)
    system_prompt_template_id = _clean_text(
        payload.get("system_prompt_template_id")
        or payload.get("vlm_system_prompt_template_id")
        or payload.get("template_id")
        or ""
    )
    custom_system_prompt = _clean_multiline_text(
        payload.get("custom_system_prompt")
        or payload.get("user_system_prompt")
        or payload.get("system_prompt")
        or ""
    )
    if system_prompt_template_id and not custom_system_prompt:
        custom_system_prompt = _clean_multiline_text(
            vlm_system_prompt_templates.resolve_vlm_system_prompt_template(system_prompt_template_id)
        )
    creative_preferences = _normalize_creative_preferences(payload.get("creative_preferences"))
    return {
        "chat_mode": chat_mode,
        "mode": mode,
        "output_tags": output_tags,
        "output_chinese": output_chinese,
        "output_artist": output_artist,
        "target_preset": _prompt_target_field(options, "preset", "preset_name", "selected_preset"),
        "target_backend_engine": _prompt_target_field(options, "backend_engine", "engine", "engine_type"),
        "target_task_method": _prompt_target_field(options, "task_method", "method"),
        "target_text_encoder": _prompt_target_field(options, "text_encoder", "clip_model", "clip"),
        "target_base_model": _prompt_target_field(options, "base_model", "model", "checkpoint"),
        "custom_system_prompt": custom_system_prompt,
        "system_prompt_template_id": system_prompt_template_id,
        "prompt_intent": prompt_intent,
        "include_current_prompt": include_current_prompt,
        "enable_prompt_skills": chat_mode == "prompt" or (chat_mode == "chat" and prompt_intent),
        "enable_generation_actions": chat_mode == "creative",
        "creative_preferences": creative_preferences,
        "media_manifest": _media_manifest_from_payload(payload),
        "preset_capabilities": _normalize_preset_capabilities(payload.get("preset_capabilities")),
    }


def _normalize_creative_preferences(value):
    source = value if isinstance(value, dict) else {}
    style = str(source.get("style") or "").strip().lower()
    if style not in {"anime", "realistic", "auto", "custom"}:
        style = ""
    preset = re.sub(r"[\x00-\x1f\x7f]+", "", str(source.get("preset") or "")).strip()[:120]
    return {
        "prompted": _truthy(source.get("prompted"), False),
        "style": style,
        "preset": preset,
        "auto_generate": _truthy(source.get("auto_generate"), False),
    }


def _prompt_skill_section(options, lang):
    options = options if isinstance(options, dict) else {}
    mode = options.get("mode") or _prompt_mode_from_options(options)
    prompt_lang = "Chinese" if options.get("output_chinese") else "English"
    if mode == "anima":
        target = (
            "Prompt target: Anima hybrid prompt for the active SimpAI preset. "
            "The action prompt must be English Anima-compatible positive prompt text with compact Danbooru/Anima anchors and short `nltags` when useful."
        )
        skill = _describe_anima_prompt_skill()
    elif mode == "danbooru_tags":
        target = "Prompt target: Danbooru tags. The action prompt must be English comma-separated tags."
        skill = DANBOORU_TAG_PROMPT_SKILL
    else:
        target = f"Prompt target: natural-language image prompt. The action prompt should use {prompt_lang} unless the user explicitly asks otherwise."
        skill = NATURAL_PROMPT_SKILL
    artist_note = (
        "If Artist is enabled, include a few style/artist-direction cues only when they help the prompt; never invent a specific living artist name. "
        if options.get("output_artist")
        else ""
    )
    target_context = (
        f"Active target context: preset={options.get('target_preset') or 'unknown'}, "
        f"backend_engine={options.get('target_backend_engine') or 'unknown'}, "
        f"task_method={options.get('target_task_method') or 'unknown'}, "
        f"text_encoder={options.get('target_text_encoder') or 'unknown'}, "
        f"base_model={options.get('target_base_model') or 'unknown'}.\n"
        if any(options.get(key) for key in ("target_preset", "target_backend_engine", "target_task_method", "target_text_encoder", "target_base_model"))
        else ""
    )
    return (
        f"{PROMPT_ASSISTANT_SYSTEM}\n"
        f"{target}\n"
        f"{target_context}"
        f"{artist_note}"
        "Do not hide the real prompt in prose, and do not return only a completion notice.\n\n"
        f"{skill.strip()}"
    )


def _describe_chat_system_prompt(options, lang):
    options = options if isinstance(options, dict) else {}
    chat_mode = _normalize_chat_mode(options.get("chat_mode"))
    custom_system_prompt = _clean_multiline_text(options.get("custom_system_prompt"))
    reply_lang = "English" if _normalize_lang(lang) == "en" else "Chinese"

    if chat_mode == "raw":
        sections = []
        if custom_system_prompt:
            sections.append(custom_system_prompt)
        else:
            sections.append("You are a helpful multimodal chat model. Answer the user directly.")
        sections.append(
            "Runtime note: this is a standalone Describe Image chat wrapper with no canvas tools. "
            "Keep answers in the user's UI language unless the user asks otherwise."
        )
        return "\n\n".join(section for section in sections if section).strip()

    sections = [
        DESCRIBE_CHAT_BASE_SYSTEM,
        f"UI language: {_normalize_lang(lang)}. Reply language: {reply_lang}.",
    ]
    if chat_mode == "chat":
        sections.append(
            "Default chat mode: normal conversation is allowed. "
            "Do not force every answer into prompt-writing. "
            "Only use prompt actions when the user clearly asks you to write, refine, append, or prepare an image-generation prompt. "
            "This mode cannot start image generation or editing. When the user asks to generate or edit an image, tell them to switch to Creative mode."
        )
    elif chat_mode == "creative":
        sections.append(CREATIVE_ASSISTANT_SYSTEM)
        preference = options.get("creative_preferences") if isinstance(options.get("creative_preferences"), dict) else {}
        preferred_style = str(preference.get("style") or "").strip()
        preferred_preset = str(preference.get("preset") or "").strip()
        auto_generate = bool(preference.get("auto_generate"))
        sections.append(
            "The UI will start valid generate_image actions immediately; keep the reply short and do not ask the user to confirm."
            if auto_generate
            else "The UI will show a review card before execution; tell the user they can review and confirm the request."
        )
        media_manifest = options.get("media_manifest") if isinstance(options.get("media_manifest"), list) else []
        if media_manifest:
            manifest_text = ", ".join(
                f"visual input {item.get('index')} ref={item.get('ref')} type={item.get('type')}"
                for item in media_manifest if isinstance(item, dict)
            )
            sections.append(
                f"Attached media manifest, in the exact order seen by the VLM: {manifest_text}. "
                "Use only these refs in media_refs."
            )
        capabilities = options.get("preset_capabilities") if isinstance(options.get("preset_capabilities"), list) else []
        if capabilities:
            capability_text = ", ".join(
                f"{item.get('name')}[min_images={item.get('min_images')}, max_images={item.get('max_images')}]"
                for item in capabilities if isinstance(item, dict) and item.get("output_type") == "image"
            )
            if capability_text:
                sections.append(f"Available image Preset input limits: {capability_text}.")
        if preferred_style or preferred_preset:
            sections.append(
                "Active session creative preference: "
                f"style={preferred_style or 'unspecified'}, preset={preferred_preset or 'choose a suitable Preset for the style'}. "
                "Use this as the default for image proposals. A clear one-image-only request may override it without changing the session preference."
            )
        else:
            sections.append(
                "No session creative preference is selected. The UI preference card already lets the user choose, so do not repeat that question. "
                "If the user names a style or Preset now, record it with set_creative_preference; otherwise choose a suitable Preset for the current request."
            )
        creative_target = {"preset": preferred_preset or options.get("target_preset")}
        sections.append(
            _describe_anima_prompt_skill(ANIMA_CREATIVE_PROMPT_ADAPTER)
            if _is_anima_prompt_target(creative_target)
            else NATURAL_PROMPT_SKILL.strip()
        )
    elif chat_mode == "guide":
        sections.append(
            "Guide mode: focus on helping the user choose SimpAI Studio main-interface workflows and presets. "
            "Do not return prompt-action JSON or start generation in this mode. "
            "Creative mode can run image Presets through Canvas Runner for text-to-image, single-image editing, and multi-image editing; "
            "recommend switching there when the user wants the chat to generate or edit images directly."
        )
        sections.append(_describe_preset_guide_skill())
    else:
        sections.append(
            "Prompt assistant mode: focus on turning the user's request and any attached image into a strong image-generation prompt, "
            "while still answering direct non-prompt questions normally."
        )
    if custom_system_prompt:
        sections.append(
            "User custom system prompt. Follow it for role, tone, and constraints unless it conflicts with the active mode's action contract:\n"
            f"{custom_system_prompt}"
        )
    if chat_mode != "guide" and options.get("enable_prompt_skills"):
        sections.append(_prompt_skill_section(options, lang))
    elif chat_mode == "guide":
        sections.append(
            "Return practical workflow guidance only. If the user needs prompt text, suggest switching to Prompt Assistant mode."
        )
    elif chat_mode != "creative":
        sections.append(
            "Prompt-writing skill is available, but it is not active for this turn. "
            "Return plain conversational text and no action JSON unless the user's next message asks for prompt text."
        )
    return "\n\n".join(section for section in sections if section).strip()


def _custom_runtime_params(payload):
    custom = payload.get("custom_api") if isinstance(payload.get("custom_api"), dict) else {}
    version = str(payload.get("version") or "").strip()
    custom_requested = bool(
        version == "Custom"
        or re.search(r"(^|\s)Custom($|\s)", version)
        or custom.get("base_url")
        or custom.get("model")
        or custom.get("api_key")
    )
    if not custom_requested:
        return version, {}

    base_url = str(custom.get("base_url") or custom.get("custom_base_url") or "").strip()
    model = str(custom.get("model") or custom.get("custom_model") or "").strip()
    api_key = str(custom.get("api_key") or custom.get("custom_api_key") or "").strip()
    params = {
        "version": "Custom",
        "custom_api_name": str(custom.get("api_name") or custom.get("custom_api_name") or "Custom").strip() or "Custom",
        "custom_provider": str(custom.get("provider") or custom.get("custom_provider") or "custom").strip() or "custom",
        "custom_api_format": str(custom.get("api_format") or custom.get("custom_api_format") or "openai_compatible").strip() or "openai_compatible",
        "custom_base_url": base_url,
        "custom_model": model,
        "custom_api_key": api_key,
        "custom_supports_images": _truthy(custom.get("supports_images", custom.get("custom_supports_images")), True),
    }
    return "Custom", params


def _prompt_for_runtime(message, current_prompt, include_current_prompt=False):
    message = str(message or "").strip()
    if not include_current_prompt:
        return message
    current_prompt = str(current_prompt or "").strip()
    if not current_prompt:
        return message
    return (
        f"{message}\n\n"
        "Current main prompt box content, for context only unless the user asks to refine or append:\n"
        f"{current_prompt[:4000]}"
    )


def build_runtime_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    message = str(payload.get("message") or payload.get("prompt") or "").strip()
    if not message:
        return {"ok": False, "error": "Message is empty."}

    conversation_id = _clean_text(payload.get("conversation_id")) or f"describe_vlm_chat:{int(time.time() * 1000)}"
    lang = _normalize_lang(payload.get("lang") or payload.get("__lang"))
    current_prompt = str(payload.get("current_prompt") or "")
    media_sources = _media_sources_from_payload(payload, conversation_id)
    prompt_options = _prompt_options_from_payload(payload, lang)
    unload_after_chat = _truthy(payload.get("unload_after_chat", payload.get("free_after")), False)
    prompt_actions_enabled = bool(prompt_options.get("enable_prompt_skills") and prompt_options.get("chat_mode") not in {"raw", "guide"})
    generation_actions_enabled = bool(prompt_options.get("enable_generation_actions"))
    prompt_mode_active = prompt_options.get("chat_mode") in {"prompt", "guide", "creative"} or prompt_actions_enabled
    params = {
        "mode": "chat",
        "agent_mode": "raw",
        "agent_use_skills": False,
        "agent_use_canvas_context": False,
        "agent_action_hints": False,
        "compact_agent_prompt": True,
        "disable_llm_draft_retry": True,
        "prompt": _prompt_for_runtime(message, current_prompt, include_current_prompt=prompt_options["include_current_prompt"]),
        "user_system_prompt": _describe_chat_system_prompt(prompt_options, lang),
        "describe_chat_mode": prompt_options["chat_mode"],
        "describe_prompt_mode": prompt_options["mode"],
        "describe_prompt_intent": prompt_options["prompt_intent"],
        "describe_prompt_actions_enabled": prompt_actions_enabled,
        "describe_generation_actions_enabled": generation_actions_enabled,
        "describe_actions_enabled": prompt_actions_enabled or generation_actions_enabled,
        "describe_prompt_target_preset": prompt_options["target_preset"],
        "describe_prompt_target_backend_engine": prompt_options["target_backend_engine"],
        "describe_prompt_target_task_method": prompt_options["target_task_method"],
        "describe_prompt_target_text_encoder": prompt_options["target_text_encoder"],
        "describe_prompt_target_base_model": prompt_options["target_base_model"],
        "describe_current_prompt_included": bool(prompt_options["include_current_prompt"] and str(current_prompt or "").strip()),
        "describe_custom_system_prompt": bool(prompt_options["custom_system_prompt"]),
        "describe_system_prompt_template_id": prompt_options["system_prompt_template_id"],
        "describe_output_tags": prompt_options["output_tags"],
        "describe_output_chinese": prompt_options["output_chinese"],
        "describe_output_artist": prompt_options["output_artist"],
        "describe_unload_after_chat": unload_after_chat,
        "describe_creative_preference_style": prompt_options["creative_preferences"]["style"],
        "describe_creative_preference_preset": prompt_options["creative_preferences"]["preset"],
        "describe_creative_auto_generate": prompt_options["creative_preferences"]["auto_generate"],
        "describe_media_manifest": prompt_options["media_manifest"],
        "describe_preset_capabilities": prompt_options["preset_capabilities"],
        "free_after": unload_after_chat,
        "conversation_id": conversation_id,
        "save_context": True,
        "max_history": 16,
        "context_chars": 6000,
        "max_tokens": 1400 if prompt_mode_active else 1800,
        "temperature": 0.45 if prompt_mode_active else 0.7,
        "top_p": 0.85 if prompt_mode_active else 0.9,
        "top_k": 40,
        "repetition_penalty": 1.05,
    }
    version, custom_params = _custom_runtime_params(payload)
    if version:
        params["version"] = version
    if custom_params:
        params.update(custom_params)

    runtime_payload = {
        "project_id": "describe_image_chat",
        "node_id": "describe_vlm_chat",
        "conversation_id": conversation_id,
        "asset_sources": media_sources,
        "chat_messages": _normalize_history(payload.get("history"), limit=18, budget=6000),
        "chat_messages_full": _normalize_history(payload.get("history_full") or payload.get("history"), limit=32, budget=9000),
        "context": payload.get("context") if isinstance(payload.get("context"), dict) else {},
        "agent_context": None,
        "params": params,
    }
    if params.get("custom_api_key"):
        runtime_payload["api_key"] = params.get("custom_api_key")

    return {
        "ok": True,
        "runtime_payload": runtime_payload,
    }


def _creative_director_system_prompt(payload, lang):
    preference = _normalize_creative_preferences(payload.get("creative_preferences"))
    preset = preference.get("preset") or ""
    style = preference.get("style") or "auto"
    previous_scene_key = _clean_text(payload.get("last_scene_key"))[:160]
    reply_lang = "English" if _normalize_lang(lang) == "en" else "Chinese"
    prompt_skill = (
        _describe_anima_prompt_skill(ANIMA_CREATIVE_PROMPT_ADAPTER)
        if _is_anima_prompt_target({"preset": preset})
        else NATURAL_PROMPT_SKILL
    )
    return (
        f"{CREATIVE_DIRECTOR_SYSTEM}\n\n"
        f"UI reply language: {reply_lang}. Session preference: style={style}, preset={preset or 'agent chooses'}. "
        f"Previously offered scene_key={previous_scene_key or 'none'}; do not offer the same scene again. "
        "The offer_text must use the UI reply language. The image prompt must follow the preferred Preset's prompt format.\n\n"
        f"{prompt_skill.strip()}"
    )


def build_creative_offer_runtime_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    conversation_id = _clean_text(payload.get("conversation_id")) or f"describe_vlm_chat:{int(time.time() * 1000)}"
    request_id = _clean_text(payload.get("request_id")) or f"director:{int(time.time() * 1000)}"
    lang = _normalize_lang(payload.get("lang") or payload.get("__lang"))
    user_message = _clean_multiline_text(payload.get("message"), limit=3000)
    assistant_reply = _clean_multiline_text(payload.get("assistant_reply"), limit=5000)
    if not user_message or not assistant_reply:
        return {"ok": False, "error": "Creative director context is incomplete."}
    prompt = (
        "Evaluate the latest exchange for a proactive image offer.\n\n"
        f"Latest user message:\n{user_message}\n\n"
        f"Main assistant reply already shown:\n{assistant_reply}"
    )
    params = {
        "mode": "chat",
        "agent_mode": "raw",
        "agent_use_skills": False,
        "agent_use_canvas_context": False,
        "agent_action_hints": False,
        "compact_agent_prompt": True,
        "disable_llm_draft_retry": True,
        "prompt": prompt,
        "user_system_prompt": _creative_director_system_prompt(payload, lang),
        "describe_chat_mode": "creative_director",
        "describe_actions_enabled": False,
        "free_after": _truthy(payload.get("unload_after_chat", payload.get("free_after")), False),
        "conversation_id": f"{conversation_id}:visual_director:{request_id}",
        "save_context": False,
        "max_history": 14,
        "context_chars": 6500,
        "max_tokens": 800,
        "temperature": 0.25,
        "top_p": 0.8,
        "top_k": 30,
        "repetition_penalty": 1.03,
    }
    version, custom_params = _custom_runtime_params(payload)
    if version:
        params["version"] = version
    if custom_params:
        params.update(custom_params)
    runtime_payload = {
        "project_id": "describe_image_chat_director",
        "node_id": "describe_vlm_chat_visual_director",
        "conversation_id": params["conversation_id"],
        "asset_sources": [],
        "chat_messages": _normalize_history(payload.get("history"), limit=14, budget=6500),
        "chat_messages_full": _normalize_history(payload.get("history_full") or payload.get("history"), limit=20, budget=8000),
        "context": {"request_kind": "creative_offer"},
        "agent_context": None,
        "params": params,
    }
    if params.get("custom_api_key"):
        runtime_payload["api_key"] = params.get("custom_api_key")
    return {"ok": True, "runtime_payload": runtime_payload, "conversation_id": conversation_id}


def _extract_json_object(text):
    source = str(text or "").strip()
    if not source:
        return None
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", source, re.I)
    if fenced:
        source = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(source):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(source[index:])
            if isinstance(value, dict):
                return value
        except Exception:
            continue
    return None


def parse_creative_offer_response(text, lang="cn", default_generation_preset="Z-imageT"):
    data = _extract_json_object(text)
    if not isinstance(data, dict) or not _truthy(data.get("offer"), False):
        return {"offer": False}
    try:
        score = max(0.0, min(1.0, float(data.get("score") or 0.0)))
    except Exception:
        score = 0.0
    reason = str(data.get("reason") or "").strip().lower().replace("-", "_")
    prompt = str(data.get("prompt") or data.get("positive_prompt") or "").strip()
    if score < CREATIVE_OFFER_MIN_SCORE or reason not in CREATIVE_OFFER_REASONS or not prompt:
        return {"offer": False}
    prompt = sanitize_danbooru_character_outfit_tags(prompt)
    prompt = canvas_danbooru_service._canvas_prompt_safe_danbooru_text(prompt)
    scene_key = re.sub(r"[^a-z0-9:_-]+", "-", str(data.get("scene_key") or "").strip().lower()).strip("-")[:160]
    if not scene_key:
        scene_key = re.sub(r"[^a-z0-9:_-]+", "-", prompt.lower()).strip("-")[:160]
    preset = re.sub(
        r"[\x00-\x1f\x7f]+",
        "",
        str(data.get("preset") or data.get("preset_name") or default_generation_preset or "Z-imageT"),
    ).strip()[:120]
    offer_text = _clean_multiline_text(data.get("offer_text") or data.get("reply"), limit=240)
    if not offer_text:
        offer_text = "I want to draw this moment." if _normalize_lang(lang) == "en" else "我想画下这一幕。"
    return {
        "offer": True,
        "score": score,
        "reason": reason,
        "scene_key": scene_key,
        "offer_text": offer_text,
        "prompt": prompt,
        "preset": preset or "Z-imageT",
        "aspect_ratio": _normalize_creative_aspect_ratio(data.get("aspect_ratio") or data.get("aspect") or data.get("ratio")),
        "image_number": _normalize_creative_image_number(data.get("image_number") or data.get("count") or 1),
    }


_DANBOORU_CHARACTER_TAG_RE = re.compile(r"^(?P<name>[a-z0-9][a-z0-9_]*?)_\((?P<context>[^)]*)\)$", re.I)


def sanitize_danbooru_character_outfit_tags(prompt_text):
    source = str(prompt_text or "").strip()
    if "," not in source:
        return source

    tags = [tag.strip() for tag in source.split(",")]
    character_prefixes = set()
    for tag in tags:
        match = _DANBOORU_CHARACTER_TAG_RE.match(tag)
        if not match:
            continue
        context = match.group("context").lower()
        if "outfit" in context:
            continue
        character_prefixes.add(match.group("name").lower())

    if not character_prefixes:
        return source

    cleaned = []
    changed = False
    seen = set()
    for tag in tags:
        if not tag:
            continue
        match = _DANBOORU_CHARACTER_TAG_RE.match(tag)
        if match and match.group("name").lower() in character_prefixes and "outfit" in match.group("context").lower():
            changed = True
            continue
        tag_key = tag.lower()
        if tag_key in seen:
            changed = True
            continue
        seen.add(tag_key)
        cleaned.append(tag)

    return ", ".join(cleaned) if changed else source


def _normalize_creative_aspect_ratio(value):
    text = str(value or "auto").strip().lower().replace("：", ":").replace("x", ":").replace("*", ":")
    aliases = {
        "square": "1:1",
        "landscape": "16:9",
        "horizontal": "16:9",
        "portrait": "9:16",
        "vertical": "9:16",
    }
    text = aliases.get(text, text)
    return text if text in CREATIVE_ASPECT_RATIOS else "auto"


def _normalize_creative_image_number(value):
    try:
        number = int(float(value))
    except Exception:
        number = 1
    return max(1, min(4, number))


def _normalize_generation_media_refs(value, available_media_refs=None):
    available = []
    for item in available_media_refs if isinstance(available_media_refs, list) else []:
        ref = _clean_text(item.get("ref") if isinstance(item, dict) else item)[:160]
        media_type = str(item.get("type") or "image").strip().lower() if isinstance(item, dict) else "image"
        if ref and media_type == "image" and ref not in available:
            available.append(ref)
    allowed = set(available)
    normalized = []
    raw_refs = value if isinstance(value, list) else []
    for item in raw_refs:
        ref = _clean_text(item.get("ref") if isinstance(item, dict) else item)[:160]
        if ref and ref in allowed and ref not in normalized:
            normalized.append(ref)
    return normalized, available


def _normalize_generation_task(value, media_refs):
    task = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "t2i": "text_to_image",
        "generate": "text_to_image",
        "edit": "image_edit",
        "image_to_image": "image_edit",
        "multi_edit": "multi_image_edit",
        "multi_image": "multi_image_edit",
    }
    task = aliases.get(task, task)
    if task not in {"text_to_image", "image_edit", "multi_image_edit"}:
        task = "multi_image_edit" if len(media_refs) > 1 else "image_edit" if media_refs else "text_to_image"
    if not media_refs:
        return "text_to_image" if task == "text_to_image" else task
    return "multi_image_edit" if len(media_refs) > 1 else "image_edit"


def _generation_media_limit(preset, preset_capabilities, default=5):
    capability = _preset_capability_map(preset_capabilities).get(str(preset or "").strip().lower())
    if not capability:
        return max(0, min(5, int(default or 5)))
    try:
        return max(0, min(5, int(capability.get("max_images") or 0)))
    except Exception:
        return 0


def _apply_generation_media_limits(actions, available_media_refs=None, preset_capabilities=None):
    normalized = []
    _, available = _normalize_generation_media_refs([], available_media_refs)
    for action in actions or []:
        if not isinstance(action, dict) or action.get("type") != "generate_image":
            normalized.append(action)
            continue
        item = dict(action)
        refs, _ = _normalize_generation_media_refs(item.get("media_refs"), available_media_refs)
        limit = _generation_media_limit(item.get("preset"), preset_capabilities)
        task = _normalize_generation_task(item.get("task"), refs)
        if task != "text_to_image" and not refs:
            refs = available[:limit]
        refs = refs[:limit]
        item["media_refs"] = refs
        item["task"] = _normalize_generation_task(task, refs)
        normalized.append(item)
    return normalized


def normalize_limited_actions(
    actions,
    allow_generation=False,
    default_generation_preset="Z-imageT",
    available_media_refs=None,
    preset_capabilities=None,
):
    normalized = []
    for item in actions if isinstance(actions, list) else []:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("action") or "").strip().lower().replace("-", "_")
        if action_type == "set_creative_preference":
            if not allow_generation or str(item.get("scope") or "session").strip().lower() != "session":
                continue
            style = str(item.get("style") or "").strip().lower()
            if style not in {"anime", "realistic", "auto", "custom"}:
                style = ""
            preset = re.sub(r"[\x00-\x1f\x7f]+", "", str(item.get("preset") or item.get("preset_name") or "")).strip()[:120]
            if not style and not preset:
                continue
            normalized.append(
                {
                    "type": "set_creative_preference",
                    "style": style or "custom",
                    "preset": preset,
                    "scope": "session",
                }
            )
            continue
        if action_type in GENERATION_ACTION_ALIASES:
            action_type = "generate_image" if allow_generation else "set_prompt"
        elif action_type in {
            "replace_prompt",
            "fill_prompt",
            "send_prompt",
            "write_prompt",
        }:
            action_type = "set_prompt"
        if action_type not in ALLOWED_PROMPT_ACTIONS and action_type != "generate_image":
            continue
        prompt_text = str(
            item.get("prompt")
            or item.get("text")
            or item.get("value")
            or item.get("positive_prompt")
            or ""
        ).strip()
        if not prompt_text:
            continue
        prompt_text = sanitize_danbooru_character_outfit_tags(prompt_text)
        prompt_text = canvas_danbooru_service._canvas_prompt_safe_danbooru_text(prompt_text)
        if action_type == "generate_image":
            preset = re.sub(
                r"[\x00-\x1f\x7f]+",
                "",
                str(item.get("preset") or item.get("preset_name") or default_generation_preset or "Z-imageT"),
            ).strip()[:120]
            refs, available = _normalize_generation_media_refs(
                item.get("media_refs") or item.get("input_refs"),
                available_media_refs,
            )
            task = _normalize_generation_task(item.get("task") or item.get("task_type"), refs)
            limit = _generation_media_limit(preset, preset_capabilities)
            if task != "text_to_image" and not refs:
                refs = available[:limit]
            refs = refs[:limit]
            normalized.append(
                {
                    "type": "generate_image",
                    "target": "canvas_run",
                    "task": _normalize_generation_task(task, refs),
                    "media_refs": refs,
                    "prompt": prompt_text,
                    "preset": preset or "Z-imageT",
                    "aspect_ratio": _normalize_creative_aspect_ratio(
                        item.get("aspect_ratio") or item.get("aspect") or item.get("ratio")
                    ),
                    "image_number": _normalize_creative_image_number(
                        item.get("image_number") or item.get("count") or item.get("images")
                    ),
                    "label": str(item.get("label") or "").strip()[:120],
                }
            )
            continue
        if action_type in {"refine_prompt", "describe_image_to_prompt", "text_to_prompt"}:
            action_type = "set_prompt"
        normalized.append(
            {
                "type": action_type,
                "target": "main_prompt",
                "prompt": prompt_text,
                "label": str(item.get("label") or "").strip(),
            }
        )
    return normalized[:3]


def parse_limited_response(
    text,
    lang="cn",
    allow_actions=True,
    allow_generation=False,
    default_generation_preset="Z-imageT",
    available_media_refs=None,
    preset_capabilities=None,
):
    if not allow_actions:
        return {"reply": str(text or "").strip(), "actions": [], "raw_json": None}
    data = _extract_json_object(text)
    if not isinstance(data, dict):
        return {"reply": str(text or "").strip(), "actions": [], "raw_json": None}
    actions = normalize_limited_actions(
        data.get("actions"),
        allow_generation=allow_generation,
        default_generation_preset=default_generation_preset,
        available_media_refs=available_media_refs,
        preset_capabilities=preset_capabilities,
    )
    if not actions and data.get("prompt"):
        action_type = str(data.get("action") or data.get("type") or "set_prompt").strip()
        actions = normalize_limited_actions(
            [{**data, "type": action_type, "prompt": data.get("prompt")}],
            allow_generation=allow_generation,
            default_generation_preset=default_generation_preset,
            available_media_refs=available_media_refs,
            preset_capabilities=preset_capabilities,
        )
    reply = str(data.get("reply") or data.get("message") or data.get("text") or "").strip()
    if not reply and actions:
        reply = _localized_default_reply(actions[0].get("type"), lang)
    return {"reply": reply or str(text or "").strip(), "actions": actions, "raw_json": data}


_ANIMA_PROMPT_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_ANIMA_QUALITY_RE = re.compile(r"(?:^|,\s*)(?:masterpiece|best quality|very[_ ]aesthetic|high quality)(?:\s*,|$)", re.I)
_ANIMA_PERIOD_RE = re.compile(r"(?:^|,\s*)(?:newest|recent|mid|early|old|year\s+\d{4})(?:\s*,|$)", re.I)
_ANIMA_RATING_RE = re.compile(r"(?:^|,\s*)(?:safe|sensitive|nsfw|explicit)(?:\s*,|$)", re.I)


def _is_anima_positive_prompt(prompt):
    source = str(prompt or "").strip()
    if not source or _ANIMA_PROMPT_CJK_RE.search(source) or source.count(",") < 4:
        return False
    return bool(
        _ANIMA_QUALITY_RE.search(source)
        and _ANIMA_PERIOD_RE.search(source)
        and _ANIMA_RATING_RE.search(source)
    )


def _repair_creative_anima_prompt(item, source_prompt=""):
    action = dict(item) if isinstance(item, dict) else {}
    prompt = str(action.get("prompt") or "").strip()
    if not prompt or not _is_anima_prompt_target({"preset": action.get("preset")}) or _is_anima_positive_prompt(prompt):
        return action

    from modules import canvas_vlm_agent

    effective_prompt = "\n".join(part for part in (str(source_prompt or "").strip(), prompt) if part)
    composed = canvas_vlm_agent._canvas_compose_anima_prompt(
        effective_prompt,
        {"type": "generate_image", "prompt": prompt},
    )
    repaired_prompt = str(composed.get("prompt") or "").strip()
    if repaired_prompt and not _ANIMA_PROMPT_CJK_RE.search(repaired_prompt):
        action["prompt"] = repaired_prompt
    return action


def _repair_creative_anima_actions(actions, source_prompt=""):
    return [
        _repair_creative_anima_prompt(action, source_prompt)
        if isinstance(action, dict) and action.get("type") == "generate_image"
        else action
        for action in (actions or [])
    ]


def _apply_creative_preference_preset(actions, active_preset="", preset_capabilities=None):
    preferred_preset = re.sub(r"[\x00-\x1f\x7f]+", "", str(active_preset or "")).strip()[:120]
    normalized = []
    for action in actions or []:
        if not isinstance(action, dict):
            normalized.append(action)
            continue
        item = dict(action)
        if item.get("type") == "set_creative_preference" and item.get("preset"):
            preferred_preset = str(item.get("preset") or "").strip()[:120]
        elif item.get("type") == "generate_image" and preferred_preset:
            refs = item.get("media_refs") if isinstance(item.get("media_refs"), list) else []
            if len(refs) <= _generation_media_limit(preferred_preset, preset_capabilities):
                item["preset"] = preferred_preset
        normalized.append(item)
    return normalized


def apply_prompt_action_payload(payload_text, current_prompt=""):
    try:
        data = json.loads(str(payload_text or "{}"))
    except Exception:
        return current_prompt
    actions = normalize_limited_actions([data])
    if not actions:
        actions = normalize_limited_actions(data.get("actions") if isinstance(data, dict) else [])
    if not actions:
        return current_prompt
    action = actions[0]
    prompt_text = str(action.get("prompt") or "").strip()
    if not prompt_text:
        return current_prompt
    if action.get("type") == "append_prompt":
        existing = str(current_prompt or "").strip()
        if not existing:
            return prompt_text
        separator = "\n" if "\n" in existing or "\n" in prompt_text else ", "
        return f"{existing.rstrip()}{separator}{prompt_text.lstrip()}"
    return prompt_text


def _describe_input_media_assets(payload, asset_refs):
    manifest = _media_manifest_from_payload(payload)
    refs = asset_refs if isinstance(asset_refs, list) else []
    allowed_asset_keys = (
        "kind",
        "asset_id",
        "mime",
        "size",
        "width",
        "height",
        "path",
        "output_path",
        "asset_relative_path",
        "relative_path",
        "preview_url",
    )
    refs_by_source_index = {}
    for position, asset_ref in enumerate(refs):
        if not isinstance(asset_ref, dict):
            continue
        match = re.search(r":(?:image|video):(\d+)$", str(asset_ref.get("node_id") or ""))
        source_index = int(match.group(1)) if match else position
        refs_by_source_index.setdefault(source_index, asset_ref)
    assets = []
    for index, item in enumerate(manifest):
        asset_ref = refs_by_source_index.get(index) or {}
        if not asset_ref:
            continue
        clean_asset = {
            key: asset_ref.get(key)
            for key in allowed_asset_keys
            if asset_ref.get(key) not in (None, "")
        }
        assets.append(
            {
                "ref": item.get("ref"),
                "index": item.get("index"),
                "type": item.get("type"),
                "name": item.get("name"),
                "asset": clean_asset,
            }
        )
    return assets


def run_describe_vlm_chat(payload):
    payload = payload if isinstance(payload, dict) else {}
    conversation_id = str(payload.get("conversation_id") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    request_kind = str(payload.get("request_kind") or "").strip().lower()
    built = build_creative_offer_runtime_payload(payload) if request_kind == "creative_offer" else build_runtime_payload(payload)
    if not built.get("ok"):
        return built

    from modules import canvas_vlm_runtime

    runtime_payload = built["runtime_payload"]
    if is_describe_vlm_chat_cancelled(conversation_id, request_id):
        clear_describe_vlm_chat_cancel(conversation_id, request_id)
        return {
            "ok": False,
            "cancelled": True,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "error": "Stopped.",
            "details": "Stopped by user.",
        }
    result = canvas_vlm_runtime.canvas_vlm_run(runtime_payload)
    if is_describe_vlm_chat_cancelled(conversation_id, request_id):
        clear_describe_vlm_chat_cancel(conversation_id, request_id)
        return {
            "ok": False,
            "cancelled": True,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "error": "Stopped.",
            "details": "Stopped by user.",
        }
    if not isinstance(result, dict) or not result.get("ok"):
        return result if isinstance(result, dict) else {"ok": False, "error": "Invalid VLM response."}

    if request_kind == "creative_offer":
        preference = _normalize_creative_preferences(payload.get("creative_preferences"))
        offer = parse_creative_offer_response(
            result.get("text") or result.get("raw_text") or "",
            payload.get("lang"),
            default_generation_preset=preference.get("preset") or "Z-imageT",
        )
        if offer.get("offer"):
            if preference.get("preset"):
                offer["preset"] = preference["preset"]
            offer = _repair_creative_anima_prompt(offer, payload.get("message"))
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "creative_offer": offer,
        }

    params = runtime_payload.get("params") if isinstance(runtime_payload.get("params"), dict) else {}
    parsed = parse_limited_response(
        result.get("text") or result.get("raw_text") or "",
        (payload or {}).get("lang"),
        allow_actions=bool(params.get("describe_actions_enabled")),
        allow_generation=bool(params.get("describe_generation_actions_enabled")),
        default_generation_preset=params.get("describe_creative_preference_preset") or "Z-imageT",
        available_media_refs=runtime_payload.get("params", {}).get("describe_media_manifest"),
        preset_capabilities=runtime_payload.get("params", {}).get("describe_preset_capabilities"),
    )
    if params.get("describe_generation_actions_enabled"):
        parsed["actions"] = _apply_creative_preference_preset(
            parsed.get("actions"),
            params.get("describe_creative_preference_preset"),
            runtime_payload.get("params", {}).get("describe_preset_capabilities"),
        )
        parsed["actions"] = _apply_generation_media_limits(
            parsed.get("actions"),
            runtime_payload.get("params", {}).get("describe_media_manifest"),
            runtime_payload.get("params", {}).get("describe_preset_capabilities"),
        )
        parsed["actions"] = _repair_creative_anima_actions(parsed.get("actions"), payload.get("message"))
    result = dict(result)
    original_text = str(result.get("text") or "")
    result["text"] = parsed.get("reply") or original_text
    if result["text"] != original_text and not result.get("raw_text"):
        result["raw_text"] = original_text
    result["limited_actions"] = parsed.get("actions") or []
    result["input_media_assets"] = _describe_input_media_assets(payload, result.get("asset_refs"))
    result["agent_actions"] = []
    return result
