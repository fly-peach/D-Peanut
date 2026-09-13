# 数据分析 Agent：前后端设计方案（v3）

> **v2→v3 变更**：① 产品定义改为**三层架构**——数据导入层（catalog）/ 画布层（canvas）/ AI 对话框（agents），核心是**编写时与运行时分离**：AI 只在"写/改图表处理逻辑"时出现，画布渲染是确定性重放，零 AI；② 图表从"每问一次 AI 产一次性 ECharts spec"变为**持久资产 ChartAsset = processor 脚本 + params dict + 数据源绑定**，存储取工作区目录（FS 为事实源）+ sqlite 索引；③ 执行面劈分：UIMessage 流只承载 AI 面，画布面走 REST 同步端点，流仅当 invalidation bus；④ 数据源从 multipart 上传改为**本地 Docker 挂卷直读**（folder / file / SQL 统一注册，路径 jail）；⑤ AI 定位收窄为 **coding agent**（Python），旧七工具废除，换 v3 十工具，删 submit_plan / search_schema / rich CLI，新增轻模式（即席问数一次性图）与 AI toggle；⑥ harness 层选型核实：用 pydantic-ai core 能力积木（`requires_approval` / `DeferredToolRequests` / `args_validator` / `defer_loading` / `ProcessHistory`+`CompactionPart` / `ToolReturn` / `agent.override(TestModel)`）自建 Agent，不整包吞 hosted harness。
> v1→v2 的变更（前后端分离、PydanticAI 编排、VercelAIAdapter 桥接、uv/bun）全部仍然成立，历史细节见 git。调研依据见 research-data-analysis-agents.md。

## 0. 选型总览

| 层 | 选型 | 备注 |
|---|---|---|
| 后端包管理 | **uv**（pyproject.toml + uv.lock，锁文件入库） | Py 3.12 固定；slim 包按需 extras |
| 后端框架 | FastAPI + Pydantic v2 | 与 PydanticAI 同门，校验贯通 API 与 LLM 输出 |
| Agent 编排 | **PydanticAI core 2.43+** 自建 Agent | 结构化输出、工具装饰器、ModelRetry、deferred 审批、capability 组合；hosted harness（`pydantic-ai-harness` pip 包）仅在需要 planning/memory 时拆组件混装，不做运行时宿主 |
| 代码执行 | jupyter_client + ipykernel 子进程 | 双池：会话常驻池（AI 试跑/探索，变量跨轮）+ **clean 重放池**（画布执行，禁会话态）；同包 `exec/kernel_pool.py` |
| 查询引擎 | DuckDB + pandas | 大文件惰性查询、谓词下推 |
| 静态校验 | ast 白名单校验器（TW 模式） | `run_in_kernel` 与资产重放共用同一 verifier |
| 图表渲染 | echarts，**前端渲染** | 消费 (RenderData 列式, ChartConfig dict)；spec 由 processor 本地重放产出，不再由 AI 每次现写 |
| 资产存储 | **workspace 目录（FS 事实源）+ sqlite 索引** | processor.py/params.json/meta.json/versions 目录化，可 git、可手改、可 diff；索引漂移用 content_hash 自愈 |
| 数据接入 | 本地路径直读（Docker 卷）+ SQL 只读连接 | folder / file / sql 三种 kind；连接串走 secrets 文件不入 DB |
| 业务库 | SQLite（v0）→ PostgreSQL（v1） | |
| 向量库 | sqlite-vec / Chroma（本地） | v1+ 知识库/schema RAG 复活时启用 |
| 前端包管理 | **bun** + Vite + React 19 + TS + Tailwind 4 + shadcn/ui | 回退方案见 §4.4 |
| AI 组件 | **ai-elements**（conversation/message/tool/prompt-input） | task 组件不再需要（计划卡随 submit_plan 废除） |
| 通信 | **双通道**：REST（画布面+控制面，同步）+ UIMessage SSE（仅 AI 面） | 桥接仍用官方 VercelAIAdapter granular 三方法 |

## 1. 仓库形态（前后端分离 + 运行时工作区）

```
data-agent/
  backend/                  # uv 管理
    pyproject.toml  uv.lock  .python-version   # 3.12
    src/data_agent/...
  frontend/                 # bun 管理
    package.json  bun.lock
    src/...
  workspace/                # ★ 运行时数据（docker 卷，不在仓库；dev 可指本地目录）
    index.db                #   sqlite：catalog 索引 + asset 索引 + replay 审计
    secrets.json            #   0600；SQL 连接串只存这里，永不进 DB/prompt/日志
    assets/{asset_id}/
      meta.json             #   版本、绑定、param_spec、output_schema、gate 状态
      processor.py          #   ★ 资产正文：磁盘上的 .py，AI 读写、人可手改、git 可纳管
      params.json
      versions/{n}.tar      #   save 成功时 processor+params 快照
      render.json           #   最近一次过闸的 RenderData（画布冷加载）
      config.json           #   最近一次过闸的 ChartConfig
    drafts/{session_id}/    #   AI 草稿目录，按会话隔离，save 才竞争全局版本
  compose.yaml              # 卷：${DATA_ROOT}:/data（数据 jail） ${WORKSPACE_ROOT}:/workspace
```

- 契约 = **REST（画布面+控制面）+ UIMessage Stream（AI 面）**，除此之外前后端零耦合。
- dev：backend `uv run uvicorn data_agent.main:app --reload --port 8000`；frontend `bun run dev`（Vite :5173，/api proxy 到 8000，SSE 关缓冲）。
- prod：`bun run build` 静态产物 → FastAPI StaticFiles 同域托管；API 独立进程。
- 环境变量分离：后端持 LLM key / DATA_ROOT / WORKSPACE_ROOT；前端只有 VITE_API_BASE。
- **路径 jail**：所有注册路径 `Path.resolve().is_relative_to(DATA_ROOT)` 断言，Windows 宿主机路径 ↔ 容器路径在注册时统一 resolve。

## 2. 后端设计（uv + FastAPI + PydanticAI v3 三层）

### 2.1 包管理（uv）

- `uv sync`；uv.lock 必须提交；CI `uv sync --frozen`；统一 `uv run <cmd>`。不变。

### 2.2 目录

```
src/data_agent/
  main.py            # FastAPI 装配 + DATA_ROOT/WORKSPACE_ROOT 配置
  settings.py        # 运行配置：路径 jail、扫描、预算、AI toggle 默认值
  api/               # datasets.py assets.py canvas.py sessions.py runs.py settings.py
  catalog/           # ★① 数据导入层（取代旧 data/ 规划）
    models.py        #   Dataset(file|folder|sql)/DatasetRef/ScanStatus/TableProfile
    registry.py      #   sqlite 索引 + 内容哈希自愈 + rebuild_index
    scan.py          #   folder 指纹 diff / 增量扫描（手动 rescan 起步）
    sources/         #   file.py(CSV/Parquet/XLSX) folder.py(展开为 child) sql.py(反射注册)
    profiler.py      #   列级画像，≤500 token/表预算（旧 M1 设计沿用）
    sampler.py       #   安全采样；privacy_mode 降级统计摘要
    reader.py        #   Dataset → DataFrame 统一读取，DuckDB 谓词下推，bindings 懒加载
  canvas/            # ★② 画布层（无 AI 依赖，可独立运行）
    models.py        #   ChartAsset/ParamField/DataSourceBinding/OutputSchema/RenderData/ChartConfig/GateReport
    assets.py        #   资产服务：FS 目录读写 + 版本快照 + 乐观锁 CAS
    gate.py          #   输出 schema 闸门（纯函数：columns 集合→dtype 族→row_bounds→payload）
    replay.py        #   重放服务：clean kernel 执行 processor → gate → 落 render.json
    kernels.py       #   clean kernel 预热池（复用 exec/kernel_pool，reset 或换新）
  exec/              # kernel_pool.py(✅已有) runner.py(Protocol) verifier.py(AST 分级，双端共用)
  agents/            # ★③ AI 层
    data_agent.py    #   Agent 装配：十工具 + output_type=FinalAnswer + deps
    deps.py          #   AgentDeps(kernel, catalog_svc, canvas_svc, settings, ai_enabled, emit)
    prompts.py       #   v3 instructions 七块（agent-design §2）+ processor 模板注入
    tools.py         #   v3 十工具（agent-design §3）
    approval.py      #   Deferred 审批续跑装配（DeferredToolResults + 历史回放）
  runs/              # state.py(状态机) store.py(Run sqlite: usage/cost/审批) stream.py(granular 桥) budget.py(熔断)
  memory/            #   ProcessHistory + CompactionPart 钩子（N4）
  schemas/           #   chart.py：RenderData/ChartConfig 跨层共享契约
```

**依赖方向铁律**：`api → {catalog, canvas, agents, runs} → exec`；**canvas 不 import agents**，agents 通过 canvas 服务写资产，catalog 谁都不依赖。这保证"AI 关掉，画布照常活"。

### 2.3 Agent Loop（v3：编码环）

1. `POST /chat` → **AI toggle 检查**（关闭则 409；已挂起的审批允许完成一次续跑）→ 创建 Run → context_builder 组 PromptContext（Dataset 目录摘要 + 请求相关画像 + 压缩历史）。
2. 工具主循环（短而固定，无独立 submit_plan）：`browse_datasource / inspect_profile / query_data` 探数据 → **`run_in_kernel` 试跑**（会话常驻内核，verifier 分级，危险模式抛 ApprovalRequired 转 deferred）→ `write_processor` 落 draft（requires_approval）→ `validate_asset` 用 clean 内核过闸（AI 的"编译器"，高频免弹窗）→ 读结构化 GateReport 自修（≤3）→ `save_asset` 上画布（requires_approval，强制 status=validated）。
3. 轻模式分叉：纯即席问数 → 试跑后直接 `emit_adhoc_chart`（ToolReturn.metadata 带一次性 payload，不落资产）；用户点"转为图表卡"→ 服务端确定性 seed（code_ref 抽字面量→PARAM_SPEC 草案）落 draft + 注入合成消息让 AI 改写为合规 processor。
4. 失败处理：run_in_kernel 报错 traceback 回灌 reflect ≤3；LLM 输出不合法用 **ModelRetry**；闸门失败给结构化 errors。
5. **审批 = deferred tool 官方模式**：`requires_approval=True` 的工具被调 → run 以 DeferredToolRequests 结束 → 前端 ConfirmDialog → 携 DeferredToolResults + 原历史续跑（`agents/approval.py`）。
6. 完成判据：`FinalAnswer`（summary + numbers 带来源 + touched_assets + followups），或 max_steps 兜底。
7. **AI 面事件**经 Run 层进 UIMessage 流；Run 表记 usage/cost/审批供审计。画布数据本体不走流（§3.2）。

### 2.4 事件桥接（官方适配器，结论沿用 v2）

- 已核实（Spike A，tests/test_spike_a_vercel_adapter.py 锁定 pydantic-ai 2.43.0）：`pydantic_ai.ui.vercel_ai.VercelAIAdapter` granular 三方法 `build_run_input() / run_stream() / encode_stream()` 可用，`DataChunk(type="data-*")` 自定义 data part 原生可行；生产路径用 granular 三方法（中间插 Run 状态机/内核池/成本统计），`dispatch_request` 留调试。
- v3 领域事件映射（对照旧表）：**删** data-plan（submit_plan 废除）；**改** data-artifact → 资产不再随流推送本体，只发 **data-asset-changed 通知帧**（asset_id/version/gate_passed/trigger），前端拿帧后走 REST 拉渲染数据；**增** adhoc 图随 `tool-output-available` 的 ToolReturn.metadata 内联；data-confirm / text-* / data-final / data-run+finish 语义不变。

### 2.5 仍然自研的部分（PydanticAI 边界外）

kernel_pool（会话池 + clean 重放池）/ verifier / catalog 全套（scan/profiler/sampler/reader）/ canvas 全套（gate/replay/assets）/ Run 状态机与 store / 轮次压缩钩子装配 / secret store——即三层的全部数据与执行基础设施；PydanticAI 只提供 Agent 循环外壳、审批原语、输出校验与测试基座。

### 2.6 核心契约（字段级，N2 末冻结）

**Dataset**（catalog/models.py）：`DatasetRef{id,name,revision}` 全局寻址句柄（revision = file:mtime+size / folder:树指纹 / sql:schema hash）。FileDataset{path,format,sheet,size_bytes}；FolderDataset{root,glob,fingerprint,child_ids}——**folder 扫描后物化为 child FileDataset 行**，每个 child 独立画像独立绑定；SqlDataset{engine,conn_ref(指向 secrets),db_schema,table,column_allowlist?}，强制只读。画像 `TableProfile{row_count, columns[ColumnProfile{name,dtype,null_rate,cardinality,num_range,time_range,top_values,sample_values,is_time,pk_hint}], revision}`；privacy_mode 清 sample_values；进 prompt 序列化 ≤500 token/表。

**ChartAsset**（canvas/models.py）：`status: draft|validated|on_canvas|broken` + `version`（save 成功 +1，乐观锁 CAS）；`bindings: list[{alias, DatasetRef(含 revision 漂移检测)}]`；`param_spec: list[ParamField{key,label,type,default,min,max,options,dataset_ref?}]`——**表单唯一事实源，由 processor 作者声明，不从 option 反推**；`params: dict`；`output_schema: OutputSchema?`（draft 首闸"盖章"，声明优先）；`chart_type` 8 类白名单；`provenance{created_by: ai|user|promote, session_id?, adhoc_id?}`；`processor_hash/params_hash`（索引自愈）；`last_gate: GateReport?`。

**processor 协议**（资产正文，模板写进 prompts.py）：

```python
PARAM_SPEC: list[dict]   # → ParamField
DEFAULTS: dict
def process(ctx) -> tuple[RenderData, ChartConfig]: ...
# ctx = ProcessorContext(params, data: Mapping[str, DataFrame 懒加载], log)
# 无 emit、无旁路出口；重放永远在 clean kernel——依赖会话变量的 processor 是非法资产
```

**渲染对**（schemas/chart.py）：`RenderData{tables: dict[str, RenderTable{dimensions, source: 列式 RenderColumn[]}], row_count, payload_bytes}`；`ChartConfig{chart_type, option_template(纯 JSON，禁 function/脚本字符串), data_map: "视觉通道→table.column" 寻址, appearance{height,width,font_size,color_palette,show_legend,...}}`。前端 `setOption(merge(option_template, {dataset: 列式源}, encode←data_map, textStyle←appearance))`。

**闸门**（canvas/gate.py 纯函数）：`validate_output(render, schema) -> GateReport{passed, checks[columns 集合语义→dtype 族匹配→row_bounds→payload_limit(2MB)], errors(结构化修正提示), kernel:"clean" 自证}`。失败时画布保留上一版 render.json + ⚠ 角标，不闪断。

## 3. 接口设计

### 3.1 REST 全集（v3）

```
Datasets（数据导入层）
POST /api/datasets                      # {kind, path|root+glob|conn_ref+schema.table} → 异步扫描+画像
GET  /api/datasets[?kind=]              # 目录
GET  /api/datasets/{id}                 # 详情（scan/profile status → 前端轮询）
POST /api/datasets/{id}/rescan          # folder 手动增量
GET  /api/datasets/{id}/profile | /preview
DELETE /api/datasets/{id}               # 被资产绑定时拒绝并列出引用方

Assets / Canvas（画布面：同步、无 SSE、零 AI）
GET  /api/assets                        # 画布冷启动：索引 + 各卡 render/config
POST /api/assets/{id}/replay            # ★ 确定性重放：200 {gate, render, config, version}；闸门失败=200+passed:false
GET  /api/assets/{id}/render            # 缓存的过闸产物（不触发重放）
PUT  /api/assets/{id}/params            # 表单改参（零 AI 路径）：校验→标 dirty→前端决定是否即时 replay
PATCH /api/assets/{id}/canvas           # 拖动/改尺寸（纯 appearance，不触发 replay）
POST /api/assets/{id}/rollback {version}
GET  /api/assets/{id}/history           # replay 审计日志
POST /api/assets/promote {adhoc_id,name}# 轻→重 seed（后续由 AI 改写环接手）

AI 对话框面
POST /api/sessions · GET /api/sessions · DELETE
POST /api/sessions/{sid}/chat           # useChat 流入口（AI toggle 关闭 → 409）
GET  /api/runs/{run_id} · POST .../confirm · POST .../cancel
GET|PUT /api/settings · POST /api/settings/llm/test   # 含 AI toggle / DATA_ROOT / 重扫策略
```

### 3.2 事件面分工（前后端契约核心）

**原则：UIMessage 流只承载"对话里发生的事 + 指向画布的指针"；画布数据本体永远从 REST 取，流仅当 invalidation bus。**

| 领域事件 | 通道 | 形态 |
|---|---|---|
| 文本回答 | UIMessage | text-start/delta/end |
| 试跑代码流与结果 | UIMessage | tool-input-delta / tool-output-available（ExecResult 截断进 content，全量进 Run 表） |
| 审批请求 | UIMessage | DeferredToolRequests → data-confirm → ConfirmDialog；续跑 = 原 chat 端点携 DeferredToolResults |
| 轻模式即席图 | UIMessage | tool-output-available 的 ToolReturn.metadata = AdhocChartPayload（render+config 内联，几十 KB 级） |
| 资产变化（AI save/表单改参/重跑） | UIMessage 仅通知帧 | data-asset-changed {asset_id, version, gate_passed, trigger: ai\|form\|replay} → 前端 GET render 拉新 |
| dataset 扫描/画像进度 | 纯 REST 轮询 | 与对话无关；N4 视需要加极简 /api/events |
| 表单改参 → 重放 | **纯 REST，完全不进 AI 流** | AI 不在场 |
| FinalAnswer / 成本 | UIMessage | data-final / data-run + finish |

断线恢复双通道：对话流 useChat resume + Run 表重放兜底；画布刷新 = `GET /api/assets` 冷加载，天然幂等与流无关——把渲染端点从 SSE 剥离换来的最大红利。

**渲染分层规则**：纯外观参数（高/宽/字体/图例）改动 → 前端直接重 setOption，零网络；影响 RenderData 的参数 → 后端 replay。

### 3.3 数据模型

sessions · messages · runs(status, usage, cost, resume_id, approval 记录) · run_steps(idx, tool, status, error, retries) · **datasets**(id, kind, name UNIQUE, meta_json, revision, parent_id, updated_at) · **profiles**(dataset_id, revision, profile_json) · **assets 索引**(asset_id, name, status, version, meta_hash, canvas placement；FS meta.json 为权威，读时哈希比对漂移标 broken) · **replays**(asset_id, version, trigger, gate_json, elapsed, ts 审计) · knowledge(v1)。

## 4. 前端设计（bun + Vite + ai-elements + echarts）

### 4.1 初始化

不变（create-vite → Tailwind4+shadcn → ai-elements 装件 → `bun add @ai-sdk/react echarts @tanstack/react-table zustand`）。

### 4.2 目录与页面

```
frontend/src/
  api/        # client.ts(REST: datasets/assets/canvas) + chatTransport.ts(useChat → /chat)
  stores/     # chatStore(useChat) · catalogStore(数据源+轮询) · canvasStore(冷加载+asset-changed 归约)
  pages/      # Workspace(对话+画布) / Datasources / Settings
  components/
    chat/     # Conversation + Tool(代码/结果) + AdhocChartCard + ConfirmDialog + PromptInput(@引用 dataset)
    canvas/   # CanvasGrid(placement) + ChartCard(ECharts 渲染器) + ParamForm(param_spec 驱动) + GateBanner + VersionHistory
```

页面：工作台（左会话/数据源目录、中对话流、右画布）；数据源页（路径注册 + 卷挂载提示 + 画像/预览 + 隐私开关 + 扫描状态）；设置页（模型/**AI toggle**/执行预算/审批策略/DATA_ROOT/重扫）。echarts client-only 动态引入。

### 4.3 关键机制

- **画布冷加载与流无关**：刷新/断网恢复 = GET /api/assets 整页重建；对话流只推 invalidation 帧。
- **ParamForm 由 param_spec 驱动**：表单从 processor 声明生成（type/min/max/select/column_ref），杜绝从 option dict 猜字段；column_ref 的可选列来自绑定的 dataset 画像。
- **ChartCard 安全契约**：option_template 纯 JSON——渲染器拒收含 `"function"`/`javascript:` 的值，formatter 不用 dangerouslySetInnerHTML（注入面防线）。
- 闸门失败 UX：⚠ 角标"最新参数未过闸" + 上版留屏 + errors 详情（一键"让 AI 修"开对话并携结构化 errors）。
- 对话内透明化：重试横幅「已自动修复 n/3」、成本徽章（data-run）、AI toggle 顶栏开关（关=对话输入框禁用并提示）。

### 4.4 ai-elements × Vite 注意

同 v2：组件拷源码进仓库可用；回退 Next.js static export，契约不变。

## 5. 验证记录与版本切分

**已验证（M0 spikes，契约测试锁定，v3 下继续有效）**：
- Spike A：VercelAIAdapter granular 三方法 + DataChunk 自定义 data part + SSE 帧序 → `tests/test_spike_a_vercel_adapter.py`
- Spike B：每会话 ipykernel 常驻、DataFrame 跨轮、超时中断恢复 → `tests/test_spike_b_kernel_pool.py`
- Spike C：bun + Vite + Tailwind4 + shadcn + ai-elements 构建链 → CI frontend job

**待验证（唯一新增项，N2 首日）**：clean kernel 重放的冷启动延迟与确定性——预热池尺寸实测；重放永远在 clean kernel、禁会话变量的执行装配跑通。

**N 阶段映射**（详见 implementation-roadmap.md v3）：N1 数据导入层 → N2 画布资产+重放（**processor/渲染契约冻结点**）→ N3 AI 编码环+轻模式+toggle（**工具签名与事件归属冻结点**）→ N4 信任稳健 → tag v0.1.0。

**v1+**：SQL 库连接器全量（N1 先 sqlite 文件）、知识库（search_schema 位以 defer_loading 复活）、经验库、容器沙箱（kernel 换实现接口不变）、HTML 报告（画布→报告新表述）、JWT 多用户、Arrow 引用式渲染（>2MB 产物）。

## 6. 风险与对策（v3）

| 风险 | 对策 | 状态 |
|---|---|---|
| SQL 连接串泄漏（备份/日志/prompt） | secrets.json 0600 + conn_ref 间接引用 + DuckDB readonly 双保险 + 统一脱敏 filter；主密钥来源（env vs OS keychain）未决 | 设计已含 |
| clean kernel 冷启动 1-3s 伤重放体验 | 预热池（常驻 N 空内核 + reset）；N2 首日实测；reset 残留变量用测试覆盖 | 待实测 |
| 重放确定性无保障（pandas 版本/随机性） | seed processor × replay 100 次字节级一致 = 架构合同锁 | N2 验收 |
| AI 改 processor 后 params 语义漂移 | 类型漂移 args_validator 拒 save；数值漂移 output_schema 闸门兜"炸"，docstring 写明参数语义 + 审批弹窗展示 diff 兜"悄悄变了" | 人工兜底 |
| option_template 注入面 | 纯 JSON 契约 + 渲染器拒 function 字符串 + 渲染器侧单测 | N3 |
| RenderData 体量爆炸（百万行不聚合直吐） | payload_limit 2MB + max_rows；超限结构化错误"请先聚合"；Arrow 引用式留 v1 | 闸门 |
| dataset 删除/schema 漂移打爆在画布资产 | 删除前引用检查；replay 时 revision 不符标 stale + 提示重绑；不静默改形 | N1/N2 |
| folder 大目录扫描慢 / watcher 在挂载卷不可靠 | N1 手动 rescan + mtime+size 指纹 diff（200 文件<5min 达标）；N4 再评估 watchdog，败则 cron 低频 | N1 |
| params 表单派生不可靠 | 不派生——PARAM_SPEC 由作者声明，spec⇄params 一致性强校验 | 设计已含 |
| promote seed 质量（会话态直译必不过闸） | 确定性 seed + 强制 AI 改写环 + validate 过闸才准 save；20 例 fixture 回归 | N3 |
| AI toggle 与历史 pending 审批冲突 | 关 AI 只禁新 run；已挂起审批允许完成一次续跑后关入口 | 设计已含 |
| 并发写同一资产 | save 携 expected_version CAS；draft 按 session 隔离 | N4 验收 |
| v2 刚发布 API 漂移 / useChat resume 语义 / ai-elements×Vite | 锁版本 2.43.0 + 契约测试；Spike A 已核；回退 Next.js | 沿用 v2 对策 |

## 7. 参考

- Pydantic AI × Vercel AI Elements（VercelAIAdapter 公告）: https://pydantic.dev/articles/pydantic-ai-vercel-ai
- Pydantic AI v2/v3 发布: https://pydantic.dev/articles/pydantic-ai-v2
- Deferred tools（审批门）: https://ai.pydantic.dev/deferred-tools/
- Pydantic AI harness（Coding/Search/Deep Research 产品与 Coder capability 包）: https://pydantic.dev/docs/ai/harness/
- AI SDK UI Message Stream Protocol: https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol
- 插件 skill：building-pydantic-ai-agents（本地 `~/.claude/plugins/.../pydantic-ai/0.1.0`，defer/审批/测试模式依据）
- 设计渊源：open-interpreter（harness 决定表现）、Data-Copilot（离线造工具层+在线调度——v3"编写时/运行时分离"的同构前身）、LIDA（画像管线）、TaskWeaver（校验+反思+预算）
