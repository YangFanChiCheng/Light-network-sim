from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from math import ceil
from pathlib import Path
from time import perf_counter

from .routing import RoutingMode, route_between_cards
from .routing import RouteResult
from .topology import MultiRailTopology
from .config import TopologyType
from .latency import LatencyConfig, LatencyResult, max_domain_rtt_latency, max_domain_size_rtt_latency
from .sparse_clos import derive_bst_parameters

LinkId = tuple[str, str]
RouteCache = dict[tuple[str, str, RoutingMode, int | None], RouteResult]
ROUTE_CACHE_LIMIT = 200_000
ProgressCallback = Callable[["SimulationProgress"], None]


@dataclass(frozen=True)
class SimulationProgress:
    event: str
    domain_size: int | None = None
    domain_index: int = 0
    domain_count: int = 0
    processed_pairs: int = 0
    total_pairs: int = 0
    elapsed_seconds: float = 0.0
    worker_count: int = 1


@dataclass(frozen=True)
class SimulationResult:
    domain_size: int
    routing_mode: RoutingMode
    focus_card: str
    link_traffic: dict[LinkId, float]
    link_loads: dict[LinkId, float]
    focus_card_sent_flows: int
    focus_card_port_count: int
    focus_card_adjacent_link_traffic: dict[LinkId, float]
    max_loaded_adjacent_link: LinkId | None
    max_adjacent_link_load: float
    focus_card_efficiency_denominator: float
    focus_card_bandwidth_efficiency: float
    latency_result: LatencyResult | None = None
    route_type_counts: dict[str, int] = field(default_factory=dict)


def factors(value: int) -> list[int]:
    if value <= 0:
        raise ValueError("value must be positive")

    return [candidate for candidate in range(1, value + 1) if value % candidate == 0]


def simulate_domain_sizes(
    topology: MultiRailTopology,
    domain_sizes: list[int] | None = None,
    mode: RoutingMode = RoutingMode.SOURCE_NODE_JUMP,
    focus_card: str = "node0-card0",
    progress_callback: ProgressCallback | None = None,
    progress_interval: float = 5.0,
    workers: int = 1,
    focus_only: bool = False,
    latency_config: LatencyConfig | None = None,
) -> list[SimulationResult]:
    if not topology._built:
        topology.build_graph()

    card_count = len(_card_ids(topology))
    sizes = _default_domain_sizes(topology, card_count) if domain_sizes is None else domain_sizes
    sizes = [domain_size for domain_size in sizes if domain_size != 1]
    route_cache: RouteCache = {}
    worker_count = max(1, int(workers))
    if progress_callback is not None:
        progress_callback(
            SimulationProgress(
                event="all_start",
                domain_count=len(sizes),
                worker_count=worker_count,
            )
        )

    results: list[SimulationResult] = []
    for index, domain_size in enumerate(sizes, start=1):
        results.append(
            simulate_domain_size(
                topology,
                domain_size,
                mode=mode,
                focus_card=focus_card,
                route_cache=route_cache,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
                domain_index=index,
                domain_count=len(sizes),
                workers=worker_count,
                focus_only=focus_only,
                latency_config=latency_config,
            )
        )
    return results


def simulate_domain_size(
    topology: MultiRailTopology,
    domain_size: int,
    mode: RoutingMode = RoutingMode.SOURCE_NODE_JUMP,
    focus_card: str = "node0-card0",
    route_cache: RouteCache | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_interval: float = 5.0,
    domain_index: int = 1,
    domain_count: int = 1,
    workers: int = 1,
    focus_only: bool = False,
    latency_config: LatencyConfig | None = None,
) -> SimulationResult:
    if not topology._built:
        topology.build_graph()

    cards = _card_ids(topology)
    if domain_size <= 0:
        raise ValueError("domain_size must be positive")
    if len(cards) % domain_size != 0 and not _allows_focus_domain(topology, domain_size, len(cards)):
        raise ValueError("domain_size must divide total card count")
    if focus_card not in cards:
        raise ValueError(f"Unknown focus_card: {focus_card}")

    if focus_only:
        return _simulate_focus_only_domain_size(
            topology,
            cards,
            domain_size,
            mode,
            focus_card,
            progress_callback,
            progress_interval,
            domain_index,
            domain_count,
            workers,
            latency_config,
        )

    worker_count = max(1, int(workers))
    route_type_counts: dict[str, int] = {}
    link_traffic = {
        directed_link: 0.0
        for source, target in topology.graph.edges()
        for directed_link in ((source, target), (target, source))
    }
    domain_groups = _communication_domains(topology, cards, domain_size, focus_card)
    total_pairs = sum(len(domain_cards) * (len(domain_cards) - 1) for domain_cards in domain_groups)
    processed_pairs = 0
    start_time = perf_counter()
    last_progress_time = start_time
    next_progress_percent = 1
    last_emitted_pairs = -1

    if progress_callback is not None:
        progress_callback(
            SimulationProgress(
                event="domain_start",
                domain_size=domain_size,
                domain_index=domain_index,
                domain_count=domain_count,
                total_pairs=total_pairs,
                worker_count=worker_count,
            )
        )

    def emit_pair_progress(force: bool = False) -> None:
        nonlocal last_progress_time, next_progress_percent, last_emitted_pairs
        if progress_callback is None or total_pairs == 0:
            return
        if processed_pairs == last_emitted_pairs:
            return

        now = perf_counter()
        percent = int(processed_pairs * 100 / total_pairs)
        should_emit = (
            force
            or percent >= next_progress_percent
            or now - last_progress_time >= progress_interval
        )
        if not should_emit:
            return

        progress_callback(
            SimulationProgress(
                event="pair_progress",
                domain_size=domain_size,
                domain_index=domain_index,
                domain_count=domain_count,
                processed_pairs=processed_pairs,
                total_pairs=total_pairs,
                elapsed_seconds=now - start_time,
                worker_count=worker_count,
            )
        )
        last_progress_time = now
        last_emitted_pairs = processed_pairs
        next_progress_percent = min(100, max(next_progress_percent + 1, percent + 1))

    if worker_count == 1:
        for domain_cards in domain_groups:
            for source_card in domain_cards:
                for destination_card in domain_cards:
                    if source_card == destination_card:
                        continue

                    route = _cached_route(
                        topology,
                        source_card,
                        destination_card,
                        mode,
                        domain_size,
                        route_cache,
                    )
                    _record_route_type(route_type_counts, route)
                    for path, traffic_share in route.weighted_paths():
                        for link in _path_links(path):
                            link_traffic[link] += traffic_share
                    processed_pairs += 1
                    emit_pair_progress()
    else:
        work_chunks = _parallel_work_chunks(topology, cards, domain_size, worker_count, focus_card)
        try:
            with ProcessPoolExecutor(max_workers=min(worker_count, len(work_chunks))) as executor:
                futures = [
                    executor.submit(_simulate_work_chunk, topology, chunk, mode, domain_size)
                    for chunk in work_chunks
                ]
                for future in as_completed(futures):
                    partial_traffic, partial_pairs, partial_route_types = future.result()
                    for link, traffic in partial_traffic.items():
                        link_traffic[link] += traffic
                    _merge_route_type_counts(route_type_counts, partial_route_types)
                    processed_pairs += partial_pairs
                    emit_pair_progress(force=True)
        except OSError:
            for chunk in work_chunks:
                partial_traffic, partial_pairs, partial_route_types = _simulate_work_chunk(
                    topology,
                    chunk,
                    mode,
                    domain_size,
                )
                for link, traffic in partial_traffic.items():
                    link_traffic[link] += traffic
                _merge_route_type_counts(route_type_counts, partial_route_types)
                processed_pairs += partial_pairs
                emit_pair_progress(force=True)

    emit_pair_progress(force=True)
    if latency_config is not None and progress_callback is not None:
        progress_callback(
            SimulationProgress(
                event="latency_start",
                domain_size=domain_size,
                domain_index=domain_index,
                domain_count=domain_count,
                processed_pairs=processed_pairs,
                total_pairs=total_pairs,
                elapsed_seconds=perf_counter() - start_time,
                worker_count=worker_count,
            )
        )

    link_loads = {
        link: traffic / _link_bandwidth(topology, link)
        for link, traffic in link_traffic.items()
    }
    adjacent_links = _adjacent_links(topology, focus_card)
    focus_card_adjacent_link_traffic = {
        link: link_traffic[link]
        for link in adjacent_links
    }
    max_loaded_adjacent_link = max(
        adjacent_links,
        key=lambda link: link_loads[link],
        default=None,
    )
    max_adjacent_link_load = (
        link_loads[max_loaded_adjacent_link]
        if max_loaded_adjacent_link is not None
        else 0.0
    )
    focus_card_sent_flows = domain_size - 1
    focus_card_port_count = len(adjacent_links)
    efficiency_denominator = _focus_card_efficiency_denominator(
        topology,
        link_traffic,
        adjacent_links,
        max_loaded_adjacent_link,
        max_adjacent_link_load,
    )
    efficiency = (
        focus_card_sent_flows / efficiency_denominator
        if efficiency_denominator
        else 0.0
    )
    latency_result = _latency_for_domain_groups(topology, cards, domain_size, mode, latency_config, focus_card)

    if progress_callback is not None:
        progress_callback(
            SimulationProgress(
                event="domain_finish",
                domain_size=domain_size,
                domain_index=domain_index,
                domain_count=domain_count,
                processed_pairs=processed_pairs,
                total_pairs=total_pairs,
                elapsed_seconds=perf_counter() - start_time,
                worker_count=worker_count,
            )
        )

    result = SimulationResult(
        domain_size=domain_size,
        routing_mode=mode,
        focus_card=focus_card,
        link_traffic=link_traffic,
        link_loads=link_loads,
        focus_card_sent_flows=focus_card_sent_flows,
        focus_card_port_count=focus_card_port_count,
        focus_card_adjacent_link_traffic=focus_card_adjacent_link_traffic,
        max_loaded_adjacent_link=max_loaded_adjacent_link,
        max_adjacent_link_load=max_adjacent_link_load,
        focus_card_efficiency_denominator=efficiency_denominator,
        focus_card_bandwidth_efficiency=efficiency,
        latency_result=latency_result,
        route_type_counts=route_type_counts,
    )
    return _fallback_to_shortest_if_detour_is_worse(
        topology,
        result,
        mode,
        focus_card,
        domain_index,
        domain_count,
        workers,
        focus_only,
        latency_config,
    )


def export_simulation_report(
    topology: MultiRailTopology,
    output_path: str | Path,
    domain_sizes: list[int] | None = None,
    mode: RoutingMode = RoutingMode.SOURCE_NODE_JUMP,
    focus_card: str = "node0-card0",
    progress_callback: ProgressCallback | None = None,
    progress_interval: float = 5.0,
    workers: int = 1,
    latency_config: LatencyConfig | None = None,
) -> Path:
    results = simulate_domain_sizes(
        topology,
        domain_sizes=domain_sizes,
        mode=mode,
        focus_card=focus_card,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
        workers=workers,
        focus_only=(mode != RoutingMode.DETOUR_ROUTING),
        latency_config=latency_config,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"routing_mode: {mode.value}",
        f"focus_card: {focus_card}",
    ]
    lines.extend(_render_topology_metadata(topology))
    lines.append("")
    lines.extend(_render_compact_summary_table(results))
    lines.append("")

    for result in results:
        lines.extend(_render_result(result))
        lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def export_all_link_traffic_report(
    topology: MultiRailTopology,
    output_path: str | Path,
    domain_sizes: list[int] | None = None,
    mode: RoutingMode = RoutingMode.SOURCE_NODE_JUMP,
    focus_card: str = "node0-card0",
    progress_callback: ProgressCallback | None = None,
    progress_interval: float = 5.0,
    workers: int = 1,
) -> Path:
    results = simulate_domain_sizes(
        topology,
        domain_sizes=domain_sizes,
        mode=mode,
        focus_card=focus_card,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
        workers=workers,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"routing_mode: {mode.value}",
        "",
    ]

    for result in results:
        lines.append(f"domain_size: {result.domain_size}")
        for link, traffic in sorted(result.link_traffic.items()):
            load = result.link_loads[link]
            lines.append(f"  {_format_link(link)} | traffic={traffic:.6f} | load={load:.6f}")
        lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _simulate_focus_only_domain_size(
    topology: MultiRailTopology,
    cards: list[str],
    domain_size: int,
    mode: RoutingMode,
    focus_card: str,
    progress_callback: ProgressCallback | None,
    progress_interval: float,
    domain_index: int,
    domain_count: int,
    workers: int,
    latency_config: LatencyConfig | None,
) -> SimulationResult:
    adjacent_links = _adjacent_links(topology, focus_card)
    link_traffic = {link: 0.0 for link in adjacent_links}
    card_attrs = {card_id: _card_attrs(topology, card_id) for card_id in cards}
    route_type_counts: dict[str, int] = {}
    domain_groups = _communication_domains(topology, cards, domain_size, focus_card)
    total_pairs = sum(len(domain_cards) * (len(domain_cards) - 1) for domain_cards in domain_groups)
    processed_pairs = 0
    start_time = perf_counter()
    last_progress_time = start_time
    next_progress_percent = 1
    last_emitted_pairs = -1
    worker_count = max(1, int(workers))

    if progress_callback is not None:
        progress_callback(
            SimulationProgress(
                event="domain_start",
                domain_size=domain_size,
                domain_index=domain_index,
                domain_count=domain_count,
                total_pairs=total_pairs,
                worker_count=worker_count,
            )
        )

    def emit_pair_progress(force: bool = False) -> None:
        nonlocal last_progress_time, next_progress_percent, last_emitted_pairs
        if progress_callback is None or total_pairs == 0 or processed_pairs == last_emitted_pairs:
            return

        now = perf_counter()
        percent = int(processed_pairs * 100 / total_pairs)
        if not (force or percent >= next_progress_percent or now - last_progress_time >= progress_interval):
            return

        progress_callback(
            SimulationProgress(
                event="pair_progress",
                domain_size=domain_size,
                domain_index=domain_index,
                domain_count=domain_count,
                processed_pairs=processed_pairs,
                total_pairs=total_pairs,
                elapsed_seconds=now - start_time,
                worker_count=worker_count,
            )
        )
        last_progress_time = now
        last_emitted_pairs = processed_pairs
        next_progress_percent = min(100, max(next_progress_percent + 1, percent + 1))

    for domain_cards in domain_groups:
        for source_card, destination_card in _focus_relevant_pairs(
            topology,
            domain_cards,
            mode,
            focus_card,
            domain_size,
            card_attrs,
        ):
            route_type = _add_focus_route_traffic(
                topology,
                link_traffic,
                source_card,
                destination_card,
                mode,
                focus_card,
                domain_size,
                card_attrs,
            )
            if route_type is not None:
                route_type_counts[route_type] = route_type_counts.get(route_type, 0) + 1

        processed_pairs += len(domain_cards) * (len(domain_cards) - 1)
        emit_pair_progress(force=True)

    emit_pair_progress(force=True)
    if latency_config is not None and progress_callback is not None:
        progress_callback(
            SimulationProgress(
                event="latency_start",
                domain_size=domain_size,
                domain_index=domain_index,
                domain_count=domain_count,
                processed_pairs=processed_pairs,
                total_pairs=total_pairs,
                elapsed_seconds=perf_counter() - start_time,
                worker_count=worker_count,
            )
        )
    link_loads = {
        link: traffic / _link_bandwidth(topology, link)
        for link, traffic in link_traffic.items()
    }
    max_loaded_adjacent_link = max(
        adjacent_links,
        key=lambda link: link_loads[link],
        default=None,
    )
    max_adjacent_link_load = (
        link_loads[max_loaded_adjacent_link]
        if max_loaded_adjacent_link is not None
        else 0.0
    )
    focus_card_sent_flows = domain_size - 1
    efficiency_denominator = _focus_card_efficiency_denominator(
        topology,
        link_traffic,
        adjacent_links,
        max_loaded_adjacent_link,
        max_adjacent_link_load,
    )
    efficiency = (
        focus_card_sent_flows / efficiency_denominator
        if efficiency_denominator
        else 0.0
    )
    latency_result = _latency_for_domain_groups(topology, cards, domain_size, mode, latency_config, focus_card)

    if progress_callback is not None:
        progress_callback(
            SimulationProgress(
                event="domain_finish",
                domain_size=domain_size,
                domain_index=domain_index,
                domain_count=domain_count,
                processed_pairs=processed_pairs,
                total_pairs=total_pairs,
                elapsed_seconds=perf_counter() - start_time,
                worker_count=worker_count,
            )
        )

    result = SimulationResult(
        domain_size=domain_size,
        routing_mode=mode,
        focus_card=focus_card,
        link_traffic=link_traffic,
        link_loads=link_loads,
        focus_card_sent_flows=focus_card_sent_flows,
        focus_card_port_count=len(adjacent_links),
        focus_card_adjacent_link_traffic=dict(link_traffic),
        max_loaded_adjacent_link=max_loaded_adjacent_link,
        max_adjacent_link_load=max_adjacent_link_load,
        focus_card_efficiency_denominator=efficiency_denominator,
        focus_card_bandwidth_efficiency=efficiency,
        latency_result=latency_result,
        route_type_counts=route_type_counts,
    )
    return _fallback_to_shortest_if_detour_is_worse(
        topology,
        result,
        mode,
        focus_card,
        domain_index,
        domain_count,
        workers,
        True,
        latency_config,
    )


def _add_focus_route_traffic(
    topology: MultiRailTopology,
    link_traffic: dict[LinkId, float],
    source_card: str,
    destination_card: str,
    mode: RoutingMode,
    focus_card: str,
    domain_size: int | None,
    card_attrs: dict[str, dict[str, int]] | None = None,
) -> str | None:
    source = _cached_card_attrs(topology, source_card, card_attrs)
    destination = _cached_card_attrs(topology, destination_card, card_attrs)
    focus = _cached_card_attrs(topology, focus_card, card_attrs)

    if mode in (RoutingMode.SHORTEST_PATH, RoutingMode.DETOUR_ROUTING):
        route = route_between_cards(
            topology,
            source_card,
            destination_card,
            mode,
            domain_size=domain_size,
        )
        for path, traffic_share in route.weighted_paths():
            _add_focus_path_traffic(link_traffic, focus_card, path, traffic_share)
        return route.route_type

    if source["compute_index"] == destination["compute_index"]:
        _add_focus_path_traffic(link_traffic, focus_card, [source_card, destination_card], 1.0)
        return "intra_node_direct"

    if topology.config.topology_type == TopologyType.TWO_D_FM_CLOS:
        if source["fm2d_domain"] == destination["fm2d_domain"]:
            _add_focus_path_traffic(
                link_traffic,
                focus_card,
                _inside_2dfm_path(source_card, destination_card),
                1.0,
            )
            return "same_2dfm_domain"

        if mode == RoutingMode.SOURCE_2DFM_JUMP:
            _add_source_2dfm_focus_traffic(
                topology,
                link_traffic,
                source_card,
                destination_card,
                focus_card,
                card_attrs,
            )
            return "source_2dfm_jump"

        if mode == RoutingMode.DESTINATION_2DFM_JUMP:
            _add_destination_2dfm_focus_traffic(
                topology,
                link_traffic,
                source_card,
                destination_card,
                focus_card,
                card_attrs,
            )
            return "destination_2dfm_jump"

    if source["switch_group"] == destination["switch_group"]:
        _add_focus_path_traffic(
            link_traffic,
            focus_card,
            [source_card, _switch_id(source["switch_group"]), destination_card],
            1.0,
        )
        return "same_switch_direct"

    if mode == RoutingMode.SOURCE_NODE_JUMP:
        group_size = _switch_group_size(topology, destination["switch_group"])
        share = 1.0 / group_size
        if source_card == focus_card:
            for card_index in _switch_group_cards(topology, destination["switch_group"]):
                _add_focus_link(link_traffic, focus_card, _card_id(source["compute_index"], card_index), share)
        elif (
            focus["compute_index"] == source["compute_index"]
            and focus["switch_group"] == destination["switch_group"]
        ):
            _add_focus_link(link_traffic, focus_card, _switch_id(destination["switch_group"]), share)
        return "source_node_jump"

    if mode == RoutingMode.DESTINATION_NODE_JUMP:
        group_size = _switch_group_size(topology, source["switch_group"])
        share = 1.0 / group_size
        if source_card == focus_card:
            _add_focus_link(link_traffic, focus_card, _switch_id(source["switch_group"]), 1.0)
        elif (
            focus["compute_index"] == destination["compute_index"]
            and focus["switch_group"] == source["switch_group"]
            and focus_card != destination_card
        ):
            _add_focus_link(link_traffic, focus_card, destination_card, share)
        return "destination_node_jump"


def _focus_relevant_pairs(
    topology: MultiRailTopology,
    domain_cards: list[str],
    mode: RoutingMode,
    focus_card: str,
    domain_size: int | None,
    card_attrs: dict[str, dict[str, int]] | None = None,
) -> set[tuple[str, str]]:
    domain_set = set(domain_cards)
    attrs = {
        card_id: _cached_card_attrs(topology, card_id, card_attrs)
        for card_id in domain_cards
    }
    focus = _cached_card_attrs(topology, focus_card, card_attrs)
    pairs: set[tuple[str, str]] = set()

    def add_pair(source_card: str, destination_card: str) -> None:
        if source_card != destination_card and source_card in domain_set and destination_card in domain_set:
            pairs.add((source_card, destination_card))

    if mode == RoutingMode.DETOUR_ROUTING:
        for source_card in domain_cards:
            for destination_card in domain_cards:
                add_pair(source_card, destination_card)
        return pairs

    if mode == RoutingMode.SHORTEST_PATH:
        if topology.config.topology_type == TopologyType.SPARSE_CLOS:
            for destination_card in domain_cards:
                add_pair(focus_card, destination_card)
            return pairs
        for source_card in domain_cards:
            for destination_card in domain_cards:
                add_pair(source_card, destination_card)
        return pairs

    if focus_card in domain_set:
        for destination_card in domain_cards:
            add_pair(focus_card, destination_card)

    focus_node_cards = [
        card_id
        for card_id, card_attrs in attrs.items()
        if card_attrs["compute_index"] == focus["compute_index"]
    ]
    for source_card in focus_node_cards:
        for destination_card in domain_cards:
            add_pair(source_card, destination_card)

    for destination_card in focus_node_cards:
        for source_card in domain_cards:
            add_pair(source_card, destination_card)

    if topology.config.topology_type != TopologyType.TWO_D_FM_CLOS:
        return pairs

    if mode == RoutingMode.SOURCE_2DFM_JUMP:
        source_cards = [
            card_id
            for card_id, card_attrs in attrs.items()
            if card_attrs["fm2d_domain"] == focus["fm2d_domain"]
        ]
        destination_cards = [
            card_id
            for card_id, card_attrs in attrs.items()
            if (
                card_attrs["fm2d_domain"] != focus["fm2d_domain"]
                and card_attrs["switch_group"] == focus["switch_group"]
            )
        ]
        for source_card in source_cards:
            for destination_card in destination_cards:
                add_pair(source_card, destination_card)

    if mode == RoutingMode.DESTINATION_2DFM_JUMP:
        destination_cards = [
            card_id
            for card_id, card_attrs in attrs.items()
            if card_attrs["fm2d_domain"] == focus["fm2d_domain"]
        ]
        focus_switch_source_cards = [
            card_id
            for card_id, card_attrs in attrs.items()
            if (
                card_attrs["fm2d_domain"] != focus["fm2d_domain"]
                and card_attrs["switch_group"] == focus["switch_group"]
            )
        ]
        non_focus_switch_source_cards = [
            card_id
            for card_id, card_attrs in attrs.items()
            if (
                card_attrs["fm2d_domain"] != focus["fm2d_domain"]
                and card_attrs["switch_group"] != focus["switch_group"]
            )
        ]
        for destination_card in destination_cards:
            destination = attrs[destination_card]
            for source_card in focus_switch_source_cards:
                add_pair(source_card, destination_card)
            if destination["card_index"] == focus["card_index"]:
                for source_card in non_focus_switch_source_cards:
                    add_pair(source_card, destination_card)

    return pairs


def _add_source_2dfm_focus_traffic(
    topology: MultiRailTopology,
    link_traffic: dict[LinkId, float],
    source_card: str,
    destination_card: str,
    focus_card: str,
    card_attrs: dict[str, dict[str, int]] | None = None,
) -> None:
    source = _cached_card_attrs(topology, source_card, card_attrs)
    destination = _cached_card_attrs(topology, destination_card, card_attrs)
    focus = _cached_card_attrs(topology, focus_card, card_attrs)
    domain_size = int(topology.config.fm2d_domain_size)
    group_cards = _switch_group_cards(topology, destination["switch_group"])
    candidate_count = domain_size * len(group_cards)
    share = 1.0 / candidate_count
    switch_id = _switch_id(destination["switch_group"])

    if source_card == focus_card:
        for card_index in group_cards:
            if card_index == source["card_index"]:
                for node_index in _nodes_in_domain(topology, source["fm2d_domain"]):
                    if node_index == source["compute_index"]:
                        _add_focus_link(link_traffic, focus_card, switch_id, share)
                    else:
                        _add_focus_link(link_traffic, focus_card, _card_id(node_index, card_index), share)
            else:
                _add_focus_link(
                    link_traffic,
                    focus_card,
                    _card_id(source["compute_index"], card_index),
                    domain_size * share,
                )

    if (
        focus["fm2d_domain"] == source["fm2d_domain"]
        and focus["switch_group"] == destination["switch_group"]
    ):
        _add_focus_link(link_traffic, focus_card, switch_id, share)

    if (
        focus["compute_index"] == source["compute_index"]
        and focus["card_index"] in group_cards
        and focus_card != source_card
    ):
        _add_focus_link_count_for_mid_source_2dfm(
            topology,
            link_traffic,
            source,
            focus_card,
            share,
            card_attrs,
        )


def _add_focus_link_count_for_mid_source_2dfm(
    topology: MultiRailTopology,
    link_traffic: dict[LinkId, float],
    source: dict[str, int],
    focus_card: str,
    share: float,
    card_attrs: dict[str, dict[str, int]] | None = None,
) -> None:
    for node_index in _nodes_in_domain(topology, source["fm2d_domain"]):
        if node_index != source["compute_index"]:
            _add_focus_link(link_traffic, focus_card, _card_id(node_index, source["card_index"]), 0.0)
    # If focus is the middle card, every candidate with focus.card_index on another node exits focus to candidate.
    focus = _cached_card_attrs(topology, focus_card, card_attrs)
    for node_index in _nodes_in_domain(topology, source["fm2d_domain"]):
        if node_index != source["compute_index"]:
            _add_focus_link(link_traffic, focus_card, _card_id(node_index, focus["card_index"]), share)


def _add_destination_2dfm_focus_traffic(
    topology: MultiRailTopology,
    link_traffic: dict[LinkId, float],
    source_card: str,
    destination_card: str,
    focus_card: str,
    card_attrs: dict[str, dict[str, int]] | None = None,
) -> None:
    source = _cached_card_attrs(topology, source_card, card_attrs)
    destination = _cached_card_attrs(topology, destination_card, card_attrs)
    focus = _cached_card_attrs(topology, focus_card, card_attrs)
    domain_size = int(topology.config.fm2d_domain_size)
    group_cards = _switch_group_cards(topology, source["switch_group"])
    candidate_count = domain_size * len(group_cards)
    share = 1.0 / candidate_count
    switch_id = _switch_id(source["switch_group"])

    if source_card == focus_card:
        _add_focus_link(link_traffic, focus_card, switch_id, 1.0)

    if (
        focus["fm2d_domain"] == destination["fm2d_domain"]
        and focus["switch_group"] == source["switch_group"]
    ):
        path = _inside_2dfm_path(focus_card, destination_card)
        if len(path) > 1:
            _add_focus_link(link_traffic, focus_card, path[1], share)

    if (
        focus["compute_index"] in _nodes_in_domain(topology, destination["fm2d_domain"])
        and focus["compute_index"] != destination["compute_index"]
        and focus["card_index"] == destination["card_index"]
        and destination["card_index"] not in group_cards
    ):
        # destination-index middle cards are reached from entries with same node but different card.
        _add_focus_link(link_traffic, focus_card, destination_card, len(group_cards) * share)


def _inside_2dfm_path(source_card: str, destination_card: str) -> list[str]:
    source_node, source_index = _parse_card_id(source_card)
    destination_node, destination_index = _parse_card_id(destination_card)
    if source_card == destination_card:
        return [source_card]
    if source_node == destination_node or source_index == destination_index:
        return [source_card, destination_card]
    return [source_card, _card_id(source_node, destination_index), destination_card]


def _add_focus_path_traffic(
    link_traffic: dict[LinkId, float],
    focus_card: str,
    path: list[str],
    share: float,
) -> None:
    for source, target in _path_links(path):
        if source == focus_card:
            _add_focus_link(link_traffic, focus_card, target, share)


def _add_focus_link(
    link_traffic: dict[LinkId, float],
    focus_card: str,
    target: str,
    traffic: float,
) -> None:
    link = (focus_card, target)
    if link in link_traffic:
        link_traffic[link] += traffic


def _card_attrs(topology: MultiRailTopology, card_id: str) -> dict[str, int]:
    attrs = topology.graph.nodes[card_id]
    return {
        "compute_index": int(attrs["compute_index"]),
        "card_index": int(attrs["card_index"]),
        "switch_group": int(attrs["switch_group"]),
        "fm2d_domain": int(attrs.get("fm2d_domain", -1)),
    }


def _cached_card_attrs(
    topology: MultiRailTopology,
    card_id: str,
    card_attrs: dict[str, dict[str, int]] | None,
) -> dict[str, int]:
    if card_attrs is None:
        return _card_attrs(topology, card_id)
    return card_attrs[card_id]


def _switch_group_cards(topology: MultiRailTopology, switch_group: int) -> list[int]:
    return topology.card_groups_for_node(0)[switch_group]


def _switch_group_size(topology: MultiRailTopology, switch_group: int) -> int:
    return len(_switch_group_cards(topology, switch_group))


def _nodes_in_domain(topology: MultiRailTopology, domain_index: int) -> list[int]:
    if topology.config.topology_type != TopologyType.TWO_D_FM_CLOS:
        return []
    return topology.nodes_in_fm2d_domain(domain_index)


def _parse_card_id(card_id: str) -> tuple[int, int]:
    node_part, card_part = card_id.split("-card")
    return int(node_part.removeprefix("node")), int(card_part)


def _card_id(node_index: int, card_index: int) -> str:
    return f"node{node_index}-card{card_index}"


def _switch_id(switch_index: int) -> str:
    return f"switch{switch_index}"


def _render_topology_metadata(topology: MultiRailTopology) -> list[str]:
    if topology.config.topology_type != TopologyType.SPARSE_CLOS or topology.config.sparse_clos is None:
        return []

    params = derive_bst_parameters(topology.config.sparse_clos)
    return [
        f"bst_v: {params['bst_v']}",
        f"bst_r: {params['bst_r']}",
        f"bst_b: {params['bst_b']}",
        f"bst_k: {params['bst_k']}",
        f"bst_lambda: {params['bst_lambda']}",
        f"cluster_size: {params['cluster_size']}",
        f"total_cards: {params['total_cards']}",
    ]


def _render_result(result: SimulationResult) -> list[str]:
    max_link = (
        _format_short_link(result.max_loaded_adjacent_link)
        if result.max_loaded_adjacent_link is not None
        else "none"
    )
    lines = [
        f"domain_size: {result.domain_size}",
        f"focus_card_sent_flows: {result.focus_card_sent_flows}",
        f"focus_card_port_count: {result.focus_card_port_count}",
        f"focus_card_efficiency_denominator: {result.focus_card_efficiency_denominator:.6f}",
        f"focus_card_bandwidth_efficiency: {result.focus_card_bandwidth_efficiency:.6f}",
        f"focus_card_link_loads: {_format_focus_card_link_loads(result)}",
        f"focus_card_link_traffic: {_format_focus_card_link_traffic_values(result)}",
    ]
    if result.routing_mode == RoutingMode.DETOUR_ROUTING:
        lines.append(f"detour_types: {_format_detour_types(result)}")
    if result.latency_result is not None:
        lines.extend(
            [
                f"single_rtt_latency_ns: {result.latency_result.single_rtt_latency_ns:.6f}",
                f"single_rtt_latency_pair: {result.latency_result.source} -> {result.latency_result.destination}",
                f"single_rtt_latency_path: {' -> '.join(result.latency_result.path)}",
            ]
        )

    lines.extend(
        [
            f"max_loaded_adjacent_link: {max_link}",
            f"max_adjacent_link_load: {result.max_adjacent_link_load:.6f}",
        ]
    )
    return lines


def _render_compact_summary_table(results: list[SimulationResult]) -> list[str]:
    has_latency = any(result.latency_result is not None for result in results)
    has_route_types = any(result.routing_mode == RoutingMode.DETOUR_ROUTING for result in results)
    header = "| 通信域 D | efficiency |"
    separator = "|---:|---:|"
    if has_route_types:
        header = f"{header} route_types |"
        separator = f"{separator}---|"
    header = f"{header} focus_card_link_traffic |"
    separator = f"{separator}---|"
    if has_latency:
        header = f"{header} single_rtt_latency_ns |"
        separator = f"{separator}---:|"

    lines = [header, separator]
    for result in results:
        row = (
            "| "
            f"{result.domain_size} | "
            f"{result.focus_card_bandwidth_efficiency:.6f} |"
        )
        if has_route_types:
            row = f"{row} {_format_detour_types(result)} |"
        row = f"{row} {_format_focus_card_link_traffic_values(result)} |"
        if has_latency:
            latency = result.latency_result.single_rtt_latency_ns if result.latency_result is not None else 0.0
            row = f"{row} {latency:.6f} |"
        lines.append(row)
    return lines


def _render_summary_table(results: list[SimulationResult]) -> list[str]:
    has_latency = any(result.latency_result is not None for result in results)
    has_route_types = any(result.routing_mode == RoutingMode.DETOUR_ROUTING for result in results)
    header = "| 通信域 D | S = D - 1 | 瓶颈链路 | L_max | denominator | efficiency | focus_card_link_traffic |"
    separator = "|---:|---:|---|---:|---:|---:|---|"
    if has_route_types:
        header = f"{header} route_types |"
        separator = f"{separator}---|"
    if has_latency:
        header = f"{header} single_rtt_latency_ns |"
        separator = f"{separator}---:|"
    lines = [header, separator]
    for result in results:
        max_link = (
            _format_short_link(result.max_loaded_adjacent_link)
            if result.max_loaded_adjacent_link is not None
            else "none"
        )
        row = (
            "| "
            f"{result.domain_size} | "
            f"{result.focus_card_sent_flows} | "
            f"{max_link} | "
            f"{result.max_adjacent_link_load:.6f} | "
            f"{result.focus_card_efficiency_denominator:.6f} | "
            f"{result.focus_card_bandwidth_efficiency:.6f} | "
            f"{_format_focus_card_link_traffic_values(result)} |"
        )
        if has_route_types:
            row = f"{row} {_format_detour_types(result)} |"
        if has_latency:
            latency = result.latency_result.single_rtt_latency_ns if result.latency_result is not None else 0.0
            row = f"{row} {latency:.6f} |"
        lines.append(row)
    return lines


def _default_domain_sizes(topology: MultiRailTopology, card_count: int) -> list[int]:
    if topology.config.topology_type != TopologyType.SPARSE_CLOS:
        return factors(card_count)

    cluster_size = topology.config.N
    small_domains = [value for value in factors(cluster_size) if value != 1]
    large_domains = list(range(cluster_size * 2, card_count + 1, cluster_size))
    return small_domains + large_domains


def _allows_focus_domain(topology: MultiRailTopology, domain_size: int, card_count: int) -> bool:
    return topology.config.topology_type == TopologyType.SPARSE_CLOS and domain_size <= card_count


def _communication_domains(
    topology: MultiRailTopology,
    cards: list[str],
    domain_size: int,
    focus_card: str,
) -> list[list[str]]:
    if len(cards) % domain_size == 0:
        return [cards[index:index + domain_size] for index in range(0, len(cards), domain_size)]
    if _allows_focus_domain(topology, domain_size, len(cards)):
        return [_focus_domain_cards(cards, domain_size, focus_card)]
    raise ValueError("domain_size must divide total card count")


def _focus_domain_cards(cards: list[str], domain_size: int, focus_card: str) -> list[str]:
    if focus_card not in cards:
        raise ValueError(f"Unknown focus_card: {focus_card}")
    focus_index = cards.index(focus_card)
    start = (focus_index // domain_size) * domain_size
    if start + domain_size > len(cards):
        start = len(cards) - domain_size
    return cards[start:start + domain_size]


def _latency_for_domain_groups(
    topology: MultiRailTopology,
    cards: list[str],
    domain_size: int,
    mode: RoutingMode,
    latency_config: LatencyConfig | None,
    focus_card: str,
) -> LatencyResult | None:
    if latency_config is None:
        return None
    if topology.config.topology_type != TopologyType.SPARSE_CLOS or len(cards) % domain_size == 0:
        return max_domain_size_rtt_latency(topology, cards, domain_size, mode, latency_config)

    best: LatencyResult | None = None
    for domain_cards in _communication_domains(topology, cards, domain_size, focus_card):
        current = max_domain_rtt_latency(topology, domain_cards, mode, latency_config)
        if best is None or current.single_rtt_latency_ns > best.single_rtt_latency_ns:
            best = current
    return best


def _parallel_work_chunks(
    topology: MultiRailTopology,
    cards: list[str],
    domain_size: int,
    worker_count: int,
    focus_card: str,
) -> list[list[tuple[list[str], list[str]]]]:
    units: list[tuple[list[str], list[str]]] = []
    target_units_per_domain = max(1, worker_count * 4)
    source_batch_size = max(1, ceil(domain_size / target_units_per_domain))
    for domain_cards in _communication_domains(topology, cards, domain_size, focus_card):
        for index in range(0, len(domain_cards), source_batch_size):
            units.append((domain_cards[index:index + source_batch_size], domain_cards))

    chunk_count = min(max(1, worker_count), len(units))
    chunks: list[list[tuple[list[str], list[str]]]] = [[] for _ in range(chunk_count)]
    for index, unit in enumerate(units):
        chunks[index % chunk_count].append(unit)
    return [chunk for chunk in chunks if chunk]


def _simulate_work_chunk(
    topology: MultiRailTopology,
    work_units: list[tuple[list[str], list[str]]],
    mode: RoutingMode,
    domain_size: int | None,
) -> tuple[dict[LinkId, float], int, dict[str, int]]:
    route_cache: RouteCache = {}
    link_traffic: dict[LinkId, float] = {}
    route_type_counts: dict[str, int] = {}
    processed_pairs = 0

    for source_cards, domain_cards in work_units:
        for source_card in source_cards:
            for destination_card in domain_cards:
                if source_card == destination_card:
                    continue

                route = _cached_route(
                    topology,
                    source_card,
                    destination_card,
                    mode,
                    domain_size,
                    route_cache,
                )
                _record_route_type(route_type_counts, route)
                for path, traffic_share in route.weighted_paths():
                    for link in _path_links(path):
                        link_traffic[link] = link_traffic.get(link, 0.0) + traffic_share
                processed_pairs += 1

    return link_traffic, processed_pairs, route_type_counts


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


def _path_links(path: list[str]) -> list[LinkId]:
    return [(path[index], path[index + 1]) for index in range(len(path) - 1)]


def _record_route_type(route_type_counts: dict[str, int], route: RouteResult) -> None:
    route_type_counts[route.route_type] = route_type_counts.get(route.route_type, 0) + 1


def _merge_route_type_counts(
    route_type_counts: dict[str, int],
    partial_route_types: dict[str, int],
) -> None:
    for route_type, count in partial_route_types.items():
        route_type_counts[route_type] = route_type_counts.get(route_type, 0) + count


def _format_detour_types(result: SimulationResult) -> str:
    detour_types = sorted(
        route_type
        for route_type, count in result.route_type_counts.items()
        if count > 0 and route_type.endswith("_detour")
    )
    return ", ".join(detour_types) if detour_types else "none"


def _fallback_to_shortest_if_detour_is_worse(
    topology: MultiRailTopology,
    result: SimulationResult,
    mode: RoutingMode,
    focus_card: str,
    domain_index: int,
    domain_count: int,
    workers: int,
    focus_only: bool,
    latency_config: LatencyConfig | None,
) -> SimulationResult:
    if mode != RoutingMode.DETOUR_ROUTING:
        return result
    if not any(route_type.endswith("_detour") for route_type in result.route_type_counts):
        return result

    shortest = simulate_domain_size(
        topology,
        result.domain_size,
        mode=RoutingMode.SHORTEST_PATH,
        focus_card=focus_card,
        progress_callback=None,
        domain_index=domain_index,
        domain_count=domain_count,
        workers=workers,
        focus_only=focus_only,
        latency_config=latency_config,
    )
    if shortest.focus_card_bandwidth_efficiency > result.focus_card_bandwidth_efficiency:
        return replace(shortest, routing_mode=RoutingMode.DETOUR_ROUTING)
    return result


def _cached_route(
    topology: MultiRailTopology,
    source_card: str,
    destination_card: str,
    mode: RoutingMode,
    domain_size: int | None,
    route_cache: RouteCache | None,
) -> RouteResult:
    if route_cache is None:
        return route_between_cards(
            topology,
            source_card,
            destination_card,
            mode,
            domain_size=domain_size,
        )

    key = (source_card, destination_card, mode, domain_size)
    route = route_cache.get(key)
    if route is None:
        route = route_between_cards(
            topology,
            source_card,
            destination_card,
            mode,
            domain_size=domain_size,
        )
        if len(route_cache) < ROUTE_CACHE_LIMIT:
            route_cache[key] = route
    return route


def _adjacent_links(topology: MultiRailTopology, card_id: str) -> list[LinkId]:
    return sorted(
        ((card_id, neighbor) for neighbor in topology.graph.neighbors(card_id)),
        key=_adjacent_link_sort_key,
    )


def _link_bandwidth(topology: MultiRailTopology, link: LinkId) -> float:
    return float(topology.graph.edges[link]["bandwidth"])


def _focus_card_efficiency_denominator(
    topology: MultiRailTopology,
    link_traffic: dict[LinkId, float],
    adjacent_links: list[LinkId],
    max_loaded_adjacent_link: LinkId | None,
    max_adjacent_link_load: float,
) -> float:
    if max_loaded_adjacent_link is None:
        return 0.0

    denominator = 0.0
    for link in adjacent_links:
        if link == max_loaded_adjacent_link:
            denominator += link_traffic[link]
        else:
            denominator += max_adjacent_link_load * _link_bandwidth(topology, link)
    return denominator


def _format_focus_card_link_loads(result: SimulationResult) -> str:
    items = [
        f"{_format_short_node(link[0])}->{_format_short_node(link[1])}={_format_compact_number(result.link_loads[link])}"
        for link in _ordered_focus_card_links(result)
    ]
    return f"[{', '.join(items)}]"


def _format_focus_card_link_traffic_values(result: SimulationResult) -> str:
    values = [
        _format_compact_number(result.focus_card_adjacent_link_traffic[link])
        for link in _ordered_focus_card_links(result)
    ]
    return f"[{', '.join(values)}]"


def _ordered_focus_card_links(result: SimulationResult) -> list[LinkId]:
    return sorted(result.focus_card_adjacent_link_traffic, key=_adjacent_link_sort_key)


def _format_link(link: LinkId) -> str:
    return f"{link[0]} -> {link[1]}"


def _format_short_link(link: LinkId) -> str:
    return f"{_format_short_node(link[0])} -> {_format_short_node(link[1])}"


def _format_short_node(node_id: str) -> str:
    if node_id.startswith("node") and "-card" in node_id:
        node_part, card_part = node_id.split("-card")
        return f"N{node_part.removeprefix('node')}_C{card_part}"
    if node_id.startswith("switch"):
        return f"S{node_id.removeprefix('switch')}"
    return node_id


def _format_compact_number(value: float) -> str:
    formatted = f"{value:.6f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"


def _adjacent_link_sort_key(link: LinkId) -> tuple[int, int, str]:
    source = link[0]
    target = link[1]
    if target.startswith("node") and "-card" in target:
        source_node = int(source.split("-card")[0].removeprefix("node"))
        target_node = int(target.split("-card")[0].removeprefix("node"))
        target_card = int(target.split("-card")[1])
        if source_node == target_node:
            return (0, target_card, target)
        return (1, target_node, target)
    if target.startswith("switch"):
        return (2, int(target.removeprefix("switch")), target)
    return (3, 0, target)
