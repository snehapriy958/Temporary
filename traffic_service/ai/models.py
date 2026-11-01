"""
traffic_service/ai/models.py

Neural Network Architectures for Signal Decision Optimization.
Includes:
- Dueling DQN (Value + Advantage streams for discrete action selection)
- Actor-Critic (Policy head with categorical distribution + Critic state-value head)

Features dual implementation:
- PyTorch (torch.nn) authoritative autograd implementation with full gradient propagation
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
# PyTorch Implementations (Authoritative, Autograd-Enabled, Full Gradient Propagation)
# =====================================================================

if TORCH_AVAILABLE:

    class PyTorchDuelingDQN(nn.Module):
        """
        Dueling Deep Q-Network in PyTorch.
        Computes Q(s, a) = V(s) + (A(s, a) - mean(A(s, a))) with full autograd.
        """

        def __init__(self, in_features: int = 14, num_actions: int = 3, seed: int = 42) -> None:
            super().__init__()
            torch.manual_seed(seed)
            self.in_features = in_features
            self.num_actions = num_actions

            # Shared trunk
            self.fc1 = nn.Linear(in_features, 64)
            self.fc2 = nn.Linear(64, 64)

            # State Value stream V(s)
            self.val_fc = nn.Linear(64, 32)
            self.val_out = nn.Linear(32, 1)

            # Advantage stream A(s, a)
            self.adv_fc = nn.Linear(64, 32)
            self.adv_out = nn.Linear(32, num_actions)

            self._init_weights(seed)

        def _init_weights(self, seed: int) -> None:
            rng = np.random.RandomState(seed)
            for m in [self.fc1, self.fc2, self.val_fc, self.val_out, self.adv_fc, self.adv_out]:
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")
                nn.init.zeros_(m.bias)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            h1 = F.relu(self.fc1(x))
            h2 = F.relu(self.fc2(h1))
            v = self.val_out(F.relu(self.val_fc(h2)))
            adv = self.adv_out(F.relu(self.adv_fc(h2)))
            # Dueling combination: Q(s, a) = V(s) + (A(s, a) - mean_a' A(s, a'))
            q = v + (adv - adv.mean(dim=-1, keepdim=True))
            return q

        def get_weights(self) -> Dict[str, np.ndarray]:
            """Returns weight dictionary compatible with existing JSON checkpoint schema."""
            return {
                "fc1_w": self.fc1.weight.detach().cpu().numpy().T.copy(),
                "fc1_b": self.fc1.bias.detach().cpu().numpy().copy(),
                "fc2_w": self.fc2.weight.detach().cpu().numpy().T.copy(),
                "fc2_b": self.fc2.bias.detach().cpu().numpy().copy(),
                "val_fc_w": self.val_fc.weight.detach().cpu().numpy().T.copy(),
                "val_fc_b": self.val_fc.bias.detach().cpu().numpy().copy(),
                "val_out_w": self.val_out.weight.detach().cpu().numpy().T.copy(),
                "val_out_b": self.val_out.bias.detach().cpu().numpy().copy(),
                "adv_fc_w": self.adv_fc.weight.detach().cpu().numpy().T.copy(),
                "adv_fc_b": self.adv_fc.bias.detach().cpu().numpy().copy(),
                "adv_out_w": self.adv_out.weight.detach().cpu().numpy().T.copy(),
                "adv_out_b": self.adv_out.bias.detach().cpu().numpy().copy(),
            }

        def set_weights(self, weights: Dict[str, np.ndarray]) -> None:
            """Loads weights from checkpoint format into PyTorch layers."""
            with torch.no_grad():
                self.fc1.weight.copy_(torch.from_numpy(weights["fc1_w"].T))
                self.fc1.bias.copy_(torch.from_numpy(weights["fc1_b"]))
                self.fc2.weight.copy_(torch.from_numpy(weights["fc2_w"].T))
                self.fc2.bias.copy_(torch.from_numpy(weights["fc2_b"]))
                self.val_fc.weight.copy_(torch.from_numpy(weights["val_fc_w"].T))
                self.val_fc.bias.copy_(torch.from_numpy(weights["val_fc_b"]))
                self.val_out.weight.copy_(torch.from_numpy(weights["val_out_w"].T))
                self.val_out.bias.copy_(torch.from_numpy(weights["val_out_b"]))
                self.adv_fc.weight.copy_(torch.from_numpy(weights["adv_fc_w"].T))
                self.adv_fc.bias.copy_(torch.from_numpy(weights["adv_fc_b"]))
                self.adv_out.weight.copy_(torch.from_numpy(weights["adv_out_w"].T))
                self.adv_out.bias.copy_(torch.from_numpy(weights["adv_out_b"]))


    class PyTorchActorCritic(nn.Module):
        """
        Actor-Critic architecture in PyTorch.
        Actor head outputs action distribution; Critic head outputs scalar state value.
        """

        def __init__(self, in_features: int = 14, num_actions: int = 3, seed: int = 42) -> None:
            super().__init__()
            torch.manual_seed(seed)
            self.in_features = in_features
            self.num_actions = num_actions

            # Shared trunk
            self.fc1 = nn.Linear(in_features, 64)
            self.fc2 = nn.Linear(64, 64)

            # Actor head
            self.actor_fc = nn.Linear(64, 32)
            self.actor_out = nn.Linear(32, num_actions)

            # Critic head
            self.critic_fc = nn.Linear(64, 32)
            self.critic_out = nn.Linear(32, 1)

            self._init_weights(seed)

        def _init_weights(self, seed: int) -> None:
            for m in [self.fc1, self.fc2, self.actor_fc, self.actor_out, self.critic_fc, self.critic_out]:
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")
                nn.init.zeros_(m.bias)

        def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            h1 = F.relu(self.fc1(x))
            h2 = F.relu(self.fc2(h1))
            logits = self.actor_out(F.relu(self.actor_fc(h2)))
            probs = F.softmax(logits, dim=-1)
            value = self.critic_out(F.relu(self.critic_fc(h2))).squeeze(-1)
            return probs, value

        def forward_logits_value(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            h1 = F.relu(self.fc1(x))
            h2 = F.relu(self.fc2(h1))
            logits = self.actor_out(F.relu(self.actor_fc(h2)))
            value = self.critic_out(F.relu(self.critic_fc(h2))).squeeze(-1)
            return logits, value

        def get_weights(self) -> Dict[str, np.ndarray]:
            return {
                "fc1_w": self.fc1.weight.detach().cpu().numpy().T.copy(),
                "fc1_b": self.fc1.bias.detach().cpu().numpy().copy(),
                "fc2_w": self.fc2.weight.detach().cpu().numpy().T.copy(),
                "fc2_b": self.fc2.bias.detach().cpu().numpy().copy(),
                "actor_fc_w": self.actor_fc.weight.detach().cpu().numpy().T.copy(),
                "actor_fc_b": self.actor_fc.bias.detach().cpu().numpy().copy(),
                "actor_out_w": self.actor_out.weight.detach().cpu().numpy().T.copy(),
                "actor_out_b": self.actor_out.bias.detach().cpu().numpy().copy(),
                "critic_fc_w": self.critic_fc.weight.detach().cpu().numpy().T.copy(),
                "critic_fc_b": self.critic_fc.bias.detach().cpu().numpy().copy(),
                "critic_out_w": self.critic_out.weight.detach().cpu().numpy().T.copy(),
                "critic_out_b": self.critic_out.bias.detach().cpu().numpy().copy(),
            }

        def set_weights(self, weights: Dict[str, np.ndarray]) -> None:
            with torch.no_grad():
                self.fc1.weight.copy_(torch.from_numpy(weights["fc1_w"].T))
                self.fc1.bias.copy_(torch.from_numpy(weights["fc1_b"]))
                self.fc2.weight.copy_(torch.from_numpy(weights["fc2_w"].T))
                self.fc2.bias.copy_(torch.from_numpy(weights["fc2_b"]))
                self.actor_fc.weight.copy_(torch.from_numpy(weights["actor_fc_w"].T))
                self.actor_fc.bias.copy_(torch.from_numpy(weights["actor_fc_b"]))
                self.actor_out.weight.copy_(torch.from_numpy(weights["actor_out_w"].T))
                self.actor_out.bias.copy_(torch.from_numpy(weights["actor_out_b"]))
                self.critic_fc.weight.copy_(torch.from_numpy(weights["critic_fc_w"].T))
                self.critic_fc.bias.copy_(torch.from_numpy(weights["critic_fc_b"]))
                self.critic_out.weight.copy_(torch.from_numpy(weights["critic_out_w"].T))
                self.critic_out.bias.copy_(torch.from_numpy(weights["critic_out_b"]))


# =====================================================================
# Unified Factory Wrappers (Exposes Consistent Interface)
# =====================================================================

class DuelingDQNNetwork:
    """Wrapper delivering unified forward pass, autograd access, and weight operations."""

    def __init__(self, in_features: int = 14, num_actions: int = 3, seed: int = 42) -> None:
        self.in_features = in_features
        self.num_actions = num_actions
        self.seed = seed
        if TORCH_AVAILABLE:
            self._model = PyTorchDuelingDQN(in_features=in_features, num_actions=num_actions, seed=seed)
        else:
            self._model = NumpyDuelingDQN(in_features=in_features, num_actions=num_actions, seed=seed)

    @property
    def model(self) -> Any:
        return self._model

    def parameters(self):
        return self._model.parameters()

    def named_parameters(self):
        return self._model.named_parameters()

    def train(self, mode: bool = True):
        if hasattr(self._model, "train"):
            self._model.train(mode)
        return self

    def eval(self):
        if hasattr(self._model, "eval"):
            self._model.eval()
        return self

    def __call__(self, x: Any) -> Any:
        return self.forward(x)

    def forward(self, x: Union[np.ndarray, torch.Tensor]) -> Union[np.ndarray, torch.Tensor]:
        if TORCH_AVAILABLE and isinstance(self._model, nn.Module):
            if isinstance(x, torch.Tensor):
                return self._model(x)
            # NumPy input handling
            is_1d = (x.ndim == 1)
            t_x = torch.from_numpy(np.expand_dims(x, axis=0) if is_1d else x).float()
            with torch.no_grad():
                out = self._model(t_x).numpy()
            return out[0] if is_1d else out
        else:
            return self._model.forward(x)

    def get_weights(self) -> Dict[str, np.ndarray]:
        return self._model.get_weights()

    def set_weights(self, weights: Dict[str, np.ndarray]) -> None:
        self._model.set_weights(weights)


class ActorCriticNetwork:
    """Wrapper delivering unified policy and value inference with full autograd."""

    def __init__(self, in_features: int = 14, num_actions: int = 3, seed: int = 42) -> None:
        self.in_features = in_features
        self.num_actions = num_actions
        self.seed = seed
        if TORCH_AVAILABLE:
            self._model = PyTorchActorCritic(in_features=in_features, num_actions=num_actions, seed=seed)
        else:
            self._model = NumpyActorCritic(in_features=in_features, num_actions=num_actions, seed=seed)

    @property
    def model(self) -> Any:
        return self._model

    def parameters(self):
        return self._model.parameters()

    def named_parameters(self):
        return self._model.named_parameters()

    def train(self, mode: bool = True):
        if hasattr(self._model, "train"):
            self._model.train(mode)
        return self

    def eval(self):
        if hasattr(self._model, "eval"):
            self._model.eval()
        return self

    def __call__(self, x: Any) -> Any:
        return self.forward(x)

    def forward(self, x: Union[np.ndarray, torch.Tensor]) -> Tuple[Any, Any]:
        if TORCH_AVAILABLE and isinstance(self._model, nn.Module):
            if isinstance(x, torch.Tensor):
                return self._model(x)
            is_1d = (x.ndim == 1)
            t_x = torch.from_numpy(np.expand_dims(x, axis=0) if is_1d else x).float()
            with torch.no_grad():
                probs, vals = self._model(t_x)
                probs_np = probs.numpy()
                vals_np = vals.numpy()
            if is_1d:
                return probs_np[0], float(vals_np[0])
            return probs_np, vals_np
        else:
            return self._model.forward(x)

    def forward_logits_value(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        if TORCH_AVAILABLE and hasattr(self._model, "forward_logits_value"):
            return self._model.forward_logits_value(x)
        raise NotImplementedError("forward_logits_value requires PyTorch")

    def get_weights(self) -> Dict[str, np.ndarray]:
        return self._model.get_weights()

    def set_weights(self, weights: Dict[str, np.ndarray]) -> None:
        self._model.set_weights(weights)
