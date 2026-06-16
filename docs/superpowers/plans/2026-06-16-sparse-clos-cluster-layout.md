# SparseClos Cluster Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a SparseClos layout option where all same-index cards across physical nodes form one logical cluster.

**Architecture:** Keep `sparse-clos` as the topology type and add `cluster_layout` to `SparseClosConfig`. The graph will expose both physical attributes (`compute_index`, `card_index`) and logical SparseClos attributes (`cluster_index`, `cluster_card_index`) so routing, simulation, latency, reports, and visualization can use the right semantic layer.

**Tech Stack:** Python dataclasses/enums, NetworkX graph construction, existing pytest coverage, existing CLI/config path.

---

### Task 1: Configuration And Validation

**Files:**
- Modify: `multirail_topology/sparse_clos.py`
- Modify: `multirail_topology/cli.py`
- Test: `tests/test_sparse_clos.py`

- [ ] Add `ClusterLayout` enum with `contiguous` and `same-index-across-nodes`.
- [ ] Add `cluster_layout` to `SparseClosConfig`, defaulting to `contiguous`.
- [ ] Validate `same-index-across-nodes` requires derived `bst_v == 8`.
- [ ] Add CLI/config parsing for `--cluster-layout`.
- [ ] Add failing tests first for default config, JSON/CLI config, and invalid `v != 8` layout.

### Task 2: Topology Construction

**Files:**
- Modify: `multirail_topology/topology.py`
- Test: `tests/test_sparse_clos.py`
- Test: `tests/test_topology.py`

- [ ] For `contiguous`, preserve current graph shape and add `cluster_index == compute_index`, `cluster_card_index == card_index`.
- [ ] For `same-index-across-nodes`, build `cluster_size` physical nodes with `v` cards each.
- [ ] In `same-index-across-nodes`, connect switch blocks to all physical nodes' same-index cards.
- [ ] In `same-index-across-nodes` and `fullmesh-plus-switch`, add fullmesh within each physical 8P node; do not fullmesh same-index cards across physical nodes.
- [ ] Add tests for node/card/switch edge counts and card metadata.

### Task 3: Routing And Detour Semantics

**Files:**
- Modify: `multirail_topology/routing.py`
- Test: `tests/test_routing.py`
- Test: `tests/test_simulation.py`

- [ ] Replace SparseClos cluster checks with `cluster_index` attributes.
- [ ] Keep physical fullmesh direct paths available through graph shortest paths.
- [ ] For `same-index-across-nodes`, allow `card_detour` only for `domain_size <= cards_per_physical_node`.
- [ ] For `same-index-across-nodes`, return shortest-path for `domain_size > cards_per_physical_node`, with no `cluster_detour`.
- [ ] Add tests proving EP=16 in same-index layout reports `none` route types.

### Task 4: Reporting, Visualization, Docs

**Files:**
- Modify: `multirail_topology/simulation.py`
- Modify: `multirail_topology/visualize.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`
- Test: `tests/test_sparse_clos.py`

- [ ] Add `cluster_layout`, `physical_node_count`, and `cards_per_physical_node` to SparseClos report metadata.
- [ ] Ensure card ordering for same-index layout is physical-node first.
- [ ] Update visualization hover/layout metadata to include `cluster_index` and `cluster_card_index`.
- [ ] Update README with CLI and JSON examples.
- [ ] Run full pytest and a representative CLI command.
