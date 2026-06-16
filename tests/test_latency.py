import pytest

from multirail_topology import MultiRailTopology, MultiRailTopologyConfig, RoutingMode
from multirail_topology.latency import (
    LatencyConfig,
    max_domain_size_rtt_latency,
    max_domain_rtt_latency,
    path_one_way_latency_ns,
    route_pair_rtt_latency,
)
from multirail_topology.sparse_clos import ClusterInternalMode, SparseClosConfig


def _latency_config() -> LatencyConfig:
    return LatencyConfig(
        switch_forward_latency_ns=10.0,
        card_forward_latency_ns=7.0,
        optical_module_latency_ns=2.0,
        npu_processing_latency_ns=100.0,
        intra_1dfm_link_length_m=3.0,
        fm2d_link_length_m=5.0,
        switch_link_length_m=4.0,
    )


def test_intra_card_path_latency_uses_1dfm_link_without_optics():
    topology = MultiRailTopology(MultiRailTopologyConfig(M=1, N=2, X=1))
    topology.build_graph()

    latency = path_one_way_latency_ns(
        topology,
        ["node0-card0", "node0-card1"],
        _latency_config(),
    )

    assert latency == pytest.approx(15.0)


def test_switch_path_rtt_latency_uses_optics_switch_and_npu():
    topology = MultiRailTopology(MultiRailTopologyConfig(M=2, N=2, X=1))
    topology.build_graph()

    result = route_pair_rtt_latency(
        topology,
        "node0-card0",
        "node1-card0",
        RoutingMode.SOURCE_NODE_JUMP,
        _latency_config(),
    )

    assert result.single_rtt_latency_ns == pytest.approx(216.0)
    assert result.path == ["node0-card0", "switch0", "node1-card0"]


def test_domain_latency_uses_max_card_pair_rtt():
    topology = MultiRailTopology(MultiRailTopologyConfig(M=2, N=2, X=1))
    topology.build_graph()

    result = max_domain_rtt_latency(
        topology,
        ["node0-card0", "node0-card1", "node1-card0", "node1-card1"],
        RoutingMode.SOURCE_NODE_JUMP,
        _latency_config(),
    )

    assert result.single_rtt_latency_ns == pytest.approx(216.0)
    assert "switch0" in result.path


def test_fast_domain_size_latency_matches_full_domain_latency_for_2dfm_modes():
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            M=4,
            N=4,
            X=2,
            topology_type="2d-fm-clos",
            fm2d_domain_size=2,
        )
    )
    topology.build_graph()
    cards = [f"node{node_index}-card{card_index}" for node_index in range(4) for card_index in range(4)]

    for mode in (RoutingMode.SOURCE_2DFM_JUMP, RoutingMode.DESTINATION_2DFM_JUMP):
        full = max_domain_rtt_latency(topology, cards, mode, _latency_config())
        fast = max_domain_size_rtt_latency(topology, cards, len(cards), mode, _latency_config())

        assert fast.single_rtt_latency_ns == pytest.approx(full.single_rtt_latency_ns)


def test_fast_domain_latency_keeps_1dfm_cross_switch_source_jump_candidates():
    topology = MultiRailTopology(MultiRailTopologyConfig(M=4, N=8, X=2))
    topology.build_graph()
    cards = [f"node{node_index}-card{card_index}" for node_index in range(4) for card_index in range(8)]

    domain_16 = max_domain_size_rtt_latency(
        topology,
        cards,
        16,
        RoutingMode.SOURCE_NODE_JUMP,
        _latency_config(),
    )
    domain_32 = max_domain_size_rtt_latency(
        topology,
        cards,
        32,
        RoutingMode.SOURCE_NODE_JUMP,
        _latency_config(),
    )

    assert domain_32.single_rtt_latency_ns >= domain_16.single_rtt_latency_ns
    assert domain_32.single_rtt_latency_ns == pytest.approx(260.0)
    assert len(domain_32.path) == 4
    assert any(node_id.startswith("switch") for node_id in domain_32.path)


def test_sparse_clos_shortest_path_latency_uses_switch_link_timing():
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            topology_type="sparse-clos",
            sparse_clos=SparseClosConfig(
                bst_r=1,
                bst_k=2,
                switch_port_num=16,
                cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
            ),
        )
    )
    topology.build_graph()

    result = route_pair_rtt_latency(
        topology,
        "node0-card0",
        "node1-card0",
        RoutingMode.SHORTEST_PATH,
        _latency_config(),
    )

    assert result.single_rtt_latency_ns == pytest.approx(216.0)
    assert result.path == ["node0-card0", "switch0", "node1-card0"]


def test_sparse_clos_detour_domain_latency_uses_detour_forwarding():
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            topology_type="sparse-clos",
            sparse_clos=SparseClosConfig(
                bst_r=7,
                bst_k=2,
                switch_port_num=16,
                cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
            ),
        )
    )
    topology.build_graph()
    cards = [f"node{node_index}-card{card_index}" for node_index in range(8) for card_index in range(8)]

    result = max_domain_size_rtt_latency(
        topology,
        cards,
        2,
        RoutingMode.DETOUR_ROUTING,
        _latency_config(),
    )

    assert result.single_rtt_latency_ns == pytest.approx(216.0)
    assert result.path == ["node0-card0", "switch0", "node0-card1"]
