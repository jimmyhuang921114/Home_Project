#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import cv2
import time
import argparse
import torch
from pathlib import Path
from PIL import Image
from transformers import AutoProcessor
from transformers import AutoModelForZeroShotObjectDetection


DEFAULT_VIDEO = "/workspace/visual/src/test_video/YTDown_YouTube_Redrow-s-The-Mere-Home-Tour-POV-Full-Wal_Media_mwUJnTCrGxU_002_720p.mp4"

DEFAULT_PROMPT = (
    "person . chair . table . sofa . couch . bed . pillow . blanket . "
    "door . window . wall . floor . ceiling . "
    "television . tv . monitor . laptop . keyboard . mouse . "
    "cup . bottle . plate . bowl . spoon . fork . "
    "book . shelf . cabinet . drawer . lamp . light . plant . "
    "bag . backpack . box . trash can . phone . remote control . "
    "speaker . picture frame . clock . mirror . shoe . slipper . "
    "clothes . towel . refrigerator . microwave . oven . sink . faucet . "
    "toilet . bathtub . shower . object . furniture . appliance ."
)


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--video", type=str, default=DEFAULT_VIDEO)
    parser.add_argument("--output", type=str, default="/workspace/output/grounding_home_objects.mp4")
    parser.add_argument("--coord-output", type=str, default="/workspace/output/grounding_home_objects_coords.txt")

    parser.add_argument("--model", type=str, default="IDEA-Research/grounding-dino-tiny")
    parser.add_argument("--prompt", type=str, default=DEFAULT_PROMPT)

    parser.add_argument("--threshold", type=float, default=0.20)
    parser.add_argument("--infer-every", type=int, default=1)

    parser.add_argument("--show", action="store_true")
    parser.add_argument("--save", action="store_true")

    parser.add_argument("--max-frames", type=int, default=0)

    return parser.parse_args()


def post_process(processor, outputs, input_ids, image_h, image_w, threshold):
    """
    相容不同 transformers 版本：
    1. 舊版：threshold
    2. 新版：box_threshold + text_threshold
    """
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


def draw_detections(frame, boxes, scores, labels, fps, infer_fps, frame_idx):
    h, w = frame.shape[:2]

    for box, score, label in zip(boxes, scores, labels):
        x1, y1, x2, y2 = map(int, box)

        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(0, min(w - 1, x2))
        y2 = max(0, min(h - 1, y2))

        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)

        text = f"{label} {score:.2f} ({cx},{cy})"

        cv2.putText(
            frame,
            text,
            (x1, max(25, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    info = f"GroundingDINO | frame={frame_idx} | FPS={fps:.2f} | infer FPS={infer_fps:.2f}"

    cv2.putText(
        frame,
        info,
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    return frame


def main():
    args = get_args()

    Path(os.path.dirname(args.output)).mkdir(parents=True, exist_ok=True)
    Path(os.path.dirname(args.coord_output)).mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print("[INFO] device:", device)
    print("[INFO] model :", args.model)
    print("[INFO] video :", args.video)
    print("[INFO] output:", args.output)
    print("[INFO] coord :", args.coord_output)

    torch.backends.cudnn.benchmark = True

    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(args.model).to(device)
    model.eval()

    cap = cv2.VideoCapture(args.video)

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")

    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if src_fps <= 0:
        src_fps = 30.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    writer = None
    if args.save:
        writer = cv2.VideoWriter(
            args.output,
            cv2.VideoWriter_fourcc(*"mp4v"),
            src_fps,
            (width, height),
        )

    coord_file = open(args.coord_output, "w", encoding="utf-8")
    coord_file.write("frame,label,score,x1,y1,x2,y2,cx,cy\n")

    frame_idx = 0
    last_boxes = []
    last_scores = []
    last_labels = []

    last_time = time.perf_counter()
    fps = 0.0

    infer_count = 0
    infer_time_sum = 0.0
    infer_fps = 0.0

    while True:
        ret, frame = cap.read()

        if not ret:
            break

        if args.max_frames > 0 and frame_idx >= args.max_frames:
            break

        now = time.perf_counter()
        dt = now - last_time
        last_time = now

        if dt > 0:
            instant_fps = 1.0 / dt
            fps = instant_fps if fps == 0 else fps * 0.9 + instant_fps * 0.1

        should_infer = frame_idx % max(1, args.infer_every) == 0

        if should_infer:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)

            inputs = processor(
                images=image,
                text=args.prompt,
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

            infer_time = t1 - t0
            infer_count += 1
            infer_time_sum += infer_time
            infer_fps = infer_count / infer_time_sum if infer_time_sum > 0 else 0.0

            results = post_process(
                processor=processor,
                outputs=outputs,
                input_ids=inputs.input_ids,
                image_h=height,
                image_w=width,
                threshold=args.threshold,
            )

            result = results[0]

            last_boxes = result["boxes"].detach().cpu().numpy()
            last_scores = result["scores"].detach().cpu().numpy()
            last_labels = result["labels"]

            print(f"[FRAME {frame_idx}] objects={len(last_boxes)} infer={infer_time*1000:.1f} ms")

        for box, score, label in zip(last_boxes, last_scores, last_labels):
            x1, y1, x2, y2 = map(int, box)

            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)

            coord_file.write(
                f"{frame_idx},{label},{float(score):.4f},"
                f"{x1},{y1},{x2},{y2},{cx},{cy}\n"
            )

        vis = frame.copy()

        vis = draw_detections(
            frame=vis,
            boxes=last_boxes,
            scores=last_scores,
            labels=last_labels,
            fps=fps,
            infer_fps=infer_fps,
            frame_idx=frame_idx,
        )

        if writer is not None:
            writer.write(vis)

        if args.show:
            cv2.imshow("GroundingDINO Home Objects", vis)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q") or key == 27:
                break

        frame_idx += 1

    coord_file.close()
    cap.release()

    if writer is not None:
        writer.release()

    if args.show:
        cv2.destroyAllWindows()

    print("\n========== DONE ==========")
    print("frames:", frame_idx)
    print("video :", args.output if args.save else "not saved, use --save")
    print("coord :", args.coord_output)


if __name__ == "__main__":
    main()