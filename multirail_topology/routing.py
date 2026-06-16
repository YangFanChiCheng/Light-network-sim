from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from enum import StrEnum
from pathlib import Path

import networkx as nx

from .config import TopologyType
from .topology import MultiRailTopology


class RoutingMode(StrEnum):
    SOURCE_NODE_JUMP = "source-node-jump"
    DESTINATION_NODE_JUMP = "destination-node-jump"
    SOURCE_2DFM_JUMP = "source-2dfm-jump"
    DESTINATION_2DFM_JUMP = "destination-2dfm-jump"
    SHORTEST_PATH = "shortest-path"
    DETOUR_ROUTING = "detour-routing"


@dataclass(frozen=True)
class RouteResult:
    source: str
    destination: str
    route_type: str
    paths: list[list[str]]
    path_weights: list[float] | None = None

    def __post_init__(self) -> None:
        if self.path_weights is None:
            return
        if len(self.path_weights) != len(self.paths):
            raise ValueError("path_weights length must match paths length")
        if any(weight < 0.0 for weight in self.path_weights):
            raise ValueError("path_weights must be non-negative")
        if self.path_weights and not isclose(sum(self.path_weights), 1.0):
            raise ValueError("path_weights must sum to 1.0")

    def weighted_paths(self) -> list[tuple[list[str], float]]:
        if self.path_weights is not None:
            return list(zip(self.paths, self.path_weights, strict=True))
        if not self.paths:
            return []
        weight = 1.0 / len(self.paths)
        return [(path, weight) for path in self.paths]


def route_between_cards(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
    mode: RoutingMode = RoutingMode.SOURCE_NODE_JUMP,
    domain_size: int | None = None,
) -> RouteResult:
    if not topology._built:
        topology.build_graph()

    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)

    if source_card == destination_card:
        return RouteResult(source_card, destination_card, "same_card", [[source_card]])

    if mode == RoutingMode.DETOUR_ROUTING:
        return _detour_route(topology, source_card, destination_card, domain_size)

    if mode == RoutingMode.SHORTEST_PATH:
        return _shortest_path(topology, source_card, destination_card)

    if source["compute_index"] == destination["compute_index"]:
        return RouteResult(
            source_card,
            destination_card,
            "intra_node_direct",
            [[source_card, destination_card]],
        )

    if topology.config.topology_type == TopologyType.TWO_D_FM_CLOS:
        if source["fm2d_domain"] == destination["fm2d_domain"]:
            return _same_2dfm_domain(topology, source_card, destination_card)

        if mode == RoutingMode.SOURCE_2DFM_JUMP:
            return _source_2dfm_jump(topology, source_card, destination_card)

        if mode == RoutingMode.DESTINATION_2DFM_JUMP:
            return _destination_2dfm_jump(topology, source_card, destination_card)

    if source["switch_group"] == destination["switch_group"]:
        switch_id = _switch_id(source["switch_group"])
        return RouteResult(
            source_card,
            destination_card,
            "same_switch_direct",
            [[source_card, switch_id, destination_card]],
        )

    if mode == RoutingMode.SOURCE_NODE_JUMP:
        return _source_node_jump(topology, source_card, destination_card)

    if mode == RoutingMode.DESTINATION_NODE_JUMP:
        return _destination_node_jump(topology, source_card, destination_card)

    raise ValueError(f"Unsupported routing mode: {mode}")


def export_all_routes(
    topology: MultiRailTopology,
    output_path: str | Path,
    mode: RoutingMode = RoutingMode.SOURCE_NODE_JUMP,
) -> Path:
    if not topology._built:
        topology.build_graph()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    cards = _card_ids(topology)
    lines = [
        f"routing_mode: {mode.value}",
        f"card_count: {len(cards)}",
        "",
    ]

    for source_card in cards:
        for destination_card in cards:
            if source_card == destination_card:
                continue

            route = route_between_cards(topology, source_card, destination_card, mode)
            rendered_paths = [" -> ".join(path) for path in route.paths]
            lines.append(
                f"{source_card} -> {destination_card} | "
                f"{route.route_type} | "
                f"{' ; '.join(rendered_paths)}"
            )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def export_representative_routes(
    topology: MultiRailTopology,
    output_path: str | Path,
    mode: RoutingMode = RoutingMode.SOURCE_NODE_JUMP,
    domain_count: int = 2,
) -> Path:
    if not topology._built:
        topology.build_graph()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    cards = _representative_card_ids(topology, domain_count)
    lines = [
        f"routing_mode: {mode.value}",
        "route_scope: representative",
        f"sampled_card_count: {len(cards)}",
        "",
    ]

    for source_card in cards:
        for destination_card in cards:
            if source_card == destination_card:
                continue

            route = route_between_cards(topology, source_card, destination_card, mode)
            rendered_paths = [" -> ".join(path) for path in route.paths]
            lines.append(
                f"{source_card} -> {destination_card} | "
                f"{route.route_type} | "
                f"{' ; '.join(rendered_paths)}"
            )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _representative_card_ids(topology: MultiRailTopology, domain_count: int) -> list[str]:
    if topology.config.topology_type == TopologyType.TWO_D_FM_CLOS:
        node_limit = min(topology.config.M, int(topology.config.fm2d_domain_size) * domain_count)
    else:
        node_limit = min(topology.config.M, domain_count)

    return [
        card_id
        for card_id in _card_ids(topology)
        if _card_attributes(topology, card_id)["compute_index"] < node_limit
    ]


def _source_node_jump(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)
    destination_switch_group = destination["switch_group"]
    switch_id = _switch_id(destination_switch_group)
    paths: list[list[str]] = []

    for candidate_card in _cards_in_compute_node(topology, source["compute_index"]):
        candidate = _card_attributes(topology, candidate_card)
        if candidate["switch_group"] != destination_switch_group:
            continue
        paths.append([source_card, candidate_card, switch_id, destination_card])

    return RouteResult(source_card, destination_card, "source_node_jump", paths)


def _destination_node_jump(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)
    switch_id = _switch_id(source["switch_group"])
    paths: list[list[str]] = []

    for candidate_card in _cards_in_compute_node(topology, destination["compute_index"]):
        candidate = _card_attributes(topology, candidate_card)
        if candidate["switch_group"] != source["switch_group"]:
            continue
        if candidate_card == destination_card:
            paths.append([source_card, switch_id, destination_card])
        else:
            paths.append([source_card, switch_id, candidate_card, destination_card])

    return RouteResult(source_card, destination_card, "destination_node_jump", paths)


def _shortest_path(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult:
    if topology.config.topology_type == TopologyType.SPARSE_CLOS:
        return _sparse_clos_shortest_path(topology, source_card, destination_card)

    paths = [
        list(path)
        for path in nx.all_shortest_paths(topology.graph, source_card, destination_card)
    ]
    return RouteResult(
        source_card,
        destination_card,
        "shortest_path",
        sorted(paths),
    )


def _detour_route(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
    domain_size: int | None,
) -> RouteResult:
    if topology.config.topology_type != TopologyType.SPARSE_CLOS:
        return _shortest_path(topology, source_card, destination_card)

    total_cards = topology.config.M * topology.config.N
    if domain_size is None or domain_size >= total_cards:
        return _shortest_path(topology, source_card, destination_card)

    if domain_size < 8:
        route = _sparse_clos_card_detour(topology, source_card, destination_card)
        if route is not None:
            return route

    if domain_size > topology.config.N:
        route = _sparse_clos_cluster_detour(topology, source_card, destination_card)
        if route is not None:
            return route

    return _shortest_path(topology, source_card, destination_card)


def _sparse_clos_card_detour(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult | None:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)
    if source["compute_index"] != destination["compute_index"]:
        return None
    if source["card_index"] // 8 != destination["card_index"] // 8:
        return None

    paths: list[list[str]] = []
    if topology.graph.has_edge(source_card, destination_card):
        paths.append([source_card, destination_card])

    group_start = (source["card_index"] // 8) * 8
    for card_index in range(group_start, group_start + 8):
        if card_index in (source["card_index"], destination["card_index"]):
            continue
        mid_card = _card_id(source["compute_index"], card_index)
        if topology.graph.has_edge(source_card, mid_card) and topology.graph.has_edge(mid_card, destination_card):
            paths.append([source_card, mid_card, destination_card])

    for switch_index in _shared_switches(topology, source_card, destination_card):
        switch_id = _switch_id(switch_index)
        paths.append([source_card, switch_id, destination_card])

    if len(paths) <= 1:
        return None
    return RouteResult(source_card, destination_card, "card_detour", paths)


def _sparse_clos_cluster_detour(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult | None:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)
    source_cluster = source["compute_index"]
    destination_cluster = destination["compute_index"]
    if source_cluster == destination_cluster:
        return None

    paths = [
        [source_card, _switch_id(switch_index), destination_card]
        for switch_index in _shared_switches(topology, source_card, destination_card)
    ]
    for intermediate_cluster in range(topology.config.M):
        if intermediate_cluster in (source_cluster, destination_cluster):
            continue
        relay_card = _relay_card_id(
            topology,
            source["card_index"],
            destination["card_index"],
            intermediate_cluster,
        )
        source_to_intermediate = _shared_switches(topology, source_card, relay_card)
        intermediate_to_destination = _shared_switches(topology, relay_card, destination_card)
        for first_switch in source_to_intermediate:
            for second_switch in intermediate_to_destination:
                if first_switch == second_switch:
                    continue
                paths.append(
                    [
                        source_card,
                        _switch_id(first_switch),
                        relay_card,
                        _switch_id(second_switch),
                        destination_card,
                    ]
                )

    if len(paths) <= 1:
        return None
    return RouteResult(source_card, destination_card, "cluster_detour", paths)


def _relay_card_id(
    topology: MultiRailTopology,
    source_card_index: int,
    destination_card_index: int,
    intermediate_cluster: int,
) -> str:
    relay_card_index = (
        source_card_index
        + destination_card_index
        + intermediate_cluster
    ) % topology.config.N
    return _card_id(intermediate_cluster, relay_card_index)


def _sparse_clos_shortest_path(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)

    if source["compute_index"] == destination["compute_index"]:
        if source["card_index"] // 8 == destination["card_index"] // 8:
            return RouteResult(
                source_card,
                destination_card,
                "shortest_path",
                [[source_card, destination_card]],
            )

        shared_switches = _card_switch_groups(topology, source_card)
    else:
        shared_switches = _shared_switches(topology, source_card, destination_card)

    paths = [
        [source_card, _switch_id(switch_index), destination_card]
        for switch_index in shared_switches
    ]
    if not paths:
        raise ValueError(f"No SparseClos shortest path between {source_card} and {destination_card}")
    return RouteResult(source_card, destination_card, "shortest_path", paths)


def _same_2dfm_domain(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)
    if source["card_index"] == destination["card_index"]:
        return RouteResult(
            source_card,
            destination_card,
            "same_2dfm_domain",
            [[source_card, destination_card]],
        )

    same_index_card = _card_id(source["compute_index"], destination["card_index"])
    return RouteResult(
        source_card,
        destination_card,
        "same_2dfm_domain",
        [[source_card, same_index_card, destination_card]],
    )


def _source_2dfm_jump(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)
    source_domain = source["fm2d_domain"]
    destination_switch_group = destination["switch_group"]
    switch_id = _switch_id(destination_switch_group)
    paths: list[list[str]] = []

    for candidate_card in _cards_in_fm2d_domain(topology, source_domain):
        candidate = _card_attributes(topology, candidate_card)
        if candidate["switch_group"] != destination_switch_group:
            continue

        path = _path_inside_2dfm_domain(
            topology,
            source_card,
            candidate_card,
        )
        paths.append(path + [switch_id, destination_card])

    return RouteResult(source_card, destination_card, "source_2dfm_jump", paths)


def _destination_2dfm_jump(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> RouteResult:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)
    destination_domain = destination["fm2d_domain"]
    source_switch_group = source["switch_group"]
    switch_id = _switch_id(source_switch_group)
    paths: list[list[str]] = []

    for entry_card in _cards_in_fm2d_domain(topology, destination_domain):
        entry = _card_attributes(topology, entry_card)
        if entry["switch_group"] != source_switch_group:
            continue

        path = _path_inside_2dfm_domain(topology, entry_card, destination_card)
        paths.append([source_card, switch_id] + path)

    return RouteResult(source_card, destination_card, "destination_2dfm_jump", paths)


def _path_inside_2dfm_domain(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> list[str]:
    source = _card_attributes(topology, source_card)
    destination = _card_attributes(topology, destination_card)

    if source_card == destination_card:
        return [source_card]
    if source["compute_index"] == destination["compute_index"]:
        return [source_card, destination_card]
    if source["card_index"] == destination["card_index"]:
        return [source_card, destination_card]

    source_node_destination_index_card = _card_id(
        source["compute_index"],
        destination["card_index"],
    )
    return [source_card, source_node_destination_index_card, destination_card]


def _card_attributes(topology: MultiRailTopology, card_id: str) -> dict[str, int]:
    if card_id not in topology.graph:
        raise ValueError(f"Unknown card: {card_id}")

    attributes = topology.graph.nodes[card_id]
    if attributes.get("node_type") != "card":
        raise ValueError(f"Node is not a card: {card_id}")

    return {
        "compute_index": int(attributes["compute_index"]),
        "card_index": int(attributes["card_index"]),
        "switch_group": int(attributes["switch_group"]),
        "fm2d_domain": int(attributes.get("fm2d_domain", -1)),
    }


def _card_switch_groups(topology: MultiRailTopology, card_id: str) -> tuple[int, ...]:
    attributes = topology.graph.nodes[card_id]
    switch_groups = attributes.get("switch_groups")
    if switch_groups is None:
        return (int(attributes["switch_group"]),)
    return tuple(int(switch_index) for switch_index in switch_groups)


def _shared_switches(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
) -> list[int]:
    return sorted(
        set(_card_switch_groups(topology, source_card))
        & set(_card_switch_groups(topology, destination_card))
    )


def _card_ids(topology: MultiRailTopology) -> list[str]:
    return sorted(
        (
            node_id
            for node_id, attributes in topology.graph.nodes(data=True)
            if attributes["node_type"] == "card"
        ),
        key=lambda card_id: (
            int(card_id.split("-card")[0].replace("node", "")),
            int(card_id.split("-card")[1]),
        ),
    )


def _cards_in_compute_node(topology: MultiRailTopology, compute_index: int) -> list[str]:
    return [
        card_id
        for card_id in _card_ids(topology)
        if topology.graph.nodes[card_id]["compute_index"] == compute_index
    ]


def _cards_in_fm2d_domain(topology: MultiRailTopology, domain_index: int) -> list[str]:
    return [
        card_id
        for card_id in _card_ids(topology)
        if topology.graph.nodes[card_id].get("fm2d_domain") == domain_index
    ]


def _card_id(node_index: int, card_index: int) -> str:
    return f"node{node_index}-card{card_index}"


def _switch_id(switch_index: int) -> str:
    return f"switch{switch_index}"
