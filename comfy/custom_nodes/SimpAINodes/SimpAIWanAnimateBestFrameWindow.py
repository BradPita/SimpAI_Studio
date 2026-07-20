import math

from comfy_api.latest import io


def _align_4n1(value):
    value = max(1, int(round(value)))
    return value + ((1 - value) % 4)


def _pass_count(total_frames, window):
    first_keep = window - 4
    repeat_keep = window - 9
    if total_frames <= first_keep:
        return 1
    return 1 + math.ceil((total_frames - first_keep) / repeat_keep)


def _best_wan_animate_window(total_frames):
    total_frames = max(1, int(total_frames))
    one_pass_window = max(17, _align_4n1(total_frames + 4))
    if one_pass_window <= 97:
        return one_pass_window

    best_window = 57
    best_candidate = None
    for window in range(57, 98, 4):
        pass_count = _pass_count(total_frames, window)
        output_capacity = (window - 4) + (pass_count - 1) * (window - 9)
        candidate = (pass_count, output_capacity - total_frames, -window)
        if best_candidate is None or candidate < best_candidate:
            best_candidate = candidate
            best_window = window
    return best_window


class SimpAIWanAnimateBestFrameWindow(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SimpAIWanAnimateBestFrameWindow",
            display_name="SimpAI Wan Animate Best Frame Window",
            category="image/video",
            description="Choose a Wan Animate 4n+1 frame window without leaving a short final segment.",
            inputs=[
                io.Int.Input("frame_count", default=81, min=1, max=100000, step=1),
                io.Int.Input("force_size", default=1, min=1, max=1025, step=4),
            ],
            outputs=[
                io.Int.Output(display_name="frame_window_size"),
            ],
        )

    @classmethod
    def execute(cls, frame_count, force_size) -> io.NodeOutput:
        if force_size > 1:
            forced_window = min(97, max(17, _align_4n1(force_size)))
            return io.NodeOutput(forced_window)
        return io.NodeOutput(_best_wan_animate_window(frame_count))


NODE_CLASS_MAPPINGS = {
    "SimpAIWanAnimateBestFrameWindow": SimpAIWanAnimateBestFrameWindow,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIWanAnimateBestFrameWindow": "SimpAI Wan Animate Best Frame Window",
}
