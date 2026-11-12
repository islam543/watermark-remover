"""Fill the masked area with LaMa and paste back only the masked pixels."""
from __future__ import annotations

import cv2
import numpy as np


class Lama:
    """The LaMa model, loaded once through IOPaint and kept in memory."""

    def __init__(self, device="cpu"):
        import torch
        from iopaint.download import cli_download_model, scan_models
        from iopaint.model_manager import ModelManager
        from iopaint.schema import HDStrategy, InpaintRequest

        if "lama" not in [m.name for m in scan_models()]:
            cli_download_model("lama")  # one time, about 200 MB, checksum-verified by IOPaint
        self._model = ModelManager(name="lama", device=torch.device(device))
        self._request = InpaintRequest(hd_strategy=HDStrategy.ORIGINAL)

    def __call__(self, rgb, mask):
        bgr = self._model(rgb, mask, self._request)
        return cv2.cvtColor(np.clip(bgr, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)


def remove(rgb, mask, inpaint, margin=128, max_side=1536):
    """Return a copy of the photo where only pixels under the mask have changed.

    Works on a crop around the mask so speed does not depend on photo size.
    A crop larger than `max_side` is filled at reduced size and scaled back up.
    """
    ys, xs = np.nonzero(mask)
    y0, y1 = max(ys.min() - margin, 0), min(ys.max() + 1 + margin, rgb.shape[0])
    x0, x1 = max(xs.min() - margin, 0), min(xs.max() + 1 + margin, rgb.shape[1])
    crop = np.ascontiguousarray(rgb[y0:y1, x0:x1])
    cmask = np.ascontiguousarray(mask[y0:y1, x0:x1])
    h, w = cmask.shape
    f = min(1.0, max_side / max(h, w))
    if f < 1:
        size = (round(w * f), round(h * f))
        small_mask = cv2.resize(cmask, size, interpolation=cv2.INTER_NEAREST)
        small_mask = cv2.dilate(small_mask, np.ones((3, 3), np.uint8))
        filled = inpaint(cv2.resize(crop, size, interpolation=cv2.INTER_AREA), small_mask)
        filled = cv2.resize(filled, (w, h), interpolation=cv2.INTER_CUBIC)
    else:
        filled = inpaint(crop, cmask)
    out = rgb.copy()
    out[y0:y1, x0:x1][cmask > 0] = filled[cmask > 0]
    return out
