"""
traffic_service/ai/ppo_agent.py

Proximal Policy Optimization (PPO) agent for adaptive traffic signal control.
Implements:
- Clipped surrogate policy objective
- Generalized Advantage Estimation (GAE-Lambda)
- Single-sample consistent action and log-probability selection
- Full autograd backpropagation across actor, critic, and shared trunk parameters
- Minibatch optimization across multiple update epochs
- Numerical safeguards against NaN and gradient explosion
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .env import ACTION_KEEP, ACTION_SWITCH, ACTION_EXTEND, ACTION_NAMES
from .models import ActorCriticNetwork


class PPOTrajectoryBuffer:
    """Stores rollout transitions for batch policy optimization."""

    def __init__(self) -> None:
        self.states: List[np.ndarray] = []
        self.actions: List[int] = []
        self.rewards: List[float] = []
        self.log_probs: List[float] = []
        self.values: List[float] = []
        self.dones: List[bool] = []

    def push(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        log_prob: float,
        value: float,
        done: bool,
    ) -> None:
        self.states.append(np.array(state, dtype=np.float32))
        self.actions.append(int(action))
        self.rewards.append(float(reward))
        self.log_probs.append(float(log_prob))
        self.values.append(float(value))
        self.dones.append(bool(done))

    def clear(self) -> None:
        self.states.clear()
        self.actions.clear()
        self.rewards.clear()
        self.log_probs.clear()
        self.values.clear()
        self.dones.clear()

    def __len__(self) -> int:
        return len(self.states)


class PPOAgent:
    """
    Coordinated PPO Agent managing signal decisions with autograd-enabled Actor-Critic optimization.
    """

    def __init__(
        self,
        agent_id: str,
        in_features: int = 14,
        num_actions: int = 3,
        learning_rate: float = 0.0003,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_ratio: float = 0.2,
        entropy_coef: float = 0.01,
        value_loss_coef: float = 0.5,
        seed: int = 42,
    ) -> None:
        self.agent_id = agent_id
        self.in_features = in_features
        self.num_actions = num_actions
        self.lr = learning_rate
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_ratio = clip_ratio
        self.entropy_coef = entropy_coef
        self.value_loss_coef = value_loss_coef
        self.seed = seed

        self.rng = np.random.RandomState(seed)
        torch.manual_seed(seed)

        self.ac_network = ActorCriticNetwork(in_features=in_features, num_actions=num_actions, seed=seed)
        self.optimizer = torch.optim.Adam(self.ac_network.parameters(), lr=self.lr, eps=1e-5)
        self.buffer = PPOTrajectoryBuffer()
        self.step_counter = 0

    def select_action(
        self,
        observation: np.ndarray,
        eval_mode: bool = False,
        can_switch: bool = True,
        action_mask: Optional[np.ndarray] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Samples an action from the policy distribution with safety masking.
        CRITICAL: The exact action executed is the exact action whose log_prob is returned.
        No second sampling occurs.
        """
        obs_t = torch.from_numpy(np.array(observation, dtype=np.float32)).unsqueeze(0)

        with torch.no_grad():
            logits, val_t = self.ac_network.forward_logits_value(obs_t)
            logits = logits[0]
            value = float(val_t[0].item())

        # Masking
        masked_logits = logits.clone()
        if action_mask is not None:
            for a_idx in range(self.num_actions):
                if action_mask[a_idx] <= 0.0:
                    masked_logits[a_idx] = -1e9
        elif not can_switch:
            masked_logits[ACTION_SWITCH] = -1e9

        dist = torch.distributions.Categorical(logits=masked_logits)
        probs = F.softmax(masked_logits, dim=-1).cpu().numpy()

        if eval_mode:
            # Deterministic greedy choice in evaluation
            action = int(torch.argmax(masked_logits).item())
            reason = f"PPO greedy policy (p={probs[action]:.2f}, action: {ACTION_NAMES.get(action)})"
        else:
            # Stochastic sample in training
            action_tensor = dist.sample()
            action = int(action_tensor.item())
            reason = f"PPO stochastic sample (p={probs[action]:.2f}, action: {ACTION_NAMES.get(action)})"

        # Exact log probability of the sampled action under the masked categorical distribution
        log_prob = float(dist.log_prob(torch.tensor(action)).item())

        info = {
            "agent_id": self.agent_id,
            "action": action,
            "action_name": ACTION_NAMES.get(action, "UNKNOWN"),
            "probabilities": probs.tolist(),
            "masked_probs": probs.tolist(),
            "value": value,
            "log_prob": log_prob,
            "reason": reason,
        }
        return action, info

    def get_value(self, observation: np.ndarray) -> float:
        """Returns scalar state value estimate for bootstrapping."""
        obs_t = torch.from_numpy(np.array(observation, dtype=np.float32)).unsqueeze(0)
        with torch.no_grad():
            _, val_t = self.ac_network.forward_logits_value(obs_t)
            return float(val_t[0].item())

    def store_transition(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        log_prob: float,
        value: float,
        done: bool,
    ) -> None:
        self.buffer.push(state, action, reward, log_prob, value, done)

    def compute_gae(
        self,
        last_value: float,
        dones: np.ndarray,
        rewards: np.ndarray,
        values: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Computes Generalized Advantage Estimation (GAE-Lambda) and returns.
        """
        n_steps = len(rewards)
        advantages = np.zeros(n_steps, dtype=np.float32)
        last_gae = 0.0

        for t in reversed(range(n_steps)):
            next_val = last_value if t == n_steps - 1 else values[t + 1]
            non_terminal = 1.0 - float(dones[t])
            delta = rewards[t] + (self.gamma * next_val * non_terminal) - values[t]
            advantages[t] = last_gae = delta + (self.gamma * self.gae_lambda * non_terminal * last_gae)

        returns = advantages + values
        # Normalize advantages for training stability
        adv_std = np.std(advantages)
        if adv_std > 1e-6:
            advantages = (advantages - np.mean(advantages)) / adv_std
        else:
            advantages = advantages - np.mean(advantages)

        return advantages, returns

    def train_step(
        self,
        last_value: float = 0.0,
        epochs: int = 4,
        minibatch_size: int = 32,
    ) -> Dict[str, float]:
        """
        Performs clipped PPO policy and value updates across recorded trajectories using autograd.
        Propagates gradients through ALL trainable parameters of actor, critic, and shared trunk.
        """
        if len(self.buffer) < 4:
            return {"loss": 0.0, "policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0}

        states = np.array(self.buffer.states, dtype=np.float32)
        actions = np.array(self.buffer.actions, dtype=np.int64)
        old_log_probs = np.array(self.buffer.log_probs, dtype=np.float32)
        rewards = np.array(self.buffer.rewards, dtype=np.float32)
        values = np.array(self.buffer.values, dtype=np.float32)
        dones = np.array(self.buffer.dones, dtype=np.bool_)

        advantages_np, returns_np = self.compute_gae(last_value, dones, rewards, values)

        # Convert to PyTorch tensors
        states_t = torch.from_numpy(states).float()
        actions_t = torch.from_numpy(actions).long()
        old_log_probs_t = torch.from_numpy(old_log_probs).float()
        advantages_t = torch.from_numpy(advantages_np).float()
        returns_t = torch.from_numpy(returns_np).float()

        n_samples = len(self.buffer)
        mb_size = min(minibatch_size, n_samples)

        epoch_total_losses = []
        epoch_policy_losses = []
        epoch_value_losses = []
        epoch_entropies = []

        self.ac_network.train()

        for _ in range(epochs):
            indices = np.random.permutation(n_samples)
            for start_idx in range(0, n_samples, mb_size):
                mb_indices = indices[start_idx : start_idx + mb_size]

                mb_states = states_t[mb_indices]
                mb_actions = actions_t[mb_indices]
                mb_old_log_probs = old_log_probs_t[mb_indices]
                mb_advantages = advantages_t[mb_indices]
                mb_returns = returns_t[mb_indices]

                # Forward pass through Actor-Critic network
                logits, curr_values = self.ac_network.forward_logits_value(mb_states)
                dist = torch.distributions.Categorical(logits=logits)
                new_log_probs = dist.log_prob(mb_actions)
                entropy = dist.entropy().mean()

                # Importance sampling probability ratio: r(theta) = exp(new_log_prob - old_log_prob)
                ratios = torch.exp(new_log_probs - mb_old_log_probs)

                # Clipped surrogate loss
                surr1 = ratios * mb_advantages
                surr2 = torch.clamp(ratios, 1.0 - self.clip_ratio, 1.0 + self.clip_ratio) * mb_advantages
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value function loss (MSE)
                value_loss = F.mse_loss(curr_values, mb_returns)

                # Total multi-objective loss
                total_loss = policy_loss + (self.value_loss_coef * value_loss) - (self.entropy_coef * entropy)

                # Backpropagation through ALL trainable parameters
                self.optimizer.zero_grad()
                total_loss.backward()
                torch.nn.utils.clip_grad_norm_(self.ac_network.parameters(), max_norm=0.5)
                self.optimizer.step()

                epoch_total_losses.append(float(total_loss.item()))
                epoch_policy_losses.append(float(policy_loss.item()))
                epoch_value_losses.append(float(value_loss.item()))
                epoch_entropies.append(float(entropy.item()))

        self.step_counter += 1
        self.buffer.clear()

        return {
            "loss": float(np.mean(epoch_total_losses)) if epoch_total_losses else 0.0,
            "policy_loss": float(np.mean(epoch_policy_losses)) if epoch_policy_losses else 0.0,
            "value_loss": float(np.mean(epoch_value_losses)) if epoch_value_losses else 0.0,
            "entropy": float(np.mean(epoch_entropies)) if epoch_entropies else 0.0,
        }

    def get_state_dict(self) -> Dict[str, Any]:
        """Exports state dict with weights and metadata."""
        raw_w = self.ac_network.get_weights()
        serializable_w = {k: v.tolist() if hasattr(v, "tolist") else v for k, v in raw_w.items()}
        return {
            "agent_id": self.agent_id,
            "algorithm_version": "2.0-autograd",
            "step_counter": int(self.step_counter),
            "weights": serializable_w,
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        """Loads state dict with full backward compatibility."""
        self.step_counter = int(state_dict.get("step_counter", 0))
        if "weights" in state_dict:
            raw_w = state_dict["weights"]
            converted_w = {
                k: np.array(v, dtype=np.float32) if not isinstance(v, np.ndarray) else v
                for k, v in raw_w.items()
            }
            self.ac_network.set_weights(converted_w)
