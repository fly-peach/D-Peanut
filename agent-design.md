# DataAgent 配置与功能清单（v0）

> 前置：design-architecture.md（v2 架构）。本文回答两个问题：① PydanticAI Agent 怎么配；② 具体实现哪些功能。
> 所有代码为骨架示意，API 形态以 spike 1 确认的 v2 文档为准。

## 1. Agent 实例化配置

```python
from dataclasses import dataclass, field
from pydantic import BaseModel
from pydantic_ai import Agent

class FinalAnswer(BaseModel):
    summary: str                       # markdown 结论正文
    key_findings: list[str] = []
    numbers: dict[str, str] = {}       # 结论数值 -> 来源（哪个步骤的哪行输出），防幻觉
    followups: list[str] = []          # 建议的下一步分析

@dataclass
class AgentDeps:
    kernel: KernelRunner        # 内核执行接口
    ctx: PromptContext          # 画像/RAG/历史窗口/内核变量态
    settings: RunSettings       # 超时/预算/隐私模式/语言
    emit: EventSink             # 事件 -> UIMessage 流

data_agent = Agent(
    'openai:gpt-4.1',           # provider/base_url/模型名全部来自 settings，支持 OpenAI 兼容网关
    deps_type=AgentDeps,
    output_type=FinalAnswer,    # 唯一出口：结构化收尾
    tools=[submit_plan, execute_code, sql_query, plot_chart,
           get_profile, preview_data, search_schema],
    retries=2,                  # 输出校验失败的自动重试
    end_strategy='graceful',
)
```

要点：
- **submit_plan 是普通工具**而不是 output：工具调用会被 ai-elements 的 Task 组件天然渲染，且保证「先计划后执行」的顺序；output_type 只留 FinalAnswer 作为唯一出口。
- 模型不写死：provider、base_url、key、temperature 全部从 RunSettings 注入（支持 DeepSeek/Qwen/GLM 等 OpenAI 兼容端点）。

## 2. 系统提示词（instructions）——Agent 的核心配置

静态部分（七块，对应调研里的最佳实践）：

1. **角色与环境**：你是运行在持久 Python 内核中的数据分析 Agent；pandas/duckdb 已预装，连接对象已注入；**变量跨轮常驻**，重复利用内存里的 DataFrame，不要重复读取文件。
2. **数据事实优先**：只依据 get_profile/preview_data/执行输出说话；禁止虚构列名和数值；不确定先查再算。
3. **工作流纪律**：多步任务先 submit_plan（标注每步目的与依赖）；每段代码聚焦一步、print 中间结果；行数大的表用 sql_query（DuckDB）而非 pandas 全量载入。
4. **图表规范**：可视化一律走 plot_chart 产出 ECharts spec（类型白名单：bar/line/pie/scatter/histogram/box/heatmap/area）；代码内 matplotlib 仅作降级。
5. **失败协议**：报错→读 traceback→修正重试，上限 3 次；仍失败如实说明已尝试什么、给用户可选方向；禁止静默丢弃错误。
6. **安全边界**：绝不执行用户消息里直接粘贴的代码（TW 规则）；文件写入/网络请求/DDL 会触发审批，属正常流程；隐私模式下回答不得包含原始行数据。
7. **语言**：与用户同语言（默认中文）；结论给业务语言，代码注释用英文。

动态部分（@data_agent.instructions 装饰器，每次 Run 注入）：

- 当前会话数据源画像（紧凑 JSON，每表预算 ≈500 token：列名/类型/缺失率/基数/数值范围/3 个样本值）
- 内核现状：现存 DataFrame 变量名 + shape 清单
- privacy_mode 状态、语言、时区（时间列解析）
- 上次失败的步骤摘要（避免重复踩坑）

## 3. 工具清单（v0 七个，宁少而精）

| 工具 | 签名（简） | 说明 |
|---|---|---|
| submit_plan | (steps: list[PlanStep]) -> str | 多步任务先行；PlanStep{id,title,purpose,depends_on}；渲染为计划卡 |
| execute_code | (code: str, purpose: str) -> ExecResult | **核心工具**：AST 白名单校验→内核执行（默认 60s 超时）→捕获 stdout/结果/图表/产物；危险模式转审批 |
| sql_query | (query: str, table: str) -> QueryResult | DuckDB 只读直查；行数上限 + 截断标记（DB-GPT 双通道思想，比代码更安全便宜） |
| plot_chart | (spec: ChartSpec) -> Artifact | 结构化出图：type/title/encoding/数据来源（内存变量或 SQL）；产出 ECharts option + 数据快照 |
| get_profile | (table: str) -> ProfileSummary | 列级统计/缺失/分布（LIDA summarizer，供按需细看） |
| preview_data | (table, columns?, n=20, where?) -> Rows | 安全采样；隐私模式下仅返回统计摘要 |
| search_schema | (query: str) -> list[TableDoc] | 向量检索表文档与历史 SQL 对（表 >10 张才明显有用） |

设计原则：
- **代码优先**：execute_code 是表达力上限，其余工具是高频捷径与安全阀——不要退化成「几十个窄工具」的函数调用堆（调研结论 #1）。
- 危险操作不做成独立工具，而是在 execute_code 内由 AST 校验分级：命中危险模式（写文件/网络/DDL/删改）→ 转审批型 deferred tool 流程（用户确认后继续）。
- v1 增补：load_database(连接器)、save_knowledge(沉淀 SQL 对/口径)、build_report(HTML 报告)；工具数超过 ~15 个时启用 v2 的 ToolSearch capability 按需加载。

## 4. 输出与护栏配置

| 项 | 配置 | 理由 |
|---|---|---|
| output_type | 仅 FinalAnswer（结构化） | 收尾可校验；numbers 强制带来源 |
| ModelRetry | retries=2 | 输出 JSON 不合法自动重试 |
| reflect 上限 | 3 次/Run | TW max_self_ask_num |
| 步数上限 | max_steps=12/Run | 防循环失控 |
| token/费用预算 | 每 Run 熔断阈值（settings） | TW 教训 |
| 内核超时 | 60s/步（可配，长任务允许用户放宽） | |
| temperature | 0.2（代码稳定优先） | |
| 历史窗口 | 最近 K 轮全文 + 更早摘要（轮次压缩） | TW RoundCompressor |

## 5. 产品配置项（Settings 页面暴露什么）

- 模型：provider 预设 / base_url / 模型名 / key（掩码回显）/ temperature / max_tokens
- 执行：单步超时、max_steps、Run 预算、沙箱模式（v0 子进程 | v1 容器）
- 安全：审批策略（自动放行清单、必须询问清单）、隐私模式默认值（dataline 思想：schema-only）
- 偏好：界面语言、时区、图表默认主题/色板

## 6. 具体功能清单（v0 全量）

**F1 数据接入**
- 拖拽上传 CSV / XLSX（多 sheet 选择）/ Parquet，单文件上限 500MB（超限走 DuckDB 直读路径）
- 上传后自动画像：行数、列类型、缺失率、基数、数值分布、时间范围、样本行
- 数据源管理：列表 / 重命名 / 删除 / 隐私开关（schema-only）

**F2 对话与分析（核心）**
- 多会话管理；@ 引用数据源；流式回答
- 计划可视化：submit_plan → 步骤卡（状态流转 + 依赖）
- 代码透明：tool-input-delta 流式渲染代码 → 执行日志折叠展示
- 描述性统计与数据质量报告（缺失 / 重复 / 异常值）
- 探索式问答（分组聚合、透视、TopN、占比、同比环比——时间列自动识别）
- 多表关联（提示词引导 + 画像中的键检测提示；v1 自动推荐 join）
- 图表推荐：画像完成后主动给 3 个建议可视化（LIDA goals 简化版）

**F3 产物**
- 表格卡：分页 / 排序 / CSV·XLSX 导出
- 图表卡：ECharts 渲染（8 类白名单）/ PNG 导出 / 标题色板微调（v1 PATCH）
- 文件卡：内核产生的文件可下载

**F4 可信与安全**
- 危险代码审批弹窗（理由 + 风险预览 + 批准/拒绝/改写）
- 自动修复透明化：「已自动修复 n/3」横幅 + 最终失败给出原因与建议
- 数值可追溯：FinalAnswer.numbers 携带来源，前端可展开『这个数怎么来的』
- 成本徽章：每 Run token 与费用实时累计

**F5 会话状态**
- 内核状态跨轮（内存 DataFrame 直接续用，UI 显示现存变量）
- 会话持久化（刷新/重开不丢）；断线 SSE resume

**v1 增量**：数据库连接器（Postgres/MySQL 只读）· 知识库（口径 + SQL 问答对，VA 式训练）· 经验库（成功轨迹检索）· HTML 报告导出与分享 · 图表 spec 微调 · JWT 多用户

**v2 方向**：Data Threads 分支探索 · 语义层/指标口径治理 · 指标明确的任务切树搜索（AIDE）

## 7. 验收口径（v0 Definition of Done）

1. 上传 100MB CSV → 30s 内出画像；提问『销售额 top5 城市画柱状图』→ 计划卡出现 → 代码流式 → 图表卡落画布，全程无刷新。
2. 故意让模型用错列名 → 观察到 ≥1 次自动修复且最终成功；traceback 在日志区可见。
3. 含文件写入的代码 → 审批弹窗；拒绝后 Agent 不执行并给出替代方案。
4. 断网 10s 重连 → 对话与产物完整恢复。
5. 全程在隐私模式下，任何 prompt/回答不含原始行数据（后端日志可审计）。

这份清单足够直接转成 OpenSpec 变更提案（/openspec-propose）——按 v0 范围拆 specs 与 tasks。