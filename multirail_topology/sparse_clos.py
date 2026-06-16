from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations


class ClusterInternalMode(StrEnum):
    FULLMESH_PLUS_SWITCH = "fullmesh-plus-switch"
    SWITCH_ONLY = "switch-only"


class ClusterLayout(StrEnum):
    CONTIGUOUS = "contiguous"
    SAME_INDEX_ACROSS_NODES = "same-index-across-nodes"


@dataclass(frozen=True)
class SparseClosConfig:
    bst_r: int
    bst_k: int
    switch_port_num: int
    bst_lambda: int = 1
    bst_v: int | None = None
    bst_b: int | None = None
    cluster_internal_mode: ClusterInternalMode = ClusterInternalMode.FULLMESH_PLUS_SWITCH
    cluster_layout: ClusterLayout = ClusterLayout.CONTIGUOUS

    def __post_init__(self) -> None:
        if isinstance(self.cluster_internal_mode, str):
            object.__setattr__(
                self,
                "cluster_internal_mode",
                ClusterInternalMode(self.cluster_internal_mode),
            )
        if isinstance(self.cluster_layout, str):
            object.__setattr__(
                self,
                "cluster_layout",
                ClusterLayout(self.cluster_layout),
            )

        for name in ("bst_r", "bst_k", "bst_lambda", "switch_port_num"):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

        if self.bst_k < 2:
            raise ValueError("bst_k must be at least 2")
        if self.bst_lambda != 1:
            raise ValueError("bst_lambda must be 1")

        derived_v = self.bst_r * (self.bst_k - 1) + 1
        if self.bst_v is not None and self.bst_v != derived_v:
            raise ValueError(f"bst_v must match derived value {derived_v}")
        object.__setattr__(self, "bst_v", derived_v)

        numerator = derived_v * self.bst_r
        if numerator % self.bst_k != 0:
            raise ValueError("derived bst_b must be an integer")
        derived_b = numerator // self.bst_k
        if self.bst_b is not None and self.bst_b != derived_b:
            raise ValueError(f"bst_b must match derived value {derived_b}")
        object.__setattr__(self, "bst_b", derived_b)

        cluster_size = self.switch_port_num // self.bst_k
        if cluster_size <= 0:
            raise ValueError("cluster_size must be positive")
        if (
            self.cluster_internal_mode == ClusterInternalMode.FULLMESH_PLUS_SWITCH
            and cluster_size % 8 != 0
        ):
            raise ValueError("cluster_size must be divisible by 8 for fullmesh-plus-switch")
        if self.cluster_layout == ClusterLayout.SAME_INDEX_ACROSS_NODES and derived_v != 8:
            raise ValueError("same-index-across-nodes requires bst_v to be 8")


def derive_bst_parameters(config: SparseClosConfig) -> dict[str, int]:
    cluster_size = config.switch_port_num // config.bst_k
    return {
        "bst_v": int(config.bst_v),
        "bst_r": config.bst_r,
        "bst_b": int(config.bst_b),
        "bst_k": config.bst_k,
        "bst_lambda": config.bst_lambda,
        "cluster_size": cluster_size,
        "total_cards": int(config.bst_v) * cluster_size,
        "physical_node_count": _physical_node_count(config, cluster_size),
        "cards_per_physical_node": _cards_per_physical_node(config, cluster_size),
    }


def _physical_node_count(config: SparseClosConfig, cluster_size: int) -> int:
    if config.cluster_layout == ClusterLayout.SAME_INDEX_ACROSS_NODES:
        return cluster_size
    return int(config.bst_v)


def _cards_per_physical_node(config: SparseClosConfig, cluster_size: int) -> int:
    if config.cluster_layout == ClusterLayout.SAME_INDEX_ACROSS_NODES:
        return int(config.bst_v)
    return cluster_size


def generate_bst_blocks(config: SparseClosConfig) -> tuple[tuple[int, ...], ...]:
    if config.bst_k == 2:
        blocks = tuple(combinations(range(int(config.bst_v)), 2))
    elif config.bst_k == 3:
        blocks = _generate_steiner_triples(int(config.bst_v))
    else:
        raise ValueError("SparseClos block generation currently supports bst_k 2 or 3")

    _validate_blocks(config, blocks)
    return blocks


def _generate_steiner_triples(v: int) -> tuple[tuple[int, int, int], ...]:
    if v % 6 != 3:
        raise ValueError("bst_k=3 generation currently supports v = 6t + 3")

    group_count = v // 3
    inv2 = pow(2, -1, group_count)

    def cluster_id(group: int, lane: int) -> int:
        return group * 3 + lane

    blocks: list[tuple[int, int, int]] = []
    for group in range(group_count):
        blocks.append(
            tuple(
                sorted(
                    (
                        cluster_id(group, 0),
                        cluster_id(group, 1),
                        cluster_id(group, 2),
                    )
                )
            )
        )

    for left in range(group_count):
        for right in range(left + 1, group_count):
            midpoint = ((left + right) * inv2) % group_count
            for lane in range(3):
                blocks.append(
                    tuple(
                        sorted(
                            (
                                cluster_id(left, lane),
                                cluster_id(right, lane),
                                cluster_id(midpoint, (lane + 1) % 3),
                            )
                        )
                    )
                )

    return tuple(blocks)


def _validate_blocks(
    config: SparseClosConfig,
    blocks: tuple[tuple[int, ...], ...],
) -> None:
    expected_v = int(config.bst_v)
    expected_b = int(config.bst_b)
    if len(blocks) != expected_b:
        raise ValueError(f"expected {expected_b} SparseClos blocks, got {len(blocks)}")

    cluster_degree = {cluster_id: 0 for cluster_id in range(expected_v)}
    pair_count: dict[tuple[int, int], int] = {}
    for block in blocks:
        if len(block) != config.bst_k:
            raise ValueError("each SparseClos block must contain bst_k clusters")
        if len(set(block)) != len(block):
            raise ValueError("SparseClos block cannot repeat a cluster")
        for cluster_id in block:
            if cluster_id not in cluster_degree:
                raise ValueError(f"unknown cluster id in SparseClos block: {cluster_id}")
            cluster_degree[cluster_id] += 1
        for pair in combinations(block, 2):
            pair_count[pair] = pair_count.get(pair, 0) + 1

    bad_degrees = {
        cluster_id: degree
        for cluster_id, degree in cluster_degree.items()
        if degree != config.bst_r
    }
    if bad_degrees:
        raise ValueError(f"SparseClos cluster degree mismatch: {bad_degrees}")

    expected_pair_count = expected_v * (expected_v - 1) // 2
    if len(pair_count) != expected_pair_count:
        raise ValueError("SparseClos blocks do not cover every cluster pair")
    if any(count != config.bst_lambda for count in pair_count.values()):
        raise ValueError("SparseClos cluster pairs must appear exactly bst_lambda times")
