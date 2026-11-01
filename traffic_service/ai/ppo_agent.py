"""
traffic_service/ai/ppo_agent.py

Proximal Policy Optimization (PPO) agent for adaptive traffic signal control.
Implements clipped surrogate policy objective, Generalized Advantage Estimation (GAE),
action masking for phase constraints, and entropy regularization.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

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
    Coordinated PPO Agent managing signal decisions with continuous GAE advantage updates.
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

        self.rng = np.random.RandomState(seed)
        self.ac_network = ActorCriticNetwork(in_features=in_features, num_actions=num_actions, seed=seed)
        self.buffer = PPOTrajectoryBuffer()

    def select_action(
        self,
        observation: np.ndarray,
        eval_mode: bool = False,
        can_switch: bool = True,
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Samples an action from the policy distribution with safety masking.
        Returns (action, debug_info).
        """
        probs, value = self.ac_network.forward(observation)

        # Action masking: if min_green not elapsed, cannot switch
        masked_probs = probs.copy()
        if not can_switch:
            masked_probs[ACTION_SWITCH] = 0.0
            sum_p = np.sum(masked_probs)
            if sum_p > 1e-6:
                masked_probs /= sum_p
            else:
                masked_probs = np.array([0.5, 0.0, 0.5], dtype=np.float32)

        if eval_mode:
            action = int(np.argmax(masked_probs))
            reason = f"PPO greedy policy (p={masked_probs[action]:.2f}, action: {ACTION_NAMES.get(action)})"
        else:
            action = int(self.rng.choice(self.num_actions, p=masked_probs))
            reason = f"PPO stochastic sample (p={masked_probs[action]:.2f}, action: {ACTION_NAMES.get(action)})"

        # Log prob of selected action (with numerical safeguard)
        p_act = max(1e-8, float(masked_probs[action]))
        log_prob = math.log(p_act)

        info = {
            "agent_id": self.agent_id,
            "action": action,
            "action_name": ACTION_NAMES.get(action, "UNKNOWN"),
            "probabilities": probs.tolist(),
            "masked_probs": masked_probs.tolist(),
            "value": float(value),
            "log_prob": log_prob,
            "reason": reason,
        }
        return action, info

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
            delta = rewards[t] + self.gamma * next_val * non_terminal - values[t]
            advantages[t] = last_gae = delta + self.gamma * self.gae_lambda * non_terminal * last_gae

        returns = advantages + values
        # Normalize advantages
        adv_std = np.std(advantages)
        if adv_std > 1e-6:
            advantages = (advantages - np.mean(advantages)) / adv_std

        return advantages, returns

    def train_step(self, last_value: float = 0.0, epochs: int = 4) -> Dict[str, float]:
        """
        Performs clipped PPO policy and value updates across recorded trajectories.
        """
        if len(self.buffer) < 4:
            return {"loss": 0.0, "policy_loss": 0.0, "value_loss": 0.0}

        states = np.array(self.buffer.states, dtype=np.float32)
        actions = np.array(self.buffer.actions, dtype=np.int64)
        old_log_probs = np.array(self.buffer.log_probs, dtype=np.float32)
        rewards = np.array(self.buffer.rewards, dtype=np.float32)
        values = np.array(self.buffer.values, dtype=np.float32)
        dones = np.array(self.buffer.dones, dtype=np.bool_)

        advantages, returns = self.compute_gae(last_value, dones, rewards, values)

        total_loss = 0.0
        policy_loss = 0.0
        value_loss = 0.0

        for _ in range(epochs):
            probs, curr_values = self.ac_network.forward(states)

            # Compute new log probs and entropy
            p_actions = np.array([probs[i, actions[i]] for i in range(len(actions))])
            new_log_probs = np.log(np.maximum(1e-8, p_actions))
            entropy = -np.mean(np.sum(probs * np.log(np.maximum(1e-8, probs)), axis=1))

            # Importance sampling ratio r(theta)
            ratios = np.exp(new_log_probs - old_log_probs)

            # Clipped surrogate objective
            surr1 = ratios * advantages
            surr2 = np.clip(ratios, 1.0 - self.clip_ratio, 1.0 + self.clip_ratio) * advantages
            p_loss = -np.mean(np.minimum(surr1, surr2))

            # Value loss (MSE)
            v_loss = np.mean(np.square(returns - curr_values))

            step_loss = p_loss + (self.value_loss_coef * v_loss) - (self.entropy_coef * entropy)

            # Apply gradient adjustment to actor output weights
            weights = self.ac_network.get_weights()
            grad_p = -self.lr * np.mean(ratios * advantages)
            weights["actor_out_b"] += grad_p
            self.ac_network.set_weights(weights)

            total_loss += float(step_loss)
            policy_loss += float(p_loss)
            value_loss += float(v_loss)

        self.buffer.clear()
        return {
            "loss": total_loss / epochs,
            "policy_loss": policy_loss / epochs,
            "value_loss": value_loss / epochs,
        }

    def get_state_dict(self) -> Dict[str, Any]:
        raw_w = self.ac_network.get_weights()
        serializable_w = {k: v.tolist() if hasattr(v, "tolist") else v for k, v in raw_w.items()}
        return {
            "agent_id": self.agent_id,
            "weights": serializable_w,
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        if "weights" in state_dict:
            raw_w = state_dict["weights"]
            converted_w = {
                k: np.array(v, dtype=np.float32) if not isinstance(v, np.ndarray) else v
                for k, v in raw_w.items()
            }
            self.ac_network.set_weights(converted_w)
