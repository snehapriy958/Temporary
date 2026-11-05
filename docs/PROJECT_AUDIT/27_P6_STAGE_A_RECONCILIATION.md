# P6.2.1 — Stage A Results and Safety Reconciliation

**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Branch / baseline:** `marl-p6-2-curriculum-training` / `1d55856`  
**Scope:** Read-only reconciliation of the existing Stage A run, except for this report. No training was launched, and no existing route, result, checkpoint, or historical audit artifact was changed.

## Executive finding

Stage A artifacts represent **three completed episodes per seed** for MAPPO, PPO, and Double-DQN, and one Coordinated Adaptive reference episode per seed, for seeds `[11, 22, 33, 44, 55]`. This is the recorded experimental budget; the data does not indicate an interrupted run. Aggregate records contain 89 PPO, 40 MAPPO, and 30 DQN starvation interventions.

The reported 65–66 second maxima are the **raw red timer**, which counts red time whether or not an approach has a queue. The separate queued-red maxima are 28–59 seconds across learning runs, below the configured 60 second threshold. Therefore the recorded 66 second raw maximum is not evidence of a queued approach violating the safety threshold. The stored artifacts do not contain per-second phase traces, so the precise cause of each 65/66 second raw maximum cannot be reconstructed from this run. The one-second timer sampling and the four-second yellow interval can account for boundary-sized differences, but this is an interpretation of the implementation and aggregates, not a replay-confirmed event.

**Stage B recommendation: NO-GO pending verification.** Most importantly, the requested junction/approach event attribution and action-level switch execution evidence are not retained in the Stage A files. Actual application checkpoint loading/inference also remains unverified because the available Python installation lacks NumPy. No retraining or threshold change is recommended as part of this reconciliation.

## 1. Stage A result inventory

Files under `results/p6/` include pilot and curve CSV/JSON files for all four algorithms, plus `stage_a_pilot_summary.json` and `stage_a_stage_summary.json`. The full curves contain 15 rows each for MAPPO, PPO, and DQN (five seeds × three episodes), and five coordinated reference rows (one per seed). The full summary reports the same counts. Existing P6 checkpoints contain best, final, and per-seed files for MAPPO, PPO, and DQN.

| Algorithm | Episode 1 events | Episode 2 | Episode 3 | Total | Per-seed totals (11, 22, 33, 44, 55) |
|---|---:|---:|---:|---:|---|
| PPO | 37 | 28 | 24 | **89** | 15, 14, 33, 11, 16 |
| MAPPO | 21 | 13 | 6 | **40** | 19, 12, 3, 1, 5 |
| Double-DQN | 25 | 4 | 1 | **30** | 9, 7, 5, 3, 6 |
| Coordinated Adaptive | 0 | — | — | **0** | 0, 0, 0, 0, 0 |

Intervention frequency decreased across episodes in aggregate for each learning algorithm. PPO was not monotonic per seed: seed 33 recorded 15, 11, and 7 events; seed 55 recorded 4, 7, and 5. The run shows improvement in aggregate event counts, not convergence or stable safety performance.

Per-episode PPO recorded 87–99 completed trips, mean queue 2.88–4.75 vehicles, and cumulative delay 3,633–5,705 vehicle-seconds. Across the 15 records, PPO averaged 94.67 completed trips, 3.76 mean queue, and 4,506.3 vehicle-seconds delay; MAPPO averaged 96.6 trips, 3.09 queue, and 3,707.9 delay; DQN averaged 97.13 trips, 2.45 queue, and 2,941.4 delay. Coordinated Adaptive averaged 96.6 trips, 2.23 queue, and 2,670.6 delay over its five reference runs. These are descriptive Stage A results, not paired inferential comparisons; the algorithms’ records are not a held-out evaluation design.

### Interpretation of intervention counts

The curves store only `starvation_events` as a count. They do not serialize each `StarvationEvent`, and do not persist event timestamps, junction IDs, approaches, queue values, or the selected policy action. Thus the requested breakdown by junction and approach, exact per-junction frequency, and KEEP-versus-EXTEND choices cannot be derived from the saved files. It would be unsafe to infer these from the aggregate counts.

The implementation has a step-level safety path in `MultiIntersectionSimulation.step()`: after updating the tracker each simulation step, it checks starved approaches and, when the signal can switch, calls `get_action_mask()` to record the intervention and calls `request_switch()` for that approach. The normal decision path also applies policy actions at the configured five-second decision interval. This code supports the intended forced-switch behavior, but the results do not log the decision/action, switch return value, or subsequent green transition for each event. Hence execution is **code-path supported, not empirically verified event by event**.

## 2. Anti-starvation and signal timing analysis

Relevant configured values are a 60 second starvation threshold, one-second simulation step, five-second policy decision interval, and four-second yellow clearance. `StarvationTracker.update()` is called after each simulation step. It increments `red_elapsed` whenever the current phase is not the monitored approach’s green phase; it increments `queued_red_elapsed` only while the cached queue meets the minimum queue threshold. A green phase resets both counters. Repeated calls at the same simulation timestamp are guarded against double accumulation.

`run_episode()` samples the maxima from those timer dictionaries after each five-step control interval. Consequently:

- `max_red_duration_s` includes **unqueued** red approaches and red time during yellow clearance. It is not the maximum queued wait and is not by itself a violation of the queued-approach guarantee. Although the tracker updates each second, the training script samples the current timer maxima only after each five-step decision block; a value that rose and reset between reads could be missed. These are sampled maxima, not a complete phase trace.
- `max_queued_red_duration_s` is the relevant reported quantity for queued approaches. Across the 45 learning episodes its values range from 28 to 59 seconds; none reaches 60 seconds.
- The maximum `max_red_duration_s` values are 65 seconds for MAPPO and DQN, and 66 seconds for PPO. PPO’s two 66 second records are seed 33 episodes 1 and 3. DQN’s 66 second records are seed 11 episodes 2 and 3. Those records’ queued-red maxima are 53–57 seconds (PPO) and 34–40 seconds (DQN), respectively.
- The tracker counts red from non-green phases, so a sample includes the mandatory yellow interval. One-second updates and five-second maxima sampling can add measurement-boundary granularity. The saved aggregates do not identify whether each raw maximum was queue-free throughout or which signal phase sequence produced it, and the sampling method cannot prove the true per-second maximum.

### Phase transition paths

`SignalController.get_green_elapsed()` tracks the last observed phase and resets its local phase-start timestamp when the phase ID changes. Normal SUMO transitions are observed the next time `can_switch()` or `get_green_elapsed()` reads the phase. A requested switch from green sets the configured yellow phase and its four-second duration; the subsequent SUMO transition into green is detected by phase ID on the next timing query. Forced starvation intervention calls this same safe `request_switch()` path and does not skip yellow.

Emergency control calls `lock_emergency_priority()`. If already on the corridor green it holds/extends that phase; from a conflicting green it commands the yellow phase and waits for clearance before locking the corridor phase. On the next timing query, changed phase IDs reset local elapsed timing. Release clears the emergency lock; the next phase timing query continues tracking from the observed phase. This is consistent with phase-timer synchronization under ordinary transitions, forced switches, and emergency transitions. However, no P6.2 event-level phase trace was retained, so Stage A cannot validate the timing of individual transitions.

One verification gap remains: `request_switch()` reports success when it initiates yellow, not when the target green is subsequently reached. The training telemetry records neither this return value nor target-phase arrival. This prevents event-by-event confirmation but does not show a reproducible defect in the examined path. No test was added because no reproducible implementation defect was established.

## 3. PPO starvation comparison

PPO’s 89 recorded events exceed MAPPO’s 40 and DQN’s 30. PPO interventions declined from 37 in episode 1 to 28 in episode 2 and 24 in episode 3, but its seed-level behavior varied substantially, especially seed 33. These trends cannot identify which junction/approach was affected because event records were discarded after counting.

The policy’s KEEP, SWITCH, or EXTEND selection is also not saved. The safety path runs once per simulation step independently of the five-second policy decision: once a queued approach is starved and the signal meets minimum green, it requests a forced switch. Thus the implementation is designed to override KEEP/EXTEND at that point. The available output cannot establish which policy action preceded any PPO event or prove that each forced transition reached the target green.

PPO has higher aggregate queue and cumulative delay than MAPPO, DQN, and Coordinated Adaptive in these Stage A records. This is an association in the episode summaries; no event-level data supports attributing those traffic outcomes to specific starvation events.

## 4. Route, vehicle type, and emergency validation

The Stage A and B route files reference `motorcycle`, `car`, and `bmtc_bus`; Stage C references the same types plus `ambulance`. The existing SUMO configuration declares `demand/vehicle_types.add.xml` as an additional file, and that file defines all four types. Stage C declares `stage_c_ambulance` on `corridor_full` with `depart="500.0"`.

SUMO 1.26.0 was run for one simulation step per existing route file using the project configuration, explicitly selecting each route file and the existing additional vehicle-type file. All three parsed and loaded successfully with no unknown-type or route errors. This validation did not modify route files. Because the one-step parse ends before 500 seconds, ambulance insertion at the specified time was verified from the XML declaration and type loading, not by observing the vehicle depart during a simulation.

The training script passes `--route-files <absolute curriculum route>` to SUMO. SUMO retains the configuration’s additional-file setting; this was confirmed by successful route validation with the same additional file selected explicitly. A reproducible route/type defect was not found.

## 5. Checkpoint integrity and verification limits

The existing checkpoint inventory contains six files per learning algorithm: `*_best.json`, `*_final.json`, and `*_seed11/22/33/44/55.json`. JSON parsing succeeded for all files, and each contains three agent entries. The top-level schema stores `algorithm_version`; training metadata records the three-episode-per-seed budget, seed list on final files, and best-checkpoint seed/episode metrics.

The training script constructs a fresh controller for each seed and saves the final checkpoint after the seed loop from the remaining controller. Therefore each `*_stage_a_final.json` contains **the last seed’s (55) controller weights**, with aggregate-run metadata. It is not a multi-seed aggregate model. The per-seed files are the seed-specific artifacts; best files carry their selected seed and episode in metadata.

The application loader requires NumPy, and model construction may also require PyTorch. The only Python interpreter available in this workspace is `C:\Program Files\Python313\python.exe`; its installed packages are only `pip` and its metadata. Importing NumPy fails with `ModuleNotFoundError`, and pytest is not installed. Thus I could not perform the requested actual application checkpoint loads, compare runtime model parameter shapes, or run targeted Python tests in this environment. JSON structure and agent counts are not substitutes for that verification. The checkpoint files do not serialize optimizer state, so optimizer-state restoration is unsupported by the current checkpoint format.

## 6. Provenance and overwrite prevention

Stage A curve and checkpoint metadata report three episodes per seed. This report accepts that as the completed run configuration and does not characterize it as an interruption.

The script currently uses deterministic names such as `mappo_stage_a_curves.json`, `stage_a_stage_summary.json`, `mappo_stage_a_seed11.json`, and `mappo_stage_a_final.json`. Rerunning a stage with these paths can overwrite existing artifacts. For the next authorized experiment, use an explicit immutable run ID (for example `p6_stage_b_20261105_<commit>_<confighash>`) as a directory component and prefix, such as:

```text
results/p6/<run_id>/stage_b/<algorithm>_seed<seed>_episode<episode>.(json|csv)
checkpoints/p6/<run_id>/stage_b/<algorithm>_seed<seed>_<role>.json
```

Write a run manifest in that directory containing the code commit, route and config hashes, SUMO/Python/dependency versions, exact seeds, episode budget, and start/end status. Refuse to write if the run-ID directory already exists. Keep the best checkpoint’s selection metadata explicit and label the last-seed checkpoint as such.

## 7. Known limitations and recommendation

- No per-event safety log was saved, so junction, approach, action, and successful target-green transition cannot be reconciled for each intervention.
- No per-second phase trace exists to reconstruct each 65/66 second raw maximum.
- Checkpoint application loading/inference and architecture shape comparison remain outstanding because NumPy/PyTorch are unavailable in the only Python installation.
- Python targeted tests could not run because pytest and project dependencies are absent. No defect-triggered test was added.
- SUMO route validation succeeded; Stage C ambulance departure was source-verified but not simulated to 500 seconds.
- The three-episode-per-seed run establishes initial behavior only and is insufficient evidence of convergence or curriculum-stage mastery.

**Recommendation: NO-GO for Stage B at this point.** Preserve the existing files. Before authorizing Stage B, make an appropriate project Python environment available and complete application checkpoint loading plus deterministic inference for all 18 MAPPO/PPO/DQN checkpoints. Also add a non-training, non-overwriting safety replay/audit that captures `StarvationEvent` details and verifies switch-to-yellow-to-target-green execution, ideally by replaying existing policies on Stage A seeds rather than retraining. Proceed only after that review; retain the 60 second threshold.
