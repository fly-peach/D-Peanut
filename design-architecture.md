# 数据分析 Agent：前后端设计方案（v2）

> v1→v2 变更：① 明确前后端分离形态——backend（uv + FastAPI + PydanticAI）与 frontend（bun + Vite + React + ai-elements + echarts）为两个独立应用；② 编排层自研 Agent Loop 改为 PydanticAI（v2），确认闸门用官方 deferred tools；③ 运行事件流从自定义 SSE 协议改为 **Vercel AI Data Stream Protocol**（官方 VercelAIAdapter 桥接，前端 useChat 原生消费）；④ 后端包管理 uv，前端 bun。
> 架构拓扑图见会话画布；调研依据见 research-data-analysis-agents.md。

## 0. 选型总览

| 层 | 选型 | 备注 |
|---|---|---|
| 后端包管理 | **uv**（pyproject.toml + uv.lock，锁文件入库） | Py 3.12 固定；slim 包按需 extras |
| 后端框架 | FastAPI + Pydantic v2 | 与 PydanticAI 同门，校验贯通 API 与 LLM 输出 |
| Agent 编排 | **PydanticAI v2**（2026-06 发布） | 结构化输出、工具装饰器、ModelRetry、deferred tools 审批 |
| 代码执行 | jupyter_client + ipykernel 子进程（每会话一内核） | PydanticAI 不管这层，自建后包成工具 |
| 查询引擎 | DuckDB + pandas | 大文件惰性查询 |
| 静态校验 | ast 白名单校验器（TW 模式） | 在 execute_code 工具内部执行 |
| 向量库 | sqlite-vec / Chroma（本地） | schema RAG、SQL 问答对 |
| 业务库 | SQLite（v0）→ PostgreSQL（v1） | |
| 前端包管理 | **bun**（包管理器 + 脚本运行器；dev server 仍跑 Node） | pnpm 为零成本退路 |
| 前端框架 | Vite + React 19 + TS + Tailwind 4 + shadcn/ui | 前后端分离下 Vite 比 Next 更贴合；回退方案见 §4.5 |
| AI 组件 | **ai-elements**（conversation/message/tool/task 等） | shadcn registry，源码拷进仓库可改；依赖 @ai-sdk/react useChat |
| 图表 | echarts（spec JSON 由 Agent 生成） | spec 化产物，client-only 渲染 |
| 通信 | REST 控制面 + **Vercel AI Data Stream**（SSE） | 桥接用官方 VercelAIAdapter |

## 1. 仓库形态（前后端分离）

```
data-agent/
  backend/                  # uv 管理
    pyproject.toml  uv.lock  .python-version   # 3.12
    src/data_agent/...
  frontend/                 # bun 管理
    package.json  bun.lock
    src/...
  docs/  research-data-analysis-agents.md  design-architecture.md
```

- 契约 = REST（控制面）+ UIMessage Stream（运行事件），除此之外前后端零耦合。
- dev：backend `uv run uvicorn data_agent.main:app --reload --port 8000`；frontend `bun run dev`（Vite :5173，server.proxy 把 /api 代理到 8000，SSE 需关缓冲）。
- prod：前端 `bun run build` 出纯静态产物——托管到 nginx / 对象存储，或 FastAPI StaticFiles 同域托管；API 独立进程。CORS 白名单仅 dev 需要（走 proxy 后同源）。
- 环境变量分离：后端持 LLM key / DSN（加密）；前端只有 VITE_API_BASE。

## 2. 后端设计（uv + FastAPI + PydanticAI v2）

### 2.1 包管理（uv）

- `uv sync` 装环境；`uv add pydantic-ai` 直接得到 v2；体积敏感用 `uv add pydantic-ai-slim` 按需加 extras（如 [openai]；vercel 适配是否需独立 extra → spike 确认）。
- uv.lock 必须提交；CI 用 `uv sync --frozen`；脚本统一 `uv run <cmd>`。

### 2.2 目录

```
src/data_agent/
  main.py            # FastAPI 装配：路由、CORS、StaticFiles(prod)
  api/               # sessions.py runs.py datasources.py artifacts.py settings.py
  runs/              # 自研 Run 层（PydanticAI 之外）
    state.py         #   状态机 planned→executing→waiting_confirm→done/failed/cancelled
    store.py         #   Run 表：plan、steps、tokens、cost、resume id
    stream.py        #   UIMessage 流装配（VercelAIAdapter granular 方法）
  agents/
    data_agent.py    # Agent：instructions + output_type(Plan | FinalAnswer) + tools
    tools.py         # execute_code / get_profile / search_schema / create_plan
    capabilities.py  # v2 capability：ToolSearch（工具检索）、Thinking 等
  exec/              # kernel_pool.py runner.py verifier.py（自研，不变）
  data/              # connectors/ profiler.py sampler.py duck.py
  memory/            # conversation(轮次压缩) vectorstore.py experience.py(v1)
  models/  schemas/
```

### 2.3 Agent Loop（PydanticAI 化）

1. POST /chat → 创建 Run → context_builder 组 PromptContext（画像 + schema RAG + 相关 SQL 对 + 压缩历史）。
2. **计划 = 一次结构化输出**：Agent 先产出 Plan（Pydantic 模型，字段 steps[id,title,depends_on]），桥接层以 data-plan part 推给前端（TW 两阶段规划的简化版：v0 先一次成型，v1 再做合并精炼）。
3. 逐步骤执行：Agent 调用 `execute_code` 工具 → 代码流式表现为 tool-input-delta → 工具内部先跑 **AST 白名单校验**，通过才提交内核；内核 ExecResult 作为 tool-output 返回（含 stdout/图表产物/错误栈）。
4. 失败处理：代码报错回灌由工具层 reflect 循环处理（≤3 次，TW 模式）；LLM 输出不合法用 PydanticAI 的 **ModelRetry** 自动重试。
5. **危险操作 = deferred tool（审批型）**：模型调用被拦 → run 以 DeferredToolRequests 结束 → 前端确认 → POST /confirm 后携 DeferredToolResults + 原消息历史开续跑（官方文档模式，v2 下路径名以文档为准）。
6. 完成判据：output_type 联合类型里的 FinalAnswer，或 max_steps 兜底。
7. 全程事件经 Run 层进入 UIMessage 流；Run 表记录成本/步骤供审计与重放。

### 2.4 事件桥接（官方适配器，不再手写翻译）

- 已核实（官方公告 2025-11）：PydanticAI 原生支持 **Vercel AI Data Stream Protocol**，`pydantic_ai.ui.vercel_ai.VercelAIAdapter`：
  - 快速路径：`return await VercelAIAdapter.dispatch_request(request, agent=agent)`（FastAPI/Starlette 一行接管：解析 AI SDK run input → 跑 agent 流 → 编码 SSE）。
  - 生产路径：granular 三方法 `build_run_input() / run_stream() / encode_stream()`——我们要在中间插 Run 状态机、内核池、成本统计，所以用这条；dispatch_request 留给 spike/调试。
- 领域事件映射：计划→data-plan part；代码→tool-input-*；执行结果→tool-output-available；产物→data-artifact；确认请求→data-confirm；文本回答→text-delta。自定义 data part 的 v2 支持面 → spike 确认，若不支持则把计划/产物统一建模为工具调用（语义上本就成立）。

### 2.5 仍然自研的部分（PydanticAI 边界外）

kernel_pool / runner / verifier / profiler / sampler / vectorstore / Run 状态机与 store / 轮次压缩——即原设计 §2 的执行与上下文层全部保留，只是编排外壳换成 PydanticAI。

## 3. 接口设计

### 3.1 REST 控制面（v0 全集）

Sessions：POST /api/sessions · GET /api/sessions · GET /api/sessions/{sid} · DELETE /api/sessions/{sid}

运行与消息：
- POST /api/sessions/{sid}/chat —— **useChat transport 的流入口**（请求体为 AI SDK run input，SSE 由适配器编码）
- GET /api/runs/{run_id} —— Run 详情（计划/步骤/产物/成本）
- POST /api/runs/{run_id}/confirm —— 审批结果（deferred tool 续跑）
- POST /api/runs/{run_id}/cancel —— 内核 interrupt + 状态落库

DataSources：POST /api/datasources/files（multipart，异步画像）· GET /api/datasources · GET /api/datasources/{id}/profile | /preview | /schema · (v1) POST /api/datasources/databases

产物与设置：GET /api/sessions/{sid}/artifacts · GET /api/artifacts/{aid}/download · GET|PUT /api/settings · POST /api/settings/llm/test · (v1) POST|GET /api/knowledge

### 3.2 UIMessage Stream 事件表（前后端契约核心）

| 领域事件 | UIMessage 形态 | ai-elements 渲染 |
|---|---|---|
| 计划 | data-plan（同 id 可更新） | Task 计划步骤卡 |
| 代码生成 | tool-input-start + tool-input-delta（tool=execute_code） | Tool 组件代码流 |
| 执行结果 | tool-output-available（ExecResult） | Tool 结果区 |
| 产物 | data-artifact | 画布卡片 |
| 确认请求 | data-confirm | ConfirmDialog |
| 文本回答 | text-start / text-delta / text-end | MessageResponse |
| 结束 | data-run + finish | 收尾横幅（成本/耗时） |

断线恢复：useChat resume + 消息 ID；Run 表重放兜底（spike 验证 resume 行为）。

### 3.3 数据模型

sessions · messages · runs(status, plan_json, tokens, cost, resume_id) · run_steps(idx, title, status, code, error, retries) · artifacts(kind, spec_json, data_uri, preview_uri) · datasources(kind, uri, profile_json, privacy_mode) · knowledge(kind, content, embedding) · audit_logs(v1)。

## 4. 前端设计（bun + Vite + ai-elements + echarts）

### 4.1 初始化

1. `bun create vite frontend --template react-ts`
2. Tailwind 4 + shadcn（按 shadcn 官方 Vite 指南配置 globals.css）
3. `bunx --bun ai-elements@latest add conversation message tool task prompt-input`（组件源码进 src/components/ai-elements/）
4. `bun add @ai-sdk/react echarts @tanstack/react-table zustand`

### 4.2 目录与页面

```
frontend/src/
  api/       # client.ts(REST) + chatTransport.ts(useChat transport → /api/sessions/{sid}/chat)
  stores/    # runStore(归约 data-* parts) artifactStore sessionStore
  pages/     # Workspace / Datasources / Knowledge(v1) / Settings
  components/
    chat/    # Conversation + Task(计划) + Tool(代码/结果) + ConfirmDialog + Composer(带数据源选择)
    canvas/  # ArtifactGrid + ChartCard(echarts) + TableCard(TanStack) + FileCard
```

页面功能：工作台（左会话历史 / 中对话流 / 右产物画布）；数据源页（拖拽上传→画像预览→隐私开关）；知识页(v1)；设置页。echarts 必须 client-only 动态引入。

### 4.3 关键机制

- **useChat 消费 UIMessage 流**：transport 直连 /chat 端点；runStore 把 data-* parts 归约为 UI 状态。
- agent 内部状态透明化：计划步骤卡、重试横幅「已自动修复 n/3」、成本徽章。
- 产物即状态：ChartCard 可改 echarts spec 字段（标题/色板）→ PATCH 回传（v1）。
- (v2) 探索分支：对话 Thread 树（DF Data Threads 思想）。

### 4.4 ai-elements × Vite 注意

官方前提写 Next.js；组件本身是拷贝进仓库的 React 组件，Vite 可用，但 useChat 流式/resume 属性行为以官方文档为准。回退方案：Next.js（output: export 纯前端导出，仍然前后端分离，契约不变）。

## 5. Spike 清单与版本切分

**三个 spike（各 ≈ 半天，先于正式开发）**
1. 桥接验证：v2 下 VercelAIAdapter 的 import 路径 / extras / 自定义 data part 支持；useChat 端到端渲染 tool 与 data part。
2. 内核工具化：execute_code 工具 + ipykernel 子进程 + 中途取消 + ExecResult 结构。
3. 环境跑通：bun + Vite + Tailwind4 + shadcn + ai-elements 在本机 Windows 装通。

**v0（MVP）**：上传+画像+预览；/chat 全链路（计划→代码→校验→内核→自动修复→产物）；UIMessage 流式；deferred tool 确认闸门；取消；会话持久化。非目标：登录、DB 连接器、分支、报告导出、容器沙箱。

**v1**：Postgres/MySQL 连接器；知识库（口径+SQL 对）；Docker 沙箱；JWT+审计（可参考 Vstorm 全栈模板的工程面）；产物编辑+HTML 报告；轮次压缩+经验库。

**v2**：Data Threads 分支；语义层/指标口径；有客观指标的任务切树搜索（AIDE 思想）。

## 6. 风险与对策

| 风险 | 对策 | 出处 |
|---|---|---|
| v2 刚发布，社区示例多为 v1 语义 | 先读 Upgrade Guide（openai: 默认 Responses API；end_strategy=graceful）；锁版本 | Pydantic AI v2 公告 |
| 自定义 data part 支持面未知 | spike 1 验证；兜底方案是把计划/产物建模为工具调用 | 官方 UI 文档 |
| ai-elements × Vite 非官方主线 | 回退 Next.js static export，契约不变 | ai-elements 文档 |
| useChat resume 与 Run 重放语义差异 | spike 验证；Run 表重放兜底 | |
| 列名幻觉 / 大文件 / 危险代码 / 循环失控 | 画像+schema 注入；DuckDB+采样；AST+审批双闸；max_steps+成本熔断 | TW/DF/VA |
| 会话互相干扰 | 内核进程隔离 → v1 容器隔离 | TW |

## 7. 参考

- Pydantic AI support for Vercel AI Elements（VercelAIAdapter 公告）: https://pydantic.dev/articles/pydantic-ai-ui-vercel-ai
- Pydantic AI v2: https://pydantic.dev/articles/pydantic-ai-v2
- Deferred tools（审批门）: https://ai.pydantic.dev/deferred-tools/
- AI SDK UI Message Stream Protocol: https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol
- ai-elements 文档（本仓库 skill）与 shadcn Vite 指南