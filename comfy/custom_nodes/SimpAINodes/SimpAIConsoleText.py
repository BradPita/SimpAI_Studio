from comfy_api.latest import io


def _print_text_to_console(text, label):
    text = "" if text is None else str(text)
    label = (label or "SimpAI text").strip() or "SimpAI text"
    print(f"\n[SimpAIConsoleText] {label}\n{text}\n[/SimpAIConsoleText]", flush=True)
    return text


class SimpAIConsoleText(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SimpAIConsoleText",
            display_name="SimpAI Console Text",
            category="utils/text",
            description="Print text to the console and pass it through unchanged.",
            inputs=[
                io.String.Input("text", multiline=True, dynamic_prompts=True),
                io.String.Input("label", default="SimpAI final prompt"),
            ],
            outputs=[
                io.String.Output(display_name="text"),
            ],
        )

    @classmethod
    def execute(cls, text, label) -> io.NodeOutput:
        return io.NodeOutput(_print_text_to_console(text, label))


NODE_CLASS_MAPPINGS = {
    "SimpAIConsoleText": SimpAIConsoleText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIConsoleText": "SimpAI Console Text",
}
