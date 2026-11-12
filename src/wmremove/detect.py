"""Find one known watermark in a photo and build the mask that covers it."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

HP_SIGMA = 3.0  # blur used to strip the photo down to fine detail, in pixels
COARSE_SIDE = 1000  # long side for the first search over the whole photo
FINE_SIDE = 1600  # long side for refining position and size
MIN_CONTRAST = 1.0  # grey levels; flatter areas than this cannot produce a match


@dataclass(frozen=True)
class Detection:
    x: int
    y: int
    w: int
    h: int
    scale: float  # relative to the template's own pixels
    score: float  # 0..1, how well the template matches here


class Template:
    """The watermark to look for. A transparent PNG gives a letter-shaped mask;
    a plain image still works but the mask is the whole box."""

    def __init__(self, path):
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise FileNotFoundError(f"cannot read watermark template: {path}")
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        self.alpha = None
        bgr = img[..., :3].astype(np.float32)
        if img.shape[2] == 4 and img[..., 3].min() < 250:
            self.alpha = img[..., 3]
            a = self.alpha[..., None].astype(np.float32) / 255
            bgr = bgr * a + 128 * (1 - a)  # show the mark on mid grey
        self.gray = cv2.cvtColor(bgr.astype(np.uint8), cv2.COLOR_BGR2GRAY)


def _resize(img, w, h):
    shrink = w < img.shape[1]
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA if shrink else cv2.INTER_LINEAR)


def _highpass(gray):
    g = gray.astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), HP_SIGMA)


def _steps(lo, hi, ratio):
    n = max(2, int(np.ceil(np.log(hi / lo) / np.log(1 + ratio))) + 1)
    return np.geomspace(lo, hi, n)


def _scaled(tpl, tw, th):
    """The template's fine detail at a given size, and which of its pixels count."""
    t = _highpass(_resize(tpl.gray, tw, th))
    if tpl.alpha is None:
        return t, np.ones_like(t)
    k = 2 * round(HP_SIGMA) + 1  # count only pixels on or next to the letters
    near_letters = cv2.dilate((_resize(tpl.alpha, tw, th) > 16).astype(np.float32), np.ones((k, k), np.uint8))
    return t, near_letters


def _ncc(feat, feat_sq, t, m):
    """Normalised correlation of template t at every position, counting only pixels where m is 1."""
    n = float(m.sum())
    t = (t - float((t * m).sum()) / n) * m
    num = cv2.matchTemplate(feat, t, cv2.TM_CCORR)
    s1 = cv2.matchTemplate(feat, m, cv2.TM_CCORR)
    s2 = cv2.matchTemplate(feat_sq, m, cv2.TM_CCORR)
    var = np.maximum(s2 - s1 * s1 / n, n * MIN_CONTRAST**2)
    return num / np.sqrt(var * float((t * t).sum()))


def _best(gray, tpl, f, scales, near=None):
    """Best match of the template at resolution factor f.
    Returns (score, scale, x, y, w, h) in full-size pixels, or None."""
    img = _resize(gray, round(gray.shape[1] * f), round(gray.shape[0] * f)) if f < 1 else gray
    th0, tw0 = tpl.gray.shape
    ox = oy = 0
    if near is not None:  # only look around a place we already found
        _, _, x0, y0, w0, h0 = near
        pad = 0.06 * max(w0, h0) * f + 8
        ox, oy = max(int(x0 * f - pad), 0), max(int(y0 * f - pad), 0)
        img = img[oy : int((y0 + h0) * f + pad) + 1, ox : int((x0 + w0) * f + pad) + 1]
    feat = _highpass(img)
    feat_sq = feat * feat
    best = None
    for s in scales:
        tw, th = round(tw0 * s * f), round(th0 * s * f)
        if min(tw, th) < 8 or tw > img.shape[1] or th > img.shape[0]:
            continue
        res = _ncc(feat, feat_sq, *_scaled(tpl, tw, th))
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if best is None or score > best[0]:
            best = (float(score), float(s), (x + ox) / f, (y + oy) / f, tw / f, th / f)
    return best


def find(gray, tpl, min_share=0.08, max_share=1.0):
    """Locate the watermark in a grayscale photo, anywhere in it.
    min_share and max_share bound the watermark's width as a share of the photo's width."""
    long_side = max(gray.shape)
    unit = gray.shape[1] / tpl.gray.shape[1]  # scale at which the mark is as wide as the photo
    scales = _steps(min_share * unit, max_share * unit, 0.015)
    coarse = _best(gray, tpl, min(1.0, COARSE_SIDE / long_side), scales)
    if coarse is None:
        return None
    s0 = coarse[1]
    fine = _best(gray, tpl, min(1.0, FINE_SIDE / long_side), _steps(s0 / 1.03, s0 * 1.03, 0.003), near=coarse)
    score, s, x, y, w, h = fine or coarse
    return Detection(round(x), round(y), round(w), round(h), s, score)


def score_at(gray, tpl, det):
    """How strongly the watermark still matches where it was found. Used after removal."""
    near = (det.score, det.scale, det.x, det.y, det.w, det.h)
    best = _best(gray, tpl, min(1.0, FINE_SIDE / max(gray.shape)), [det.scale], near=near)
    return best[0] if best else 0.0


def build_mask(shape, det, tpl, grow):
    """uint8 mask the size of the photo, 255 where the watermark is, grown by `grow` pixels."""
    h, w = shape[:2]
    mask = np.zeros((h, w), np.uint8)
    x1, y1 = min(det.x + det.w, w), min(det.y + det.h, h)
    if tpl.alpha is None:
        mask[det.y : y1, det.x : x1] = 255
    else:
        a = _resize(tpl.alpha, det.w, det.h)[: y1 - det.y, : x1 - det.x]
        mask[det.y : y1, det.x : x1] = np.where(a > 16, 255, 0)
    if grow > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
        mask = cv2.dilate(mask, k)
    return mask
