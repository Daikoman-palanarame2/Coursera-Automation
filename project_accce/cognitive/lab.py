import json
import asyncio
import google.generativeai as genai
from typing import List, Dict, Any, Optional
from playwright.sync_api import Page
import websockets

class WebSocketLabClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url

    async def execute_command_async(self, cmd: str) -> Dict[str, Any]:
        """
        Connects directly to the intercepted container WebSocket endpoint
        and runs a shell command, returning output and exit status.
        """
        try:
            async with websockets.connect(self.ws_url) as ws:
                # Format payload to match container terminal specifications (e.g. Jupyter or VS Code shell API)
                payload = {
                    "header": {
                        "msg_id": "accce-cmd-execution",
                        "msg_type": "execute_request",
                        "version": "5.3"
                    },
                    "metadata": {},
                    "content": {
                        "code": cmd,
                        "silent": False,
                        "store_history": False,
                        "user_expressions": {},
                        "allow_stdin": False
                    },
                    "parent_header": {},
                    "channel": "shell"
                }
                
                await ws.send(json.dumps(payload))
                
                stdout = ""
                stderr = ""
                exit_code = 0
                
                # Listen to WebSocket messages until container is idle
                async for message in ws:
                    data = json.loads(message)
                    msg_type = data.get("header", {}).get("msg_type")
                    
                    if msg_type == "stream":
                        content = data.get("content", {})
                        if content.get("name") == "stdout":
                            stdout += content.get("text", "")
                        elif content.get("name") == "stderr":
                            stderr += content.get("text", "")
                            
                    elif msg_type == "execute_reply":
                        status = data.get("content", {}).get("status")
                        exit_code = 0 if status == "ok" else 1
                        break
                        
                return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}

    def execute_command(self, cmd: str) -> Dict[str, Any]:
        """Synchronous wrapper for async command execution."""
        return asyncio.run(self.execute_command_async(cmd))


def setup_lab_interceptor(page: Page) -> List[str]:
    """
    Registers network listeners in Playwright to intercept
    WebSocket URLs or shell authentication tokens.
    """
    ws_urls = []
    
    def on_websocket(ws):
        url = ws.url.lower()
        # Typical Jupyter/VS Code container socket patterns
        if "kernel" in url or "terminals" in url or "shell" in url:
            ws_urls.append(ws.url)
            
    page.on("websocket", on_websocket)
    return ws_urls


def run_closed_loop_lab_agent(
    client: WebSocketLabClient,
    api_key: str,
    ai_model: str,
    instructions: str = "",
    target_file: str = "",
    test_command: str = "",
    max_iterations: int = 5
) -> bool:
    """
    Agentic closed-loop debugger with automatic workspace discovery.
    """
    # Discovery Phase
    print("[LAB AGENT] Beginning workspace discovery...")
    
    # 1. List files in workspace (excluding node_modules)
    ls_res = client.execute_command("find . -maxdepth 3 -not -path '*/node_modules*' -not -path '*/.*'")
    files_list = ls_res.get("stdout", "").strip()
    print(f"[LAB AGENT] Workspace files found:\n{files_list}")
    
    # 2. Read README.md if present
    readme_content = ""
    readme_path = None
    for line in files_list.splitlines():
        if "readme.md" in line.lower():
            readme_path = line.strip()
            break
            
    if readme_path:
        print(f"[LAB AGENT] Reading lab instructions from {readme_path}...")
        readme_res = client.execute_command(f"cat {readme_path}")
        readme_content = readme_res.get("stdout", "")
        
    # 3. Read package.json if present
    pkg_content = ""
    for line in files_list.splitlines():
        if "package.json" in line.lower():
            pkg_res = client.execute_command(f"cat {line.strip()}")
            pkg_content = pkg_res.get("stdout", "")
            break
            
    # 4. Use LLM to analyze the workspace and determine parameters
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(ai_model)
    
    analysis_prompt = f"""
    Analyze the following Coursera lab workspace files and README instructions.
    
    Workspace Files:
    {files_list}
    
    README Content:
    {readme_content}
    
    package.json Content:
    {pkg_content}
    
    Determine:
    1. The target file path that contains the code we need to write or complete.
    2. The test execution command to verify if our code is correct (for example: "npm test" or "CI=true npm test" or "python -m pytest").
    3. The specific instructions of what we need to code.
    
    Return your response strictly in the following JSON format:
    {{
      "target_file": "src/App.js",
      "test_command": "CI=true npm test",
      "instructions": "Implement the components as described..."
    }}
    """
    
    try:
        response = model.generate_content(
            analysis_prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        discovery = json.loads(response.text)
        discovered_target_file = discovery.get("target_file", target_file or "src/App.js")
        discovered_test_command = discovery.get("test_command", test_command or "CI=true npm test")
        discovered_instructions = discovery.get("instructions", instructions or "Complete the lab requirements.")
        
        print(f"[LAB AGENT] Discovered Target File: {discovered_target_file}")
        print(f"[LAB AGENT] Discovered Test Command: {discovered_test_command}")
        print(f"[LAB AGENT] Discovered Instructions:\n{discovered_instructions}")
    except Exception as e:
        print(f"[LAB AGENT] Workspace analysis failed: {e}. Falling back to default parameters.")
        discovered_target_file = target_file or "src/App.js"
        discovered_test_command = test_command or "CI=true npm test"
        discovered_instructions = instructions or "Complete the lab requirements."
        
    # Read existing target file content
    current_content = ""
    if discovered_target_file:
        read_res = client.execute_command(f"cat {discovered_target_file}")
        if read_res["exit_code"] == 0:
            current_content = read_res["stdout"]
            print(f"[LAB AGENT] Read existing content of {discovered_target_file} (length: {len(current_content)} chars)")

    # Ensure test command is non-interactive (prevents watch mode hanging)
    if "npm" in discovered_test_command and "CI=" not in discovered_test_command:
        discovered_test_command = f"CI=true {discovered_test_command}"
        
    error_context = ""
    
    for i in range(max_iterations):
        print(f"[LAB AGENT] Starting iteration {i+1} of {max_iterations}...")
        
        prompt = f"""
        You are an autonomous software engineering agent tasked with completing a graded programming assignment.
        
        Instructions:
        {discovered_instructions}
        
        Target File: {discovered_target_file}
        Test Execution Command: {discovered_test_command}
        
        Original File Content:
        ```
        {current_content}
        ```
        
        Current Iteration: {i+1}
        Previous Errors/Feedback:
        {error_context if error_context else "None (Initial Attempt)"}
        
        Please generate the complete, updated code that must be written to {discovered_target_file}.
        Preserve any existing code structure, imports, and helper functions that are not meant to be changed.
        Do not wrap the code block in formatting like markdown unless it is clean raw file contents.
        Return your response strictly in JSON format matching the schema:
        {{
          "file_contents": "the actual code content..."
        }}
        """
        
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        try:
            data = json.loads(response.text)
            code = data.get("file_contents", "")
        except Exception as e:
            error_context = f"Failed to parse model response as JSON: {e}"
            continue
            
        # Write file inside lab container via shell
        # Escape single quotes in generated code
        escaped_code = code.replace("'", "'\\''")
        write_cmd = f"cat << 'EOF' > {discovered_target_file}\n{code}\nEOF"
        
        write_res = client.execute_command(write_cmd)
        if write_res["exit_code"] != 0:
            error_context = f"Failed to write code to file: {write_res['stderr']}"
            continue
            
        # Execute tests inside the container
        print(f"[LAB AGENT] Executing verification test: {discovered_test_command}")
        test_res = client.execute_command(discovered_test_command)
        
        print(f"  Test Exit Code: {test_res['exit_code']}")
        print(f"  Test Stdout: {test_res['stdout']}")
        print(f"  Test Stderr: {test_res['stderr']}")
        
        if test_res["exit_code"] == 0:
            print("[LAB AGENT] Success! All tests passed inside container.")
            return True
        else:
            # Capture error to feed back into model context next iteration
            error_context = f"Verification failed:\nStdout: {test_res['stdout']}\nStderr: {test_res['stderr']}"
            
    print("[LAB AGENT] Aborting. Maximum debug iterations exceeded without passing.")
    return False
