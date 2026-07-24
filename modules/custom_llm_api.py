import json
import re
import urllib.error
import urllib.request


OPENAI_CHAT_COMPLETIONS = "openai_compatible"
OPENAI_RESPONSES = "openai_responses"
SUPPORTED_API_FORMATS = (OPENAI_CHAT_COMPLETIONS, OPENAI_RESPONSES)


def normalize_api_format(value):
    api_format = str(value or OPENAI_CHAT_COMPLETIONS).strip() or OPENAI_CHAT_COMPLETIONS
    return api_format


def api_format_supported(value):
    return normalize_api_format(value) in SUPPORTED_API_FORMATS


def custom_llm_url(base_url, suffix):
    base = str(base_url or "").strip().rstrip("/")
    suffix = str(suffix or "").strip()
    if not suffix.startswith("/"):
        suffix = "/" + suffix
    return base + suffix


def responses_url(base_url):
    base = str(base_url or "").strip().rstrip("/")
    if re.search(r"/responses$", base, flags=re.IGNORECASE):
        return base
    if re.search(r"/v\d+(?:beta)?$", base, flags=re.IGNORECASE):
        return base + "/responses"
    return base + "/v1/responses"


def completion_url(base_url, api_format):
    if normalize_api_format(api_format) == OPENAI_RESPONSES:
        return responses_url(base_url)
    return custom_llm_url(base_url, "/chat/completions")


def models_url(base_url):
    base = str(base_url or "").strip().rstrip("/")
    base = re.sub(r"/(?:responses|chat/completions)$", "", base, flags=re.IGNORECASE)
    return custom_llm_url(base, "/models")


def _response_preview(body, limit=300):
    compact = re.sub(r"\s+", " ", str(body or "")).strip()
    return compact[:limit] or "<empty body>"


def request_json(url, payload=None, api_key="", method="POST", timeout=120):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    api_key = str(api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body:
                return {}
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                status = getattr(response, "status", None) or response.getcode()
                content_type = response.headers.get("Content-Type", "unknown")
                raise RuntimeError(
                    f"API returned non-JSON response (HTTP {status}, Content-Type: {content_type}): "
                    f"{_response_preview(body)}"
                ) from exc
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = None
        message = ""
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")
            elif isinstance(error, str):
                message = error
            if not message:
                message = str(parsed.get("message") or parsed.get("detail") or "")
        if not message:
            message = _response_preview(body)
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc


def _content_text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
        elif isinstance(item.get("content"), str):
            parts.append(item["content"])
    return "\n".join(part for part in parts if part)


def _responses_content(content):
    if not isinstance(content, list):
        return content
    converted = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type in ("text", "input_text", "output_text"):
            converted.append({"type": "input_text", "text": str(item.get("text") or "")})
            continue
        if item_type in ("image_url", "input_image"):
            image_value = item.get("image_url")
            if isinstance(image_value, dict):
                image_value = image_value.get("url")
            if image_value:
                converted.append({"type": "input_image", "image_url": str(image_value)})
    return converted


def chat_payload_to_responses(payload):
    payload = payload if isinstance(payload, dict) else {}
    instructions = []
    input_items = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip() or "user"
        content = message.get("content", "")
        if role in ("system", "developer"):
            text = _content_text(content).strip()
            if text:
                instructions.append(text)
            continue
        item = {"role": role, "content": _responses_content(content)}
        if item["content"] not in ("", [], None):
            input_items.append(item)

    result = {
        "model": payload.get("model"),
        "input": input_items,
        "stream": bool(payload.get("stream", False)),
    }
    if instructions:
        result["instructions"] = "\n\n".join(instructions)
    max_tokens = payload.get("max_output_tokens", payload.get("max_tokens"))
    if max_tokens is not None:
        result["max_output_tokens"] = int(max_tokens)
    for key in ("temperature", "top_p"):
        if payload.get(key) is not None:
            result[key] = payload[key]
    return result


def prepare_completion_request(base_url, api_format, chat_payload):
    api_format = normalize_api_format(api_format)
    if api_format == OPENAI_RESPONSES:
        return responses_url(base_url), chat_payload_to_responses(chat_payload)
    if api_format == OPENAI_CHAT_COMPLETIONS:
        return custom_llm_url(base_url, "/chat/completions"), chat_payload
    raise RuntimeError(f"Unsupported Custom API format: {api_format}")


def extract_response_text(response):
    if not isinstance(response, dict):
        return ""

    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts = []
    for output in response.get("output") or []:
        if not isinstance(output, dict):
            continue
        content = output.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        for item in content or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") in ("output_text", "text") and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item.get("content"), str):
                parts.append(item["content"])
    if any(part.strip() for part in parts):
        return "\n".join(part for part in parts if part)

    choices = response.get("choices")
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    text = _content_text(content)
    if text.strip():
        return text
    for key in ("reasoning_content", "reasoning"):
        reasoning = message.get(key) if isinstance(message, dict) else ""
        if isinstance(reasoning, str) and reasoning.strip() and reasoning.strip() != "None":
            return reasoning
    return str(content or "")
