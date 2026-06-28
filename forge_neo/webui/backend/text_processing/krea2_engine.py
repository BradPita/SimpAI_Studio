# https://github.com/Comfy-Org/ComfyUI/blob/v0.16.2/comfy/text_encoders/krea2.py

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

        self.id_pad = 151643
        self.id_template = 151644
        self.llama_template = "<|im_start|>system\nDescribe the image by detailing the color, shape, size, texture, quantity, text, spatial relationships of the objects and background:<|im_end|>\n<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n"
        self.intermediate_output = KREA2_TAP_LAYERS
        self.layer_norm_hidden_state = False

    def tokenize(self, texts):
        llama_texts = [self.llama_template.format(text) for text in texts]
        return self.tokenizer(llama_texts)["input_ids"]

    def tokenize_line(self, line: str):
        parsed = parsing.parse_prompt_attention(line, self.emphasis.name)
        tokenized = self.tokenize([text for text, _ in parsed])

        chunks = []
        chunk = PromptChunk()

        def next_chunk():
            nonlocal chunk
            chunks.append(chunk)
            chunk = PromptChunk()

        for tokens, (text, weight) in zip(tokenized, parsed):
            position = 0
            while position < len(tokens):
                token = tokens[position]
                chunk.tokens.append(token)
                chunk.multipliers.append(weight)
                position += 1

        if chunk.tokens or not chunks:
            next_chunk()

        return chunks

    def __call__(self, texts: "SdConditioning"):
        self.emphasis = emphasis.get_current_option(opts.emphasis)()
        if any(emphasis.uses_emphasis(x) for x in texts):
            dynamic_args.last_extra_generation_params["Emphasis"] = self.emphasis.name

        zs = []
        cache = {}

        for line in texts:
            if line in cache:
                line_z_values = cache[line]
            else:
                chunks = self.tokenize_line(line)
                line_z_values = []

                for chunk in chunks:
                    tokens = chunk.tokens
                    multipliers = chunk.multipliers

                    z = self.process_tokens([tokens], [multipliers])
                    z = self.strip_template(z, tokens)
                    z = self.flatten_tap_layers(z)[0]
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

        return out[:, :, template_end:]

    def flatten_tap_layers(self, out):
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
            eos = False

            for item in tokens:
                token = int(item)
                attention_mask.append(0 if eos else 1)
                tokens_temp.append(token)
                if not eos and token == self.id_pad:
                    eos = True

            tokens_embed = torch.tensor([tokens_temp], device=device, dtype=torch.long)
            tokens_embed = self.text_encoder.get_input_embeddings()(tokens_embed)

            embeds_out.append(tokens_embed)
            attention_masks.append(attention_mask)
            num_tokens.append(sum(attention_mask))

        return torch.cat(embeds_out), torch.tensor(attention_masks, device=device, dtype=torch.long), num_tokens

    def process_tokens(self, batch_tokens, batch_multipliers):
        embeds, mask, count = self.process_embeds(batch_tokens)

        self.emphasis.tokens = batch_tokens
        self.emphasis.multipliers = torch.asarray(batch_multipliers).to(embeds)
        self.emphasis.z = embeds
        self.emphasis.after_transformers()
        embeds = self.emphasis.z

        _, z = self.text_encoder(
            None,
            attention_mask=mask,
            embeds=embeds,
            num_tokens=count,
            intermediate_output=self.intermediate_output,
            final_layer_norm_intermediate=self.layer_norm_hidden_state,
        )
        return z
