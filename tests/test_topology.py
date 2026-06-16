from pathlib import Path
from math import hypot, isclose

import pytest

from multirail_topology import (
    MultiRailTopology,
    MultiRailTopologyConfig,
    TopologyType,
    export_topology_html,
)
from multirail_topology.sparse_clos import ClusterInternalMode, SparseClosConfig
from multirail_topology.visualize import build_positions
from multirail_topology.visualize import create_topology_figure
from multirail_topology.visualize import _omit_edge_in_simplified_view


def test_config_rejects_switch_count_greater_than_cards():
    with pytest.raises(ValueError, match="X cannot exceed N"):
        MultiRailTopologyConfig(M=2, N=2, X=3)


def test_config_rejects_non_positive_topology_values():
    with pytest.raises(ValueError, match="M must be a positive integer"):
        MultiRailTopologyConfig(M=0, N=4, X=2)


def test_config_rejects_non_positive_bandwidth_values():
    with pytest.raises(ValueError, match="switch_bandwidth must be a positive number"):
        MultiRailTopologyConfig(M=2, N=4, X=2, switch_bandwidth=0)


def test_config_accepts_positive_values():
    config = MultiRailTopologyConfig(
        M=2,
        N=4,
        X=2,
        intra_bandwidth=200.0,
        switch_bandwidth=100.0,
    )

    assert config.M == 2
    assert config.N == 4
    assert config.X == 2


def test_topology_counts_for_small_graph():
    config = MultiRailTopologyConfig(M=2, N=4, X=2)
    topology = MultiRailTopology(config)
    graph = topology.build_graph()

    assert topology.summary() == {
        "compute_nodes": 2,
        "card_nodes": 8,
        "switch_nodes": 2,
        "intra_links": 12,
        "switch_links": 8,
        "fm2d_links": 0,
        "total_nodes": 12,
        "total_edges": 20,
    }
    assert graph.nodes["node0-card0"]["switch_group"] == 0
    assert graph.nodes["node0-card3"]["switch_group"] == 1


def test_topology_groups_cards_evenly_when_not_divisible():
    config = MultiRailTopologyConfig(M=1, N=5, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    assert topology.card_groups_for_node(0) == [[0, 1, 2], [3, 4]]


def test_topology_edges_have_bandwidth_and_type():
    config = MultiRailTopologyConfig(
        M=1,
        N=3,
        X=1,
        intra_bandwidth=400.0,
        switch_bandwidth=100.0,
    )
    topology = MultiRailTopology(config)
    graph = topology.build_graph()

    assert graph.edges["node0-card0", "node0-card1"]["bandwidth"] == 400.0
    assert graph.edges["node0-card0", "node0-card1"]["link_type"] == "intra"
    assert graph.edges["node0-card2", "switch0"]["bandwidth"] == 100.0
    assert graph.edges["node0-card2", "switch0"]["link_type"] == "switch"


def test_cards_in_each_compute_node_are_laid_out_as_a_ring():
    config = MultiRailTopologyConfig(M=1, N=6, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    positions = build_positions(topology)
    compute_x, compute_y = positions["node0"]
    distances = []

    for card_index in range(config.N):
        card_x, card_y = positions[f"node0-card{card_index}"]
        distances.append(((card_x - compute_x) ** 2 + (card_y - compute_y) ** 2) ** 0.5)

    assert all(isclose(distance, distances[0], rel_tol=0.001) for distance in distances)
    assert len({positions[f"node0-card{card_index}"][1] for card_index in range(config.N)}) > 2


def test_visualization_separates_upper_and_lower_node_rows_for_large_card_count():
    config = MultiRailTopologyConfig(M=16, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    positions = build_positions(topology)
    upper_y = positions["node0"][1]
    lower_y = positions["node1"][1]
    card_radius = abs(positions["node0"][1] - positions["node0-card0"][1])

    assert abs(upper_y - lower_y) > card_radius * 2.5


def test_export_topology_html_creates_interactive_file():
    config = MultiRailTopologyConfig(M=2, N=2, X=1)
    topology = MultiRailTopology(config)
    output_path = Path("test_outputs/topology_test.html")

    export_topology_html(topology, output_path)

    html = output_path.read_text(encoding="utf-8")
    assert "Plotly.newPlot" in html
    assert "Node 0" in html
    assert "Switch 0" in html


def test_visualization_title_explains_m_n_x_parameters():
    config = MultiRailTopologyConfig(M=16, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    figure = create_topology_figure(topology)

    assert "M=16 nodes" in figure.layout.title.text
    assert "N=8 cards/node" in figure.layout.title.text
    assert "X=2 switches" in figure.layout.title.text


def test_visualization_omits_compute_markers_and_uses_external_node_labels():
    config = MultiRailTopologyConfig(M=16, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}

    assert "Compute node" not in traces
    assert traces["Network card"].marker.size <= 8
    assert traces["Compute label"].mode == "text"


def test_visualization_places_card_numbers_around_node_ring():
    config = MultiRailTopologyConfig(M=1, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    positions = build_positions(topology)
    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}
    card_trace = traces["Network card"]
    label_trace = traces["Card label"]
    compute_x, compute_y = positions["node0"]

    assert card_trace.mode == "markers"
    assert all(text is None for text in card_trace.text)
    assert label_trace.mode == "text"
    assert list(label_trace.text) == [str(index) for index in range(config.N)]

    card0_distance = hypot(
        positions["node0-card0"][0] - compute_x,
        positions["node0-card0"][1] - compute_y,
    )
    label0_distance = hypot(label_trace.x[0] - compute_x, label_trace.y[0] - compute_y)
    assert label0_distance > card0_distance * 1.25


def test_visualization_places_compute_labels_well_outside_card_ring():
    config = MultiRailTopologyConfig(M=16, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    positions = build_positions(topology)
    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}
    label_y = traces["Compute label"].y[0]
    compute_y = positions["node0"][1]
    card_radius = abs(positions["node0-card0"][1] - compute_y)

    assert abs(label_y - compute_y) > card_radius * 1.8


def test_simplified_intra_fm_draws_full_mesh_edges():
    config = MultiRailTopologyConfig(M=1, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    graph = topology.graph

    assert not _omit_edge_in_simplified_view(
        topology,
        "node0-card0",
        "node0-card1",
        graph.edges["node0-card0", "node0-card1"],
    )
    assert _omit_edge_in_simplified_view(
        topology,
        "node0-card0",
        "switch0",
        graph.edges["node0-card0", "switch0"],
    ) is False
    assert not _omit_edge_in_simplified_view(
        topology,
        "node0-card2",
        "node0-card5",
        graph.edges["node0-card2", "node0-card5"],
    )


def test_simplified_2d_fm_is_not_drawn_in_main_graph():
    config = MultiRailTopologyConfig(
        M=4,
        N=4,
        X=2,
        topology_type=TopologyType.TWO_D_FM_CLOS,
        fm2d_domain_size=2,
    )
    topology = MultiRailTopology(config)
    topology.build_graph()
    graph = topology.graph

    assert _omit_edge_in_simplified_view(
        topology,
        "node0-card0",
        "node1-card0",
        graph.edges["node0-card0", "node1-card0"],
    )
    assert _omit_edge_in_simplified_view(
        topology,
        "node0-card1",
        "node1-card1",
        graph.edges["node0-card1", "node1-card1"],
    )


def test_simplified_switch_edges_show_one_complete_multirail_example_node():
    config = MultiRailTopologyConfig(M=3, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()
    graph = topology.graph

    for card_index in range(config.N):
        card_id = f"node1-card{card_index}"
        switch_id = f"switch{graph.nodes[card_id]['switch_group']}"
        assert not _omit_edge_in_simplified_view(
            topology,
            card_id,
            switch_id,
            graph.edges[card_id, switch_id],
        )

    assert _omit_edge_in_simplified_view(
        topology,
        "node0-card1",
        "switch0",
        graph.edges["node0-card1", "switch0"],
    )


def test_visualization_colors_switches_and_highlights_multirail_example():
    config = MultiRailTopologyConfig(M=3, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}
    switch_shapes = [shape for shape in figure.layout.shapes if shape.name == "switch-rect"]

    assert len({shape.fillcolor for shape in switch_shapes}) == config.X
    assert traces["Card-switch rail 0"].line.color != traces["Card-switch rail 1"].line.color
    assert traces["Highlighted multirail example 0"].line.width > traces["Card-switch rail 0"].line.width
    assert traces["Highlighted multirail example 1"].line.width > traces["Card-switch rail 1"].line.width
    assert traces["Highlighted multirail example 0"].line.color == traces["Card-switch rail 0"].line.color
    assert traces["Highlighted multirail example 1"].line.color == traces["Card-switch rail 1"].line.color
    card_colors = list(traces["Network card"].marker.color)
    exemplar_card_colors = card_colors[8:16]
    assert exemplar_card_colors[:4] == [traces["Card-switch rail 0"].line.color] * 4
    assert exemplar_card_colors[4:] == [traces["Card-switch rail 1"].line.color] * 4


def test_main_topology_is_shifted_up_from_switch_axis():
    config = MultiRailTopologyConfig(M=3, N=8, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    positions = build_positions(topology)

    assert positions["switch0"][1] > 0.5
    assert positions["node0"][1] > abs(positions["node1"][1])


def test_2d_visualization_adds_top_left_schematic_for_same_index_fm():
    config = MultiRailTopologyConfig(
        M=8,
        N=8,
        X=2,
        topology_type=TopologyType.TWO_D_FM_CLOS,
        fm2d_domain_size=8,
    )
    topology = MultiRailTopology(config)
    topology.build_graph()

    positions = build_positions(topology)
    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}
    card_x_values = [x for node_id, (x, _) in positions.items() if "-card" in node_id]
    card_y_values = [y for node_id, (_, y) in positions.items() if "-card" in node_id]

    assert "2D FM schematic" in traces
    assert "2D FM schematic nodes" in traces
    assert "2D FM schematic labels" in traces
    assert "2D FM schematic title" in traces
    assert len(traces["2D FM schematic labels"].text) == config.fm2d_domain_size
    assert traces["2D FM schematic labels"].mode == "text"
    assert "第二维FullMesh连接，一维同号卡互连，规模是8" in traces["2D FM schematic title"].text[0]
    assert abs(min(traces["2D FM schematic labels"].x) - min(card_x_values)) < 0.01
    assert min(traces["2D FM schematic nodes"].x) >= min(card_x_values)
    assert min(traces["2D FM schematic nodes"].y) > max(card_y_values) + 4.0
    assert min(traces["2D FM schematic title"].y) > max(traces["2D FM schematic labels"].y) + 0.4


def test_visualization_uses_rectangular_switches_with_text_inside_and_solid_lines():
    config = MultiRailTopologyConfig(M=2, N=4, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}
    switch_shapes = [shape for shape in figure.layout.shapes if shape.name == "switch-rect"]

    assert traces["Switch"].mode == "text"
    assert traces["Switch"].text == ("Switch 0", "Switch 1")
    assert len(switch_shapes) == config.X
    assert all((shape.x1 - shape.x0) > (shape.y1 - shape.y0) * 2 for shape in switch_shapes)
    assert abs(traces["Switch"].x[1] - traces["Switch"].x[0]) > 3.0
    assert traces["Card-switch rail 0"].line.dash == "solid"
    assert traces["Intra-node full mesh"].line.dash == "solid"
    assert traces["Card-switch rail 0"].line.width <= 1.0


def test_2d_topology_defaults_domain_size_to_card_count():
    config = MultiRailTopologyConfig(M=4, N=4, X=2, topology_type=TopologyType.TWO_D_FM_CLOS)

    assert config.fm2d_domain_size == 4


def test_2d_topology_adds_same_index_card_full_mesh_links_inside_domains():
    config = MultiRailTopologyConfig(
        M=4,
        N=4,
        X=2,
        topology_type=TopologyType.TWO_D_FM_CLOS,
        fm2d_domain_size=2,
        fm2d_bandwidth=300.0,
    )
    topology = MultiRailTopology(config)
    graph = topology.build_graph()

    assert graph.edges["node0-card1", "node1-card1"]["link_type"] == "fm2d"
    assert graph.edges["node0-card1", "node1-card1"]["bandwidth"] == 300.0
    assert graph.edges["node2-card3", "node3-card3"]["link_type"] == "fm2d"
    assert topology.summary()["fm2d_links"] == 8
    assert graph.nodes["node3-card2"]["fm2d_domain"] == 1


def test_sparse_clos_topology_derives_cluster_dimensions_and_switch_blocks():
    config = MultiRailTopologyConfig(
        topology_type=TopologyType.SPARSE_CLOS,
        sparse_clos=SparseClosConfig(
            bst_r=2,
            bst_k=2,
            switch_port_num=16,
            cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
        ),
    )
    topology = MultiRailTopology(config)
    graph = topology.build_graph()

    assert (config.M, config.N, config.X) == (3, 8, 3)
    assert topology.summary() == {
        "compute_nodes": 3,
        "card_nodes": 24,
        "switch_nodes": 3,
        "intra_links": 84,
        "switch_links": 48,
        "fm2d_links": 0,
        "total_nodes": 30,
        "total_edges": 132,
    }
    assert graph.nodes["switch0"]["cluster_block"] == (0, 1)
    assert graph.nodes["switch1"]["cluster_block"] == (0, 2)
    assert graph.nodes["node0-card0"]["switch_groups"] == (0, 1)
    assert graph.has_edge("node0-card0", "switch0")
    assert graph.has_edge("node0-card0", "switch1")
    assert not graph.has_edge("node0-card0", "switch2")


def test_sparse_clos_switch_only_mode_omits_cluster_internal_fullmesh():
    config = MultiRailTopologyConfig(
        topology_type=TopologyType.SPARSE_CLOS,
        sparse_clos=SparseClosConfig(
            bst_r=2,
            bst_k=2,
            switch_port_num=16,
            cluster_internal_mode=ClusterInternalMode.SWITCH_ONLY,
        ),
    )
    topology = MultiRailTopology(config)
    graph = topology.build_graph()

    assert topology.summary()["intra_links"] == 0
    assert topology.summary()["switch_links"] == 48
    assert not graph.has_edge("node0-card0", "node0-card1")


def test_sparse_clos_visualization_uses_cluster_and_representative_cluster_views():
    config = MultiRailTopologyConfig(
        topology_type=TopologyType.SPARSE_CLOS,
        sparse_clos=SparseClosConfig(
            bst_r=2,
            bst_k=2,
            switch_port_num=16,
            cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
        ),
    )
    topology = MultiRailTopology(config)
    topology.build_graph()

    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}

    assert "SparseClos cluster view" in figure.layout.title.text
    assert "SparseClos clusters" in traces
    assert "SparseClos switches" in traces
    assert "SparseClos cluster-switch membership" in traces
    assert "SparseClos representative cluster" in traces


def test_sparse_clos_representative_cluster_shows_full_fullmesh_cluster_and_switch_example():
    config = MultiRailTopologyConfig(
        topology_type=TopologyType.SPARSE_CLOS,
        sparse_clos=SparseClosConfig(
            bst_r=8,
            bst_k=2,
            switch_port_num=128,
            cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
        ),
    )
    topology = MultiRailTopology(config)
    topology.build_graph()

    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}
    representative_cards = traces["SparseClos representative cluster"]
    fullmesh_trace = traces["SparseClos representative cluster fullmesh"]

    assert len(representative_cards.x) == 64
    assert set(representative_cards.text) == {str(card_index) for card_index in range(64)}
    assert list(fullmesh_trace.x).count(None) == 8 * 28
    switch_fanout_trace = traces["SparseClos representative switch example fanout"]
    assert "SparseClos representative switch example" in traces
    assert list(switch_fanout_trace.x).count(None) == 64


def test_sparse_clos_representative_fullmesh_edges_are_curved_for_visibility():
    config = MultiRailTopologyConfig(
        topology_type=TopologyType.SPARSE_CLOS,
        sparse_clos=SparseClosConfig(
            bst_r=8,
            bst_k=2,
            switch_port_num=128,
            cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
        ),
    )
    topology = MultiRailTopology(config)
    topology.build_graph()

    figure = create_topology_figure(topology)
    traces = {trace.name: trace for trace in figure.data}
    fullmesh_trace = traces["SparseClos representative cluster fullmesh"]
    segments = []
    current_segment = []
    for x_value, y_value in zip(fullmesh_trace.x, fullmesh_trace.y):
        if x_value is None:
            if current_segment:
                segments.append(current_segment)
                current_segment = []
            continue
        current_segment.append((x_value, y_value))

    assert segments
    assert all(len(segment) > 2 for segment in segments)
    assert any(len({round(point[1], 6) for point in segment}) > 2 for segment in segments)
