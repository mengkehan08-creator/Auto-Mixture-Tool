"""Executor plugins for running jobs on a cluster.

Only the HPC cluster API backend is registered (see
``quadmix_platform.components.HpcClusterExecutor``); local mock and Slurm
``sbatch`` backends are intentionally not supported.
"""

__all__: list[str] = []
