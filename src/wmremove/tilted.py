"""Reverse the faint, translucent Torque Motors stamp on 16:9 photos."""
from __future__ import annotations

import cv2
import numpy as np

from .detect import _highpass

# The number of strong, consistent edge responses expected along the wordmark.
MIN_WORD_EVIDENCE = 15


class TiltedTorque:
    def __init__(self, alpha, colors):
        self.alpha = alpha.astype(np.float32) / 1275  # mattes encode 0–20% opacity
        self.colors = colors.astype(np.float32)
        self.luma = self.colors @ np.array([0.299, 0.587, 0.114], np.float32)
        h, w = self.alpha.shape[1:]
        self.size = (w, h)

    def _measure(self, rgb):
        reference = cv2.resize(rgb, self.size, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY).astype(np.float32)
        detail = _highpass(gray)
        weight = 1 / (cv2.GaussianBlur(abs(detail), (0, 0), 3) + 3)
        background = gray - detail
        features = np.stack([
            _highpass(alpha * (tone - background)) * weight
            for alpha, tone in zip(self.alpha, self.luma)
        ])
        return detail * weight, features

    @staticmethod
    def _word_evidence(detail, features):
        # Concentrate on TORQUE so busy trim near the dial contributes less.
        band = slice(135, 235)
        signature = features[:, band].sum(axis=0)
        return float(np.sum(signature * detail[band]) / max(np.linalg.norm(signature), 1e-6))

    def evidence(self, rgb):
        return self._word_evidence(*self._measure(rgb))

    def reverse(self, rgb):
        h, w = rgb.shape[:2]
        ratio = w / h
        if not 1.73 <= ratio <= 1.83:
            return None

        detail, features = self._measure(rgb)
        if self._word_evidence(detail, features) < MIN_WORD_EVIDENCE:
            return None
        values = features.reshape(len(self.alpha), -1).T
        strength = np.linalg.lstsq(values, detail.ravel(), rcond=None)[0]
        if strength[0] < 0.45:
            return None

        opacity = np.clip(strength, 0.3, 1.1)[:, None, None] * self.alpha
        total = opacity.sum(axis=0)
        added = np.einsum("ihw,ic->hwc", opacity, self.colors)
        # Resize premultiplied color and opacity together, then invert the
        # blend at the original resolution to retain detail like screen text.
        blend = cv2.resize(np.dstack((added, total)), (w, h))
        restored = (rgb - blend[..., :3]) / (1 - blend[..., 3:])
        return np.rint(restored).clip(0, 255).astype(np.uint8)
