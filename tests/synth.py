"""Synthetic photos and watermarks, so tests need no real pictures."""
import cv2
import numpy as np


def make_photo(seed, w=1200, h=800):
    """A busy RGB picture: gradient, shapes, lines and noise standing in for a car in a showroom."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 1, h)[:, None, None]
    img = (rng.integers(60, 230, 3) * (1 - t) + rng.integers(20, 120, 3) * t) * np.ones((h, w, 1))
    img = img.astype(np.uint8)
    for _ in range(30):
        color = tuple(int(c) for c in rng.integers(0, 256, 3))
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        kind = rng.integers(0, 3)
        if kind == 0:
            cv2.rectangle(img, (x, y), (x + int(rng.integers(40, 400)), y + int(rng.integers(20, 250))), color, -1)
        elif kind == 1:
            axes = (int(rng.integers(20, 200)), int(rng.integers(20, 120)))
            cv2.ellipse(img, (x, y), axes, float(rng.integers(0, 180)), 0, 360, color, -1)
        else:
            cv2.line(img, (x, y), (int(rng.integers(0, w)), int(rng.integers(0, h))), color, int(rng.integers(1, 6)))
    img = cv2.GaussianBlur(img, (0, 0), 1.2).astype(np.float32) + rng.normal(0, 4, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def make_mark(text="SAMPLE MARK", height=60, angle=0.0):
    """White text on a transparent background, as an RGBA array. `angle` tilts it."""
    font, scale, thick = cv2.FONT_HERSHEY_DUPLEX, height / 30, max(2, height // 12)
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    alpha = np.zeros((th + base + 8, tw + 8), np.uint8)
    cv2.putText(alpha, text, (4, th + 4), font, scale, 255, thick, cv2.LINE_AA)
    if angle:
        h, w = alpha.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        cos, sin = abs(m[0, 0]), abs(m[0, 1])
        nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
        m[0, 2] += nw / 2 - w / 2
        m[1, 2] += nh / 2 - h / 2
        alpha = cv2.warpAffine(alpha, m, (nw, nh))
    rgba = np.full((*alpha.shape, 4), 255, np.uint8)
    rgba[..., 3] = alpha
    return rgba


def stamp(photo, mark, x, y, scale=1.0, opacity=0.6):
    """Blend the mark onto a copy of the photo with its top-left corner at (x, y)."""
    m = cv2.resize(mark, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    h, w = m.shape[:2]
    a = m[..., 3:4].astype(np.float32) / 255 * opacity
    out = photo.astype(np.float32)
    out[y : y + h, x : x + w] = out[y : y + h, x : x + w] * (1 - a) + m[..., :3] * a
    return out.astype(np.uint8)
