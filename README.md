# watermark-remover

Drop a photo in a folder and get the same photo back without the watermark. No manual steps.

Built for photos you own that carry your own fixed text watermark.

## Status

Planning. No code yet. The design below is the agreed direction and will be proven on sample photos first.

## How it will work

1. **Watch**: a background service notices a new file in `in/`.
2. **Find**: OpenCV locates the watermark text in the photo, wherever it sits.
3. **Mask**: a mask slightly larger than the text is drawn.
4. **Remove**: IOPaint with the LaMa model fills the masked area from the surrounding pixels.
5. **Paste back**: only the filled patch is copied onto the original, so every other pixel stays identical.
6. **Check**: the detector runs again on the result. If the watermark is still found, the photo fails.
7. **Deliver**: passing photos go to `clean/`, failing ones go to `needs-attention/`. The untouched original is kept in `originals/`.
8. **Record**: one log row per photo (found or not, score, pass or fail).

## Rules the tool must keep

- Only pixels under the watermark may change.
- Output keeps the original resolution and format.
- Photos never leave the machine. Everything runs locally.
- Nothing uncertain is delivered as clean.

## Planned stack

Python, watchdog, OpenCV, IOPaint (LaMa), Pillow, SQLite.

## Folders

| Folder | Purpose |
|---|---|
| `in/` | Drop photos here |
| `clean/` | Results that passed the check |
| `needs-attention/` | Results that failed the check |
| `originals/` | Untouched copies of every dropped photo |

These folders are ignored by git so photos are never committed.

## Use

Only use this on images you own or have the right to edit.
