from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import TopologyType
from .routing import RoutingMode, route_between_cards
from .topology import MultiRailTopology


PROPAGATION_LATENCY_NS_PER_METER = 5.0


@dataclass(frozen=True)
class LatencyConfig:
    switch_forward_latency_ns: float
    card_forward_latency_ns: float
    optical_module_latency_ns: float
    npu_processing_latency_ns: float
    intra_1dfm_link_length_m: float
    fm2d_link_length_m: float
    switch_link_length_m: float


@dataclass(frozen=True)
class LatencyResult:
    single_rtt_latency_ns: float
    source: str
    destination: str
    path: list[str]


def load_latency_config(path: str | Path) -> LatencyConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return latency_config_from_mapping(data)


def latency_config_from_mapping(data: dict[str, object]) -> LatencyConfig:
    return LatencyConfig(
        switch_forward_latency_ns=_positive_float(data, "switch_forward_latency_ns"),
        card_forward_latency_ns=_positive_float(data, "card_forward_latency_ns"),
        optical_module_latency_ns=_positive_float(data, "optical_module_latency_ns"),
        npu_processing_latency_ns=_positive_float(data, "npu_processing_latency_ns"),
        intra_1dfm_link_length_m=_positive_float(data, "intra_1dfm_link_length_m"),
        fm2d_link_length_m=_positive_float(data, "fm2d_link_length_m"),
        switch_link_length_m=_positive_float(data, "switch_link_length_m"),
    )


def path_one_way_latency_ns(
    topology: MultiRailTopology,
    path: list[str],
    config: LatencyConfig,
) -> float:
    if len(path) < 2:
        return 0.0

    latency = 0.0
    for source, target in zip(path, path[1:]):
        latency += _link_latency_ns(topology, source, target, config)

    for node_id in path[1:-1]:
        node_type = topology.graph.nodes[node_id]["node_type"]
        if node_type == "switch":
            latency += config.switch_forward_latency_ns
        elif node_type == "card":
            latency += config.card_forward_latency_ns
    return latency


def route_pair_rtt_latency(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
    mode: RoutingMode,
    config: LatencyConfig,
    domain_size: int | None = None,
) -> LatencyResult:
    route = route_between_cards(topology, source_card, destination_card, mode, domain_size=domain_size)
    max_path = max(
        route.paths,
        key=lambda path: path_one_way_latency_ns(topology, path, config),
    )
    one_way_latency = path_one_way_latency_ns(topology, max_path, config)
    return LatencyResult(
        single_rtt_latency_ns=one_way_latency * 2 + config.npu_processing_latency_ns,
        source=source_card,
        destination=destination_card,
        path=max_path,
    )


def max_domain_rtt_latency(
    topology: MultiRailTopology,
    domain_cards: list[str],
    mode: RoutingMode,
    config: LatencyConfig,
    domain_size: int | None = None,
) -> LatencyResult:
    if len(domain_cards) > 16:
        return _max_candidate_rtt_latency(topology, domain_cards, mode, config, domain_size=domain_size)

    best: LatencyResult | None = None
    for source_card in domain_cards:
        for destination_card in domain_cards:
            if source_card == destination_card:
                continue
            current = route_pair_rtt_latency(
                topology,
                source_card,
                destination_card,
                mode,
                config,
                domain_size=domain_size,
            )
            if best is None or current.single_rtt_latency_ns > best.single_rtt_latency_ns:
                best = current

    if best is None:
        return LatencyResult(0.0, "", "", [])
    return best


def max_domain_size_rtt_latency(
    topology: MultiRailTopology,
    cards: list[str],
    domain_size: int,
    mode: RoutingMode,
    config: LatencyConfig,
) -> LatencyResult:
    best: LatencyResult | None = None
    for index in range(0, len(cards), domain_size):
        current = max_domain_rtt_latency(
            topology,
            cards[index:index + domain_size],
            mode,
            config,
            domain_size=domain_size,
        )
        if best is None or current.single_rtt_latency_ns > best.single_rtt_latency_ns:
            best = current

    if best is None:
        return LatencyResult(0.0, "", "", [])
    return best


def _max_candidate_rtt_latency(
    topology: MultiRailTopology,
    domain_cards: list[str],
    mode: RoutingMode,
    config: LatencyConfig,
    domain_size: int | None = None,
) -> LatencyResult:
    candidates = _candidate_card_pairs(topology, domain_cards, mode)
    best: LatencyResult | None = None
    for source_card, destination_card in candidates:
        current = route_pair_rtt_latency(
            topology,
            source_card,
            destination_card,
            mode,
            config,
            domain_size=domain_size,
        )
        if best is None or current.single_rtt_latency_ns > best.single_rtt_latency_ns:
            best = current

    if best is None:
        return LatencyResult(0.0, "", "", [])
    return best


def _candidate_card_pairs(
    topology: MultiRailTopology,
    domain_cards: list[str],
    mode: RoutingMode,
) -> set[tuple[str, str]]:
    cards = sorted(domain_cards, key=_card_sort_key)
    attrs = {card_id: _card_attrs(topology, card_id) for card_id in cards}
    candidates: set[tuple[str, str]] = set()

    def add(source: str | None, destination: str | None) -> None:
        if source is not None and destination is not None and source != destination:
            candidates.add((source, destination))

    nodes = sorted({card_attrs["compute_index"] for card_attrs in attrs.values()})
    card_indices = sorted({card_attrs["card_index"] for card_attrs in attrs.values()})
    switch_groups = sorted({card_attrs["switch_group"] for card_attrs in attrs.values()})
    domains = sorted({card_attrs["fm2d_domain"] for card_attrs in attrs.values()})

    for node in nodes:
        node_cards = [card for card in cards if attrs[card]["compute_index"] == node]
        add(_pick_card(node_cards, attrs, card_index=card_indices[0]), _pick_card(node_cards, attrs, card_index=card_indices[-1]))

    for switch_group in switch_groups:
        group_cards = [card for card in cards if attrs[card]["switch_group"] == switch_group]
        add(group_cards[0], group_cards[-1])

    if len(nodes) >= 2:
        first_node = nodes[0]
        last_node = nodes[-1]
        for switch_group in switch_groups:
            add(
                _pick_card(cards, attrs, compute_index=first_node, switch_group=switch_group),
                _pick_card(cards, attrs, compute_index=last_node, switch_group=switch_group),
            )
        if mode == RoutingMode.SOURCE_NODE_JUMP:
            for source_switch in switch_groups:
                for destination_switch in switch_groups:
                    if source_switch == destination_switch:
                        continue
                    add(
                        _pick_card(cards, attrs, compute_index=first_node, switch_group=source_switch),
                        _pick_card(cards, attrs, compute_index=last_node, switch_group=destination_switch),
                    )
                    add(
                        _pick_card(cards, attrs, compute_index=last_node, switch_group=source_switch),
                        _pick_card(cards, attrs, compute_index=first_node, switch_group=destination_switch),
                    )
        elif mode == RoutingMode.DESTINATION_NODE_JUMP:
            for source_switch in switch_groups:
                for destination_switch in switch_groups:
                    if source_switch == destination_switch:
                        continue
                    add(
                        _pick_card(cards, attrs, compute_index=first_node, switch_group=source_switch),
                        _pick_card(cards, attrs, compute_index=last_node, switch_group=destination_switch),
                    )
                    add(
                        _pick_card(cards, attrs, compute_index=last_node, switch_group=source_switch),
                        _pick_card(cards, attrs, compute_index=first_node, switch_group=destination_switch),
                    )

    if topology.config.topology_type == TopologyType.TWO_D_FM_CLOS:
        for domain in domains:
            domain_nodes = sorted(
                {card_attrs["compute_index"] for card_attrs in attrs.values() if card_attrs["fm2d_domain"] == domain}
            )
            if len(domain_nodes) >= 2:
                add(
                    _pick_card(cards, attrs, compute_index=domain_nodes[0], card_index=card_indices[0]),
                    _pick_card(cards, attrs, compute_index=domain_nodes[-1], card_index=card_indices[0]),
                )
                add(
                    _pick_card(cards, attrs, compute_index=domain_nodes[0], card_index=card_indices[0]),
                    _pick_card(cards, attrs, compute_index=domain_nodes[-1], card_index=card_indices[-1]),
                )

        if len(domains) >= 2:
            source_domain = domains[0]
            destination_domain = domains[-1]
            source_nodes = sorted(
                {card_attrs["compute_index"] for card_attrs in attrs.values() if card_attrs["fm2d_domain"] == source_domain}
            )
            destination_nodes = sorted(
                {card_attrs["compute_index"] for card_attrs in attrs.values() if card_attrs["fm2d_domain"] == destination_domain}
            )
            for source_switch in switch_groups:
                for destination_switch in switch_groups:
                    add(
                        _pick_card(cards, attrs, compute_index=source_nodes[0], switch_group=source_switch),
                        _pick_card(cards, attrs, compute_index=destination_nodes[-1], switch_group=destination_switch),
                    )

            if mode == RoutingMode.DESTINATION_2DFM_JUMP:
                add(
                    _pick_card(cards, attrs, compute_index=source_nodes[0], switch_group=switch_groups[0]),
                    _pick_card(cards, attrs, compute_index=destination_nodes[-1], switch_group=switch_groups[-1]),
                )

    return candidates


def _pick_card(
    cards: list[str],
    attrs: dict[str, dict[str, int]],
    compute_index: int | None = None,
    card_index: int | None = None,
    switch_group: int | None = None,
) -> str | None:
    for card in cards:
        card_attrs = attrs[card]
        if compute_index is not None and card_attrs["compute_index"] != compute_index:
            continue
        if card_index is not None and card_attrs["card_index"] != card_index:
            continue
        if switch_group is not None and card_attrs["switch_group"] != switch_group:
            continue
        return card
    return None


def _card_attrs(topology: MultiRailTopology, card_id: str) -> dict[str, int]:
    attrs = topology.graph.nodes[card_id]
    return {
        "compute_index": int(attrs["compute_index"]),
        "card_index": int(attrs["card_index"]),
        "switch_group": int(attrs["switch_group"]),
        "fm2d_domain": int(attrs.get("fm2d_domain", -1)),
    }


def _card_sort_key(card_id: str) -> tuple[int, int]:
    node_part, card_part = card_id.split("-card")
    return int(node_part.removeprefix("node")), int(card_part)


def _link_latency_ns(
    topology: MultiRailTopology,
    source: str,
    target: str,
    config: LatencyConfig,
) -> float:
    link_type = topology.graph.edges[source, target]["link_type"]
    if link_type == "switch":
        return (
            config.switch_link_length_m * PROPAGATION_LATENCY_NS_PER_METER
            + config.optical_module_latency_ns * 2
        )
    if link_type == "fm2d":
        return config.fm2d_link_length_m * PROPAGATION_LATENCY_NS_PER_METER
    return config.intra_1dfm_link_length_m * PROPAGATION_LATENCY_NS_PER_METER


def _positive_float(data: dict[str, object], key: str) -> float:
    if key not in data:
        raise ValueError(f"Missing latency config field: {key}")
    value = data[key]
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{key} must be a non-negative number")
    return float(value)
