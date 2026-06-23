import os
import uuid
import secrets
import decimal
import logging
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List
from fastapi import FastAPI, Header, HTTPException, status, Request
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field, EmailStr
import httpx

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("licensing_server")

# Trusted proxy whitelist for rate-limiting extraction security
TRUSTED_PROXIES = {"127.0.0.1", "::1", "localhost", "testserver", "testclient"}
trusted_env = os.getenv("TRUSTED_PROXIES")
if trusted_env:
    TRUSTED_PROXIES.update(ip.strip() for ip in trusted_env.split(","))

class WebTrialRequest(BaseModel):
    email: EmailStr = Field(..., description="Validated user email address")

class PurchaseRequest(BaseModel):
    email: EmailStr

class StatusRequest(BaseModel):
    key: str = Field(..., description="Target licensing API key")

class LockTrialRequest(BaseModel):
    key: str = Field(..., description="Target licensing API key")
    course_id: str = Field(..., description="Target course ID string")
    module_index: int = Field(..., description="1-based module index")

def get_client_ip(request: Request) -> str:
    remote_host = request.client.host if request.client else "127.0.0.1"
    if remote_host not in TRUSTED_PROXIES:
        return remote_host

    for header in ["cf-connecting-ip", "x-real-ip"]:
        val = request.headers.get(header)
        if val:
            return val.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return remote_host


app = FastAPI(title="ACCCE Gated Map Server", version="1.0.0")

# Database Setup: Supports PostgreSQL (via Supabase/Render) or fallback to local SQLite
DATABASE_URL = os.getenv("DATABASE_URL")
MASTER_WALLET = os.getenv("MASTER_WALLET_ADDRESS", "0x0000000000000000000000000000000000000000").lower()
POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
USDT_POLYGON_CONTRACT = "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"

# Dynamic selector map for Coursera layout elements
COURSERA_LAYOUT_MAP = {
    "video_player": "video",
    "mark_completed": "button:has-text('Mark as completed'), button:has-text('Mark as Completed'), button:has-text('I understand'), button:has-text('I Understand'), [data-testid='mark-complete-button'], .mark-complete-button",
    "quiz_container": "div[data-testid^='part-Submission_'], .rc-Option, .rc-FormQuestion, .question-container, .rc-Form, [data-testid='question-prompt'], .css-k008qs, form[data-testid]",
    "start_quiz_button": "button:has-text('Start'), button:has-text('Resume'), button:has-text('Retake'), button:has-text('Try again'), button:has-text('Continue'), button:has-text('Start Assignment'), button:has-text('Retake Quiz'), a:has-text('Start'), a:has-text('Start Quiz'), a:has-text('Resume'), a:has-text('Try again'), a:has-text('Retake'), a:has-text('Retake Quiz')",
    "submit_quiz_button": "button:has-text('Submit'), button:has-text('Submit Quiz')",
    "text_inputs": "textarea, input[type='text']",
    "choice_inputs": "input[type='checkbox'], input[type='radio']",
    "agreement_checkbox": "input[type='checkbox']#honor-code-checkbox, input[type='checkbox'][name='honor-code'], label:has-text('Honor Code') input, input#agreement-checkbox, input#agreement-checkbox-base, input[type='checkbox']#agreement-checkbox-base, input[type='checkbox']",
    "modal_dialog": ".rc-Modal, .cds-dialog",
    "modal_close_button": "button:has-text('Continue'), button:has-text('Start Quiz'), button:has-text('Start attempt'), button:has-text('Start Attempt'), button:has-text('I agree'), button:has-text('I Agree'), button:has-text('Start Assignment'), button:has-text('Agree and Continue'), a:has-text('Continue'), a:has-text('Start Quiz'), a:has-text('Start attempt'), a:has-text('Start Attempt'), a:has-text('I agree'), a:has-text('I Agree'), a:has-text('Start Assignment'), a:has-text('Agree and Continue'), button[aria-label='Close'], button:has-text('OK'), button:has-text('Close')",
    "enroll_button": "button:text-is('Enroll for free'), button:text-is('Enroll'), a:text-is('Enroll for free'), a:text-is('Enroll')",
    "enroll_modal_button": "button:has-text('Go to course'), button:has-text('Go to Course'), button:has-text('Enroll'), button:has-text('Start learning'), button:has-text('Continue')"
}

# Db connection abstraction
is_postgres = False

if DATABASE_URL and DATABASE_URL.startswith("postgres"):
    import psycopg2
    import psycopg2.extras
    is_postgres = True
    logger.info("Database: Using PostgreSQL (Supabase/Render)")
else:
    import sqlite3
    logger.info("Database: Using SQLite (Local)")

def get_db():
    if is_postgres:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        return conn
    else:
        conn = sqlite3.connect("server_licensing.db")
        conn.row_factory = sqlite3.Row
        return conn

def get_cursor(conn):
    if is_postgres:
        return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    else:
        return conn.cursor()

def parse_iso_datetime(dt_str: str) -> datetime:
    """Helper to parse datetime strings from SQLite database."""
    # SQLite datetimes might have trailing Z or spaces
    dt_str = dt_str.replace("Z", "+00:00")
    if " " in dt_str and "+" not in dt_str:
        dt_str = dt_str.replace(" ", "T") + "+00:00"
    return datetime.fromisoformat(dt_str)

# Initialize tables
def init_db():
    conn = get_db()
    cursor = get_cursor(conn)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                api_key TEXT PRIMARY KEY,
                expires_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
                assigned_amount NUMERIC(8, 4) DEFAULT 0.0000 NOT NULL,
                is_trial BOOLEAN DEFAULT FALSE NOT NULL,
                device_id TEXT,
                discord_id TEXT,
                email TEXT,
                ip_address TEXT,
                payment_assigned_at TIMESTAMP WITH TIME ZONE,
                trial_locked_course_id TEXT DEFAULT NULL,
                trial_locked_module_index INTEGER DEFAULT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS payments (
                tx_hash TEXT PRIMARY KEY,
                api_key TEXT REFERENCES users(api_key),
                amount NUMERIC(12, 4) NOT NULL,
                network TEXT NOT NULL,
                processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Auto-migrate schema changes for existing tables
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_trial BOOLEAN DEFAULT FALSE NOT NULL;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS device_id TEXT;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS discord_id TEXT;")
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                api_key TEXT PRIMARY KEY,
                expires_at TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
                assigned_amount REAL DEFAULT 0.0000 NOT NULL,
                is_trial INTEGER DEFAULT 0 NOT NULL,
                device_id TEXT,
                discord_id TEXT,
                email TEXT,
                ip_address TEXT,
                payment_assigned_at TEXT,
                trial_locked_course_id TEXT DEFAULT NULL,
                trial_locked_module_index INTEGER DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                tx_hash TEXT PRIMARY KEY,
                api_key TEXT REFERENCES users(api_key),
                amount REAL NOT NULL,
                network TEXT NOT NULL,
                processed_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Insert a default demo token (active for the next 10 minutes)
        init_expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO users (api_key, expires_at) VALUES ('test-demo-key-12345', ?);
        """, (init_expiry,))

    # Safe Try-Except Migrations
    migrations = [
        ("email", "TEXT"),
        ("ip_address", "TEXT"),
        ("payment_assigned_at", "TIMESTAMP WITH TIME ZONE" if is_postgres else "TEXT"),
        ("trial_locked_course_id", "TEXT"),
        ("trial_locked_module_index", "INTEGER")
    ]
    for col, col_type in migrations:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except Exception as e:
            logger.debug(f"Column {col} change skipped: {e}")

    conn.commit()
    conn.close()

init_db()

def allocate_unique_salt(cursor, is_postgres: bool, window_minutes: int = 60) -> decimal.Decimal:
    base_price = decimal.Decimal("3.0000")
    now_utc = datetime.now(timezone.utc)
    expiration_cutoff = now_utc - timedelta(minutes=window_minutes)
    
    pg_cutoff = expiration_cutoff
    sqlite_cutoff = expiration_cutoff.strftime("%Y-%m-%d %H:%M:%S")

    for _ in range(500):
        salt = secrets.randbelow(9999) + 1
        assigned_amount = base_price + (decimal.Decimal(salt) / decimal.Decimal("10000"))
        
        if is_postgres:
            query = """
                SELECT 1 FROM users 
                WHERE assigned_amount = %s 
                  AND assigned_amount > 0.0 
                  AND payment_assigned_at > %s 
                LIMIT 1
            """
            cursor.execute(query, (assigned_amount, pg_cutoff))
        else:
            query = """
                SELECT 1 FROM users 
                WHERE assigned_amount = ? 
                  AND assigned_amount > 0.0 
                  AND payment_assigned_at > ? 
                LIMIT 1
            """
            cursor.execute(query, (float(assigned_amount), sqlite_cutoff))
            
        if not cursor.fetchone():
            return assigned_amount
            
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="All temporary payment parameters are currently reserved. Please retry shortly."
    )


@app.get("/", response_class=HTMLResponse)
def read_root():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    index_path = os.path.join(base_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("{{MASTER_WALLET_ADDRESS}}", MASTER_WALLET)
        return HTMLResponse(content=content)
    return HTMLResponse(content="<h1>ACCCE licensing server is operational.</h1>")

@app.post("/api/v1/web/trial")
async def claim_web_trial(
    payload: WebTrialRequest,
    request: Request,
    x_device_id: Optional[str] = Header(None)
):
    email = payload.email.strip().lower()
    client_ip = get_client_ip(request)
    
    if not x_device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Device-ID header. Trial keys can only be claimed directly from the desktop application."
        )
        
    device_id = x_device_id.strip().lower()
    
    conn = get_db()
    cursor = get_cursor(conn)
    
    try:
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)
        
        # 1. Check IP rate-limiting in the last 24h
        if is_postgres:
            cursor.execute(
                "SELECT 1 FROM users WHERE ip_address = %s AND is_trial = TRUE AND created_at > %s LIMIT 1",
                (client_ip, cutoff_24h)
            )
        else:
            cursor.execute(
                "SELECT 1 FROM users WHERE ip_address = ? AND is_trial = 1 AND created_at > ? LIMIT 1",
                (client_ip, cutoff_24h.isoformat())
            )
            
        if cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This IP address has already generated a free trial in the last 24 hours."
            )
            
        # 2. Check if email has ever claimed a trial
        if is_postgres:
            cursor.execute("SELECT 1 FROM users WHERE email = %s AND is_trial = TRUE LIMIT 1", (email,))
        else:
            cursor.execute("SELECT 1 FROM users WHERE email = ? AND is_trial = 1 LIMIT 1", (email,))
            
        if cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This email address has already claimed a free trial."
            )
            
        # 3. Check if this device ID has ever claimed a trial
        if is_postgres:
            cursor.execute("SELECT 1 FROM users WHERE is_trial = TRUE AND device_id = %s LIMIT 1", (device_id,))
        else:
            cursor.execute("SELECT 1 FROM users WHERE is_trial = 1 AND device_id = ? LIMIT 1", (device_id,))
            
        if cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This computer hardware configuration has already claimed an active free trial."
            )
            
        # 4. Create fresh 24-hour trial key
        trial_key = f"trial-web-{uuid.uuid4().hex[:12]}"
        expiry_time = now + timedelta(hours=24)
        
        if is_postgres:
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, is_trial, device_id, email, ip_address, created_at) VALUES (%s, %s, TRUE, %s, %s, %s, %s)",
                (trial_key, expiry_time, device_id, email, client_ip, now)
            )
        else:
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, is_trial, device_id, email, ip_address, created_at) VALUES (?, ?, 1, ?, ?, ?, ?)",
                (trial_key, expiry_time.isoformat(), device_id, email, client_ip, now.isoformat())
            )
        conn.commit()
        
        return {
            "success": True,
            "key": trial_key,
            "expires_at": expiry_time.isoformat()
        }
    finally:
        conn.close()

@app.post("/api/v1/web/trial/lock")
async def lock_trial_module(payload: LockTrialRequest):
    conn = get_db()
    cursor = get_cursor(conn)
    try:
        if is_postgres:
            cursor.execute("SELECT is_trial, trial_locked_course_id, trial_locked_module_index FROM users WHERE api_key = %s", (payload.key,))
        else:
            cursor.execute("SELECT is_trial, trial_locked_course_id, trial_locked_module_index FROM users WHERE api_key = ?", (payload.key,))
            
        record = cursor.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="Trial key not found.")
            
        is_trial_val = record[0]
        locked_course = record[1]
        locked_module = record[2]
        
        if not is_trial_val:
            # Full license keys are not restricted
            return {"success": True, "message": "Full license key. No lock required."}
            
        if locked_course is not None:
            if locked_course != payload.course_id or locked_module != payload.module_index:
                raise HTTPException(
                    status_code=403,
                    detail=f"This trial key is already locked to Course '{locked_course}', Module {locked_module}."
                )
            return {"success": True, "message": "Valid matching trial allocation."}
            
        # First time running: permanently lock key to this course and module
        if is_postgres:
            cursor.execute(
                "UPDATE users SET trial_locked_course_id = %s, trial_locked_module_index = %s WHERE api_key = %s",
                (payload.course_id, payload.module_index, payload.key)
            )
        else:
            cursor.execute(
                "UPDATE users SET trial_locked_course_id = ?, trial_locked_module_index = ? WHERE api_key = ?",
                (payload.course_id, payload.module_index, payload.key)
            )
        conn.commit()
        return {"success": True, "message": "Trial key successfully locked to this module."}
    finally:
        conn.close()

class PurchaseClaimRequest(BaseModel):
    email: EmailStr = Field(..., description="Target user email address")
    tx_hash: str = Field(..., description="Polygon transaction hash string")

def hex_to_int(h: str) -> int:
    return int(h, 16)

async def verify_polygon_payment(tx_hash: str) -> dict:
    # Sandbox check: Allow a specific mock hash if ALLOW_MOCK_PAYMENT is enabled in env
    allow_mock = os.getenv("ALLOW_MOCK_PAYMENT", "false").strip().lower() == "true"
    mock_hash = "0x" + "9" * 64
    if allow_mock and tx_hash.lower() == mock_hash.lower():
        logger.info(f"Sandbox Mode active. Mock transaction hash accepted: {tx_hash}")
        return {"success": True, "status": "SUCCESS"}

    # Use the RPC URL defined globally
    async with httpx.AsyncClient() as client:
        # 1. Fetch Transaction Receipt
        receipt_payload = {
            "jsonrpc": "2.0",
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
            "id": 1
        }
        try:
            r = await client.post(POLYGON_RPC_URL, json=receipt_payload, timeout=15)
            res = r.json().get("result")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to connect to Polygon RPC node: {e}")
            
        if not res:
            return {"success": False, "status": "NOT_MINED"}
            
        # Verify transaction status (1 = Success, 0 = Failure)
        status_val = res.get("status")
        if not status_val or hex_to_int(status_val) != 1:
            raise HTTPException(status_code=400, detail="Target transaction execution failed on-chain.")

        # 2. Block Confirmation Depth (Re-org mitigation)
        tx_block = hex_to_int(res.get("blockNumber"))
        
        block_payload = {
            "jsonrpc": "2.0",
            "method": "eth_blockNumber",
            "params": [],
            "id": 2
        }
        try:
            br = await client.post(POLYGON_RPC_URL, json=block_payload, timeout=15)
            current_block = hex_to_int(br.json().get("result"))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch current block height from RPC: {e}")
            
        if (current_block - tx_block) < 5:
            return {
                "success": False,
                "status": "PENDING_CONFIRMATIONS",
                "current": current_block - tx_block,
                "required": 5
            }

        # 3. Retrieve block timestamp to validate 24h window
        get_block_payload = {
            "jsonrpc": "2.0",
            "method": "eth_getBlockByNumber",
            "params": [res.get("blockNumber"), False],
            "id": 3
        }
        try:
            b_res = await client.post(POLYGON_RPC_URL, json=get_block_payload, timeout=15)
            block_data = b_res.json().get("result")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to retrieve block details: {e}")
            
        if not block_data or not block_data.get("timestamp"):
            raise HTTPException(status_code=502, detail="Block timestamp details are missing from RPC response.")
            
        tx_time = hex_to_int(block_data.get("timestamp")) # Unix epoch format
        
        import time
        if (time.time() - tx_time) > 86400:
            raise HTTPException(status_code=400, detail="Transaction was executed more than 24 hours ago.")

        # 4. Parse Logs for strict emitter and recipient matching
        TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        valid_payment_found = False
        
        for log in res.get("logs", []):
            # Check contract address (USDT contract address strictly)
            if log.get("address", "").lower() != USDT_POLYGON_CONTRACT.lower():
                continue
                
            topics = log.get("topics", [])
            if not topics or topics[0].lower() != TRANSFER_EVENT_TOPIC:
                continue
                
            if len(topics) >= 3:
                # Strip 64-char hex block to get 40-char standard address
                recipient = f"0x{topics[2][-40:]}".lower()
                if recipient == MASTER_WALLET.lower():
                    # Parse value from data field (USDT has 6 decimals)
                    value = hex_to_int(log.get("data", "0x0"))
                    if value >= 3000000: # 3.00 USDT
                        valid_payment_found = True
                        break
                        
        if not valid_payment_found:
            raise HTTPException(
                status_code=400,
                detail=f"No successful USDT transfer of at least 3.00 USDT to destination wallet '{MASTER_WALLET}' was found in this transaction."
            )
            
        return {"success": True, "status": "SUCCESS"}

@app.post("/api/v1/web/claim-purchase")
async def claim_purchase(payload: PurchaseClaimRequest):
    email = payload.email.strip().lower()
    tx_hash = payload.tx_hash.strip().lower()
    
    # Strict regex validation to ensure tx_hash is valid 64-char hex block
    if not re.match(r"^0x[a-fA-F0-9]{64}$", tx_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed transaction hash format. Must be a 64-character hexadecimal string starting with 0x."
        )
        
    conn = get_db()
    cursor = get_cursor(conn)
    
    try:
        # Check if this tx_hash has already been registered (double-spend check)
        if is_postgres:
            cursor.execute("SELECT api_key FROM payments WHERE tx_hash = %s LIMIT 1", (tx_hash,))
        else:
            cursor.execute("SELECT api_key FROM payments WHERE tx_hash = ? LIMIT 1", (tx_hash,))
            
        if cursor.fetchone():
            raise HTTPException(status_code=403, detail="This transaction has already been claimed.")
            
        # Perform on-chain transaction checks
        verification_result = await verify_polygon_payment(tx_hash)
        if not verification_result.get("success", False):
            return JSONResponse(status_code=202, content=verification_result)
        
        # Generate new active 30-day license key
        license_key = f"license-web-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=30)
        
        # Insert new user and payment records
        expiry_val = expires_at if is_postgres else expires_at.isoformat()
        now_val = now if is_postgres else now.isoformat()
        
        if is_postgres:
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, is_trial, email, created_at) VALUES (%s, %s, FALSE, %s, %s)",
                (license_key, expiry_val, email, now_val)
            )
            cursor.execute(
                "INSERT INTO payments (tx_hash, api_key, amount, network) VALUES (%s, %s, 3.0, %s)",
                (tx_hash, license_key, "polygon")
            )
        else:
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, is_trial, email, created_at) VALUES (?, ?, 0, ?, ?)",
                (license_key, expiry_val, email, now_val)
            )
            cursor.execute(
                "INSERT INTO payments (tx_hash, api_key, amount, network) VALUES (?, ?, 3.0, ?)",
                (tx_hash, license_key, "polygon")
            )
        conn.commit()
        
        logger.info(f"Purchase Claim Success! Tx {tx_hash} verified. Generated new active key {license_key} for {email}.")
        
        return {
            "success": True,
            "key": license_key,
            "expires_at": expires_at.isoformat()
        }
    finally:
        conn.close()

@app.post("/api/v1/web/status")
async def get_web_key_status(
    payload: StatusRequest,
    x_device_id: Optional[str] = Header(None)
):
    conn = get_db()
    cursor = get_cursor(conn)
    
    try:
        if is_postgres:
            cursor.execute("SELECT expires_at, assigned_amount, payment_assigned_at, is_trial, device_id FROM users WHERE api_key = %s", (payload.key,))
        else:
            cursor.execute("SELECT expires_at, assigned_amount, payment_assigned_at, is_trial, device_id FROM users WHERE api_key = ?", (payload.key,))
            
        record = cursor.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="Licensing key not found.")
            
        expires_at_val = record["expires_at"]
        assigned_amount_val = record["assigned_amount"]
        payment_assigned_at_val = record["payment_assigned_at"]
        is_trial_val = record["is_trial"] if is_postgres else record[3]
        device_id_val = record["device_id"] if is_postgres else record[4]
        
        # Enforce device-id check on trial keys during status queries
        if is_trial_val:
            if not x_device_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing X-Device-ID header for trial key verification."
                )
            
            device_id = x_device_id.strip().lower()
            if not device_id_val:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Corrupt server state: Trial key lacks an authenticated device lock sequence."
                )
            
            if device_id_val.strip().lower() != device_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Security Violation: License key signature is locked to alternative hardware parameters."
                )
                
        now = datetime.now(timezone.utc)
        
        if is_postgres:
            expires_at = expires_at_val
        else:
            expires_at = parse_iso_datetime(expires_at_val)
            
        if expires_at > now:
            return {
                "success": True,
                "status": "active",
                "expires_at": expires_at.isoformat()
            }
            
        # If expired, check if they have a pending salt that is still within the 60-min window
        if float(assigned_amount_val) > 0.0 and payment_assigned_at_val:
            if is_postgres:
                assigned_at = payment_assigned_at_val
            else:
                assigned_at = parse_iso_datetime(payment_assigned_at_val)
                
            elapsed = now - assigned_at
            if elapsed < timedelta(minutes=60):
                remaining_seconds = max(0, int(3600 - elapsed.total_seconds()))
                return {
                    "success": True,
                    "status": "payment_required",
                    "amount": float(assigned_amount_val),
                    "destination_address": MASTER_WALLET,
                    "chain": "polygon",
                    "expires_in_seconds": remaining_seconds
                }
                
        return {
            "success": True,
            "status": "expired",
            "message": "Payment session expired. Please re-purchase or refresh through the Buy License tab to generate a new active invoice."
        }
    finally:
        conn.close()

@app.get("/api/v1/layout-map")
def get_layout_map(
    x_api_key: Optional[str] = Header(None),
    x_device_id: Optional[str] = Header(None)
):
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-API-Key header.")
        
    conn = get_db()
    cursor = get_cursor(conn)
    
    if is_postgres:
        cursor.execute("SELECT * FROM users WHERE api_key = %s", (x_api_key,))
    else:
        cursor.execute("SELECT * FROM users WHERE api_key = ?", (x_api_key,))
        
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API Key.")
        
    is_trial_val = user["is_trial"] if is_postgres else user[3]
    device_id_val = user["device_id"] if is_postgres else user[4]
    
    # Enforce device-id check on trial keys
    if is_trial_val:
        if not x_device_id:
            conn.close()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-Device-ID header for trial key.")
            
        device_id = x_device_id.strip().lower()
        
        # Trial keys must always be pre-locked under the new model
        if not device_id_val:
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Corrupt server state: Trial key lacks an authenticated device lock sequence."
            )
            
        if device_id_val.strip().lower() != device_id:
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Security Violation: License key signature is locked to alternative hardware parameters."
            )

    # Check if subscription is active
    raw_expiry = user["expires_at"] if is_postgres else user[1]
    
    if is_postgres:
        expires_at = raw_expiry
    else:
        expires_at = parse_iso_datetime(raw_expiry)
        
    now = datetime.now(timezone.utc)
    
    if expires_at > now:
        conn.close()
        logger.info(f"Authorized access for key {x_api_key}. Subscription active until: {expires_at}")
        return {
            "status": "authorized",
            "subscription_expires_at": expires_at.isoformat(),
            "layout_map": COURSERA_LAYOUT_MAP
        }
        
    # If expired, generate a unique payment salt for $3 USD with 60 minutes TTL
    assigned_amount = user["assigned_amount"]
    payment_assigned_at_val = user["payment_assigned_at"]
    
    needs_new_salt = False
    if float(assigned_amount) <= 0.0:
        needs_new_salt = True
    elif payment_assigned_at_val:
        if is_postgres:
            assigned_at = payment_assigned_at_val
        else:
            assigned_at = parse_iso_datetime(payment_assigned_at_val)
        if datetime.now(timezone.utc) - assigned_at > timedelta(minutes=60):
            needs_new_salt = True
    else:
        needs_new_salt = True

    if needs_new_salt:
        assigned_amount = allocate_unique_salt(cursor, is_postgres)
        now_val = datetime.now(timezone.utc)
        if is_postgres:
            cursor.execute(
                "UPDATE users SET assigned_amount = %s, payment_assigned_at = %s WHERE api_key = %s",
                (assigned_amount, now_val, x_api_key)
            )
        else:
            cursor.execute(
                "UPDATE users SET assigned_amount = ?, payment_assigned_at = ? WHERE api_key = ?",
                (float(assigned_amount), now_val.strftime("%Y-%m-%d %H:%M:%S"), x_api_key)
            )
        conn.commit()
        
    conn.close()
    
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={
            "status": "payment_required",
            "message": "Subscription expired. Please subscribe to unlock unlimited runs for 1 month.",
            "payment_details": {
                "destination_address": MASTER_WALLET,
                "amount": float(assigned_amount),
                "suggested_chain": "polygon",
                "token": "USDT"
            }
        }
    )

# Blockchain transaction polling check
async def check_polygon_payments():
    if not MASTER_WALLET or MASTER_WALLET == "0x0000000000000000000000000000000000000000":
        logger.warning("Blockchain Listener: MASTER_WALLET_ADDRESS not configured. Payment auto-reload disabled.")
        return

    logger.info(f"Blockchain Listener: Monitoring wallet {MASTER_WALLET} on Polygon chain...")
    
    padded_wallet = "0x" + MASTER_WALLET[2:].zfill(64)
    transfer_event_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

    async with httpx.AsyncClient() as client:
        while True:
            try:
                rpc_payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_getLogs",
                    "params": [{
                        "address": USDT_POLYGON_CONTRACT,
                        "topics": [transfer_event_topic, None, padded_wallet],
                        "fromBlock": "latest"
                    }],
                    "id": 1
                }
                response = await client.post(POLYGON_RPC_URL, json=rpc_payload, timeout=10)
                if response.status_code == 200:
                    result = response.json().get("result", [])
                    for log in result:
                        tx_hash = log.get("transactionHash")
                        raw_data = log.get("data")
                        amount_int = int(raw_data, 16)
                        amount_usdt = decimal.Decimal(amount_int) / decimal.Decimal("1000000")
                        
                        await process_payment(tx_hash, amount_usdt)
            except Exception as e:
                logger.error(f"Blockchain Listener Error: {e}")
            await asyncio.sleep(20)

async def process_payment(tx_hash: str, amount: decimal.Decimal):
    conn = get_db()
    cursor = get_cursor(conn)
    
    try:
        # Check if transaction was already processed
        if is_postgres:
            cursor.execute("SELECT 1 FROM payments WHERE tx_hash = %s", (tx_hash,))
        else:
            cursor.execute("SELECT 1 FROM payments WHERE tx_hash = ?", (tx_hash,))
            
        if cursor.fetchone():
            return
            
        # Find user with matching assigned amount and active lock window (60 minutes)
        expiration_cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)
        amount_float = float(amount)
        if is_postgres:
            cursor.execute("""
                SELECT api_key, expires_at FROM users 
                WHERE assigned_amount = %s 
                  AND payment_assigned_at > %s
            """, (amount, expiration_cutoff))
        else:
            cursor.execute("""
                SELECT api_key, expires_at FROM users 
                WHERE assigned_amount = ? 
                  AND payment_assigned_at > ?
            """, (amount_float, expiration_cutoff.strftime("%Y-%m-%d %H:%M:%S")))
            
        matched_user = cursor.fetchone()
        if matched_user:
            api_key = matched_user["api_key"] if is_postgres else matched_user[0]
            raw_expiry = matched_user["expires_at"] if is_postgres else matched_user[1]
            
            if is_postgres:
                current_expiry = raw_expiry
            else:
                current_expiry = parse_iso_datetime(raw_expiry)
                
            now = datetime.now(timezone.utc)
            # If currently active, extend subscription. Otherwise, set expiry to 30 days from now.
            start_time = current_expiry if current_expiry > now else now
            new_expiry = start_time + timedelta(days=30)
            
            logger.info(f"Payment Match! Tx {tx_hash} of {amount_float} USDT matched to API Key {api_key}. Extending subscription to {new_expiry.isoformat()}.")
            
            if is_postgres:
                cursor.execute("INSERT INTO payments (tx_hash, api_key, amount, network) VALUES (%s, %s, %s, %s)",
                               (tx_hash, api_key, amount, "polygon"))
                cursor.execute("UPDATE users SET expires_at = %s, assigned_amount = 0, is_trial = FALSE, device_id = NULL WHERE api_key = %s",
                               (new_expiry, api_key))
            else:
                cursor.execute("INSERT INTO payments (tx_hash, api_key, amount, network) VALUES (?, ?, ?, ?)",
                               (tx_hash, api_key, amount_float, "polygon"))
                cursor.execute("UPDATE users SET expires_at = ?, assigned_amount = 0, is_trial = 0, device_id = NULL WHERE api_key = ?",
                               (new_expiry.isoformat(), api_key))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed processing payment {tx_hash}: {e}")
    finally:
        conn.close()

# Start background worker and Discord Bot when running
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if DISCORD_BOT_TOKEN:
    import discord
    from discord.ext import commands
    import uuid
    
    intents = discord.Intents.default()
    intents.message_content = True
    discord_bot = commands.Bot(command_prefix="!", intents=intents)
    
    @discord_bot.event
    async def on_ready():
        logger.info(f"Discord Bot: Logged in as {discord_bot.user}!")
        
    @discord_bot.command(name="trial")
    async def claim_trial(ctx):
        discord_id = str(ctx.author.id)
        logger.info(f"Discord Bot: User {ctx.author} ({discord_id}) requested a trial key.")
        
        conn = get_db()
        cursor = get_cursor(conn)
        
        try:
            # Check if this Discord user already has a key
            if is_postgres:
                cursor.execute("SELECT api_key FROM users WHERE discord_id = %s", (discord_id,))
            else:
                cursor.execute("SELECT api_key FROM users WHERE discord_id = ?", (discord_id,))
                
            existing_user = cursor.fetchone()
            if existing_user:
                await ctx.reply("❌ You have already claimed your free trial!")
                return
                
            # Generate a new unique 24-hour trial key
            trial_key = f"trial-{uuid.uuid4().hex[:12]}"
            expiry_time = datetime.now(timezone.utc) + timedelta(hours=24)
            
            if is_postgres:
                cursor.execute(
                    "INSERT INTO users (api_key, expires_at, is_trial, discord_id) VALUES (%s, %s, TRUE, %s)",
                    (trial_key, expiry_time, discord_id)
                )
            else:
                cursor.execute(
                    "INSERT INTO users (api_key, expires_at, is_trial, discord_id) VALUES (?, ?, 1, ?)",
                    (trial_key, expiry_time.isoformat(), discord_id)
                )
            conn.commit()
            
            try:
                dm_message = (
                    f"🎉 **Your ACCCE 24-Hour Free Trial Key has been generated!**\n\n"
                    f"🔑 **Token**: `{trial_key}`\n"
                    f"⏰ **Expires in**: 24 Hours\n\n"
                    f"To use the bot, set this key as your `COURSERA_ENGINE_TOKEN` in your `.env` file.\n"
                    f"Once your trial expires, the bot will display instructions to extend it for 1 month for $3 USD."
                )
                await ctx.author.send(dm_message)
                await ctx.reply("✅ I have sent your 24-hour free trial key to your Direct Messages (DMs)!")
            except discord.Forbidden:
                await ctx.reply("❌ I could not DM you the key. Please temporarily enable 'Allow Direct Messages from Server Members' in your Discord settings, and try again!")
                # Delete key
                if is_postgres:
                    cursor.execute("DELETE FROM users WHERE api_key = %s", (trial_key,))
                else:
                    cursor.execute("DELETE FROM users WHERE api_key = ?", (trial_key,))
                conn.commit()
        except Exception as e:
            logger.error(f"Discord Bot error: {e}")
            await ctx.reply("❌ An internal error occurred while generating your trial key.")
        finally:
            conn.close()

async def start_discord_bot():
    try:
        logger.info("Discord Bot: Starting client...")
        await discord_bot.start(DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"Discord Bot failed to run: {e}")

@app.on_event("startup")
async def startup_event():
    if DISCORD_BOT_TOKEN:
        asyncio.create_task(start_discord_bot())
