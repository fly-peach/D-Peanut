"""Agent dependency container (agent-design v3 §1). Constructed per /chat request,
lives for one run; carries services + run-scoped mutable state (reflect counter,
code cache, pending asset events)."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ..canvas.assets import AssetService
from ..canvas.replay import ReplayService
from ..catalog.pipeline import CatalogPipeline
from ..catalog.registry import CatalogRepository
from ..exec.kernel_pool import KernelPool
from ..runs.store import RunStore


@dataclass
class RunSettings:
    provider: str = "test"          # openai|deepseek|dashscope|zhipu|moonshot|custom|test
    base_url: str = ""
    model_name: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096
    kernel_timeout_s: float = 60.0
    max_steps: int = 12
    budget_tokens: int = 200_000
    budget_usd: float = 2.0
    privacy_default: bool = False
    language: str = "zh"
    timezone: str = "Asia/Shanghai"
    # False → OpenAIModelProfile['openai_supports_tool_choice_required']=False：
    # 思考模式模型（deepseek-flash 等）拒绝 tool_choice='required'，置 False 时
    # pydantic-ai 静默降级为 'auto'（工具全保留，模型自主选择）。
    supports_forced_tool_choice: bool = True


@dataclass
class RunState:
    """Per-run mutable counters/caches (design: reflect counting lives in deps)."""

    run_id: str = ""
    session_id: str = ""
    reflects: int = 0            # run_in_kernel failures fed back
    last_error_summary: str = ""
    code_cache: OrderedDict[str, dict[str, Any]] = field(default_factory=OrderedDict)
    asset_events: list[dict[str, Any]] = field(default_factory=list)  # data-asset-changed queue
    adhoc_seq: int = 0
    usage_tokens: int = 0
    usage_cost: float = 0.0

    def cache_code(self, code: str, stdout: str) -> str:
        ref = f"rc{len(self.code_cache) + 1:03d}_{self.adhoc_seq}"
        self.code_cache[ref] = {"code": code, "stdout": stdout}
        if len(self.code_cache) > 20:
            self.code_cache.popitem(last=False)
        return ref


@dataclass
class AgentDeps:
    kernel: KernelPool           # per-session trial kernel pool (session_id inside)
    catalog: CatalogPipeline
    repo: CatalogRepository
    canvas_assets: AssetService
    canvas_replay: ReplayService
    store: RunStore
    settings: RunSettings
    state: RunState
    ai_enabled: bool = True
