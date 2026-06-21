import os
import random
import decimal
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
import httpx

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("licensing_server")

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
db_conn = None

if DATABASE_URL and DATABASE_URL.startswith("postgres"):
    import psycopg2
    from psycopg2.extras import RealDictCursor
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

# Initialize tables
def init_db():
    conn = get_db()
    cursor = conn.cursor()
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                api_key TEXT PRIMARY KEY,
                credits INTEGER DEFAULT 5 NOT NULL,
                assigned_amount NUMERIC(8, 4) DEFAULT 0.0000 NOT NULL,
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
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                api_key TEXT PRIMARY KEY,
                credits INTEGER DEFAULT 5 NOT NULL,
                assigned_amount REAL DEFAULT 0.0000 NOT NULL,
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
        # Insert a default demo token for easy local verification
        cursor.execute("""
            INSERT OR IGNORE INTO users (api_key, credits) VALUES ('test-demo-key-12345', 5);
        """)
    conn.commit()
    conn.close()

init_db()

@app.get("/")
def read_root():
    return {"status": "online", "message": "ACCCE licensing server is operational."}

@app.get("/api/v1/layout-map")
def get_layout_map(x_api_key: Optional[str] = Header(None)):
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-API-Key header.")
        
    conn = get_db()
    cursor = conn.cursor()
    
    if is_postgres:
        cursor.execute("SELECT * FROM users WHERE api_key = %s", (x_api_key,))
    else:
        cursor.execute("SELECT * FROM users WHERE api_key = ?", (x_api_key,))
        
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API Key.")
        
    # Check if user has credits remaining
    credits = user["credits"] if is_postgres else user[1]
    
    if credits > 0:
        # Decrement credits
        new_credits = credits - 1
        if is_postgres:
            cursor.execute("UPDATE users SET credits = %s WHERE api_key = %s", (new_credits, x_api_key))
        else:
            cursor.execute("UPDATE users SET credits = ? WHERE api_key = ?", (new_credits, x_api_key))
        conn.commit()
        conn.close()
        logger.info(f"Authorized access for key {x_api_key}. Credits remaining: {new_credits}")
        return {"status": "authorized", "credits": new_credits, "layout_map": COURSERA_LAYOUT_MAP}
        
    # If out of credits, generate a random decimal payment amount (e.g. between 20.0001 and 20.0999)
    assigned_amount = user["assigned_amount"] if is_postgres else user[2]
    if float(assigned_amount) <= 0.0:
        # Generate random unique cents salt to link payment to this key
        salt = random.randint(1, 9999)
        assigned_amount = decimal.Decimal("20.0000") + decimal.Decimal(salt) / decimal.Decimal("10000")
        if is_postgres:
            cursor.execute("UPDATE users SET assigned_amount = %s WHERE api_key = %s", (assigned_amount, x_api_key))
        else:
            cursor.execute("UPDATE users SET assigned_amount = ? WHERE api_key = ?", (float(assigned_amount), x_api_key))
        conn.commit()
        
    conn.close()
    
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={
            "status": "payment_required",
            "message": "Free tier exhausted. Please top up your account.",
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
    """
    Background worker that runs if a MASTER_WALLET is specified, scanning 
    Polygon logs for incoming USDT transfers matching our unique user cents salts.
    """
    if not MASTER_WALLET or MASTER_WALLET == "0x0000000000000000000000000000000000000000":
        logger.warning("Blockchain Listener: MASTER_WALLET_ADDRESS not configured. Payment auto-reload disabled.")
        return

    logger.info(f"Blockchain Listener: Monitoring wallet {MASTER_WALLET} on Polygon chain...")
    
    # Pad the target address to 32 bytes for EVM topic matching
    padded_wallet = "0x" + MASTER_WALLET[2:].zfill(64)
    transfer_event_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Query Ethereum JSON-RPC eth_getLogs
                rpc_payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_getLogs",
                    "params": [{
                        "address": USDT_POLYGON_CONTRACT,
                        "topics": [transfer_event_topic, None, padded_wallet],
                        "fromBlock": "latest" # In production, track last block height to avoid missing txs
                    }],
                    "id": 1
                }
                response = await client.post(POLYGON_RPC_URL, json=rpc_payload, timeout=10)
                if response.status_code == 200:
                    result = response.json().get("result", [])
                    for log in result:
                        tx_hash = log.get("transactionHash")
                        # USDT has 6 decimals on Polygon
                        raw_data = log.get("data")
                        amount_int = int(raw_data, 16)
                        amount_usdt = decimal.Decimal(amount_int) / decimal.Decimal("1000000")
                        
                        # Process matched payment
                        await process_payment(tx_hash, amount_usdt)
            except Exception as e:
                logger.error(f"Blockchain Listener Error: {e}")
            await asyncio.sleep(20)

async def process_payment(tx_hash: str, amount: decimal.Decimal):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Check if transaction was already processed
        if is_postgres:
            cursor.execute("SELECT 1 FROM payments WHERE tx_hash = %s", (tx_hash,))
        else:
            cursor.execute("SELECT 1 FROM payments WHERE tx_hash = ?", (tx_hash,))
            
        if cursor.fetchone():
            return
            
        # Find user with matching assigned amount
        amount_float = float(amount)
        if is_postgres:
            cursor.execute("SELECT api_key, credits FROM users WHERE assigned_amount = %s", (amount,))
        else:
            cursor.execute("SELECT api_key, credits FROM users WHERE assigned_amount = ?", (amount_float,))
            
        matched_user = cursor.fetchone()
        if matched_user:
            api_key = matched_user["api_key"] if is_postgres else matched_user[0]
            current_credits = matched_user["credits"] if is_postgres else matched_user[1]
            new_credits = current_credits + 50 # Add 50 runs per top-up
            
            logger.info(f"Payment Match! Tx {tx_hash} of {amount_float} USDT matched to API Key {api_key}. Crediting 50 runs.")
            
            if is_postgres:
                cursor.execute("INSERT INTO payments (tx_hash, api_key, amount, network) VALUES (%s, %s, %s, %s)",
                               (tx_hash, api_key, amount, "polygon"))
                cursor.execute("UPDATE users SET credits = %s, assigned_amount = 0 WHERE api_key = %s",
                               (new_credits, api_key))
            else:
                cursor.execute("INSERT INTO payments (tx_hash, api_key, amount, network) VALUES (?, ?, ?, ?)",
                               (tx_hash, api_key, amount_float, "polygon"))
                cursor.execute("UPDATE users SET credits = ?, assigned_amount = 0 WHERE api_key = ?",
                               (new_credits, api_key))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed processing payment {tx_hash}: {e}")
    finally:
        conn.close()

# Start background worker when running
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(check_polygon_payments())
