"""
traffic_service/ai/dqn_agent.py

Double Deep Q-Network (Double-DQN) agent with Dueling architecture,
Experience Replay Buffer, and target network synchronization.
"""

from __future__ import annotations

from collections import deque
import random
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

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
    Coordinated Double-DQN Agent for traffic light control.
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

        self.rng = np.random.RandomState(seed)

        # Primary and Target Dueling Q-networks
        self.q_network = DuelingDQNNetwork(in_features=in_features, num_actions=num_actions, seed=seed)
        self.target_network = DuelingDQNNetwork(in_features=in_features, num_actions=num_actions, seed=seed + 100)
        self.update_target_network()

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
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Selects action using epsilon-greedy policy with safety action masking.
        If can_switch is False (e.g. min_green not elapsed), ACTION_SWITCH is masked out.
        Returns (action, debug_info).
        """
        q_values = self.q_network.forward(observation)

        # Action masking: if min_green not yet reached, cannot SWITCH
        masked_q = q_values.copy()
        if not can_switch:
            masked_q[ACTION_SWITCH] = -1e9

        if not eval_mode and (self.rng.rand() < self.epsilon):
            # Exploration
            valid_actions = [ACTION_KEEP, ACTION_EXTEND] if not can_switch else [ACTION_KEEP, ACTION_SWITCH, ACTION_EXTEND]
            action = int(self.rng.choice(valid_actions))
            reason = f"DQN ε-greedy exploration (ε={self.epsilon:.2f})"
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
            "epsilon": self.epsilon,
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
        Executes one Double-DQN training step using a mini-batch from the buffer.
        Double-DQN target: y = r + gamma * Q_target(s', argmax_a Q(s', a))
        """
        if len(self.replay_buffer) < batch_size:
            return None

        states, actions, rewards, next_states, dones = self.replay_buffer.sample(batch_size)

        # Current Q-values
        curr_q = self.q_network.forward(states)  # (batch, num_actions)

        # Double-DQN: choose best next action with current network, evaluate with target network
        next_q_curr = self.q_network.forward(next_states)  # (batch, num_actions)
        best_next_actions = np.argmax(next_q_curr, axis=1)  # (batch,)
        next_q_target = self.target_network.forward(next_states)  # (batch, num_actions)

        # Target Q-values
        target_q = curr_q.copy()
        for i in range(batch_size):
            if dones[i]:
                target_q[i, actions[i]] = rewards[i]
            else:
                a_max = best_next_actions[i]
                target_q[i, actions[i]] = rewards[i] + self.gamma * next_q_target[i, a_max]

        # TD Error Loss (MSE)
        td_errors = target_q - curr_q
        loss = float(np.mean(np.square(td_errors)))

        # Gradient update on primary network weights (analytical backprop on output layer)
        weights = self.q_network.get_weights()
        grad = -2.0 * td_errors / batch_size
        weights["adv_out_b"] -= self.lr * np.sum(grad, axis=0)
        self.q_network.set_weights(weights)

        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        # Periodic target update
        self.step_counter += 1
        if self.step_counter % self.target_update_interval == 0:
            self.update_target_network()

        return loss

    def get_state_dict(self) -> Dict[str, Any]:
        raw_w = self.q_network.get_weights()
        serializable_w = {k: v.tolist() if hasattr(v, "tolist") else v for k, v in raw_w.items()}
        return {
            "agent_id": self.agent_id,
            "epsilon": float(self.epsilon),
            "q_network_weights": serializable_w,
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        self.epsilon = float(state_dict.get("epsilon", self.epsilon_min))
        if "q_network_weights" in state_dict:
            raw_w = state_dict["q_network_weights"]
            converted_w = {
                k: np.array(v, dtype=np.float32) if not isinstance(v, np.ndarray) else v
                for k, v in raw_w.items()
            }
            self.q_network.set_weights(converted_w)
            self.update_target_network()
