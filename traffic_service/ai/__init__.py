"""
traffic_service/ai package

Multi-Agent Reinforcement Learning (MARL) Decision Layer for Coordinated
Multi-Intersection Traffic Management along the Silk Board corridor (J1 -> J2 -> J3).
"""

from .env import (
    CorridorObservationSpace,
    MultiIntersectionReward,
    RewardWeights,
    RewardBreakdown,
    ACTION_KEEP,
    ACTION_SWITCH,
    ACTION_EXTEND,
    ACTION_NAMES,
)
from .models import (
    DuelingDQNNetwork,
    ActorCriticNetwork,
    MAPPOActorNetwork,
    MAPPOCentralizedCriticNetwork,
)
from .dqn_agent import DQNAgent, ReplayBuffer
from .ppo_agent import PPOAgent
from .mappo_agent import MAPPOAgent
from .starvation_tracker import StarvationTracker
from .marl_controller import MARLCorridorController

__all__ = [
    "CorridorObservationSpace",
    "MultiIntersectionReward",
    "RewardWeights",
    "RewardBreakdown",
    "ACTION_KEEP",
    "ACTION_SWITCH",
    "ACTION_EXTEND",
    "ACTION_NAMES",
    "DuelingDQNNetwork",
    "ActorCriticNetwork",
    "MAPPOActorNetwork",
    "MAPPOCentralizedCriticNetwork",
    "DQNAgent",
    "ReplayBuffer",
    "PPOAgent",
    "MAPPOAgent",
    "StarvationTracker",
    "MARLCorridorController",
]
