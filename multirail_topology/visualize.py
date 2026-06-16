from __future__ import annotations

from itertools import combinations
from math import cos, pi, sin
from pathlib import Path

import plotly.graph_objects as go

from .config import TopologyType, VisualizationDetail
from .sparse_clos import ClusterInternalMode, ClusterLayout, derive_bst_parameters
from .topology import MultiRailTopology


def build_positions(topology: MultiRailTopology) -> dict[str, tuple[float, float]]:
    """Create a stable layout with cards arranged as a ring inside each node."""

    if not topology._built:
        topology.build_graph()

    config = topology.config
    positions: dict[str, tuple[float, float]] = {}
    ring_radius = max(1.2, config.N * 0.18)
    node_spacing = max(5.2, ring_radius * 3.9)
    row_y = max(5.4, ring_radius * 4.1)
    main_y_shift = max(1.0, ring_radius * 0.8)
    switch_spacing = max(3.6, config.N * 0.6)

    for node_index in range(config.M):
        x_origin = node_index * node_spacing
        y_origin = (row_y if node_index % 2 == 0 else -row_y) + main_y_shift
        positions[f"node{node_index}"] = (x_origin, y_origin)

        for card_index in range(config.N):
            angle = (2 * pi * card_index / config.N) - (pi / 2)
            positions[f"node{node_index}-card{card_index}"] = (
                x_origin + ring_radius * cos(angle),
                y_origin + ring_radius * sin(angle),
            )

    total_width = max((config.M - 1) * node_spacing, config.X * switch_spacing)
    switch_offset = (config.X - 1) * switch_spacing / 2
    switch_center = total_width / 2

    for switch_index in range(config.X):
        positions[f"switch{switch_index}"] = (
            switch_center + switch_index * switch_spacing - switch_offset,
            main_y_shift,
        )

    return positions


def create_topology_figure(topology: MultiRailTopology) -> go.Figure:
    if not topology._built:
        topology.build_graph()

    if topology.config.topology_type == TopologyType.SPARSE_CLOS:
        return _create_sparse_clos_figure(topology)

    graph = topology.graph
    positions = build_positions(topology)
    traces = [
        _edge_trace(topology, positions, "intra"),
        _edge_trace(topology, positions, "fm2d"),
        *_switch_edge_traces(topology, positions),
        _node_trace(topology, positions, "card"),
        _card_label_trace(topology, positions),
        _node_trace(topology, positions, "switch"),
        _compute_label_trace(topology, positions),
    ]
    traces.extend(_fm2d_schematic_traces(topology, positions))

    title = (
        f"Multi-Rail Topology: {topology.config.topology_type.value}, "
        f"M={topology.config.M} nodes, "
        f"N={topology.config.N} cards/node, "
        f"X={topology.config.X} switches"
    )
    figure = go.Figure(data=[trace for trace in traces if trace is not None])
    figure.update_layout(
        title=title,
        showlegend=True,
        hovermode="closest",
        margin={"b": 20, "l": 20, "r": 20, "t": 60},
        plot_bgcolor="#ffffff",
        font={"size": 10},
        shapes=_switch_shapes(topology, positions),
        xaxis={"showgrid": False, "zeroline": False, "visible": False},
        yaxis={"showgrid": False, "zeroline": False, "visible": False},
    )
    figure.update_yaxes(scaleanchor="x", scaleratio=1)

    # Keep graph referenced for static analyzers and as a clear visualization input.
    assert graph.number_of_nodes() > 0
    return figure


def _create_sparse_clos_figure(topology: MultiRailTopology) -> go.Figure:
    config = topology.config
    sparse_config = config.sparse_clos
    if sparse_config is None:
        raise ValueError("sparse_clos config is required for sparse-clos visualization")
    sparse_params = derive_bst_parameters(sparse_config)
    cluster_count = sparse_params["bst_v"]
    cluster_size = sparse_params["cluster_size"]
    representative_card_count = sparse_params["cards_per_physical_node"]
    same_index_layout = sparse_config.cluster_layout == ClusterLayout.SAME_INDEX_ACROSS_NODES

    cluster_positions = {
        cluster_index: (cluster_index * 3.0, 6.0)
        for cluster_index in range(cluster_count)
    }
    switch_positions = {
        switch_index: (
            (switch_index % max(1, cluster_count)) * 3.0,
            1.8 - (switch_index // max(1, cluster_count)) * 1.0,
        )
        for switch_index in range(config.X)
    }
    representative_origin_x = 0.0
    representative_origin_y = -5.2
    representative_columns = 8
    representative_row_spacing = 1.35
    representative_rows = max(1, (representative_card_count + representative_columns - 1) // representative_columns)
    card_positions = {
        card_index: (
            representative_origin_x + (card_index % representative_columns) * 0.9,
            representative_origin_y - (card_index // representative_columns) * representative_row_spacing,
        )
        for card_index in range(representative_card_count)
    }
    representative_switch_position = (
        representative_origin_x + representative_columns * 0.9 + 1.2,
        representative_origin_y - (representative_rows - 1) * representative_row_spacing * 0.5,
    )

    membership_x: list[float | None] = []
    membership_y: list[float | None] = []
    membership_hover: list[str] = []
    for switch_id, attributes in topology.graph.nodes(data=True):
        if attributes["node_type"] != "switch":
            continue
        switch_index = int(attributes["switch_index"])
        switch_x, switch_y = switch_positions[switch_index]
        for cluster_index in attributes["cluster_block"]:
            cluster_x, cluster_y = cluster_positions[int(cluster_index)]
            membership_x.extend([cluster_x, switch_x, None])
            membership_y.extend([cluster_y, switch_y, None])
            membership_hover.extend(
                [
                    f"cluster: {cluster_index}<br>switch: {switch_index}<br>block: {attributes['cluster_block']}",
                    f"cluster: {cluster_index}<br>switch: {switch_index}<br>block: {attributes['cluster_block']}",
                    "",
                ]
            )

    intra_x: list[float | None] = []
    intra_y: list[float | None] = []
    if sparse_config.cluster_internal_mode == ClusterInternalMode.FULLMESH_PLUS_SWITCH:
        group_step = representative_card_count if same_index_layout else 8
        for group_start in range(0, representative_card_count, group_step):
            group_cards = [
                card_index
                for card_index in range(group_start, min(group_start + group_step, representative_card_count))
            ]
            for left_index, right_index in combinations(group_cards, 2):
                left_x, left_y = card_positions[left_index]
                right_x, right_y = card_positions[right_index]
                card_gap = abs(right_index - left_index)
                curve_offset = 0.12 + card_gap * 0.08
                for curve_x, curve_y in _curved_segment_points(
                    (left_x, left_y),
                    (right_x, right_y),
                    offset=curve_offset,
                ):
                    intra_x.append(curve_x)
                    intra_y.append(curve_y)
                intra_x.append(None)
                intra_y.append(None)
    switch_fanout_x: list[float | None] = []
    switch_fanout_y: list[float | None] = []
    representative_switch_x, representative_switch_y = representative_switch_position
    representative_switch_block = topology.graph.nodes["switch0"]["cluster_block"] if "switch0" in topology.graph else ()
    if same_index_layout:
        fanout_card_indices = [card_index for card_index in representative_switch_block if card_index in card_positions]
    else:
        fanout_card_indices = list(card_positions)
    for card_index in fanout_card_indices:
        card_x, card_y = card_positions[card_index]
        switch_fanout_x.extend([card_x, representative_switch_x, None])
        switch_fanout_y.extend([card_y, representative_switch_y, None])

    traces = [
        go.Scatter(
            x=membership_x,
            y=membership_y,
            mode="lines",
            line={"width": 0.6, "color": "#2f80ed"},
            hoverinfo="text",
            text=membership_hover,
            name="SparseClos cluster-switch membership",
        ),
        go.Scatter(
            x=[position[0] for position in cluster_positions.values()],
            y=[position[1] for position in cluster_positions.values()],
            mode="markers+text",
            text=[f"C{cluster_index}" for cluster_index in cluster_positions],
            textposition="top center",
            marker={"symbol": "square", "size": 14, "color": "#27ae60", "line": {"width": 0.8, "color": "#263238"}},
            hovertext=[
                f"cluster: {cluster_index}<br>cluster size: {cluster_size}<br>ports/card: {sparse_config.bst_r}"
                for cluster_index in cluster_positions
            ],
            hoverinfo="text",
            name="SparseClos clusters",
        ),
        go.Scatter(
            x=[position[0] for position in switch_positions.values()],
            y=[position[1] for position in switch_positions.values()],
            mode="markers",
            marker={"symbol": "square", "size": 7, "color": "#f2c94c", "line": {"width": 0.7, "color": "#263238"}},
            hovertext=[
                f"switch: {switch_index}<br>block: {topology.graph.nodes[f'switch{switch_index}']['cluster_block']}"
                for switch_index in switch_positions
            ],
            hoverinfo="text",
            name="SparseClos switches",
        ),
    ]
    if intra_x:
        traces.append(
            go.Scatter(
                x=intra_x,
                y=intra_y,
                mode="lines",
                line={"width": 0.45, "color": "#7d8790"},
                hoverinfo="skip",
                name="SparseClos representative cluster fullmesh",
            )
        )
    traces.append(
        go.Scatter(
            x=switch_fanout_x,
            y=switch_fanout_y,
            mode="lines",
            line={"width": 0.35, "color": "#2f80ed"},
            hoverinfo="skip",
            name="SparseClos representative switch example fanout",
        )
    )
    traces.append(
        go.Scatter(
            x=[position[0] for position in card_positions.values()],
            y=[position[1] for position in card_positions.values()],
            mode="markers+text",
            text=[str(card_index) for card_index in card_positions],
            textposition="bottom center",
            marker={"symbol": "circle", "size": 8, "color": "#dbeafe", "line": {"width": 0.8, "color": "#1f6feb"}},
            hovertext=[
                _sparse_representative_card_hover(card_index, sparse_config.cluster_layout)
                for card_index in card_positions
            ],
            hoverinfo="text",
            name="SparseClos representative cluster",
        )
    )
    traces.append(
        go.Scatter(
            x=[representative_switch_x],
            y=[representative_switch_y],
            mode="markers+text",
            text=["Switch example"],
            textposition="middle right",
            marker={"symbol": "square", "size": 14, "color": "#f2c94c", "line": {"width": 0.8, "color": "#263238"}},
            hovertext=[f"representative switch example<br>connected cards: {len(fanout_card_indices)}"],
            hoverinfo="text",
            name="SparseClos representative switch example",
        )
    )

    figure = go.Figure(data=traces)
    figure.update_layout(
        title=(
            "SparseClos cluster view and representative cluster, "
            f"v={cluster_count}, r={sparse_config.bst_r}, b={config.X}, "
            f"k={sparse_config.bst_k}, lambda={sparse_config.bst_lambda}, "
            f"cluster_size={cluster_size}, layout={sparse_config.cluster_layout.value}"
        ),
        showlegend=True,
        hovermode="closest",
        margin={"b": 20, "l": 20, "r": 20, "t": 60},
        plot_bgcolor="#ffffff",
        font={"size": 10},
        xaxis={"showgrid": False, "zeroline": False, "visible": False},
        yaxis={"showgrid": False, "zeroline": False, "visible": False},
    )
    figure.update_yaxes(scaleanchor="x", scaleratio=1)
    return figure


def _sparse_representative_card_hover(card_index: int, layout: ClusterLayout) -> str:
    if layout == ClusterLayout.SAME_INDEX_ACROSS_NODES:
        return (
            f"representative physical node card: {card_index}<br>"
            f"cluster: {card_index}<br>layout: {layout.value}"
        )
    return f"representative cluster card: {card_index}<br>layout: {layout.value}"


def _curved_segment_points(
    start: tuple[float, float],
    end: tuple[float, float],
    offset: float,
    samples: int = 8,
) -> list[tuple[float, float]]:
    start_x, start_y = start
    end_x, end_y = end
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length = (delta_x**2 + delta_y**2) ** 0.5 or 1.0
    normal_x = -delta_y / length
    normal_y = delta_x / length
    control_x = (start_x + end_x) / 2 + normal_x * offset
    control_y = (start_y + end_y) / 2 + normal_y * offset

    points = []
    for sample_index in range(samples + 1):
        t = sample_index / samples
        one_minus_t = 1 - t
        points.append(
            (
                one_minus_t * one_minus_t * start_x
                + 2 * one_minus_t * t * control_x
                + t * t * end_x,
                one_minus_t * one_minus_t * start_y
                + 2 * one_minus_t * t * control_y
                + t * t * end_y,
            )
        )
    return points


def export_topology_html(topology: MultiRailTopology, output_path: str | Path) -> Path:
    figure = create_topology_figure(topology)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output, include_plotlyjs=True, full_html=True)
    return output


def _edge_trace(
    topology: MultiRailTopology,
    positions: dict[str, tuple[float, float]],
    link_type: str,
) -> go.Scatter | None:
    x_values: list[float | None] = []
    y_values: list[float | None] = []
    hover_text: list[str] = []
    edge_count = 0

    for source, target, attributes in topology.graph.edges(data=True):
        if attributes["link_type"] != link_type:
            continue
        if _omit_edge_in_simplified_view(topology, source, target, attributes):
            continue

        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        x_values.extend([source_x, target_x, None])
        y_values.extend([source_y, target_y, None])
        hover_text.extend(
            [
                _edge_hover(source, target, attributes),
                _edge_hover(source, target, attributes),
                "",
            ]
        )
        edge_count += 1

    if edge_count == 0:
        return None

    if link_type == "intra":
        color = "#7d8790"
        width = 0.45 if topology.config.visualization_detail == VisualizationDetail.SIMPLIFIED else 0.8
        name = "Intra-node full mesh"
        dash = "solid"
    elif link_type == "fm2d":
        color = "#9b51e0"
        width = 0.55
        name = "2D same-index full mesh"
        dash = "solid"
    else:
        color = "#2f80ed"
        width = 0.55
        name = "Card-switch rail"
        dash = "solid"

    return go.Scatter(
        x=x_values,
        y=y_values,
        mode="lines",
        line={"width": width, "color": color, "dash": dash},
        hoverinfo="text",
        text=hover_text,
        name=name,
    )


def _switch_edge_traces(
    topology: MultiRailTopology,
    positions: dict[str, tuple[float, float]],
) -> list[go.Scatter]:
    traces: list[go.Scatter] = []
    for switch_index in range(topology.config.X):
        trace = _switch_edge_trace(
            topology,
            positions,
            switch_index=switch_index,
            highlight=False,
        )
        if trace is not None:
            traces.append(trace)

    for switch_index in range(topology.config.X):
        highlight_trace = _switch_edge_trace(
            topology,
            positions,
            switch_index=switch_index,
            highlight=True,
        )
        if highlight_trace is not None:
            traces.append(highlight_trace)
    return traces


def _switch_edge_trace(
    topology: MultiRailTopology,
    positions: dict[str, tuple[float, float]],
    switch_index: int | None,
    highlight: bool,
) -> go.Scatter | None:
    x_values: list[float | None] = []
    y_values: list[float | None] = []
    hover_text: list[str] = []
    edge_count = 0
    exemplar_index = _switch_exemplar_compute_index(topology)

    for source, target, attributes in topology.graph.edges(data=True):
        if attributes["link_type"] != "switch":
            continue

        source_attrs = topology.graph.nodes[source]
        target_attrs = topology.graph.nodes[target]
        card_attrs = source_attrs if source_attrs["node_type"] == "card" else target_attrs
        edge_is_highlight = card_attrs["compute_index"] == exemplar_index
        if edge_is_highlight != highlight:
            continue
        if card_attrs["switch_group"] != switch_index:
            continue
        if _omit_edge_in_simplified_view(topology, source, target, attributes):
            continue

        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        x_values.extend([source_x, target_x, None])
        y_values.extend([source_y, target_y, None])
        hover_text.extend(
            [
                _edge_hover(source, target, attributes),
                _edge_hover(source, target, attributes),
                "",
            ]
        )
        edge_count += 1

    if edge_count == 0:
        return None

    if highlight:
        color = _switch_color(int(switch_index))["line"]
        width = 1.45
        name = f"Highlighted multirail example {switch_index}"
    else:
        color = _switch_color(int(switch_index))["line"]
        width = 0.55
        name = f"Card-switch rail {switch_index}"

    return go.Scatter(
        x=x_values,
        y=y_values,
        mode="lines",
        line={"width": width, "color": color, "dash": "solid"},
        hoverinfo="text",
        text=hover_text,
        name=name,
        showlegend=True,
    )


def _omit_edge_in_simplified_view(
    topology: MultiRailTopology,
    source: str,
    target: str,
    attributes: dict[str, object],
) -> bool:
    if topology.config.visualization_detail == VisualizationDetail.FULL:
        return False

    link_type = attributes["link_type"]
    if link_type == "intra":
        return False
    if link_type == "fm2d":
        return True
    if link_type == "switch":
        source_attrs = topology.graph.nodes[source]
        target_attrs = topology.graph.nodes[target]
        card_attrs = source_attrs if source_attrs["node_type"] == "card" else target_attrs
        if card_attrs["compute_index"] == _switch_exemplar_compute_index(topology):
            return False
        return card_attrs["card_index"] % max(1, topology.config.N // max(1, topology.config.X)) != 0
    return False


def _switch_exemplar_compute_index(topology: MultiRailTopology) -> int:
    """Pick a central node so simplified views still show one full multirail fanout."""

    return max(0, (topology.config.M - 1) // 2)


def _intra_full_mesh_sample_indices(card_count: int) -> set[int]:
    if card_count <= 1:
        return set()
    return {
        1,
        max(1, card_count // 2),
        card_count - 1,
    }


def _node_trace(
    topology: MultiRailTopology,
    positions: dict[str, tuple[float, float]],
    node_type: str,
) -> go.Scatter | None:
    nodes = [
        (node_id, attributes)
        for node_id, attributes in topology.graph.nodes(data=True)
        if attributes["node_type"] == node_type
    ]

    if not nodes:
        return None

    style = {
        "compute": {"symbol": "square", "size": 12, "color": "#f2c94c", "name": "Compute node"},
        "card": {"symbol": "circle", "size": 6, "color": "#27ae60", "name": "Network card"},
        "switch": {"symbol": "square", "size": 1, "color": "rgba(0,0,0,0)", "name": "Switch"},
    }[node_type]
    text = [attributes["label"] for _, attributes in nodes]
    mode = "markers+text"
    textposition = "top center"
    if node_type == "compute":
        text = [None for _ in nodes]
        mode = "markers"
    elif node_type == "card":
        text = [None for _ in nodes]
        mode = "markers"
        exemplar_index = _switch_exemplar_compute_index(topology)
        style["color"] = [
            _switch_color(int(attributes["switch_group"]))["line"]
            if attributes["compute_index"] == exemplar_index
            else "#27ae60"
            for _, attributes in nodes
        ]
    elif node_type == "switch":
        text = [f"Switch {attributes['switch_index']}" for _, attributes in nodes]
        mode = "text"
        textposition = "middle center"

    return go.Scatter(
        x=[positions[node_id][0] for node_id, _ in nodes],
        y=[positions[node_id][1] for node_id, _ in nodes],
        mode=mode,
        text=text,
        textposition=textposition,
        textfont={"size": 8, "color": "#111111"},
        hoverinfo="text",
        hovertext=[_node_hover(node_id, attributes) for node_id, attributes in nodes],
        marker={
            "symbol": style["symbol"],
            "size": style["size"],
            "color": style["color"],
            "line": {"width": 0.8, "color": "#263238"},
        },
        name=style["name"],
    )


def _card_label_trace(
    topology: MultiRailTopology,
    positions: dict[str, tuple[float, float]],
) -> go.Scatter | None:
    card_nodes = [
        (node_id, attributes)
        for node_id, attributes in topology.graph.nodes(data=True)
        if attributes["node_type"] == "card"
    ]
    if not card_nodes:
        return None

    ring_radius = max(1.2, topology.config.N * 0.18)
    label_radius = ring_radius * 1.35
    x_values: list[float] = []
    y_values: list[float] = []
    labels: list[str] = []

    for node_id, attributes in card_nodes:
        compute_id = f"node{attributes['compute_index']}"
        compute_x, compute_y = positions[compute_id]
        card_x, card_y = positions[node_id]
        vector_x = card_x - compute_x
        vector_y = card_y - compute_y
        distance = (vector_x**2 + vector_y**2) ** 0.5 or 1.0
        x_values.append(compute_x + (vector_x / distance) * label_radius)
        y_values.append(compute_y + (vector_y / distance) * label_radius)
        labels.append(str(attributes["card_index"]))

    return go.Scatter(
        x=x_values,
        y=y_values,
        mode="text",
        text=labels,
        textfont={"size": 8, "color": "#111111"},
        hoverinfo="skip",
        showlegend=False,
        name="Card label",
    )


def _switch_shapes(
    topology: MultiRailTopology,
    positions: dict[str, tuple[float, float]],
) -> list[dict[str, object]]:
    switch_nodes = [
        node_id
        for node_id, attributes in topology.graph.nodes(data=True)
        if attributes["node_type"] == "switch"
    ]
    switch_width = max(2.4, min(4.2, topology.config.N * 0.32 + 1.6))
    switch_height = 0.72

    return [
        {
            "type": "rect",
            "xref": "x",
            "yref": "y",
            "x0": positions[node_id][0] - switch_width / 2,
            "x1": positions[node_id][0] + switch_width / 2,
            "y0": positions[node_id][1] - switch_height / 2,
            "y1": positions[node_id][1] + switch_height / 2,
            "line": {"color": _switch_color(int(topology.graph.nodes[node_id]["switch_index"]))["line"], "width": 0.9},
            "fillcolor": _switch_color(int(topology.graph.nodes[node_id]["switch_index"]))["fill"],
            "name": "switch-rect",
            "layer": "below",
        }
        for node_id in switch_nodes
    ]


def _switch_color(switch_index: int) -> dict[str, str]:
    palette = [
        {"line": "#1f6feb", "fill": "#dbeafe"},
        {"line": "#d97706", "fill": "#ffedd5"},
        {"line": "#059669", "fill": "#d1fae5"},
        {"line": "#7c3aed", "fill": "#ede9fe"},
        {"line": "#dc2626", "fill": "#fee2e2"},
        {"line": "#0891b2", "fill": "#cffafe"},
    ]
    return palette[switch_index % len(palette)]


def _fm2d_schematic_traces(
    topology: MultiRailTopology,
    positions: dict[str, tuple[float, float]],
) -> list[go.Scatter]:
    if topology.config.topology_type != TopologyType.TWO_D_FM_CLOS:
        return []

    min_x = min(x for x, _ in positions.values())
    max_y = max(y for _, y in positions.values())
    node_count = int(topology.config.fm2d_domain_size)
    schematic_radius = max(1.3, min(3.0, node_count * 0.32))
    label_radius = schematic_radius * 1.35
    base_x = min_x + label_radius
    base_y = max_y + label_radius + 3.8
    schematic_positions = [
        (
            base_x + schematic_radius * cos((2 * pi * index / node_count) - (pi / 2)),
            base_y + schematic_radius * sin((2 * pi * index / node_count) - (pi / 2)),
        )
        for index in range(node_count)
    ]
    label_positions = [
        (
            base_x + label_radius * cos((2 * pi * index / node_count) - (pi / 2)),
            base_y + label_radius * sin((2 * pi * index / node_count) - (pi / 2)),
        )
        for index in range(node_count)
    ]

    line_x: list[float | None] = []
    line_y: list[float | None] = []
    for left_index in range(node_count):
        for right_index in range(left_index + 1, node_count):
            left_x, left_y = schematic_positions[left_index]
            right_x, right_y = schematic_positions[right_index]
            line_x.extend([left_x, right_x, None])
            line_y.extend([left_y, right_y, None])

    labels = [f"N{index}" for index in range(node_count)]
    title_trace = go.Scatter(
        x=[base_x],
        y=[base_y + label_radius + 0.8],
        mode="text",
        text=[f"第二维FullMesh连接，一维同号卡互连，规模是{node_count}"],
        textfont={"size": 9, "color": "#263238"},
        hoverinfo="skip",
        showlegend=False,
        name="2D FM schematic title",
    )
    line_trace = go.Scatter(
        x=line_x,
        y=line_y,
        mode="lines",
        line={"width": 0.5, "color": "#9b51e0", "dash": "solid"},
        hoverinfo="skip",
        name="2D FM schematic",
    )
    node_trace = go.Scatter(
        x=[x for x, _ in schematic_positions],
        y=[y for _, y in schematic_positions],
        mode="markers",
        marker={
            "symbol": "circle",
            "size": 7,
            "color": "#9b51e0",
            "line": {"width": 0.8, "color": "#263238"},
        },
        hoverinfo="skip",
        name="2D FM schematic nodes",
    )
    label_trace = go.Scatter(
        x=[x for x, _ in label_positions],
        y=[y for _, y in label_positions],
        mode="text",
        text=labels,
        textfont={"size": 8, "color": "#263238"},
        hoverinfo="skip",
        showlegend=False,
        name="2D FM schematic labels",
    )
    return [title_trace, line_trace, node_trace, label_trace]


def _compute_label_trace(
    topology: MultiRailTopology,
    positions: dict[str, tuple[float, float]],
) -> go.Scatter | None:
    compute_nodes = [
        (node_id, attributes)
        for node_id, attributes in topology.graph.nodes(data=True)
        if attributes["node_type"] == "compute"
    ]
    if not compute_nodes:
        return None

    ring_radius = max(1.2, topology.config.N * 0.18)
    label_gap = ring_radius * 2.1 + 0.25
    x_values: list[float] = []
    y_values: list[float] = []
    labels: list[str] = []

    for node_id, attributes in compute_nodes:
        x, y = positions[node_id]
        direction = 1 if y >= 0 else -1
        x_values.append(x)
        y_values.append(y + direction * label_gap)
        labels.append(f"Node {attributes['compute_index']}")

    return go.Scatter(
        x=x_values,
        y=y_values,
        mode="text",
        text=labels,
        textfont={"size": 9, "color": "#263238"},
        hoverinfo="skip",
        showlegend=False,
        name="Compute label",
    )


def _node_hover(node_id: str, attributes: dict[str, object]) -> str:
    node_type = attributes["node_type"]
    lines = [f"id: {node_id}", f"type: {node_type}"]

    if node_type == "compute":
        lines.append(f"compute node: {attributes['compute_index']}")
    elif node_type == "card":
        lines.extend(
            [
                f"compute node: {attributes['compute_index']}",
                f"card index: {attributes['card_index']}",
                f"switch group: {attributes['switch_group']}",
                f"2D FM domain: {attributes.get('fm2d_domain', 'n/a')}",
            ]
        )
    elif node_type == "switch":
        lines.append(f"switch index: {attributes['switch_index']}")

    return "<br>".join(lines)


def _edge_hover(source: str, target: str, attributes: dict[str, object]) -> str:
    return (
        f"type: {attributes['link_type']}<br>"
        f"source: {source}<br>"
        f"target: {target}<br>"
        f"bandwidth: {attributes['bandwidth']}"
    )
