# Computer Warrior v0.2.0 — Public Site and Analytics Foundation

A Windows-first activity game core that converts anonymous aggregate input activity into XP. It keeps the CLI dashboard and now also serves a live browser dashboard on this PC only.

## v0.2.0 public site and analytics foundation

- Adds a responsive Cloudflare-hosted landing page, privacy page, and branded
  404 page without exposing or replacing the localhost tracker dashboard.
- Uses Workers Static Assets for public pages while `/api/*` continues through
  the existing Worker and D1 backend.
- Prepares Cloudflare Web Analytics for cookie-free daily visitors, page views,
  referrers, device aggregates, and performance. A real Cloudflare-generated
  site token must be added deliberately before visitor analytics starts.
- Adds optional Workers Analytics Engine events for successful account,
  device, sync, and leaderboard actions.
- Analytics has a fixed anonymous schema and never accepts username, email,
  account ID, device ID, token, IP address, user-agent, or raw activity.
- Adds `cloudflare/ANALYTICS.md` and tested starter SQL queries for later product
  reporting.
- Needs no D1 migration or secret rotation. Deploy the beta Worker to publish
  the site and analytics binding.

Follow `V0.2.0_UPGRADE_GUIDE.md` for the exact Windows copy, test, preview, Git,
deployment, and Web Analytics steps.

## v0.1.1 focus quests

- Adds local 25-minute, 50-minute, and 5–180 minute custom focus quests.
- A quest shows a running or paused countdown and the aggregate XP earned while
  it runs. It grants no artificial or bonus XP.
- Completion stores only the local calendar date, planned duration, and total
  aggregate XP earned during that quest. Active timers are runtime-only and are
  not saved across an app restart.
- The last 20 completed quests stay in the existing local stats file. No quest
  information is sent to Cloudflare, D1, or the global leaderboard.
- Needs no D1 migration, secret update, Worker deployment, or `npm install`.

## v0.1.0 global leaderboard

- Adds opt-in global lifetime and current UTC-day leaderboards.
- Shows the top 25 public accounts plus the signed-in participant's rank when
  it falls below the top 25.
- Shows only username, rank and accepted aggregate XP. It never publishes a
  device ID, label, session token, event data, typed content or coordinates.
- New accounts and existing beta accounts are private until the user explicitly
  enables leaderboard visibility.
- Requires D1 migration `0003_global_leaderboard_visibility.sql` and a Worker
  deployment. Existing local XP and sync queues remain unchanged.

## v0.0.9.1 daily momentum chart fix

- Makes dates without a saved local daily record visibly empty in the
  seven-day signal, rather than rendering them as activity bars.
- Labels empty dates with an accessible “No data” marker; stored aggregate
  XP values remain the only chart data.
- Needs no Worker deployment, D1 migration, or change to existing XP.

## v0.0.9 daily momentum

- Adds a configurable local daily XP goal (50–50,000 XP).
- Adds goal progress, completion feedback and a consecutive completed-day
  streak.
- Retains a rolling seven-day local history of date plus total XP only.
- Derives small milestone badges from XP, the goal and the streak.
- Keeps goal settings and history on this PC; neither is sent to the Worker.

This release needs no D1 migration, secret rotation or Worker deployment.

## v0.0.8 game-loop dashboard

- Adds an earned rank title based only on the existing XP level.
- Adds a live session pulse beside the level progress.
- Adds a collapsed Activity Mix view showing the percentage split of today's
  four aggregate XP categories.
- Improves the online leaderboard hierarchy so the current top competitor is
  easier to scan.
- Keeps all detailed activity information in the existing collapsible panel;
  no new activity data is recorded, uploaded, or retained.

This is a local dashboard update. It needs no D1 migration, secret change, or
Worker deployment.

## Private Cloudflare beta foundation

The new `cloudflare/` folder contains the online-account backend, tested against
Wrangler's **local D1 database**. It has accounts, account sessions, device
registration, per-device ordered XP updates, combined account totals, and daily
or lifetime leaderboards. It does not deploy, connect to a real Cloudflare
account, or change the Python tracker’s privacy boundary.

Start with [cloudflare/README.md](cloudflare/README.md). The Python tracker is
now wired to this local API through a durable, device-specific offline queue.
The committed `wrangler.jsonc` stays local-only. A separate
`cloudflare/wrangler.beta.jsonc` binds only the private beta Worker to the new
remote APAC D1 database. The beta is not deployed until secrets, remote
migration, and two-device QA are completed.

## v0.0.7 beta hardening

- Registration can be closed behind a private invite code.
- Remote password and session hashes are peppered with a Worker secret that is
  never committed to Git or returned to the dashboard.
- Beta registration and login attempts are throttled by a hashed client
  address.
- The dashboard sends an invite code only during registration and clears it
  afterwards; it never serializes that code in `online_sync.json`.
- Local development remains compatible with existing local accounts and local
  D1 state.

## v0.0.7.1 Cloudflare transport hotfix

The local Python HTTPS client now sends a browser-compatible `User-Agent` when
calling a Cloudflare Worker. This prevents Cloudflare Browser Integrity Check
from rejecting Python's default `Python-urllib/<version>` request signature
before the Worker API can validate an invite or account request. It does not
send any additional local activity data and requires no D1 migration or Worker
redeployment.

## v0.0.7.2 Cloudflare Free CPU auth hotfix

The beta Worker now uses 20,000 PBKDF2-SHA-256 iterations for new beta
password hashes. This fits Cloudflare Workers Free's 10 ms CPU limit, which
the former 310,000-iteration setting exceeded during account registration.
The server-only `AUTH_PEPPER`, a unique password salt, and per-address auth
throttling remain in place. This release needs a Worker deployment but no D1
migration. Because no beta account was created successfully, there is no
existing password hash to migrate.

## v0.0.6 online sync

When signed in, Computer Warrior creates one random device UUID for this
installation. XP is still captured locally every 10 seconds, but it is merged
into one aggregate batch and normally uploaded at most once every five
minutes. Sync now and a clean exit upload immediately. A batch is frozen
before its first request, so a retry reuses the same payload and the D1 backend
can accept it safely without double-counting. Automatic batches do not request
the leaderboard; it refreshes when the Online panel opens or after Sync now.
The Online-panel refresh route is covered by an automated local-server test.
While the Online panel is visible, its local status refreshes every two seconds,
without calling the Worker or D1.

On Windows, the Worker session token is stored in Windows Credential Manager
as a Generic Credential. It is never returned to the browser or written to
online_sync.json. Existing v0.0.5.x plaintext tokens are migrated once, then
removed from that JSON file. If Windows cannot securely store the token, the
app signs out rather than retaining it in plaintext.

## Repository and deployment foundation

Run init_git_repository.bat once in the project root to initialize a local Git
repository. GIT_WORKFLOW.md explains the review and release flow, while
RELEASE_AND_DEPLOYMENT_PLAN.md defines the remaining gates before a private
Cloudflare beta. verify_project.bat runs both the Python and Worker tests.

Open the local dashboard, choose **Online**, then register or sign in. The
browser sends credentials only to the local Python dashboard; Python owns the
Worker session token and the page never receives it. `online_sync.json` is a
local application-state file containing the device ID, queue, and local Worker
session. It contains no typed content or raw input events.

For this local beta, do not copy `online_sync.json` between computers. A
production update will move the local session secret to Windows protected
credential storage before a public deployment.

## Web dashboard

Run `launch_web_dashboard.bat` (or the normal `launch_computer_warrior.bat`).
Computer Warrior starts its normal tracker and opens:

`http://127.0.0.1:8765/`

The page refreshes aggregate totals every 500 ms. Its Pause, Resume, and Exit
buttons control the real local tracker; F9 and F10 continue to work as before.
The server binds exclusively to `127.0.0.1`, so no other device, website, or
cloud service can access it. No new dependency is required.

If port 8765 is already being used, run:

```powershell
py -3 run_computer_warrior.py --web-port 8766
```

Use `--no-web` to run only the CLI dashboard and `--no-browser` to start the
local page without opening a browser window.

## What changed in v0.0.3

- Adds a responsive local web dashboard that uses the real tracker snapshot.
- Adds a collapsed right-side activity drawer with category and session detail.
- Adds a local-only health endpoint, aggregate stats endpoint, and real tracker controls.
- Keeps all typed content, input identities, coordinates, and event history out of the API.

## What changed in v0.0.2

- Displays Keyboard, Mouse clicks, Cursor movement and Scrolling XP separately.
- Displays Session, Today and Lifetime values for every category.
- Places the four category rows before the combined Total XP row.
- Displays progress toward the next cursor XP and scroll XP.
- Changes the visible dashboard state between `RUNNING` and `PAUSED`.
- Refreshes the fixed dashboard rows in place instead of filling console history.
- Keeps the v0.0.1 stats path and schema, so existing XP loads automatically.

## Upgrade from v0.0.1-hotfix.1

1. Press F10 in the old version and wait for `XP saved successfully`.
2. Extract the v0.0.2 ZIP into a new folder.
3. Double-click `run_self_tests.bat`.
4. Double-click `launch_computer_warrior.bat`.
5. Confirm the title says `Computer Warrior v0.0.2` and your Today/Lifetime XP remains.

The default stats path and schema are unchanged:

`%LOCALAPPDATA%\ComputerWarrior\stats.json`

If pynput is missing or older than 1.8.2, run `install_dependencies.bat` once.

## Live output

```text
Computer Warrior Activity Dashboard [RUNNING]
Activity XP            Session       Today    Lifetime
------------------------------------------------------
Keyboard                    90         306         306
Mouse clicks                18          51          51
Cursor movement             46          66          66
Scrolling                   20          20          20
------------------------------------------------------
TOTAL XP                   174         443         443

Next cursor XP: 485.3 / 1,000 pixels
Next scroll XP: 0.0 / 10 steps
F9 = pause/resume | F10 = save and exit
```

## XP rules

- Keyboard: 1 XP for each new physical key-down. Operating-system repeat while held is suppressed.
- Mouse click: 1 XP for button-down only.
- Cursor distance: 1 XP per 1,000 accumulated pixels. Individual jumps over 5,000 pixels are ignored.
- Scroll: 1 XP per 10 accumulated horizontal/vertical wheel steps.
- F9: pause/resume; the control key awards no XP.
- F10: save and exit; the control key awards no XP.

## Totals

- Session starts at zero whenever the program starts.
- Today persists for the current local calendar day and resets when the date changes.
- Lifetime persists unless the user deletes the stats file.
- Each scope contains Keyboard, Mouse clicks, Cursor movement, Scrolling and Total XP.

## Privacy boundary

Computer Warrior stores only aggregate counters. It does **not** store typed keys, typed text, key sequences, cursor coordinates, clicked locations, window titles, application names, websites, screenshots, clipboard data or event-by-event timestamps.

Injected or synthetic keyboard and mouse events are ignored. Only physical input reported as non-injected can award XP.

## Storage and recovery

Each save is written to and verified from a temporary file before atomically replacing the primary file. A verified previous primary is retained as `stats.json.bak`. If the primary becomes corrupt, the program loads the backup and repairs the primary on the next save.

## Launch and controls

1. Install Python 3.10 or newer for Windows and enable the Python launcher.
2. Run `install_dependencies.bat` if dependencies have not already been installed.
3. Run `run_self_tests.bat` and confirm every test passes.
4. Run `launch_computer_warrior.bat`.
5. Use F9 to pause/resume and F10 to save/exit.

`launch_minimized.bat` launches the same console minimized. It does not configure automatic startup or hide the process.

For a final JSON snapshot, run:

```powershell
py -3 run_computer_warrior.py --print-json
```

## Manual Windows QA

1. Confirm the dashboard shows all four category rows before Total XP.
2. Generate each activity and confirm its Session, Today and Lifetime column changes.
3. Confirm cursor and scroll progress reset after reaching their XP thresholds.
4. Press F9 and confirm the title changes to `PAUSED`; activity must award no XP.
5. Press F9 again and confirm `RUNNING` and resumed counting.
6. Start a second copy and confirm it reports that Computer Warrior is already running.
7. Press F10, relaunch and confirm Session resets while Today/Lifetime persist.

## Project layout

- `computer_warrior/`: activity core, persistence and dashboard modules.
- `tests/test_core.py`: unit, compatibility, privacy and dashboard tests.
- `self_test.py`: QA runner and report generator.
- `run_computer_warrior.py`: Windows runtime entry point.
- `V0.0.2_NOTES.md`: v0.0.2 change and compatibility notes.
- `HOTFIX_NOTES.md`: historical Python 3.13 hotfix notes.
- `*.bat`: dependency, launch and QA scripts.

No autostart installer, public deployment, content logging, or raw-input sync is included.
