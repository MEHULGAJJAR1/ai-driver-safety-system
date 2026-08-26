"""
analyzer.py
===========
Offline analysis of an uploaded image or video file. Runs every frame
(video) or the single image through the DrowsinessPipeline and returns a
summary the dashboard can render, plus a base64 preview of the most
"drowsy" annotated frame.
"""

import os
import base64

from detection import DrowsinessPipeline


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def _b64_jpeg(frame_bgr, quality=80):
    import cv2
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def analyze_file(path, config, max_frames=3000, sample_every=1):
    """
    Analyze an uploaded image/video.

    Returns a dict summary:
        kind, frames_analyzed, faces_found, avg_ear, min_ear, avg_mar,
        max_score, drowsy_events, yawn_count, nod_count, blink_count,
        drowsy_ratio, timeline (per-sample score), preview (base64 jpeg)
    """
    import cv2

    ext = os.path.splitext(path)[1].lower()
    pipeline = DrowsinessPipeline(config)
    pipeline.reset()

    ears, mars, scores, timeline = [], [], [], []
    faces_found = 0
    frames_analyzed = 0
    worst_score = -1.0
    worst_preview = None

    def _consume(frame, t=None):
        nonlocal faces_found, frames_analyzed, worst_score, worst_preview
        annotated, state = pipeline.process_frame(frame, draw=True)
        frames_analyzed += 1
        if state.get("found"):
            faces_found += 1
            ears.append(state["ear"])
            mars.append(state["mar"])
        scores.append(state["score"])
        timeline.append({"t": t if t is not None else frames_analyzed,
                         "score": state["score"], "ear": state["ear"],
                         "mar": state["mar"]})
        if state["score"] > worst_score:
            worst_score = state["score"]
            worst_preview = annotated

    try:
        if ext in IMAGE_EXTS:
            frame = cv2.imread(path)
            if frame is None:
                raise ValueError("Could not read image file.")
            _consume(frame)
            kind = "image"
        else:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise ValueError("Could not open video file.")
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            idx = 0
            while frames_analyzed < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                if idx % sample_every == 0:
                    _consume(frame, t=round(idx / fps, 2))
                idx += 1
            cap.release()
            kind = "video"
    finally:
        pipeline.close()

    scorer = pipeline.scorer
    n = max(frames_analyzed, 1)
    drowsy_ratio = sum(1 for s in scores if s >= config.SCORE_ALARM) / n

    return {
        "kind": kind,
        "frames_analyzed": frames_analyzed,
        "faces_found": faces_found,
        "avg_ear": round(sum(ears) / len(ears), 3) if ears else None,
        "min_ear": round(min(ears), 3) if ears else None,
        "avg_mar": round(sum(mars) / len(mars), 3) if mars else None,
        "max_score": round(max(scores), 1) if scores else 0.0,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "drowsy_events": scorer.drowsy_events,
        "yawn_count": scorer.yawn_count,
        "nod_count": scorer.nod_count,
        "blink_count": scorer.blink_count,
        "drowsy_ratio": round(drowsy_ratio, 3),
        "verdict": _verdict(worst_score, drowsy_ratio, scorer),
        "timeline": timeline[:2000],
        "preview": _b64_jpeg(worst_preview) if worst_preview is not None else None,
    }


def _verdict(max_score, drowsy_ratio, scorer):
    if max_score >= 70 or drowsy_ratio > 0.15 or scorer.drowsy_events > 0:
        return "Drowsiness detected"
    if max_score >= 40 or scorer.yawn_count > 0 or scorer.nod_count > 0:
        return "Mild fatigue signs"
    return "No significant drowsiness"
