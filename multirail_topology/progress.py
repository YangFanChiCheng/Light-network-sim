from __future__ import annotations

from .simulation import SimulationProgress


class ProgressPrinter:
    """Render simulation progress as a compact single-line progress bar."""

    def __call__(self, progress: SimulationProgress) -> None:
        if progress.event == "all_start":
            print(
                f"Simulation domains: {progress.domain_count}, workers: {progress.worker_count}",
                flush=True,
            )
        elif progress.event == "domain_start":
            print(
                f"Simulating domain {progress.domain_index}/{progress.domain_count}: D={progress.domain_size}",
                flush=True,
            )
        elif progress.event == "pair_progress":
            percent = (
                int(progress.processed_pairs * 100 / progress.total_pairs)
                if progress.total_pairs
                else 100
            )
            filled = min(20, max(0, percent // 5))
            bar = "#" * filled + "-" * (20 - filled)
            print(
                f"\r  D={progress.domain_size} pairs [{bar}] {percent:3d}% "
                f"({progress.processed_pairs}/{progress.total_pairs})",
                end="",
                flush=True,
            )
        elif progress.event == "domain_finish":
            print(
                f"\nFinished D={progress.domain_size} in {progress.elapsed_seconds:.1f}s",
                flush=True,
            )
        elif progress.event == "latency_start":
            print(
                f"\n  D={progress.domain_size} latency calculation...",
                flush=True,
            )
