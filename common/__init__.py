"""
common package
Shared utilities and environment resolution for Smart Traffic Coordination.
"""

from .sumo_env import SumoEnvironment, SumoEnvironmentError, require_sumo_env, silk_board_dir

__all__ = [
    "SumoEnvironment",
    "SumoEnvironmentError",
    "require_sumo_env",
    "silk_board_dir",
]
