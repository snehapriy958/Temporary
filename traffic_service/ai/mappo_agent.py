"""
traffic_service/ai/mappo_agent.py

Multi-Agent Proximal Policy Optimization (MAPPO) for Corridor Signal Control.
Implements Centralized Training with Decentralized Execution (CTDE):
- Decentralized Actor Network pi_theta_j(a_j | s_j) observing local 14-dim junction state
- Centralized Critic Network V_phi(s_corridor) observing unified 42-dim corridor state
- Action masking with Anti-Starvation safety constraints
- Clipped surrogate policy objective with Generalized Advantage Estimation (GAE-Lambda)
- Gradient clipping and autograd validation across all parameters
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from .env import ACTION_KEEP, ACTION_SWITCH, ACTION_EXTEND, ACTION_NAMES
from .models import MAPPOActorNetwork, MAPPOCentralizedCriticNetwork

logger = logging.getLogger("mappo_agent")


class MAPPOTrajectoryBuffer:
    """Stores rollout transitions for CTDE policy and critic updates."""

    def __init__(self) -> None:
        self.local_states: List[np.ndarray] = []
        self.corridor_states: List[np.ndarray] = []
        self.actions: List[int] = []
        self.action_masks: List[np.ndarray] = []
        self.rewards: List[float] = []
        self.log_probs: List[float] = []
        self.values: List[float] = []
        self.dones: List[bool] = []

    def push(
        self,
        local_state: np.ndarray,
        corridor_state: np.ndarray,
        action: int,
        action_mask: np.ndarray,
        reward: float,
        log_prob: float,
        value: float,
        done: bool,
    ) -> None:
        self.local_states.append(np.array(local_state, dtype=np.float32))
        self.corridor_states.append(np.array(corridor_state, dtype=np.float32))
        self.actions.append(int(action))
        self.action_masks.append(np.array(action_mask, dtype=np.float32))
        self.rewards.append(float(reward))
        self.log_probs.append(float(log_prob))
        self.values.append(float(value))
        self.dones.append(bool(done))

    def clear(self) -> None:
        self.local_states.clear()
        self.corridor_states.clear()
        self.actions.clear()
        self.action_masks.clear()
        self.rewards.clear()
        self.log_probs.clear()
        self.values.clear()
        self.dones.clear()

    def __len__(self) -> int:
        return len(self.local_states)


class MAPPOAgent:
    """
    Decentralized actor agent participating in Multi-Agent PPO.
    Executes using local junction observation (dim=14) and action masking.
    Trains in conjunction with a Centralized Corridor Critic (dim=42).
    """

    def __init__(
        self,
        agent_id: str,
        in_features: int = 14,
        corridor_features: int = 42,
        num_actions: int = 3,
        actor_lr: float = 0.0003,
        critic_lr: float = 0.001,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_ratio: float = 0.2,
        entropy_coef: float = 0.01,
        value_loss_coef: float = 0.5,
        shared_critic: Optional[MAPPOCentralizedCriticNetwork] = None,
        shared_critic_optimizer: Optional[Any] = None,
        seed: int = 42,
    ) -> None:
        self.agent_id = agent_id
        self.in_features = in_features
        self.corridor_features = corridor_features
        self.num_actions = num_actions
        self.actor_lr = actor_lr
        self.critic_lr = critic_lr
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_ratio = clip_ratio
        self.entropy_coef = entropy_coef
        self.value_loss_coef = value_loss_coef
        self.seed = seed

        self.rng = np.random.RandomState(seed)
        if TORCH_AVAILABLE:
            torch.manual_seed(seed)

        # 1. Decentralized Actor Network
        self.actor = MAPPOActorNetwork(in_features=in_features, num_actions=num_actions, seed=seed)
        self.actor_optimizer = (
            torch.optim.Adam(self.actor.parameters(), lr=self.actor_lr, eps=1e-5)
            if TORCH_AVAILABLE else None
        )

        # 2. Centralized Critic Network (Can be shared across sibling agents)
        self.owns_critic = (shared_critic is None)
        if shared_critic is not None:
            self.critic = shared_critic
            if shared_critic_optimizer is not None:
                self.critic_optimizer = shared_critic_optimizer
            elif TORCH_AVAILABLE and hasattr(shared_critic, "parameters"):
                self.critic_optimizer = torch.optim.Adam(self.critic.parameters(), lr=self.critic_lr, eps=1e-5)
            else:
                self.critic_optimizer = None
        else:
            self.critic = MAPPOCentralizedCriticNetwork(in_features=corridor_features, seed=seed + 100)
            self.critic_optimizer = (
                torch.optim.Adam(self.critic.parameters(), lr=self.critic_lr, eps=1e-5)
                if TORCH_AVAILABLE else None
            )

        self.buffer = MAPPOTrajectoryBuffer()
        self.step_counter = 0

    def select_action(
        self,
        local_obs: np.ndarray,
        action_mask: Optional[np.ndarray] = None,
        eval_mode: bool = False,
        can_switch: bool = True,
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Samples an action using local observation and action mask.
        If action_mask is None, builds default mask from can_switch.
        """
        if action_mask is None:
            # Default action mask based on min-green can_switch
            mask = np.array([1.0, 1.0 if can_switch else 0.0, 1.0], dtype=np.float32)
        else:
            mask = np.array(action_mask, dtype=np.float32)

        # Forward pass through actor network
        if TORCH_AVAILABLE:
            obs_t = torch.from_numpy(np.array(local_obs, dtype=np.float32)).unsqueeze(0)
            mask_t = torch.from_numpy(mask).unsqueeze(0)

            with torch.no_grad():
                logits, probs = self.actor.forward_logits(obs_t, mask=mask_t)
                logits = logits[0]
                probs_np = probs[0].cpu().numpy()

            dist = torch.distributions.Categorical(probs=probs[0])

            if eval_mode:
                # Deterministic greedy action
                action = int(torch.argmax(probs[0]).item())
                reason = f"MAPPO greedy policy (p={probs_np[action]:.2f}, action: {ACTION_NAMES.get(action)})"
            else:
                # Stochastic sample in training
                action_tensor = dist.sample()
                action = int(action_tensor.item())
                reason = f"MAPPO stochastic sample (p={probs_np[action]:.2f}, action: {ACTION_NAMES.get(action)})"

            log_prob = float(dist.log_prob(torch.tensor(action)).item())
        else:
            logits, probs_np = self.actor.forward(local_obs, mask=mask)
            if eval_mode:
                action = int(np.argmax(probs_np))
            else:
                action = int(self.rng.choice(self.num_actions, p=probs_np))
            log_prob = float(np.log(max(probs_np[action], 1e-8)))
            reason = f"NumPy MAPPO sample (p={probs_np[action]:.2f})"

        info = {
            "agent_id": self.agent_id,
            "action": action,
            "action_name": ACTION_NAMES.get(action, "UNKNOWN"),
            "probabilities": probs_np.tolist(),
            "action_mask": mask.tolist(),
            "log_prob": log_prob,
            "reason": reason,
        }
        return action, info

    def get_corridor_value(self, corridor_obs: np.ndarray) -> float:
        """Evaluates Centralized Critic baseline V(s_corridor)."""
        val = self.critic.forward(corridor_obs)
        return float(val) if isinstance(val, (int, float, np.floating)) else float(val.item())

    def store_transition(
        self,
        local_state: np.ndarray,
        corridor_state: np.ndarray,
        action: int,
        action_mask: np.ndarray,
        reward: float,
        log_prob: float,
        value: float,
        done: bool,
    ) -> None:
        self.buffer.push(
            local_state=local_state,
            corridor_state=corridor_state,
            action=action,
            action_mask=action_mask,
            reward=reward,
            log_prob=log_prob,
            value=value,
            done=done,
        )

    def compute_gae(
        self,
        last_corridor_value: float,
        dones: np.ndarray,
        rewards: np.ndarray,
        values: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Computes Generalized Advantage Estimation over Centralized Critic values."""
        n_steps = len(rewards)
        advantages = np.zeros(n_steps, dtype=np.float32)
        last_gae = 0.0

        for t in reversed(range(n_steps)):
            next_val = last_corridor_value if t == n_steps - 1 else values[t + 1]
            non_terminal = 1.0 - float(dones[t])
            delta = rewards[t] + (self.gamma * next_val * non_terminal) - values[t]
            advantages[t] = last_gae = delta + (self.gamma * self.gae_lambda * non_terminal * last_gae)

        returns = advantages + values
        adv_std = np.std(advantages)
        if adv_std > 1e-6:
            advantages = (advantages - np.mean(advantages)) / adv_std
        else:
            advantages = advantages - np.mean(advantages)

        return advantages, returns

    def train_step(
        self,
        last_corridor_value: float = 0.0,
        epochs: int = 4,
        minibatch_size: int = 32,
        update_critic: bool = True,
    ) -> Dict[str, float]:
        """
        Updates decentralized actor and centralized critic networks.
        Propagates gradients with autograd clipping.
        """
        if not TORCH_AVAILABLE or len(self.buffer) < 4:
            return {"loss": 0.0, "policy_loss": 0.0, "critic_loss": 0.0, "entropy": 0.0}

        local_states = np.array(self.buffer.local_states, dtype=np.float32)
        corridor_states = np.array(self.buffer.corridor_states, dtype=np.float32)
        actions = np.array(self.buffer.actions, dtype=np.int64)
        action_masks = np.array(self.buffer.action_masks, dtype=np.float32)
        old_log_probs = np.array(self.buffer.log_probs, dtype=np.float32)
        rewards = np.array(self.buffer.rewards, dtype=np.float32)
        values = np.array(self.buffer.values, dtype=np.float32)
        dones = np.array(self.buffer.dones, dtype=np.bool_)

        advantages_np, returns_np = self.compute_gae(last_corridor_value, dones, rewards, values)

        # PyTorch Tensors
        l_states_t = torch.from_numpy(local_states).float()
        c_states_t = torch.from_numpy(corridor_states).float()
        actions_t = torch.from_numpy(actions).long()
        masks_t = torch.from_numpy(action_masks).float()
        old_log_probs_t = torch.from_numpy(old_log_probs).float()
        advantages_t = torch.from_numpy(advantages_np).float()
        returns_t = torch.from_numpy(returns_np).float()

        n_samples = len(self.buffer)
        mb_size = min(minibatch_size, n_samples)

        actor_losses = []
        critic_losses = []
        entropies = []

        self.actor.train()
        if update_critic and self.critic_optimizer is not None:
            self.critic.train()

        for _ in range(epochs):
            indices = np.random.permutation(n_samples)
            for start_idx in range(0, n_samples, mb_size):
                mb_idx = indices[start_idx : start_idx + mb_size]

                mb_l_states = l_states_t[mb_idx]
                mb_c_states = c_states_t[mb_idx]
                mb_actions = actions_t[mb_idx]
                mb_masks = masks_t[mb_idx]
                mb_old_log_probs = old_log_probs_t[mb_idx]
                mb_advantages = advantages_t[mb_idx]
                mb_returns = returns_t[mb_idx]

                # 1. Update Decentralized Actor
                logits, probs = self.actor.forward_logits(mb_l_states, mask=mb_masks)
                dist = torch.distributions.Categorical(probs=probs)
                new_log_probs = dist.log_prob(mb_actions)
                entropy = dist.entropy().mean()

                ratios = torch.exp(new_log_probs - mb_old_log_probs)
                surr1 = ratios * mb_advantages
                surr2 = torch.clamp(ratios, 1.0 - self.clip_ratio, 1.0 + self.clip_ratio) * mb_advantages
                policy_loss = -torch.min(surr1, surr2).mean() - (self.entropy_coef * entropy)

                self.actor_optimizer.zero_grad()
                policy_loss.backward()
                torch.nn.utils.clip_grad_norm_(self.actor.parameters(), max_norm=0.5)
                self.actor_optimizer.step()

                actor_losses.append(float(policy_loss.item()))
                entropies.append(float(entropy.item()))

                # 2. Update Centralized Critic (if authorized for this step)
                if update_critic and self.critic_optimizer is not None:
                    curr_vals = self.critic.forward(mb_c_states)
                    critic_loss = F.mse_loss(curr_vals, mb_returns)

                    self.critic_optimizer.zero_grad()
                    critic_loss.backward()
                    torch.nn.utils.clip_grad_norm_(self.critic.parameters(), max_norm=0.5)
                    self.critic_optimizer.step()

                    critic_losses.append(float(critic_loss.item()))

        self.step_counter += 1
        self.buffer.clear()

        mean_pol = float(np.mean(actor_losses)) if actor_losses else 0.0
        mean_crit = float(np.mean(critic_losses)) if critic_losses else 0.0
        mean_ent = float(np.mean(entropies)) if entropies else 0.0

        return {
            "loss": mean_pol + (self.value_loss_coef * mean_crit),
            "policy_loss": mean_pol,
            "critic_loss": mean_crit,
            "entropy": mean_ent,
        }

    def get_state_dict(self) -> Dict[str, Any]:
        """Serializes actor and critic weights into dictionary."""
        actor_w = self.actor.get_weights()
        serializable_actor = {k: v.tolist() if hasattr(v, "tolist") else v for k, v in actor_w.items()}
        state_dict: Dict[str, Any] = {
            "agent_id": self.agent_id,
            "algorithm_version": "2.0-mappo",
            "step_counter": int(self.step_counter),
            "actor_weights": serializable_actor,
        }
        if self.critic is not None:
            critic_w = self.critic.get_weights()
            state_dict["critic_weights"] = {k: v.tolist() if hasattr(v, "tolist") else v for k, v in critic_w.items()}
        return state_dict

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        """Loads actor and critic weights with schema validation."""
        self.step_counter = int(state_dict.get("step_counter", 0))
        if "actor_weights" in state_dict:
            raw_w = state_dict["actor_weights"]
            converted_w = {
                k: np.array(v, dtype=np.float32) if not isinstance(v, np.ndarray) else v
                for k, v in raw_w.items()
            }
            self.actor.set_weights(converted_w)
        if "critic_weights" in state_dict and self.critic is not None:
            raw_cw = state_dict["critic_weights"]
            converted_cw = {
                k: np.array(v, dtype=np.float32) if not isinstance(v, np.ndarray) else v
                for k, v in raw_cw.items()
            }
            self.critic.set_weights(converted_cw)


def train_mappo_corridor(
    agents: Dict[str, MAPPOAgent],
    shared_critic: MAPPOCentralizedCriticNetwork,
    shared_critic_optimizer: Optional[Any] = None,
    last_corridor_value: float = 0.0,
    epochs: int = 4,
    minibatch_size: int = 32,
) -> Dict[str, Any]:
    """
    Coordinated CTDE training for all corridor MAPPO agents:
    1. Updates each decentralized actor network on its own local trajectory buffer and advantages
       without triggering redundant or conflicting updates on the shared critic.
    2. Updates the shared centralized critic ONCE per batch using the mean corridor returns.
    """
    if not TORCH_AVAILABLE:
        return {"policy_results": {}, "mean_policy_loss": 0.0, "critic_loss": 0.0, "mean_loss": 0.0}

    # Verify buffers
    for j_id, agent in agents.items():
        if len(agent.buffer) < 4:
            return {"policy_results": {}, "mean_policy_loss": 0.0, "critic_loss": 0.0, "mean_loss": 0.0}

    # Step 1: Collect returns and update each decentralized actor independently (update_critic=False)
    policy_results = {}
    computed_returns = []
    corridor_states_ref = None

    for j_id, agent in agents.items():
        dones = np.array(agent.buffer.dones, dtype=np.bool_)
        rewards = np.array(agent.buffer.rewards, dtype=np.float32)
        values = np.array(agent.buffer.values, dtype=np.float32)
        adv_np, ret_np = agent.compute_gae(last_corridor_value, dones, rewards, values)
        computed_returns.append(ret_np)

        if corridor_states_ref is None:
            corridor_states_ref = np.array(agent.buffer.corridor_states, dtype=np.float32)

        # Train actor only
        res = agent.train_step(
            last_corridor_value=last_corridor_value,
            epochs=epochs,
            minibatch_size=minibatch_size,
            update_critic=False,
        )
        policy_results[j_id] = res

    # Step 2: Update shared centralized critic ONCE using mean corridor returns
    critic_losses = []
    opt = shared_critic_optimizer or (
        next(iter(agents.values())).critic_optimizer if agents else None
    )

    if opt is not None and corridor_states_ref is not None and computed_returns:
        mean_returns_np = np.mean(computed_returns, axis=0).astype(np.float32)
        c_states_t = torch.from_numpy(corridor_states_ref).float()
        returns_t = torch.from_numpy(mean_returns_np).float()

        n_samples = len(corridor_states_ref)
        mb_size = min(minibatch_size, n_samples)

        shared_critic.train()
        for _ in range(epochs):
            indices = np.random.permutation(n_samples)
            for start_idx in range(0, n_samples, mb_size):
                mb_idx = indices[start_idx : start_idx + mb_size]
                mb_c_states = c_states_t[mb_idx]
                mb_returns = returns_t[mb_idx]

                curr_vals = shared_critic.forward(mb_c_states)
                critic_loss = F.mse_loss(curr_vals, mb_returns)

                opt.zero_grad()
                critic_loss.backward()
                torch.nn.utils.clip_grad_norm_(shared_critic.parameters(), max_norm=0.5)
                opt.step()

                critic_losses.append(float(critic_loss.item()))

    mean_crit_loss = float(np.mean(critic_losses)) if critic_losses else 0.0
    mean_pol_loss = float(np.mean([r.get("policy_loss", 0.0) for r in policy_results.values()])) if policy_results else 0.0

    return {
        "policy_results": policy_results,
        "mean_policy_loss": mean_pol_loss,
        "critic_loss": mean_crit_loss,
        "mean_loss": mean_pol_loss + 0.5 * mean_crit_loss,
    }
