"""
P6.3 — Learned Model Runtime Verification Script
Performs deterministic inference tests on PPO, DQN, and MAPPO checkpoints.
Uses the actual application implementations — no monkey-patching or bypasses.
"""
from __future__ import annotations

import json
import logging
import sys
import os
import math
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Setup ──────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("p6_3_audit")

# Inject project root so application modules are importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SUMO_TOOLS = Path("C:/Program Files (x86)/Eclipse/Sumo/tools")
if SUMO_TOOLS.exists():
    sys.path.insert(0, str(SUMO_TOOLS))

CHECKPOINT_DIR = PROJECT_ROOT / "checkpoints"

# ── Results collector ──────────────────────────────────────────────────────────
results: Dict[str, Any] = {
    "environment": {},
    "phase3_ppo_historical": {},
    "phase4_dqn_historical": {},
    "phase5_p6_ppo": {},
    "phase5_p6_dqn": {},
    "phase6_mappo": {},
    "phase7_connectivity": {},
    "phase8_sumo": {},
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def check_finite(arr, name: str) -> bool:
    import numpy as np
    if isinstance(arr, (int, float)):
        ok = math.isfinite(arr)
    else:
        arr = np.asarray(arr)
        ok = bool(np.all(np.isfinite(arr)))
    if not ok:
        log.error(f"  NON-FINITE values in {name}: {arr}")
    return ok


def build_obs_14d(phase=2, elapsed=20.0, corridor_q=5.0, side_q=2.0,
                  speed=35.0, wait=40.0, count=8.0) -> "np.ndarray":
    """Construct a valid, deterministic 14-dimensional observation vector."""
    import numpy as np
    vec = np.zeros(14, dtype=np.float32)
    vec[0] = phase / 3.0           # current_phase_norm
    vec[1] = elapsed / 60.0        # phase_elapsed_norm
    vec[2] = 0.3                   # time_to_switch_norm
    vec[3] = 1.0                   # can_switch_flag
    vec[4] = corridor_q / 50.0     # corridor_queue_norm
    vec[5] = side_q / 50.0         # side_queue_norm
    vec[6] = (corridor_q + side_q) / 100.0  # total_queue_norm
    vec[7] = speed / 60.0          # average_speed_norm
    vec[8] = wait / 500.0          # waiting_time_norm
    vec[9] = count / 100.0         # vehicle_count_norm
    vec[10] = 0.1                  # co2_emissions_norm
    vec[11] = 0.2                  # upstream_inflow_norm
    vec[12] = 0.0                  # approaching_platoons_norm
    vec[13] = 0.0                  # emergency_approaching_flag
    return vec


# ==============================================================================
# Phase 2 — Environment provenance
# ==============================================================================
def phase2_environment():
    log.info("=" * 60)
    log.info("PHASE 2 — Environment Provenance")
    env = {}
    env["python_version"] = sys.version
    env["python_executable"] = sys.executable

    try:
        import torch
        env["torch_version"] = torch.__version__
        env["torch_file"] = torch.__file__
        env["cuda_available"] = torch.cuda.is_available()
    except ImportError as e:
        env["torch_error"] = str(e)

    try:
        import numpy as np
        env["numpy_version"] = np.__version__
    except ImportError as e:
        env["numpy_error"] = str(e)

    try:
        import traci
        env["traci_file"] = traci.__file__
        env["traci_under_sumo"] = str(SUMO_TOOLS) in traci.__file__
    except ImportError as e:
        env["traci_error"] = str(e)

    try:
        import sumolib
        env["sumolib_file"] = sumolib.__file__
        env["sumolib_under_sumo"] = str(SUMO_TOOLS) in sumolib.__file__
    except ImportError as e:
        env["sumolib_error"] = str(e)

    env["sumo_home"] = os.environ.get("SUMO_HOME", "NOT_SET")
    results["environment"] = env

    log.info(f"  Python:  {env.get('python_version','?')}")
    log.info(f"  torch:   {env.get('torch_version','MISSING')}")
    log.info(f"  numpy:   {env.get('numpy_version','MISSING')}")
    log.info(f"  traci:   {env.get('traci_file','MISSING')}")
    log.info(f"  sumolib: {env.get('sumolib_file','MISSING')}")
    return env


# ==============================================================================
# Phase 3 — Historical PPO
# ==============================================================================
def phase3_historical_ppo():
    log.info("=" * 60)
    log.info("PHASE 3 — Historical PPO checkpoint")
    r = {"status": "FAILED", "details": {}}

    cp_path = CHECKPOINT_DIR / "marl_ppo_corridor.json"
    try:
        # 1. Import
        from traffic_service.ai.ppo_agent import PPOAgent
        r["details"]["import"] = "OK"
        log.info("  PPOAgent import: OK")

        # 2. Instantiate
        agents = {
            jid: PPOAgent(agent_id=jid, in_features=14, num_actions=3, seed=42)
            for jid in ["J1", "J2", "J3"]
        }
        r["details"]["instantiation"] = "OK"

        # 3. Load checkpoint
        with open(cp_path, "r") as f:
            ckpt = json.load(f)
        r["details"]["checkpoint_path"] = str(cp_path)
        r["details"]["checkpoint_algorithm"] = ckpt.get("algorithm")
        r["details"]["checkpoint_seed"] = ckpt.get("seed")
        r["details"]["checkpoint_junctions"] = ckpt.get("junctions")

        agents_data = ckpt.get("agents", {})
        weights_loaded = {}
        for jid in ["J1", "J2", "J3"]:
            if jid not in agents_data:
                raise ValueError(f"Missing agent {jid} in checkpoint")
            agents[jid].load_state_dict(agents_data[jid])
            w = agents[jid].ac_network.get_weights()
            shapes = {k: list(v.shape) for k, v in w.items()}
            weights_loaded[jid] = shapes
        r["details"]["weight_shapes"] = weights_loaded
        r["details"]["load_checkpoint"] = "OK"
        log.info(f"  Checkpoint load: OK — agents {list(agents_data.keys())}")

        # 4. Deterministic inference
        import numpy as np
        obs = build_obs_14d()
        inference_results = {}
        for jid, agent in agents.items():
            action1, info1 = agent.select_action(obs, eval_mode=True)
            action2, info2 = agent.select_action(obs, eval_mode=True)
            probs1 = info1.get("probabilities", [])
            probs2 = info2.get("probabilities", [])
            match = (action1 == action2) and (probs1 == probs2)
            finite_probs = check_finite(probs1, f"PPO {jid} probs")
            valid_range = 0 <= action1 <= 2
            inference_results[jid] = {
                "action1": action1, "action2": action2,
                "action_name": info1.get("action_name"),
                "probabilities": probs1,
                "value": info1.get("value"),
                "deterministic_match": match,
                "finite_probs": finite_probs,
                "valid_action_range": valid_range,
            }
            log.info(f"  {jid}: action={action1} ({info1.get('action_name')}), "
                     f"probs={[f'{p:.4f}' for p in probs1]}, det_match={match}, finite={finite_probs}")

        r["details"]["inference"] = inference_results

        # 5. Validate
        all_ok = all(
            ir["deterministic_match"] and ir["finite_probs"] and ir["valid_action_range"]
            for ir in inference_results.values()
        )
        r["status"] = "PASSED" if all_ok else "FAILED"
        log.info(f"  PHASE 3 STATUS: {r['status']}")

    except Exception as e:
        r["status"] = "FAILED"
        r["error"] = str(e)
        r["traceback"] = traceback.format_exc()
        log.error(f"  PHASE 3 FAILED: {e}")

    results["phase3_ppo_historical"] = r
    return r


# ==============================================================================
# Phase 4 — Historical DQN
# ==============================================================================
def phase4_historical_dqn():
    log.info("=" * 60)
    log.info("PHASE 4 — Historical Double-DQN checkpoint")
    r = {"status": "FAILED", "details": {}}

    cp_path = CHECKPOINT_DIR / "marl_dqn_corridor.json"
    try:
        from traffic_service.ai.dqn_agent import DQNAgent
        r["details"]["import"] = "OK"
        log.info("  DQNAgent import: OK")

        agents = {
            jid: DQNAgent(agent_id=jid, in_features=14, num_actions=3, seed=42)
            for jid in ["J1", "J2", "J3"]
        }

        with open(cp_path, "r") as f:
            ckpt = json.load(f)
        r["details"]["checkpoint_algorithm"] = ckpt.get("algorithm")
        r["details"]["checkpoint_seed"] = ckpt.get("seed")

        agents_data = ckpt.get("agents", {})
        weight_shapes = {}
        for jid in ["J1", "J2", "J3"]:
            if jid not in agents_data:
                raise ValueError(f"Missing {jid}")
            agents[jid].load_state_dict(agents_data[jid])
            w = agents[jid].q_network.get_weights()
            weight_shapes[jid] = {k: list(v.shape) for k, v in w.items()}
        r["details"]["weight_shapes"] = weight_shapes
        r["details"]["load_checkpoint"] = "OK"
        log.info(f"  Checkpoint load: OK — agents {list(agents_data.keys())}")

        # Verify dueling architecture keys
        for jid in ["J1", "J2", "J3"]:
            w = agents[jid].q_network.get_weights()
            assert "val_fc_w" in w, f"Missing val_fc_w in {jid}"
            assert "adv_fc_w" in w, f"Missing adv_fc_w in {jid}"
            assert "adv_out_w" in w, f"Missing adv_out_w in {jid}"
        r["details"]["dueling_arch_verified"] = True
        log.info("  Dueling network architecture: VERIFIED (val+adv streams present)")

        import numpy as np
        obs = build_obs_14d()
        inference_results = {}
        for jid, agent in agents.items():
            # Set epsilon=0 for fully deterministic evaluation
            agent.epsilon = 0.0
            action1, info1 = agent.select_action(obs, eval_mode=True)
            action2, info2 = agent.select_action(obs, eval_mode=True)
            q1 = info1.get("q_values", [])
            q2 = info2.get("q_values", [])
            match = (action1 == action2) and (q1 == q2)
            finite_q = check_finite(q1, f"DQN {jid} Q-values")
            valid_range = 0 <= action1 <= 2
            loaded_eps = agents_data[jid].get("epsilon")
            inference_results[jid] = {
                "action1": action1, "action2": action2,
                "action_name": info1.get("action_name"),
                "q_values": q1,
                "loaded_epsilon": loaded_eps,
                "deterministic_match": match,
                "finite_q": finite_q,
                "valid_action_range": valid_range,
            }
            log.info(f"  {jid}: action={action1} ({info1.get('action_name')}), "
                     f"Q={[f'{q:.4f}' for q in q1]}, loaded_eps={loaded_eps:.4f}, det_match={match}")

        r["details"]["inference"] = inference_results
        all_ok = all(
            ir["deterministic_match"] and ir["finite_q"] and ir["valid_action_range"]
            for ir in inference_results.values()
        )
        r["status"] = "PASSED" if all_ok else "FAILED"
        log.info(f"  PHASE 4 STATUS: {r['status']}")

    except Exception as e:
        r["status"] = "FAILED"
        r["error"] = str(e)
        r["traceback"] = traceback.format_exc()
        log.error(f"  PHASE 4 FAILED: {e}")

    results["phase4_dqn_historical"] = r
    return r


# ==============================================================================
# Phase 5 — P6 Stage A PPO and DQN
# ==============================================================================
def _verify_p6_checkpoint(algo: str, cp_path: Path, label: str) -> Dict[str, Any]:
    """Generic verifier for a single P6 Stage A checkpoint (PPO or DQN)."""
    r = {"status": "FAILED", "details": {}}
    try:
        from traffic_service.ai.ppo_agent import PPOAgent
        from traffic_service.ai.dqn_agent import DQNAgent
        import numpy as np

        with open(cp_path, "r") as f:
            ckpt = json.load(f)

        ckpt_algo = ckpt.get("algorithm")
        ckpt_seed = ckpt.get("seed")
        ckpt_version = ckpt.get("algorithm_version")
        meta = ckpt.get("metadata", {})
        saved_at = ckpt.get("saved_at", "N/A")

        r["details"]["checkpoint_path"] = str(cp_path)
        r["details"]["checkpoint_algorithm"] = ckpt_algo
        r["details"]["checkpoint_seed"] = ckpt_seed
        r["details"]["algorithm_version"] = ckpt_version
        r["details"]["saved_at"] = saved_at
        r["details"]["metadata_keys"] = list(meta.keys())

        agents_data = ckpt.get("agents", {})
        if set(agents_data.keys()) != {"J1", "J2", "J3"}:
            raise ValueError(f"Agent IDs mismatch: got {set(agents_data.keys())}")

        # Create agents using actual MARLCorridorController convention
        # seed offsets: J1=seed+0*37, J2=seed+1*37, J3=seed+2*37 (but checkpoint has its own seed)
        agents = {}
        for jid in ["J1", "J2", "J3"]:
            if algo == "ppo":
                agents[jid] = PPOAgent(agent_id=jid, in_features=14, num_actions=3, seed=42)
            else:
                agents[jid] = DQNAgent(agent_id=jid, in_features=14, num_actions=3, seed=42)
            agents[jid].load_state_dict(agents_data[jid])

        weight_shapes = {}
        step_counters = {}
        for jid in ["J1", "J2", "J3"]:
            if algo == "ppo":
                w = agents[jid].ac_network.get_weights()
                sc = agents[jid].step_counter
            else:
                w = agents[jid].q_network.get_weights()
                sc = agents[jid].step_counter
            weight_shapes[jid] = {k: list(v.shape) for k, v in w.items()}
            step_counters[jid] = sc
        r["details"]["weight_shapes"] = weight_shapes
        r["details"]["step_counters"] = step_counters

        # Deterministic inference
        obs = build_obs_14d()
        inference_results = {}
        for jid, agent in agents.items():
            if algo == "dqn":
                agent.epsilon = 0.0
            action1, info1 = agent.select_action(obs, eval_mode=True)
            action2, info2 = agent.select_action(obs, eval_mode=True)

            if algo == "ppo":
                vals1 = info1.get("probabilities", [])
                vals2 = info2.get("probabilities", [])
                finite_ok = check_finite(vals1, f"{label} {jid} probs")
            else:
                vals1 = info1.get("q_values", [])
                vals2 = info2.get("q_values", [])
                finite_ok = check_finite(vals1, f"{label} {jid} Q")

            match = (action1 == action2) and (vals1 == vals2)
            valid_range = 0 <= action1 <= 2
            inference_results[jid] = {
                "action1": action1, "action2": action2,
                "action_name": info1.get("action_name"),
                "values": vals1,
                "deterministic_match": match,
                "finite_values": finite_ok,
                "valid_action_range": valid_range,
            }
            log.info(f"  {label} {jid}: action={action1} ({info1.get('action_name')}), "
                     f"det_match={match}, finite={finite_ok}")

        r["details"]["inference"] = inference_results
        all_ok = all(
            ir["deterministic_match"] and ir["finite_values"] and ir["valid_action_range"]
            for ir in inference_results.values()
        )
        r["status"] = "PASSED" if all_ok else "FAILED"

    except Exception as e:
        r["status"] = "FAILED"
        r["error"] = str(e)
        r["traceback"] = traceback.format_exc()
        log.error(f"  {label} FAILED: {e}")

    return r


def phase5_p6_ppo():
    log.info("=" * 60)
    log.info("PHASE 5a — P6 Stage A PPO checkpoints")
    r = {}

    checkpoints = {
        "ppo_stage_a_best": CHECKPOINT_DIR / "p6/ppo_stage_a_best.json",
        "ppo_stage_a_final": CHECKPOINT_DIR / "p6/ppo_stage_a_final.json",
        "ppo_stage_a_seed11": CHECKPOINT_DIR / "p6/ppo_stage_a_seed11.json",
        "ppo_stage_a_seed55": CHECKPOINT_DIR / "p6/ppo_stage_a_seed55.json",
    }
    for label, cp in checkpoints.items():
        log.info(f"  Verifying {label}...")
        r[label] = _verify_p6_checkpoint("ppo", cp, label)
        log.info(f"  {label}: {r[label]['status']}")

    results["phase5_p6_ppo"] = r
    statuses = [v["status"] for v in r.values()]
    overall = "PASSED" if all(s == "PASSED" for s in statuses) else "FAILED"
    log.info(f"  PHASE 5a OVERALL: {overall}")
    return r


def phase5_p6_dqn():
    log.info("=" * 60)
    log.info("PHASE 5b — P6 Stage A DQN checkpoints")
    r = {}

    checkpoints = {
        "dqn_stage_a_best": CHECKPOINT_DIR / "p6/dqn_stage_a_best.json",
        "dqn_stage_a_final": CHECKPOINT_DIR / "p6/dqn_stage_a_final.json",
        "dqn_stage_a_seed11": CHECKPOINT_DIR / "p6/dqn_stage_a_seed11.json",
        "dqn_stage_a_seed55": CHECKPOINT_DIR / "p6/dqn_stage_a_seed55.json",
    }
    for label, cp in checkpoints.items():
        log.info(f"  Verifying {label}...")
        r[label] = _verify_p6_checkpoint("dqn", cp, label)
        log.info(f"  {label}: {r[label]['status']}")

    results["phase5_p6_dqn"] = r
    statuses = [v["status"] for v in r.values()]
    overall = "PASSED" if all(s == "PASSED" for s in statuses) else "FAILED"
    log.info(f"  PHASE 5b OVERALL: {overall}")
    return r


# ==============================================================================
# Phase 6 — MAPPO
# ==============================================================================
def phase6_mappo():
    log.info("=" * 60)
    log.info("PHASE 6 — MAPPO verification")
    r = {}

    checkpoints = {
        "mappo_stage_a_best": CHECKPOINT_DIR / "p6/mappo_stage_a_best.json",
        "mappo_stage_a_final": CHECKPOINT_DIR / "p6/mappo_stage_a_final.json",
        "mappo_stage_a_seed11": CHECKPOINT_DIR / "p6/mappo_stage_a_seed11.json",
    }

    for label, cp_path in checkpoints.items():
        log.info(f"  Verifying {label}...")
        cr = {"status": "FAILED", "details": {}}
        try:
            from traffic_service.ai.mappo_agent import MAPPOAgent
            from traffic_service.ai.models import MAPPOCentralizedCriticNetwork
            import numpy as np

            with open(cp_path, "r") as f:
                ckpt = json.load(f)

            ckpt_algo = ckpt.get("algorithm")
            ckpt_seed = ckpt.get("seed")
            cr["details"]["checkpoint_algorithm"] = ckpt_algo
            cr["details"]["checkpoint_seed"] = ckpt_seed
            cr["details"]["has_shared_critic_weights"] = "shared_critic_weights" in ckpt

            agents_data = ckpt.get("agents", {})
            if set(agents_data.keys()) != {"J1", "J2", "J3"}:
                raise ValueError(f"Agent IDs mismatch: {set(agents_data.keys())}")

            # Create shared critic
            shared_critic = MAPPOCentralizedCriticNetwork(in_features=42, seed=42)

            # Load shared critic weights
            if "shared_critic_weights" in ckpt:
                raw_cw = ckpt["shared_critic_weights"]
                import numpy as np
                converted_cw = {
                    k: np.array(v, dtype=np.float32) for k, v in raw_cw.items()
                }
                shared_critic.set_weights(converted_cw)
                cr["details"]["shared_critic_load"] = "OK"
                cr["details"]["shared_critic_weight_shapes"] = {
                    k: list(np.array(v).shape) for k, v in converted_cw.items()
                }
                log.info(f"    Shared critic loaded: in_features=42 (corridor=42)")
            else:
                cr["details"]["shared_critic_load"] = "NO_SHARED_CRITIC_WEIGHTS"

            # Create and load agents
            agents = {}
            for jid in ["J1", "J2", "J3"]:
                agents[jid] = MAPPOAgent(
                    agent_id=jid,
                    in_features=14,
                    corridor_features=42,
                    num_actions=3,
                    shared_critic=shared_critic,
                    seed=42,
                )
                agents[jid].load_state_dict(agents_data[jid])

            # Verify actor weight shapes
            actor_shapes = {}
            for jid in ["J1", "J2", "J3"]:
                w = agents[jid].actor.get_weights()
                actor_shapes[jid] = {k: list(np.array(v).shape) for k, v in w.items()}
            cr["details"]["actor_weight_shapes"] = actor_shapes
            log.info(f"    Actor weights loaded for J1/J2/J3")

            # Verify actor obs dim = 14
            assert actor_shapes["J1"]["fc1_w"][0] == 14, "Actor input dim != 14"
            cr["details"]["actor_obs_dim_verified"] = True

            # Verify shared critic obs dim = 42
            sc_w = shared_critic.get_weights()
            sc_in = sc_w["fc1_w"].shape[0]
            assert sc_in == 42, f"Shared critic input dim = {sc_in} != 42"
            cr["details"]["critic_obs_dim_verified"] = True
            log.info(f"    obs dims: actor=14, shared_critic=42 — VERIFIED")

            # Deterministic inference — local obs (14-dim)
            obs_14 = build_obs_14d()
            # Corridor obs (42-dim) = concatenate 3 junction obs
            obs_42 = np.tile(obs_14, 3).astype(np.float32)

            inference_results = {}
            for jid, agent in agents.items():
                action1, info1 = agent.select_action(obs_14, eval_mode=True)
                action2, info2 = agent.select_action(obs_14, eval_mode=True)
                probs1 = info1.get("probabilities", [])
                probs2 = info2.get("probabilities", [])
                match = (action1 == action2) and (probs1 == probs2)
                finite_p = check_finite(probs1, f"MAPPO {jid} probs")
                valid_range = 0 <= action1 <= 2

                # Test corridor critic
                val = agent.get_corridor_value(obs_42)
                finite_v = check_finite(val, f"MAPPO {jid} critic value")

                inference_results[jid] = {
                    "action1": action1, "action2": action2,
                    "action_name": info1.get("action_name"),
                    "probabilities": probs1,
                    "corridor_value": val,
                    "deterministic_match": match,
                    "finite_probs": finite_p,
                    "finite_critic_value": finite_v,
                    "valid_action_range": valid_range,
                }
                log.info(f"    {jid}: action={action1} ({info1.get('action_name')}), "
                         f"V(s_corridor)={val:.4f}, det_match={match}")

            cr["details"]["inference"] = inference_results
            all_ok = all(
                ir["deterministic_match"] and ir["finite_probs"] and
                ir["finite_critic_value"] and ir["valid_action_range"]
                for ir in inference_results.values()
            )
            cr["status"] = "PASSED" if all_ok else "FAILED"

        except Exception as e:
            cr["status"] = "FAILED"
            cr["error"] = str(e)
            cr["traceback"] = traceback.format_exc()
            log.error(f"  {label} FAILED: {e}")

        r[label] = cr
        log.info(f"  {label}: {cr['status']}")

    results["phase6_mappo"] = r
    statuses = [v["status"] for v in r.values()]
    overall = "PASSED" if all(s == "PASSED" for s in statuses) else "FAILED"
    log.info(f"  PHASE 6 OVERALL: {overall}")
    return r


# ==============================================================================
# Phase 7 — Application connectivity analysis
# ==============================================================================
def phase7_connectivity():
    log.info("=" * 60)
    log.info("PHASE 7 — Application connectivity analysis")
    r = {}

    models = {
        "ppo": {
            "api_mode": "marl_ppo",
            "runtime_constructor": "MARLCorridorController(algorithm='ppo')",
            "checkpoint_path": "checkpoints/marl_ppo_corridor.json",
            "model_loader": "MARLCorridorController.load_checkpoint()",
            "observation_builder": "CorridorObservationSpace.vectorize_junction() — 14-dim",
            "action_selection": "PPOAgent.select_action(eval_mode=True) — greedy argmax",
            "signal_dispatch": "MARLCorridorController.apply_decisions() -> SignalController.request_switch()",
            "safety_enforcement": "SignalController: min_green, max_green, yellow clearance, emergency_locked",
            "integration_gaps": ["MAPPO not in MultiIntersectionSimulation.mode dispatch"],
        },
        "dqn": {
            "api_mode": "marl_dqn",
            "runtime_constructor": "MARLCorridorController(algorithm='dqn')",
            "checkpoint_path": "checkpoints/marl_dqn_corridor.json",
            "model_loader": "MARLCorridorController.load_checkpoint()",
            "observation_builder": "CorridorObservationSpace.vectorize_junction() — 14-dim",
            "action_selection": "DQNAgent.select_action(eval_mode=True, epsilon=0) — argmax Q",
            "signal_dispatch": "MARLCorridorController.apply_decisions() -> SignalController.request_switch()",
            "safety_enforcement": "SignalController: min_green, max_green, yellow clearance, emergency_locked",
            "integration_gaps": [],
        },
        "mappo": {
            "api_mode": "marl_mappo (not yet wired into MultiIntersectionSimulation)",
            "runtime_constructor": "MARLCorridorController(algorithm='mappo')",
            "checkpoint_path": "checkpoints/p6/mappo_stage_a_best.json",
            "model_loader": "MARLCorridorController.load_checkpoint() — also loads shared_critic_weights",
            "observation_builder": "local: CorridorObservationSpace.vectorize_junction() — 14-dim; "
                                   "corridor: CorridorObservationSpace.vectorize_corridor() — 42-dim",
            "action_selection": "MAPPOAgent.select_action(local_obs, eval_mode=True) — greedy argmax probs",
            "signal_dispatch": "MARLCorridorController.apply_decisions() — same dispatch as PPO/DQN",
            "safety_enforcement": "SignalController + StarvationTracker action masking",
            "integration_gaps": [
                "MultiIntersectionSimulation.mode does not include 'mappo' — only 'marl_ppo' and 'marl_dqn'",
                "MAPPO select_action signature differs: takes local_obs, action_mask, eval_mode (no can_switch positional)",
                "MARLCorridorController.decide() calls agent.select_action(vec, eval_mode=eval_mode, can_switch=can_switch, action_mask=action_mask) — MAPPOAgent.select_action() accepts this signature",
            ],
        },
    }

    # Test actual MARLCorridorController import and construction
    try:
        from traffic_service.ai.marl_controller import MARLCorridorController
        for algo in ["ppo", "dqn", "mappo"]:
            ctrl = MARLCorridorController(algorithm=algo, seed=42)
            r[algo] = dict(models[algo])
            r[algo]["controller_instantiation"] = "OK"
            r[algo]["agent_ids"] = list(ctrl.agents.keys())
            r[algo]["algorithm_field"] = ctrl.algorithm
            if algo == "mappo":
                r[algo]["shared_critic_created"] = ctrl.shared_critic is not None
            log.info(f"  MARLCorridorController({algo}): instantiated OK, agents={list(ctrl.agents.keys())}")
    except Exception as e:
        for algo in ["ppo", "dqn", "mappo"]:
            r.setdefault(algo, {})["error"] = str(e)
        log.error(f"  PHASE 7 controller error: {e}")

    # Inspect MultiIntersectionSimulation mode dispatch
    try:
        import inspect
        from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation
        src = inspect.getsource(MultiIntersectionSimulation)
        r["multi_sim_modes"] = {
            "has_marl_ppo": "marl_ppo" in src,
            "has_marl_dqn": "marl_dqn" in src,
            "has_mappo": "mappo" in src and "marl_mappo" in src,
            "note": "MAPPO is in MARLCorridorController but not in MultiIntersectionSimulation.mode dispatch",
        }
        log.info(f"  MultiIntersectionSimulation MARL modes: ppo={r['multi_sim_modes']['has_marl_ppo']}, dqn={r['multi_sim_modes']['has_marl_dqn']}, mappo={r['multi_sim_modes']['has_mappo']}")
    except Exception as e:
        r["multi_sim_error"] = str(e)

    results["phase7_connectivity"] = r
    return r


# ==============================================================================
# Phase 8 — Bounded SUMO inference test
# ==============================================================================
def phase8_sumo_inference():
    log.info("=" * 60)
    log.info("PHASE 8 — Bounded SUMO inference test (PPO best checkpoint)")
    r = {"status": "NOT_RUN", "details": {}}

    sumocfg = PROJECT_ROOT / "sumo/silk_board/silk_board.sumocfg"
    if not sumocfg.exists():
        r["status"] = "BLOCKED"
        r["blocker"] = f"sumocfg not found: {sumocfg}"
        log.warning(f"  SUMO config not found: {sumocfg}")
        results["phase8_sumo"] = r
        return r

    try:
        import traci
        import numpy as np
        from traffic_service.ai.marl_controller import MARLCorridorController
        from traffic_service.ai.env import CorridorObservationSpace

        # Load PPO best checkpoint
        cp_path = CHECKPOINT_DIR / "p6/ppo_stage_a_best.json"
        ctrl = MARLCorridorController(algorithm="ppo", seed=42)
        ok = ctrl.load_checkpoint(cp_path)
        if not ok:
            raise RuntimeError(f"Failed to load checkpoint: {cp_path}")
        r["details"]["checkpoint_loaded"] = str(cp_path)

        # Observation space
        obs_space = CorridorObservationSpace(junctions=["J1", "J2", "J3"])

        tls_ids = {
            "J1": "1617743335",
            "J2": "GS_cluster_10282769895_10775075568_11964440742_11964440743",
            "J3": "6970466614",
        }
        approach_lanes = {
            "J1": {"corridor_hosur": ["172853382#2_0", "172853382#2_1"], "side_cross": ["-148697299_0"]},
            "J2": {"corridor_hosur": ["172853382#3_0", "172853382#3_1", "464465165#0_0", "464465165#0_1", "464465165#0_2"], "madiwala": ["92196679#0_0", "92196679#0_1"]},
            "J3": {"corridor_hosur": ["1148717038#0_0", "1148717038#0_1"], "side_cross": ["-744783934_0"]},
        }

        # Start SUMO (no GUI, short run)
        sumo_binary = "sumo"
        sumo_cmd = [
            sumo_binary,
            "-c", str(sumocfg),
            "--begin", "0",
            "--end", "120",
            "--step-length", "1",
            "--no-step-log",
            "--no-warnings",
        ]
        log.info(f"  Starting SUMO: {' '.join(sumo_cmd[:4])}...")
        traci.start(sumo_cmd, label="p6_audit")

        step = 0
        max_steps = 120
        obs_records = []
        action_records = []
        safety_records = []
        green_phases = {"J1": {0, 2}, "J2": {0, 2}, "J3": {0, 2}}
        yellow_transitions = {"J1": {0: 1, 2: 3}, "J2": {0: 1, 2: 3}, "J3": {0: 1, 2: 3}}
        last_phase = {}
        phase_start = {}
        min_green = 15.0

        def get_obs(j, tls, lanes, sim_t):
            """Minimal observation builder from live TraCI data."""
            try:
                phase = traci.trafficlight.getPhase(tls)
                total_q = sum(traci.lane.getLastStepHaltingNumber(ln) for lns in lanes.values() for ln in lns)
                total_wait = sum(traci.lane.getWaitingTime(ln) for lns in lanes.values() for ln in lns)
                veh_count = sum(traci.lane.getLastStepVehicleNumber(ln) for lns in lanes.values() for ln in lns)
                speeds = []
                for lns in lanes.values():
                    for ln in lns:
                        s = traci.lane.getLastStepMeanSpeed(ln)
                        if s >= 0:
                            speeds.append(s * 3.6)
                avg_speed = float(np.mean(speeds)) if speeds else 0.0
                elapsed = sim_t - phase_start.get(j, 0.0)
                q_dict = {k: sum(traci.lane.getLastStepHaltingNumber(l) for l in lns) for k, lns in lanes.items()}
                return {
                    "phase": phase,
                    "phase_elapsed": elapsed,
                    "time_to_switch": max(0.0, min_green - elapsed),
                    "total_queue": total_q,
                    "total_waiting_time": total_wait,
                    "vehicle_count": veh_count,
                    "average_speed_kmh": avg_speed,
                    "co2_mg_s": 0.0,
                    "upstream_expected_inflow": 0.0,
                    "approaching_platoons_count": 0,
                    "emergency_approaching": False,
                    "approach_queues": q_dict,
                }
            except Exception as ex:
                return {}

        try:
            decision_interval = 5
            while step < max_steps:
                traci.simulationStep()
                sim_time = float(traci.simulation.getTime())
                step += 1

                # Track phase starts
                for j, tls in tls_ids.items():
                    try:
                        p = traci.trafficlight.getPhase(tls)
                        if last_phase.get(j) != p:
                            phase_start[j] = sim_time
                            last_phase[j] = p
                    except Exception:
                        pass

                if step % decision_interval == 0:
                    # Build observations
                    raw_obs = {
                        j: get_obs(j, tls_ids[j], approach_lanes[j], sim_time)
                        for j in ["J1", "J2", "J3"]
                    }
                    obs_ok = all(bool(v.get("phase") is not None) for v in raw_obs.values())

                    if obs_ok:
                        # Agent decisions (eval_mode, no weight updates)
                        decisions = ctrl.decide(raw_obs, sim_time, eval_mode=True)
                        obs_records.append({"step": step, "sim_time": sim_time, "obs": {
                            j: {"phase": raw_obs[j].get("phase"), "total_queue": raw_obs[j].get("total_queue")}
                            for j in ["J1","J2","J3"]
                        }})
                        action_records.append({"step": step, "decisions": {
                            j: {
                                "action": d.get("action"),
                                "action_name": d.get("action_name"),
                                "is_fallback": d.get("is_fallback"),
                            }
                            for j, d in decisions.items()
                        }})

                        # Apply decisions — safety enforced by SignalController if present
                        # (no controllers attached in this isolated test, decisions are computed only)
                        for j, dec in decisions.items():
                            action = dec.get("action")
                            is_fallback = dec.get("is_fallback", False)
                            valid_action = 0 <= action <= 2
                            safety_records.append({
                                "step": step, "junction": j,
                                "action": action, "action_name": dec.get("action_name"),
                                "is_fallback": is_fallback, "valid_range": valid_action,
                                "is_starvation_prevention": dec.get("is_starvation_prevention", False),
                            })

        finally:
            traci.close()
            log.info(f"  SUMO process closed cleanly after {step} steps")

        r["details"]["steps_completed"] = step
        r["details"]["obs_records_count"] = len(obs_records)
        r["details"]["action_records_count"] = len(action_records)
        r["details"]["sample_obs"] = obs_records[:3] if obs_records else []
        r["details"]["sample_actions"] = action_records[:3] if action_records else []
        r["details"]["safety_records_count"] = len(safety_records)

        # Validate all actions
        all_valid = all(sr["valid_range"] for sr in safety_records)
        marl_decisions = [sr for sr in safety_records if not sr["is_fallback"]]
        fallback_decisions = [sr for sr in safety_records if sr["is_fallback"]]
        starvation_overrides = [sr for sr in safety_records if sr["is_starvation_prevention"]]

        r["details"]["all_actions_valid_range"] = all_valid
        r["details"]["marl_decisions_count"] = len(marl_decisions)
        r["details"]["fallback_decisions_count"] = len(fallback_decisions)
        r["details"]["starvation_overrides_count"] = len(starvation_overrides)

        log.info(f"  Steps: {step}, MARL decisions: {len(marl_decisions)}, "
                 f"Fallback: {len(fallback_decisions)}, Starvation overrides: {len(starvation_overrides)}")
        log.info(f"  All actions valid [0-2]: {all_valid}")

        # Safety enforcement note (no SignalController attached — inference-only test)
        r["details"]["safety_note"] = (
            "SignalControllers not attached in this isolated inference test. "
            "MARL decisions computed but not dispatched to TraCI. "
            "Safety (min_green, yellow, max_green) is enforced at dispatch time by SignalController."
        )

        r["status"] = "PASSED" if (step > 0 and all_valid and obs_records) else "FAILED"

    except Exception as e:
        r["status"] = "FAILED"
        r["error"] = str(e)
        r["traceback"] = traceback.format_exc()
        log.error(f"  PHASE 8 FAILED: {e}")
        try:
            traci.close()
        except Exception:
            pass

    results["phase8_sumo"] = r
    log.info(f"  PHASE 8 STATUS: {r['status']}")
    return r


# ==============================================================================
# Main
# ==============================================================================
if __name__ == "__main__":
    log.info("╔═══════════════════════════════════════════════════════════╗")
    log.info("║  P6.3 — LEARNED MODEL RUNTIME VERIFICATION               ║")
    log.info("╚═══════════════════════════════════════════════════════════╝")

    phase2_environment()
    phase3_historical_ppo()
    phase4_historical_dqn()
    phase5_p6_ppo()
    phase5_p6_dqn()
    phase6_mappo()
    phase7_connectivity()
    phase8_sumo_inference()

    # Save raw results JSON
    out_path = PROJECT_ROOT / "scratch/p6_3_audit_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log.info(f"\nRaw results saved to: {out_path}")

    log.info("\n" + "=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)
    for phase, v in results.items():
        if isinstance(v, dict):
            if "status" in v:
                log.info(f"  {phase}: {v['status']}")
            else:
                sub = {k: vv.get("status","?") for k, vv in v.items() if isinstance(vv, dict)}
                log.info(f"  {phase}: {sub}")

