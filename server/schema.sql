-- Users Table: Tracks anonymous access tokens and current credit counts.
CREATE TABLE IF NOT EXISTS users (
    api_key TEXT PRIMARY KEY,
    credits INTEGER DEFAULT 5 NOT NULL,
    assigned_amount NUMERIC(8, 4) DEFAULT 0.0000 NOT NULL,
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

-- Insert a default demo token for local testing and validation
INSERT INTO users (api_key, credits)
VALUES ('test-demo-key-12345', 5)
ON CONFLICT (api_key) DO NOTHING;
