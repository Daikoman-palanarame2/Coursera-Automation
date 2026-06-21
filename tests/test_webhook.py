import urllib.request
import json
import sys

webhook_url = "https://discord.com/api/webhooks/1515120868001579139/vl-9MBIWDrAZRgv1DsgDssNHV5izXQVPDMx80bSr0-6II9VqyvqDXBcFjzTd2PnG90v3"

payload = {
    "content": "🚀 **Project ACCCE Notifier Initialization**\nStealth browser environment and dependencies have been successfully installed on the target system. Gateway online.",
    "embeds": [{
        "title": "Initialization Complete",
        "description": "Waiting for Gemini API Key and Course ID configuration.",
        "color": 3066993
    }]
}

try:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "ACCCE-Orchestrator/1.0"}
    )
    with urllib.request.urlopen(req) as response:
        if response.status in (200, 204):
            print("Webhook test message sent successfully!")
        else:
            print(f"Failed to send webhook message. Status: {response.status}")
except Exception as e:
    print(f"Error sending webhook test message: {e}")
