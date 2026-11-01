# STAGE P4 AUDIT REPORT: DQN AND PPO ALGORITHMIC RECOVERY AND VALIDATION

**Project:** Hybrid Traffic Control — Bengaluru Silk Board Corridor  
**Date:** 2026-11-01  
**Branch:** `marl-p4-rl-algorithm-recovery`  
**Base Commit:** `85713e3`  
**Author:** Antigravity Pairing Assistant  
**Status:** COMPLETE & VERIFIED

---

## 1. Executive Summary

Stage P4 resolves the algorithmic deficiencies identified in the historical reinforcement learning implementations (`smart-traffic-coordination/tree/ai-module`). In the historical repository, the DQN and PPO agents were synthetically simulated: rather than performing true backpropagation across network layers, the code updated only the single output bias of the final layer (`weights["adv_out_b"]` for DQN and `weights["actor_out_b"]` for PPO), leaving all feature extractor trunks, value streams, and policy layers completely frozen.

Under Stage P4:
1. **Full Autograd Backpropagation:** PyTorch-based neural architectures (`PyTorchDuelingDQN` and `PyTorchActorCritic`) were implemented, connected to PyTorch Adam optimizers, and verified to propagate non-zero gradients across all 12 parameter tensors for each agent.
2. **Double-DQN Algorithmic Correction:** Implemented target network evaluation of online argmax actions, terminal state masking with $(1 - d)$, Huber loss (`SmoothL1Loss`), gradient norm clipping ($10.0$), and smooth epsilon decay ($0.95$).
3. **Actor-Critic PPO Algorithmic Correction:** Implemented single-sample action/log-prob consistency (guaranteeing that the action executed matches the stored log probability), Generalized Advantage Estimation ($\text{GAE}-\lambda$), clipped surrogate objective ($\epsilon=0.2$), MSE value loss, and entropy regularization bonus ($\beta=0.02$).
4. **Controlled Multi-Episode Training Harness:** Executed deterministic multi-episode training on the active SUMO Silk Board corridor network for both DQN and PPO, logging loss trajectories, gradient norms, completed trips, queues, travel time, and corrected fuel/emissions.
5. **Versioned Checkpoints:** Generated new `v2.0-autograd` checkpoints (`checkpoints/marl_dqn_corridor_v2.json` and `checkpoints/marl_ppo_corridor_v2.json`) while preserving historical v1.0 checkpoints (`checkpoints/marl_{dqn,ppo}_corridor.json`) completely intact.
6. **Zero-Regression Verification:** Passed the complete backend test suite (169/169 tests passed, 100%) and frontend test suite (75/75 tests passed, 100%).

---

## 2. Root-Cause Analysis of Historical Algorithmic Defects

### A. Historical DQN Defect: Frozen Feature Extractor and Output Bias-Only Update
In the historical repository (`traffic_service/ai/dqn_agent.py`), the Q-network was defined as a multi-layer Dueling DQN (`fc1`, `fc2`, `val_fc`, `val_out`, `adv_fc`, `adv_out`). However, in `train_step()`:
```python
# HISTORICAL DEFECTIVE CODE:
weights = self.q_network.get_weights()
weights["adv_out_b"] -= self.lr * np.sum(grad, axis=0)  # Only 3 bias values updated!
self.q_network.set_weights(weights)
```
- **Consequence:** The shared representation trunk (`fc1_w`, `fc1_b`, `fc2_w`, `fc2_b`), value stream (`val_fc_w`, `val_fc_b`, `val_out_w`, `val_out_b`), and advantage weights (`adv_fc_w`, `adv_fc_b`, `adv_out_w`) never received gradient updates.
- **Terminal State Leakage:** Terminal flags were ignored, causing Q-values to bootstrap infinitely across episode boundaries.
- **Double-DQN Violation:** Standard Q-learning was used without target network action decoupling: $y = r + \gamma \max_{a'} Q_{\text{target}}(s', a')$.

### B. Historical PPO Defect: Action Resampling and Single-Bias Shift
In the historical repository (`traffic_service/ai/ppo_agent.py`):
1. **Action/Log-Prob Discrepancy:** In `select_action()`, an action was sampled, but during optimization, `old_log_probs` were computed from a re-evaluated forward pass without action masking. The importance ratio $r_t(\theta) = \frac{\pi_\theta(a_t | s_t)}{\pi_{\theta_{\text{old}}}(a_t | s_t)}$ was mathematically invalid.
2. **Actor-Only Bias Update:** In `train_step()`:
   ```python
   # HISTORICAL DEFECTIVE CODE:
   weights["actor_out_b"] += grad_p  # Only actor output bias modified!
   ```
   The critic was never updated, advantage was computed without Generalized Advantage Estimation (GAE), and minibatches were not sampled.

---

## 3. Mathematical Formulations of the Corrected Implementations

### A. Corrected Double-DQN (`traffic_service/ai/dqn_agent.py`)

#### 1. Target Value Construction
For transition $(s, a, r, s', d)$ with terminal indicator $d \in \{0, 1\}$:
$$a^* = \arg\max_{a' \in \mathcal{A}_{\text{valid}}(s')} Q_{\text{online}}(s', a'; \theta)$$
$$y = r + \gamma (1 - d) Q_{\text{target}}(s', a^*; \theta^-)$$

#### 2. Loss Function (Huber / Smooth L1)
$$\mathcal{L}(\theta) = \frac{1}{B} \sum_{i=1}^B l_i, \quad l_i = \begin{cases} 0.5 (Q(s_i, a_i; \theta) - y_i)^2 & \text{if } |Q - y| < 1.0 \\ |Q - y| - 0.5 & \text{otherwise} \end{cases}$$

#### 3. Full Backpropagation & Gradient Clipping
$$\theta \leftarrow \theta - \alpha \nabla_\theta \mathcal{L}(\theta), \quad \text{with } \|\nabla_\theta \mathcal{L}\|_2 \le 10.0$$
$$\theta^- \leftarrow \theta \quad \text{every } K \text{ steps}$$

---

### B. Corrected Actor-Critic PPO (`traffic_service/ai/ppo_agent.py`)

#### 1. Single-Sample Action Consistency
Given observation $s$, the network outputs actor logits $z$ and state value $V(s)$. With invalid actions masked ($z_k = -\infty$ for $k \notin \mathcal{A}_{\text{valid}}$):
$$a \sim \text{Categorical}(\text{softmax}(z)), \quad \log \pi_{\text{old}}(a | s) = \log\left(\frac{e^{z_a}}{\sum_j e^{z_j}}\right)$$
*Critical Invariant:* The exact action executed in SUMO is the exact action whose log probability is stored.

#### 2. Generalized Advantage Estimation ($\text{GAE}-\lambda$)
$$\delta_t = r_t + \gamma (1 - d_t) V(s_{t+1}) - V(s_t)$$
$$\hat{A}_t = \sum_{l=0}^{\infty} (\gamma \lambda)^l (1 - d_{t+l}) \delta_{t+l}$$
Normalized advantages: $\hat{A}_t^{\text{norm}} = \frac{\hat{A}_t - \mu_A}{\sigma_A + 10^{-8}}$.

#### 3. Clipped Surrogate Objective
$$r_t(\theta) = \frac{\pi_\theta(a_t | s_t)}{\pi_{\theta_{\text{old}}}(a_t | s_t)}$$
$$\mathcal{L}^{\text{CLIP}}(\theta) = -\mathbb{E}_t \left[ \min\left( r_t(\theta) \hat{A}_t, \, \text{clip}(r_t(\theta), 1 - \epsilon, 1 + \epsilon) \hat{A}_t \right) \right]$$

#### 4. Total Loss with Value and Entropy Regularization
$$\mathcal{L}^{\text{TOTAL}}(\theta) = \mathcal{L}^{\text{CLIP}}(\theta) + c_1 \frac{1}{2} \mathbb{E}_t \left[ (V_\theta(s_t) - R_t)^2 \right] - c_2 \mathbb{E}_t \left[ \mathcal{H}(\pi_\theta(\cdot | s_t)) \right]$$
where $c_1 = 0.5$, $c_2 = 0.02$, and $\epsilon = 0.2$.

---

## 4. Empirical Verification of Gradient Propagation

To prove conclusively that the historical single-bias freeze is eliminated, a numerical gradient audit was conducted on both architectures. Every parameter tensor across the network was inspected after a training step:

### A. Double-DQN Parameter Gradient & Update Verification
| Layer Tensor | Parameter Shape | Gradient Norm ($\|\nabla_\theta \mathcal{L}\|_2$) | Weight Displacement ($\max |\Delta W|$) | Status |
| :--- | :--- | :--- | :--- | :--- |
| `fc1.weight` (Trunk Layer 1) | `[64, 14]` | `0.828296` | `0.001000` | **UPDATED** |
| `fc1.bias` (Trunk Layer 1) | `[64]` | `0.252959` | `0.001000` | **UPDATED** |
| `fc2.weight` (Trunk Layer 2) | `[64, 64]` | `1.775299` | `0.001000` | **UPDATED** |
| `fc2.bias` (Trunk Layer 2) | `[64]` | `0.240872` | `0.001000` | **UPDATED** |
| `val_fc.weight` (Value Layer 1) | `[32, 64]` | `1.174644` | `0.001000` | **UPDATED** |
| `val_fc.bias` (Value Layer 1) | `[32]` | `0.149678` | `0.001000` | **UPDATED** |
| `val_out.weight` (Value Output) | `[1, 32]` | `0.895020` | `0.001000` | **UPDATED** |
| `val_out.bias` (Value Output) | `[1]` | `0.168141` | `0.001000` | **UPDATED** |
| `adv_fc.weight` (Advantage Layer 1) | `[32, 64]` | `1.188239` | `0.001000` | **UPDATED** |
| `adv_fc.bias` (Advantage Layer 1) | `[32]` | `0.184450` | `0.001000` | **UPDATED** |
| `adv_out.weight` (Advantage Output) | `[3, 32]` | `1.036244` | `0.001000` | **UPDATED** |
| `adv_out.bias` (Advantage Output) | `[3]` | `0.171812` | `0.001000` | **UPDATED** |

*Verification:* All 12 DQN parameter tensors receive non-zero gradients and evolve under Adam optimization.

### B. Actor-Critic PPO Parameter Gradient & Update Verification
| Layer Tensor | Parameter Shape | Gradient Norm ($\|\nabla_\theta \mathcal{L}\|_2$) | Weight Displacement ($\max |\Delta W|$) | Status |
| :--- | :--- | :--- | :--- | :--- |
| `fc1.weight` (Shared Trunk 1) | `[64, 14]` | `0.145430` | `0.007975` | **UPDATED** |
| `fc1.bias` (Shared Trunk 1) | `[64]` | `0.031783` | `0.007707` | **UPDATED** |
| `fc2.weight` (Shared Trunk 2) | `[64, 64]` | `0.301572` | `0.008032` | **UPDATED** |
| `fc2.bias` (Shared Trunk 2) | `[64]` | `0.033059` | `0.008013` | **UPDATED** |
| `actor_fc.weight` (Policy Stream 1) | `[32, 64]` | `0.169836` | `0.007884` | **UPDATED** |
| `actor_fc.bias` (Policy Stream 1) | `[32]` | `0.019058` | `0.007731` | **UPDATED** |
| `actor_out.weight` (Policy Output) | `[3, 32]` | `0.120865` | `0.007910` | **UPDATED** |
| `actor_out.bias` (Policy Output) | `[3]` | `0.018418` | `0.007789` | **UPDATED** |
| `critic_fc.weight` (Value Stream 1) | `[32, 64]` | `0.247482` | `0.008021` | **UPDATED** |
| `critic_fc.bias` (Value Stream 1) | `[32]` | `0.013700` | `0.007940` | **UPDATED** |
| `critic_out.weight` (Value Output) | `[1, 32]` | `0.173773` | `0.007994` | **UPDATED** |
| `critic_out.bias` (Value Output) | `[1]` | `0.003722` | `0.007563` | **UPDATED** |

*Verification:* All 12 PPO Actor-Critic parameter tensors receive non-zero gradients across both policy and value loss streams.

---

## 5. Controlled Multi-Episode Training Experiment on Silk Board Corridor

A controlled training experiment was executed on the live SUMO Silk Board corridor using `scripts/train_marl_agents.py`.
- **Corridor Topology:** J1 (Hosur North) $\leftrightarrow$ J2 (Central Silk Board) $\leftrightarrow$ J3 (Hosur South)
- **Episodes:** 5 episodes per algorithm, 60 simulation seconds per episode, 1.0s step length, 5.0s decision interval (12 decision steps/episode).
- **Seeds:** Base Seed 42 for DQN (seeds 52, 62, 72, 82, 92); Base Seed 43 for PPO (seeds 53, 63, 73, 83, 93).
- **Fuel Density:** Corrected $0.750\text{ kg/L}$ density ($750{,}000\text{ mg/L}$).

### A. Double-DQN Multi-Episode Training Trajectory
| Episode | Seed | Mean Reward | Mean TD Loss | Max Grad Norm | Epsilon ($\epsilon$) | Avg Queue | Cumulative Delay | Total Fuel (L) | Total $\text{CO}_2$ (kg) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | 52 | `-2.365` | `0.0000`* | `0.0000`* | `0.800` | `4.53` | `272.0 s` | `0.890 L` | `2.067 kg` |
| 2 | 62 | `-2.068` | `0.1190` | `0.5120` | `0.504` | `4.53` | `272.0 s` | `0.887 L` | `2.059 kg` |
| 3 | 72 | `-2.110` | `0.0785` | `0.7193` | `0.272` | `4.53` | `272.0 s` | `0.903 L` | `2.098 kg` |
| 4 | 82 | `-2.326` | `0.0451` | `0.4551` | `0.147` | `4.52` | `271.0 s` | `0.917 L` | `2.129 kg` |
| 5 | 92 | `-2.006` | `0.0291` | `0.3062` | `0.080` | `2.12` | `127.0 s` | `0.968 L` | `2.246 kg` |

*\* Episode 1 transitions populated the replay buffer; active gradient optimization began once buffer size reached the batch threshold ($\ge 16$).*

**DQN Observations:**
- **Smooth TD Loss Convergence:** Mean TD error monotonically decreased from `0.1190` in Episode 2 to `0.0291` in Episode 5.
- **Epsilon Decay:** Exploration decayed predictably from `0.800` to `0.080`, transitioning from stochastic exploration to learned greedy policies.
- **Queue and Delay Reduction:** In Episode 5, average queue dropped to `2.12` veh and cumulative delay decreased from $272\text{ s}$ to $127\text{ s}$.

### B. Actor-Critic PPO Multi-Episode Training Trajectory
| Episode | Seed | Mean Reward | Policy Loss | Value Loss | Entropy | Max Grad Norm | Avg Queue | Cumulative Delay | Total Fuel (L) | Total $\text{CO}_2$ (kg) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | 53 | `-2.542` | `0.0248` | `5.579` | `0.9711` | `0.2845` | `4.52` | `271.0 s` | `0.916 L` | `2.127 kg` |
| 2 | 63 | `-2.869` | `0.0209` | `5.695` | `0.9824` | `0.2745` | `4.53` | `272.0 s` | `0.908 L` | `2.109 kg` |
| 3 | 73 | `-2.157` | `0.0203` | `3.535` | `0.9843` | `0.2710` | `4.58` | `275.0 s` | `0.916 L` | `2.126 kg` |
| 4 | 83 | `-2.244` | `0.0160` | `3.734` | `0.9868` | `0.2813` | `4.53` | `272.0 s` | `0.914 L` | `2.123 kg` |
| 5 | 93 | `-2.519` | `0.0166` | `3.958` | `0.9802` | `0.2740` | `4.57` | `274.0 s` | `0.907 L` | `2.105 kg` |

**PPO Observations:**
- **Stable Policy Loss:** Policy loss remained bounded between `0.016` and `0.025`, confirming that the clipping ratio ($\epsilon=0.2$) effectively prevented destructive policy jumps.
- **Value Loss Reduction:** Value function MSE loss dropped from `5.579` to `3.958`, reflecting improved baseline estimation by the critic.
- **Entropy Regularization:** Policy entropy remained stable near `0.98` (for a 3-action space, maximum uniform entropy is $\ln(3) \approx 1.0986$), indicating healthy exploration without premature collapse.

---

## 6. Checkpoint Validation & Forward/Backward Compatibility

1. **Historical Checkpoints Preserved:**
   - `checkpoints/marl_dqn_corridor.json` (SHA intact, unmodified).
   - `checkpoints/marl_ppo_corridor.json` (SHA intact, unmodified).
   - Both load cleanly into `MARLCorridorController`, correctly falling back to version identifier `"1.0-historical"`.
2. **Newly Generated Checkpoints:**
   - `checkpoints/marl_dqn_corridor_v2.json` (version: `"2.0-autograd"`).
   - `checkpoints/marl_ppo_corridor_v2.json` (version: `"2.0-autograd"`).
   - `checkpoints/marl_training_validation_p4.json` (complete multi-episode trajectory metrics).
3. **Fresh Instantiation & Inference Validation:**
   - Fresh `MARLCorridorController` instances loaded both v2 checkpoints.
   - All three junctions (`J1`, `J2`, `J3`) loaded their respective weights and produced deterministic, valid actions (`EXTEND`, `SWITCH`, `KEEP`) without triggering fallbacks.
   - P3 simulation runtime dispatch successfully executed 10-second live SUMO stepping with both v2 checkpoints.

---

## 7. Scientific Performance Disclosures

In accordance with strict scientific integrity guidelines, the following distinctions are formally established:

| Category | Assessment | Empirical Evidence |
| :--- | :--- | :--- |
| **1. Algorithmic Correctness** | **PROVEN** | PyTorch autograd verified across all 12 parameters per network; Double-DQN target evaluation decoupled; PPO single-sample log-probs match actions; GAE-$\lambda$ advantage computed. |
| **2. Successful Training Execution** | **PROVEN** | 10 multi-episode simulation runs executed on SUMO; zero runtime crashes, NaNs, or process hangs; finite losses and bounded gradient norms throughout. |
| **3. Evidence of Learning** | **OBSERVED** | Double-DQN TD loss decreased from `0.1190` to `0.0291`; PPO critic value loss decreased from `5.579` to `3.958`; parameter displacements confirm non-trivial weight updates. |
| **4. Policy Convergence** | **NOT CLAIMED** | 5 episodes of 60 seconds is a controlled verification harness, not an asymptotic training regime. Convergence to an optimal stationary policy requires hundreds of episodes. |
| **5. Traffic-Control Performance** | **COORDINATED ADAPTIVE REMAINS SUPERIOR** | Fixed-rule Coordinated Adaptive control (incorporating upstream inflow bonuses and corridor green waves) outperforms untrained or lightly-trained MARL agents on Silk Board. |

---

## 8. Full Workspace Regression Suite Verification

To ensure zero regressions across the codebase, both backend and frontend test suites were executed:

### A. Backend PyTest Suite
```bash
pytest
```
- **Result:** **169 passed, 0 failed** in 77.95s.
- **Includes:**
  - `tests/test_marl_algorithm_correction.py` (10 passed)
  - `tests/test_marl_runtime_dispatch.py` (10 passed)
  - `tests/test_ai_controller.py` (17 passed)
  - `tests/test_benchmark_metrics.py` (9 passed)
  - All existing API, database, simulation service, and watchdog tests (123 passed).

### B. Frontend Vitest / Node Suite
```bash
npm test --prefix frontend
```
- **Result:** **75 passed, 0 failed** across 18 test suites in 767ms.
- **Includes:** WebSocket lifecycle, snapshot recovery, coordinate transformation, 3D ribbon mesh generation, and corridor scene construction.

---

## 9. Conclusion and Stage P4 Sign-off

Stage P4 has successfully transformed the historical, non-learning MARL code into a mathematically valid, fully autograd-driven deep reinforcement learning system. All trainable parameters receive real gradients, training trajectories are stable, versioned checkpoints are saved, and 100% backward/forward compatibility is maintained without altering any benchmark formulas or runtime safety rules.

**Stage P4 is COMPLETE and ready for Git commit on branch `marl-p4-rl-algorithm-recovery`.**
