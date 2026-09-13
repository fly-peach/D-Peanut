# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

数据分析 Agent，**v3 三层架构**（编写时/运行时分离）：数据导入层（本地文件夹/文件/SQL 直读注册为 Dataset）+ 画布层（图表 = processor 脚本 + params 的持久资产，确定性重放零 AI）+ AI 对话框（coding agent，写/改 processor 与参数；轻模式即席问数 + AI toggle）。后端 uv + FastAPI + PydanticAI core + 每会话常驻 ipykernel + clean 重放内核池；前端 bun + Vite + React 19 + Tailwind 4 + shadcn/ai-elements + ECharts（前端渲染，RenderData 列式 + ChartConfig 纯 JSON）。本地 Docker 挂卷部署，同一镜像托管前端。

## 规格驱动流程（重要）

本仓库使用 openspec（`spec-driven` schema）：

- `openspec/specs/` — 已归档生效的 spec（当前仅 `agent-scaffold`，即 M0 产出）
- `openspec/changes/` — 进行中的 change（proposal/design/tasks + delta specs），完成后归档至 `changes/archive/`
- 根目录三份设计文档是需求的唯一事实源，**均已升 v3**：`design-architecture.md`（三层架构、§2.6 核心契约、§3.2 事件面分工）、`agent-design.md`（编码 Agent 配置、十工具、v3 DoD）、`implementation-roadmap.md`（N1-N4 路线图）

新功能开发先建 openspec change 再动代码；按 N 阶段推进：**M0 已完成，下一个是 N1 `data-catalog`**（随后 canvas-assets / ai-coding-loop / trust-hardening）。旧 m1/m2（M1-M5）里程碑体系已随 v3 重定义作废。

## 常用命令

后端（`backend/` 下执行，需 uv 0.12+ / Python 3.12）：

```bash
uv sync                              # 安装依赖（CI 用 --frozen，改依赖必须提交 uv.lock）
uv run pytest                        # 全部测试（全局 timeout=120s）
uv run pytest tests/test_spike_b_kernel_pool.py            # 单文件
uv run pytest tests/test_x.py::test_name                   # 单测
uv run ruff check .                  # lint（line-length=100，E/F/I/UP/B）
uv run uvicorn data_agent.main:app --reload --port 8000    # 开发服务器
```

前端（`frontend/` 下执行，需 bun 1.2+）：

```bash
bun install
bun run dev        # :5173，/api 代理到 :8000
bun run build      # tsc -b && vite build（两者必须零错误，CI 同样检查）
bun run lint       # oxlint
```

Docker（在 WSL 内执行）：

```bash
docker compose up -d --build   # backend/Dockerfile 多阶段：bun 构建前端 → uv 运行时
curl localhost:8010/healthz
```

WSL 性能注意：仓库挂载在 /mnt/*（DrvFS）时，`export UV_PROJECT_ENVIRONMENT=~/.venvs/data-agent` 把 venv 放 ext4，否则内核启动分钟级。

## 架构

### 后端 `backend/src/data_agent/`

v3 三层包结构（design-architecture §2.2 为事实源；当前仅 exec/ 与 runs/ 骨架有真实现，其余为占位待 N1-N3 落地）：

- `catalog/`（N1）— 数据导入层：file/folder/sql Dataset 注册、扫描指纹、画像、DuckDB 读取；sqlite 索引 + workspace FS
- `canvas/`（N2）— 画布层：ChartAsset、clean kernel 重放池、输出 schema 闸门；**不 import agents**（AI 关掉画布照常活）
- `agents/`（N3）— AI 编码环：十工具（run_in_kernel/write_processor/validate_asset/save_asset/emit_adhoc_chart…）+ deferred 审批
- `exec/` — `kernel_pool.py`（✅ 唯一已实现的硬资产：每会话 ipykernel 子进程，跨调用变量常驻，超时中断可恢复）、`runner.py`、`verifier.py`（AST 分级校验，试跑与重放共用）
- `runs/` — `stream.py` VercelAIAdapter granular 三方法桥接 AI 面 UIMessage SSE；画布数据本体走 REST，事件面分工见 design-architecture §3.2
- `api/` `main.py` — FastAPI 路由（`/api` 前缀）；`DATA_AGENT_STATIC_DIR` 指向目录时同域托管前端；运行期数据在 `workspace/`（index.db/secrets.json/assets 目录，N1 起建）

### 前端 `frontend/src/`

- `components/ai-elements/` — ai-elements 对话组件（Conversation/Task/Tool/PromptInput 等）；`components/ui/` — shadcn 基础件；`@` 别名指向 `src/`

### 测试即契约

`tests/test_spike_a_vercel_adapter.py`（离线 TestModel 端到端流帧序）与 `test_spike_b_kernel_pool.py`（DataFrame 跨轮常驻、超时恢复）锁定 M0 三项 spec，改桥接/内核层时先保证它们绿。

## 约定

- 提交/PR 仅在用户要求时创建；commit message 末尾加 `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- CI 三个 job（backend / frontend / docker）与本地命令一致，本地跑绿再推
- 设计文档为中文，接口冻结点在 roadmap 标注处（v3：N1 末 Dataset 契约、N2 末 processor 协议+渲染 schema、N3 末十工具签名+事件归属表；冻结后只加不改）
