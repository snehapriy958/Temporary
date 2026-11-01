"""
traffic_service/ai/dqn_agent.py

Double Deep Q-Network (Double-DQN) agent with Dueling architecture,
Experience Replay Buffer, full autograd backpropagation, Huber loss,
and target network synchronization.
"""

from __future__ import annotations

from collections import deque
import random
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .env import ACTION_KEEP, ACTION_SWITCH, ACTION_EXTEND, ACTION_NAMES
from .models import DuelingDQNNetwork


class ReplayBuffer:
    """Cyclic transition storage for off-policy reinforcement learning."""

    def __init__(self, capacity: int = 10000) -> None:
        self.buffer: deque = deque(maxlen=capacity)

    def push(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        self.buffer.append((
            np.array(state, dtype=np.float32),
            int(action),
            float(reward),
            np.array(next_state, dtype=np.float32),
            bool(done),
        ))

    def sample(self, batch_size: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            np.array(states, dtype=np.float32),
            np.array(actions, dtype=np.int64),
            np.array(rewards, dtype=np.float32),
            np.array(next_states, dtype=np.float32),
            np.array(dones, dtype=np.bool_),
        )

    def __len__(self) -> int:
        return len(self.buffer)


class DQNAgent:
    """
    Coordinated Double-DQN Agent for traffic light control with full autograd backpropagation.
    """

    def __init__(
        self,
        agent_id: str,
        in_features: int = 14,
        num_actions: int = 3,
        learning_rate: float = 0.001,
        gamma: float = 0.95,
        epsilon: float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.995,
        target_update_interval: int = 50,
        buffer_capacity: int = 10000,
        seed: int = 42,
    ) -> None:
        self.agent_id = agent_id
        self.in_features = in_features
        self.num_actions = num_actions
        self.lr = learning_rate
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.target_update_interval = target_update_interval
        self.seed = seed

        self.rng = np.random.RandomState(seed)
        torch.manual_seed(seed)

        # Primary and Target Dueling Q-networks
        self.q_network = DuelingDQNNetwork(in_features=in_features, num_actions=num_actions, seed=seed)
        self.target_network = DuelingDQNNetwork(in_features=in_features, num_actions=num_actions, seed=seed + 100)
        self.update_target_network()

        # PyTorch Optimizer & Loss function
        self.optimizer = torch.optim.Adam(self.q_network.parameters(), lr=self.lr)
        self.loss_fn = nn.SmoothL1Loss()  # Huber loss for robust TD errors

        self.replay_buffer = ReplayBuffer(capacity=buffer_capacity)
        self.step_counter = 0

    def update_target_network(self) -> None:
        """Copies primary network weights to the target network."""
        self.target_network.set_weights(self.q_network.get_weights())

    def select_action(
        self,
        observation: np.ndarray,
        eval_mode: bool = False,
        can_switch: bool = True,
        action_mask: Optional[np.ndarray] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Selects action using epsilon-greedy policy with safety action masking.
        If action_mask is provided, invalid actions (mask <= 0) are set to -1e9.
        Otherwise if can_switch is False (e.g. min_green not elapsed), ACTION_SWITCH is masked out.
        Returns (action, debug_info).
        """
        q_values = self.q_network.forward(observation)

        # Action masking
        masked_q = q_values.copy()
        if action_mask is not None:
            for a_idx in range(self.num_actions):
                if action_mask[a_idx] <= 0.0:
                    masked_q[a_idx] = -1e9
        elif not can_switch:
            masked_q[ACTION_SWITCH] = -1e9

        valid_actions = [a for a in range(self.num_actions) if masked_q[a] > -1e8]
        if not valid_actions:
            valid_actions = [ACTION_KEEP]

        if not eval_mode and (self.rng.rand() < self.epsilon):
            # Exploration
            action = int(self.rng.choice(valid_actions))
            reason = f"DQN epsilon-greedy exploration (eps={self.epsilon:.2f})"
        else:
            # Exploitation
            action = int(np.argmax(masked_q))
            reason = f"DQN exploitation (Q-value: {masked_q[action]:.2f}, best action: {ACTION_NAMES.get(action)})"

        info = {
            "agent_id": self.agent_id,
            "action": action,
            "action_name": ACTION_NAMES.get(action, "UNKNOWN"),
            "q_values": q_values.tolist(),
            "masked_q": masked_q.tolist(),
            "epsilon": float(self.epsilon),
            "reason": reason,
        }
        return action, info

    def store_transition(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        """Appends step transition to experience replay buffer."""
        self.replay_buffer.push(state, action, reward, next_state, done)

    def train_step(self, batch_size: int = 32) -> Optional[float]:
        """
        Executes one Double-DQN training step using autograd and mini-batch from buffer.
        Double-DQN target: y = r + gamma * (1 - done) * Q_target(s', argmax_a Q(s', a))
        Propagates gradients through ALL trainable parameters of the primary Q-network.
        """
        if len(self.replay_buffer) < batch_size:
            return None

        states, actions, rewards, next_states, dones = self.replay_buffer.sample(batch_size)

        s_t = torch.from_numpy(states).float()
        a_t = torch.from_numpy(actions).long()
        r_t = torch.from_numpy(rewards).float()
        ns_t = torch.from_numpy(next_states).float()
        d_t = torch.from_numpy(dones.astype(np.float32)).float()

        # 1. Current Q-values for actions taken
        self.q_network.train()
        q_pred = self.q_network.forward(s_t)  # shape (batch, num_actions)
        state_action_values = q_pred.gather(1, a_t.unsqueeze(1)).squeeze(1)  # shape (batch,)

        # 2. Double-DQN Target Calculation (detached from computation graph)
        with torch.no_grad():
            # Online network selects best action
            next_q_online = self.q_network.forward(ns_t)
            best_next_actions = next_q_online.argmax(dim=1, keepdim=True)
            # Target network evaluates selected action
            next_q_target = self.target_network.forward(ns_t)
            next_state_values = next_q_target.gather(1, best_next_actions).squeeze(1)
            # Bellman target (terminal state -> non_terminal = 0.0)
            expected_state_action_values = r_t + (self.gamma * (1.0 - d_t) * next_state_values)

        # 3. Loss & Backpropagation across ALL trainable parameters
        loss = self.loss_fn(state_action_values, expected_state_action_values)

        self.optimizer.zero_grad()
        loss.backward()
        # Gradient clipping for numerical stability
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), max_norm=10.0)
        self.optimizer.step()

        # 4. Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        # 5. Periodic target network synchronization
        self.step_counter += 1
        if self.step_counter % self.target_update_interval == 0:
            self.update_target_network()

        return float(loss.item())

    def get_state_dict(self) -> Dict[str, Any]:
        """Exports state dict with weights and metadata."""
        raw_w = self.q_network.get_weights()
        serializable_w = {k: v.tolist() if hasattr(v, "tolist") else v for k, v in raw_w.items()}
        return {
            "agent_id": self.agent_id,
            "algorithm_version": "2.0-autograd",
            "epsilon": float(self.epsilon),
            "step_counter": int(self.step_counter),
            "q_network_weights": serializable_w,
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        """Loads state dict with full backward compatibility."""
        self.epsilon = float(state_dict.get("epsilon", self.epsilon_min))
        self.step_counter = int(state_dict.get("step_counter", 0))
        if "q_network_weights" in state_dict:
            raw_w = state_dict["q_network_weights"]
            converted_w = {
                k: np.array(v, dtype=np.float32) if not isinstance(v, np.ndarray) else v
                for k, v in raw_w.items()
            }
            self.q_network.set_weights(converted_w)
            self.update_target_network()
