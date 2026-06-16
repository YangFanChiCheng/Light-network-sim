from __future__ import annotations

from itertools import combinations

import networkx as nx

from .config import MultiRailTopologyConfig
from .config import TopologyType
from .sparse_clos import ClusterInternalMode, generate_bst_blocks


class MultiRailTopology:
    """Builds the multi-rail graph and exposes topology metadata."""

    def __init__(self, config: MultiRailTopologyConfig) -> None:
        self.config = config
        self.graph = nx.Graph()
        self._built = False

    def build_graph(self) -> nx.Graph:
        self.graph = nx.Graph()

        if self.config.topology_type == TopologyType.SPARSE_CLOS:
            return self._build_sparse_clos_graph()

        for switch_index in range(self.config.X):
            self.graph.add_node(
                self._switch_id(switch_index),
                node_type="switch",
                switch_index=switch_index,
                label=f"Switch {switch_index}",
            )

        for node_index in range(self.config.M):
            compute_id = self._compute_id(node_index)
            self.graph.add_node(
                compute_id,
                node_type="compute",
                compute_index=node_index,
                label=f"Node {node_index}",
            )

            for group_index, card_indices in enumerate(self.card_groups_for_node(node_index)):
                for card_index in card_indices:
                    card_id = self._card_id(node_index, card_index)
                    self.graph.add_node(
                        card_id,
                        node_type="card",
                        compute_index=node_index,
                        card_index=card_index,
                        switch_group=group_index,
                        fm2d_domain=self.fm2d_domain_for_node(node_index),
                        label=f"N{node_index}:C{card_index}",
                    )
                    self.graph.add_edge(
                        card_id,
                        self._switch_id(group_index),
                        link_type="switch",
                        bandwidth=float(self.config.switch_bandwidth),
                    )

            card_ids = [self._card_id(node_index, card_index) for card_index in range(self.config.N)]
            for left_card, right_card in combinations(card_ids, 2):
                self.graph.add_edge(
                    left_card,
                    right_card,
                    link_type="intra",
                    bandwidth=float(self.config.intra_bandwidth),
                )

        if self.config.topology_type == TopologyType.TWO_D_FM_CLOS:
            self._add_fm2d_links()

        self._built = True
        return self.graph

    def _build_sparse_clos_graph(self) -> nx.Graph:
        sparse_config = self.config.sparse_clos
        if sparse_config is None:
            raise ValueError("sparse_clos config is required for sparse-clos topology")

        blocks = generate_bst_blocks(sparse_config)
        cluster_switches: dict[int, list[int]] = {cluster_id: [] for cluster_id in range(self.config.M)}

        for switch_index, block in enumerate(blocks):
            self.graph.add_node(
                self._switch_id(switch_index),
                node_type="switch",
                switch_index=switch_index,
                cluster_block=block,
                label=f"Switch {switch_index}",
            )
            for cluster_id in block:
                cluster_switches[cluster_id].append(switch_index)

        for cluster_index in range(self.config.M):
            compute_id = self._compute_id(cluster_index)
            self.graph.add_node(
                compute_id,
                node_type="compute",
                compute_index=cluster_index,
                label=f"Cluster {cluster_index}",
            )

            switch_groups = tuple(cluster_switches[cluster_index])
            for card_index in range(self.config.N):
                card_id = self._card_id(cluster_index, card_index)
                self.graph.add_node(
                    card_id,
                    node_type="card",
                    compute_index=cluster_index,
                    card_index=card_index,
                    switch_group=switch_groups[0],
                    switch_groups=switch_groups,
                    fm2d_domain=-1,
                    label=f"C{cluster_index}:Card{card_index}",
                )
                for switch_index in switch_groups:
                    self.graph.add_edge(
                        card_id,
                        self._switch_id(switch_index),
                        link_type="switch",
                        bandwidth=float(self.config.switch_bandwidth),
                    )

            if sparse_config.cluster_internal_mode == ClusterInternalMode.FULLMESH_PLUS_SWITCH:
                for group_start in range(0, self.config.N, 8):
                    card_ids = [
                        self._card_id(cluster_index, card_index)
                        for card_index in range(group_start, group_start + 8)
                    ]
                    for left_card, right_card in combinations(card_ids, 2):
                        self.graph.add_edge(
                            left_card,
                            right_card,
                            link_type="intra",
                            bandwidth=float(self.config.intra_bandwidth),
                        )

        self._built = True
        return self.graph

    def fm2d_domain_for_node(self, node_index: int) -> int:
        if node_index < 0 or node_index >= self.config.M:
            raise ValueError(f"node_index must be in [0, {self.config.M - 1}]")
        return node_index // int(self.config.fm2d_domain_size)

    def nodes_in_fm2d_domain(self, domain_index: int) -> list[int]:
        start = domain_index * int(self.config.fm2d_domain_size)
        end = start + int(self.config.fm2d_domain_size)
        return list(range(start, end))

    def _add_fm2d_links(self) -> None:
        domain_count = self.config.M // int(self.config.fm2d_domain_size)
        for domain_index in range(domain_count):
            for card_index in range(self.config.N):
                card_ids = [
                    self._card_id(node_index, card_index)
                    for node_index in self.nodes_in_fm2d_domain(domain_index)
                ]
                for left_card, right_card in combinations(card_ids, 2):
                    self.graph.add_edge(
                        left_card,
                        right_card,
                        link_type="fm2d",
                        bandwidth=float(self.config.fm2d_bandwidth),
                    )

    def card_groups_for_node(self, node_index: int) -> list[list[int]]:
        if node_index < 0 or node_index >= self.config.M:
            raise ValueError(f"node_index must be in [0, {self.config.M - 1}]")

        base_size = self.config.N // self.config.X
        remainder = self.config.N % self.config.X
        groups: list[list[int]] = []
        cursor = 0

        for group_index in range(self.config.X):
            size = base_size + (1 if group_index < remainder else 0)
            groups.append(list(range(cursor, cursor + size)))
            cursor += size

        return groups

    def summary(self) -> dict[str, int]:
        if not self._built:
            self.build_graph()

        node_counts = {"compute_nodes": 0, "card_nodes": 0, "switch_nodes": 0}
        edge_counts = {"intra_links": 0, "switch_links": 0, "fm2d_links": 0}

        for _, attributes in self.graph.nodes(data=True):
            node_type = attributes["node_type"]
            node_counts[f"{node_type}_nodes"] += 1

        for _, _, attributes in self.graph.edges(data=True):
            link_type = attributes["link_type"]
            edge_counts[f"{link_type}_links"] += 1

        return {
            **node_counts,
            **edge_counts,
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
        }

    @staticmethod
    def _compute_id(node_index: int) -> str:
        return f"node{node_index}"

    @staticmethod
    def _card_id(node_index: int, card_index: int) -> str:
        return f"node{node_index}-card{card_index}"

    @staticmethod
    def _switch_id(switch_index: int) -> str:
        return f"switch{switch_index}"
