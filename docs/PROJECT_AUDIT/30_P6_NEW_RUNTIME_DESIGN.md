# P6.2.4 — New Reproducible Runtime Design

**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Branch / baseline:** `marl-p6-2-curriculum-training` / `1d55856`  
**Scope:** Read-only environment design. This specifies a new runtime for future development and validation. It does not reproduce, or claim to reproduce, the unknown Stage A environment. No packages, environments, manifests, source, checkpoints, or experiment artifacts were changed; no training or SUMO experiment was run.

## Executive recommendation

The repository can move to a documented, CPU-first runtime design for owner review. A practical starting target is 64-bit CPython 3.13.17, NumPy 2.5.2, PyTorch 2.15.0 CPU, pytest 9.2.0, and the project-validated SUMO 1.26.0 distribution with its own `tools` directory supplying TraCI and sumolib. The Python, NumPy, PyTorch, and pytest versions are proposed pins supported by official Python/wheel/support evidence, but have not been installed or tested together with this project. SUMO 1.26.0 has project validation history, but is not proven to be Stage A's version.

The CPU choice follows the code: the MARL paths use CPU tensors and contain no device selection or CUDA calls. The visible host does have an NVIDIA GeForce RTX 2050 with 4 GB, but the current project does not use it. CPU is appropriate for loading and inference and is the lower-variance default for controlled future training; whether Stage B's 1,200-second episodes fit a desired wall-clock budget is unknown and should be profiled only after environment setup is separately approved.

**Recommendation: `RUNTIME DESIGN: READY FOR OWNER REVIEW`.** This is design readiness only. It does not authorize environment creation, checkpoint validation, Stage B, or any experiment.

## 1. Evidence basis and boundaries

Read the requested reports `21`, `25`, `27`, and `29`, inspected imports and relevant agent/model/controller/checkpoint code, and checked the present interpreter and package inventory. The working tree already had uncommitted P6.2 source changes and untracked Stage A routes/results/checkpoints plus reports 27 and 29. They remain untouched. The only current interpreter found was `C:\Program Files\Python313\python.exe`, Python 3.13.14; its package inventory contained pip 26.1.2 only. SUMO executables are on PATH. The October 31, 2026 stress-test report records Python 3.13.14, pytest 9.1.1, SUMO 1.25.0 and a web-stack version set, but that environment is not tied to Stage A.

The repository has no dependency manifest, Python version pin, Dockerfile, or CI environment in the available current or historical local Git trees. Report 29 found no removed manifest among available refs. Thus all package pins below are proposed for a new environment, not recovered historical values. Exact app-stack resolution and full project compatibility remain to be verified after owner approval of a separate setup task.

## 2. Dependency inventory

### Mandatory for P6 MARL and SUMO operation

| Role | Dependencies | Source evidence / classification |
|---|---|---|
| Numerical arrays | NumPy | Direct imports in `traffic_service/ai/env.py`, all three agents, model wrappers and training scripts. Required. |
| MARL model/training | PyTorch | DQN and PPO import `torch` and `torch.nn` unconditionally (`dqn_agent.py`, `ppo_agent.py`). The active corridor controller imports/constructs those agent classes for algorithm dispatch, so the actual controller entry path requires Torch for MAPPO, PPO and DQN. P4 report also records autograd training for PPO/DQN. Required. |
| Simulation engine | Eclipse SUMO executable and network tools | `common/sumo_env.py`, SUMO manager and simulation use external binaries. Required for simulation-backed validation/training; not a pip dependency. |
| Python SUMO interface/tools | TraCI and sumolib from the same SUMO installation | Source imports `traci` and `sumolib`; project helper resolves SUMO's `<SUMO_HOME>/tools`. Use the bundled tools to keep client/server versions aligned. SUMO documentation describes this import-path option and recommends checking `traci.__file__`. |

`TORCH_AVAILABLE` has optional/fallback logic in `traffic_service/ai/models.py` and `mappo_agent.py`; that does not make the full execution paths Torch-optional. DQN and PPO have unconditional top-level Torch imports, and controller dispatch imports them. Furthermore, a no-Torch MAPPO fallback is not the verified autograd CTDE implementation. Do not use fallback mode to train or validate the P6 algorithms.

### Backend/application dependencies

| Dependency | Used for | Classification |
|---|---|---|
| FastAPI | API, websocket endpoints, `TestClient` tests | Required for full backend application and suite; not required for a standalone MARL script. |
| Pydantic | API schemas and validation | Required by backend. |
| SQLAlchemy | database models/session | Required by backend and API tests. |
| python-dotenv | `.env` loading | Imported by backend config; required by current backend startup path. |
| Uvicorn | ASGI serving command/runtime | Runtime server dependency if the documented service is launched with Uvicorn; source should be checked for exact launch method at setup time. |
| scikit-learn | DBSCAN/hotspot analysis | Used by `traffic_service/hotspot_analyzer.py`; required for that feature/tests, not for MARL controller math itself. |

### Testing, optional analysis, and development dependencies

| Dependency | Scope | Notes |
|---|---|---|
| pytest | Test runner | Required to run Python test suite. Plugin needs should be determined from pytest configuration/imports during setup; none is pinned by current manifest. |
| HTTPX | FastAPI `TestClient` backend | Likely needed by Starlette's test client; include in test extra and verify resolver/runtime compatibility rather than treating it as a standalone application import. |
| WebSockets | websocket test/client support | Full-stack tests and app websocket stack depend on a compatible WebSocket implementation, often supplied by the chosen ASGI/test dependency set. Resolve and lock explicitly. |
| SciPy | P5 statistical evaluation script | `scripts/evaluate_p5_controllers.py` imports `scipy.stats`; optional for P6 MARL operation, needed only for that analysis tool. |
| pywin32 | Windows-only stress tests | `tests/test_full_stack_stress.py` imports Windows process APIs. Test-only and platform-specific, not a cross-platform runtime dependency. |
| Frontend Node packages | frontend build/test | Separate from Python environment; this design does not prescribe Node versions or modify the frontend lockfile. |

The above reflects imports and call paths inspected; it is not a complete transitive dependency lock. Python standard-library modules are omitted.

## 3. Runtime compatibility matrix

| Component | Proposed baseline | Evidence status | Assessment / remaining validation |
|---|---|---|---|
| CPython | 3.13.17, 64-bit Windows | **Candidate, official Windows installer** | Python.org identifies 3.13.17 as the last 3.13 bugfix release with binary installers; PyTorch 2.15 supports Python 3.11–3.15 and its official CPU index lists a Windows `cp313` wheel. |
| NumPy | 2.5.2 | **Candidate, officially supports 3.12–3.15** | Official release notes state support for Python 3.12–3.15. Need integration validation with code and selected Torch wheel; historical Stage A NumPy is unknown. |
| PyTorch | 2.15.0 CPU wheel | **Candidate, official Windows CPython 3.13 wheel** | Official CPU index lists `torch-2.15.0+cpu-cp313-cp313-win_amd64.whl`; PyTorch 2.15 docs/blog state Python 3.11–3.15 support. Candidate is a compatible wheel, not project-tested. |
| pytest | 9.2.0 | **Candidate, official release and Python support policy** | Release announced October 27, 2026. pytest 9.0+ supports Python 3.10+, therefore 3.13 is in range. Full project suite still needs to run in the new env. |
| SUMO | 1.26.0 | **Project-history confirmed; new baseline candidate** | P6.2.1 route/type checks succeeded against SUMO 1.26.0. Other project validation records also use it. This is not evidence that Stage A used 1.26.0; project history includes other SUMO versions. |
| TraCI / sumolib | bundled tools for SUMO 1.26.0 | **Strategy confirmed by official docs; pair untested here** | SUMO documentation says add `<SUMO_HOME>/tools` to Python path and check actual `traci` import path. Avoid separately installing pip `traci`/`sumolib`, which can silently mismatch the binary. |
| FastAPI, Starlette, Uvicorn, AnyIO, WebSockets | versions recorded in Oct. 31 full-stack report | **Historically confirmed for that stress-test environment only** | Report records FastAPI 0.141.1, Starlette 1.3.1, Uvicorn 0.52.1, AnyIO 4.14.2, WebSockets 16.1.1 with Python 3.13.14. They are potential starting candidates, not confirmed compatible with the new pins or P6 Stage A. Resolve and test together. |
| Pydantic, SQLAlchemy, dotenv, scikit-learn, HTTPX, SciPy | no defensible exact pin from Stage A evidence | **Unknown** | Include only as needed in runtime/test/analysis groups. Choose exact versions during separately authorized setup based on official metadata, compatible wheels, and the project suite; lock resolver output. |

Official compatibility sources: [PyTorch 2.15 release information](https://pytorch.org/blog/pytorch-2-15-release-blog/), [PyTorch CPU wheel index](https://download.pytorch.org/whl/cpu/torch/), [NumPy 2.5.2 release notes](https://numpy.org/devdocs/release/2.5.2-notes.html), [pytest 9.2 announcement](https://docs.pytest.org/en/stable/announce/release-9.2.0.html), [pytest Python support policy](https://docs.pytest.org/en/latest/backwards-compatibility.html), [SUMO TraCI Python interface](https://sumo.dlr.de/docs/TraCI/Interfacing_TraCI_from_Python.html). These sources establish package support and wheel availability, not successful end-to-end compatibility with this project.

## 4. CPU/GPU recommendation

The observed host has an NVIDIA GeForce RTX 2050 (4 GB) and a reported NVIDIA driver 592.00. This is hardware evidence for this machine only, not a requirement for other developers. In the inspected source, neural networks and optimizer tensors are constructed without a CUDA device, tensors are created from NumPy on CPU, and no `.to("cuda")` or `torch.device("cuda")` path is present. Thus CPU-only Torch is sufficient for checkpoint loading, deterministic inference, unit tests, and the current Stage B training code path. CUDA is not required by the implementation.

Recommend the CPU wheel for the first reproducible baseline. The workload is three small agents per run (network dimensions documented in P6.1 and code) and one SUMO simulator process; it is plausible CPU training is practical, but wall-clock duration cannot be responsibly estimated without an experiment. Profile runtime only as part of an authorized environment validation step. GPU acceleration would require explicit device plumbing and a separately validated CUDA Torch build; the 4 GB RTX 2050 may constrain memory and no speed benefit is established. CPU-only also avoids CUDA/cuDNN/driver variation and is the clearest deterministic baseline. Deterministic outcomes still require recording all RNG seeds and controlling any nondeterministic operators; CPU alone does not guarantee bitwise reproducibility across library/OS/CPU builds.

## 5. Checkpoint compatibility analysis

The inspected `MARLCorridorController.save_checkpoint()` writes JSON. Agent `get_state_dict()` methods obtain model weights as NumPy arrays and convert arrays to nested Python lists; the controller emits algorithm/version/seed/junction metadata and agent state, plus MAPPO's shared critic data. Checkpoints therefore contain ordinary JSON numeric lists and scalar metadata, not NumPy binary arrays, `torch.save` archives, or PyTorch `state_dict` objects. The names `get_state_dict` / `load_state_dict` here describe application dictionaries and should not be confused with Torch serialization.

The source-defined architecture permits reconstruction when the matching algorithm code is used: expected agents are ordered by the controller's junction list (default J1, J2, J3); the per-agent weights are then converted to float32 arrays and loaded into model wrappers. P6.1 identifies the MAPPO CTDE topology and the code records algorithm version, but checkpoints do not contain a full architecture/schema description or package-version/device metadata. Existing controller loading uses source defaults and validates only parts of the shape/schema; future setup validation should explicitly assert algorithm, agent IDs/order, each tensor name/shape, and finite outputs.

The JSON representation is device-independent and CPU loading/inference is feasible. Deterministic inference is possible without optimizer state: inference consumes loaded model parameters and fixed observations, while optimizer states are only needed to resume training. Current checkpoints do not save optimizer state, so exact training continuation is not supported. Inference determinism requires evaluation/greedy action mode and fixed input; stochastic sampling is not deterministic unless RNG state is controlled.

The three agents within each checkpoint are intended to share algorithm-specific architecture, but a complete cross-check of every saved checkpoint's tensors is not performed in this design task (the request explicitly says not to load checkpoints). Treat consistency as an unverified validation gate. MAPPO has per-junction actors and a shared centralized critic; do not mistake three agents for three independently saved critics. The Stage A final checkpoint is documented in report 27 as the last seed's seed-55 controller, accompanied by aggregate-run metadata, not a multi-seed aggregate model.

## 6. Proposed environment specification

### Exact candidate pins

| Component | Proposed value | Why / caveat |
|---|---|---|
| Python | CPython 3.13.17 x64 | Last 3.13 release with official Windows installer; common baseline with official Torch 2.15 CPython 3.13 Windows CPU wheel. New runtime only. |
| NumPy | 2.5.2 | Official support includes Python 3.13. This point version is conservative relative to latest patch; project ABI/integration must be checked. |
| PyTorch | 2.15.0 CPU (`+cpu` wheel) | Official Windows CPython 3.13 CPU wheel is listed. Keep CPU-only initially. |
| pytest | 9.2.0 | Official release; Python 3.13 falls inside pytest 9 support policy. |
| SUMO | 1.26.0 x64 Windows | Matches the project route/type validation baseline. Install/locate separately from Python packages and capture its executable path and full version output. |
| TraCI / sumolib | `<SUMO_HOME>/tools` from the same SUMO 1.26.0 install | Do not put independent pip copies ahead of this import path. Capture actual import file paths. |

The four Python exact pins are compatibility-backed proposals, not confirmed pins. NumPy 2.5.4 appears in the official release listing as newer, but 2.5.2 has explicit Python compatibility notes retrieved for this audit; using 2.5.2 makes the rationale reviewable and should not be described as newest. Owner may approve a different target before setup.

### Remaining dependency groups

The future manifest should have distinct groups rather than making every tool mandatory:

- **core/MARL:** NumPy, CPU PyTorch, plus SUMO's external runtime/tools integration.
- **application:** FastAPI, Pydantic, SQLAlchemy, python-dotenv, Uvicorn, scikit-learn, and any verified API/websocket runtime dependencies.
- **test:** pytest, HTTPX, websocket test/runtime support, and Windows-only pywin32 only for tests that import it.
- **analysis:** SciPy for the P5 statistical evaluator; other analysis packages only when direct imports require them.
- **frontend:** keep the separately managed Node dependency lock as-is and document the Node runtime independently.

Exact pins for the remaining groups are intentionally not fabricated. In the setup task, resolve versions from official package metadata for CPython 3.13/Windows x64 and test the actual backend/full-suite imports, then commit the selected manifest and complete lock only after approval.

## 7. Proposed setup and reproducibility procedure

These are steps for a separately authorized setup task; none was executed here.

1. Install/identify the approved 64-bit CPython 3.13.17 and SUMO 1.26.0 x64. Set a stable `SUMO_HOME` to the SUMO installation root. Record installer/source and executable paths.
2. Create a project-local ignored environment at `.venv-p6` (or another explicitly chosen path) using the pinned interpreter. Keep it out of Git. Python's `venv` is disposable and should be recreated from declared dependencies, not copied between machines.
3. Add a reviewed dependency manifest with the exact core pins and runtime/test/analysis groups above. Resolve and commit a complete lock with hashes where the selected tool supports them; record the resolver/tool version. Do not add separate `traci` or `sumolib` distributions while using bundled tools.
4. Confirm active interpreter, architecture, `python -m pip --version`, and `python -m pip freeze --all`. Capture package metadata (`importlib.metadata`) to a setup report. The lock is the authority; a freeze file is an execution record, not a replacement for the lock.
5. Confirm `sumo --version` (and resolved executable full path), `SUMO_HOME`, and that `Path(traci.__file__)` and `Path(sumolib.__file__)` are under the selected `<SUMO_HOME>/tools`. Run only a no-traffic version/import check at setup validation; route/simulation checks require explicit experiment authorization.
6. Run targeted non-training checks first: import each algorithm/controller, load each existing JSON checkpoint using the application's loader, assert J1/J2/J3 ordering, algorithm and shape compatibility, and generate fixed-observation inference twice in greedy/evaluation mode. Record outputs and whether they match. Then run the requested targeted tests and full backend suite as authorized; no training is needed for these checks.
7. Before any future experiment, create a unique immutable run directory; refuse to reuse an existing directory. Store an experiment manifest before the first simulation and append completion/failure status without rewriting historical artifacts.

### Environment and experiment capture fields

Record at minimum:

- UTC start/end, host OS/build and architecture, CPU model, RAM, GPU model/VRAM/driver if present;
- Python implementation/full version, executable path, pip/resolver version, locked dependency file hash, installed package versions;
- SUMO executable path, full version, configuration/network/route/additional-file hashes, `SUMO_HOME`, TraCI/sumolib resolved import paths;
- code commit and dirty-tree indicator/diff hash, script arguments, algorithm, stage, episode budget, seeds, policy/checkpoint path and hash;
- device (`cpu` or CUDA device string), deterministic settings/RNG seeds for Python, NumPy, Torch and SUMO, configuration JSON hash;
- per-run ID, start/end state, errors/exit code, checkpoint role (best/per-seed/last-seed), and metrics schema/version.

## 8. Known risks and validation gates

- Stage A's original Python, NumPy, PyTorch, pytest and exact SUMO runtime remain unrecoverable from available evidence; this design creates a new baseline only.
- Official wheel/support evidence is not a substitute for installing and running the project's own checks. NumPy 2.x behavior, Torch integration, app dependency compatibility and Windows wheels remain to be validated together.
- Historical full-stack versions (Python 3.13.14 and SUMO 1.25.0) are from another test run, not proof that Stage A or P6.1 used those exact versions.
- `TORCH_AVAILABLE` fallback could make isolated model/MAPPO imports appear optional, but actual controller execution of all algorithms imports Torch-required DQN/PPO modules. Require Torch for the supported P6 runtime.
- Existing JSON checkpoints omit optimizer state, full architecture metadata and dependency provenance. They can support inference after schema/shape validation but cannot resume the same optimizer trajectory.
- CPU training runtime is unknown. GPU support is not wired into code; adding it would be a separate design/implementation and reproducibility decision.
- The run-ID/output-collision risk from deterministic names was reported in P6.2.1. The new runtime setup should not start training or use those existing result/checkpoint paths.

## 9. Exact next steps after owner review

1. Approve or revise the proposed Python 3.13.17 / NumPy 2.5.2 / PyTorch 2.15.0 CPU / pytest 9.2.0 / SUMO 1.26.0 baseline.
2. In a separately authorized setup task, create the ignored virtual environment and reviewed manifest/lock, selecting exact pins for backend/test/optional dependencies using official package metadata and available Windows wheels.
3. Run package imports and record the resolved environment; verify SUMO binary and bundled TraCI/sumolib paths.
4. Load all existing P6 checkpoints with actual controller loaders; validate junction order/shapes and fixed-input inference. Preserve checkpoints.
5. Run approved targeted tests and then the relevant full suite. Report failures without silently changing algorithms or historical artifacts.
6. Present setup and checkpoint evidence for a separate owner decision. Stage B remains NO-GO unless and until separately authorized.

## Sources

- [Python 3.13.17 release](https://www.python.org/downloads/release/python-31317/) — last Python 3.13 release with Windows binary installer.
- [PyTorch 2.15 release information](https://pytorch.org/blog/pytorch-2-15-release-blog/) and [official CPU wheel index](https://download.pytorch.org/whl/cpu/torch/) — Python support and Windows `cp313` CPU wheel availability.
- [NumPy 2.5.2 release notes](https://numpy.org/devdocs/release/2.5.2-notes.html) — supported Python versions.
- [pytest 9.2.0 release announcement](https://docs.pytest.org/en/stable/announce/release-9.2.0.html) and [Python support policy](https://docs.pytest.org/en/latest/backwards-compatibility.html).
- [SUMO TraCI Python interface](https://sumo.dlr.de/docs/TraCI/Interfacing_TraCI_from_Python.html) — bundled `tools` import path and loaded-module path check.
- [Python `venv` documentation](https://docs.python.org/3/library/venv.html) — isolated and reproducible environment creation guidance.

**RUNTIME DESIGN: READY FOR OWNER REVIEW**
