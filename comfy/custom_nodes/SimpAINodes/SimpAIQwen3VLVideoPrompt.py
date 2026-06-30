from comfy_api.latest import io


DEFAULT_SYSTEM_PROMPT = (
    "You are a vision-language assistant. The attached images are sampled frames "
    "from one video in chronological order."
)


def _format_qwen3vl_video_prompt(prompt, frame_count, system_prompt=DEFAULT_SYSTEM_PROMPT, thinking=False):
    prompt = (prompt or "").strip()
    system_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT
    frame_count = max(1, int(frame_count))

    frame_lines = []
    for index in range(frame_count):
        frame_lines.append(
            f"Frame {index + 1}: <|vision_start|><|image_pad|><|vision_end|>"
        )

    assistant_start = "<|im_start|>assistant\n"
    if not thinking:
        assistant_start += "<think>\n\n</think>\n\n"

    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        "<|im_start|>user\n"
        "Treat these images as consecutive frames from a single video, not as unrelated static images.\n"
        + "\n".join(frame_lines)
        + "\n\nFollow the system prompt and the task exactly. Do not answer with a visual caption unless the task asks for one."
        + "\nFor video-to-audio or sound-design tasks, output synchronized ambient sound, foreground action sounds, spatial distance, voice handling, and motion-sound timing."
        + "\nOutput only the final prompt text, with no notes or explanation."
        + f"\n\nTask: {prompt}<|im_end|>\n"
        + assistant_start
    )


class SimpAIQwen3VLVideoPrompt(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SimpAIQwen3VLVideoPrompt",
            display_name="SimpAI Qwen3VL Video Prompt",
            category="conditioning/text",
            description="Wrap a prompt in Qwen3VL format with one image token per sampled video frame.",
            inputs=[
                io.String.Input("prompt", multiline=True, dynamic_prompts=True),
                io.Int.Input("frame_count", default=1, min=1, max=64, step=1),
                io.String.Input("system_prompt", multiline=True, default=DEFAULT_SYSTEM_PROMPT),
                io.Boolean.Input("thinking", default=False),
            ],
            outputs=[
                io.String.Output(display_name="prompt"),
            ],
        )

    @classmethod
    def execute(cls, prompt, frame_count, system_prompt, thinking) -> io.NodeOutput:
        return io.NodeOutput(_format_qwen3vl_video_prompt(prompt, frame_count, system_prompt, thinking))


NODE_CLASS_MAPPINGS = {
    "SimpAIQwen3VLVideoPrompt": SimpAIQwen3VLVideoPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIQwen3VLVideoPrompt": "SimpAI Qwen3VL Video Prompt",
}
