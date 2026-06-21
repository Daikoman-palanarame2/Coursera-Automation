# 🚀 ACCCE: Autonomous Coursera Course Completion Engine

ACCCE is an **Autonomous Web Agent** built to automate the end-to-end traversal and completion of Coursera courses. Unlike traditional browser extensions that simply assist human users, ACCCE runs completely hands-free (headless) in the background, scraping syllabus structures, resolving quizzes via AI reasoning, simulating realistic human scrolling/telemetry, and persisting progress in a local database.

---

## 🌟 Key Features

* **🤖 Autonomous Autopilot:** Fully traverses courses (videos, readings, quizzes, surveys, and reflections) completely hands-free.
* **💾 State & Session Persistence (Resumable):** Stores session cookies and course syllabus structures in a local **SQLite database (`project_accce.db`)**. If interrupted, it resumes exactly where it stopped.
* **🧠 Cognitive Quiz Solving (Gemini 3.5):** Reads quiz elements from the DOM, resolves multiple-choice and open-ended writing prompts, handles API key failovers when rate-limited, and reads grading feedback to auto-correct mistakes.
* **📹 Enhanced Video Emulation:** Automatically plays videos, fast-forwards them at 16x speed, waits for native `ended` events, and verifies completion before moving on.
* **🔒 Stealth Integration:** Humanized click patterns, randomized sleep intervals, and stealth browser configurations to operate naturally on the platform.

---

## ⚔️ Comparison: Autopilot Agent vs. Browser Copilot

Here is how ACCCE compares to standard browser extensions like `nerufuyo/coursera-automation`:

| Feature | Browser Extension (Copilot) | ACCCE (Autopilot Agent) |
| :--- | :--- | :--- |
| **Execution** | Manual browsing & clicking required. | Standalone command-line automated process. |
| **Browsing Mode** | Headful only (runs inside your browser). | Headless (runs silently in the background). |
| **State Memory** | None (starts fresh every page reload). | SQLite database (saves exact completed syllabus nodes). |
| **Quiz Abilities** | Basic multiple-choice assistance. | Solves text questions, self-reflections, and auto-corrects. |
| **Telemetry** | Speeds up video (manual click required). | Full video play-and-verify loops automatically. |

---

## 🛠️ Installation & Setup (5 Minutes)

### 1. Prerequisites
* **Python 3.10+** installed.
* **Playwright** dependencies installed.

### 2. Clone and Setup
```bash
git clone <repository-url>
cd project_accce
pip install -r requirements.txt
playwright install chromium
```

### 3. Session Setup (First-Time Login)
To login to your Coursera account:
1. Run the traverser in **headful mode** (without the `--headless` flag):
   ```bash
   $env:PYTHONPATH="."; python main.py --course-id <course-id>
   ```
2. A Chrome browser window will open. Complete the login manually with your Coursera credentials.
3. Once logged in, the engine will automatically detect the active session, save the cookies to `project_accce.db`, and begin scanning the syllabus.
4. You can now close the script and run it in **headless mode** in the future:
   ```bash
   $env:PYTHONPATH="."; python main.py --course-id <course-id> --headless --ai-model gemini-3.5-flash
   ```

---

## 🎮 Command Line Interface

Run the traverser engine:
```bash
$env:PYTHONPATH="."; python main.py --course-id <course-id> --headless --ai-model gemini-3.5-flash
```

### Options
* `--course-id`: The Coursera course slug from the URL (e.g., `accelerate-your-job-search-with-ai`).
* `--headless`: Run the browser in the background (no visible UI).
* `--ai-model`: The Gemini model to use for quiz answers (defaults to `gemini-flash-latest`, recommended `gemini-3.5-flash`).

### Environment Variables
Configure the following keys in your environment (or `.env` file):
* `COURSERA_ENGINE_TOKEN`: Your anonymous access token to connect to the licensing/layout server.
* `COURSERA_ENGINE_BACKEND_URL`: The URL of the hosted licensing server (defaults to the production API gateway).
* `GEMINI_API_KEY`: Your personal Gemini API key. This key is used **100% locally** for solving quizzes on your machine and is never sent to the backend server.

---

## 📊 Monitoring Progress
You can query completion statistics stored in the SQLite database by running:
```bash
python scratch/check_progress.py
```
This prints the completion percentages and next pending nodes for all courses in your workspace.

---

## 🔒 Licensing & Subscription Model

ACCCE is a premium gated utility. To connect to the remote server and fetch the latest layout mappings, you must configure a valid token:

* **Subscription Fee**: **$3.00 USD / month** (paid in **USDT** stablecoin on the **Polygon PoS** network).
* **Automated Payments**: When your token expires, the bot will automatically pause and display exact payment instructions in your command terminal. Once you send the transaction, our backend checks the blockchain and activates your token within minutes.
* **How to Get a Token**: Currently, tokens are issued manually. To request a new token or active trial, please contact the repository administrator or join our community server.

---

## 📜 License
This project is licensed under the MIT License.
