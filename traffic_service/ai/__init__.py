"""
traffic_service/ai package

Multi-Agent Reinforcement Learning (MARL) Decision Layer for Coordinated
Multi-Intersection Traffic Management along the Silk Board corridor (J1 -> J2 -> J3).
"""

from .env import (
    CorridorObservationSpace,
    MultiIntersectionReward,
    ACTION_KEEP,
    ACTION_SWITCH,
    ACTION_EXTEND,
    ACTION_NAMES,
)
from .models import (
    DuelingDQNNetwork,
    ActorCriticNetwork,
)
from .dqn_agent import DQNAgent, ReplayBuffer
from .ppo_agent import PPOAgent
from .marl_controller import MARLCorridorController

__all__ = [
    "CorridorObservationSpace",
    "MultiIntersectionReward",
    "ACTION_KEEP",
    "ACTION_SWITCH",
    "ACTION_EXTEND",
    "ACTION_NAMES",
    "DuelingDQNNetwork",
    "ActorCriticNetwork",
    "DQNAgent",
    "ReplayBuffer",
    "PPOAgent",
    "MARLCorridorController",
]
