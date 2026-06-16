# Multi-Rail Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python tool that constructs a configurable multi-rail topology and exports an interactive HTML visualization.

**Architecture:** Use a validated dataclass for user inputs, a NetworkX graph builder for topology construction, and Plotly for a standalone interactive graph. Keep routing and simulation as importable modules with explicit future extension points.

**Tech Stack:** Python 3, NetworkX, Plotly, pytest.

---

## File Structure

- `multirail_topology/__init__.py`: public package exports.
- `multirail_topology/config.py`: `MultiRailTopologyConfig` dataclass and validation.
- `multirail_topology/topology.py`: graph construction, group assignment, and summary counts.
- `multirail_topology/visualize.py`: deterministic Plotly visualization and HTML export.
- `multirail_topology/routing.py`: future routing module marker.
- `multirail_topology/simulation.py`: future simulation module marker.
- `main.py`: command-line entry point.
- `requirements.txt`: runtime and test dependencies.
- `tests/test_topology.py`: topology validation and graph count tests.

### Task 1: Configuration Validation

**Files:**
- Create: `multirail_topology/config.py`
- Create: `multirail_topology/__init__.py`
- Test: `tests/test_topology.py`

- [ ] **Step 1: Create failing validation tests**

```python
import pytest

from multirail_topology import MultiRailTopologyConfig


def test_config_rejects_switch_count_greater_than_cards():
    with pytest.raises(ValueError, match="X cannot exceed N"):
        MultiRailTopologyConfig(M=2, N=2, X=3)


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
```

- [ ] **Step 2: Run test and verify import failure**

Run: `pytest tests/test_topology.py -v`
Expected: FAIL because `multirail_topology` does not exist.

- [ ] **Step 3: Implement config and exports**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MultiRailTopologyConfig:
    M: int
    N: int
    X: int
    intra_bandwidth: float = 200.0
    switch_bandwidth: float = 100.0

    def __post_init__(self) -> None:
        for name in ("M", "N", "X"):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

        if self.X > self.N:
            raise ValueError("X cannot exceed N; each switch group needs at least one card")

        for name in ("intra_bandwidth", "switch_bandwidth"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be a positive number")
```

- [ ] **Step 4: Run validation tests**

Run: `pytest tests/test_topology.py -v`
Expected: PASS for validation tests.

### Task 2: Topology Graph Construction

**Files:**
- Create: `multirail_topology/topology.py`
- Modify: `multirail_topology/__init__.py`
- Test: `tests/test_topology.py`

- [ ] **Step 1: Add graph count and grouping tests**

```python
from multirail_topology import MultiRailTopology, MultiRailTopologyConfig


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
        "total_nodes": 12,
        "total_edges": 20,
    }
    assert graph.nodes["node0-card0"]["switch_group"] == 0
    assert graph.nodes["node0-card3"]["switch_group"] == 1


def test_topology_groups_cards_evenly_when_not_divisible():
    config = MultiRailTopologyConfig(M=1, N=5, X=2)
    topology = MultiRailTopology(config)
    topology.build_graph()

    groups = topology.card_groups_for_node(0)

    assert groups == [[0, 1, 2], [3, 4]]
```

- [ ] **Step 2: Run test and verify missing topology failure**

Run: `pytest tests/test_topology.py -v`
Expected: FAIL because `MultiRailTopology` is not exported.

- [ ] **Step 3: Implement topology builder**

Implement:
- `MultiRailTopology.build_graph()`
- `MultiRailTopology.card_groups_for_node(node_index)`
- `MultiRailTopology.summary()`

Use node ids:
- compute: `node{i}`
- card: `node{i}-card{j}`
- switch: `switch{k}`

- [ ] **Step 4: Run graph tests**

Run: `pytest tests/test_topology.py -v`
Expected: PASS.

### Task 3: Interactive Visualization And CLI

**Files:**
- Create: `multirail_topology/visualize.py`
- Create: `multirail_topology/routing.py`
- Create: `multirail_topology/simulation.py`
- Create: `main.py`
- Create: `requirements.txt`

- [ ] **Step 1: Implement Plotly visualization**

Implement:
- `build_positions(topology)`
- `create_topology_figure(topology)`
- `export_topology_html(topology, output_path)`

The figure uses separate traces for compute nodes, card nodes, switch nodes, intra links, and switch links so hover text and styling are clear.

- [ ] **Step 2: Implement CLI**

Add argparse options:
- `--nodes`
- `--cards`
- `--switches`
- `--intra-bandwidth`
- `--switch-bandwidth`
- `--output`

Print graph summary and output path after successful generation.

- [ ] **Step 3: Add dependencies**

Add:

```text
networkx>=3.2
plotly>=5.20
pytest>=8.0
```

- [ ] **Step 4: Run generation command**

Run: `python main.py --nodes 3 --cards 4 --switches 2 --output topology.html`
Expected: command prints summary and creates `topology.html`.

## Self-Review

- Spec coverage: configuration, full mesh links, switch grouping, bandwidth attributes, interactive HTML visualization, and future routing/simulation modules are covered.
- Placeholder scan: no task relies on unspecified code; deferred modules are intentionally marker modules.
- Type consistency: config class, topology class, method names, and CLI argument names are consistent across tasks.

