---
name: coursera-course-traverser
description: >-
  Automates Coursera syllabus traversal, including video playback speedup,
  scroll-to-complete readings, and dynamic quiz-solving using Gemini 3.5.
---

# Coursera Course Traverser Skill

## Overview
This skill allows AI coding assistants to manage, execute, and troubleshoot the ACCCE (Autonomous Coursera Course Completion Engine) script within this project workspace.

## Quick Start
To launch the traverser for a specific course:
1. Verify the user's session is active in the database (or ask them to run in headful mode first to log in).
2. Execute the traverser in the background:
   ```bash
   $env:PYTHONPATH="."; python main.py --course-id <course-id> --headless --ai-model gemini-3.5-flash
   ```
3. Monitor progress by printing the last 40 lines of `project_accce.log` or running:
   ```bash
   python scratch/check_progress.py
   ```

## Workflow & Operations

### 1. Launching Traversers
* Ensure the target course ID matches the URL slug.
* Prefer running in `--headless` mode with `--ai-model gemini-3.5-flash` for quiz-solving accuracy.

### 2. Session Validation (Headful Login)
* If the log reports `No session cookies found`, instruct the user to run the engine once without the `--headless` flag:
  `$env:PYTHONPATH="."; python main.py --course-id <course-id>`
  This opens a Chromium window for the user to manually enter credentials. Once cookies are saved to SQLite, future runs can be headless.

### 3. Troubleshooting Node Halts
* **Video Node Fails:** Ensure that Playwright finds the `<video>` element on the page or inside sub-frames. The script uses an async helper in browser context to wait for the video to end (`video.ended === true`) before checking verification.
* **Quiz Fails (< 80%):** Check `project_accce.log`. Review the AI responses and rate limits. If rate-limited, verify multiple API keys are present in `config.json`. The engine will cycle through available keys.
* **Verification Issues:** Check if the course structure has custom layout elements (like complex LTI external tool links or peer reviews). Peer reviews or manual external lab launchers must be solved in interactive mode or handled manually.

## Common Mistakes
* **Running cd commands:** Never try to navigate using `cd` inside terminal commands; specify paths relative to workspace root or use absolute paths.
* **Missing PYTHONPATH:** Always prefix the execution command with `$env:PYTHONPATH="."` on Windows shell to resolve the project imports correctly.
