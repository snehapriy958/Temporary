# DAY 3 — Complete Controller and AI Model Connectivity Audit

**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Date:** 2026-11-05  
**Branch / HEAD:** `marl-p6-2-curriculum-training` / `1d55856b1d8b53278d142537f43e1c79314993a7`  
**Scope:** Backend, controller, checkpoint, and SUMO integration code only. No frontend or browser inspection was performed. No source, checkpoint, dataset, result, historical database, or prior report was changed. No dependency was installed and no training was run.

## Executive Summary

The non-learning controllers are connected to the SUMO/TraCI runtime: Day 2's bounded checks established Fixed-Time and Coordinated Adaptive execution for all three junctions. The current API exposes those modes alongside PPO and DQN. However, this audit environment has no PyTorch, and importing the actual MARL controller fails with `ModuleNotFoundError: No module named 'torch'`; consequently no PPO, DQN, or MAPPO model was loaded through the application loader, no learned inference was executed, and no learned action was sent to SUMO during this audit.

All discovered checkpoint JSON files parse and have expected junction identities and parameter shapes. That is structural evidence only; it does not prove successful model deserialization or inference. The P6 Stage A `final` files identify seed 55 as the saved model seed and separately record five training seeds, three episodes per seed, and 15 total episodes. They are not aggregate models. The application defaults still point to the historical root PPO/DQN checkpoints, not the Stage A files. MAPPO is implemented in the controller and its Stage A checkpoint schema matches its architecture, but MAPPO is not an accepted API mode and is not instantiated by `MultiIntersectionSimulation`.

## 1. Repository and Audit Environment

Git remained on the stated branch and HEAD. The working tree already contained the P6 source edits, route files, checkpoints/results, lock file and reports documented in the Day 2 record; those were preserved. The requested report path was absent at audit start and is created by this audit.

Checks ran with `.venv-demo\Scripts\python.exe` (Python 3.13.14) and the installed SUMO 1.26.0 tools directory on `PYTHONPATH`. Importing `torch` failed because it is not installed. Importing `traffic_service.ai.marl_controller` failed for the same reason. This is an observed runtime failure, not an inference from the lock file. No package installation was attempted.

Day 2 documented successful backend API and bounded SUMO/TraCI runs for baseline and coordinated modes, using the isolated disposable database. Its existing integration checks are reused as evidence for those two modes; they did not cover learned controllers, emergency preemption, or model inference.

## 2. Runtime and Controller Connectivity

| Mode/controller | Runtime path | Connectivity finding |
|---|---|---|
| Fixed-Time (`baseline`) | API mode validation → simulation service → `MultiIntersectionSimulation` → SUMO signal program / TraCI | **CONNECTED / previously exercised.** Day 2 completed a 120-second API run and focused lifecycle test with J1/J2/J3 state extraction. |
| Coordinated Adaptive (`coordinated`) | API → simulation service → simulation's coordinated-control loop, signal controllers, corridor communication and emergency coordinator | **CONNECTED / previously exercised.** Day 2 completed a 120-second API run and observed coordinated decisions, accepted switch requests, phase changes, and yellow phases at all three junctions. |
| Independent PPO (`marl_ppo`) | API → simulation → `MARLCorridorController(algorithm="ppo")` → one PPO agent per J1/J2/J3 → historical root PPO JSON by default → decision and signal dispatch | **CODE-CONNECTED, RUNTIME-BLOCKED.** Mode and loader path exist, but PyTorch is absent and actual controller import fails. Stage A PPO checkpoints are not selected by the default application path. |
| Double-DQN (`marl_dqn`) | API → simulation → `MARLCorridorController(algorithm="dqn")` → one DQN agent per junction → historical root DQN JSON by default → decision and signal dispatch | **CODE-CONNECTED, RUNTIME-BLOCKED.** Same PyTorch import blocker. Stage A DQN checkpoints are not selected by the default application path. |
| MAPPO / Stage A MAPPO | `MARLCorridorController(algorithm="mappo")` can construct three MAPPO actors and a shared centralized critic; training script also uses the controller | **IMPLEMENTED IN CODE, NOT APPLICATION-SELECTABLE OR RUNTIME-VERIFIED.** API mode allowlist omits `mappo`; simulation instantiates the MARL controller only for PPO/DQN. Package initialization's unconditional PPO/DQN imports prevent reaching MAPPO in this environment. |

The API `POST /api/simulation/start` allowlist is exactly `baseline`, `coordinated`, `marl_ppo`, and `marl_dqn`; `mappo` is rejected before simulation startup. `MultiIntersectionSimulation` independently creates a MARL controller only for `marl_dqn` or `marl_ppo`. The training script's use of MAPPO demonstrates a training path, not production application/API selection.

For PPO/DQN, the application constructs the controller, loads a checkpoint, checks for J1/J2/J3 agents, then at decision intervals calls `decide(..., eval_mode=True)` and `apply_decisions(...)`. `apply_decisions` maps SWITCH to `SignalController.request_switch`, EXTEND to `extend_current_green`, and KEEP to no phase change. The simulation records executed operations. This path is present in code, but it was not reached end-to-end because the package import fails first.

## 3. Checkpoint Inventory and Structural Inspection

The audit enumerated **34 JSON files** under `checkpoints/`: 6 root historical/default PPO/DQN files, 1 P4 validation record, 6 P5 per-seed files, and 21 Stage A P6 files. The Stage A set contains seven files each for DQN, PPO, and MAPPO (`best`, `final`, and seeds 11, 22, 33, 44, 55). Excluding the P4 validation record, 33 are model checkpoint JSONs. All 34 JSON files parsed successfully.

| Family / files | Format and metadata | Observed architecture / status |
|---|---|---|
| Historical root `marl_{ppo,dqn}_corridor.json` | JSON; algorithm and seed 42; no explicit algorithm version or episode metadata | Three agents J1/J2/J3. PPO input 14, hidden widths 64 and 32, three action outputs and scalar value output. DQN dueling Q network input 14, widths 64 and 32, three action outputs. Structurally compatible with current agent state schemas, but actual application loader was not run. These are the application's default checkpoint filenames. |
| Root P5 and v2 `marl_{ppo,dqn}_corridor_{p5,v2}.json` | JSON; explicit versions `5.0-autograd-multiseed` or `2.0-autograd`, seed metadata | Same observed PPO/DQN parameter shapes and J1/J2/J3 mapping. They are not default runtime paths. No load/inference verified. |
| `checkpoints/p5_training/*_seed*_final.json` | JSON; version `5.0-multiseed`, per-file seed | Three-junction PPO/DQN shapes match the corresponding implementations. Not default runtime paths. No load/inference verified. |
| Stage A P6 DQN/PPO: `checkpoints/p6/{dqn,ppo}_stage_a_{best,final,seed11,seed22,seed33,seed44,seed55}.json` | JSON; version tagged `6.2-{algorithm}-stage_a-{best,final,seedN}`; J1/J2/J3; per-seed files retain their seed | Expected per-junction network dimensions: observation 14, three actions; DQN hidden widths 64/64/32; PPO 64/32. The `final` metadata says seeds `[11,22,33,44,55]`, 3 episodes per seed, 15 total episodes, while top-level `seed` is 55. This describes the final seed's saved weights plus run metadata, not a weight average. Not connected to default app checkpoint paths. |
| Stage A P6 MAPPO: `checkpoints/p6/mappo_stage_a_{best,final,seed11,seed22,seed33,seed44,seed55}.json` | JSON; version tagged `6.2-mappo-stage_a-*`; J1/J2/J3; shared critic is present | Per-junction actors use 14 inputs, hidden widths 64/64, three actions. Centralized critic uses 42 corridor features and widths 128/64; the checkpoint also contains shared critic weights. `final` records seed 55, five training seeds, 3 episodes per seed, 15 total. Schema dimensions align with current MAPPO components, but loader/inference was not run. |

**Inventory count note:** directory scan counted 34 total JSON files including `marl_training_validation_p4.json`; 33 are model checkpoint JSONs. The 21-file Stage A collection includes best/final and five per-seed checkpoints for each of three algorithms. Files were read-only inspected; no checkpoint was overwritten.

`MARLCorridorController.load_checkpoint()` reads JSON and invokes each agent's `load_state_dict()`. It checks that required junction IDs exist. MAPPO additionally reads `shared_critic_weights` when constructed as MAPPO. The loader does not validate top-level algorithm identity, architecture/version compatibility, exact junction ordering, or unexpected extra agents before loading. JSON parse and dimensions are encouraging but are not a substitute for exercising these loader functions.

## 4. Actual Model Loading and Inference Results

| Model group | Checkpoint present | Dependencies available | Application loader | Deterministic inference / dispatch | Result |
|---|---:|---:|---:|---:|---|
| Historical PPO | Yes | No (PyTorch missing) | Not run; controller import fails | Not run | **BLOCKED** |
| Historical DQN | Yes | No (PyTorch missing) | Not run; controller import fails | Not run | **BLOCKED** |
| P5/v2 PPO and DQN | Yes | No | Not run | Not run | **BLOCKED** |
| Stage A PPO and DQN | Yes | No | Not run | Not run | **BLOCKED** |
| Stage A MAPPO | Yes | Agent code includes a NumPy fallback, but package-level controller import still requires PPO/DQN modules and fails | Not run through application loader | Not run; no SUMO action dispatched | **BLOCKED** |

The user-specified inference procedure (load with actual application loader, supply a validated observation, repeat deterministic inference, confirm action dispatch, and advance bounded SUMO) could not be executed safely within the existing environment. Installing PyTorch or bypassing the application's package/loader path would alter the authorized test conditions or cease to validate the real application path; neither was done. Therefore the audit makes no claim that a learned checkpoint currently loads or that any learned action reaches SUMO.

## 5. MAPPO Implementation and Availability

| MAPPO criterion | Finding |
|---|---|
| Implemented | **Yes.** `MARLCorridorController` has a MAPPO branch, creates one actor per junction and a shared critic over the 42-value corridor observation; MAPPO training functions are used by the curriculum training script. |
| Instantiable in application environment | **No, currently blocked.** Importing `traffic_service.ai.marl_controller` first imports `.dqn_agent` and `.ppo_agent`; these require PyTorch. The isolated runtime lacks it. |
| Stage A checkpoint shape compatibility | **Structurally consistent.** Observation/action/critic dimensions and expected state keys appear in the JSON files. Actual loading is unverified. |
| Checkpoint loaded and inference performed | **No.** |
| SUMO signal action exercised | **No.** |
| Selectable through API | **No.** `mappo` is absent from the route's valid mode set. |
| Instantiated by simulation runtime | **No.** Simulation runtime branches only for `marl_ppo` and `marl_dqn`. |
| Frontend selectable | **Not inspected by explicit scope.** No frontend or browser files were examined. |

## 6. Safety, Signal Transitions, and Emergency Handling

The source path preserves controller-side safety mediation: learned decisions do not set arbitrary SUMO phases directly. SWITCH goes through `request_switch`, which requests a yellow phase and then transitions to the target green; EXTEND is mediated by `extend_current_green`. Signal controller methods reject or constrain operations when emergency lockout is active. The simulation checks emergency lockout before normal MARL decisions, and coordinated/emergency logic is handled in the simulation and emergency coordinator paths.

The MARL controller also updates `StarvationTracker`, obtains an action mask, and marks starvation-forced switches in the decision result. The simulation has a separate anti-starvation preemption pass before decision-interval policy actions; it requests a switch through `SignalController`. This indicates safety mechanisms are wired in code, but it does not establish that a loaded learned policy cooperates correctly at runtime.

No emergency vehicle scenario, emergency clearance/recovery, anti-starvation replay, physical phase transition, or learned-policy safety test was run in this audit. Day 2's coordinated-control evidence is not evidence for learned mode safety. These behaviors remain unverified for the current isolated runtime.

## 7. Connectivity Classification

| Controller/model | Code implemented | API-selectable | Checkpoint structurally present | Actual load verified | Inference verified | SUMO action verified |
|---|---:|---:|---:|---:|---:|---:|
| Fixed-Time | Yes | Yes | N/A | N/A | N/A | **Yes (Day 2)** |
| Coordinated Adaptive | Yes | Yes | N/A | N/A | N/A | **Yes (Day 2)** |
| Independent PPO, historical default | Yes | Yes | Yes | No | No | No |
| Double-DQN, historical default | Yes | Yes | Yes | No | No | No |
| P6 Stage A PPO | Yes | No separate selector/path | Yes | No | No | No |
| P6 Stage A DQN | Yes | No separate selector/path | Yes | No | No | No |
| P6 Stage A MAPPO | Yes in controller/trainer | **No** | Yes | No | No | No |

## 8. Risks and Known Limitations

- The Day 2 demo environment is deliberately torch-free. The full `traffic_service.ai` package is not importable in that environment because package initialization imports DQN and PPO agent modules even when a MAPPO-only path is desired.
- PPO/DQN API modes point to historical root checkpoint filenames by default. Stage A weights are not automatically selected by the demo application.
- MAPPO exists as training/controller code but is absent from both API mode validation and the simulation constructor's MARL mode branch.
- The checkpoint loader's validation is permissive: it relies on `load_state_dict()` for shape failures and does not enforce declared algorithm/version metadata or reject extra agent IDs.
- Checkpoint architecture inspection was structural JSON analysis, not actual framework loading. No learned deterministic-action repeatability or action-dispatch claim is made.
- Emergency preemption and recovery were not exercised. Existing Day 2 fixed/coordinated runs did not include emergency validation.
- Frontend selection/controls were intentionally not inspected, per the backend-only scope.
- No source changes or tests were added. Prior Day 2 focused checks establish non-learning control paths only.

## 9. Recommended Next Action

**Do not treat learned-controller connectivity as demonstrated yet.** The next authorized task should first resolve the runtime provenance decision for PyTorch in a separate isolated environment, then execute a bounded backend-only checkpoint load, deterministic inference, dispatch, and short SUMO verification for PPO and DQN. MAPPO requires an explicit product decision and separate integration work because the current API/runtime does not expose it. Until those checks pass, use Fixed-Time or Coordinated Adaptive for the demo and keep Stage B NO-GO.

## Evidence Locations

- [`backend/routers/simulation.py`](../../backend/routers/simulation.py): API mode allowlist.
- [`traffic_service/multi_intersection_simulation.py`](../../traffic_service/multi_intersection_simulation.py): runtime mode branches, default checkpoint paths, decision interval and SUMO dispatch.
- [`traffic_service/ai/marl_controller.py`](../../traffic_service/ai/marl_controller.py): agents, MAPPO construction, masking, decision mapping, signal action dispatch and JSON checkpoint load/save.
- [`traffic_service/ai/mappo_agent.py`](../../traffic_service/ai/mappo_agent.py): MAPPO inference and state serialization.
- [`traffic_service/signal_controller.py`](../../traffic_service/signal_controller.py): constrained signal switch/extension and emergency lockout.
- [`docs/DEMO/02_DAY_2_RUNTIME_AND_INTEGRATION_REPORT.md`](02_DAY_2_RUNTIME_AND_INTEGRATION_REPORT.md): isolated runtime, Fixed-Time and Coordinated Adaptive evidence.
