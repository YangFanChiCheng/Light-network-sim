# SparseClos BST Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `sparse-clos` topology type with BST `(v, r, b, k, lambda)` derivation, shortest-path routing, bandwidth efficiency, latency, config-file support, and separated visualization views.

**Architecture:** Add focused SparseClos helpers for BST derivation and block generation, then plug them into the existing `MultiRailTopology` graph builder. Reuse the current simulation formula by making shortest-path routing return all equal shortest paths and extending domain selection for SparseClos defaults.

**Tech Stack:** Python dataclasses/enums, NetworkX graph/path APIs, Plotly HTML export, pytest.

---

### Task 1: SparseClos Config And BST Blocks

**Files:**
- Modify: `multirail_topology/config.py`
- Create: `multirail_topology/sparse_clos.py`
- Test: `tests/test_sparse_clos.py`

- [ ] Write failing tests for BST derivation, `r=16,k=3 -> v=33,b=176`, `k=2` pair blocks, `k=3,v=33` blocks, and cluster size derivation.
- [ ] Run `python -m pytest tests/test_sparse_clos.py -v` and verify failures are due to missing SparseClos code.
- [ ] Implement `SparseClosConfig`, `ClusterInternalMode`, `derive_bst_parameters()`, `generate_bst_blocks()`, and block validation.
- [ ] Run `python -m pytest tests/test_sparse_clos.py -v` and verify the tests pass.

### Task 2: Graph Construction

**Files:**
- Modify: `multirail_topology/topology.py`
- Modify: `multirail_topology/config.py`
- Test: `tests/test_topology.py`

- [ ] Write failing tests for SparseClos node/edge counts and internal modes.
- [ ] Run targeted topology tests and verify failures are due to missing graph support.
- [ ] Build SparseClos graphs with clusters as compute nodes, `b` switch nodes, per-card `r` switch edges, and optional 8P fullmesh groups.
- [ ] Run targeted topology tests and verify they pass.

### Task 3: Shortest-Path Routing And Latency

**Files:**
- Modify: `multirail_topology/routing.py`
- Modify: `multirail_topology/latency.py`
- Test: `tests/test_routing.py`
- Test: `tests/test_latency.py`

- [ ] Write failing tests for `shortest-path` and equal shortest-path splitting readiness.
- [ ] Run targeted routing/latency tests and verify expected failures.
- [ ] Implement `RoutingMode.SHORTEST_PATH` using NetworkX all-shortest-paths.
- [ ] Ensure latency uses the returned shortest paths and existing switch-link timing.
- [ ] Run targeted routing/latency tests and verify they pass.

### Task 4: SparseClos Domain Sizes And Simulation

**Files:**
- Modify: `multirail_topology/simulation.py`
- Test: `tests/test_simulation.py`

- [ ] Write failing tests for SparseClos domain sequence and non-dividing focus-card domain simulation.
- [ ] Run targeted simulation tests and verify expected failures.
- [ ] Add SparseClos default domain-size generation and focus-domain simulation path.
- [ ] Include BST metadata in SparseClos simulation reports.
- [ ] Run targeted simulation tests and verify they pass.

### Task 5: CLI, Config File, And Visualization

**Files:**
- Modify: `multirail_topology/cli.py`
- Modify: `multirail_topology/visualize.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`
- Test: `tests/test_topology.py`

- [ ] Write failing CLI/config and HTML export tests.
- [ ] Run targeted tests and verify expected failures.
- [ ] Add CLI and JSON config parsing for `sparse_clos`.
- [ ] Add SparseClos cluster-level and representative cluster visualization.
- [ ] Update README with a SparseClos JSON example.
- [ ] Run targeted tests and then the full test suite.
