# Computer Warrior — local Cloudflare D1 backend

This folder is the v0.0.4 online-account foundation. It runs entirely on this
computer until you deliberately create and deploy a real D1 database.

## What is included

- Username/password registration and login.
- Token-based local development sessions.
- One account owning multiple random UUID devices.
- Strict device-only ordered XP updates (`device_id + sequence`).
- Retry-safe sync: the same device sequence and payload returns the original result instead of adding XP again.
- Per-device totals plus combined account totals.
- Daily and lifetime verified leaderboards.
- Local rate checks for impossible aggregate XP bursts.

Only four aggregate XP numbers are accepted: keyboard, click, cursor, and
scroll. The API rejects arbitrary fields by ignoring them; it never asks for or
stores typed text, key identities, coordinates, websites, windows, clipboard
data, screenshots, or event history.

## Run locally

From this `cloudflare` folder on Windows PowerShell:

```powershell
npm install
npm run check
npm test
npm run db:migrate
npm run dev
```

The Worker starts at `http://127.0.0.1:8787` and uses a local Wrangler D1
database. No Cloudflare login is needed for these commands.

## First local API flow

1. `POST /api/auth/register` with `username` and `password`.
2. Store the returned token only in the local tracker’s protected account store.
3. `POST /api/devices` with that Bearer token, a random UUID, and a label.
4. `POST /api/sync` with that device UUID, a new sequence number, duration, timestamp, and four aggregate XP values.
5. `GET /api/leaderboard?period=lifetime`.

The Python tracker is intentionally not connected to this local Worker yet. It
will be the next update, after we verify the local Worker/D1 account flow in a
browser or API test. That prevents the tracker from uploading to an untested
backend.

## Before deployment

Do not deploy this local configuration. Create a real D1 database, replace the
placeholder `database_id`, set a production `APP_ORIGIN`, and add the browser
account/sync UI. Production also needs stronger login throttling and a server
secret/session-cookie design.
