# watermark-remover

## Photo cleanup

Use the [remove-car-overlays skill](.claude/skills/remove-car-overlays/SKILL.md) when a user supplies a photo, link, or folder to clean. Run the app and return the cleaned files.

If you cloned this repo for the user in the current task, follow the [first-clone instructions](README.md#first-clone-with-claude-code) before replying.

## Verify (most important section)
- Tests: `uv run pytest -m "not slow"`
- Real model test: `uv run pytest -m slow` (downloads the LaMa model on first run, about 200 MB)
- Run: `uv run python -m wmremove`, then drop a photo in `in/`

## Decisions not in the code
- This is a laptop pilot, not a platform service. Before it runs as a company service it needs the architecture review and the platform rules (env config is done; Dockerfile, probes, metrics, no local-disk state are not).
- The folder service polls once a second instead of using a file-watching library. One less dependency, and it works on network folders.
- Python is pinned below 3.12 because IOPaint pins an old Pillow.

## Misleading areas
- `tests/` uses a cheap OpenCV fill instead of LaMa so tests are fast. Only tests marked `slow` prove real removal quality.

## Never touch
- `originals/`: the tool only ever adds files here.
- Never commit photos or `watermark.png`. The `.gitignore` blocks them; do not weaken it.

## Lessons (added via /retro)
- 
