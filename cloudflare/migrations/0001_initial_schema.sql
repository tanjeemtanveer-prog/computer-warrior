PRAGMA foreign_keys = ON;

CREATE TABLE accounts (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL COLLATE NOCASE UNIQUE,
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX sessions_account_id_idx ON sessions(account_id);
CREATE INDEX sessions_expires_at_idx ON sessions(expires_at);

CREATE TABLE devices (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  public_key TEXT,
  last_sequence INTEGER NOT NULL DEFAULT 0 CHECK(last_sequence >= 0),
  verified_total INTEGER NOT NULL DEFAULT 0 CHECK(verified_total >= 0),
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE INDEX devices_account_id_idx ON devices(account_id);

CREATE TABLE sync_entries (
  device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL CHECK(sequence > 0),
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  occurred_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  duration_seconds INTEGER NOT NULL CHECK(duration_seconds BETWEEN 1 AND 3600),
  keyboard_xp INTEGER NOT NULL CHECK(keyboard_xp >= 0),
  click_xp INTEGER NOT NULL CHECK(click_xp >= 0),
  cursor_xp INTEGER NOT NULL CHECK(cursor_xp >= 0),
  scroll_xp INTEGER NOT NULL CHECK(scroll_xp >= 0),
  total_xp INTEGER NOT NULL CHECK(total_xp >= 0),
  payload_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'verified' CHECK(status IN ('verified', 'pending')),
  PRIMARY KEY (device_id, sequence)
);

CREATE INDEX sync_entries_account_received_idx ON sync_entries(account_id, received_at DESC);

CREATE TABLE account_totals (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  keyboard_xp INTEGER NOT NULL DEFAULT 0,
  click_xp INTEGER NOT NULL DEFAULT 0,
  cursor_xp INTEGER NOT NULL DEFAULT 0,
  scroll_xp INTEGER NOT NULL DEFAULT 0,
  verified_total INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE account_daily_totals (
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  day_utc TEXT NOT NULL,
  verified_total INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_id, day_utc)
);

CREATE INDEX account_daily_totals_rank_idx ON account_daily_totals(day_utc, verified_total DESC);

CREATE TABLE security_flags (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  device_id TEXT REFERENCES devices(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  details_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
