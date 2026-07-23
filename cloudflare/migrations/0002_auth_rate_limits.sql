CREATE TABLE auth_rate_limits (
  bucket TEXT PRIMARY KEY,
  window_started_at INTEGER NOT NULL,
  attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
  blocked_until INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);

CREATE INDEX auth_rate_limits_updated_at_idx ON auth_rate_limits(updated_at);
