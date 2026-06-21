import json
import os
import urllib.request
import mimetypes
from typing import Optional, Dict, Any

def send_discord_notification(
    webhook_url: str,
    content: str,
    embed: Optional[Dict[str, Any]] = None,
    screenshot_path: Optional[str] = None
) -> bool:
    """
    Sends an alert notification to a Discord channel via Webhook.
    Supports uploading an optional verification screenshot.
    
    Args:
        webhook_url: Discord Webhook URL.
        content: Main text message content.
        embed: Optional dictionary defining a Discord Rich Embed.
        screenshot_path: Path to the screenshot file to upload.
        
    Returns:
        True if the request was successful, False otherwise.
    """
    if not webhook_url:
        print("[NOTIFIER] Warning: Discord Webhook URL is empty. Notification skipped.")
        return False

    try:
        # Prepare payload
        payload = {
            "content": content
        }
        if embed:
            payload["embeds"] = [embed]

        # If no screenshot is provided, send a clean JSON payload
        if not screenshot_path or not os.path.exists(screenshot_path):
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "ACCCE-Orchestrator/1.0"}
            )
            with urllib.request.urlopen(req) as response:
                return response.status in (200, 204)

        # If screenshot is provided, encode payload and file as multipart/form-data
        boundary = "----ACCCEMultipartBoundary" + os.urandom(16).hex()
        parts = []

        # Add JSON payload part
        parts.append(f"--{boundary}")
        parts.append('Content-Disposition: form-data; name="payload_json"')
        parts.append('Content-Type: application/json')
        parts.append('')
        parts.append(json.dumps(payload))

        # Add file part
        filename = os.path.basename(screenshot_path)
        mime_type, _ = mimetypes.guess_type(screenshot_path)
        mime_type = mime_type or "application/octet-stream"
        
        parts.append(f"--{boundary}")
        parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"')
        parts.append(f'Content-Type: {mime_type}')
        parts.append('')
        
        with open(screenshot_path, "rb") as f:
            file_bytes = f.read()
            
        # Join text parts and binary file
        body = b""
        for part in parts:
            if isinstance(part, str):
                body += part.encode("utf-8") + b"\r\n"
            else:
                body += part + b"\r\n"
        body += file_bytes + b"\r\n"
        body += f"--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "ACCCE-Orchestrator/1.0"
            }
        )
        
        with urllib.request.urlopen(req) as response:
            return response.status in (200, 204)

    except Exception as e:
        print(f"[NOTIFIER] Error sending Discord notification: {e}")
        return False
