import torch
import nodes
import node_helpers
import comfy.model_management
import comfy.utils
import comfy.latent_formats
import comfy.clip_vision
from comfy_api.latest import io


def linear_interpolation(features, input_fps, output_fps, output_len=None):
    features = features.transpose(1, 2)
    seq_len = features.shape[2] / float(input_fps)
    if output_len is None:
        output_len = int(seq_len * output_fps)
    output_features = torch.nn.functional.interpolate(
        features, size=output_len, align_corners=True, mode='linear')
    return output_features.transpose(1, 2)


from comfy.ldm.wan.model_multitalk import InfiniteTalkOuterSampleWrapper, MultiTalkCrossAttnPatch, project_audio_features
import comfy.patcher_extension


def match_color_to_reference(frames, reference):
    frames_f = frames.to(dtype=torch.float32)
    reference_f = reference.to(device=frames_f.device, dtype=torch.float32)
    dims = (0, 1, 2)
    frames_mean = frames_f.mean(dim=dims, keepdim=True)
    frames_std = frames_f.std(dim=dims, keepdim=True).clamp_min(1e-4)
    reference_mean = reference_f.mean(dim=dims, keepdim=True)
    reference_std = reference_f.std(dim=dims, keepdim=True).clamp_min(1e-4)
    matched = (frames_f - frames_mean) / frames_std * reference_std + reference_mean
    return matched.clamp(0.0, 1.0).to(dtype=frames.dtype)


class SimpAIPainterAV2V(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SimpAIPainterAV2V",
            category="conditioning/video_models",
            inputs=[
                io.Model.Input("model"),
                io.ModelPatch.Input("model_patch"),
                io.Conditioning.Input("positive"),
                io.Conditioning.Input("negative"),
                io.Vae.Input("vae"),
                io.Int.Input("width", default=832, min=16, max=nodes.MAX_RESOLUTION, step=16),
                io.Int.Input("height", default=480, min=16, max=nodes.MAX_RESOLUTION, step=16),
                io.Int.Input("length", default=81, min=1, max=nodes.MAX_RESOLUTION, step=4),
                io.Float.Input("fps", default=25.0, min=1.0, max=60.0, step=0.1, tooltip="Video frame rate for lip sync alignment"),
                io.AudioEncoderOutput.Input("audio_encoder"),
                io.Image.Input("video"),
                io.Mask.Input("mask", optional=True),
                io.Image.Input("start_image", optional=True),
                io.Image.Input("previous_frames", optional=True),
                io.Boolean.Input(
                    "match_previous_color_to_video",
                    default=True,
                    optional=True,
                    advanced=True,
                    tooltip="Match continuation frames to the source video color before encoding.",
                ),
                io.ClipVisionOutput.Input("clip_vision_output", optional=True),
                io.Int.Input("motion_frame_count", default=9, min=1, max=33, step=1),
                io.Int.Input("audio_start", default=0, min=0, max=nodes.MAX_RESOLUTION, step=1),
                io.Float.Input("audio_scale", default=1.0, min=-10.0, max=10.0, step=0.01),
            ],
            outputs=[
                io.Model.Output("model"),
                io.Conditioning.Output("positive"),
                io.Conditioning.Output("negative"),
                io.Latent.Output("latent"),
            ],
        )

    @classmethod
    def execute(cls, model, model_patch, positive, negative, vae, width, height, length, fps, audio_encoder, video, mask=None, start_image=None, previous_frames=None, match_previous_color_to_video=True, clip_vision_output=None, motion_frame_count=9, audio_start=0, audio_scale=1.0) -> io.NodeOutput:
        device = comfy.model_management.get_torch_device()
        model_dtype = model.model_dtype()

        if model_dtype == torch.float8_e4m3fn:
            compute_dtype = torch.float16
        else:
            compute_dtype = model_dtype

        length = max(1, int(length))
        if (length - 1) % 4 != 0:
            length = ((length - 1 + 3) // 4) * 4 + 1

        video_frame_count = video.shape[0]
        if video_frame_count < length:
            pad = video[-1:].repeat((length - video_frame_count, 1, 1, 1))
            video = torch.cat([video, pad], dim=0)
        elif video_frame_count > length:
            video = video[:length]

        latent_video = vae.encode(video)
        out_latent = {"samples": latent_video}
        if mask is not None:
            if len(mask.shape) == 3:
                mask = mask.unsqueeze(1)
            out_latent["noise_mask"] = mask

        concat_latent_image = None
        if start_image is not None:
            start_image_proc = comfy.utils.common_upscale(start_image[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
            image = torch.ones((length, height, width, start_image_proc.shape[-1]), device=device, dtype=compute_dtype) * 0.5
            image[:start_image_proc.shape[0]] = start_image_proc.to(device=device, dtype=compute_dtype)

            concat_latent_image = vae.encode(image[:, :, :, :3].contiguous())
            concat_mask = torch.ones((1, 1, ((length - 1) // 4) + 1, concat_latent_image.shape[-2], concat_latent_image.shape[-1]), device=device, dtype=compute_dtype)
            concat_mask[:, :, :((start_image_proc.shape[0] - 1) // 4) + 1] = 0.0

            positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent_image, "concat_mask": concat_mask})
            negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent_image, "concat_mask": concat_mask})

        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})
            negative = node_helpers.conditioning_set_values(negative, {"clip_vision_output": clip_vision_output})

        model_patched = model.clone()

        all_layers = audio_encoder["encoded_audio_all_layers"]
        encoded_audio = torch.stack(all_layers, dim=0).squeeze(1)[1:]
        encoded_audio = encoded_audio.to(device=device, dtype=compute_dtype).contiguous()
        encoded_audio = linear_interpolation(encoded_audio, input_fps=50, output_fps=fps).movedim(0, 1)

        encoded_audio_list = [encoded_audio]
        is_extend = False
        if previous_frames is not None:
            motion_frame_count = max(1, int(motion_frame_count))
            if previous_frames.shape[0] < motion_frame_count:
                raise ValueError("Not enough previous frames provided.")
            motion_frames = comfy.utils.common_upscale(previous_frames[-motion_frame_count:].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
            if match_previous_color_to_video:
                reference_frames = comfy.utils.common_upscale(video[:motion_frame_count].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
                motion_frames = match_color_to_reference(motion_frames, reference_frames)
            motion_frames_latent = vae.encode(motion_frames[:, :, :, :3].contiguous())
            audio_start = max(0, int(audio_start))
            is_extend = True
        else:
            audio_start = max(0, int(audio_start))
            motion_source = concat_latent_image if concat_latent_image is not None else latent_video
            motion_frames_latent = motion_source[:, :, :1].contiguous().to(device=device, dtype=compute_dtype)
        audio_end = audio_start + length

        audio_embed = project_audio_features(model_patch.model.audio_proj, encoded_audio_list, audio_start, audio_end)
        audio_embed = audio_embed.to(device=device, dtype=compute_dtype).contiguous()
        model_patched.model_options["transformer_options"]["audio_embeds"] = audio_embed

        model_patched.add_wrapper_with_key(
            comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
            "infinite_talk_outer_sample",
            InfiniteTalkOuterSampleWrapper(
                motion_frames_latent,
                model_patch,
                is_extend=is_extend,
            ))
        model_patched.set_model_patch(MultiTalkCrossAttnPatch(model_patch, audio_scale), "attn2_patch")

        return io.NodeOutput(model_patched, positive, negative, out_latent)


NODE_CLASS_MAPPINGS = {
    "SimpAIPainterAV2V": SimpAIPainterAV2V,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpAIPainterAV2V": "SimpAI Painter AV2V",
}
