---
name: remove-car-overlays
description: Clean supported QatarSale, Qatar Living, Mzad Qatar, and Torque Motors overlays from car photos. Use when the user asks to clean an attached photo, local image or folder, direct image link, or listing link with this project.
---

Run the existing app from this repository's root. The user supplies an image, folder, or link and receives the cleaned files.

1. Use the local file path for an attachment if the client exposes one. If you can see only a preview, ask for its local path or a direct image link. Confirm you have an input before running the app.
2. Run `uv run --locked python -m wmremove "<input>"` yourself with the supplied path or URL as one quoted argument. Use an absolute path for local inputs. If the user requests a destination, pass `-o "<destination>"`. For an attachment stored temporarily, give the output a new name with the same image extension under the project's `clean/` folder so the user can find it after the chat.
3. On first use, allow time for `uv` to set up the environment and download the model. If `uv` is missing, help set it up from the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/), using the client's approval flow if it requires permission.
4. Check the command's output and the files it produced. Give the user the exact paths or clickable links to the clean images or folder. For a partial batch, report the successful files and what failed. If a listing blocks downloads, ask for a direct photo link or a local folder.

Use one-off processing for this workflow so original files stay in place. The built-in matcher targets the known overlay artwork and can report that an image has no match.
