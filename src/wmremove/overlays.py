"""Detect the four image overlays shown in the reference photos."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from .detect import Detection, Template, build_mask, find
from .tilted import TiltedTorque


@dataclass(frozen=True)
class Overlay:
    name: str
    template: Template
    region: tuple[float, float]  # vertical fractions of the image
    widths: tuple[float, float]  # template width as a fraction of image width
    min_score: float
    grow: float  # margin as a fraction of the matched width
    panel: bool = False


@dataclass(frozen=True)
class ReferenceOverlays:
    designs: tuple[Overlay, ...]
    tilted_torque: TiltedTorque


def load_overlays():
    """Load isolated artwork and alpha mattes packaged with the app."""
    with np.load(Path(__file__).with_name("overlay-mattes.npz")) as mattes:
        designs = (
            Overlay("QatarSale", Template.from_array(mattes["qatar_sale"]),
                    (0, 1), (0.33, 0.85), 0.51, 0.006),
            Overlay("Torque Motors", Template.from_array(mattes["torque"], 200),
                    (0, 0.35), (0.095, 0.29), 0.46, 0.05, panel=True),
            Overlay("Qatar Living", Template.from_array(mattes["qatar_living"]),
                    (0.55, 1), (0.12, 0.37), 0.55, 0.014),
            Overlay("Mzad Qatar", Template.from_array(mattes["mzad_qatar"]),
                    (0.62, 1), (0.10, 0.30), 0.56, 0, panel=True),
        )
        return ReferenceOverlays(designs, TiltedTorque(mattes["tilted_alpha"], mattes["tilted_rgb"]))


def locate(gray, overlay):
    y0, y1 = (round(edge * gray.shape[0]) for edge in overlay.region)
    if y1 - y0 < 8:
        return None
    step = 0.015 if overlay.name == "QatarSale" else 0.04
    det = find(gray[y0:y1], overlay.template, *overlay.widths, scale_step=step)
    return replace(det, y=det.y + y0) if det else None


def overlay_mask(shape, overlay, det: Detection, grow):
    margin = grow or round(det.w * overlay.grow)
    if overlay.panel:
        # Mzad has a dark backing, and some Torque versions have a halo
        # between the strokes that extends beyond the lettering.
        mask = np.zeros(shape, np.uint8)
        y0, x0 = max(0, det.y - margin), max(0, det.x - margin)
        mask[y0:det.y + det.h + margin, x0:det.x + det.w + margin] = 255
        return mask
    return build_mask(shape, det, overlay.template, max(1, margin))
