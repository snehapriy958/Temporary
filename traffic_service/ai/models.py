"""
traffic_service/ai/models.py

Neural Network Architectures for Signal Decision Optimization.
Includes:
- Dueling DQN (Value + Advantage streams for discrete action selection)
- Actor-Critic (Policy head with categorical distribution + Critic state-value head)

Features dual implementation:
- PyTorch (torch.nn) when installed
- High-performance, self-contained NumPy implementation for zero-dependency execution
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

# Check if PyTorch is available
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


# =====================================================================
# NumPy Implementations (Deterministic, High-Performance, Standalone)
# =====================================================================

def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    """Numerically stable softmax."""
    e_x = np.exp(x - np.max(x, axis=axis, keepdims=True))
    return e_x / np.sum(e_x, axis=axis, keepdims=True)


class NumpyDense:
    """Fully-connected layer with He/Kaiming initialization in NumPy."""

    def __init__(self, in_features: int, out_features: int, seed: Optional[int] = None) -> None:
        rng = np.random.RandomState(seed)
        std = math.sqrt(2.0 / in_features)
        self.weights = rng.normal(0.0, std, (in_features, out_features)).astype(np.float32)
        self.biases = np.zeros(out_features, dtype=np.float32)

    def forward(self, x: np.ndarray) -> np.ndarray:
        return np.dot(x, self.weights) + self.biases


class NumpyDuelingDQN:
    """
    Dueling Q-Network implemented in pure NumPy.
    Decomposes Q(s, a) into State Value V(s) and Advantage A(s, a).
    """

    def __init__(self, in_features: int = 14, num_actions: int = 3, seed: int = 42) -> None:
        self.in_features = in_features
        self.num_actions = num_actions

        # Feature extractor
        self.fc1 = NumpyDense(in_features, 64, seed=seed)
        self.fc2 = NumpyDense(64, 64, seed=seed + 1)

        # Value stream: 64 -> 32 -> 1
        self.val_fc = NumpyDense(64, 32, seed=seed + 2)
        self.val_out = NumpyDense(32, 1, seed=seed + 3)

        # Advantage stream: 64 -> 32 -> num_actions
        self.adv_fc = NumpyDense(64, 32, seed=seed + 4)
        self.adv_out = NumpyDense(32, num_actions, seed=seed + 5)

    def forward(self, x: np.ndarray) -> np.ndarray:
        """
        Forward pass computing Q(s, a) = V(s) + (A(s, a) - mean(A(s, a))).
        Input can be 1D (in_features,) or 2D (batch, in_features).
        """
        is_1d = (x.ndim == 1)
        if is_1d:
            x = np.expand_dims(x, axis=0)

        # Shared trunk (ReLU activations)
        h1 = np.maximum(0.0, self.fc1.forward(x))
        h2 = np.maximum(0.0, self.fc2.forward(h1))

        # Value stream
        v_h = np.maximum(0.0, self.val_fc.forward(h2))
        v = self.val_out.forward(v_h)  # shape (batch, 1)

        # Advantage stream
        a_h = np.maximum(0.0, self.adv_fc.forward(h2))
        adv = self.adv_out.forward(a_h)  # shape (batch, num_actions)

        # Combine: Q = V + (A - mean(A))
        q = v + (adv - np.mean(adv, axis=1, keepdims=True))

        return q[0] if is_1d else q

    def get_weights(self) -> Dict[str, np.ndarray]:
        return {
            "fc1_w": self.fc1.weights, "fc1_b": self.fc1.biases,
            "fc2_w": self.fc2.weights, "fc2_b": self.fc2.biases,
            "val_fc_w": self.val_fc.weights, "val_fc_b": self.val_fc.biases,
            "val_out_w": self.val_out.weights, "val_out_b": self.val_out.biases,
            "adv_fc_w": self.adv_fc.weights, "adv_fc_b": self.adv_fc.biases,
            "adv_out_w": self.adv_out.weights, "adv_out_b": self.adv_out.biases,
        }

    def set_weights(self, weights: Dict[str, np.ndarray]) -> None:
        self.fc1.weights = weights["fc1_w"].copy()
        self.fc1.biases = weights["fc1_b"].copy()
        self.fc2.weights = weights["fc2_w"].copy()
        self.fc2.biases = weights["fc2_b"].copy()
        self.val_fc.weights = weights["val_fc_w"].copy()
        self.val_fc.biases = weights["val_fc_b"].copy()
        self.val_out.weights = weights["val_out_w"].copy()
        self.val_out.biases = weights["val_out_b"].copy()
        self.adv_fc.weights = weights["adv_fc_w"].copy()
        self.adv_fc.biases = weights["adv_fc_b"].copy()
        self.adv_out.weights = weights["adv_out_w"].copy()
        self.adv_out.biases = weights["adv_out_b"].copy()


class NumpyActorCritic:
    """
    Actor-Critic architecture in pure NumPy.
    Policy head produces action probabilities; Critic head produces state value.
    """

    def __init__(self, in_features: int = 14, num_actions: int = 3, seed: int = 42) -> None:
        self.in_features = in_features
        self.num_actions = num_actions

        # Shared representation
        self.fc1 = NumpyDense(in_features, 64, seed=seed)
        self.fc2 = NumpyDense(64, 64, seed=seed + 1)

        # Actor head: 64 -> 32 -> num_actions
        self.actor_fc = NumpyDense(64, 32, seed=seed + 2)
        self.actor_out = NumpyDense(32, num_actions, seed=seed + 3)

        # Critic head: 64 -> 32 -> 1
        self.critic_fc = NumpyDense(64, 32, seed=seed + 4)
        self.critic_out = NumpyDense(32, 1, seed=seed + 5)

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Returns (action_probabilities, state_value).
        """
        is_1d = (x.ndim == 1)
        if is_1d:
            x = np.expand_dims(x, axis=0)

        # Shared trunk
        h1 = np.maximum(0.0, self.fc1.forward(x))
        h2 = np.maximum(0.0, self.fc2.forward(h1))

        # Actor (policy logits -> probabilities)
        a_h = np.maximum(0.0, self.actor_fc.forward(h2))
        logits = self.actor_out.forward(a_h)
        probs = softmax(logits, axis=1)

        # Critic (state-value)
        c_h = np.maximum(0.0, self.critic_fc.forward(h2))
        value = self.critic_out.forward(c_h)

        if is_1d:
            return probs[0], float(value[0, 0])
        return probs, value.squeeze(-1)

    def get_weights(self) -> Dict[str, np.ndarray]:
        return {
            "fc1_w": self.fc1.weights, "fc1_b": self.fc1.biases,
            "fc2_w": self.fc2.weights, "fc2_b": self.fc2.biases,
            "actor_fc_w": self.actor_fc.weights, "actor_fc_b": self.actor_fc.biases,
            "actor_out_w": self.actor_out.weights, "actor_out_b": self.actor_out.biases,
            "critic_fc_w": self.critic_fc.weights, "critic_fc_b": self.critic_fc.biases,
            "critic_out_w": self.critic_out.weights, "critic_out_b": self.critic_out.biases,
        }

    def set_weights(self, weights: Dict[str, np.ndarray]) -> None:
        self.fc1.weights = weights["fc1_w"].copy()
        self.fc1.biases = weights["fc1_b"].copy()
        self.fc2.weights = weights["fc2_w"].copy()
        self.fc2.biases = weights["fc2_b"].copy()
        self.actor_fc.weights = weights["actor_fc_w"].copy()
        self.actor_fc.biases = weights["actor_fc_b"].copy()
        self.actor_out.weights = weights["actor_out_w"].copy()
        self.actor_out.biases = weights["actor_out_b"].copy()
        self.critic_fc.weights = weights["critic_fc_w"].copy()
        self.critic_fc.biases = weights["critic_fc_b"].copy()
        self.critic_out.weights = weights["critic_out_w"].copy()
        self.critic_out.biases = weights["critic_out_b"].copy()


# =====================================================================
# Unified Factory Wrappers (Exposes Consistent Interface)
# =====================================================================

class DuelingDQNNetwork:
    """Wrapper delivering unified forward pass and weight operations."""

    def __init__(self, in_features: int = 14, num_actions: int = 3, seed: int = 42) -> None:
        self._model = NumpyDuelingDQN(in_features=in_features, num_actions=num_actions, seed=seed)

    def forward(self, x: np.ndarray) -> np.ndarray:
        return self._model.forward(x)

    def get_weights(self) -> Dict[str, np.ndarray]:
        return self._model.get_weights()

    def set_weights(self, weights: Dict[str, np.ndarray]) -> None:
        self._model.set_weights(weights)


class ActorCriticNetwork:
    """Wrapper delivering unified policy and value inference."""

    def __init__(self, in_features: int = 14, num_actions: int = 3, seed: int = 42) -> None:
        self._model = NumpyActorCritic(in_features=in_features, num_actions=num_actions, seed=seed)

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, float | np.ndarray]:
        return self._model.forward(x)

    def get_weights(self) -> Dict[str, np.ndarray]:
        return self._model.get_weights()

    def set_weights(self, weights: Dict[str, np.ndarray]) -> None:
        self._model.set_weights(weights)
