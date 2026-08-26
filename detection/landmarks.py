"""
detection/landmarks.py
=======================
MediaPipe FaceMesh wrapper that turns a video frame into the geometric
signals we need for drowsiness detection:

    * EAR  - Eye Aspect Ratio        (eye closure / micro-sleep)
    * MAR  - Mouth Aspect Ratio      (yawning)
    * head pose (pitch, yaw, roll)   (nodding off / looking away)

The Eye Aspect Ratio was introduced by Soukupova & Cech (2016),
"Real-Time Eye Blink Detection using Facial Landmarks".

    EAR = (||p2 - p6|| + ||p3 - p5||) / (2 * ||p1 - p4||)

We compute it from MediaPipe's 468-point mesh instead of dlib's 68 points,
so the indices below are MediaPipe indices.
"""

import numpy as np

try:
    import mediapipe as mp
    _MP_AVAILABLE = True
except Exception:                      # pragma: no cover - import guard
    mp = None
    _MP_AVAILABLE = False


# --------------------------------------------------------------------------- #
#  MediaPipe FaceMesh landmark indices
# --------------------------------------------------------------------------- #
# Six points per eye, ordered to match the EAR formula (p1..p6):
#   p1, p4 = horizontal corners ; p2,p3,p5,p6 = vertical lids
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

# Mouth: horizontal corners + vertical lips for MAR (order matters).
#   [left_corner, right_corner, outer_top, outer_bottom, (extra, extra),
#    inner_top, inner_bottom]
#   61/291 = mouth corners, 0/17 = outer upper/lower lip,
#   13/14 = inner upper/lower lip. MAR uses (0-17) and (13-14) vertically.
MOUTH = [61, 291, 0, 17, 39, 181, 13, 14]

# Iris centers (available when refine_landmarks=True) - handy for gaze.
LEFT_IRIS = 468
RIGHT_IRIS = 473

# Points used for solvePnP head-pose estimation and a canonical 3D face model.
# (nose tip, chin, left/right eye outer corners, left/right mouth corners)
POSE_LANDMARKS = [1, 199, 33, 263, 61, 291]
_FACE_3D_MODEL = np.array(
    [
        [0.0, 0.0, 0.0],          # nose tip
        [0.0, -63.6, -12.5],      # chin
        [-43.3, 32.7, -26.0],     # left eye outer corner
        [43.3, 32.7, -26.0],      # right eye outer corner
        [-28.9, -28.9, -24.1],    # left mouth corner
        [28.9, -28.9, -24.1],     # right mouth corner
    ],
    dtype=np.float64,
)


def euclidean(a, b):
    """Euclidean distance between two 2D points."""
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))


def eye_aspect_ratio(pts):
    """EAR from six (x, y) eye points in p1..p6 order."""
    p1, p2, p3, p4, p5, p6 = pts
    vertical = euclidean(p2, p6) + euclidean(p3, p5)
    horizontal = 2.0 * euclidean(p1, p4)
    if horizontal == 0:
        return 0.0
    return vertical / horizontal


def mouth_aspect_ratio(pts):
    """MAR from mouth points: corners (p1,p2) + two vertical lip pairs."""
    p_left, p_right, o_top, o_bot, _, _, i_top, i_bot = pts
    vertical = euclidean(i_top, i_bot) + euclidean(o_top, o_bot)
    horizontal = 2.0 * euclidean(p_left, p_right)
    if horizontal == 0:
        return 0.0
    return vertical / horizontal


class LandmarkDetector:
    """Stateless per-frame facial-landmark analyzer built on FaceMesh."""

    def __init__(self, static_mode=False, max_faces=1, min_det_conf=0.5,
                 min_track_conf=0.5, refine=True):
        if not _MP_AVAILABLE:
            raise ImportError(
                "mediapipe is not installed. Run `pip install mediapipe` "
                "or use the CNN-only path."
            )
        self._mp_face = mp.solutions.face_mesh
        self.face_mesh = self._mp_face.FaceMesh(
            static_image_mode=static_mode,
            max_num_faces=max_faces,
            refine_landmarks=refine,
            min_detection_confidence=min_det_conf,
            min_tracking_confidence=min_track_conf,
        )
        self.refine = refine

    # ------------------------------------------------------------------ #
    def process(self, frame_rgb):
        """Run FaceMesh on an RGB frame. Returns landmark list or None."""
        results = self.face_mesh.process(frame_rgb)
        if not results.multi_face_landmarks:
            return None
        return results.multi_face_landmarks[0]

    # ------------------------------------------------------------------ #
    def analyze(self, frame_bgr):
        """
        Full per-frame analysis.

        Parameters
        ----------
        frame_bgr : np.ndarray  (H, W, 3) BGR image (OpenCV default)

        Returns
        -------
        dict with keys:
            found (bool), ear, mar, pitch, yaw, roll,
            left_eye_pts, right_eye_pts, mouth_pts, landmarks
        or {"found": False} if no face is detected.
        """
        import cv2
        h, w = frame_bgr.shape[:2]
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        face = self.process(frame_rgb)
        if face is None:
            return {"found": False}

        def px(idx):
            lm = face.landmark[idx]
            return (lm.x * w, lm.y * h)

        left_pts = [px(i) for i in LEFT_EYE]
        right_pts = [px(i) for i in RIGHT_EYE]
        mouth_pts = [px(i) for i in MOUTH]

        ear_left = eye_aspect_ratio(left_pts)
        ear_right = eye_aspect_ratio(right_pts)
        ear = (ear_left + ear_right) / 2.0
        mar = mouth_aspect_ratio(mouth_pts)

        pitch, yaw, roll = self._head_pose(face, w, h)

        return {
            "found": True,
            "ear": ear,
            "ear_left": ear_left,
            "ear_right": ear_right,
            "mar": mar,
            "pitch": pitch,
            "yaw": yaw,
            "roll": roll,
            "left_eye_pts": left_pts,
            "right_eye_pts": right_pts,
            "mouth_pts": mouth_pts,
            "landmarks": face,
        }

    # ------------------------------------------------------------------ #
    def _head_pose(self, face, w, h):
        """Estimate head Euler angles (degrees) via solvePnP."""
        import cv2
        image_pts = np.array(
            [(face.landmark[i].x * w, face.landmark[i].y * h) for i in POSE_LANDMARKS],
            dtype=np.float64,
        )
        focal = w
        cam_matrix = np.array(
            [[focal, 0, w / 2.0],
             [0, focal, h / 2.0],
             [0, 0, 1]],
            dtype=np.float64,
        )
        dist = np.zeros((4, 1))
        ok, rvec, _ = cv2.solvePnP(
            _FACE_3D_MODEL, image_pts, cam_matrix, dist,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            return 0.0, 0.0, 0.0
        rmat, _ = cv2.Rodrigues(rvec)
        # Decompose to Euler angles.
        sy = np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        singular = sy < 1e-6
        if not singular:
            x = np.arctan2(rmat[2, 1], rmat[2, 2])
            y = np.arctan2(-rmat[2, 0], sy)
            z = np.arctan2(rmat[1, 0], rmat[0, 0])
        else:
            x = np.arctan2(-rmat[1, 2], rmat[1, 1])
            y = np.arctan2(-rmat[2, 0], sy)
            z = 0.0
        pitch = np.degrees(x)
        yaw = np.degrees(y)
        roll = np.degrees(z)
        # Normalize pitch so that "looking straight" ~ 0.
        if pitch > 90:
            pitch -= 180
        elif pitch < -90:
            pitch += 180
        return float(pitch), float(yaw), float(roll)

    # ------------------------------------------------------------------ #
    def eye_crop(self, frame_bgr, eye_pts, pad=6):
        """Return a grayscale crop around an eye for the CNN classifier."""
        import cv2
        xs = [p[0] for p in eye_pts]
        ys = [p[1] for p in eye_pts]
        x1, x2 = int(min(xs)) - pad, int(max(xs)) + pad
        y1, y2 = int(min(ys)) - pad, int(max(ys)) + pad
        h, w = frame_bgr.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame_bgr[y1:y2, x1:x2]
        return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    def close(self):
        try:
            self.face_mesh.close()
        except Exception:
            pass
