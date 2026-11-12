# Decisions not visible in the code
Format: YYYY-MM-DD | decision | why | who decided

2026-11-12 | Fully automatic, no painting or review step in the normal path | The person using it only wants to drop photos and collect results | owner
2026-11-12 | Runs on a laptop, folder in and folder out, usually one photo per drop | No server needed for a pilot | owner
2026-11-12 | Build before real sample photos were available | Wanted a working version now; thresholds are tuned on synthetic photos and must be re-tuned on real ones | owner
2026-11-12 | Fill with LaMa on a mask, not a whole-image generation model | A generation model redraws the whole photo and can alter the car; a mask limits changes to the watermark | Claude, accepted by owner
2026-11-12 | Removes only the single mark in `watermark.png`; everything else is held back | The tool is for the owner's own mark, not for other parties' marks | Claude
2026-11-12 | The repository is public on GitHub | Asked for it to be public, twice, after the alternative was raised | owner
