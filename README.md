# Computer Warrior v0.0.7.1 — Cloudflare User-Agent Hotfix

A Windows-first activity game core that converts anonymous aggregate input activity into XP. It keeps the CLI dashboard and now also serves a live browser dashboard on this PC only.

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
