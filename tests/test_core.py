from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from computer_warrior.app import _raise_if_listener_stopped, _version_tuple
from computer_warrior.config import PIXELS_PER_CURSOR_XP, SCROLL_STEPS_PER_XP
from computer_warrior.dashboard import LiveDashboard, format_dashboard
from computer_warrior.model import MetricTotals, PersistedState
from computer_warrior.persistence import AtomicJsonStore
from computer_warrior.online import OnlineSyncError, OnlineSyncManager, WORKER_USER_AGENT
from computer_warrior.single_instance import AlreadyRunningError, WindowsSingleInstance
from computer_warrior.tracker import ActivityTracker
from computer_warrior.web import LocalDashboardServer, make_dashboard_payload


class FakeKey:
    def __init__(self, *, vk: int | None = None, name: str | None = None) -> None:
        self.vk = vk
        self.name = name


class MutableDay:
    def __init__(self, value: date) -> None:
        self.value = value

    def __call__(self) -> date:
        return self.value


def dashboard_snapshot(*, paused: bool = False) -> dict[str, object]:
    return {
        "paused": paused,
        "day_local": "2026-07-23",
        "session": {
            "keyboard": 56,
            "click": 7,
            "cursor": 6,
            "scroll": 2,
            "total": 71,
        },
        "daily": {
            "keyboard": 216,
            "click": 33,
            "cursor": 20,
            "scroll": 12,
            "total": 281,
        },
        "lifetime": {
            "keyboard": 1216,
            "click": 333,
            "cursor": 220,
            "scroll": 112,
            "total": 1881,
        },
        "movement_remainder_pixels": 485.2522,
        "scroll_remainder_steps": 4.0,
    }


class DashboardTests(unittest.TestCase):
    def test_web_payload_exposes_only_aggregate_dashboard_values(self) -> None:
        payload = make_dashboard_payload(dashboard_snapshot(), "2026-07-23T12:00:00+00:00")
        self.assertEqual(payload["lifetime"]["total"], 1881)
        self.assertEqual(payload["level"]["number"], 2)
        self.assertEqual(payload["level"]["progress_xp"], 881)
        self.assertEqual(payload["progress"]["cursor_pixels"], 485.2522)
        serialized = json.dumps(payload).lower()
        self.assertNotIn("key_sequence", serialized)
        self.assertNotIn("cursor_position", serialized)
    def test_dashboard_shows_categories_before_totals_for_every_scope(self) -> None:
        output = format_dashboard(dashboard_snapshot())
        self.assertIn("Activity Dashboard [RUNNING]", output)
        self.assertIn("Activity XP            Session       Today    Lifetime", output)
        self.assertIn("Keyboard", output)
        self.assertIn("Mouse clicks", output)
        self.assertIn("Cursor movement", output)
        self.assertIn("Scrolling", output)
        self.assertLess(output.index("Keyboard"), output.index("TOTAL XP"))
        self.assertIn("1,881", output)
        self.assertIn("485.3 / 1,000 pixels", output)
        self.assertIn("4.0 / 10 steps", output)

    def test_dashboard_visibly_changes_to_paused(self) -> None:
        output = format_dashboard(dashboard_snapshot(paused=True))
        self.assertIn("[PAUSED]", output)
        self.assertNotIn("[RUNNING]", output)

    def test_live_dashboard_rewrites_fixed_rows_and_skips_duplicates(self) -> None:
        stream = io.StringIO()
        dashboard = LiveDashboard(stream=stream, live=True)
        running = dashboard_snapshot()
        dashboard.render(running)
        first_output = stream.getvalue()
        dashboard.render(running)
        self.assertEqual(stream.getvalue(), first_output)

        dashboard.render(dashboard_snapshot(paused=True))
        refreshed = stream.getvalue()[len(first_output) :]
        self.assertIn("\x1b[13F", refreshed)
        self.assertEqual(refreshed.count("\x1b[2K"), 13)
        self.assertIn("[PAUSED]", refreshed)


class TrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "stats.json"
        self.day = MutableDay(date(2026, 7, 23))
        self.tracker = ActivityTracker(AtomicJsonStore(self.path), self.day)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_held_key_repeat_is_suppressed(self) -> None:
        key = FakeKey(vk=65)
        self.tracker.on_key_press(key)
        self.tracker.on_key_press(key)
        self.assertEqual(self.tracker.snapshot()["session"]["keyboard"], 1)
        self.tracker.on_key_release(key)
        self.tracker.on_key_press(key)
        self.assertEqual(self.tracker.snapshot()["session"]["keyboard"], 2)

    def test_pause_resume_blocks_all_xp(self) -> None:
        self.tracker.set_paused(True)
        self.tracker.on_key_press(FakeKey(vk=65))
        self.tracker.on_mouse_click(0, 0, object(), True)
        self.tracker.on_mouse_move(0, 0)
        self.tracker.on_mouse_move(2000, 0)
        self.tracker.on_mouse_scroll(0, 0, 0, 20)
        self.assertEqual(self.tracker.snapshot()["session"]["total"], 0)

        self.tracker.set_paused(False)
        self.tracker.on_key_release(FakeKey(vk=65))
        self.tracker.on_key_press(FakeKey(vk=65))
        self.tracker.on_mouse_click(0, 0, object(), True)
        self.assertEqual(self.tracker.snapshot()["session"]["total"], 2)

    def test_control_keys_toggle_and_quit_without_xp(self) -> None:
        pause = FakeKey(name="f9")
        quit_key = FakeKey(name="f10")
        self.tracker.on_key_press(pause)
        self.assertTrue(self.tracker.snapshot()["paused"])
        self.assertEqual(self.tracker.snapshot()["session"]["total"], 0)
        self.tracker.on_key_release(pause)
        self.tracker.on_key_press(pause)
        self.assertFalse(self.tracker.snapshot()["paused"])
        self.tracker.on_key_press(quit_key)
        self.assertTrue(self.tracker.shutdown_requested.is_set())
        self.assertEqual(self.tracker.snapshot()["session"]["total"], 0)

    def test_click_counts_press_only(self) -> None:
        self.tracker.on_mouse_click(1, 2, object(), True)
        self.tracker.on_mouse_click(1, 2, object(), False)
        self.assertEqual(self.tracker.snapshot()["session"]["click"], 1)

    def test_cursor_distance_uses_remainder_and_rejects_jump(self) -> None:
        self.tracker.on_mouse_move(0, 0)
        self.tracker.on_mouse_move(PIXELS_PER_CURSOR_XP * 0.75, 0)
        self.tracker.on_mouse_move(PIXELS_PER_CURSOR_XP * 1.5, 0)
        snap = self.tracker.snapshot()
        self.assertEqual(snap["session"]["cursor"], 1)
        self.assertAlmostEqual(snap["movement_remainder_pixels"], 500.0)

        self.tracker.on_mouse_move(100000, 0)
        self.assertEqual(self.tracker.snapshot()["session"]["cursor"], 1)

    def test_scroll_uses_absolute_horizontal_and_vertical_steps(self) -> None:
        self.tracker.on_mouse_scroll(0, 0, 3, -4)
        self.tracker.on_mouse_scroll(0, 0, 1, -2)
        snap = self.tracker.snapshot()
        self.assertEqual(snap["session"]["scroll"], 1)
        self.assertAlmostEqual(snap["scroll_remainder_steps"], 0.0)
        self.assertEqual(SCROLL_STEPS_PER_XP, 10.0)

    def test_session_daily_lifetime_and_daily_rollover(self) -> None:
        self.tracker.on_key_press(FakeKey(vk=65))
        first = self.tracker.snapshot()
        self.assertEqual(first["session"]["total"], 1)
        self.assertEqual(first["daily"]["total"], 1)
        self.assertEqual(first["lifetime"]["total"], 1)

        self.day.value = date(2026, 7, 24)
        rolled = self.tracker.snapshot()
        self.assertEqual(rolled["daily"]["total"], 0)
        self.assertEqual(rolled["session"]["total"], 1)
        self.assertEqual(rolled["lifetime"]["total"], 1)

    def test_injected_events_are_ignored(self) -> None:
        key = FakeKey(vk=65)
        self.tracker.on_key_press(key, injected=True)
        self.tracker.on_key_release(key, injected=True)
        self.tracker.on_mouse_click(0, 0, object(), True, injected=True)
        self.tracker.on_mouse_move(0, 0, injected=True)
        self.tracker.on_mouse_move(2000, 0, injected=True)
        self.tracker.on_mouse_scroll(0, 0, 0, 20, injected=True)
        self.assertEqual(self.tracker.snapshot()["session"]["total"], 0)

    def test_pynput_18_callback_signatures_are_accepted(self) -> None:
        key = FakeKey(vk=65)
        self.tracker.on_key_press(key, False)
        self.tracker.on_key_release(key, False)
        self.tracker.on_mouse_click(0, 0, object(), True, False)
        self.tracker.on_mouse_move(0, 0, False)
        self.tracker.on_mouse_scroll(0, 0, 0, 10, False)
        self.assertEqual(self.tracker.snapshot()["session"]["total"], 3)

    def test_persisted_json_contains_only_aggregate_fields(self) -> None:
        self.tracker.on_key_press(FakeKey(vk=65))
        self.tracker.on_mouse_move(100, 200)
        self.tracker.save()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload).lower()
        self.assertIn("aggregate_xp_only", serialized)
        self.assertNotIn('"keys"', serialized)
        self.assertNotIn("cursor_position", serialized)
        self.assertNotIn("window_title", serialized)
        self.assertNotIn("typed", serialized)


class OnlineSyncTests(unittest.TestCase):
    def test_worker_request_uses_a_browser_compatible_user_agent(self) -> None:
        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"ok":true}'

        with patch("computer_warrior.online.urlopen", return_value=Response()) as mocked:
            result = OnlineSyncManager._request("GET", "https://worker.example/api/health", None, None)
        request = mocked.call_args.args[0]
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.get_header("User-agent"), WORKER_USER_AGENT)

    def test_plaintext_session_is_migrated_out_of_json_state(self) -> None:
        class MemoryCredentials:
            def __init__(self) -> None:
                self.values: dict[str, str] = {}

            def read(self, target: str) -> str | None:
                return self.values.get(target)

            def write(self, target: str, token: str) -> None:
                self.values[target] = token

            def delete(self, target: str) -> None:
                self.values.pop(target, None)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "online_sync.json"
            device_id = str(uuid.uuid4())
            path.write_text(json.dumps({
                "schema_version": 1,
                "worker_url": "http://worker.test",
                "device_id": device_id,
                "username": "tanveer_local",
                "session_token": "m" * 40,
            }), encoding="utf-8")
            credentials = MemoryCredentials()
            manager = OnlineSyncManager(path, credential_store=credentials)
            stored = json.loads(path.read_text(encoding="utf-8"))
            target = f"ComputerWarrior.Session.{device_id}"
            self.assertNotIn("session_token", stored)
            self.assertEqual(stored["credential_target"], target)
            self.assertEqual(credentials.values[target], "m" * 40)
            self.assertTrue(manager.summary()["signed_in"])

    def test_open_online_panel_polls_only_the_local_status_endpoint(self) -> None:
        page_path = Path(__file__).resolve().parent.parent / "web" / "index.html"
        page = page_path.read_text(encoding="utf-8")
        self.assertIn("if (onlineDialog.open) await loadOnline();", page)
        self.assertIn("window.setInterval(refreshOpenOnlinePanel, 2000);", page)

    def test_dashboard_game_loop_uses_only_existing_aggregate_metrics(self) -> None:
        page_path = Path(__file__).resolve().parent.parent / "web" / "index.html"
        page = page_path.read_text(encoding="utf-8")
        self.assertIn('id="rankTitle"', page)
        self.assertIn('id="sessionPulse"', page)
        self.assertIn('id="mixSummary"', page)
        self.assertIn("function rankForLevel(level)", page)
        self.assertIn("function renderActivityMix(daily)", page)
        self.assertIn("[['keyboard', 'Keyboard'], ['click', 'Mouse clicks'], ['cursor', 'Cursor travel'], ['scroll', 'Scrolling']]", page)
        self.assertNotIn("key_sequence", page.lower())
        self.assertNotIn("cursor_position", page.lower())

    def test_online_refresh_route_returns_json_instead_of_an_html_404(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tracker = ActivityTracker(AtomicJsonStore(Path(folder) / "stats.json"))
            manager = OnlineSyncManager(Path(folder) / "online_sync.json")
            page_path = Path(__file__).resolve().parent.parent / "web" / "index.html"
            server = LocalDashboardServer(tracker, page_path, 0, manager)
            server.start()
            try:
                request = Request(
                    server.url + "api/online/refresh",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertFalse(payload["signed_in"])
            finally:
                server.stop()

    def test_pending_xp_includes_a_sealed_offline_batch(self) -> None:
        def worker(method: str, url: str, payload: dict[str, object] | None, token: str | None) -> dict[str, object]:
            if url.endswith("/api/auth/login"):
                return {"token": "d" * 40, "account": {"username": "tanveer_local"}}
            if url.endswith("/api/devices"):
                return {"device": {"id": payload["device_id"]}}
            if url.endswith("/api/sync"):
                raise OnlineSyncError("Worker unavailable: test")
            raise AssertionError(f"Unexpected worker call: {method} {url}")

        with tempfile.TemporaryDirectory() as folder:
            manager = OnlineSyncManager(Path(folder) / "online_sync.json", worker)
            manager.login("tanveer_local", "not-sent-to-test", {"lifetime": {}}, "http://worker.test", "Test laptop")
            manager.capture({"lifetime": {"keyboard": 2, "click": 1}})
            summary = manager.sync_pending(refresh_leaderboard=False)
            self.assertEqual(summary["pending_count"], 1)
            self.assertEqual(summary["pending_xp"], 3)
            self.assertIn("unavailable", summary["last_error"])

    def test_normal_sync_batches_five_minutes_without_leaderboard_polling(self) -> None:
        calls: list[tuple[str, str, dict[str, object] | None, str | None]] = []
        clock = [datetime(2026, 7, 23, 0, 0, tzinfo=timezone.utc)]

        def worker(method: str, url: str, payload: dict[str, object] | None, token: str | None) -> dict[str, object]:
            calls.append((method, url, payload, token))
            if url.endswith("/api/auth/login"):
                return {"token": "c" * 40, "account": {"username": "tanveer_local"}}
            if url.endswith("/api/devices"):
                return {"device": {"id": payload["device_id"]}}
            if url.endswith("/api/sync"):
                return {"accepted": True, "idempotent": False, "totals": {"verified_total": 7}}
            if "leaderboard" in url:
                return {"leaderboard": []}
            self.fail(f"Unexpected worker call: {method} {url}")

        with tempfile.TemporaryDirectory() as folder:
            manager = OnlineSyncManager(Path(folder) / "online_sync.json", worker, now=lambda: clock[0])
            manager.login("tanveer_local", "not-sent-to-test", {"lifetime": {}}, "http://worker.test", "Test laptop")
            manager.capture({"lifetime": {"keyboard": 5, "click": 2}})
            self.assertEqual(manager.summary()["pending_count"], 1)

            manager.sync_due()
            self.assertFalse(any(call[1].endswith("/api/sync") for call in calls))

            clock[0] += timedelta(seconds=299)
            manager.sync_due()
            self.assertFalse(any(call[1].endswith("/api/sync") for call in calls))

            clock[0] += timedelta(seconds=1)
            summary = manager.sync_due()
            sync_calls = [call for call in calls if call[1].endswith("/api/sync")]
            self.assertEqual(len(sync_calls), 1)
            self.assertEqual(sync_calls[0][2]["sequence"], 1)
            self.assertEqual(sync_calls[0][2]["xp"], {"keyboard": 5, "click": 2, "cursor": 0, "scroll": 0})
            self.assertEqual(sync_calls[0][2]["duration_seconds"], 300)
            self.assertEqual(summary["pending_count"], 0)
            self.assertEqual(summary["pending_xp"], 0)
            self.assertFalse(any("leaderboard" in call[1] for call in calls))

    def test_new_xp_is_queued_once_then_synced_once(self) -> None:
        calls: list[tuple[str, str, dict[str, object] | None, str | None]] = []

        def worker(method: str, url: str, payload: dict[str, object] | None, token: str | None) -> dict[str, object]:
            calls.append((method, url, payload, token))
            if url.endswith("/api/auth/login"):
                return {"token": "a" * 40, "account": {"username": "tanveer_local"}}
            if url.endswith("/api/devices"):
                return {"device": {"id": payload["device_id"]}}
            if url.endswith("/api/sync"):
                return {"accepted": True, "idempotent": False, "totals": {"verified_total": 3}}
            if "leaderboard" in url:
                return {"leaderboard": [{"rank": 1, "username": "tanveer_local", "verified_total": 3}]}
            self.fail(f"Unexpected worker call: {method} {url}")

        with tempfile.TemporaryDirectory() as folder:
            manager = OnlineSyncManager(Path(folder) / "online_sync.json", worker)
            zero = {"lifetime": {"keyboard": 0, "click": 0, "cursor": 0, "scroll": 0}}
            manager.login("tanveer_local", "not-sent-to-test", zero, "http://worker.test", "Test laptop")
            self.assertNotIn("session_token", (Path(folder) / "online_sync.json").read_text(encoding="utf-8"))
            manager.capture({"lifetime": {"keyboard": 2, "click": 1, "cursor": 0, "scroll": 0}})
            self.assertEqual(manager.summary()["pending_count"], 1)
            manager.capture({"lifetime": {"keyboard": 2, "click": 1, "cursor": 0, "scroll": 0}})
            self.assertEqual(manager.summary()["pending_count"], 1)

            summary = manager.sync_pending()
            self.assertEqual(summary["pending_count"], 0)
            self.assertEqual(summary["account_totals"]["verified_total"], 3)
            sync_calls = [call for call in calls if call[1].endswith("/api/sync")]
            self.assertEqual(len(sync_calls), 1)
            self.assertEqual(sync_calls[0][2]["sequence"], 1)
            self.assertEqual(sync_calls[0][2]["xp"], {"keyboard": 2, "click": 1, "cursor": 0, "scroll": 0})

    def test_switching_account_drops_unsynced_xp_instead_of_misattributing_it(self) -> None:
        def worker(method: str, url: str, payload: dict[str, object] | None, token: str | None) -> dict[str, object]:
            if url.endswith("/api/auth/login"):
                return {"token": "b" * 40, "account": {"username": payload["username"]}}
            if url.endswith("/api/devices"):
                return {"device": {"id": payload["device_id"]}}
            raise AssertionError(f"Unexpected worker call: {method} {url}")

        with tempfile.TemporaryDirectory() as folder:
            manager = OnlineSyncManager(Path(folder) / "online_sync.json", worker)
            manager.login("first_user", "password", {"lifetime": {}}, "http://worker.test", "Test laptop")
            manager.capture({"lifetime": {"keyboard": 9}})
            self.assertEqual(manager.summary()["pending_count"], 1)
            manager.login("second_user", "password", {"lifetime": {"keyboard": 9}}, "http://worker.test", "Test laptop")
            self.assertEqual(manager.summary()["username"], "second_user")
            self.assertEqual(manager.summary()["pending_count"], 0)

    def test_beta_invite_code_is_sent_for_registration_but_not_saved(self) -> None:
        calls: list[dict[str, object]] = []

        def worker(method: str, url: str, payload: dict[str, object] | None, token: str | None) -> dict[str, object]:
            if url.endswith("/api/auth/register"):
                calls.append(dict(payload or {}))
                return {"token": "i" * 40, "account": {"username": "beta_user"}}
            if url.endswith("/api/devices"):
                return {"device": {"id": payload["device_id"]}}
            raise AssertionError(f"Unexpected worker call: {method} {url}")

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "online_sync.json"
            manager = OnlineSyncManager(path, worker)
            manager.register(
                "beta_user",
                "not-saved-password",
                {"lifetime": {}},
                "http://worker.test",
                "Test laptop",
                "invite-code-not-saved",
            )
            self.assertEqual(calls[0]["invite_code"], "invite-code-not-saved")
            self.assertNotIn("invite-code-not-saved", path.read_text(encoding="utf-8"))

    def test_dashboard_contains_a_beta_invite_field(self) -> None:
        root = Path(__file__).resolve().parents[1]
        page = (root / "web" / "index.html").read_text(encoding="utf-8")
        server = (root / "computer_warrior" / "web.py").read_text(encoding="utf-8")
        self.assertIn('id="onlineInviteCode"', page)
        self.assertIn('payload.get("invite_code", "")', server)


class PersistenceTests(unittest.TestCase):
    def test_v001_stats_file_loads_without_migration_or_xp_loss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stats.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "application": "Computer Warrior",
                        "app_version": "0.0.1-hotfix.1",
                        "privacy": "aggregate_xp_only_no_key_or_cursor_content",
                        "day_local": "2026-07-23",
                        "lifetime": {
                            "keyboard": 306,
                            "click": 51,
                            "cursor": 66,
                            "scroll": 20,
                            "total": 443,
                        },
                        "daily": {
                            "keyboard": 306,
                            "click": 51,
                            "cursor": 66,
                            "scroll": 20,
                            "total": 443,
                        },
                        "movement_remainder_pixels": 485.2522,
                        "scroll_remainder_steps": 0.0,
                    }
                ),
                encoding="utf-8",
            )

            loaded = AtomicJsonStore(path).load("2026-07-23")
            self.assertEqual(loaded.source, "primary")
            self.assertEqual(loaded.state.lifetime.total, 443)
            self.assertEqual(loaded.state.daily.total, 443)
            self.assertAlmostEqual(loaded.state.movement_remainder_pixels, 485.2522)

    def test_atomic_save_backup_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stats.json"
            store = AtomicJsonStore(path)
            first = PersistedState(
                day_local="2026-07-23",
                lifetime=MetricTotals(keyboard=5),
                daily=MetricTotals(keyboard=5),
            )
            second = PersistedState(
                day_local="2026-07-23",
                lifetime=MetricTotals(keyboard=8),
                daily=MetricTotals(keyboard=8),
            )
            store.save(first)
            store.save(second)
            self.assertTrue(store.backup_path.exists())
            self.assertEqual(store.load("2026-07-23").state.lifetime.keyboard, 8)

            path.write_text("{corrupt", encoding="utf-8")
            recovered = store.load("2026-07-23")
            self.assertEqual(recovered.source, "backup")
            self.assertEqual(recovered.state.lifetime.keyboard, 5)

            # Saving after recovery repairs the primary without destroying backup.
            store.save(recovered.state)
            repaired = store.load("2026-07-23")
            self.assertEqual(repaired.source, "primary")
            self.assertEqual(repaired.state.lifetime.keyboard, 5)

    def test_temp_files_are_not_left_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = AtomicJsonStore(Path(folder) / "stats.json")
            store.save(
                PersistedState(
                    day_local="2026-07-23",
                    lifetime=MetricTotals(),
                    daily=MetricTotals(),
                )
            )
            self.assertFalse(store.temp_path.exists())
            self.assertFalse(store.backup_temp_path.exists())


class CompatibilityTests(unittest.TestCase):
    def test_version_parser(self) -> None:
        self.assertEqual(_version_tuple("1.8.2"), (1, 8, 2))
        self.assertEqual(_version_tuple("1.8.2.post1"), (1, 8, 2))
        self.assertLess(_version_tuple("1.7.7"), (1, 8, 2))

    def test_dead_listener_error_is_promoted(self) -> None:
        class DeadListener:
            def is_alive(self) -> bool:
                return False

            def join(self, timeout: float = 0) -> None:
                del timeout
                raise TypeError("listener callback failed")

        with self.assertRaisesRegex(RuntimeError, "listener callback failed"):
            _raise_if_listener_stopped(DeadListener(), "Mouse")


@unittest.skipUnless(sys.platform == "win32", "Windows mutex test")
class WindowsMutexTests(unittest.TestCase):
    def test_second_instance_is_rejected(self) -> None:
        name = rf"Local\ComputerWarriorSelfTest_{uuid.uuid4().hex}"
        first = WindowsSingleInstance(name)
        try:
            with self.assertRaises(AlreadyRunningError):
                WindowsSingleInstance(name)
        finally:
            first.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
