from itertools import combinations

import pytest

from multirail_topology.sparse_clos import (
    ClusterInternalMode,
    SparseClosConfig,
    derive_bst_parameters,
    generate_bst_blocks,
)


def test_sparse_clos_derives_bst_tuple_for_k3_v33_case():
    config = SparseClosConfig(
        bst_r=16,
        bst_k=3,
        switch_port_num=128,
        cluster_internal_mode=ClusterInternalMode.SWITCH_ONLY,
    )

    assert derive_bst_parameters(config) == {
        "bst_v": 33,
        "bst_r": 16,
        "bst_b": 176,
        "bst_k": 3,
        "bst_lambda": 1,
        "cluster_size": 42,
        "total_cards": 1386,
    }


def test_sparse_clos_accepts_matching_explicit_v_and_b():
    config = SparseClosConfig(
        bst_r=16,
        bst_k=3,
        bst_v=33,
        bst_b=176,
        switch_port_num=128,
        cluster_internal_mode=ClusterInternalMode.SWITCH_ONLY,
    )

    assert config.bst_v == 33
    assert config.bst_b == 176


def test_sparse_clos_rejects_mismatched_explicit_b():
    with pytest.raises(ValueError, match="bst_b must match derived value 176"):
        SparseClosConfig(
            bst_r=16,
            bst_k=3,
            bst_b=175,
            switch_port_num=128,
        )


def test_sparse_clos_fullmesh_mode_requires_8_card_groups():
    with pytest.raises(ValueError, match="cluster_size must be divisible by 8"):
        SparseClosConfig(
            bst_r=16,
            bst_k=3,
            switch_port_num=128,
            cluster_internal_mode=ClusterInternalMode.FULLMESH_PLUS_SWITCH,
        )


def test_k2_blocks_cover_every_cluster_pair_once():
    config = SparseClosConfig(bst_r=4, bst_k=2, switch_port_num=128)

    blocks = generate_bst_blocks(config)

    assert len(blocks) == 10
    assert blocks == tuple(combinations(range(5), 2))


def test_k3_v33_blocks_have_expected_degree_and_pair_coverage():
    config = SparseClosConfig(
        bst_r=16,
        bst_k=3,
        switch_port_num=128,
        cluster_internal_mode=ClusterInternalMode.SWITCH_ONLY,
    )

    blocks = generate_bst_blocks(config)

    assert len(blocks) == 176
    cluster_degree = {cluster_id: 0 for cluster_id in range(33)}
    pair_count: dict[tuple[int, int], int] = {}
    for block in blocks:
        assert len(block) == 3
        for cluster_id in block:
            cluster_degree[cluster_id] += 1
        for pair in combinations(block, 2):
            pair_count[pair] = pair_count.get(pair, 0) + 1

    assert set(cluster_degree.values()) == {16}
    assert len(pair_count) == 528
    assert set(pair_count.values()) == {1}
