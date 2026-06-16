from pathlib import Path

import networkx as nx

from multirail_topology import MultiRailTopology, MultiRailTopologyConfig, TopologyType
from multirail_topology.routing import (
    RouteResult,
    RoutingMode,
    export_all_routes,
    export_representative_routes,
    route_between_cards,
)
from multirail_topology.sparse_clos import ClusterInternalMode, ClusterLayout, SparseClosConfig


def _topology() -> MultiRailTopology:
    topology = MultiRailTopology(MultiRailTopologyConfig(M=2, N=4, X=2))
    topology.build_graph()
    return topology


def test_routes_inside_same_compute_node_directly():
    route = route_between_cards(_topology(), "node0-card0", "node0-card3")

    assert route.route_type == "intra_node_direct"
    assert route.paths == [["node0-card0", "node0-card3"]]


def test_route_result_defaults_to_equal_path_weights():
    route = RouteResult(
        "node0-card0",
        "node1-card0",
        "test",
        [
            ["node0-card0", "switch0", "node1-card0"],
            ["node0-card0", "switch1", "node1-card0"],
        ],
    )

    assert route.weighted_paths() == [
        (["node0-card0", "switch0", "node1-card0"], 0.5),
        (["node0-card0", "switch1", "node1-card0"], 0.5),
    ]


def test_route_result_uses_explicit_path_weights():
    route = RouteResult(
        "node0-card0",
        "node1-card0",
        "test",
        [
            ["node0-card0", "switch0", "node1-card0"],
            ["node0-card0", "switch1", "node1-card0"],
        ],
        path_weights=[0.25, 0.75],
    )

    assert route.weighted_paths() == [
        (["node0-card0", "switch0", "node1-card0"], 0.25),
        (["node0-card0", "switch1", "node1-card0"], 0.75),
    ]


def test_routes_between_cards_on_same_switch_directly_through_switch():
    route = route_between_cards(_topology(), "node0-card0", "node1-card1")

    assert route.route_type == "same_switch_direct"
    assert route.paths == [["node0-card0", "switch0", "node1-card1"]]


def test_source_node_jump_uses_all_source_cards_connected_to_destination_switch():
    route = route_between_cards(
        _topology(),
        "node0-card0",
        "node1-card3",
        mode=RoutingMode.SOURCE_NODE_JUMP,
    )

    assert route.route_type == "source_node_jump"
    assert route.paths == [
        ["node0-card0", "node0-card2", "switch1", "node1-card3"],
        ["node0-card0", "node0-card3", "switch1", "node1-card3"],
    ]


def test_destination_node_jump_uses_destination_node_cards_on_source_switch():
    route = route_between_cards(
        _topology(),
        "node0-card0",
        "node1-card3",
        mode=RoutingMode.DESTINATION_NODE_JUMP,
    )

    assert route.route_type == "destination_node_jump"
    assert route.paths == [
        ["node0-card0", "switch0", "node1-card0", "node1-card3"],
        ["node0-card0", "switch0", "node1-card1", "node1-card3"],
    ]


def test_export_all_routes_writes_every_ordered_card_pair():
    topology = MultiRailTopology(MultiRailTopologyConfig(M=2, N=2, X=1))
    topology.build_graph()
    output_path = Path("test_outputs/routes_test.txt")

    export_all_routes(topology, output_path)

    lines = output_path.read_text(encoding="utf-8").splitlines()
    route_lines = [line for line in lines if line.startswith("node")]
    assert len(route_lines) == 12
    assert any("node0-card0 -> node1-card1" in line for line in route_lines)


def test_export_representative_routes_samples_only_two_domains():
    topology = MultiRailTopology(MultiRailTopologyConfig(M=4, N=4, X=2))
    topology.build_graph()
    output_path = Path("test_outputs/routes_sample_test.txt")

    export_representative_routes(topology, output_path)

    lines = output_path.read_text(encoding="utf-8").splitlines()
    route_lines = [line for line in lines if line.startswith("node")]
    assert len(route_lines) == 8 * 7
    assert any("route_scope: representative" in line for line in lines)
    assert not any(line.startswith("node2-card") for line in route_lines)


def _topology_2d() -> MultiRailTopology:
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            M=4,
            N=4,
            X=2,
            topology_type=TopologyType.TWO_D_FM_CLOS,
            fm2d_domain_size=2,
        )
    )
    topology.build_graph()
    return topology


def test_2d_routes_between_cards_in_same_fm2d_domain_via_same_index_card():
    route = route_between_cards(
        _topology_2d(),
        "node0-card0",
        "node1-card3",
        mode=RoutingMode.SOURCE_2DFM_JUMP,
    )

    assert route.route_type == "same_2dfm_domain"
    assert route.paths == [["node0-card0", "node0-card3", "node1-card3"]]


def test_2d_routes_between_same_index_cards_in_same_fm2d_domain_directly():
    route = route_between_cards(
        _topology_2d(),
        "node0-card0",
        "node1-card0",
        mode=RoutingMode.SOURCE_2DFM_JUMP,
    )

    assert route.route_type == "same_2dfm_domain"
    assert route.paths == [["node0-card0", "node1-card0"]]


def test_2d_source_domain_jump_uses_source_domain_cards_on_destination_switch():
    route = route_between_cards(
        _topology_2d(),
        "node0-card0",
        "node2-card3",
        mode=RoutingMode.SOURCE_2DFM_JUMP,
    )

    assert route.route_type == "source_2dfm_jump"
    assert route.paths == [
        ["node0-card0", "node0-card2", "switch1", "node2-card3"],
        ["node0-card0", "node0-card3", "switch1", "node2-card3"],
        ["node0-card0", "node0-card2", "node1-card2", "switch1", "node2-card3"],
        ["node0-card0", "node0-card3", "node1-card3", "switch1", "node2-card3"],
    ]


def test_2d_destination_domain_jump_can_return_multiple_equal_paths():
    route = route_between_cards(
        _topology_2d(),
        "node0-card0",
        "node2-card3",
        mode=RoutingMode.DESTINATION_2DFM_JUMP,
    )

    assert route.route_type == "destination_2dfm_jump"
    assert route.paths == [
        ["node0-card0", "switch0", "node2-card0", "node2-card3"],
        ["node0-card0", "switch0", "node2-card1", "node2-card3"],
        ["node0-card0", "switch0", "node3-card0", "node3-card3", "node2-card3"],
        ["node0-card0", "switch0", "node3-card1", "node3-card3", "node2-card3"],
    ]


def _sparse_topology(switch_port_num: int = 16) -> MultiRailTopology:
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            topology_type=TopologyType.SPARSE_CLOS,
            sparse_clos=SparseClosConfig(
                bst_r=2,
                bst_k=2,
                switch_port_num=switch_port_num,
                cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
            ),
        )
    )
    topology.build_graph()
    return topology


def _same_index_sparse_topology() -> MultiRailTopology:
    topology = MultiRailTopology(
        MultiRailTopologyConfig(
            topology_type=TopologyType.SPARSE_CLOS,
            sparse_clos=SparseClosConfig(
                bst_r=7,
                bst_k=2,
                switch_port_num=16,
                cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
                cluster_layout=ClusterLayout.SAME_INDEX_ACROSS_NODES,
            ),
        )
    )
    topology.build_graph()
    return topology


def test_sparse_clos_shortest_path_uses_shared_switch_between_clusters():
    route = route_between_cards(
        _sparse_topology(),
        "node0-card0",
        "node2-card0",
        mode=RoutingMode.SHORTEST_PATH,
    )

    assert route.route_type == "shortest_path"
    assert route.paths == [["node0-card0", "switch1", "node2-card0"]]


def test_sparse_clos_shortest_path_returns_all_equal_paths_inside_cluster_without_direct_edge():
    route = route_between_cards(
        _sparse_topology(switch_port_num=32),
        "node0-card0",
        "node0-card8",
        mode=RoutingMode.SHORTEST_PATH,
    )

    assert route.route_type == "shortest_path"
    assert route.paths == [
        ["node0-card0", "switch0", "node0-card8"],
        ["node0-card0", "switch1", "node0-card8"],
    ]


def test_sparse_clos_shortest_path_uses_structural_route_without_networkx(monkeypatch):
    def fail_all_shortest_paths(*args, **kwargs):
        raise AssertionError("SparseClos shortest path should use structural routing")

    monkeypatch.setattr(nx, "all_shortest_paths", fail_all_shortest_paths)

    route = route_between_cards(
        _sparse_topology(switch_port_num=32),
        "node0-card0",
        "node0-card8",
        mode=RoutingMode.SHORTEST_PATH,
    )

    assert route.paths == [
        ["node0-card0", "switch0", "node0-card8"],
        ["node0-card0", "switch1", "node0-card8"],
    ]


def test_sparse_clos_detour_uses_card_detour_for_small_domains():
    route = route_between_cards(
        _sparse_topology(),
        "node0-card0",
        "node0-card1",
        mode=RoutingMode.DETOUR_ROUTING,
        domain_size=4,
    )

    assert route.route_type == "card_detour"
    assert ["node0-card0", "node0-card1"] in route.paths
    assert ["node0-card0", "node0-card2", "node0-card1"] in route.paths
    assert ["node0-card0", "switch0", "node0-card1"] in route.paths
    assert sum(weight for _, weight in route.weighted_paths()) == 1.0


def test_sparse_clos_detour_uses_cluster_detour_above_cluster_size():
    route = route_between_cards(
        _sparse_topology(),
        "node0-card0",
        "node1-card0",
        mode=RoutingMode.DETOUR_ROUTING,
        domain_size=16,
    )

    assert route.route_type == "cluster_detour"
    assert ["node0-card0", "switch0", "node1-card0"] in route.paths
    assert ["node0-card0", "switch1", "node2-card2", "switch2", "node1-card0"] in route.paths


def test_sparse_clos_detour_keeps_full_all2all_on_shortest_path():
    route = route_between_cards(
        _sparse_topology(),
        "node0-card0",
        "node1-card0",
        mode=RoutingMode.DETOUR_ROUTING,
        domain_size=24,
    )

    assert route.route_type == "shortest_path"
    assert route.paths == [["node0-card0", "switch0", "node1-card0"]]


def test_sparse_clos_same_index_layout_shortest_path_uses_physical_fullmesh():
    route = route_between_cards(
        _same_index_sparse_topology(),
        "node0-card0",
        "node0-card5",
        mode=RoutingMode.SHORTEST_PATH,
    )

    assert route.route_type == "shortest_path"
    assert route.paths == [["node0-card0", "node0-card5"]]


def test_sparse_clos_same_index_layout_detour_skips_cluster_detour_above_8p():
    route = route_between_cards(
        _same_index_sparse_topology(),
        "node0-card0",
        "node1-card1",
        mode=RoutingMode.DETOUR_ROUTING,
        domain_size=16,
    )

    assert route.route_type == "shortest_path"
    assert all(len(path) <= 3 for path in route.paths)
