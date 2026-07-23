# Computer Warrior v0.0.7 Automated QA Notes

- Result: **PASS**
- Generated: 2026-07-23T05:44:03.438084+00:00
- Python: 3.13.2
- Platform: Windows-11-10.0.26200-SP0
- pynput in test environment: 1.8.2
- Required Windows runtime dependency: pynput 1.8.2+
- Tests run: 29
- Failures: 0
- Errors: 0
- Skipped: 0

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
- Direct loading of v0.0.1-hotfix.1 schema-version-1 stats without XP loss.

## Test runner output

```text
test_dead_listener_error_is_promoted (test_core.CompatibilityTests.test_dead_listener_error_is_promoted) ... ok
test_version_parser (test_core.CompatibilityTests.test_version_parser) ... ok
test_dashboard_shows_categories_before_totals_for_every_scope (test_core.DashboardTests.test_dashboard_shows_categories_before_totals_for_every_scope) ... ok
test_dashboard_visibly_changes_to_paused (test_core.DashboardTests.test_dashboard_visibly_changes_to_paused) ... ok
test_live_dashboard_rewrites_fixed_rows_and_skips_duplicates (test_core.DashboardTests.test_live_dashboard_rewrites_fixed_rows_and_skips_duplicates) ... ok
test_web_payload_exposes_only_aggregate_dashboard_values (test_core.DashboardTests.test_web_payload_exposes_only_aggregate_dashboard_values) ... ok
test_beta_invite_code_is_sent_for_registration_but_not_saved (test_core.OnlineSyncTests.test_beta_invite_code_is_sent_for_registration_but_not_saved) ... ok
test_dashboard_contains_a_beta_invite_field (test_core.OnlineSyncTests.test_dashboard_contains_a_beta_invite_field) ... ok
test_new_xp_is_queued_once_then_synced_once (test_core.OnlineSyncTests.test_new_xp_is_queued_once_then_synced_once) ... ok
test_normal_sync_batches_five_minutes_without_leaderboard_polling (test_core.OnlineSyncTests.test_normal_sync_batches_five_minutes_without_leaderboard_polling) ... ok
test_online_refresh_route_returns_json_instead_of_an_html_404 (test_core.OnlineSyncTests.test_online_refresh_route_returns_json_instead_of_an_html_404) ... ok
test_open_online_panel_polls_only_the_local_status_endpoint (test_core.OnlineSyncTests.test_open_online_panel_polls_only_the_local_status_endpoint) ... ok
test_pending_xp_includes_a_sealed_offline_batch (test_core.OnlineSyncTests.test_pending_xp_includes_a_sealed_offline_batch) ... ok
test_plaintext_session_is_migrated_out_of_json_state (test_core.OnlineSyncTests.test_plaintext_session_is_migrated_out_of_json_state) ... ok
test_switching_account_drops_unsynced_xp_instead_of_misattributing_it (test_core.OnlineSyncTests.test_switching_account_drops_unsynced_xp_instead_of_misattributing_it) ... ok
test_atomic_save_backup_and_recovery (test_core.PersistenceTests.test_atomic_save_backup_and_recovery) ... ok
test_temp_files_are_not_left_after_success (test_core.PersistenceTests.test_temp_files_are_not_left_after_success) ... ok
test_v001_stats_file_loads_without_migration_or_xp_loss (test_core.PersistenceTests.test_v001_stats_file_loads_without_migration_or_xp_loss) ... ok
test_click_counts_press_only (test_core.TrackerTests.test_click_counts_press_only) ... ok
test_control_keys_toggle_and_quit_without_xp (test_core.TrackerTests.test_control_keys_toggle_and_quit_without_xp) ... ok
test_cursor_distance_uses_remainder_and_rejects_jump (test_core.TrackerTests.test_cursor_distance_uses_remainder_and_rejects_jump) ... ok
test_held_key_repeat_is_suppressed (test_core.TrackerTests.test_held_key_repeat_is_suppressed) ... ok
test_injected_events_are_ignored (test_core.TrackerTests.test_injected_events_are_ignored) ... ok
test_pause_resume_blocks_all_xp (test_core.TrackerTests.test_pause_resume_blocks_all_xp) ... ok
test_persisted_json_contains_only_aggregate_fields (test_core.TrackerTests.test_persisted_json_contains_only_aggregate_fields) ... ok
test_pynput_18_callback_signatures_are_accepted (test_core.TrackerTests.test_pynput_18_callback_signatures_are_accepted) ... ok
test_scroll_uses_absolute_horizontal_and_vertical_steps (test_core.TrackerTests.test_scroll_uses_absolute_horizontal_and_vertical_steps) ... ok
test_session_daily_lifetime_and_daily_rollover (test_core.TrackerTests.test_session_daily_lifetime_and_daily_rollover) ... ok
test_second_instance_is_rejected (test_core.WindowsMutexTests.test_second_instance_is_rejected) ... ok

----------------------------------------------------------------------
Ran 29 tests in 1.119s

OK
```

## Environment limitation

The automated core, local-dashboard and batching tests are cross-platform. Global Windows input hooks, the actual Win32 mutex and browser interaction must also be smoke-tested on the target Windows machine using `run_self_tests.bat` and `launch_web_dashboard.bat`. The package pins pynput 1.8.2 for Python 3.13 compatibility.
