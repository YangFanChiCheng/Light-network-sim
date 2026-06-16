from dataclasses import dataclass
from enum import StrEnum

from .sparse_clos import SparseClosConfig, derive_bst_parameters


class TopologyType(StrEnum):
    ONE_D_FM_CLOS = "1d-fm-clos"
    TWO_D_FM_CLOS = "2d-fm-clos"
    SPARSE_CLOS = "sparse-clos"


class VisualizationDetail(StrEnum):
    SIMPLIFIED = "simplified"
    FULL = "full"


@dataclass(frozen=True)
class MultiRailTopologyConfig:
    """User-facing configuration for a multi-rail topology."""

    M: int = 1
    N: int = 1
    X: int = 1
    intra_bandwidth: float = 200.0
    switch_bandwidth: float = 100.0
    topology_type: TopologyType = TopologyType.ONE_D_FM_CLOS
    fm2d_domain_size: int | None = None
    fm2d_bandwidth: float = 200.0
    visualization_detail: VisualizationDetail = VisualizationDetail.SIMPLIFIED
    sparse_clos: SparseClosConfig | None = None

    def __post_init__(self) -> None:
        if isinstance(self.topology_type, str):
            object.__setattr__(self, "topology_type", TopologyType(self.topology_type))
        if isinstance(self.visualization_detail, str):
            object.__setattr__(
                self,
                "visualization_detail",
                VisualizationDetail(self.visualization_detail),
            )
        if isinstance(self.sparse_clos, dict):
            object.__setattr__(self, "sparse_clos", SparseClosConfig(**self.sparse_clos))

        if self.topology_type == TopologyType.SPARSE_CLOS:
            if self.sparse_clos is None:
                raise ValueError("sparse_clos config is required for sparse-clos topology")
            sparse_params = derive_bst_parameters(self.sparse_clos)
            object.__setattr__(self, "M", sparse_params["bst_v"])
            object.__setattr__(self, "N", sparse_params["cluster_size"])
            object.__setattr__(self, "X", sparse_params["bst_b"])

        if self.fm2d_domain_size is None:
            object.__setattr__(self, "fm2d_domain_size", self.N)

        for name in ("M", "N", "X"):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

        if self.topology_type != TopologyType.SPARSE_CLOS and self.X > self.N:
            raise ValueError("X cannot exceed N; each switch group needs at least one card")

        if not isinstance(self.fm2d_domain_size, int) or self.fm2d_domain_size <= 0:
            raise ValueError("fm2d_domain_size must be a positive integer")

        if self.topology_type == TopologyType.TWO_D_FM_CLOS and self.M % self.fm2d_domain_size != 0:
            raise ValueError("M must be divisible by fm2d_domain_size for 2D FM domains")

        for name in ("intra_bandwidth", "switch_bandwidth", "fm2d_bandwidth"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be a positive number")
