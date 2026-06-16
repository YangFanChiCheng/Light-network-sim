import subprocess
import sys
import json
from pathlib import Path


def test_cli_writes_topology_and_route_files():
    topology_output = Path("test_outputs/cli_topology.html")
    routes_output = Path("test_outputs/cli_routes.txt")
    simulation_output = Path("test_outputs/cli_simulation.txt")
    all_links_output = Path("test_outputs/cli_all_links.txt")

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--nodes",
            "2",
            "--cards",
            "4",
            "--switches",
            "2",
            "--routing-mode",
            "destination-node-jump",
            "--output",
            str(topology_output),
            "--routes-output",
            str(routes_output),
            "--simulation-output",
            str(simulation_output),
            "--all-links-output",
            str(all_links_output),
            "--domain-size",
            "4",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert topology_output.exists()
    assert routes_output.exists()
    assert simulation_output.exists()
    assert all_links_output.exists()
    assert "Routes written to:" in result.stdout
    assert "Simulation written to:" in result.stdout
    assert "All-link traffic written to:" in result.stdout
    assert "destination_node_jump" in routes_output.read_text(encoding="utf-8")
    simulation_report = simulation_output.read_text(encoding="utf-8")
    assert "domain_size: 4" in simulation_report
    assert "all_links:" not in simulation_report
    assert "node0-card0 -> switch0 | traffic=" in all_links_output.read_text(encoding="utf-8")


def test_cli_accepts_2d_topology_parameters():
    topology_output = Path("test_outputs/cli_2d_topology.html")
    routes_output = Path("test_outputs/cli_2d_routes.txt")
    simulation_output = Path("test_outputs/cli_2d_simulation.txt")
    all_links_output = Path("test_outputs/cli_2d_all_links.txt")

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--topology-type",
            "2d-fm-clos",
            "--nodes",
            "4",
            "--cards",
            "4",
            "--switches",
            "2",
            "--fm2d-domain-size",
            "2",
            "--fm2d-bandwidth",
            "300",
            "--routing-mode",
            "destination-2dfm-jump",
            "--output",
            str(topology_output),
            "--routes-output",
            str(routes_output),
            "--simulation-output",
            str(simulation_output),
            "--all-links-output",
            str(all_links_output),
            "--domain-size",
            "4",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert topology_output.exists()
    assert "fm2d_links:" in result.stdout
    assert "destination_2dfm_jump" in routes_output.read_text(encoding="utf-8")
    assert "node0-card0 -> node1-card0 | traffic=" in all_links_output.read_text(encoding="utf-8")


def test_cli_skips_topology_html_when_card_count_exceeds_256():
    topology_output = Path("test_outputs/cli_large_topology.html")
    simulation_output = Path("test_outputs/cli_large_simulation.txt")
    if topology_output.exists():
        topology_output.unlink()

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--nodes",
            "33",
            "--cards",
            "8",
            "--switches",
            "2",
            "--output",
            str(topology_output),
            "--simulation-output",
            str(simulation_output),
            "--domain-size",
            "8",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not topology_output.exists()
    assert simulation_output.exists()
    assert "HTML output skipped because total card count 264 exceeds 256." in result.stdout


def test_cli_prints_simulation_progress_by_default():
    simulation_output = Path("test_outputs/cli_progress_simulation.txt")

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--nodes",
            "2",
            "--cards",
            "4",
            "--switches",
            "2",
            "--simulation-output",
            str(simulation_output),
            "--domain-size",
            "4",
            "--progress-interval",
            "0",
            "--workers",
            "2",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Simulation domains: 1, workers: 2" in result.stdout
    assert "Simulating domain 1/1: D=4" in result.stdout
    assert "[####################] 100%" in result.stdout
    assert "D=4 pairs" in result.stdout
    assert "Finished D=4" in result.stdout


def test_cli_can_disable_simulation_progress():
    simulation_output = Path("test_outputs/cli_no_progress_simulation.txt")

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--nodes",
            "2",
            "--cards",
            "4",
            "--switches",
            "2",
            "--simulation-output",
            str(simulation_output),
            "--domain-size",
            "4",
            "--no-progress",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Simulation domains:" not in result.stdout
    assert "Simulating domain" not in result.stdout


def test_cli_accepts_worker_count():
    simulation_output = Path("test_outputs/cli_workers_simulation.txt")

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--nodes",
            "2",
            "--cards",
            "4",
            "--switches",
            "2",
            "--simulation-output",
            str(simulation_output),
            "--domain-size",
            "8",
            "--workers",
            "2",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "workers: 2" in result.stdout


def test_cli_accepts_run_config_file_with_topology_outputs_and_latency():
    config_path = Path("test_outputs/cli_run_config.json")
    topology_output = Path("test_outputs/cli_config_topology.html")
    simulation_output = Path("test_outputs/cli_config_simulation.txt")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "topology": {
                    "nodes": 2,
                    "cards": 2,
                    "switches": 1,
                    "intra_bandwidth": 10.0,
                    "switch_bandwidth": 5.0,
                },
                "routing_mode": "source-node-jump",
                "domain_sizes": [4],
                "focus_card": "node0-card0",
                "outputs": {
                    "topology": str(topology_output),
                    "simulation": str(simulation_output),
                },
                "no_progress": True,
                "latency": {
                    "switch_forward_latency_ns": 10.0,
                    "card_forward_latency_ns": 7.0,
                    "optical_module_latency_ns": 2.0,
                    "npu_processing_latency_ns": 100.0,
                    "intra_1dfm_link_length_m": 3.0,
                    "fm2d_link_length_m": 5.0,
                    "switch_link_length_m": 4.0,
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "main.py", "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert topology_output.exists()
    assert simulation_output.exists()
    report = simulation_output.read_text(encoding="utf-8")
    assert "single_rtt_latency_ns" in report
    assert "| 4 | 0.500000 | [1, 2] | 216.000000 |" in report
    assert "Simulation domains:" not in result.stdout


def test_cli_prints_latency_stage_after_pair_progress_when_latency_enabled():
    config_path = Path("test_outputs/cli_latency_progress_config.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "topology": {"nodes": 2, "cards": 2, "switches": 1},
                "routing_mode": "source-node-jump",
                "domain_sizes": [4],
                "outputs": {"simulation": "test_outputs/cli_latency_progress_simulation.txt"},
                "progress_interval": 0,
                "latency": {
                    "switch_forward_latency_ns": 10.0,
                    "card_forward_latency_ns": 7.0,
                    "optical_module_latency_ns": 2.0,
                    "npu_processing_latency_ns": 100.0,
                    "intra_1dfm_link_length_m": 3.0,
                    "fm2d_link_length_m": 5.0,
                    "switch_link_length_m": 4.0,
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "main.py", "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "D=4 pairs [####################] 100%" in result.stdout
    assert "D=4 latency calculation..." in result.stdout


def test_cli_accepts_sparse_clos_run_config_file():
    config_path = Path("test_outputs/cli_sparse_clos_config.json")
    topology_output = Path("test_outputs/cli_sparse_clos_topology.html")
    simulation_output = Path("test_outputs/cli_sparse_clos_simulation.txt")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "topology": {
                    "type": "sparse-clos",
                    "sparse_clos": {
                        "bst_r": 2,
                        "bst_k": 2,
                        "bst_lambda": 1,
                        "bst_v": 3,
                        "bst_b": 3,
                        "switch_port_num": 16,
                        "cluster_internal_mode": "fullmesh-plus-switch",
                    },
                    "intra_bandwidth": 50.0,
                    "switch_bandwidth": 100.0,
                },
                "routing_mode": "shortest-path",
                "domain_sizes": [8, 16],
                "focus_card": "node0-card0",
                "outputs": {
                    "topology": str(topology_output),
                    "simulation": str(simulation_output),
                },
                "no_progress": True,
                "latency": {
                    "switch_forward_latency_ns": 10.0,
                    "card_forward_latency_ns": 7.0,
                    "optical_module_latency_ns": 2.0,
                    "npu_processing_latency_ns": 100.0,
                    "intra_1dfm_link_length_m": 3.0,
                    "fm2d_link_length_m": 5.0,
                    "switch_link_length_m": 4.0,
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "main.py", "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert topology_output.exists()
    assert simulation_output.exists()
    report = simulation_output.read_text(encoding="utf-8")
    assert "routing_mode: shortest-path" in report
    assert "bst_v: 3" in report
    assert "domain_size: 16" in report
    assert "single_rtt_latency_ns" in report
    assert "SparseClos cluster view" in topology_output.read_text(encoding="utf-8")


def test_cli_accepts_sparse_clos_same_index_cluster_layout_config():
    config_path = Path("test_outputs/cli_sparse_clos_same_index_config.json")
    simulation_output = Path("test_outputs/cli_sparse_clos_same_index_simulation.txt")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "topology": {
                    "type": "sparse-clos",
                    "sparse_clos": {
                        "bst_r": 7,
                        "bst_k": 2,
                        "switch_port_num": 16,
                        "cluster_internal_mode": "fullmesh-plus-switch",
                        "cluster_layout": "same-index-across-nodes",
                    },
                    "intra_bandwidth": 50.0,
                    "switch_bandwidth": 50.0,
                },
                "routing": {"mode": "detour-routing"},
                "domain_sizes": [16],
                "focus_card": "node0-card0",
                "outputs": {"simulation": str(simulation_output)},
                "no_progress": True,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "main.py", "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = simulation_output.read_text(encoding="utf-8")
    assert "cluster_layout: same-index-across-nodes" in report
    assert "cards_per_physical_node: 8" in report
    assert "detour_types: cluster_detour" not in report
