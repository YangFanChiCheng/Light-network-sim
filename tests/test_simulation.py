from pathlib import Path

import pytest
import multirail_topology.simulation as simulation_module

from multirail_topology import MultiRailTopology, MultiRailTopologyConfig, RoutingMode
from multirail_topology.routing import RouteResult
from multirail_topology.simulation import (
    factors,
    export_all_link_traffic_report,
    export_simulation_report,
    simulate_domain_size,
    simulate_domain_sizes,
)
from multirail_topology.latency import LatencyConfig
from multirail_topology.sparse_clos import ClusterInternalMode, SparseClosConfig


def _topology() -> MultiRailTopology:
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            M=2,
            N=2,
            X=1,
            intra_bandwidth=10.0,
            switch_bandwidth=5.0,
        )
    )
    topology.build_graph()
    return topology


def test_factors_returns_all_cluster_card_count_divisors():
    assert factors(12) == [1, 2, 3, 4, 6, 12]


def test_simulation_rejects_domain_size_that_does_not_divide_card_count():
    with pytest.raises(ValueError, match="domain_size must divide total card count"):
        simulate_domain_size(_topology(), 3)


def test_all2all_loads_are_split_across_equivalent_routes():
    topology = MultiRailTopology(MultiRailTopologyConfig(M=2, N=4, X=2))
    topology.build_graph()

    result = simulate_domain_size(
        topology,
        domain_size=8,
        mode=RoutingMode.SOURCE_NODE_JUMP,
        focus_card="node0-card0",
    )

    assert result.link_traffic[("node0-card0", "node0-card2")] == pytest.approx(
        result.link_traffic[("node0-card0", "node0-card3")]
    )
    assert result.link_traffic[("node0-card0", "node0-card2")] > 0


def test_simulation_uses_explicit_route_path_weights(monkeypatch):
    topology = _topology()
    original_route_between_cards = simulation_module.route_between_cards

    def weighted_route_between_cards(
        topology,
        source_card,
        destination_card,
        mode,
        domain_size=None,
    ):
        if source_card == "node0-card0" and destination_card == "node0-card1":
            return RouteResult(
                source_card,
                destination_card,
                "weighted_test",
                [
                    ["node0-card0", "node0-card1"],
                    ["node0-card0", "switch0", "node0-card1"],
                ],
                path_weights=[0.25, 0.75],
            )
        return original_route_between_cards(
            topology,
            source_card,
            destination_card,
            mode,
            domain_size=domain_size,
        )

    monkeypatch.setattr(simulation_module, "route_between_cards", weighted_route_between_cards)

    result = simulate_domain_size(
        topology,
        domain_size=2,
        mode=RoutingMode.SHORTEST_PATH,
        focus_card="node0-card0",
        workers=1,
    )

    assert result.link_traffic[("node0-card0", "node0-card1")] == pytest.approx(0.25)
    assert result.link_traffic[("node0-card0", "switch0")] == pytest.approx(0.75)
    assert result.link_traffic[("switch0", "node0-card1")] == pytest.approx(0.75)


def test_link_traffic_keeps_full_duplex_directions_separate():
    result = simulate_domain_size(_topology(), domain_size=4, focus_card="node0-card0")

    assert result.link_traffic[("node0-card0", "node0-card1")] == pytest.approx(1.0)
    assert result.link_traffic[("node0-card1", "node0-card0")] == pytest.approx(1.0)
    assert result.link_traffic[("node0-card0", "switch0")] == pytest.approx(2.0)
    assert result.link_traffic[("switch0", "node0-card0")] == pytest.approx(2.0)


def test_focus_card_efficiency_uses_max_adjacent_link_load():
    result = simulate_domain_size(_topology(), domain_size=4, focus_card="node0-card0")

    assert result.focus_card == "node0-card0"
    assert result.focus_card_sent_flows == 3
    assert result.focus_card_port_count == 2
    assert result.focus_card_adjacent_link_traffic == {
        ("node0-card0", "node0-card1"): 1.0,
        ("node0-card0", "switch0"): 2.0,
    }
    assert result.max_loaded_adjacent_link == ("node0-card0", "switch0")
    assert result.max_adjacent_link_load == pytest.approx(0.4)
    assert result.focus_card_efficiency_denominator == pytest.approx(6.0)
    assert result.focus_card_bandwidth_efficiency == pytest.approx(0.5)


def test_simulate_domain_sizes_defaults_to_all_factors():
    results = simulate_domain_sizes(_topology())

    assert [result.domain_size for result in results] == [2, 4]


def test_export_simulation_report_writes_domain_information():
    output_path = Path("test_outputs/simulation_report_test.txt")

    export_simulation_report(_topology(), output_path, domain_sizes=[4])

    report = output_path.read_text(encoding="utf-8")
    assert "| 通信域 D | efficiency | focus_card_link_traffic |" in report
    assert "| 4 | 0.500000 | [1, 2] |" in report
    assert "domain_size: 4" in report
    assert "focus_card_bandwidth_efficiency: 0.500000" in report
    assert "focus_card_link_loads: [N0_C0->N0_C1=0.1, N0_C0->S0=0.4]" in report
    assert "focus_card_link_traffic: [1, 2]" in report
    assert "focus_card_efficiency_denominator: 6.000000" in report
    assert "all_links:" not in report
    assert "max_loaded_adjacent_link: N0_C0 -> S0" in report


def test_export_simulation_report_adds_single_rtt_latency_column_when_configured():
    output_path = Path("test_outputs/simulation_latency_report_test.txt")

    export_simulation_report(
        _topology(),
        output_path,
        domain_sizes=[4],
        latency_config=LatencyConfig(
            switch_forward_latency_ns=10.0,
            card_forward_latency_ns=7.0,
            optical_module_latency_ns=2.0,
            npu_processing_latency_ns=100.0,
            intra_1dfm_link_length_m=3.0,
            fm2d_link_length_m=5.0,
            switch_link_length_m=4.0,
        ),
    )

    report = output_path.read_text(encoding="utf-8")
    assert "single_rtt_latency_ns" in report
    assert "| 4 | 0.500000 | [1, 2] | 216.000000 |" in report
    assert "single_rtt_latency_path: node0-card0 -> switch0 -> node1-card0" in report


def test_focus_card_link_traffic_array_orders_intra_cards_then_switches():
    topology = MultiRailTopology(
        MultiRailTopologyConfig(M=2, N=4, X=2, intra_bandwidth=10.0, switch_bandwidth=5.0)
    )
    topology.build_graph()
    result = simulate_domain_size(
        topology,
        domain_size=8,
        mode=RoutingMode.SOURCE_NODE_JUMP,
        focus_card="node0-card0",
    )

    from multirail_topology.simulation import _format_focus_card_link_traffic_values

    assert _format_focus_card_link_traffic_values(result) == "[1, 2, 2, 4]"


def test_parallel_simulation_matches_single_worker_result():
    topology = MultiRailTopology(MultiRailTopologyConfig(M=2, N=4, X=2))
    topology.build_graph()

    single_worker = simulate_domain_size(
        topology,
        domain_size=8,
        mode=RoutingMode.SOURCE_NODE_JUMP,
        focus_card="node0-card0",
        workers=1,
    )
    two_workers = simulate_domain_size(
        topology,
        domain_size=8,
        mode=RoutingMode.SOURCE_NODE_JUMP,
        focus_card="node0-card0",
        workers=2,
    )

    assert two_workers.link_traffic == pytest.approx(single_worker.link_traffic)
    assert two_workers.focus_card_bandwidth_efficiency == pytest.approx(
        single_worker.focus_card_bandwidth_efficiency
    )


@pytest.mark.parametrize(
    ("topology", "mode", "domain_size"),
    [
        (
            MultiRailTopology(MultiRailTopologyConfig(M=2, N=4, X=2)),
            RoutingMode.SOURCE_NODE_JUMP,
            8,
        ),
        (
            MultiRailTopology(MultiRailTopologyConfig(M=2, N=4, X=2)),
            RoutingMode.DESTINATION_NODE_JUMP,
            8,
        ),
        (
            MultiRailTopology(
                MultiRailTopologyConfig(
                    M=4,
                    N=4,
                    X=2,
                    topology_type="2d-fm-clos",
                    fm2d_domain_size=2,
                )
            ),
            RoutingMode.SOURCE_2DFM_JUMP,
            8,
        ),
        (
            MultiRailTopology(
                MultiRailTopologyConfig(
                    M=4,
                    N=4,
                    X=2,
                    topology_type="2d-fm-clos",
                    fm2d_domain_size=2,
                )
            ),
            RoutingMode.DESTINATION_2DFM_JUMP,
            8,
        ),
    ],
)
def test_focus_only_simulation_matches_full_focus_link_traffic(topology, mode, domain_size):
    topology.build_graph()

    full = simulate_domain_size(
        topology,
        domain_size=domain_size,
        mode=mode,
        focus_card="node0-card0",
        workers=1,
    )
    focus_only = simulate_domain_size(
        topology,
        domain_size=domain_size,
        mode=mode,
        focus_card="node0-card0",
        focus_only=True,
    )

    assert focus_only.focus_card_adjacent_link_traffic == pytest.approx(
        full.focus_card_adjacent_link_traffic
    )
    assert focus_only.focus_card_bandwidth_efficiency == pytest.approx(
        full.focus_card_bandwidth_efficiency
    )


def test_focus_only_simulation_matches_full_result_for_every_focus_card_in_2d():
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
    focus_cards = [f"node{node_index}-card{card_index}" for node_index in range(4) for card_index in range(4)]

    for mode in (RoutingMode.SOURCE_2DFM_JUMP, RoutingMode.DESTINATION_2DFM_JUMP):
        for focus_card in focus_cards:
            full = simulate_domain_size(
                topology,
                domain_size=8,
                mode=mode,
                focus_card=focus_card,
                workers=1,
            )
            focus_only = simulate_domain_size(
                topology,
                domain_size=8,
                mode=mode,
                focus_card=focus_card,
                focus_only=True,
            )

            assert focus_only.focus_card_adjacent_link_traffic == pytest.approx(
                full.focus_card_adjacent_link_traffic
            )


def test_focus_card_link_traffic_array_puts_intra_before_2dfm_and_switches():
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
    result = simulate_domain_size(
        topology,
        domain_size=4,
        mode=RoutingMode.SOURCE_2DFM_JUMP,
        focus_card="node0-card0",
    )

    from multirail_topology.simulation import _ordered_focus_card_links

    assert _ordered_focus_card_links(result) == [
        ("node0-card0", "node0-card1"),
        ("node0-card0", "node0-card2"),
        ("node0-card0", "node0-card3"),
        ("node0-card0", "node1-card0"),
        ("node0-card0", "switch0"),
    ]


def test_export_all_link_traffic_report_writes_all_links_separately():
    output_path = Path("test_outputs/all_link_traffic_test.txt")

    export_all_link_traffic_report(_topology(), output_path, domain_sizes=[4])

    report = output_path.read_text(encoding="utf-8")
    assert "domain_size: 4" in report
    assert "node0-card0 -> node0-card1 | traffic=1.000000 | load=0.100000" in report
    assert "node0-card1 -> node0-card0 | traffic=1.000000 | load=0.100000" in report
    assert "focus_card_bandwidth_efficiency" not in report


def _sparse_sim_topology() -> MultiRailTopology:
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            topology_type="sparse-clos",
            sparse_clos=SparseClosConfig(
                bst_r=2,
                bst_k=2,
                switch_port_num=16,
                cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
            ),
            intra_bandwidth=50.0,
            switch_bandwidth=100.0,
        )
    )
    topology.build_graph()
    return topology


def test_sparse_clos_default_domain_sizes_use_cluster_divisors_then_multiples():
    results = simulate_domain_sizes(
        _sparse_sim_topology(),
        mode=RoutingMode.SHORTEST_PATH,
        focus_card="node0-card0",
        workers=1,
    )

    assert [result.domain_size for result in results] == [2, 4, 8, 16, 24]


def test_sparse_clos_simulation_accepts_non_dividing_cluster_multiple_domain_size():
    result = simulate_domain_size(
        _sparse_sim_topology(),
        domain_size=16,
        mode=RoutingMode.SHORTEST_PATH,
        focus_card="node0-card0",
        focus_only=True,
    )

    assert result.focus_card_sent_flows == 15
    assert result.focus_card_adjacent_link_traffic[("node0-card0", "switch0")] > 0


def test_sparse_clos_focus_only_shortest_path_uses_focus_source_pairs_only(monkeypatch):
    topology = _sparse_sim_topology()
    full = simulate_domain_size(
        topology,
        domain_size=16,
        mode=RoutingMode.SHORTEST_PATH,
        focus_card="node0-card0",
        workers=1,
    )
    call_count = 0
    original_route_between_cards = simulation_module.route_between_cards

    def counted_route_between_cards(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_route_between_cards(*args, **kwargs)

    monkeypatch.setattr(simulation_module, "route_between_cards", counted_route_between_cards)

    focus_only = simulate_domain_size(
        topology,
        domain_size=16,
        mode=RoutingMode.SHORTEST_PATH,
        focus_card="node0-card0",
        focus_only=True,
    )

    assert focus_only.focus_card_adjacent_link_traffic == pytest.approx(full.focus_card_adjacent_link_traffic)
    assert focus_only.focus_card_bandwidth_efficiency == pytest.approx(full.focus_card_bandwidth_efficiency)
    assert call_count == 15


def test_sparse_clos_simulation_report_includes_bst_metadata(tmp_path):
    output_path = tmp_path / "sparse_report.txt"

    export_simulation_report(
        _sparse_sim_topology(),
        output_path,
        domain_sizes=[8],
        mode=RoutingMode.SHORTEST_PATH,
        focus_card="node0-card0",
        workers=1,
    )

    report = output_path.read_text(encoding="utf-8")
    assert "bst_v: 3" in report
    assert "bst_r: 2" in report
    assert "bst_b: 3" in report
    assert "bst_k: 2" in report
    assert "bst_lambda: 1" in report
    assert "cluster_size: 8" in report
    assert "total_cards: 24" in report


def test_sparse_clos_detour_report_includes_route_types(tmp_path):
    output_path = tmp_path / "sparse_detour_report.txt"

    export_simulation_report(
        _sparse_sim_topology(),
        output_path,
        domain_sizes=[4, 16, 24],
        mode=RoutingMode.DETOUR_ROUTING,
        focus_card="node0-card0",
        workers=1,
    )

    report = output_path.read_text(encoding="utf-8")
    assert "| 通信域 D | efficiency | route_types | focus_card_link_traffic |" in report
    assert "domain_size: 4" in report
    assert "detour_types: card_detour" in report
    assert "domain_size: 16" in report
    assert "detour_types: cluster_detour" in report
    assert "domain_size: 24" in report
    assert "detour_types: none" in report


def test_sparse_clos_detour_falls_back_when_cluster_detour_is_worse():
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            topology_type="sparse-clos",
            sparse_clos=SparseClosConfig(
                bst_r=4,
                bst_k=2,
                switch_port_num=16,
                cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
            ),
            intra_bandwidth=50.0,
            switch_bandwidth=50.0,
        )
    )
    topology.build_graph()

    shortest = simulate_domain_size(
        topology,
        domain_size=32,
        mode=RoutingMode.SHORTEST_PATH,
        focus_card="node0-card0",
        workers=1,
    )
    detour = simulate_domain_size(
        topology,
        domain_size=32,
        mode=RoutingMode.DETOUR_ROUTING,
        focus_card="node0-card0",
        workers=1,
    )

    assert detour.focus_card_bandwidth_efficiency == pytest.approx(
        shortest.focus_card_bandwidth_efficiency
    )
    assert "cluster_detour" not in detour.route_type_counts
