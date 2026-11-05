# P6.7 Final Recording Runbook

**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Branch / HEAD:** `marl-p6-2-curriculum-training` / `1d55856b1d8b53278d142537f43e1c79314993a7`  
**Decision:** **CONDITIONAL GO** for the backend recording workflow. Use the combined runtime below; the documented `.venv-demo` interpreter alone cannot run PPO/DQN. Frontend/browser readiness remains for the owner to review separately.

## Scope and repository state

P6.7 preserved the pre-existing modified and untracked project work. It did not modify source files, frontend files, checkpoints, either virtual environment, training data, or historical P6.4–P6.6 evidence. It did not start training or commit changes. The only P6.7 additions are this runbook and uniquely named rehearsal scripts/logs/results under `scratch/`.

At start and finish, the branch and HEAD remained the values above. The prior worktree changes remained present; P6.7 added only its new runbook and scratch evidence. `git diff --check` passed.

## Environment startup verification

The documented environment variables resolved correctly:

```powershell
$env:SUMO_HOME = "C:\Program Files (x86)\Eclipse\Sumo"
$env:PYTHONPATH = "$env:SUMO_HOME\tools;$PWD"
$env:DATABASE_URL = "sqlite:///./demo_audit_disposable.db"
```

With `.venv-demo`, Uvicorn started, `/api/health` returned `status=ok`, SUMO was available as version 1.26.0, TraCI and sumolib imported from `SUMO_HOME\tools`, and the backend database URL was the disposable database. The frontend command also started Vite 5.4.21; `http://127.0.0.1:5173/` returned HTTP 200. No browser was opened, and no UI behavior is claimed.

The first live five-run attempt exposed a runtime gap: `.venv-demo` does not contain PyTorch. Fixed-Time and Coordinated Adaptive ran, but PPO startup returned HTTP 500 with `No module named 'torch'`. This failed raw output is preserved. The corrected, isolated launch uses the Torch-enabled `.venv-marl-audit` interpreter and adds the existing demo backend packages to `PYTHONPATH`; no packages or environments were changed.

Use this configuration for the full recording sequence:

```powershell
$env:SUMO_HOME = "C:\Program Files (x86)\Eclipse\Sumo"
$env:PYTHONPATH = "$env:SUMO_HOME\tools;$PWD\.venv-demo\Lib\site-packages;$PWD"
$env:DATABASE_URL = "sqlite:///./demo_audit_disposable.db"
.\.venv-marl-audit\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info
```

This live Uvicorn configuration passed `/api/health` and the five-run HTTP/WebSocket rehearsal. It combines already-existing environments; do not replace the command with `.venv-demo` alone for a PPO/DQN recording.

## Five-run sequential rehearsal

The five requests were submitted in the requested order through the live HTTP API. WebSocket telemetry captured junction phases, vehicle presence/speed, decisions, and emergency state. Each run reached its requested horizon before the next run started; every run ID was unique and every terminal API status was `COMPLETED` with no backend error. The separate stop-endpoint probe is recorded below.

| Run | Horizon / seed | Result | Observations |
|---|---:|---|---|
| Fixed-Time (`baseline`) | 120 s / 99 | PASSED | J1/J2/J3 phase IDs 0–3 observed; vehicles had positive speed. 40 vehicles remained and no corridor trip completed within this short horizon. |
| Coordinated Adaptive (`coordinated`) | 120 s / 99 | PASSED | Phase IDs 0–3 observed at all junctions; positive vehicle speed; 11 completed corridor trips. |
| Stage A PPO (`marl_ppo`) | 90 s / 99 | PASSED | Explicit P6 PPO checkpoint accepted; live phase activity at all junctions; decision records covered J1/J2/J3. Exact loaded parameter equality was also verified in the instrumented application run. |
| Stage A Double-DQN (`marl_dqn`) | 90 s / 99 | PASSED | Explicit P6 DQN checkpoint accepted; live phase activity at all junctions; decision records covered J1/J2/J3. Exact loaded parameter equality was also verified in the instrumented application run. |
| Emergency (`coordinated`) | 500 s / 42 | PASSED | Ambulance event completed with 37 s traversal; all three priority greens, J2 yellow clearance, no conflicting approach green, and post-release coordinated decisions observed. |

The in-process instrumented sequence independently confirmed each run's SUMO process handle was reaped, backend simulation state was cleared, and the worker stopped before the next start. The live HTTP rehearsal also verified SUMO PIDs were absent after each run. It recorded positive-speed telemetry in every mode. PPO showed only phases 0–2 at J2/J3 during the 90-second window; this is phase activity, not a failed junction.

Live smoke metrics are not a performance comparison:

| Run | Throughput | Mean speed | Cumulative delay |
|---|---:|---:|---:|
| Fixed-Time, 120 s | 0 completed corridor trips | 16.66 km/h | 986 veh·s |
| Coordinated Adaptive, 120 s | 11 trips | 43.19 km/h | 485 veh·s |
| PPO, 90 s | 4 trips | 25.96 km/h | 392 veh·s |
| Double-DQN, 90 s | 9 trips | 38.47 km/h | 299 veh·s |
| Emergency Coordinated, 500 s | 92 trips | 25.85 km/h | 5,977 veh·s |

These short, seeded runs only demonstrate runtime behavior. Do not use them to claim convergence or controller superiority. The fixed-time run did show moving vehicles by positive speed, but no full corridor trips completed in its 120-second window.

## Exact API requests

Send each JSON body to `POST http://127.0.0.1:8000/api/simulation/start`. Wait for `/api/simulation/status` to report `COMPLETED` before starting the next request. The calls used the actual API; the JSON bodies were:

### Run 1 — Fixed-Time

```json
{"mode":"baseline","duration":120,"seed":99,"step_length":1,"decision_interval":5,"enable_emergency":false}
```

### Run 2 — Coordinated Adaptive

```json
{"mode":"coordinated","duration":120,"seed":99,"step_length":1,"decision_interval":5,"enable_emergency":false}
```

### Run 3 — P6 PPO

```json
{"mode":"marl_ppo","duration":90,"seed":99,"step_length":1,"decision_interval":5,"enable_emergency":false,"checkpoint_path":"checkpoints/p6/ppo_stage_a_best.json"}
```

### Run 4 — P6 Double-DQN

```json
{"mode":"marl_dqn","duration":90,"seed":99,"step_length":1,"decision_interval":5,"enable_emergency":false,"checkpoint_path":"checkpoints/p6/dqn_stage_a_best.json"}
```

### Run 5 — Emergency vehicle

```json
{"mode":"coordinated","duration":500,"seed":42,"step_length":1,"decision_interval":5,"enable_emergency":true}
```

The observed ambulance route edges were `172853382#2` → `172853382#3` → `1148717038#0` → `40696223#1`. Detection occurred at t=421 s and clearance at t=458 s. It was already on the priority phase at J1 and J3; J2 displayed yellow through its 4-second clearance (next switch at t=426 s) before priority green was observed at t=427 s. No conflicting approach lane was green in the captured priority states. All locks were released, and coordinated decisions resumed. The 500-second endpoint returned one completed event with traversal duration 37 seconds.

## Stop endpoint and SUMO return-code investigation

A separate bounded API stop probe started Fixed-Time and called `POST /api/simulation/stop` at simulation time 1 s. The endpoint returned HTTP 200, status became `STOPPED`, worker and simulation state cleared, SUMO PID was cleared, and the process was reaped.

All five natural-completion runs and the explicit stop probe returned SUMO code **1**, with no backend error. The source path in `traffic_service/sumo_manager.py` closes the TraCI connection using `wait=False`, calls `traci.close()`, and then invokes `Popen.terminate()` if the child is still alive. Instrumenting the stop probe's exact SUMO process confirmed that `terminate()` was called and the child was reaped with code 1. The live sequence logs contain no SUMO fatal error or worker traceback for the five successful runs. Their API states were `COMPLETED`, `error=null`; the stop probe correctly returned `STOPPED`, `error=null`.

Conclusion: code 1 reflects the current manager's terminate-after-TraCI-close cleanup path; it is not a reported simulation failure. Do not change or mask the exit code for this demo. The process is reaped, but its exit status is not zero and should be disclosed if asked.

## Startup, stop, and recovery commands

Start the API with the combined runtime command above. In another terminal start the frontend, if the owner has completed the UI review:

```powershell
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173 --strictPort
```

Check health at `GET http://127.0.0.1:8000/api/health`. Start the five runs one at a time and wait for terminal status. Each completed run already cleans up automatically. If a run remains active or must be stopped early, call:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/simulation/stop"
```

Wait for `/api/simulation/status` to show `running=false` and `pid=null` before another run. If startup fails, inspect API logs and `/api/health`; for PPO/DQN confirm Uvicorn was launched by `.venv-marl-audit` with the demo site-packages and SUMO tools on `PYTHONPATH`. Stop Uvicorn with Ctrl+C in the recording terminal after stopping any active simulation. Confirm ports 8000/5173 are released before restarting. Do not use or modify `traffic_dashboard.db`.

## Eight-minute recording script

| Segment | Time | On-screen plan and supported narration |
|---|---:|---|
| Problem statement | 45 s | Introduce congestion and the Silk Board three-junction corridor. State the project goal: coordinate signals and evaluate fixed, adaptive, and learned control. |
| Architecture and stack | 60 s | Show the system diagram or code architecture: FastAPI API, SUMO/TraCI simulation, J1/J2/J3 controllers, PPO/DQN checkpoints. Explain training is offline and these are inference runs. |
| Three-junction simulation | 90 s | Show the live corridor and identify J1, J2, J3. Point to vehicle movement, active signal phases, queues, and current mode. Do not infer real-world deployment readiness from simulation. |
| Fixed-Time and Coordinated Adaptive | 90 s | Select Fixed-Time, then Coordinated Adaptive, waiting for each run to finish before starting the next. Point out phase activity and live traffic metrics. Label values as this run's observations, not a controlled performance result. |
| PPO and Double-DQN | 90 s | Select PPO with `checkpoints/p6/ppo_stage_a_best.json`, then Double-DQN with `checkpoints/p6/dqn_stage_a_best.json`. Explain J1/J2/J3 agents act through the application API; point to live phase changes and decisions. |
| Emergency priority | 60 s | Run coordinated mode with emergency enabled and duration 500 s. Explain the ambulance departs at t=420, is detected at t=421, traverses all three junctions, receives observed J2 yellow clearance and priority green, then control recovers. |
| Metrics and limitations | 45 s | Explain throughput, queue, mean speed, corridor travel time when trips exist, cumulative delay in veh·s, CO₂ in kg, NOx in g, and estimated fuel in L under the configured 0.750 kg/L reference. Distinguish live run metrics from archived benchmark summaries. |
| Conclusion | 30 s | Summarize verified controller/API behavior and emergency traversal. State that smoke runs do not prove superiority or convergence and that frontend review is separate. |

## Remaining limitations and decision

- `.venv-demo` alone starts the API but cannot import PyTorch for PPO/DQN. Use the combined runtime command in this runbook.
- The frontend dev server's startup and HTTP root were checked; no browser UI, visuals, or recording capture were validated. Owner review remains required.
- The 120/90/500-second live runs are smoke/rehearsal evidence, not statistical evaluation or proof of learned-policy quality.
- Fixed-Time moved vehicles but had no completed corridor trips in 120 seconds.
- SUMO child return code is 1 under the existing cleanup policy, although processes were reaped and the backend reported no errors.
- Existing dependency versions and the external SUMO installation remain machine-specific; this milestone did not alter or reinstall them.

**Recording decision: CONDITIONAL GO.** The backend five-run workflow passed through live HTTP/WebSocket using the combined runtime, and the stop endpoint passed its separate probe. Proceed after the owner completes the frontend review; disclose the limitations above. No claim of frontend readiness is made.

## Raw evidence

- `scratch/p6_7_live_http_rehearsal_results2.json` and `scratch/p6_7_live_http_rehearsal_raw2.txt` — actual live HTTP/WebSocket sequential run evidence.
- `scratch/p6_7_uvicorn_stderr2.txt` — combined-runtime Uvicorn startup and requests.
- `scratch/p6_7_sequential_rehearsal_results.json` and `scratch/p6_7_sequential_rehearsal_raw.txt` — instrumented five-run phase, movement, emergency route, and process evidence.
- `scratch/p6_7_stop_endpoint_results.json` and `scratch/p6_7_stop_endpoint_raw.txt` — HTTP stop and terminate-call probe.
- `scratch/p6_7_live_http_rehearsal_raw.txt`, `scratch/p6_7_uvicorn_stderr.txt`, and `scratch/p6_7_uvicorn_stdout.txt` — preserved failed `.venv-demo`-only PPO startup attempt (`No module named 'torch'`).
