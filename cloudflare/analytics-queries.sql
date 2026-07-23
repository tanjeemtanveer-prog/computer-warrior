-- Computer Warrior Workers Analytics Engine examples.
-- Run through the Cloudflare Analytics Engine SQL API against the
-- computer_warrior_product dataset. Analytics Engine may sample high-volume
-- data, so multiply counts and values by _sample_interval.

-- Daily product funnel for the last 30 days.
SELECT
  toStartOfDay(timestamp) AS day,
  blob1 AS event_name,
  SUM(double1 * _sample_interval) AS event_count
FROM computer_warrior_product
WHERE
  timestamp >= NOW() - INTERVAL '30' DAY
  AND blob3 = 'product-v1'
GROUP BY day, event_name
ORDER BY day DESC, event_name ASC;

-- Accepted aggregate XP volume by day. This is not a visitor count.
SELECT
  toStartOfDay(timestamp) AS day,
  SUM(double2 * _sample_interval) AS accepted_xp
FROM computer_warrior_product
WHERE
  timestamp >= NOW() - INTERVAL '30' DAY
  AND blob1 = 'xp_sync_accepted'
  AND blob3 = 'product-v1'
GROUP BY day
ORDER BY day DESC;

-- Beta-to-production event comparison.
SELECT
  blob2 AS environment,
  blob1 AS event_name,
  SUM(double1 * _sample_interval) AS event_count
FROM computer_warrior_product
WHERE
  timestamp >= NOW() - INTERVAL '7' DAY
  AND blob3 = 'product-v1'
GROUP BY environment, event_name
ORDER BY environment ASC, event_count DESC;
