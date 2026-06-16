from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import TopologyType, VisualizationDetail
from .latency import LatencyConfig, latency_config_from_mapping, load_latency_config
from .progress import ProgressPrinter
from .routing import RoutingMode, export_all_routes, export_representative_routes
from .simulation import export_all_link_traffic_report, export_simulation_report
from .sparse_clos import SparseClosConfig
from .topology import MultiRailTopology
from .config import MultiRailTopologyConfig
from .visualize import export_topology_html

MAX_VISUALIZED_CARDS = 256
DEFAULTS = {
    "topology_type": TopologyType.ONE_D_FM_CLOS.value,
    "nodes": 4,
    "cards": 8,
    "switches": 2,
    "intra_bandwidth": 200.0,
    "switch_bandwidth": 100.0,
    "fm2d_bandwidth": 200.0,
    "visualization_detail": VisualizationDetail.SIMPLIFIED.value,
    "output": "topology.html",
    "routing_mode": RoutingMode.SOURCE_NODE_JUMP.value,
    "focus_card": "node0-card0",
    "simulation_output": "simulation.txt",
    "progress_interval": 5.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a multi-rail topology HTML visualization.")
    parser.add_argument("--config", default=None, help="Optional JSON run config file.")
    parser.add_argument(
        "--topology-type",
        choices=[topology_type.value for topology_type in TopologyType],
        default=DEFAULTS["topology_type"],
        help="Topology type: 1d-fm-clos or 2d-fm-clos.",
    )
    parser.add_argument("--nodes", type=int, default=DEFAULTS["nodes"], help="Number of compute nodes M.")
    parser.add_argument("--cards", type=int, default=DEFAULTS["cards"], help="Number of cards per compute node N.")
    parser.add_argument("--switches", type=int, default=DEFAULTS["switches"], help="Number of switches X.")
    parser.add_argument(
        "--intra-bandwidth",
        type=float,
        default=DEFAULTS["intra_bandwidth"],
        help="Bandwidth of intra-node card full-mesh links.",
    )
    parser.add_argument(
        "--switch-bandwidth",
        type=float,
        default=DEFAULTS["switch_bandwidth"],
        help="Bandwidth of card-to-switch links.",
    )
    parser.add_argument(
        "--fm2d-domain-size",
        type=int,
        default=None,
        help="Number of compute nodes in each 2D full-mesh domain. Defaults to --cards.",
    )
    parser.add_argument(
        "--fm2d-bandwidth",
        type=float,
        default=DEFAULTS["fm2d_bandwidth"],
        help="Bandwidth of same-index cross-node 2D full-mesh links.",
    )
    parser.add_argument(
        "--visualization-detail",
        choices=[detail.value for detail in VisualizationDetail],
        default=DEFAULTS["visualization_detail"],
        help="Visualization detail level. simplified omits repeated visual clutter.",
    )
    parser.add_argument("--bst-r", type=int, default=None, help="SparseClos BST r value.")
    parser.add_argument("--bst-k", type=int, default=None, help="SparseClos BST k value.")
    parser.add_argument("--bst-lambda", type=int, default=None, help="SparseClos BST lambda value. Only 1 is supported.")
    parser.add_argument("--bst-v", type=int, default=None, help="Optional SparseClos BST v validation value.")
    parser.add_argument("--bst-b", type=int, default=None, help="Optional SparseClos BST b validation value.")
    parser.add_argument("--switch-port-num", type=int, default=None, help="SparseClos switch port count.")
    parser.add_argument(
        "--cluster-internal-mode",
        choices=["fullmesh-plus-switch", "switch-only"],
        default=None,
        help="SparseClos cluster internal connection mode.",
    )
    parser.add_argument("--output", default=DEFAULTS["output"], help="Output HTML path.")
    parser.add_argument(
        "--routing-mode",
        choices=[mode.value for mode in RoutingMode],
        default=DEFAULTS["routing_mode"],
        help="Routing mode used when source and destination cards connect to different switches.",
    )
    parser.add_argument(
        "--routes-output",
        default=None,
        help="Optional output path for a representative routing record. Omit for large topologies.",
    )
    parser.add_argument(
        "--all-routes",
        action="store_true",
        help="Write all card-pair routes instead of the representative two-domain sample.",
    )
    parser.add_argument(
        "--domain-size",
        type=int,
        action="append",
        default=None,
        help="Communication domain size to simulate. Repeat to simulate multiple sizes. Defaults to all factors.",
    )
    parser.add_argument(
        "--focus-card",
        default=DEFAULTS["focus_card"],
        help="Card used for adjacent-link traffic and bandwidth efficiency reporting.",
    )
    parser.add_argument(
        "--simulation-output",
        default=DEFAULTS["simulation_output"],
        help="Output path for the traffic simulation and bandwidth efficiency report.",
    )
    parser.add_argument(
        "--all-links-output",
        default=None,
        help="Optional output path for the full per-link traffic and load report. Omit for large topologies.",
    )
    parser.add_argument(
        "--latency-config",
        default=None,
        help="Optional JSON latency config file. Overrides the latency block in --config.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable command-line simulation progress output.",
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=DEFAULTS["progress_interval"],
        help="Minimum seconds between slow-progress updates. Percent milestones are still printed.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes for simulation. Defaults to the current machine CPU count.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_config = _load_run_config(args.config)
    topology_type = _resolve_value(args, run_config, "topology_type", DEFAULTS["topology_type"], ("topology", "topology_type"), ("topology", "type"))
    visualization_detail = _resolve_value(args, run_config, "visualization_detail", DEFAULTS["visualization_detail"], ("topology", "visualization_detail"))
    routing_mode = _resolve_value(args, run_config, "routing_mode", DEFAULTS["routing_mode"], ("routing", "mode"))
    output_path = _resolve_value(args, run_config, "output", DEFAULTS["output"], ("outputs", "topology"))
    routes_output = _resolve_value(args, run_config, "routes_output", None, ("outputs", "routes"))
    simulation_output_path = _resolve_value(args, run_config, "simulation_output", DEFAULTS["simulation_output"], ("outputs", "simulation"))
    all_links_output_path = _resolve_value(args, run_config, "all_links_output", None, ("outputs", "all_links"))
    domain_sizes = _resolve_domain_sizes(args, run_config)
    no_progress = _resolve_bool(args.no_progress, run_config, "no_progress", False)
    all_routes = _resolve_bool(args.all_routes, run_config, "all_routes", False)
    worker_count = args.workers if args.workers is not None else _config_lookup(run_config, ("workers",))
    worker_count = worker_count if worker_count is not None else (os.cpu_count() or 1)
    latency_config = _resolve_latency_config(args, run_config)
    sparse_clos_config = _resolve_sparse_clos_config(args, run_config, topology_type)

    config = MultiRailTopologyConfig(
        M=int(_resolve_value(args, run_config, "nodes", DEFAULTS["nodes"], ("topology", "nodes"))),
        N=int(_resolve_value(args, run_config, "cards", DEFAULTS["cards"], ("topology", "cards"))),
        X=int(_resolve_value(args, run_config, "switches", DEFAULTS["switches"], ("topology", "switches"))),
        intra_bandwidth=float(_resolve_value(args, run_config, "intra_bandwidth", DEFAULTS["intra_bandwidth"], ("topology", "intra_bandwidth"))),
        switch_bandwidth=float(_resolve_value(args, run_config, "switch_bandwidth", DEFAULTS["switch_bandwidth"], ("topology", "switch_bandwidth"))),
        topology_type=TopologyType(topology_type),
        fm2d_domain_size=_resolve_value(args, run_config, "fm2d_domain_size", None, ("topology", "fm2d_domain_size")),
        fm2d_bandwidth=float(_resolve_value(args, run_config, "fm2d_bandwidth", DEFAULTS["fm2d_bandwidth"], ("topology", "fm2d_bandwidth"))),
        visualization_detail=VisualizationDetail(visualization_detail),
        sparse_clos=sparse_clos_config,
    )
    topology = MultiRailTopology(config)
    topology.build_graph()
    total_cards = config.M * config.N
    output = None
    if total_cards <= MAX_VISUALIZED_CARDS:
        output = export_topology_html(topology, output_path)

    routes_path = None
    if routes_output:
        route_exporter = export_all_routes if all_routes else export_representative_routes
        routes_path = route_exporter(topology, routes_output, mode=RoutingMode(routing_mode))

    progress_callback = None if no_progress else ProgressPrinter()
    simulation_output = export_simulation_report(
        topology,
        simulation_output_path,
        domain_sizes=domain_sizes,
        mode=RoutingMode(routing_mode),
        focus_card=_resolve_value(args, run_config, "focus_card", DEFAULTS["focus_card"], ("simulation", "focus_card")),
        progress_callback=progress_callback,
        progress_interval=float(_resolve_value(args, run_config, "progress_interval", DEFAULTS["progress_interval"], ("progress", "interval"))),
        workers=int(worker_count),
        latency_config=latency_config,
    )

    all_links_output = None
    if all_links_output_path:
        all_links_output = export_all_link_traffic_report(
            topology,
            all_links_output_path,
            domain_sizes=domain_sizes,
            mode=RoutingMode(routing_mode),
            focus_card=_resolve_value(args, run_config, "focus_card", DEFAULTS["focus_card"], ("simulation", "focus_card")),
            progress_callback=progress_callback,
            progress_interval=float(_resolve_value(args, run_config, "progress_interval", DEFAULTS["progress_interval"], ("progress", "interval"))),
            workers=int(worker_count),
        )

    print("Topology summary:")
    for key, value in topology.summary().items():
        print(f"  {key}: {value}")
    if output is not None:
        print(f"HTML written to: {output.resolve()}")
    else:
        print(f"HTML output skipped because total card count {total_cards} exceeds {MAX_VISUALIZED_CARDS}.")
    if routes_path is not None:
        print(f"Routes written to: {routes_path.resolve()}")
    else:
        print("Routes output skipped. Pass --routes-output to write it.")
    print(f"Simulation written to: {simulation_output.resolve()}")
    if all_links_output is not None:
        print(f"All-link traffic written to: {all_links_output.resolve()}")
    else:
        print("All-link traffic output skipped. Pass --all-links-output to write it.")


def _load_run_config(path: str | None) -> dict[str, object]:
    if path is None:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _resolve_value(
    args: argparse.Namespace,
    config: dict[str, object],
    attr: str,
    default: object,
    *config_paths: tuple[str, ...],
) -> object:
    value = getattr(args, attr)
    if value != default and value is not None:
        return value
    for path in config_paths:
        config_value = _config_lookup(config, path)
        if config_value is not None:
            return config_value
    config_value = _config_lookup(config, (attr,))
    if config_value is not None:
        return config_value
    return value if value is not None else default


def _resolve_bool(
    cli_value: bool,
    config: dict[str, object],
    key: str,
    default: bool,
) -> bool:
    if cli_value:
        return True
    config_value = _config_lookup(config, (key,))
    if config_value is None:
        return default
    return bool(config_value)


def _resolve_domain_sizes(args: argparse.Namespace, config: dict[str, object]) -> list[int] | None:
    if args.domain_size is not None:
        return args.domain_size
    value = _config_lookup(config, ("domain_sizes",))
    if value is None:
        value = _config_lookup(config, ("domain_size",))
    if value is None:
        return None
    if isinstance(value, int):
        return [value]
    return [int(item) for item in value]


def _resolve_latency_config(args: argparse.Namespace, config: dict[str, object]) -> LatencyConfig | None:
    if args.latency_config:
        return load_latency_config(args.latency_config)
    latency_data = _config_lookup(config, ("latency",))
    if latency_data is None:
        return None
    if not isinstance(latency_data, dict):
        raise ValueError("latency config must be an object")
    return latency_config_from_mapping(latency_data)


def _resolve_sparse_clos_config(
    args: argparse.Namespace,
    config: dict[str, object],
    topology_type: object,
) -> SparseClosConfig | None:
    if TopologyType(topology_type) != TopologyType.SPARSE_CLOS:
        return None

    sparse_data: dict[str, object] = {}
    config_value = _config_lookup(config, ("topology", "sparse_clos"))
    if config_value is not None:
        if not isinstance(config_value, dict):
            raise ValueError("topology.sparse_clos config must be an object")
        sparse_data.update(config_value)

    key_map = {
        "bst_r": "bst_r",
        "bst_k": "bst_k",
        "bst_lambda": "bst_lambda",
        "bst_v": "bst_v",
        "bst_b": "bst_b",
        "switch_port_num": "switch_port_num",
        "cluster_internal_mode": "cluster_internal_mode",
    }
    for attr, key in key_map.items():
        cli_value = getattr(args, attr)
        if cli_value is not None:
            sparse_data[key] = cli_value
        config_flat_value = _config_lookup(config, ("topology", key))
        if config_flat_value is not None and key not in sparse_data:
            sparse_data[key] = config_flat_value

    return SparseClosConfig(**sparse_data)


def _config_lookup(config: dict[str, object], path: tuple[str, ...]) -> object | None:
    current: object = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current
