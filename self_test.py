"""Run built-in tests and write a human-readable QA report."""

from __future__ import annotations

import io
import platform
import sys
import unittest
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

from computer_warrior.config import APP_VERSION


ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "QA_NOTES.md"


def _dependency_status() -> str:
    try:
        return package_version("pynput")
    except PackageNotFoundError:
        return "not installed in this QA environment"


def main() -> int:
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    output = stream.getvalue()

    status = "PASS" if result.wasSuccessful() else "FAIL"
    report = f"""# Computer Warrior v{APP_VERSION} Automated QA Notes

- Result: **{status}**
- Generated: {datetime.now(timezone.utc).isoformat()}
- Python: {sys.version.split()[0]}
- Platform: {platform.platform()}
- pynput in test environment: {_dependency_status()}
- Required Windows runtime dependency: pynput 1.8.2+
- Tests run: {result.testsRun}
- Failures: {len(result.failures)}
- Errors: {len(result.errors)}
- Skipped: {len(result.skipped)}

## Scope covered

- Held-key auto-repeat suppression.
- Anonymous keyboard, click, cursor-distance and scroll XP aggregation.
- Pause/resume and clean shutdown controls.
- Session, local-day and lifetime totals.
- Daily rollover without resetting session or lifetime totals.
- Atomic JSON write, previous-good backup and corrupt-primary recovery.
- Privacy check confirming no keys, text, cursor coordinates or window titles are persisted.
- pynput 1.8 callback signatures, including the injected-event flag.
- Synthetic/injected keyboard and mouse events award no XP.
- Dead listener threads are promoted to visible fatal errors instead of silently showing RUNNING.
- Windows named-mutex duplicate-instance rejection (runs on Windows; skipped elsewhere).
- Detailed live dashboard formatting for keyboard, clicks, cursor, scroll and total XP.
- Session, today and lifetime values are visible for every XP category before totals.
- RUNNING/PAUSED dashboard state and cursor/scroll progress formatting.
- In-place dashboard refresh without duplicate redraws.
- Five-minute online XP batching without automatic leaderboard polling.
- Immediate manual aggregation, immutable retry entries and account switching safety.
- Migration of legacy plaintext session state into a non-serialized credential store.
- Beta invite-code forwarding without serializing the invite in local state.
- Beta dashboard invite field and private Worker configuration separation.
- Cloudflare-compatible User-Agent on Python Worker requests.
- Workers Free CPU-compatible beta password work factor.
- Local dashboard rank, session-pulse and aggregate activity-mix UI contract.
- Local daily-goal validation, streak calculation and seven-day aggregate history.
- Local focus-quest start, pause, completion, aggregate-XP record and restart behavior.
- Focus-quest dashboard controls and loopback API routes without any Cloudflare upload.
- Direct loading of v0.0.1-hotfix.1 schema-version-1 stats without XP loss.

## Test runner output

```text
{output.rstrip()}
```

## Environment limitation

The automated core, local-dashboard and batching tests are cross-platform. Global Windows input hooks, the actual Win32 mutex and browser interaction must also be smoke-tested on the target Windows machine using `run_self_tests.bat` and `launch_web_dashboard.bat`. The package pins pynput 1.8.2 for Python 3.13 compatibility.
"""
    REPORT_PATH.write_text(report, encoding="utf-8", newline="\n")
    print(output, end="")
    print(f"QA report written to: {REPORT_PATH}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
