# DataAgent 配置与功能清单（v3：编码 Agent）

> 前置：design-architecture.md v3（三层架构与核心契约）。本文回答两个问题：① PydanticAI 编码 Agent 怎么配；② v0 具体实现哪些功能。
> **v2→v3 角色变化**：Agent 从"对话式分析师"（每问现生成 spec）收窄为**画布的作者（coding agent）**——写/改 Python processor 脚本与参数 dict；运行时（重放渲染）不经过它。agent = model + harness + 数据接口 三维度在本文落地：model 全配置注入（§1）、harness 用 core 能力积木（§1/§4）、数据接口 = catalog/canvas 服务（§3）。
> 所有代码为骨架示意，API 形态以 pydantic-ai 2.43.0 实测为准（Spike A 已锁适配器面）。

## 1. Agent 实例化配置

```python
class AssetRef(BaseModel):
    id: str; name: str; version: int

class FinalAnswer(BaseModel):
    summary: str                       # markdown 结论正文
    key_findings: list[str] = []
    numbers: dict[str, str] = {}       # 结论数值 -> 来源（哪次执行/哪张卡的 gate 记录），防幻觉
    touched_assets: list[AssetRef] = []
    followups: list[str] = []

@dataclass
class AgentDeps:
    kernel: SessionKernel      # 会话常驻内核（试跑/探索；与画布 clean 池分离）
    catalog: CatalogService    # 数据接口①：Dataset 目录/画像/读取
    canvas: CanvasService      # 数据接口②：资产读写/validate/replay（与 REST 同一实现，单一事实源）
    settings: RunSettings      # 模型/超时/预算/审批策略/隐私/语言
    ai_enabled: bool           # AI toggle（服务端事实，见 §4）
    emit: EventSink            # 事件 -> UIMessage 流（仅 AI 面）

data_agent = Agent(
    'openai:gpt-4.1',          # provider/base_url/model 全部来自 RunSettings，OpenAI 兼容网关
    deps_type=AgentDeps,
    output_type=FinalAnswer,   # 唯一出口：结构化收尾
    tools=[browse_datasource, inspect_profile, query_data, run_in_kernel,
           read_asset, write_processor, validate_asset, patch_params,
           save_asset, emit_adhoc_chart],
    retries=2,                 # ModelRetry：输出/参数校验失败自动重试
    end_strategy='graceful',
)
```

要点：
- **无 submit_plan**。v2 的"先计划后执行"服务长分析链；v3 主循环短而固定（探→试→写→闸→存），max_steps=12 + 步数徽章足够，省一个工具省一类 data part。
- **requires_approval 只挂两处**：write_processor、save_asset（写盘与上画布）。run_in_kernel / query_data 的危险性由 verifier 在工具内分级抛 `ApprovalRequired`，统一走 DeferredToolRequests → 前端弹窗 → 携 DeferredToolResults 续跑（官方 deferred 模式，pydantic-ai core 原生）。
- **validate_asset 免弹窗**：它是 AI 的编译器（clean kernel 重放 draft → GateReport），高频调用，弹窗会骚扰修复循环。
- 模型不写死：provider/base_url/key/temperature 全从 RunSettings 注入（DeepSeek/Qwen/GLM 兼容端点）。

## 2. 系统提示词（instructions）——编码 Agent 纪律

静态七块：

1. **角色与环境**：你在为数据画布编写**可重放的 processor**。你有会话常驻试跑内核（变量跨轮、数据集按名懒注入）；但资产上线跑在 clean 内核——**重放内核不认任何会话变量**。pandas/duckdb 预装。
2. **数据事实优先**：只依据 inspect_profile / query_data / 执行输出说话；禁止虚构列名和数值；不确定先查再写。
3. **编写纪律**：先 `run_in_kernel` 试跑看到真实结果，才准 `write_processor`；processor 必须导出 PARAM_SPEC / DEFAULTS / process(ctx) 三件套（模板注入），process 是纯函数——只从 ctx 取数，只返回 (RenderData, ChartConfig)；写完必 `validate_asset` 过闸，读结构化 errors 修正再闸，≤3 次；**save 前强制 status=validated**。
4. **轻/重模式选择**：用户只想看一眼 → 试跑后 `emit_adhoc_chart`（一次性卡，别建资产）；要常驻/要改参/要跟着数据刷新 → 走资产环。不确定时问一句。promote 请求 = 把 adhoc 的 code_ref 改写为 ctx 重读绑定数据的合规 processor，不是照抄。
5. **渲染契约**：ChartConfig.option_template 纯 JSON（禁函数字符串）；类型白名单 bar/line/pie/scatter/histogram/box/heatmap/area；数据寻址走 data_map "table.column"；外观（高宽字体图例）放 appearance；**PARAM_SPEC 是用户表单的唯一来源——每个可调参数都要声明**，含默认值/范围/含义（docstring 写参数语义，审批人要看 diff）。
6. **失败协议**：traceback / GateReport 如实读，修正重试上限 3；仍失败说明已尝试与可选方向；禁止静默吞错、禁止绕过闸门（例如把聚合失败改成硬编码样例数据）。
7. **安全与在场规则**：run_in_kernel/query_data 命中危险模式（网络/写盘/DDL/删改）会被 AST 分级拦截转人工审批——被拒后给替代方案，不重试同一路径；**AI toggle 关闭时你不接单**（服务端 409 兜底，instructions 明示）；隐私模式（schema-only）下回答与 prompt 不含原始行数据；与用户同语言（默认中文），代码注释英文。

动态部分（`@agent.instructions`，每次 Run 注入）：

- Dataset 目录摘要（name/kind/revision/row_count/profile_status），按需画像 ≤500 token/表
- 试跑内核现存变量清单（会话态，仅供探索——再次提醒资产不可依赖）
- 上次 validate/save 的 GateReport 摘要（避免重复踩坑）
- AI toggle 状态、隐私模式、语言、时区

## 3. 工具清单（v3 十工具，宁少而精）

| 工具 | 签名（简） | 审批 | 说明 |
|---|---|---|---|
| browse_datasource | `(name_prefix?, kind?) -> list[DatasetBrief]` | 否 | 目录+名字解析；极紧凑 |
| inspect_profile | `(dataset, columns?, sample_rows=0) -> ProfileSummary` | 否 | 画像+可选样例；privacy 或 rows>5 降级统计摘要（合并旧 get_profile+preview_data） |
| query_data | `(dataset, sql, limit=200) -> QueryResult` | 条件闸 | DuckDB 只读直查，强制 LIMIT；命中写/DDL 工具内抛 ApprovalRequired |
| run_in_kernel | `(code, purpose) -> ToolReturn[ExecResult]` | 条件闸 | **会话常驻内核**试跑/探索；AST verifier 分级；metadata 携带候选渲染对与 code_ref（adhoc/promote 的原料）；stdout 截断，全量进 Run 表 |
| read_asset | `(asset_id) -> {source, params, param_spec, output_schema, last_gate, version}` | 否 | 改脚本先读全文 |
| write_processor | `(name?, asset_id?, source, bindings, params?) -> DraftBrief` | **是** | 新建/整体改写 draft（原子 tmp+rename）；args_validator 前置：三导出齐全、bindings 存在 |
| validate_asset | `(asset_id, params?) -> GateReport` | 否 | **clean kernel 重放 draft**——AI 的编译器；errors 结构化供修 |
| patch_params | `(asset_id, params) -> DraftBrief+GateReport` | 否 | 只动 params.json；按 PARAM_SPEC 类型/范围校验，不过直接 ModelRetry |
| save_asset | `(asset_id, canvas?) -> ChartAsset` | **是** | draft→on_canvas 唯一门；status≠validated 拒绝；expected_version 乐观锁；版本+1 快照入 versions/ |
| emit_adhoc_chart | `(title, render, config, code_ref) -> ToolReturn` | 否 | **轻模式出口**：一次性卡，不落盘；code_ref 供 promote |

设计原则（沿用 v2，载体更新）：
- **代码优先**：run_in_kernel 是表达力上限，其余工具是高频捷径与安全阀；勿退化成窄工具堆。
- 危险操作不做独立工具——verifier 分级转审批。
- 工具数 >10~15 时启用 `defer_loading` 按需加载（search_schema 向量位届时复活，v1+）。

## 4. 输出与护栏配置

| 项 | 配置 | 理由 |
|---|---|---|
| output_type | 仅 FinalAnswer（summary+numbers 带来源+touched_assets+followups） | 收尾可校验；数值可追溯 |
| ModelRetry | retries=2 | 参数/输出不合法自动重试 |
| reflect 上限 | 3 次/Run（语义限定：run_in_kernel 报错回灌） | TW 模式 |
| 闸门修复上限 | 3 次/资产（validate 失败→改→再 validate） | v3 新增；超限必须如实报告不硬存 |
| 步数上限 | max_steps=12/Run | 防循环失控 |
| token/费用预算 | 每 Run 熔断阈值（settings），runs/budget.py 读 usage 强制 | TW 教训 |
| 试跑超时 | 60s/步（可配） | 会话内核 |
| 重放超时 | 30s（闸门含之；超时=gate failed） | 画布是秒级操作，长任务不属于重放 |
| temperature | 0.2 | 代码稳定优先 |
| 历史窗口 | ProcessHistory + CompactionPart 轮次压缩（N4） | 长会话 |
| **AI toggle** | 服务端 AgentDeps.ai_enabled；关 → /chat 409，只读面（画布/表单/重放）完整可用；已挂起审批允许完成一次续跑 | D5：关掉后产品是纯确定性管线 |

## 5. 产品配置项（Settings 页）

- 模型：provider 预设 / base_url / 模型名 / key（掩码）/ temperature / max_tokens
- 执行：试跑超时、重放超时、max_steps、Run 预算、闸门 payload/max_rows 上限
- 安全：审批策略（自动放行/必须询问清单）、隐私模式默认、**SQL 连接串管理（secrets 轮换 UI）**
- 数据：DATA_ROOT / WORKSPACE_ROOT 显示、folder 自动重扫开关（N4）
- AI：**AI toggle 默认值**、轻模式默认
- 偏好：语言、时区、图表默认色板

## 6. 功能清单（v0，按三层）

**F1 数据导入层**（N1）
- 注册：挂载文件夹（glob 展开子文件）/ 单文件 CSV·XLSX（多 sheet）·Parquet / SQL 库（sqlite 起步，PG/MySQL 反射）
- 异步扫描 + 画像（行/列/类型/缺失/基数/数值范围/时间列识别/键提示/3 样本值）；stale 检测（revision 指纹）
- 目录管理：重命名 / 删除（引用检查）/ 隐私开关（schema-only）/ 手动 rescan
- 连接串安全：secrets.json + conn_ref 间接引用 + 全链路脱敏

**F2 画布层**（N2，无 AI）
- 画布页：图表卡网格（placement 拖动/改尺寸），冷加载 GET /api/assets
- ChartCard：ECharts 渲染 (RenderData, ChartConfig)；PNG 导出
- ParamForm：由 param_spec 驱动表单，改参即时/延迟 replay（外观参数纯前端重 setOption）
- 手动重跑 + 输出 schema 闸门：过闸落画布，失败上版留屏 + ⚠ 角标 + 结构化 errors
- 版本历史 / 回滚 / replay 审计
- 表格卡：分页/排序/导出 CSV

**F3 AI 对话框**（N3）
- 会话管理、@ 引用数据源、useChat 流式；工具卡（试跑代码+日志折叠）；FinalAnswer 渲染 + 成本徽章
- 编码环全链：探→试→写（弹窗）→闸→存（弹窗）；Deferred 审批 ConfirmDialog（风险预览：verifier 命中项 / processor diff 视图，N4 升级）
- 轻模式即席问数：一次性 adhoc 卡（阅后即焚）；**promote「转为图表卡」**：seed→AI 改写→过闸→落画布（provenance 链 adhoc_id→asset）
- AI toggle（顶栏）：关 = 一切 AI 入口 409，对话输入禁用
- 拒绝审批：agent 收 DeferredToolResults 拒绝，给替代方案不重试

**F4 信任**（N3/N4）
- 数值可追溯：FinalAnswer.numbers + 前端"这个数怎么来的"展开（关联 run_steps/gate 记录）
- 修复/闸门透明：「已自动修复 n/3」横幅；数据接口层与审计日志

**F5 会话状态**（N4）
- 试跑内核状态跨轮；会话持久化；断线双通道恢复（对话 resume + 画布冷加载）；长会话压缩

**v1+**：向量 search_schema / 知识库口径 / 经验库 / HTML 报告（画布→报告）/ JWT 多用户 / 容器沙箱 / Arrow 引用式大产物渲染。

## 7. 验收口径（v3 DoD，N 阶段验收汇编）

1. **（N1）** 注册 200 CSV 挂载文件夹 <5min 全部可寻址可画像；改一文件 mtime rescan 只重标该 child；sqlite 源任何响应/日志无连接串明文；隐私模式 preview 只回统计摘要。
2. **（N2）** 3 个种子 processor 重放 ×100 次 RenderData 字节级一致；表单 TopN 5→3 重放出图全程零 LLM 调用；params 打错列名 → 闸门 failed、上版留屏 + ⚠；只改 height → 前端重渲染零网络。
3. **（N3）** "用 sales 画 top5 城市销售额" → 试跑→write（批准弹窗）→validate 过→save（弹窗）→卡片落画布；注入错列名 seed → validate 炸 → AI 读 errors 自修 ≤3 过闸；关 AI → 409 且表单/重放完整可用；adhoc 出卡 → promote → 新卡接活数据、provenance 可查；拒绝 write → agent 给替代方案不重试。
4. **（N4）** 50 轮会话压缩触发、资产引用不丢；审计页可见单资产全生命周期；断网 10s 对话 resume + 画布冷恢复双路完整；两会话并发 save → 后者 409 版本冲突。

对照 v2 DoD 的迁移：旧 #1 上传流 → N1 注册流 + N3 编码环；旧 #2 错列名自动修复 → N3 保留（validate/reflect 双环）；旧 #3 审批弹窗 → N3；旧 #4 断网重连 → N4 双通道；旧 #5 隐私 → N1。
