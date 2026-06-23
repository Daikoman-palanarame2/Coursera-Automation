-- Users Table: Tracks anonymous access tokens and their subscription expiration.
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
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Payments Table: Logs processed blockchain transactions to prevent duplicate crediting.
CREATE TABLE IF NOT EXISTS payments (
    tx_hash TEXT PRIMARY KEY,
    api_key TEXT REFERENCES users(api_key),
    amount NUMERIC(12, 4) NOT NULL,
    network TEXT NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Insert a default demo token for local testing (expires in 10 minutes by default)
INSERT INTO users (api_key, expires_at)
VALUES ('test-demo-key-12345', CURRENT_TIMESTAMP + INTERVAL '10 minutes')
ON CONFLICT (api_key) DO NOTHING;

