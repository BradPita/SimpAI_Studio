# https://github.com/Comfy-Org/ComfyUI/blob/v0.26.1/comfy/sd1_clip.py
# https://github.com/Comfy-Org/ComfyUI/blob/v0.26.1/comfy/text_encoders/krea2.py
# https://github.com/Comfy-Org/ComfyUI/blob/v0.26.1/comfy/text_encoders/qwen35.py
# https://github.com/Comfy-Org/ComfyUI/blob/v0.26.1/comfy/text_encoders/qwen3vl.py

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.prompt_parser import SdConditioning

import torch

from backend import memory_management
from backend.args import dynamic_args
from backend.text_processing import emphasis, parsing
from modules.shared import opts


KREA2_TAP_LAYERS = [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35]


class PromptChunk:
    def __init__(self):
        self.tokens = []
        self.multipliers = []


class Krea2TextProcessingEngine:
    def __init__(self, text_encoder, tokenizer):
        self.emphasis = emphasis.get_current_option(opts.emphasis)()

        self.text_encoder = text_encoder
        self.tokenizer = tokenizer

        self.max_length = 99999999
        self.min_length = 1
        self.id_pad = 151643
        self.id_template = 151644
        self.id_image = 151655

        self.llama_template = "<|im_start|>system\nDescribe the image by detailing the color, shape, size, texture, quantity, text, spatial relationships of the objects and background:<|im_end|>\n<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n"
        self.image_template = "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>{}<|im_end|>\n<|im_start|>assistant\n"
        self.vision_block = "<|vision_start|><|image_pad|><|vision_end|>"
        self.intermediate_output = KREA2_TAP_LAYERS
        self.layer_norm_hidden_state = False

    def tokenize(self, texts, images=None):
        images = images or []
        template = self.image_template.replace(self.vision_block, self.vision_block * len(images), 1) if images else self.llama_template
        llama_texts = [template.format(text) if text else "" for text in texts]
        return self.tokenizer(llama_texts)["input_ids"]

    def tokenize_line(self, line: str, images=None):
        images = images or []
        parsed = parsing.parse_prompt_attention(line, self.emphasis.name)
        tokenized = self.tokenize([text for text, _ in parsed], images)

        chunks = []
        chunk = PromptChunk()

        def next_chunk():
            nonlocal chunk
            chunks.append(chunk)
            chunk = PromptChunk()

        for tokens, (text, weight) in zip(tokenized, parsed):
            embed_count = 0
            position = 0
            while position < len(tokens):
                token = tokens[position]

                if token == self.id_image:
                    token = {"type": "image", "data": images[embed_count], "original_type": "image"}
                    embed_count += 1

                chunk.tokens.append(token)
                chunk.multipliers.append(weight)
                position += 1

        if chunk.tokens or not chunks:
            next_chunk()

        return chunks

    def __call__(self, texts: "SdConditioning", images=None):
        images = images or []
        self.emphasis = emphasis.get_current_option(opts.emphasis)()
        if any(emphasis.uses_emphasis(x) for x in texts):
            dynamic_args.last_extra_generation_params["Emphasis"] = self.emphasis.name

        zs = []
        cache = {}

        for line in texts:
            if line in cache:
                line_z_values = cache[line]
            else:
                chunks = self.tokenize_line(line, images)
                line_z_values = []

                for chunk in chunks:
                    tokens = chunk.tokens
                    multipliers = chunk.multipliers

                    z = self.process_tokens([tokens], [multipliers])
                    z = self.strip_template(z, tokens)
                    line_z_values.append(z)
                cache[line] = line_z_values

            zs.extend(line_z_values)

        return zs

    def strip_template(self, out, tokens):
        template_end = 0
        count_im_start = 0

        for i, value in enumerate(tokens):
            try:
                elem = int(value)
                if elem == self.id_template and count_im_start < 2:
                    template_end = i
                    count_im_start += 1
            except TypeError:
                continue

        if len(tokens) > template_end + 2 and out.shape[2] > (template_end + 3):
            if int(tokens[template_end + 1]) == 872 and int(tokens[template_end + 2]) == 198:
                template_end += 3

        out = out[:, :, template_end:]
        return self.flatten_tap_layers(out)

    def flatten_tap_layers(self, out: torch.Tensor) -> torch.Tensor:
        b, layers, seq, hidden = out.shape
        return out.permute(0, 2, 1, 3).reshape(b, seq, layers * hidden)

    def process_embeds(self, batch_tokens):
        device = memory_management.text_encoder_device()

        embeds_out = []
        attention_masks = []
        num_tokens = []

        for tokens in batch_tokens:
            attention_mask = []
            tokens_temp = []
            other_embeds = []
            eos = False
            index = 0

            for item in tokens:
                try:
                    token = int(item)
                    attention_mask.append(0 if eos else 1)
                    tokens_temp.append(token)
                    if not eos and token == self.id_pad:
                        eos = True
                except TypeError:
                    other_embeds.append((index, item))
                index += 1

            tokens_embed = torch.tensor([tokens_temp], device=device, dtype=torch.long)
            tokens_embed = self.text_encoder.get_input_embeddings()(tokens_embed)

            index = 0
            embeds_info = []

            for position, item in other_embeds:
                emb, extra = self.text_encoder.preprocess_embed(item, device=device)
                if emb is None:
                    index -= 1
                    continue

                ind = index + position
                emb = emb.view(1, -1, emb.shape[-1]).to(device=device, dtype=torch.float32)
                emb_shape = emb.shape[1]

                assert emb.shape[-1] == tokens_embed.shape[-1]
                tokens_embed = torch.cat([tokens_embed[:, :ind], emb, tokens_embed[:, ind:]], dim=1)
                attention_mask = attention_mask[:ind] + [1] * emb_shape + attention_mask[ind:]
                index += emb_shape - 1
                emb_type = item.get("type", None)
                embeds_info.append({"type": emb_type, "index": ind, "size": emb_shape, "extra": extra})

            embeds_out.append(tokens_embed)
            attention_masks.append(attention_mask)
            num_tokens.append(sum(attention_mask))

        return torch.cat(embeds_out), torch.tensor(attention_masks, device=device, dtype=torch.long), num_tokens, embeds_info

    def process_tokens(self, batch_tokens, batch_multipliers):
        embeds, mask, count, info = self.process_embeds(batch_tokens)

        self.emphasis.tokens = batch_tokens
        self.emphasis.multipliers = torch.asarray(batch_multipliers).to(embeds)
        self.emphasis.z = embeds
        self.emphasis.after_transformers()
        embeds = self.emphasis.z

        _, z = self.text_encoder(
            None,
            embeds=embeds,
            attention_mask=mask,
            num_tokens=count,
            embeds_info=info,
            intermediate_output=self.intermediate_output,
            final_layer_norm_intermediate=self.layer_norm_hidden_state,
        )
        return z
