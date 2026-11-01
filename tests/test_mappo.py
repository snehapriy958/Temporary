"""
tests/test_mappo.py

Unit tests for Multi-Agent PPO (MAPPO):
- Decentralized Actor Network with Action Masking
- Centralized Corridor Critic Network (42-dim state value)
- GAE Advantage Estimation
- CTDE Policy and Critic Training Steps
- Checkpoint Serialization and Deserialization
- Integration in MARLCorridorController
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import numpy as np
import pytest
import torch

from traffic_service.ai.env import (
    ACTION_KEEP,
    ACTION_SWITCH,
    ACTION_EXTEND,
    CORRIDOR_OBSERVATION_DIM,
    OBSERVATION_DIM_PER_JUNCTION,
)
from traffic_service.ai.models import (
    MAPPOActorNetwork,
    MAPPOCentralizedCriticNetwork,
    NumpyMAPPOActor,
    NumpyMAPPOCentralizedCritic,
)
from traffic_service.ai.mappo_agent import MAPPOAgent
from traffic_service.ai.marl_controller import MARLCorridorController


def test_mappo_actor_masking():
    actor = MAPPOActorNetwork(in_features=14, num_actions=3, seed=42)
    obs = np.random.randn(14).astype(np.float32)

    # 1. Unconstrained forward pass
    logits_unmasked, probs_unmasked = actor.forward(obs, mask=np.array([1.0, 1.0, 1.0]))
    assert len(probs_unmasked) == 3
    assert pytest.approx(float(np.sum(probs_unmasked)), abs=1e-5) == 1.0

    # 2. Masking action 1 (SWITCH)
    mask_no_switch = np.array([1.0, 0.0, 1.0], dtype=np.float32)
    _, probs_no_switch = actor.forward(obs, mask=mask_no_switch)
    assert probs_no_switch[1] < 1e-6
    assert probs_no_switch[0] + probs_no_switch[2] == pytest.approx(1.0, abs=1e-5)

    # 3. Forcing action 1 (SWITCH)
    mask_force_switch = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    _, probs_force_switch = actor.forward(obs, mask=mask_force_switch)
    assert probs_force_switch[1] == pytest.approx(1.0, abs=1e-5)
    assert probs_force_switch[0] < 1e-6
    assert probs_force_switch[2] < 1e-6


def test_mappo_centralized_critic():
    critic = MAPPOCentralizedCriticNetwork(in_features=42, seed=42)

    # Single-sample corridor observation (dim=42)
    obs = np.random.randn(42).astype(np.float32)
    val = critic.forward(obs)
    assert isinstance(val, float)

    # Batch observation
    batch_obs = np.random.randn(8, 42).astype(np.float32)
    batch_val = critic.forward(batch_obs)
    assert batch_val.shape == (8,)


def test_mappo_numpy_models():
    np_actor = NumpyMAPPOActor(in_features=14, num_actions=3, seed=42)
    obs_14 = np.random.randn(14).astype(np.float32)
    _, probs = np_actor.forward(obs_14, mask=np.array([1.0, 0.0, 0.0]))
    assert probs[0] == pytest.approx(1.0, abs=1e-5)
    assert probs[1] == pytest.approx(0.0, abs=1e-5)

    np_critic = NumpyMAPPOCentralizedCritic(in_features=42, seed=42)
    obs_42 = np.random.randn(42).astype(np.float32)
    val = np_critic.forward(obs_42)
    assert isinstance(val, float)


def test_mappo_agent_action_selection_and_log_prob():
    agent = MAPPOAgent("J1", in_features=14, corridor_features=42, seed=42)
    obs = np.random.randn(14).astype(np.float32)

    # Forced action via anti-starvation mask
    mask = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    action, info = agent.select_action(obs, action_mask=mask, eval_mode=False)
    assert action == ACTION_SWITCH
    assert info["action_name"] == "SWITCH"
    assert info["probabilities"][1] == pytest.approx(1.0, abs=1e-5)

    # Evaluated log_prob should be close to 0.0 (log(1.0) = 0.0)
    assert info["log_prob"] == pytest.approx(0.0, abs=1e-4)


def test_mappo_agent_gae_and_train_step():
    agent = MAPPOAgent("J1", in_features=14, corridor_features=42, seed=42)

    # Record initial weights
    w_actor_init = agent.actor.get_weights()["actor_out_w"].copy()
    w_critic_init = agent.critic.get_weights()["critic_out_w"].copy()

    # Populate buffer with mock trajectory transitions
    for t in range(20):
        l_obs = np.random.randn(14).astype(np.float32)
        c_obs = np.random.randn(42).astype(np.float32)
        act, info = agent.select_action(l_obs, eval_mode=False)
        agent.store_transition(
            local_state=l_obs,
            corridor_state=c_obs,
            action=act,
            action_mask=np.array(info["action_mask"]),
            reward=float(np.sin(t)),
            log_prob=info["log_prob"],
            value=agent.get_corridor_value(c_obs),
            done=(t == 19),
        )

    # Execute training update
    metrics = agent.train_step(last_corridor_value=0.0, epochs=3, minibatch_size=10)

    assert "loss" in metrics
    assert "policy_loss" in metrics
    assert "critic_loss" in metrics
    assert "entropy" in metrics
    assert not np.isnan(metrics["loss"])

    # Verify that trainable parameters updated (gradient backpropagation occurred)
    w_actor_post = agent.actor.get_weights()["actor_out_w"]
    w_critic_post = agent.critic.get_weights()["critic_out_w"]

    assert not np.allclose(w_actor_init, w_actor_post), "Actor weights must be updated by backprop"
    assert not np.allclose(w_critic_init, w_critic_post), "Critic weights must be updated by backprop"


def test_mappo_agent_checkpoint_state_dict():
    agent = MAPPOAgent("J1", in_features=14, corridor_features=42, seed=42)

    # Extract state dict
    state_dict = agent.get_state_dict()
    assert state_dict["agent_id"] == "J1"
    assert state_dict["algorithm_version"] == "2.0-mappo"
    assert "actor_weights" in state_dict
    assert "critic_weights" in state_dict

    # Instantiate fresh agent and load
    agent_fresh = MAPPOAgent("J1", in_features=14, corridor_features=42, seed=999)
    agent_fresh.load_state_dict(state_dict)

    # Compare weights
    w1 = agent.actor.get_weights()["fc1_w"]
    w2 = agent_fresh.actor.get_weights()["fc1_w"]
    np.testing.assert_allclose(w1, w2, rtol=1e-5, atol=1e-5)


def test_marl_corridor_controller_mappo_integration():
    marl = MARLCorridorController(algorithm="mappo", junctions=["J1", "J2", "J3"], seed=42)

    assert marl.algorithm == "mappo"
    assert marl.shared_critic is not None
    assert len(marl.agents) == 3

    # All three agents must share the exact same centralized critic instance
    for j_id in ["J1", "J2", "J3"]:
        assert marl.agents[j_id].critic is marl.shared_critic

    raw_obs = {
        "J1": {"phase": 2, "phase_elapsed": 18.0, "total_queue": 4, "approach_queues": {"corridor_hosur": 4}},
        "J2": {"phase": 0, "phase_elapsed": 25.0, "total_queue": 6, "approach_queues": {"corridor_hosur": 6}},
        "J3": {"phase": 2, "phase_elapsed": 12.0, "total_queue": 2, "approach_queues": {"corridor_hosur": 2}},
    }

    decisions = marl.decide(raw_obs, sim_time=100.0, eval_mode=True)
    assert len(decisions) == 3
    for j_id in ["J1", "J2", "J3"]:
        assert "action" in decisions[j_id]
        assert "action_mask" in decisions[j_id]
        assert "probabilities" in decisions[j_id]
        assert decisions[j_id]["action"] in [ACTION_KEEP, ACTION_SWITCH, ACTION_EXTEND]

    # Test Checkpoint Save and Load
    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt_path = Path(tmpdir) / "mappo_checkpoint.json"
        marl.save_checkpoint(ckpt_path, version="2.0-mappo")
        assert ckpt_path.is_file()

        fresh_marl = MARLCorridorController(algorithm="mappo", junctions=["J1", "J2", "J3"], seed=999)
        loaded = fresh_marl.load_checkpoint(ckpt_path)
        assert loaded is True

        # Verify weights match
        w_orig = marl.shared_critic.get_weights()["fc1_w"]
        w_loaded = fresh_marl.shared_critic.get_weights()["fc1_w"]
        np.testing.assert_allclose(w_orig, w_loaded, rtol=1e-5, atol=1e-5)
