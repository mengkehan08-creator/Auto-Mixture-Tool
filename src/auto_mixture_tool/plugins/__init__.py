"""Auto-Mixture-Tool 插件系统入口。

所有插件在 ``quadmix_platform.service.PlatformService.__init__`` 中**集中注册**
（这是运行时唯一生效的注册入口，见 docs/AUTO_MIXTURE_TOOL.md §6）。

本模块只负责把四个 Adapter 基类、注册表、命令模型重新导出，方便插件与测试
从同一个位置导入。新增插件流程：
  1. 在对应子目录（algorithms / trainers / validators / executors）新建文件，
     继承下方某个 Adapter；
  2. 在 ``PlatformService.__init__`` 中 import 并 ``register(...)``。
"""

from __future__ import annotations

from quadmix_platform.interfaces import (
    AlgorithmAdapter,
    ExecutorAdapter,
    TrainerAdapter,
    ValidatorAdapter,
)
from quadmix_platform.models import CommandSpec, JobRecord
from quadmix_platform.registry import ComponentRegistry

__all__ = [
    "AlgorithmAdapter",
    "TrainerAdapter",
    "ValidatorAdapter",
    "ExecutorAdapter",
    "CommandSpec",
    "JobRecord",
    "ComponentRegistry",
]
