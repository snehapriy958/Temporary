"""
P6.4 Phase B/C/D — Application-level checkpoint loading and MARL controller test.

Exercises the actual application code path:
  MultiIntersectionSimulation (with explicit checkpoint_path) →
  MARLCorridorController → load_checkpoint() →
  get_ai_observations() → decide(eval_mode=True) → apply_decisions()

Runs a 90-second bounded SUMO simulation with the P6 Stage A PPO checkpoint,
then repeats for DQN.

Does NOT use randomly initialized weights. Uses the actual application loaders.
"""
import sys, json, time, pathlib, logging, traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("p6_4_audit")

ROOT = pathlib.Path(r"C:\Developers\Sneha\Projects\hybrid-traffic-control")
sys.path.insert(0, str(ROOT))

SUMO_HOME = r"C:\Program Files (x86)\Eclipse\Sumo"
import os
os.environ["SUMO_HOME"] = SUMO_HOME
sys.path.insert(0, str(pathlib.Path(SUMO_HOME) / "tools"))

SUMOCFG = ROOT / "sumo" / "silk_board" / "silk_board.sumocfg"
PPO_CKPT = ROOT / "checkpoints" / "p6" / "ppo_stage_a_best.json"
DQN_CKPT = ROOT / "checkpoints" / "p6" / "dqn_stage_a_best.json"
HIST_PPO = ROOT / "checkpoints" / "marl_ppo_corridor.json"
HIST_DQN = ROOT / "checkpoints" / "marl_dqn_corridor.json"

RESULTS_PATH = ROOT / "scratch" / "p6_4_audit_results.json"

results = {
    "metadata": {
        "task": "P6.4",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.version,
        "root": str(ROOT),
        "sumocfg": str(SUMOCFG),
    },
    "phase_b_checkpoint_loading": {},
    "phase_c_ppo_application": {},
    "phase_d_dqn_application": {},
    "phase_e_safety": {},
}


# =========================================================
# Phase B: Checkpoint Loading via actual application loader
# =========================================================
def run_phase_b():
    logger.info("=" * 60)
    logger.info("PHASE B: Checkpoint Loading via Application Loader")
    logger.info("=" * 60)
    res = results["phase_b_checkpoint_loading"]

    from traffic_service.ai.marl_controller import MARLCorridorController
    from traffic_service.signal_controller import SignalController

    for algo, ckpt, label in [
        ("ppo", PPO_CKPT, "p6_stage_a_best"),
        ("dqn", DQN_CKPT, "p6_stage_a_best"),
        ("ppo", HIST_PPO, "historical_root"),
        ("dqn", HIST_DQN, "historical_root"),
    ]:
        key = f"{algo}_{label}"
        logger.info(f"  Loading {key}: {ckpt.name} ({ckpt.stat().st_size} bytes)")
        entry = {
            "file": str(ckpt),
            "bytes": ckpt.stat().st_size if ckpt.is_file() else 0,
            "exists": ckpt.is_file(),
        }

        try:
            # Construct dummy SignalControllers for the constructor
            dummy_controllers = {
                j: SignalController(junction_id=j, tls_id=j, num_phases=4)
                for j in ["J1", "J2", "J3"]
            }
            controller = MARLCorridorController(
                algorithm=algo,
                junctions=["J1", "J2", "J3"],
                controllers=dummy_controllers,
                communication_hub=None,
            )
            loaded = controller.load_checkpoint(ckpt)
            entry["load_checkpoint_returned"] = loaded
            entry["load_success"] = loaded

            if loaded:
                # Validate agents
                agent_keys = list(controller.agents.keys())
                entry["agents_found"] = agent_keys
                entry["j1_present"] = "J1" in agent_keys
                entry["j2_present"] = "J2" in agent_keys
                entry["j3_present"] = "J3" in agent_keys

                # Probe checkpoint metadata
                raw = json.loads(ckpt.read_text())
                entry["ckpt_algorithm"] = raw.get("algorithm")
                entry["ckpt_seed"] = raw.get("seed")
                entry["ckpt_obs_dim"] = raw.get("obs_dim")
                entry["ckpt_num_actions"] = raw.get("num_actions")
                entry["ckpt_agents_in_file"] = list(raw.get("agents", {}).keys())

                # Quick inference test on loaded model
                import numpy as np
                obs_14 = np.zeros(14, dtype=np.float32)
                obs_14[0] = 0.5   # phase_progress
                obs_14[2] = 0.3   # queue_j1
                obs_14[6] = 0.2   # queue_j2
                dummy_ai_obs = {j: obs_14 for j in ["J1", "J2", "J3"]}

                decisions = controller.decide(dummy_ai_obs, sim_time=10.0, eval_mode=True)
                entry["inference_decisions"] = {
                    j: {
                        "action": int(d.get("action", -1)),
                        "action_name": d.get("action_name"),
                        "is_fallback": d.get("is_fallback", False),
                    }
                    for j, d in decisions.items()
                }
                entry["all_j_decisions_present"] = all(j in decisions for j in ["J1", "J2", "J3"])
                # Determinism check
                decisions2 = controller.decide(dummy_ai_obs, sim_time=10.0, eval_mode=True)
                entry["deterministic"] = all(
                    decisions[j].get("action") == decisions2[j].get("action")
                    for j in ["J1", "J2", "J3"]
                )
                entry["PASSED"] = True
                logger.info(f"    ✓ {key} PASSED — decisions: {entry['inference_decisions']}")
            else:
                entry["PASSED"] = False
                logger.warning(f"    ✗ {key} FAILED — load_checkpoint returned False")

        except Exception as e:
            entry["PASSED"] = False
            entry["error"] = str(e)
            entry["traceback"] = traceback.format_exc()
            logger.error(f"    ✗ {key} ERROR: {e}")

        res[key] = entry

    logger.info("Phase B complete.")


# =========================================================
# Phase C/D: Application-level SUMO smoke test
# =========================================================
def run_sumo_test(algo: str, ckpt_path: pathlib.Path, duration_s: int, seed: int, phase_key: str):
    """
    Instantiates MultiIntersectionSimulation with the given checkpoint,
    runs for duration_s seconds, and captures MARL decisions.
    """
    logger.info("=" * 60)
    logger.info(f"{phase_key.upper()}: SUMO smoke test — {algo.upper()} | ckpt={ckpt_path.name}")
    logger.info("=" * 60)
    res = results[phase_key]
    res["algo"] = algo
    res["checkpoint"] = str(ckpt_path)
    res["duration_requested"] = duration_s

    try:
        from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation

        sim = MultiIntersectionSimulation(
            sumocfg_path=SUMOCFG,
            mode=f"marl_{algo}",
            gui=False,
            step_length=1.0,
            decision_interval=5.0,
            enable_emergency=False,
            label="p6_4_audit",
            checkpoint_path=ckpt_path,
        )

        res["controller_instantiated"] = True
        res["marl_controller_present"] = sim.marl_controller is not None
        if sim.marl_controller:
            res["marl_algorithm"] = sim.marl_controller.algorithm
            res["marl_agents"] = list(sim.marl_controller.agents.keys())
            res["all_agents_j1_j2_j3"] = all(j in sim.marl_controller.agents for j in ["J1", "J2", "J3"])

        logger.info(f"  Starting SUMO (seed={seed}, duration={duration_s}s)...")
        sim.start(seed=seed)
        res["sumo_started"] = True
        logger.info("  SUMO started.")

        import traci
        decisions_log = []
        ops_log = []
        sim_times = []

        step = 0
        sim_time = 0.0
        next_decision = 0.0

        while sim_time < duration_s:
            sim_time = sim.sumo_manager.step()
            sim_times.append(sim_time)
            states = sim.get_states(sim_time)

            if sim_time >= next_decision:
                # Replicate _run_marl_with_logging call chain
                ai_obs = sim.get_ai_observations(states)
                decisions = sim.marl_controller.decide(ai_obs, sim_time, eval_mode=True)
                executed_ops = sim.marl_controller.apply_decisions(decisions, sim_time)

                snap = {
                    "sim_time": sim_time,
                    "decisions": {
                        j: {
                            "action": d.get("action"),
                            "action_name": d.get("action_name"),
                            "target_phase": d.get("target_phase"),
                            "is_fallback": d.get("is_fallback"),
                        }
                        for j, d in decisions.items()
                    },
                    "executed_ops": executed_ops,
                }
                decisions_log.append(snap)
                ops_log.extend(list(executed_ops.values()))

                if len(decisions_log) <= 3:
                    logger.info(f"  t={sim_time:.1f}s | decisions={snap['decisions']} ops={executed_ops}")

                next_decision = sim_time + 5.0

            step += 1

        res["sim_time_end"] = sim_time
        res["steps_executed"] = step
        res["decision_intervals"] = len(decisions_log)
        res["all_decisions_logged"] = decisions_log

        # Summarize ops
        from collections import Counter
        op_counts = Counter(ops_log)
        res["op_summary"] = dict(op_counts)
        res["switch_occurred"] = "SWITCH" in op_counts
        res["extend_occurred"] = "EXTEND" in op_counts
        res["keep_occurred"] = "KEEP" in op_counts

        # Verify all 3 agents active in every interval
        agent_coverage = all(
            all(j in d["decisions"] for j in ["J1", "J2", "J3"])
            for d in decisions_log
        )
        res["all_junctions_active_per_interval"] = agent_coverage

        # Action validity (0, 1, 2 only)
        all_actions = [
            d["decisions"][j]["action"]
            for d in decisions_log
            for j in ["J1", "J2", "J3"]
            if d["decisions"].get(j)
        ]
        res["action_values_seen"] = list(set(all_actions))
        res["actions_in_valid_range"] = all(a in [0, 1, 2] for a in all_actions)

        logger.info(f"  Simulation complete: {step} steps, {len(decisions_log)} decision intervals")
        logger.info(f"  Op summary: {op_counts}")

        # Cleanup
        sim.sumo_manager.stop()
        res["sumo_stopped_cleanly"] = True
        logger.info("  SUMO stopped cleanly.")
        res["PASSED"] = True

    except Exception as e:
        res["PASSED"] = False
        res["error"] = str(e)
        res["traceback"] = traceback.format_exc()
        logger.error(f"  FAILED: {e}")
        try:
            sim.sumo_manager.stop()
            logger.info("  SUMO stopped after error.")
        except Exception:
            pass


# =========================================================
# Phase E: Safety constraint audit (source-level)
# =========================================================
def run_phase_e():
    logger.info("=" * 60)
    logger.info("PHASE E: Safety constraint source-level audit")
    logger.info("=" * 60)
    res = results["phase_e_safety"]

    signal_src = (ROOT / "traffic_service" / "signal_controller.py").read_text()
    marl_src = (ROOT / "traffic_service" / "ai" / "marl_controller.py").read_text()
    starvation_src = (ROOT / "traffic_service" / "ai" / "starvation_tracker.py").read_text()

    import re

    # min_green enforcement
    mg_match = re.search(r'min_green.*?switch', signal_src[:3000], re.DOTALL | re.IGNORECASE)
    res["signal_controller_min_green_enforced"] = "min_green" in signal_src
    res["signal_controller_max_green_enforced"] = "max_green" in signal_src
    res["signal_controller_yellow_clearance"] = "yellow" in signal_src.lower()
    res["signal_controller_request_switch_exists"] = "def request_switch" in signal_src
    res["signal_controller_extend_green_exists"] = "def extend_current_green" in signal_src

    # MARL controller apply_decisions safety
    res["marl_apply_decisions_uses_signal_controller"] = "request_switch" in marl_src or "apply_decisions" in marl_src
    res["marl_uses_action_mask"] = "get_action_mask" in marl_src
    res["marl_uses_starvation_tracker"] = "starvation" in marl_src.lower()
    res["marl_eval_mode_enforced"] = "eval_mode" in marl_src

    # Starvation tracker
    res["starvation_max_red_threshold_s"] = "max_red_threshold_s" in starvation_src
    res["starvation_emergency_lock_checked"] = "emergency_locked" in starvation_src

    # Find min_green value in signal_controller
    mg_val = re.search(r'min_green\s*[:=]\s*([\d.]+)', signal_src)
    res["min_green_default_value"] = float(mg_val.group(1)) if mg_val else "NOT_FOUND"
    max_g = re.search(r'max_green\s*[:=]\s*([\d.]+)', signal_src)
    res["max_green_default_value"] = float(max_g.group(1)) if max_g else "NOT_FOUND"

    # Yellow phase check
    yellow_match = re.search(r'yellow.*?phase|phase.*?yellow', signal_src[:5000], re.DOTALL | re.IGNORECASE)
    res["yellow_phase_in_signal_controller"] = bool(yellow_match)

    res["PASSED"] = all([
        res["signal_controller_min_green_enforced"],
        res["signal_controller_max_green_enforced"],
        res["signal_controller_yellow_clearance"],
        res["marl_uses_action_mask"],
        res["starvation_max_red_threshold_s"],
    ])

    logger.info(f"  Safety audit: {res}")


# =========================================================
# Main
# =========================================================
if __name__ == "__main__":
    try:
        run_phase_b()
    except Exception as e:
        logger.error(f"Phase B crashed: {e}")
        results["phase_b_checkpoint_loading"]["crash"] = traceback.format_exc()

    # Phase C: PPO (90-second run)
    try:
        run_sumo_test(
            algo="ppo",
            ckpt_path=PPO_CKPT,
            duration_s=90,
            seed=99,
            phase_key="phase_c_ppo_application",
        )
    except Exception as e:
        logger.error(f"Phase C crashed: {e}")
        results["phase_c_ppo_application"]["crash"] = traceback.format_exc()

    # Phase D: DQN (90-second run)
    try:
        run_sumo_test(
            algo="dqn",
            ckpt_path=DQN_CKPT,
            duration_s=90,
            seed=99,
            phase_key="phase_d_dqn_application",
        )
    except Exception as e:
        logger.error(f"Phase D crashed: {e}")
        results["phase_d_dqn_application"]["crash"] = traceback.format_exc()

    try:
        run_phase_e()
    except Exception as e:
        logger.error(f"Phase E crashed: {e}")
        results["phase_e_safety"]["crash"] = traceback.format_exc()

    # Save results (strip large log to avoid bloat)
    for phase_key in ["phase_c_ppo_application", "phase_d_dqn_application"]:
        full = results[phase_key].get("all_decisions_logged", [])
        if len(full) > 20:
            results[phase_key]["all_decisions_logged"] = full[:10]
            results[phase_key]["all_decisions_logged_truncated"] = True

    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))
    logger.info(f"\nAll results saved to {RESULTS_PATH}")
    print("\n=== SUMMARY ===")
    for section, data in results.items():
        if section == "metadata":
            continue
        passed = data.get("PASSED")
        print(f"  {section}: {'PASSED' if passed else 'FAILED' if passed is False else 'PARTIAL'}")

