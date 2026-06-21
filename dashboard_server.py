import http.server
import socketserver
import json
import os
import time
import sqlite3

PORT = 8000
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project_accce.db")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project_accce.log")

def get_db_status():
    """
    Reads SQLite database to determine current progress and course state.
    """
    if not os.path.exists(DB_PATH):
        return {
            "status": "OFFLINE",
            "course_id": "None",
            "progress_percent": 0,
            "completed_count": 0,
            "total_count": 0,
            "current_node": "None",
            "completed_nodes": [],
            "syllabus_nodes": [],
            "logs": ["No database found. Start ACCCE bot to initialize state."]
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Get course state
        row = conn.execute("SELECT * FROM course_state ORDER BY updated_at DESC LIMIT 1").fetchone()
        if not row:
            return {
                "status": "IDLE",
                "course_id": "None",
                "progress_percent": 0,
                "completed_count": 0,
                "total_count": 0,
                "current_node": "None",
                "completed_nodes": [],
                "syllabus_nodes": [],
                "logs": ["State database is empty. Waiting for bot initialization..."]
            }

        course_id = row["course_id"]
        current_node = row["current_node_id"] or "None"
        completed_nodes = json.loads(row["completed_nodes_json"])
        syllabus_nodes = json.loads(row["syllabus_nodes_json"]) if row["syllabus_nodes_json"] else []
        updated_at = row["updated_at"]

        # Calculate status
        # If database updated in last 15 seconds, bot is actively running
        is_active = (time.time() - updated_at) < 15.0
        status = "RUNNING" if is_active else "IDLE"

        # Calculate progress
        total_count = len(syllabus_nodes)
        completed_count = len(completed_nodes)
        progress_percent = round((completed_count / total_count) * 100, 1) if total_count > 0 else 0

        # Read last 35 lines of logs
        log_lines = []
        if os.path.exists(LOG_PATH):
            try:
                with open(LOG_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    log_lines = [l.strip() for l in lines[-35:]]
            except Exception as e:
                log_lines = [f"Error reading log file: {e}"]
        else:
            log_lines = ["Log file 'project_accce.log' not generated yet."]

        return {
            "status": status,
            "course_id": course_id,
            "progress_percent": progress_percent,
            "completed_count": completed_count,
            "total_count": total_count,
            "current_node": current_node,
            "completed_nodes": completed_nodes,
            "syllabus_nodes": syllabus_nodes,
            "logs": log_lines
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "course_id": "Error",
            "progress_percent": 0,
            "completed_count": 0,
            "total_count": 0,
            "current_node": "None",
            "completed_nodes": [],
            "syllabus_nodes": [],
            "logs": [f"Database query error: {e}"]
        }
    finally:
        conn.close()

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project ACCCE Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(17, 24, 39, 0.65);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --primary-glow: rgba(59, 130, 246, 0.15);
            --accent-color: #3b82f6;
            --accent-gradient: linear-gradient(135deg, #3b82f6, #06b6d4);
        }

        body {
            margin: 0;
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: 'Inter', sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 30px 20px;
            min-height: 100vh;
            box-sizing: border-box;
            background-image: radial-gradient(circle at 10% 20%, rgba(59, 130, 246, 0.05) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(6, 182, 212, 0.05) 0%, transparent 40%);
        }

        .container {
            max-width: 1100px;
            width: 100%;
            display: flex;
            flex-direction: column;
            gap: 25px;
        }

        /* Header Style */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
        }

        .logo {
            font-family: 'Outfit', sans-serif;
            font-weight: 800;
            font-size: 26px;
            letter-spacing: -0.02em;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .status-wrapper {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .status-badge {
            font-family: 'Outfit', sans-serif;
            font-size: 11px;
            font-weight: 800;
            padding: 5px 12px;
            border-radius: 20px;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }

        .badge-running {
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.25);
            box-shadow: 0 0 15px rgba(16, 185, 129, 0.1);
        }

        .badge-idle {
            background: rgba(245, 158, 11, 0.15);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.25);
        }

        .pulse-light {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: currentColor;
            display: inline-block;
            animation: pulse 1.8s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.9); opacity: 0.6; }
            50% { transform: scale(1.15); opacity: 1; }
            100% { transform: scale(0.9); opacity: 0.6; }
        }

        /* Grid Layout */
        .dashboard-grid {
            display: grid;
            grid-template-columns: 1fr 1.6fr;
            gap: 25px;
        }

        @media (max-width: 900px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
        }

        /* Glass Cards */
        .card {
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            box-sizing: border-box;
        }

        .card-title {
            font-family: 'Outfit', sans-serif;
            font-weight: 700;
            font-size: 18px;
            margin-top: 0;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        /* Progress Card */
        .progress-section {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 15px;
            height: 100%;
        }

        .progress-ring-container {
            position: relative;
            width: 160px;
            height: 160px;
        }

        .progress-ring-circle-bg {
            fill: none;
            stroke: rgba(255, 255, 255, 0.03);
            stroke-width: 12;
        }

        .progress-ring-circle {
            fill: none;
            stroke: url(#gradient);
            stroke-width: 12;
            stroke-linecap: round;
            transform: rotate(-90deg);
            transform-origin: 50% 50%;
            transition: stroke-dashoffset 0.6s ease-out;
        }

        .progress-text {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-family: 'Outfit', sans-serif;
            font-weight: 800;
            font-size: 32px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .progress-subtext {
            font-size: 11px;
            font-family: 'Inter', sans-serif;
            font-weight: 600;
            color: var(--text-secondary);
            margin-top: -2px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .meta-row {
            display: flex;
            justify-content: space-around;
            width: 100%;
            margin-top: 15px;
            border-top: 1px solid rgba(255, 255, 255, 0.04);
            padding-top: 15px;
        }

        .meta-item {
            text-align: center;
        }

        .meta-val {
            font-family: 'Outfit', sans-serif;
            font-size: 20px;
            font-weight: 700;
            color: var(--accent-color);
        }

        .meta-lbl {
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        /* Timeline Plan */
        .timeline {
            display: flex;
            flex-direction: column;
            gap: 12px;
            max-height: 400px;
            overflow-y: auto;
            padding-right: 5px;
        }

        .timeline::-webkit-scrollbar {
            width: 4px;
        }
        .timeline::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }

        .timeline-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.03);
            transition: all 0.25s ease;
        }

        .timeline-item.completed {
            border-color: rgba(16, 185, 129, 0.15);
            background: rgba(16, 185, 129, 0.02);
            opacity: 0.7;
        }

        .timeline-item.active {
            border-color: rgba(59, 130, 246, 0.4);
            background: rgba(59, 130, 246, 0.06);
            box-shadow: 0 0 15px rgba(59, 130, 246, 0.05);
            animation: pulse-border 2s infinite;
        }

        @keyframes pulse-border {
            0% { border-color: rgba(59, 130, 246, 0.3); }
            50% { border-color: rgba(59, 130, 246, 0.6); }
            100% { border-color: rgba(59, 130, 246, 0.3); }
        }

        .node-info {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .node-icon {
            font-size: 16px;
            width: 28px;
            height: 28px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(255, 255, 255, 0.04);
        }

        .timeline-item.completed .node-icon {
            background: rgba(16, 185, 129, 0.1);
            color: #10b981;
        }

        .timeline-item.active .node-icon {
            background: rgba(59, 130, 246, 0.15);
            color: #3b82f6;
        }

        .node-name {
            font-weight: 600;
            font-size: 13px;
        }

        .node-meta {
            font-size: 10px;
            color: var(--text-secondary);
            margin-top: 1px;
            text-transform: uppercase;
            letter-spacing: 0.02em;
        }

        .node-status-label {
            font-family: 'Outfit', sans-serif;
            font-size: 9px;
            font-weight: 800;
            padding: 3px 8px;
            border-radius: 6px;
            letter-spacing: 0.05em;
        }

        .status-completed { color: #10b981; background: rgba(16, 185, 129, 0.08); }
        .status-active { color: #3b82f6; background: rgba(59, 130, 246, 0.12); }
        .status-pending { color: var(--text-secondary); background: rgba(255, 255, 255, 0.04); }

        /* Console Card */
        .console-card {
            grid-column: 1 / -1;
        }

        .console-box {
            background: rgba(0, 0, 0, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 14px;
            padding: 15px 20px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px;
            color: #38bdf8;
            overflow-y: auto;
            height: 280px;
            line-height: 1.6;
            white-space: pre-wrap;
            box-shadow: inset 0 2px 10px rgba(0, 0, 0, 0.5);
            text-shadow: 0 0 2px rgba(56, 189, 248, 0.15);
        }

        .console-box::-webkit-scrollbar {
            width: 4px;
        }
        .console-box::-webkit-scrollbar-thumb {
            background: rgba(56, 189, 248, 0.2);
            border-radius: 10px;
        }

        .log-success { color: #34d399; }
        .log-warning { color: #fbbf24; }
        .log-error { color: #f87171; }
        .log-info { color: #38bdf8; }
        .log-default { color: #e2e8f0; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">🚀 PROJECT ACCCE</div>
            <div class="status-wrapper">
                <span style="color: var(--text-secondary); font-size: 12px;" id="course-name-header">Course: react-basics</span>
                <span id="bot-status-badge" class="status-badge">
                    <span class="pulse-light"></span> <span id="status-text">Checking</span>
                </span>
            </div>
        </header>

        <div class="dashboard-grid">
            <!-- Left Side: Progress -->
            <div class="card">
                <h3 class="card-title">📊 Progress</h3>
                <div class="progress-section">
                    <div class="progress-ring-container">
                        <svg width="160" height="160">
                            <defs>
                                <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                                    <stop offset="0%" stop-color="#3b82f6" />
                                    <stop offset="100%" stop-color="#06b6d4" />
                                </linearGradient>
                            </defs>
                            <circle class="progress-ring-circle-bg" cx="80" cy="80" r="70" />
                            <circle id="progress-circle" class="progress-ring-circle" cx="80" cy="80" r="70" stroke-dasharray="439.82" stroke-dashoffset="439.82" />
                        </svg>
                        <div class="progress-text">
                            <span id="progress-value">0%</span>
                            <span class="progress-subtext">Done</span>
                        </div>
                    </div>
                    
                    <div class="meta-row">
                        <div class="meta-item">
                            <div id="meta-completed" class="meta-val">0</div>
                            <div class="meta-lbl">Completed</div>
                        </div>
                        <div class="meta-item" style="border-left: 1px solid rgba(255,255,255,0.04); border-right: 1px solid rgba(255,255,255,0.04); padding: 0 15px;">
                            <div id="meta-current" class="meta-val" style="font-size: 11px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">None</div>
                            <div class="meta-lbl">Active Task</div>
                        </div>
                        <div class="meta-item">
                            <div id="meta-total" class="meta-val">0</div>
                            <div class="meta-lbl">Total Tasks</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Right Side: Syllabus Timeline -->
            <div class="card" style="display: flex; flex-direction: column;">
                <h3 class="card-title">📋 Traversal Plan</h3>
                <div id="timeline-list" class="timeline">
                    <div style="text-align: center; color: var(--text-secondary); margin-top: 50px;">Waiting for syllabus nodes data...</div>
                </div>
            </div>

            <!-- Bottom: Console Output -->
            <div class="card console-card">
                <h3 class="card-title">📟 Live Execution Terminal</h3>
                <div id="console-output" class="console-box">Initializing console hook...</div>
            </div>
        </div>
    </div>

    <script>
        const circle = document.getElementById('progress-circle');
        const radius = circle.r.baseVal.value;
        const circumference = radius * 2 * Math.PI;

        function setProgress(percent) {
            const offset = circumference - (percent / 100) * circumference;
            circle.style.strokeDashoffset = offset;
            document.getElementById('progress-value').textContent = `${percent}%`;
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                // Update Course and status badge
                document.getElementById('course-name-header').textContent = `Course: ${data.course_id}`;
                const badge = document.getElementById('bot-status-badge');
                const text = document.getElementById('status-text');
                
                text.textContent = data.status;
                if (data.status === 'RUNNING') {
                    badge.className = 'status-badge badge-running';
                } else {
                    badge.className = 'status-badge badge-idle';
                }

                // Update Progress Ring and stats
                setProgress(data.progress_percent);
                document.getElementById('meta-completed').textContent = data.completed_count;
                document.getElementById('meta-total').textContent = data.total_count;
                
                let currentTxt = 'Idle';
                if (data.current_node !== 'None') {
                    const activeNode = data.syllabus_nodes.find(n => n.id === data.current_node);
                    currentTxt = activeNode ? (activeNode.name || activeNode.id) : data.current_node;
                }
                const currentEl = document.getElementById('meta-current');
                currentEl.textContent = currentTxt;
                currentEl.title = currentTxt;

                // Update Timeline List
                const timeline = document.getElementById('timeline-list');
                timeline.innerHTML = '';
                
                if (data.syllabus_nodes && data.syllabus_nodes.length > 0) {
                    data.syllabus_nodes.forEach(node => {
                        const isCompleted = data.completed_nodes.includes(node.id);
                        const isActive = data.current_node === node.id;
                        
                        let statusClass = 'status-pending';
                        let statusText = 'Pending';
                        let itemClass = '';
                        
                        if (isCompleted) {
                            statusClass = 'status-completed';
                            statusText = 'Completed';
                            itemClass = 'completed';
                        } else if (isActive) {
                            statusClass = 'status-active';
                            statusText = 'Active';
                            itemClass = 'active';
                        }

                        // Determine Icon
                        let icon = '📄';
                        if (node.type === 'video') icon = '🎥';
                        else if (node.type === 'reading') icon = '📖';
                        else if (node.type === 'quiz') icon = '✏️';
                        else if (node.type === 'lab') icon = '💻';
                        else if (node.type === 'peer') icon = '👥';

                        const div = document.createElement('div');
                        div.className = `timeline-item ${itemClass}`;
                        div.innerHTML = `
                            <div class="node-info">
                                <div class="node-icon">${icon}</div>
                                <div>
                                    <div class="node-name">${node.name || node.id}</div>
                                    <div class="node-meta">${node.module_name || 'Module'} • ${node.type}</div>
                                </div>
                            </div>
                            <span class="node-status-label ${statusClass}">${statusText}</span>
                        `;
                        timeline.appendChild(div);
                    });
                } else {
                    timeline.innerHTML = '<div style="text-align: center; color: var(--text-secondary); margin-top: 50px;">Waiting for syllabus nodes data...</div>';
                }

                // Update Console Log
                const consoleBox = document.getElementById('console-output');
                consoleBox.innerHTML = '';
                
                if (data.logs && data.logs.length > 0) {
                    data.logs.forEach(line => {
                        const span = document.createElement('span');
                        span.style.display = 'block';
                        span.style.marginBottom = '2px';
                        
                        let colorClass = 'log-default';
                        if (line.includes('[SUCCESS]')) colorClass = 'log-success';
                        else if (line.includes('[WARNING]')) colorClass = 'log-warning';
                        else if (line.includes('[ERROR]')) colorClass = 'log-error';
                        else if (line.includes('[INFO]') || line.includes('[ENGINE]')) colorClass = 'log-info';
                        
                        span.className = colorClass;
                        span.textContent = line;
                        consoleBox.appendChild(span);
                    });
                    
                    // Auto scroll to bottom
                    consoleBox.scrollTop = consoleBox.scrollHeight;
                } else {
                    consoleBox.innerHTML = 'Console logs are empty.';
                }
            } catch (err) {
                console.error("Dashboard fetch error:", err);
            }
        }

        // Poll every 2 seconds
        setInterval(fetchStatus, 2000);
        fetchStatus();
    </script>
</body>
</html>
"""

class ACCCEHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_data = get_db_status()
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
        elif self.path == "/api/debug":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            debug_info = {
                "cwd": os.getcwd(),
                "__file__": __file__,
                "db_path": DB_PATH,
                "db_exists": os.path.exists(DB_PATH),
                "db_status": get_db_status()
            }
            self.wfile.write(json.dumps(debug_info).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def main():
    print(f"Starting Project ACCCE Web Dashboard Server...")
    handler = ACCCEHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"SUCCESS: Dashboard live at http://127.0.0.1:{PORT}")
        print("Keep this script running and open the link in your web browser to monitor progress!")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard server terminated.")

if __name__ == "__main__":
    main()
