import logging

import torch


logger = logging.getLogger(__name__)

try:
    import triton
    import triton.language as tl

    TRITON_AVAILABLE = True
    _TRITON_IMPORT_ERROR = None
except Exception as triton_error:
    triton = None
    tl = None
    TRITON_AVAILABLE = False
    _TRITON_IMPORT_ERROR = triton_error
    logger.warning(
        "[Easy-Sam3] Triton unavailable for EDT; falling back to slow distance transform. error=%s",
        triton_error,
    )


def _edt_slow(data: torch.Tensor) -> torch.Tensor:
    try:
        import cv2
    except Exception as cv2_error:
        raise RuntimeError(
            "Easy-Sam3 distance transform fallback requires OpenCV when Triton is unavailable."
        ) from cv2_error

    if data.dim() != 3:
        raise ValueError(f"Expected a 3D tensor for EDT, got shape {tuple(data.shape)}")

    original_device = data.device
    data_cpu = data.detach().to("cpu")
    output_cpu = torch.empty(data_cpu.shape, dtype=torch.float32)

    for idx in range(data_cpu.shape[0]):
        mask = data_cpu[idx].to(dtype=torch.bool).numpy().astype("uint8", copy=False)
        output_cpu[idx] = torch.from_numpy(cv2.distanceTransform(mask, cv2.DIST_L2, 0)).to(torch.float32)

    return output_cpu.to(device=original_device)


if TRITON_AVAILABLE:
    @triton.jit
    def edt_kernel(inputs_ptr, outputs_ptr, v, z, height, width, horizontal: tl.constexpr):
        batch_id = tl.program_id(axis=0)
        if horizontal:
            row_id = tl.program_id(axis=1)
            block_start = (batch_id * height * width) + row_id * width
            length = width
            stride = 1
        else:
            col_id = tl.program_id(axis=1)
            block_start = (batch_id * height * width) + col_id
            length = height
            stride = width

        k = 0
        for q in range(1, length):
            cur_input = tl.load(inputs_ptr + block_start + (q * stride))
            r = tl.load(v + block_start + (k * stride))
            z_k = tl.load(z + block_start + (k * stride))
            previous_input = tl.load(inputs_ptr + block_start + (r * stride))
            s = (cur_input - previous_input + q * q - r * r) / (q - r) / 2

            while s <= z_k and k - 1 >= 0:
                k = k - 1
                r = tl.load(v + block_start + (k * stride))
                z_k = tl.load(z + block_start + (k * stride))
                previous_input = tl.load(inputs_ptr + block_start + (r * stride))
                s = (cur_input - previous_input + q * q - r * r) / (q - r) / 2

            k = k + 1
            tl.store(v + block_start + (k * stride), q)
            tl.store(z + block_start + (k * stride), s)
            if k + 1 < length:
                tl.store(z + block_start + ((k + 1) * stride), 1e9)

        k = 0
        for q in range(length):
            while (
                k + 1 < length
                and tl.load(
                    z + block_start + ((k + 1) * stride), mask=(k + 1) < length, other=q
                )
                < q
            ):
                k += 1
            r = tl.load(v + block_start + (k * stride))
            d = q - r
            old_value = tl.load(inputs_ptr + block_start + (r * stride))
            tl.store(outputs_ptr + block_start + (q * stride), old_value + d * d)


    def edt_triton(data: torch.Tensor):
        if data.dim() != 3:
            raise ValueError(f"Expected a 3D tensor for EDT, got shape {tuple(data.shape)}")

        if not data.is_cuda:
            return _edt_slow(data)

        B, H, W = data.shape
        data = data.contiguous()

        output = torch.where(data, 1e18, 0.0)
        assert output.is_contiguous()

        parabola_loc = torch.zeros(B, H, W, dtype=torch.uint32, device=data.device)
        parabola_inter = torch.empty(B, H, W, dtype=torch.float, device=data.device)
        parabola_inter[:, :, 0] = -1e18
        parabola_inter[:, :, 1] = 1e18

        grid = (B, H)
        edt_kernel[grid](
            output.clone(),
            output,
            parabola_loc,
            parabola_inter,
            H,
            W,
            horizontal=True,
        )

        parabola_loc.zero_()
        parabola_inter[:, :, 0] = -1e18
        parabola_inter[:, :, 1] = 1e18

        grid = (B, W)
        edt_kernel[grid](
            output.clone(),
            output,
            parabola_loc,
            parabola_inter,
            H,
            W,
            horizontal=False,
        )
        return output.sqrt()
else:
    def edt_triton(data: torch.Tensor):
        return _edt_slow(data)
