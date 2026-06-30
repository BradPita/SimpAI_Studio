from comfy_api.latest import io


DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


def _format_gemma3_vlm_prompt(prompt, system_prompt=DEFAULT_SYSTEM_PROMPT):
    prompt = (prompt or "").strip()
    system_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT
    return (
        f"<start_of_turn>system\n{system_prompt}<end_of_turn>\n"
        f"<start_of_turn>user\n\n<image_soft_token>\n\n{prompt}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


class SimpAIGemma3VLMPrompt(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SimpAIGemma3VLMPrompt",
            display_name="SimpAI Gemma3 VLM Prompt",
            category="conditioning/text",
            description="Wrap a prompt in Gemma3 image-chat format with an explicit image token.",
            inputs=[
                io.String.Input("prompt", multiline=True, dynamic_prompts=True),
                io.String.Input("system_prompt", multiline=True, default=DEFAULT_SYSTEM_PROMPT),
            ],
            outputs=[
                io.String.Output(display_name="prompt"),
            ],
        )

    @classmethod
    def execute(cls, prompt, system_prompt) -> io.NodeOutput:
        return io.NodeOutput(_format_gemma3_vlm_prompt(prompt, system_prompt))


NODE_CLASS_MAPPINGS = {
    "SimpAIGemma3VLMPrompt": SimpAIGemma3VLMPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIGemma3VLMPrompt": "SimpAI Gemma3 VLM Prompt",
}
