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
TRUSTED_PROXIES = {"127.0.0.1", "::1", "localhost"}
trusted_env = os.getenv("TRUSTED_PROXIES")
if trusted_env:
    TRUSTED_PROXIES.update(ip.strip() for ip in trusted_env.split(","))

class WebTrialRequest(BaseModel):
    email: EmailStr = Field(..., description="Validated user email address")

class PurchaseRequest(BaseModel):
    email: EmailStr

class StatusRequest(BaseModel):
    key: str = Field(..., description="Target licensing API key")

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
        ("payment_assigned_at", "TIMESTAMP WITH TIME ZONE" if is_postgres else "TEXT")
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
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>ACCCE licensing server is operational.</h1>")

@app.post("/api/v1/web/trial")
async def claim_web_trial(payload: WebTrialRequest, request: Request):
    email = payload.email.strip().lower()
    client_ip = get_client_ip(request)
    
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
            
        # 3. Create fresh 3-hour trial key
        trial_key = f"trial-web-{uuid.uuid4().hex[:12]}"
        expiry_time = now + timedelta(hours=3)
        
        if is_postgres:
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, is_trial, email, ip_address, created_at) VALUES (%s, %s, TRUE, %s, %s, %s)",
                (trial_key, expiry_time, email, client_ip, now)
            )
        else:
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, is_trial, email, ip_address, created_at) VALUES (?, ?, 1, ?, ?, ?)",
                (trial_key, expiry_time.isoformat(), email, client_ip, now.isoformat())
            )
        conn.commit()
        
        return {
            "success": True,
            "key": trial_key,
            "expires_at": expiry_time.isoformat()
        }
    finally:
        conn.close()

@app.post("/api/v1/web/purchase")
async def initiate_purchase(payload: PurchaseRequest):
    email = payload.email.strip().lower()
    
    conn = get_db()
    cursor = get_cursor(conn)
    
    try:
        now = datetime.now(timezone.utc)
        
        # Allocate a unique salt within 60 min window
        assigned_amount = allocate_unique_salt(cursor, is_postgres)
        license_key = f"license-web-{uuid.uuid4().hex[:12]}"
        
        expiry = now if is_postgres else now.isoformat()
        assigned_at = now if is_postgres else now.strftime("%Y-%m-%d %H:%M:%S")
        
        if is_postgres:
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, assigned_amount, is_trial, email, payment_assigned_at, created_at) VALUES (%s, %s, %s, FALSE, %s, %s, %s)",
                (license_key, expiry, assigned_amount, email, assigned_at, now)
            )
        else:
            cursor.execute(
                "INSERT INTO users (api_key, expires_at, assigned_amount, is_trial, email, payment_assigned_at, created_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
                (license_key, expiry, float(assigned_amount), email, assigned_at, now.isoformat())
            )
        conn.commit()
        
        return {
            "success": True,
            "key": license_key,
            "amount": float(assigned_amount),
            "destination_address": MASTER_WALLET,
            "chain": "polygon"
        }
    finally:
        conn.close()

@app.post("/api/v1/web/status")
async def get_web_key_status(payload: StatusRequest):
    conn = get_db()
    cursor = get_cursor(conn)
    
    try:
        if is_postgres:
            cursor.execute("SELECT expires_at, assigned_amount, payment_assigned_at FROM users WHERE api_key = %s", (payload.key,))
        else:
            cursor.execute("SELECT expires_at, assigned_amount, payment_assigned_at FROM users WHERE api_key = ?", (payload.key,))
            
        record = cursor.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="Licensing key not found.")
            
        expires_at_val = record["expires_at"]
        assigned_amount_val = record["assigned_amount"]
        payment_assigned_at_val = record["payment_assigned_at"]
        
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
            
        # Case A: Trial key is fresh (not locked to a device yet)
        if not device_id_val:
            # Check if this device has already claimed ANY other trial key in the database
            if is_postgres:
                cursor.execute("SELECT 1 FROM users WHERE is_trial = TRUE AND device_id = %s", (x_device_id,))
            else:
                cursor.execute("SELECT 1 FROM users WHERE is_trial = 1 AND device_id = ?", (x_device_id,))
                
            if cursor.fetchone():
                conn.close()
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This device has already used a free trial.")
                
            # Lock this key to the current device
            if is_postgres:
                cursor.execute("UPDATE users SET device_id = %s WHERE api_key = %s", (x_device_id, x_api_key))
            else:
                cursor.execute("UPDATE users SET device_id = ? WHERE api_key = ?", (x_device_id, x_api_key))
            conn.commit()
            
        # Case B: Trial key is already locked to a different device
        elif device_id_val != x_device_id:
            conn.close()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This trial key is locked to another device.")

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
                
            # Generate a new unique 3-hour trial key
            trial_key = f"trial-{uuid.uuid4().hex[:12]}"
            expiry_time = datetime.now(timezone.utc) + timedelta(hours=3)
            
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
                    f"🎉 **Your ACCCE 3-Hour Free Trial Key has been generated!**\n\n"
                    f"🔑 **Token**: `{trial_key}`\n"
                    f"⏰ **Expires in**: 3 Hours\n\n"
                    f"To use the bot, set this key as your `COURSERA_ENGINE_TOKEN` in your `.env` file.\n"
                    f"Once your trial expires, the bot will display instructions to extend it for 1 month for $3 USD."
                )
                await ctx.author.send(dm_message)
                await ctx.reply("✅ I have sent your 3-hour free trial key to your Direct Messages (DMs)!")
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
    asyncio.create_task(check_polygon_payments())
    if DISCORD_BOT_TOKEN:
        asyncio.create_task(start_discord_bot())
