#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import argparse
from pathlib import Path

import numpy as np
import torch
from PIL import Image


def get_device():
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_image(path: str):
    return Image.open(path).convert("RGB")


def check_env():
    print("========== ENV CHECK ==========")
    print("torch:", torch.__version__)
    print("cuda version in torch:", torch.version.cuda)
    print("cuda available:", torch.cuda.is_available())

    if torch.cuda.is_available():
        print("gpu:", torch.cuda.get_device_name(0))
        print("arch list:", torch.cuda.get_arch_list())

        x = torch.randn(512, 512, device="cuda")
        y = x @ x
        torch.cuda.synchronize()
        print("cuda smoke test:", y.shape, y.dtype)

    print("transformers cache:", os.environ.get("HF_HOME"))
    print("================================")


def run_segformer(args):
    from transformers import SegformerImageProcessor, SegformerForSemanticSegmentation
    import torch.nn.functional as F

    device = get_device()
    image = load_image(args.image)

    model_id = args.model
    print(f"[SegFormer] model = {model_id}")
    print(f"[SegFormer] device = {device}")

    processor = SegformerImageProcessor.from_pretrained(model_id)
    model = SegformerForSemanticSegmentation.from_pretrained(model_id).to(device)
    model.eval()

    inputs = processor(images=image, return_tensors="pt").to(device)

    with torch.inference_mode():
        outputs = model(**inputs)

    logits = outputs.logits

    upsampled_logits = F.interpolate(
        logits,
        size=image.size[::-1],
        mode="bilinear",
        align_corners=False,
    )

    pred = upsampled_logits.argmax(dim=1)[0].detach().cpu().numpy().astype(np.uint8)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mask_path = output_dir / "segformer_ade_mask.png"
    Image.fromarray(pred).save(mask_path)

    # 顯示面積最大的 ADE 類別
    unique_ids, counts = np.unique(pred, return_counts=True)
    pairs = sorted(zip(unique_ids.tolist(), counts.tolist()), key=lambda x: x[1], reverse=True)

    print("[SegFormer] top classes:")
    for class_id, count in pairs[:20]:
        label = model.config.id2label.get(int(class_id), str(class_id))
        print(f"  id={class_id:3d}  pixels={count:8d}  label={label}")

    print(f"[SegFormer] saved mask: {mask_path}")


def run_dinov2(args):
    from transformers import AutoImageProcessor, AutoModel

    device = get_device()
    image = load_image(args.image)

    model_id = args.model
    print(f"[DINOv2] model = {model_id}")
    print(f"[DINOv2] device = {device}")

    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id).to(device)
    model.eval()

    inputs = processor(images=image, return_tensors="pt").to(device)

    with torch.inference_mode():
        outputs = model(**inputs)

    # ViT CLS token embedding
    cls_embedding = outputs.last_hidden_state[:, 0, :].detach().cpu().numpy()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    npy_path = output_dir / "dinov2_cls_embedding.npy"
    np.save(npy_path, cls_embedding)

    print("[DINOv2] last_hidden_state:", tuple(outputs.last_hidden_state.shape))
    print("[DINOv2] cls_embedding:", cls_embedding.shape)
    print(f"[DINOv2] saved embedding: {npy_path}")


def move_inputs_to_device(inputs, device, dtype=None):
    moved = {}
    for k, v in inputs.items():
        if hasattr(v, "to"):
            if dtype is not None and torch.is_floating_point(v):
                moved[k] = v.to(device=device, dtype=dtype)
            else:
                moved[k] = v.to(device=device)
        else:
            moved[k] = v
    return moved


def run_paligemma(args):
    from transformers import AutoProcessor, PaliGemmaForConditionalGeneration

    if not torch.cuda.is_available():
        print("[PaliGemma2] WARNING: CUDA not available. CPU will be very slow.")

    device = get_device()
    image = load_image(args.image)

    model_id = args.model
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

    print(f"[PaliGemma2] model = {model_id}")
    print(f"[PaliGemma2] device = {device}")
    print(f"[PaliGemma2] dtype = {dtype}")
    print(f"[PaliGemma2] prompt = {args.prompt}")

    processor = AutoProcessor.from_pretrained(model_id)

    model = PaliGemmaForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=dtype,
        device_map="auto" if torch.cuda.is_available() else None,
    ).eval()

    inputs = processor(
        text=args.prompt,
        images=image,
        return_tensors="pt",
    )

    model_device = next(model.parameters()).device
    inputs = move_inputs_to_device(inputs, model_device, dtype=dtype)

    input_len = inputs["input_ids"].shape[-1]

    with torch.inference_mode():
        generation = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
        )

    generation = generation[0][input_len:]
    decoded = processor.decode(generation, skip_special_tokens=True)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    txt_path = output_dir / "paligemma2_output.txt"
    txt_path.write_text(decoded, encoding="utf-8")

    print("========== PaliGemma2 Output ==========")
    print(decoded)
    print("=======================================")
    print(f"[PaliGemma2] saved text: {txt_path}")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--task",
        type=str,
        required=True,
        choices=["check", "segformer", "dinov2", "paligemma"],
    )

    parser.add_argument(
        "--image",
        type=str,
        default="/workspace/data/test.jpg",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="/workspace/output",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
    )

    parser.add_argument(
        "--prompt",
        type=str,
        default="caption en",
    )

    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=160,
    )

    args = parser.parse_args()

    if args.task == "check":
        check_env()
        return

    if not Path(args.image).exists():
        raise FileNotFoundError(f"Image not found: {args.image}")

    if args.task == "segformer":
        if args.model is None:
            args.model = "nvidia/segformer-b4-finetuned-ade-512-512"
        run_segformer(args)

    elif args.task == "dinov2":
        if args.model is None:
            args.model = "facebook/dinov2-base"
        run_dinov2(args)

    elif args.task == "paligemma":
        if args.model is None:
            args.model = "google/paligemma2-3b-ft-docci-448"
        run_paligemma(args)


if __name__ == "__main__":
    main()
