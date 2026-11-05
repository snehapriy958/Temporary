# P6.5 — Checkpoint Selection and API Integration Report

**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Date:** 2026-11-05  
**Branch / HEAD at start:** `marl-p6-2-curriculum-training` / `1d55856b1d8b53278d142537f43e1c79314993a7`  
**Database for API runs:** `sqlite:///./demo_audit_disposable.db`  
**Training:** Not run. **Stage B/C:** Not started. **MAPPO:** Not integrated.

## Summary

The API now accepts the two approved relative checkpoint paths and passes the resolved, validated path through a per-worker thread argument into the correct `MultiIntersectionSimulation` instance. The default remains the historical root checkpoint when `checkpoint_path` is omitted. API validation rejects traversal, unsupported paths, incompatible controller/checkpoint pairs, missing or malformed files, and explicit checkpoints used with non-MARL modes.

Bounded API-initiated PPO and Double-DQN runs both completed 90 simulated seconds. For each run, the runtime constructed J1/J2/J3 agents, logged the P6 Stage A version, made 19 decision/dispatch calls, had accepted signal-switch operations, showed SUMO phase IDs changing at all three junctions, and exited with SUMO stopped. Every loaded agent's parameters exactly matched its corresponding arrays in the requested JSON checkpoint. Fixed-Time and Coordinated Adaptive integration regression tests passed.

The focused checkpoint tests passed (18/18). The combined regression selection had **37 passed and 1 failed**. The failure is an existing test setup issue: `test_action_routing_keep_switch_extend` sets the obsolete `_green_start_time` field, while the current implementation uses `_last_phase` and `_phase_start_time`; its first timing query therefore correctly initializes elapsed time to zero and rejects an immediate switch. I did not weaken or edit that assertion. Emergency preemption was not live-tested; the bounded learned runs used `enable_emergency=false`.

## 1. Files Changed for P6.5

Implementation changes:

- `backend/schemas.py` — optional field and strict approved-path schema validation.
- `backend/simulation_service.py` — project-root resolution, allowlist/existence/algorithm checks, and per-worker checkpoint argument propagation.
- `backend/routers/simulation.py` — pass-through and HTTP 400 mapping for service validation failures.
- `tests/test_checkpoint_api_selection.py` — focused API, service validation, default behavior, traversal, mismatch, and signal-safety tests.

New audit evidence (no existing P6.4 evidence was overwritten):

- `scratch/p6_5_checkpoint_api_audit.py` — bounded API-to-SUMO verification harness.
- `scratch/p6_5_api_run_results_verified3.json` — structured PPO/DQN run evidence.
- `scratch/p6_5_api_runtime_verified3_raw.txt` — raw verified API/SUMO logs.
- `scratch/p6_5_focused_tests_final2_raw.txt` — final focused test output.
- `scratch/p6_5_regression_tests_final2_raw.txt` — final combined regression output.
- `scratch/p6_5_checkpoint_api_unit_tests_demo_env.txt`, `scratch/p6_5_api_runtime_raw.txt`, `scratch/p6_5_api_runtime_raw_retry1.txt`, and `scratch/p6_5_regression_tests_raw.txt` — preserved initial attempts, including environment/instrumentation issues described below.

Pre-existing modified source, routes, training artifacts, checkpoints, results, reports, environments, and database were preserved. No branch switch, commit, reset, clean, stash, or checkpoint write occurred. `git diff --check` completed without whitespace errors; Git printed only existing line-ending notices.

## 2. Implementation and Validation Behavior

The API accepts these values for `checkpoint_path`:

- `checkpoints/p6/ppo_stage_a_best.json`
- `checkpoints/p6/dqn_stage_a_best.json`

The schema normalizes Windows separators to `/` and rejects every other supplied path. The service independently enforces an exact allowlist by controller mode, resolves the candidate against `BASE_DIR`, verifies the resolved file remains inside `checkpoints/p6/`, verifies the file exists and parses as JSON, then checks its top-level algorithm (`ppo` or `dqn`) against the selected mode. Unsupported schema values return HTTP 422; algorithm mismatches, checkpoints for non-MARL modes, and service-level file validation failures return HTTP 400. An invalid explicit path fails; it does not fall back to a historical checkpoint.

The resolved path is passed as an argument to that simulation's worker thread. It is not written into singleton mutable checkpoint state. The worker passes that immutable argument to the `MultiIntersectionSimulation` constructor. When omitted, the worker passes `None`, preserving the existing constructor behavior and historical default filenames (`checkpoints/marl_ppo_corridor.json` and `checkpoints/marl_dqn_corridor.json`). Existing mode allowlist and response body remain unchanged.

Example PPO request:

```json
{
  "mode": "marl_ppo",
  "duration": 90,
  "seed": 99,
  "checkpoint_path": "checkpoints/p6/ppo_stage_a_best.json"
}
```

Example DQN request:

```json
{
  "mode": "marl_dqn",
  "duration": 90,
  "seed": 99,
  "checkpoint_path": "checkpoints/p6/dqn_stage_a_best.json"
}
```

## 3. API and SUMO Integration Results

The runs used the existing torch-enabled `.venv-marl-audit` interpreter and read-only package contents from `.venv-demo` for FastAPI and backend dependencies. Neither virtual environment was changed or installed into. Both used the required disposable database. Each run disabled emergency injection and used seed 99, a 1-second SUMO step, a 5-second decision interval, and a 90-second horizon.

| Check | PPO | Double-DQN |
|---|---|---|
| API accepted explicit approved path | **PASSED** | **PASSED** |
| `MultiIntersectionSimulation` mode | `marl_ppo` | `marl_dqn` |
| Checkpoint version logged | `6.2-ppo-stage_a-best` | `6.2-dqn-stage_a-best` |
| Exact equality of all three agents' checkpoint parameter arrays | **PASSED** | **PASSED** |
| J1/J2/J3 agents constructed | **PASSED** | **PASSED** |
| SUMO/TraCI reached 90 seconds | **PASSED** | **PASSED** |
| Decisions and action dispatch | 19 intervals, all three junctions | 19 intervals, all three junctions |
| Accepted switch operation observed | **PASSED** | **PASSED** |
| SUMO phase IDs observed | J1: 0,1,2,3; J2: 0,1,2; J3: 0,1,2 | J1/J2/J3: 0,1,2,3 |
| SUMO process stopped after completion | **PASSED** | **PASSED** |

The phase telemetry was collected from the actual simulation service's `get_states()` path, not inferred from successful API startup. Exact parameter comparisons for J1/J2/J3 confirm the selected file's weights were installed; the controller constructor and runtime version logs identify the requested P6 checkpoint. Raw decision logs include actions, per-junction operations, and fallback flags.

## 4. Test and Regression Results

| Test/check | Status | Evidence |
|---|---|---|
| Approved PPO/DQN API values forwarded | **PASSED** | Focused tests, 18 passed total |
| Omitted path preserves default (`None`) | **PASSED** | Focused API test and unchanged default constructor behavior |
| Unsupported paths and traversal rejected | **PASSED** | Schema validation tests |
| Algorithm/controller mismatch rejected | **PASSED** | Service and API HTTP 400 tests |
| Signal min-green, max-green, yellow clearance, emergency lock gates | **PASSED** | New direct `SignalController` regression test |
| Fixed-Time lifecycle and state extraction | **PASSED** | `tests/test_simulation_integration.py` |
| Coordinated Adaptive stepping | **PASSED** | `tests/test_simulation_integration.py` |
| MARL dispatch, emergency-lock behavior, checkpoint and live stepping checks | **PARTIAL** | Remaining tests passed; one pre-existing test failure below |
| P6 reward and anti-starvation safety tests | **PASSED** | Included in combined regression selection |
| Combined targeted regression selection | **FAILED** | 37 passed, 1 failed |
| Emergency vehicle preemption through a live scenario | **NOT RUN** | Learned API runs explicitly used `enable_emergency=false` |

The single failing assertion is in `tests/test_marl_runtime_dispatch.py::test_action_routing_keep_switch_extend`. The test sets `ctrl._green_start_time = 0.0`, but current `SignalController.get_green_elapsed()` tracks `_last_phase` and `_phase_start_time`. Since the test has not initialized the current phase tracker, `request_switch()` initializes it at the switch timestamp and reports zero elapsed; the min-green guard rejects the request. The test's fixture is stale relative to the already-modified controller implementation. It was not changed or weakened. The actual API runs subsequently observed real phase transitions at all junctions.

The first combined test attempt also hit pytest's default temporary-directory permission error. The test suite was rerun with `--basetemp` under `scratch/`; the final run had no temp-directory errors. The first runtime harness attempt lacked FastAPI in `.venv-marl-audit`; a later run reused `.venv-demo` site packages without modifying either environment. An initial telemetry wrapper observed no phase IDs because the backend worker advances TraCI directly rather than calling `sim.step()`; that raw attempt was preserved and the harness corrected to observe `get_states()`. Only the corrected verified run is used for the PASS results above.

## 5. Safety and Cleanup

Source and test evidence confirms the existing 15-second minimum green, 60-second maximum green, 4-second yellow clearance, action-mask/anti-starvation integration, and emergency lockout gates remain in place. The new direct safety test covers min-green rejection before 15 seconds, yellow transition on an accepted switch, no immediate transition from yellow to another green, max-green extension rejection at 60 seconds, and emergency-lock rejection.

The API simulations confirmed actual phase changes and no fallback-only execution. Windows process checks found both captured SUMO PIDs absent after completion; the structured run record also shows API status `COMPLETED`, `pid=null`, and `sumo_running_after_completion=false` for both runs.

Emergency preemption and clearance/recovery are not claimed as live-verified. No emergency was injected in these 90-second tests.

## 6. Test Classification

- **PASSED:** 18 focused P6.5 tests.
- **PASSED:** API-initiated PPO Stage A run and API-initiated DQN Stage A run, including checkpoint identity, inference dispatch, observed phase changes, and process cleanup.
- **PASSED:** Fixed-Time and Coordinated Adaptive integration checks.
- **PASSED:** P6 reward/anti-starvation tests and the remaining MARL runtime-dispatch tests in the selected suite.
- **FAILED:** One existing action-routing unit test because it initializes the obsolete `_green_start_time` field; failure details are preserved above and in the raw pytest output.
- **NOT RUN:** Live emergency preemption/clearance scenario.

## 7. Remaining Before Recording the Demo Video

The backend API can now select and run both P6 Stage A PPO and DQN checkpoints. Before recording, resolve or explicitly accept the stale signal-controller unit-test fixture failure, and decide whether the video will show checkpoint selection via direct API request or whether a separately scoped frontend change is wanted. If the video depicts an ambulance/emergency preemption, run a separate live emergency scenario first; this report does not verify it. Fixed-Time and Coordinated Adaptive remain available and their selected regressions passed.
