"""
P6.4 Phase A — Static dispatch trace verification via source code analysis.
Confirms the checkpoint gap without importing backend (pydantic/fastapi) dependencies.
"""
import sys, json, re, inspect, pathlib

ROOT = pathlib.Path(r"C:\Developers\Sneha\Projects\hybrid-traffic-control")
sys.path.insert(0, str(ROOT))

results = {}

# ---- 1. Source-level: SimulationStartRequest schema (schemas.py) ----
schemas_src = (ROOT / "backend" / "schemas.py").read_text()
# Find fields in SimulationStartRequest
req_block_match = re.search(
    r"class SimulationStartRequest\(BaseModel\):.*?(?=\n\nclass |\nclass |\Z)",
    schemas_src, re.DOTALL
)
req_block = req_block_match.group(0) if req_block_match else ""
results["SimulationStartRequest_block"] = req_block[:600]
results["checkpoint_path_in_schema"] = "checkpoint_path" in req_block

# ---- 2. Source-level: start_simulation() signature in simulation_service.py ----
svc_src = (ROOT / "backend" / "simulation_service.py").read_text()
sig_match = re.search(
    r"def start_simulation\(.*?\) -> StartupResult:", svc_src, re.DOTALL
)
sig_text = sig_match.group(0) if sig_match else "NOT_FOUND"
results["start_simulation_signature"] = sig_text
results["checkpoint_path_in_start_simulation"] = "checkpoint_path" in sig_text

# ---- 3. Source-level: worker construction of MultiIntersectionSimulation ----
mis_block_match = re.search(
    r"sim = MultiIntersectionSimulation\([^)]*\)", svc_src, re.DOTALL
)
worker_block = mis_block_match.group(0) if mis_block_match else "NOT_FOUND"
results["worker_construction_snippet"] = worker_block
results["checkpoint_path_passed_in_worker"] = "checkpoint_path" in worker_block

# ---- 4. Source-level: MultiIntersectionSimulation.__init__ signature ----
mis_src = (ROOT / "traffic_service" / "multi_intersection_simulation.py").read_text()
mis_sig_match = re.search(
    r"def __init__\(.*?\) -> None:", mis_src, re.DOTALL
)
mis_sig_text = mis_sig_match.group(0) if mis_sig_match else "NOT_FOUND"
results["MultiIntersectionSimulation_init_signature"] = mis_sig_text
results["checkpoint_path_in_MIS"] = "checkpoint_path" in mis_sig_text

# ---- 5. Default checkpoint path in MIS source ----
default_match = re.search(
    r'ckpt_file = .*?(?=\n\s*if !?ckpt_file)', mis_src, re.DOTALL
)
results["MIS_default_checkpoint_resolution"] = default_match.group(0).strip() if default_match else "NOT_FOUND"

# ---- 6. Checkpoint file existence ----
files = {
    "p6_ppo_stage_a_best":  ROOT / "checkpoints" / "p6" / "ppo_stage_a_best.json",
    "p6_dqn_stage_a_best":  ROOT / "checkpoints" / "p6" / "dqn_stage_a_best.json",
    "hist_ppo_corridor":    ROOT / "checkpoints" / "marl_ppo_corridor.json",
    "hist_dqn_corridor":    ROOT / "checkpoints" / "marl_dqn_corridor.json",
}
results["checkpoint_files"] = {
    k: {"exists": v.is_file(), "bytes": v.stat().st_size if v.is_file() else 0}
    for k, v in files.items()
}

# ---- 7. Confirm _run_marl_with_logging call chain ----
marl_chain = re.search(
    r"def _run_marl_with_logging.*?(?=\n    def )", svc_src, re.DOTALL
)
chain_text = marl_chain.group(0) if marl_chain else "NOT_FOUND"
results["_run_marl_with_logging_body"] = chain_text[:800]
results["chain_calls_get_ai_observations"] = "get_ai_observations" in chain_text
results["chain_calls_decide_eval_mode_true"] = "eval_mode=True" in chain_text
results["chain_calls_apply_decisions"] = "marl_controller.apply_decisions" in chain_text

# ---- 8. Router: accepted mode values ----
router_src = (ROOT / "backend" / "routers" / "simulation.py").read_text()
valid_modes_match = re.search(r'valid_modes\s*=\s*\{[^}]+\}', router_src)
results["router_valid_modes"] = valid_modes_match.group(0) if valid_modes_match else "NOT_FOUND"
results["router_checkpoint_param_in_start"] = "checkpoint_path" in router_src

# ---- 9. Summary ----
results["SUMMARY"] = {
    "checkpoint_gap_confirmed": (
        not results["checkpoint_path_in_schema"] and
        not results["checkpoint_path_in_start_simulation"] and
        not results["checkpoint_path_passed_in_worker"] and
        results["checkpoint_path_in_MIS"]
    ),
    "MIS_accepts_checkpoint_path": results["checkpoint_path_in_MIS"],
    "API_no_checkpoint_param": not results["checkpoint_path_in_schema"],
    "service_no_checkpoint_param": not results["checkpoint_path_in_start_simulation"],
    "worker_no_checkpoint_passthrough": not results["checkpoint_path_passed_in_worker"],
    "marl_dispatch_chain_complete": (
        results["chain_calls_get_ai_observations"] and
        results["chain_calls_decide_eval_mode_true"] and
        results["chain_calls_apply_decisions"]
    ),
}

out = ROOT / "scratch" / "p6_4_phase_a_results.json"
out.write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
print(f"\nResults saved to: {out}")
