"""
detection/sunglasses.py
=======================
Lightweight, real-time **sunglasses / dark-glasses detection** that reuses
the eye landmarks already produced by MediaPipe FaceMesh — no extra model
download, Apple-Silicon friendly.

Idea
----
A dark lens covering the eye region has two tell-tale signatures compared
with a bare eye (open OR closed):

1. **It is darker** than the surrounding skin (forehead / cheek). We compare
   the mean brightness of the eye region to a skin reference patch, so the
   test is robust to overall lighting (a bright room vs. a dim cabin).

2. **It is smoother / low-texture.** A real eye — even closed — has an
   eyelid crease, lashes, sclera or iris that create local intensity
   variation. A lens is a fairly uniform dark surface, so the standard
   deviation of the eye region is *low*.

Crucially, a **closed eye** is NOT dark relative to skin (it's skin-toned)
and still has lash/crease texture, so it does not satisfy (1). That's what
keeps us from mis-classifying closed eyes / drowsiness as sunglasses.

We combine the two cues into a 0-1 confidence and debounce over several
frames. Everything is tunable from `config.py`
(`SUNGLASSES_DARK_RATIO`, `SUNGLASSES_STD_MAX`, `SUNGLASSES_CONFIDENCE`,
`SUNGLASSES_MIN_FRAMES`).
"""

import numpy as np


class SunglassesDetector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self._hits = 0
        self._active = False
        self._last_conf = 0.0

    # ------------------------------------------------------------------ #
    def _region_bounds(self, pts, w, h, pad):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1 = max(0, int(min(xs)) - pad)
        x2 = min(w, int(max(xs)) + pad)
        y1 = max(0, int(min(ys)) - pad)
        y2 = min(h, int(max(ys)) + pad)
        return x1, y1, x2, y2

    def _skin_reference(self, gray, metrics, w, h):
        """
        Sample a skin patch (mid-forehead / nose bridge area) as a
        brightness reference. We use the region between/above the eyes,
        which is skin for both bare-eyed and sunglasses-wearing drivers'
        upper face is above the lenses' top rim most of the time; to be
        safe we sample the forehead above the eyes.
        """
        left = metrics["left_eye_pts"]
        right = metrics["right_eye_pts"]
        # midpoint between the two inner eye corners
        cx = int((left[0][0] + right[3][0]) / 2)
        # top of eyes
        eye_top = int(min(p[1] for p in left + right))
        eye_h = max(6, int(abs(max(p[1] for p in left) - min(p[1] for p in left))))
        # forehead patch sits above the eyes by ~1.5 eye-heights
        fy2 = max(0, eye_top - eye_h)
        fy1 = max(0, fy2 - eye_h * 2)
        fx1 = max(0, cx - eye_h * 2)
        fx2 = min(w, cx + eye_h * 2)
        if fy2 <= fy1 or fx2 <= fx1:
            # fallback: whole-face mean
            return float(np.mean(gray)) + 1e-6
        patch = gray[fy1:fy2, fx1:fx2]
        if patch.size == 0:
            return float(np.mean(gray)) + 1e-6
        return float(np.mean(patch)) + 1e-6

    # ------------------------------------------------------------------ #
    def analyze(self, frame_bgr, metrics):
        """
        Returns dict:
            detected (bool), confidence (0-1), dark_ratio, eye_std
        `metrics` is the LandmarkDetector.analyze() output (found=True).
        """
        import cv2
        if not metrics.get("found"):
            # can't judge without eyes; decay debounce
            self._hits = max(0, self._hits - 1)
            if self._hits == 0:
                self._active = False
            return {"detected": self._active, "confidence": 0.0,
                    "dark_ratio": None, "eye_std": None}

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]

        eye_vals = []
        stds = []
        for pts in (metrics["left_eye_pts"], metrics["right_eye_pts"]):
            x1, y1, x2, y2 = self._region_bounds(pts, w, h, pad=4)
            if x2 <= x1 or y2 <= y1:
                continue
            region = gray[y1:y2, x1:x2]
            if region.size == 0:
                continue
            eye_vals.append(float(np.mean(region)))
            stds.append(float(np.std(region)))

        if not eye_vals:
            return {"detected": self._active, "confidence": 0.0,
                    "dark_ratio": None, "eye_std": None}

        eye_mean = float(np.mean(eye_vals))
        eye_std = float(np.mean(stds))
        skin_mean = self._skin_reference(gray, metrics, w, h)
        dark_ratio = eye_mean / skin_mean          # <1 => eyes darker than skin

        # --- cue 1: darkness relative to skin -> 0..1
        # at dark_ratio <= DARK_RATIO*0.7 fully dark; at >= DARK_RATIO not dark
        dr_lo = self.cfg.SUNGLASSES_DARK_RATIO * 0.7
        dr_hi = self.cfg.SUNGLASSES_DARK_RATIO
        dark_score = _inv_lerp(dark_ratio, dr_hi, dr_lo)   # note: reversed

        # --- cue 2: smoothness (low std) -> 0..1
        std_hi = self.cfg.SUNGLASSES_STD_MAX
        std_lo = self.cfg.SUNGLASSES_STD_MAX * 0.4
        smooth_score = _inv_lerp(eye_std, std_hi, std_lo)  # reversed

        # combine: needs BOTH dark AND smooth (min emphasizes agreement,
        # averaged with mean to avoid being too strict)
        confidence = 0.5 * min(dark_score, smooth_score) + 0.5 * (
            (dark_score + smooth_score) / 2.0)
        confidence = float(max(0.0, min(1.0, confidence)))
        self._last_conf = confidence

        qualifies = confidence >= self.cfg.SUNGLASSES_CONFIDENCE
        if qualifies:
            self._hits = min(self.cfg.SUNGLASSES_MIN_FRAMES + 3, self._hits + 1)
        else:
            self._hits = max(0, self._hits - 1)

        if self._hits >= self.cfg.SUNGLASSES_MIN_FRAMES:
            self._active = True
        elif self._hits == 0:
            self._active = False

        return {
            "detected": self._active,
            "confidence": round(confidence, 3),
            "dark_ratio": round(dark_ratio, 3),
            "eye_std": round(eye_std, 2),
        }


def _inv_lerp(x, hi, lo):
    """
    Map x to 0..1 where x>=hi -> 0 and x<=lo -> 1 (linear between).
    Used so that "smaller is stronger" cues (darkness ratio, std) become a
    0..1 score.
    """
    if hi == lo:
        return 1.0 if x <= lo else 0.0
    if x <= lo:
        return 1.0
    if x >= hi:
        return 0.0
    return (hi - x) / (hi - lo)
