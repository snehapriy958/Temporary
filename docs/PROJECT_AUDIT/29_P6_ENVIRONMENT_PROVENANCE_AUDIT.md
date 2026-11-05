# P6.2.3 — Python Environment and Dependency Provenance Audit

**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Branch / baseline:** `marl-p6-2-curriculum-training` / `1d55856`  
**Audit mode:** Read-only. No packages were installed; no environment, source, or experiment files were created or modified during the investigation except this report.

## Executive finding

The repository’s local Git history and available project records do **not** recover a reproducible Python environment for Stage A. No Python dependency manifest, Python version pin, committed Dockerfile, or CI workflow exists in the current tree or local historical refs. The Stage A training harness and checkpoint metadata do not record the runtime or package versions.

There is useful but incomplete historical evidence: a dated Oct. 31, 2026 full-stack test report records Python 3.13.14, pytest 9.1.1, and SUMO 1.25.0. Other project records and the current host show SUMO 1.26.0. P4 reports confirm PyTorch was used in algorithm validation, but no report or artifact supplies its version or NumPy’s version. None of the historical environment records is explicitly tied to the P6.2 Stage A run.

**Recommendation: ENVIRONMENT NOT RECOVERABLE —** obtain the Stage A machine’s package freeze/lockfile, CI or shell history, or equivalent environment capture. If those cannot be recovered, the project owner must choose a target runtime and compatible dependency versions in a separately authorized environment setup task. Do not claim that a newly chosen environment reproduces the original Stage A runtime.

## 1. Scope and evidence sources

Inspected the active working tree and local Git refs, tracked-path history, current interpreter/package inventory, P6.2 harness and metadata format, checkpoint serializer/loader code, P4/P6.1/P6.2 reports, and existing environment audit/roadmap documents. No remote-tracking Git refs were present in the local repository, so this audit cannot inspect un-fetched remote branches or external developer-machine state.

The current working tree remains as it was before this task: P6.2 source modifications and untracked Stage A results/checkpoints/routes remain present. This audit did not modify them.

## 2. Dependency manifests and environment configuration

### Current and historical Git trees

The current tree and all locally available Git history were searched for:

- `requirements*.txt`, `pyproject.toml`, `poetry.lock`, `uv.lock`
- `Pipfile`, `Pipfile.lock`, `environment.yml` / `environment.yaml`
- `setup.py`, `setup.cfg`, `.python-version`, `tox.ini`, `pytest.ini`
- Dockerfiles and `.github/workflows/*`

**No matching Python manifest, environment file, Dockerfile, or CI workflow was found in the current tree or local Git history.** There is no historical manifest to restore from the available refs.

`docs/AUDIT/01_REPOSITORY_AUDIT.md` independently documents the same gap: no Python dependency declarations and no Docker/CI configuration. `docs/AUDIT/10_IMPLEMENTATION_ROADMAP.md` proposes creating manifests and a Docker setup, including candidate package pins and a Python 3.12/3.13 plus SUMO 1.26 image. It labels these as future work; they were not configuration or evidence of an environment actually used.

### Existing documentation and reports

- `docs/AUDIT/PHASE_2B_3D_STRESS_TEST_RESULTS.md` (dated 2026-10-31) records Python 3.13.14, pytest 9.1.1, and SUMO 1.25.0 for that stress-test environment. It also records FastAPI 0.141.1, Starlette 1.3.1, Uvicorn 0.52.1, AnyIO 4.14.2, and WebSockets 16.1.1. This is historical environment evidence, not a Stage A environment manifest.
- `docs/AUDIT/02_SUMO_SIMULATION_AUDIT.md` and P1/P2 reports record SUMO 1.26.0 for project simulation/validation work. P2 addendum also identifies historical benchmark records made on SUMO 1.28.0. These document multiple SUMO versions across project work, not the Stage A training executable.
- `docs/PROJECT_AUDIT/21_P4_RL_ALGORITHM_RECOVERY.md` confirms PyTorch/autograd was used and verified during P4. It provides no PyTorch or NumPy package version.
- `docs/PROJECT_AUDIT/25_P6_PRETRAINING_VALIDATION.md` records test results and architectural validation but no Python, NumPy, PyTorch, or pytest version.
- `docs/PROJECT_AUDIT/27_P6_STAGE_A_RECONCILIATION.md` describes the Stage A artifact inventory and notes that checkpoint loads remained unverified; it contains no package freeze or Stage A runtime capture.

## 3. Available host versions

These are confirmed for the current host at audit time, not inferred as the original Stage A environment:

| Component | Current host observation | Version classification for current host | Stage A version |
|---|---|---|---|
| Python | `C:\Program Files\Python313\python.exe`, `Python 3.13.14`; Python launcher lists only this interpreter | **CONFIRMED** | **UNKNOWN** |
| pip | `pip 26.1.2`; the installed Python distribution inventory contains only pip | **CONFIRMED** | **UNKNOWN** |
| NumPy | Import/distribution not available in the current Python installation | Version **UNKNOWN**; unavailable now | **UNKNOWN** |
| PyTorch | Import/distribution not available in the current Python installation | Version **UNKNOWN**; unavailable now | **UNKNOWN** |
| pytest | Not available in the current Python installation (`python -m pytest` reports no module) | Version **UNKNOWN**; unavailable now | **UNKNOWN** |
| SUMO | Installed executable reports Eclipse SUMO 1.26.0 | **CONFIRMED** | **UNKNOWN** |
| sumolib | Current interpreter imports SUMO’s bundled `sumolib` at version 1.26.0 | **CONFIRMED** | **UNKNOWN** |
| TraCI | Current interpreter imports SUMO’s bundled `traci` module, whose module `__version__` reports `0.0.0` | Module presence **CONFIRMED**; meaningful version **UNKNOWN** | **UNKNOWN** |

The bundled TraCI module’s `0.0.0` value is not treated as the SUMO release version. The executable itself reports SUMO 1.26.0.

## 4. Version provenance classifications

Classification refers to evidence for the version in the indicated environment. “Historically confirmed” means a dated project report recorded it for a prior task; it does not imply the Stage A task used the same environment.

| Dependency / runtime | Version evidence | Classification | Relevance and limitation |
|---|---|---|---|
| Python | 3.13.14 in current host and Oct. 31 stress-test report | **CONFIRMED** current; **HISTORICALLY CONFIRMED** in that report | Stage A process did not record `sys.version`; exact Stage A Python is **UNKNOWN**. |
| NumPy | Imported by MARL agents, observations, reward and model modules; P4/P6 tests and training architecture rely on it | Version **UNKNOWN** | Required dependency is **INFERRED** from imports; neither current nor historical version is recorded. |
| PyTorch (`torch`) | P4 report confirms PyTorch autograd and Adam were exercised; training script branches on `TORCH_AVAILABLE` | Version **UNKNOWN** | Use in P4 is **HISTORICALLY CONFIRMED**; Stage A installation/use and exact version are not captured. Current installation lacks it. |
| pytest | 9.1.1 in the Oct. 31, 2026 stress-test report | **HISTORICALLY CONFIRMED** | Current version is **UNKNOWN** and pytest is unavailable. No evidence ties 9.1.1 to P6 Stage A. |
| Eclipse SUMO | 1.25.0 in Oct. 31 stress report; 1.26.0 in project simulation audit/P1 and current host; 1.28.0 for restored historical P2 benchmarks | Each report’s version is **HISTORICALLY CONFIRMED**; current host 1.26.0 is **CONFIRMED** | Multiple versions are documented. Stage A version is **UNKNOWN**. |
| sumolib | 1.26.0 proposed in roadmap; current bundled module is 1.26.0 | Current bundled module **CONFIRMED**; roadmap statement alone is a proposal | Stage A package/toolkit version is **UNKNOWN**. |
| TraCI | Current module is bundled with SUMO tools; its self-reported `0.0.0` is non-informative | Presence **CONFIRMED**, version **UNKNOWN** | No Stage A package metadata or module path was saved. |
| FastAPI / Starlette / Uvicorn / AnyIO / WebSockets | Versions listed in Oct. 31 full-stack stress-test report | **HISTORICALLY CONFIRMED** for that report | API stack, not sufficient to reproduce MARL training; no Stage A provenance. |
| SQLAlchemy / Pydantic and other roadmap-listed packages | Exact pins appear only as proposed values in `10_IMPLEMENTATION_ROADMAP.md` | **INFERRED / proposed**, not confirmed | They must not be copied as actual installed versions without independent evidence. |

## 5. Inferred dependency requirements

The code imports NumPy throughout the AI environment, controller, agents, and model code. MAPPO/PPO/Double-DQN use PyTorch code paths when `TORCH_AVAILABLE` is true; Stage A reports include gradient-related metrics, but the script does not persist that flag or a framework version. The application also uses SUMO’s TraCI and `sumolib` tooling. Tests require pytest. Other project/server dependencies identified by the older repository audit include FastAPI, Uvicorn, Pydantic, SQLAlchemy, scikit-learn, pandas, httpx, and python-dotenv.

These imports establish likely package requirements, **not exact compatible versions**. In particular, source compatibility with Python 3.13 does not prove that the historical NumPy/PyTorch binary wheels or exact framework versions were used under 3.13. No package lock, install transcript, `pip freeze`, CI log, or Stage A manifest resolves that uncertainty.

## 6. Compatibility uncertainties

- Stage A’s Python interpreter, architecture, and environment isolation are unknown.
- NumPy and PyTorch versions are unknown; current host lacks both.
- It is not known whether Stage A used PyTorch or a non-Torch fallback for each learner; the training script does not record `TORCH_AVAILABLE`.
- The project contains evidence of SUMO 1.25, 1.26, and 1.28 use across distinct tasks. Stage A’s SUMO/TraCI version is absent from its result metadata.
- TraCI can be loaded from SUMO’s bundled tools independently of a pip package; the checkpoint and Stage A metadata do not record which module path was active.
- Historical reports record differing Python package sets from separate project tasks. They cannot safely be combined into a single Stage A environment.
- The exact P6 dependency set cannot be reconstructed from roadmap package pins because the roadmap explicitly presents them as proposed future configuration.

## 7. Reproducibility decision and setup recommendation

**The original Stage A training environment cannot currently be reproduced from the available evidence.** The latest report supplies some plausible host versions, but no source ties them to the Stage A process, and the most important numerical dependencies have no version provenance.

No exact isolated environment recipe is recommended here. Python 3.13.14 and SUMO 1.26.0 are supported as current-host observations and appear in other project records, but pinning NumPy, PyTorch, pytest, and the remaining runtime dependencies to guessed values would create a new environment, not recover Stage A. After the owner chooses between recovering the original machine’s package inventory and establishing a new supported target, a separate authorized setup task can create an isolated virtual environment and lock the tested dependency set without touching global Python.

## Conclusion

**ENVIRONMENT NOT RECOVERABLE —** the missing provenance is the Stage A Python/package freeze, exact NumPy and PyTorch versions/framework availability, and the SUMO/TraCI runtime version. Recover that evidence from the original training host or run records; otherwise obtain an explicit decision to define and validate a new target environment. This recommendation does not authorize Stage B.
