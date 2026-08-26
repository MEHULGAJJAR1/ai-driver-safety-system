"""
train_model.py
==============
Train the CNN eye-state classifier (open vs. closed eyes) used by the
optional deep-learning detection path.

Expected dataset layout (ImageDataGenerator flow_from_directory):

    data/
      train/
        open/     *.png|jpg   (open-eye crops)
        closed/   *.png|jpg   (closed-eye crops)
      val/
        open/     ...
        closed/   ...

Recommended public dataset: **MRL Eye Dataset**
    http://mrl.cs.vsb.cz/eyedataset
(~85k grayscale eye images labelled open/closed). Split it into the
train/ and val/ folders above, or use `--split` to auto-split a single
`--data` folder that has just open/ and closed/ subfolders.

Usage
-----
    python train_model.py --data data --epochs 20
    python train_model.py --data all_eyes --split 0.2 --epochs 25

The trained model is saved to models/eye_state_cnn.h5, which the dashboard
loads automatically on next start.
"""

import os
import argparse

from config import config
from detection.cnn_model import build_model


def build_generators(data_dir, img_size, batch, val_split):
    from tensorflow.keras.preprocessing.image import ImageDataGenerator

    train_dir = os.path.join(data_dir, "train")
    val_dir = os.path.join(data_dir, "val")

    common = dict(target_size=(img_size, img_size), color_mode="grayscale",
                  class_mode="binary", batch_size=batch)

    if os.path.isdir(train_dir) and os.path.isdir(val_dir):
        train_aug = ImageDataGenerator(
            rescale=1./255, rotation_range=12, width_shift_range=0.1,
            height_shift_range=0.1, zoom_range=0.1, horizontal_flip=True,
            brightness_range=[0.7, 1.3])
        val_aug = ImageDataGenerator(rescale=1./255)
        train_gen = train_aug.flow_from_directory(train_dir, shuffle=True, **common)
        val_gen = val_aug.flow_from_directory(val_dir, shuffle=False, **common)
    else:
        # single folder with open/ closed/ -> auto validation split
        print(f"[train] No train/ + val/ found; splitting '{data_dir}' "
              f"with validation_split={val_split}")
        aug = ImageDataGenerator(
            rescale=1./255, rotation_range=12, width_shift_range=0.1,
            height_shift_range=0.1, zoom_range=0.1, horizontal_flip=True,
            brightness_range=[0.7, 1.3], validation_split=val_split)
        train_gen = aug.flow_from_directory(data_dir, subset="training",
                                            shuffle=True, **common)
        val_gen = aug.flow_from_directory(data_dir, subset="validation",
                                          shuffle=False, **common)
    return train_gen, val_gen


def main():
    ap = argparse.ArgumentParser(description="Train eye-state CNN")
    ap.add_argument("--data", default="data", help="dataset root folder")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--img-size", type=int, default=config.CNN_INPUT_SIZE)
    ap.add_argument("--split", type=float, default=0.2,
                    help="validation split when no train/val subfolders exist")
    ap.add_argument("--out", default=config.CNN_MODEL_PATH)
    args = ap.parse_args()

    from tensorflow.keras.callbacks import (
        ModelCheckpoint, EarlyStopping, ReduceLROnPlateau)

    if not os.path.isdir(args.data):
        raise SystemExit(
            f"Dataset folder '{args.data}' not found. See the docstring at "
            f"the top of train_model.py for the expected layout and dataset.")

    train_gen, val_gen = build_generators(
        args.data, args.img_size, args.batch, args.split)

    print(f"[train] classes: {train_gen.class_indices}")
    model = build_model(args.img_size)
    model.summary()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    callbacks = [
        ModelCheckpoint(args.out, monitor="val_accuracy",
                        save_best_only=True, verbose=1),
        EarlyStopping(monitor="val_loss", patience=5,
                      restore_best_weights=True, verbose=1),
        ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=3, verbose=1),
    ]

    model.fit(train_gen, validation_data=val_gen,
              epochs=args.epochs, callbacks=callbacks)

    model.save(args.out)
    print(f"\n[train] Done. Best model saved to: {args.out}")
    print("[train] Restart the dashboard to pick up the new model "
          "(CNN badge will read ON).")


if __name__ == "__main__":
    main()
