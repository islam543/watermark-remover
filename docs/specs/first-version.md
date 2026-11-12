# Spec: first working version
Date: 2026-11-12

## Goal (measurable)
A photo dropped in `in/` comes out in `clean/` with the company's own fixed text watermark removed, with no manual step. A photo the tool is not sure about goes to `needs-attention/` instead. The untouched original is always in `originals/`.

## Why it matters
The clean originals no longer exist, and the photos are needed without the mark. Doing it by hand per photo does not scale.

## Constraints
- Only pixels under the watermark may change. PNG output is identical elsewhere. JPEG output is re-saved with the original compression tables, so it is visually identical elsewhere, not bit-identical.
- Same resolution and file format as the input.
- Photos never leave the machine.
- Runs on a laptop without a GPU.
- Works only for the one watermark supplied as `watermark.png`. It does not look for or remove any other mark.

## Out of scope
- Other parties' watermarks.
- Any other photo editing.
- Upload page, direct write to app storage, a second generative attempt for hard cases.
- Running as a company platform service (see CLAUDE.md, Decisions).

## Check (exact commands that prove it's done)
- `uv run pytest -m "not slow"`: detection, routing, original kept, pixels outside the mask unchanged, restart recovery.
- `uv run pytest -m slow`: the real LaMa model removes a synthetic mark and passes the gate.
- Manual: `uv run python -m wmremove`, drop a photo in `in/`, see it in `clean/` or `needs-attention/`.

## Assumptions / open questions
- The watermark is the same text every time, at the same angle. Position and size may vary.
- `watermark.png` is a transparent PNG of the mark. A plain crop also works but removes a whole box, not only the letters.
- Not yet tested on real photos. Thresholds are tuned on synthetic photos and must be re-tuned on real samples.
- Open: how large and how transparent the real mark is. A large mark across the car is the hard case for quality.

## Plan
1. `detect.py`: find the mark (multi-scale template matching) and build the mask.
2. `inpaint.py`: fill the mask with LaMa (IOPaint), paste back only masked pixels.
3. `pipeline.py`: one photo end to end, the quality gate, routing, SQLite log.
4. `__main__.py`: the folder service.
5. Tests on synthetic photos.
