"""
detection/cnn_model.py
=======================
Optional Convolutional Neural Network that classifies an eye crop as
OPEN or CLOSED. This is the "trained model" path: you train it with
`train_model.py` on an eye-state dataset (e.g. the MRL Eye Dataset) and
drop the resulting `models/eye_state_cnn.h5` in place.

The rest of the app works fine WITHOUT this model — the landmark-based
EAR detector is the default. When a trained model is present and
`Config.USE_CNN` is on, the pipeline blends the CNN's opinion with EAR
for a more robust eye-closure signal.

TensorFlow is imported lazily so that the dashboard still runs on machines
that only installed the lightweight (landmark) dependencies.
"""

import os
import numpy as np


def build_model(input_size=64):
    """
    Build & compile the eye-state CNN.

    A compact VGG-style network: 3 conv blocks -> dense head -> sigmoid.
    Input : (input_size, input_size, 1) grayscale eye crop.
    Output: probability the eye is CLOSED (0 = open, 1 = closed).
    """
    from tensorflow.keras import layers, models  # lazy import

    model = models.Sequential(name="eye_state_cnn")
    model.add(layers.Input(shape=(input_size, input_size, 1)))

    model.add(layers.Conv2D(32, (3, 3), activation="relu", padding="same"))
    model.add(layers.BatchNormalization())
    model.add(layers.MaxPooling2D((2, 2)))

    model.add(layers.Conv2D(64, (3, 3), activation="relu", padding="same"))
    model.add(layers.BatchNormalization())
    model.add(layers.MaxPooling2D((2, 2)))

    model.add(layers.Conv2D(128, (3, 3), activation="relu", padding="same"))
    model.add(layers.BatchNormalization())
    model.add(layers.MaxPooling2D((2, 2)))

    model.add(layers.Flatten())
    model.add(layers.Dropout(0.5))
    model.add(layers.Dense(128, activation="relu"))
    model.add(layers.Dropout(0.3))
    model.add(layers.Dense(1, activation="sigmoid"))

    model.compile(
        optimizer="adam",
        loss="binary_crossentropy",
        metrics=["accuracy"],
    )
    return model


class EyeStateClassifier:
    """
    Thin inference wrapper around a trained Keras eye-state model.

    Degrades gracefully: if TensorFlow is missing or the model file is not
    found, `available` is False and the pipeline falls back to EAR only.
    """

    def __init__(self, model_path, input_size=64):
        self.model_path = model_path
        self.input_size = input_size
        self.model = None
        self.available = False
        self._load()

    def _load(self):
        if not os.path.exists(self.model_path):
            return
        try:
            from tensorflow.keras.models import load_model
            self.model = load_model(self.model_path)
            self.available = True
        except Exception as exc:               # pragma: no cover
            print(f"[EyeStateClassifier] Could not load model: {exc}")
            self.available = False

    # ------------------------------------------------------------------ #
    def _preprocess(self, eye_gray):
        import cv2
        img = cv2.resize(eye_gray, (self.input_size, self.input_size))
        img = img.astype("float32") / 255.0
        return img.reshape(1, self.input_size, self.input_size, 1)

    def predict_closed_prob(self, eye_gray):
        """Return P(closed) in [0, 1] for a single grayscale eye crop."""
        if not self.available or eye_gray is None or eye_gray.size == 0:
            return None
        batch = self._preprocess(eye_gray)
        pred = float(self.model.predict(batch, verbose=0)[0][0])
        return pred

    def predict_pair(self, left_gray, right_gray):
        """Average P(closed) across both eyes (ignoring missing crops)."""
        probs = []
        for eye in (left_gray, right_gray):
            p = self.predict_closed_prob(eye)
            if p is not None:
                probs.append(p)
        if not probs:
            return None
        return float(np.mean(probs))
