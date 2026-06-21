# 🚀 ACCCE: Automatic Coursera Autopilot Bot

ACCCE is an automatic tool that helps you complete Coursera courses in the background. Unlike regular browser extensions that just speed up videos, ACCCE runs completely hands-free on your computer: it plays videos, reads pages, solves quizzes using smart AI (Gemini), and saves your progress so you can pause and resume at any time.

---

## 🌟 What ACCCE Does For You

* **🤖 100% Hands-Free**: Automatically clicks through lessons, videos, and quizzes for you.
* **🧠 Smart Quiz Solver**: Uses Google's Gemini AI to read questions, write answers, and get perfect grades.
* **📹 Auto-Video Watcher**: Plays videos, speeds them up to finish faster, and makes sure Coursera registers them as completed.
* **💾 Memory (Resumable)**: If you close the program or lose internet, it remembers exactly where you left off and resumes from there.
* **🔒 Human-like Movement**: Moves and clicks naturally to look like a real person learning.

---

## 🛠️ Easy Setup Guide (5 Minutes)

You don't need to be a developer to use this! Just follow these simple steps:

### Step 1: Install Python
If you don't have Python installed:
1. Download and install **Python 3.10 or newer** from the official website: [python.org/downloads](https://www.python.org/downloads/).
2. **Important:** During installation, check the box that says **"Add Python to PATH"** before clicking Install.

### Step 2: Download the Bot
Open your terminal (Command Prompt on Windows or Terminal on Mac) and run these commands:
```bash
git clone https://github.com/Daikoman-palanarame2/Coursera-Automation.git
cd Coursera-Automation
pip install -r requirements.txt
playwright install chromium
```

### Step 3: Set Up Your Keys (.env File)
The bot needs a few keys to run. We made this very simple:
1. Inside the `Coursera-Automation` folder, find the file named `.env.example`.
2. Copy it and rename the copy to just `.env` (make sure it doesn't end in `.txt`).
3. Open the `.env` file in **Notepad** (or any text editor) and fill in your keys:
   * **`COURSERA_ENGINE_TOKEN`**: Paste the subscription key you received from the admin.
   * **`GEMINI_API_KEY`**: Paste your personal Gemini API key. *(This key runs locally on your machine to solve quizzes; it is never shared with us).*

---

## 🎮 How to Run the Bot

We built a double-clickable launcher file for Windows users to make running the bot completely effortless:

1. **Double-click the `start.bat`** file in your `Coursera-Automation` folder.
2. The launcher will automatically perform first-time setup (creating a virtual environment, installing dependencies, and downloading the Playwright browser).
3. When prompted, **paste your Coursera course URL** (e.g., `https://www.coursera.org/learn/digital-marketing`) directly from your browser's address bar. The bot will automatically clean the URL and extract the course name.
4. Select **Mode [1] (visible browser)** for your first run, and complete the login manually when the browser opens.
5. For future runs, select **Mode [2] (invisible background)** so the bot runs silently in the background while you work!

*(Non-Windows users can run the bot in their terminal by typing `python main.py --course-id digital-marketing --headless`).*

---

## 🔒 Subscription & Pricing

To keep the bot updated (since Coursera changes its website design often), we use a simple subscription model:

* **Price**: **$3.00 USD / month** (paid in **USDT** stablecoin on the **Polygon** network).
* **How to Pay**: When your 30-day token expires, the bot will automatically pause and display easy payment instructions in your terminal. Once you send the transaction, our server automatically detects it and reactivates your key in minutes.
* **Get a Key**: Currently, keys are issued manually. Join our community server or contact the repository administrator to get your key or request a free trial!

---

## 📜 License
This project is licensed under the MIT License.
