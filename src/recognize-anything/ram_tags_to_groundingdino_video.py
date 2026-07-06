#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import importlib
import inspect
import os
import re
import time
from pathlib import Path

import cv2
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection


def get_project_root() -> Path:
    env = os.environ.get("HOME_PROJECT_ROOT")
    if env:
        return Path(env).expanduser().resolve()

    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").exists():
            return parent
    return p.parents[2]


PROJECT_ROOT = get_project_root()
DEFAULT_VIDEO = str(
    PROJECT_ROOT
    / "data"
    / "test_video"
    / "YTDown_YouTube_Redrow-s-The-Mere-Home-Tour-POV-Full-Wal_Media_mwUJnTCrGxU_002_720p.mp4"
)

DEFAULT_OUTPUT = str(PROJECT_ROOT / "output" / "ram_groundingdino_home_objects.mp4")
DEFAULT_COORD_OUTPUT = str(PROJECT_ROOT / "output" / "ram_groundingdino_home_objects_coords.csv")
DEFAULT_PROMPT_LOG = str(PROJECT_ROOT / "output" / "ram_groundingdino_prompts.csv")


# 太抽象、顏色、場景形容詞，通常不適合直接餵給 GroundingDINO
STOP_TAGS = {
    "indoor", "outdoor", "inside", "outside",
    "room", "living room", "bedroom", "kitchen", "bathroom",
    "home", "house", "interior", "interior design",
    "design", "modern", "style", "decoration", "decor",
    "photo", "image", "picture", "scene",
    "object", "things", "stuff",
    "white", "black", "gray", "grey", "red", "blue", "green",
    "yellow", "brown", "orange", "pink", "purple",
    "large", "small", "big", "old", "new",
    "wood", "wooden", "metal", "plastic", "glass",
    "bright", "dark", "light",
    "furniture", "appliance",
}


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--video", type=str, default=DEFAULT_VIDEO)
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT)
    parser.add_argument("--coord-output", type=str, default=DEFAULT_COORD_OUTPUT)
    parser.add_argument("--prompt-log", type=str, default=DEFAULT_PROMPT_LOG)

    # RAM / RAM++ 設定
    parser.add_argument("--ram-mode", type=str, default="ram", choices=["ram", "ram_plus"])
    parser.add_argument("--ram-pretrained", type=str, default="pretrained/ram_swin_large_14m.pth")
    parser.add_argument("--ram-image-size", type=int, default=384)
    parser.add_argument("--ram-vit", type=str, default="swin_l")
    parser.add_argument("--ram-every", type=int, default=30)

    # GroundingDINO 設定
    parser.add_argument("--dino-model", type=str, default="IDEA-Research/grounding-dino-tiny")
    parser.add_argument("--dino-every", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.25)

    # tag → prompt 設定
    parser.add_argument("--max-tags", type=int, default=20)
    parser.add_argument(
        "--extra-tags",
        type=str,
        default="chair, table, sofa, couch, bed, door, window, cabinet, shelf, lamp, plant",
        help="固定額外加入 GroundingDINO 的 tags，用逗號分隔",
    )
    parser.add_argument("--no-filter", action="store_true")

    parser.add_argument("--save", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)

    return parser.parse_args()


def import_ram_builder(ram_mode: str):
    try:
        if ram_mode == "ram_plus":
            from ram.models import ram_plus
            return ram_plus
        else:
            from ram.models import ram
            return ram
    except Exception as e:
        raise RuntimeError(
            "找不到 RAM/RAM++ 模組。請確認你是在 recognize-anything 專案根目錄執行，"
            f"例如：cd {PROJECT_ROOT / 'src' / 'recognize-anything'}"
        ) from e


def import_ram_transform():
    try:
        from ram import get_transform
        return get_transform
    except Exception as e:
        raise RuntimeError("找不到 ram.get_transform，請確認 recognize-anything 安裝完整。") from e


def import_ram_inference(ram_mode: str):
    if ram_mode == "ram_plus":
        candidates = [
            ("ram.inference", "inference_ram_openset"),
            ("ram", "inference_ram_openset"),
            ("ram.inference", "inference_ram"),
            ("ram", "inference_ram"),
        ]
    else:
        candidates = [
            ("ram.inference", "inference_ram"),
            ("ram", "inference_ram"),
            ("ram.inference", "inference_ram_openset"),
            ("ram", "inference_ram_openset"),
        ]

    for module_name, func_name in candidates:
        try:
            module = importlib.import_module(module_name)
            func = getattr(module, func_name)
            print(f"[INFO] RAM inference function = {module_name}.{func_name}")
            return func
        except Exception:
            pass

    raise RuntimeError(
        "找不到 RAM inference function。請檢查 recognize-anything 版本，"
        "常見函式名稱是 inference_ram 或 inference_ram_openset。"
    )


def build_ram_model(args, device):
    builder = import_ram_builder(args.ram_mode)

    if not os.path.exists(args.ram_pretrained):
        raise FileNotFoundError(
            f"RAM 權重不存在：{args.ram_pretrained}\n"
            f"請先確認：ls -lh {args.ram_pretrained}"
        )

    sig = inspect.signature(builder)
    has_var_kwargs = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )

    kwargs = {}

    if "pretrained" in sig.parameters or has_var_kwargs:
        kwargs["pretrained"] = args.ram_pretrained

    if "image_size" in sig.parameters or has_var_kwargs:
        kwargs["image_size"] = args.ram_image_size

    if "vit" in sig.parameters or has_var_kwargs:
        kwargs["vit"] = args.ram_vit

    print(f"[INFO] loading {args.ram_mode} model...")
    print(f"[INFO] RAM pretrained = {args.ram_pretrained}")
    print(f"[INFO] RAM kwargs     = {kwargs}")

    model = builder(**kwargs)
    model.eval().to(device)

    return model


def build_ram_transform(image_size: int):
    get_transform = import_ram_transform()

    try:
        return get_transform(image_size=image_size)
    except TypeError:
        return get_transform(image_size)


def parse_tags_from_ram_result(result):
    """
    RAM 常見輸出：
    result[0] = English tags，可能是 "tag1 | tag2 | tag3"
    result[1] = Chinese tags
    """
    if isinstance(result, (list, tuple)):
        raw = result[0]
    else:
        raw = result

    if isinstance(raw, (list, tuple)):
        tags = [str(x).strip() for x in raw]
    else:
        raw = str(raw)
        tags = re.split(r"\s*\|\s*|,\s*|;\s*|\n+", raw)

    clean_tags = []

    for tag in tags:
        tag = tag.strip().lower()
        tag = re.sub(r"<.*?>", "", tag)
        tag = re.sub(r"[^a-z0-9 _\-]", "", tag)
        tag = re.sub(r"\s+", " ", tag).strip()

        if not tag:
            continue

        clean_tags.append(tag)

    return clean_tags


def split_extra_tags(extra_tags: str):
    if not extra_tags:
        return []

    tags = re.split(r",|;|\|", extra_tags)
    return [t.strip().lower() for t in tags if t.strip()]


def filter_tags(tags, max_tags=20, no_filter=False):
    output = []
    seen = set()

    for tag in tags:
        tag = tag.strip().lower()

        if not tag:
            continue

        if len(tag) <= 1:
            continue

        if not no_filter and tag in STOP_TAGS:
            continue

        if tag in seen:
            continue

        seen.add(tag)
        output.append(tag)

        if len(output) >= max_tags:
            break

    return output


def tags_to_grounding_prompt(tags):
    """
    GroundingDINO 建議格式：
    chair . table . sofa .
    """
    if not tags:
        return ""

    return " . ".join(tags) + " ."


def run_ram_tagging(frame_bgr, ram_model, ram_transform, ram_infer_func, device):
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(frame_rgb)

    image_tensor = ram_transform(pil_image).unsqueeze(0).to(device)

    with torch.inference_mode():
        result = ram_infer_func(image_tensor, ram_model)

    tags = parse_tags_from_ram_result(result)
    return tags, result


def post_process_grounding(processor, outputs, input_ids, image_h, image_w, threshold):
    target_sizes = [(image_h, image_w)]

    try:
        return processor.post_process_grounded_object_detection(
            outputs,
            input_ids,
            threshold=threshold,
            target_sizes=target_sizes,
        )
    except TypeError:
        return processor.post_process_grounded_object_detection(
            outputs=outputs,
            input_ids=input_ids,
            box_threshold=threshold,
            text_threshold=threshold,
            target_sizes=target_sizes,
        )


def run_grounding_dino(frame_bgr, prompt, processor, model, device, threshold):
    h, w = frame_bgr.shape[:2]

    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(frame_rgb)

    inputs = processor(
        images=image,
        text=prompt,
        return_tensors="pt",
    ).to(device)

    if device == "cuda":
        torch.cuda.synchronize()

    t0 = time.perf_counter()

    with torch.inference_mode():
        outputs = model(**inputs)

    if device == "cuda":
        torch.cuda.synchronize()

    t1 = time.perf_counter()

    results = post_process_grounding(
        processor=processor,
        outputs=outputs,
        input_ids=inputs.input_ids,
        image_h=h,
        image_w=w,
        threshold=threshold,
    )

    result = results[0]

    boxes = result["boxes"].detach().cpu().numpy()
    scores = result["scores"].detach().cpu().numpy()
    labels = result["labels"]

    return boxes, scores, labels, t1 - t0


def draw_detections(frame, boxes, scores, labels, fps, infer_fps, frame_idx, tags, prompt):
    out = frame.copy()
    h, w = out.shape[:2]

    for box, score, label in zip(boxes, scores, labels):
        x1, y1, x2, y2 = map(int, box)

        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(0, min(w - 1, x2))
        y2 = max(0, min(h - 1, y2))

        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)

        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.circle(out, (cx, cy), 4, (0, 0, 255), -1)

        text = f"{label} {float(score):.2f} ({cx},{cy})"

        cv2.putText(
            out,
            text,
            (x1, max(25, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    info1 = f"RAM tags -> GroundingDINO | frame={frame_idx} | FPS={fps:.2f} | DINO FPS={infer_fps:.2f}"
    info2 = "tags: " + ", ".join(tags[:12])
    info3 = "prompt: " + prompt[:130]

    cv2.putText(out, info1, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(out, info2, (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(out, info3, (20, h - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 2, cv2.LINE_AA)

    return out


def main():
    args = get_args()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.coord_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.prompt_log).parent.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print("[INFO] device      =", device)
    print("[INFO] video       =", args.video)
    print("[INFO] output      =", args.output)
    print("[INFO] coord output=", args.coord_output)
    print("[INFO] prompt log  =", args.prompt_log)

    torch.backends.cudnn.benchmark = True

    # 1. Load RAM / RAM++
    ram_model = build_ram_model(args, device)
    ram_transform = build_ram_transform(args.ram_image_size)
    ram_infer_func = import_ram_inference(args.ram_mode)

    # 2. Load GroundingDINO
    print("[INFO] loading GroundingDINO...")
    dino_processor = AutoProcessor.from_pretrained(args.dino_model)
    dino_model = AutoModelForZeroShotObjectDetection.from_pretrained(args.dino_model).to(device)
    dino_model.eval()

    # 3. Open video
    cap = cv2.VideoCapture(args.video)

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")

    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if src_fps <= 0:
        src_fps = 30.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"[INFO] source fps   = {src_fps:.2f}")
    print(f"[INFO] resolution   = {width} x {height}")
    print(f"[INFO] total frames = {total_frames}")

    writer = None
    if args.save:
        writer = cv2.VideoWriter(
            args.output,
            cv2.VideoWriter_fourcc(*"mp4v"),
            src_fps,
            (width, height),
        )

    coord_file = open(args.coord_output, "w", encoding="utf-8", newline="")
    coord_writer = csv.writer(coord_file)
    coord_writer.writerow(["frame", "label", "score", "x1", "y1", "x2", "y2", "cx", "cy", "prompt"])

    prompt_file = open(args.prompt_log, "w", encoding="utf-8", newline="")
    prompt_writer = csv.writer(prompt_file)
    prompt_writer.writerow(["frame", "ram_tags", "final_tags", "grounding_prompt"])

    frame_idx = 0
    last_time = time.perf_counter()
    fps = 0.0

    last_tags = []
    last_prompt = ""
    last_boxes = []
    last_scores = []
    last_labels = []

    dino_infer_count = 0
    dino_infer_time_sum = 0.0
    dino_infer_fps = 0.0

    extra_tags = split_extra_tags(args.extra_tags)

    while True:
        ok, frame = cap.read()

        if not ok:
            break

        if args.max_frames > 0 and frame_idx >= args.max_frames:
            break

        now = time.perf_counter()
        dt = now - last_time
        last_time = now

        if dt > 0:
            instant_fps = 1.0 / dt
            fps = instant_fps if fps == 0 else fps * 0.9 + instant_fps * 0.1

        # 4. RAM / RAM++ 每 N 幀更新一次 tags
        if frame_idx % max(1, args.ram_every) == 0:
            try:
                ram_tags, raw_ram_result = run_ram_tagging(
                    frame_bgr=frame,
                    ram_model=ram_model,
                    ram_transform=ram_transform,
                    ram_infer_func=ram_infer_func,
                    device=device,
                )

                merged_tags = ram_tags + extra_tags
                final_tags = filter_tags(
                    merged_tags,
                    max_tags=args.max_tags,
                    no_filter=args.no_filter,
                )

                prompt = tags_to_grounding_prompt(final_tags)

                if prompt:
                    last_tags = final_tags
                    last_prompt = prompt

                prompt_writer.writerow([
                    frame_idx,
                    " | ".join(ram_tags),
                    " | ".join(final_tags),
                    last_prompt,
                ])

                print(f"[RAM] frame={frame_idx:06d} tags={final_tags}")
                print(f"[PROMPT] {last_prompt}")

            except Exception as e:
                print(f"[WARN] RAM tagging failed at frame {frame_idx}: {e}")

        # 沒有 prompt 就跳過 GroundingDINO
        if not last_prompt:
            frame_idx += 1
            continue

        # 5. GroundingDINO 每 M 幀跑一次，使用 RAM 產生的 prompt
        if frame_idx % max(1, args.dino_every) == 0:
            try:
                boxes, scores, labels, infer_time = run_grounding_dino(
                    frame_bgr=frame,
                    prompt=last_prompt,
                    processor=dino_processor,
                    model=dino_model,
                    device=device,
                    threshold=args.threshold,
                )

                last_boxes = boxes
                last_scores = scores
                last_labels = labels

                dino_infer_count += 1
                dino_infer_time_sum += infer_time
                dino_infer_fps = dino_infer_count / dino_infer_time_sum if dino_infer_time_sum > 0 else 0.0

                print(
                    f"[DINO] frame={frame_idx:06d} "
                    f"objects={len(last_boxes)} "
                    f"infer={infer_time * 1000:.1f} ms "
                    f"prompt_tags={len(last_tags)}"
                )

            except Exception as e:
                print(f"[WARN] GroundingDINO failed at frame {frame_idx}: {e}")

        # 6. 寫出座標
        for box, score, label in zip(last_boxes, last_scores, last_labels):
            x1, y1, x2, y2 = map(int, box)
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)

            coord_writer.writerow([
                frame_idx,
                label,
                float(score),
                x1,
                y1,
                x2,
                y2,
                cx,
                cy,
                last_prompt,
            ])

        # 7. 畫面疊圖
        vis = draw_detections(
            frame=frame,
            boxes=last_boxes,
            scores=last_scores,
            labels=last_labels,
            fps=fps,
            infer_fps=dino_infer_fps,
            frame_idx=frame_idx,
            tags=last_tags,
            prompt=last_prompt,
        )

        if writer is not None:
            writer.write(vis)

        if args.show:
            cv2.imshow("RAM Tags -> GroundingDINO", vis)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q") or key == 27:
                break

        frame_idx += 1

    cap.release()
    coord_file.close()
    prompt_file.close()

    if writer is not None:
        writer.release()

    if args.show:
        cv2.destroyAllWindows()

    print("\n========== DONE ==========")
    print(f"frames processed : {frame_idx}")
    print(f"output video     : {args.output if args.save else 'not saved, add --save'}")
    print(f"coord csv        : {args.coord_output}")
    print(f"prompt log       : {args.prompt_log}")

    if dino_infer_count > 0:
        print(f"DINO infer FPS   : {dino_infer_fps:.2f}")
        print(f"DINO avg ms      : {(dino_infer_time_sum / dino_infer_count) * 1000.0:.2f}")


if __name__ == "__main__":
    main()
