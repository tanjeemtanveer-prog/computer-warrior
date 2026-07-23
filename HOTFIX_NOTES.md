# Computer Warrior v0.0.1 Hotfix 1

## Reported failure

On Python 3.13, the original package's pinned `pynput==1.7.7` could crash its listener callback with:

```text
TypeError: '_thread._ThreadHandle' object is not callable
```

Python 3.13 introduced an internal `threading.Thread._handle` field, while old pynput listeners also used `_handle` as a method name.

## Corrections

- Replaced `pynput==1.7.7` with `pynput==1.8.2`.
- Updated all keyboard and mouse callbacks for the `injected` event flag used by pynput 1.8.x.
- Ignored injected/synthetic events so automated input cannot generate XP.
- Added a startup dependency-version check with a clear repair instruction.
- Added listener-health checks so a dead input listener cannot leave the console falsely displaying `RUNNING`.
- Updated the dependency installer to force-replace the incompatible package.
- Added compatibility and listener-failure tests.

## Upgrade without losing XP

The stats location and JSON schema are unchanged:

`%LOCALAPPDATA%\ComputerWarrior\stats.json`

Replacing the program folder does not delete daily or lifetime XP.
