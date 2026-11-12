# watermark-remover

Drop a photo in a folder and get the same photo back without your watermark. No manual steps, no painting.

It removes one watermark only: the one you give it as `watermark.png`. It is meant for photos you own that carry your own mark. A photo with any other mark, or none, is held back untouched.

## Status

First working version. Proven on synthetic test photos only. Not yet tested or tuned on real photos.

## Setup

Needs [uv](https://docs.astral.sh/uv/). It installs the right Python (3.11) by itself.

```bash
uv sync
```

This takes about 1.2 GB of disk. The first run also downloads the LaMa model once (196 MB).

Then put a picture of your watermark in the project folder as `watermark.png`:
- Best: a PNG with a transparent background, at the angle it appears in the photos. Only the letters are then removed.
- Also works: a tight crop of the mark from a photo. The whole box around the mark is then filled in, which is rougher.

## Use

```bash
uv run python -m wmremove
```

Leave it running. Drop photos into `in/`. Stop it with Ctrl+C; it finishes the photo in progress first.

| Folder | What ends up there |
|---|---|
| `in/` | You drop photos here. The tool empties it. |
| `clean/` | Photos with the watermark removed, same name, size and format. |
| `needs-attention/` | Photos the tool would not vouch for, unchanged. |
| `originals/` | The untouched copy of every photo you dropped. |

Why a photo was held back is printed in the terminal and stored in `wmremove.sqlite` (table `photos`).

## How it works

1. **Wait**: a dropped file is picked up once its size stops changing, so half-copied files are left alone.
2. **Find**: OpenCV looks for the watermark anywhere in the photo, at any size, and gives a match score.
3. **Mask**: a mask is drawn over the letters, slightly enlarged.
4. **Remove**: the LaMa model (through IOPaint, used as a library) fills the masked area.
5. **Paste back**: only the masked pixels are copied onto the original.
6. **Check**: the search runs again on the result. If the watermark still matches, the photo is held back.
7. **Record**: one row per photo with the scores and the time taken.

## What is guaranteed, and what is not

- PNG: every pixel outside the mask is identical to the original. Tested.
- JPEG: the photo is re-saved with its own compression tables, so areas outside the mask are visually the same but not bit-identical (average drift under 1 brightness level out of 255 in tests).
- The filled area is a reconstruction. The model guesses what was under the letters. Do not use this on photos where the pixels are evidence.
- The check catches "watermark still there". It does not catch a smear left where the watermark was.

## Measured so far (synthetic photos, laptop CPU)

- Found the mark in 32 of 32 photos, within 4 pixels, across sizes from 600x400 to 4000x3000, opacity 35 to 80 percent, corner and diagonal styles.
- Match score with the mark present: 0.74 or higher. Without it: 0.55 or lower. The threshold is 0.65.
- Time per photo, end to end: about 14 seconds for a 1288x966 photo and 20 seconds for a 4000x3000 photo. About 5 seconds of that is the search, which gets faster once the size range is narrowed (see settings).

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `WM_ROOT` | current folder | Where the four folders and the log live |
| `WM_TEMPLATE` | `<root>/watermark.png` | The watermark picture |
| `WM_MIN_SCORE` | `0.65` | Below this, the watermark counts as not found |
| `WM_MAX_RESIDUAL` | `0.35` | At or above this after removal, the photo is held back |
| `WM_MIN_SHARE` | `0.08` | Smallest watermark width, as a share of photo width |
| `WM_MAX_SHARE` | `1.0` | Largest watermark width, as a share of photo width |
| `WM_MASK_GROW` | `0` (automatic) | Extra pixels around the letters |
| `WM_MAX_MASK_SHARE` | `0.25` | Hold the photo back if the mask covers more than this share of it |
| `WM_DEVICE` | `cpu` | `cuda` on a machine with an NVIDIA card |

## Known limits

- The watermark must be the same picture every time, at the same angle. A rotated or reworded mark is not found.
- A mark that is cut off by the edge of the photo is not found.
- Photos with a rotation tag (some phone photos) are searched as stored, so a mark may be missed.
- Only formats Pillow can read and write (JPEG, PNG, WebP, TIFF). No HEIC.
- One photo at a time.

## Tests

```bash
uv run pytest -m "not slow"
```

```bash
uv run pytest -m slow
```

The first set uses a cheap stand-in for the model and checks the plumbing. The second runs the real LaMa model.
