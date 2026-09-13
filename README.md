# data-agent (v0.1.0 · MVP)

数据分析 Agent，v3 三层架构：**数据导入层**（本地文件夹/文件/SQL 注册为带画像的 Dataset）+
**画布层**（图表 = processor 脚本 + 参数的持久资产，clean 内核确定性重放、schema 闸门）+
**AI 编码对话框**（探查→试跑→写 processor（审批）→过闸→上画布；轻模式即席问数 + promote；
AI toggle 一键离线为纯管线）。后端 uv + FastAPI + PydanticAI；前端 bun + Vite + React 19 +
ai-elements + ECharts（VSCode 式：左树·中画布·右 AI 面板，linear-app 暗色主题）。

设计文档：`design-architecture.md`（v3 三层架构：数据导入 / 画布资产 / AI 编码对话框）· `agent-design.md`（编码 Agent 配置与 v3 DoD）· `implementation-roadmap.md`（M0 已完成 + N1-N4 路线图）。

## 仓库结构

```
backend/    # uv 管理；src/data_agent/{api,runs,agents,exec,data,memory,...}
frontend/   # bun 管理；Vite + Tailwind4 + shadcn + ai-elements
```

## 本地开发

后端（需 uv 0.12+）：

```bash
cd backend
uv sync                 # 默认在 backend/.venv 建环境
uv run pytest           # 三个 spike + healthz
uv run ruff check .
uv run uvicorn data_agent.main:app --reload --port 8000
```

> WSL 下仓库若在 /mnt/*（DrvFS），建议 `export UV_PROJECT_ENVIRONMENT=~/.venvs/data-agent` 把 venv 放到 ext4，内核启动从分钟级降到秒级。

前端（需 bun 1.2+）：

```bash
cd frontend
bun install
bun run build           # tsc -b && vite build
bun run dev             # :5173，/api 代理到 :8000
```

## Docker（WSL 内）

```bash
docker compose up -d --build   # 构建镜像并启动
curl localhost:8010/healthz    # {"status":"ok"}
# 浏览器打开 http://localhost:8010/ —— 前端静态页由 FastAPI 同域托管
```

## CI

GitHub Actions：backend（uv sync --frozen + ruff + pytest）、frontend（bun install --frozen-lockfile + tsc -b + build）、docker（构建镜像）。
