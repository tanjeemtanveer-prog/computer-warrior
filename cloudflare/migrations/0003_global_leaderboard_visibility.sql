ALTER TABLE accounts ADD COLUMN leaderboard_visible INTEGER NOT NULL DEFAULT 0 CHECK(leaderboard_visible IN (0, 1));

CREATE INDEX accounts_leaderboard_visibility_idx ON accounts(leaderboard_visible, username);
