CREATE TABLE IF NOT EXISTS licenses (
 id TEXT PRIMARY KEY,
 key_hash TEXT NOT NULL UNIQUE,
 key_cipher TEXT NOT NULL,
 customer TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 expires_at TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN(0,1)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 last_seen_at TEXT,
 checks INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_licenses_customer ON licenses(customer);
CREATE INDEX IF NOT EXISTS idx_licenses_expires ON licenses(expires_at);
CREATE TABLE IF NOT EXISTS versions (
 version TEXT PRIMARY KEY,
 download_url TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '',
 mandatory INTEGER NOT NULL DEFAULT 0 CHECK(mandatory IN(0,1)),
 is_current INTEGER NOT NULL DEFAULT 0 CHECK(is_current IN(0,1)),
 published_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_current_release ON versions(is_current) WHERE is_current=1;
