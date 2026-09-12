# data-agent

数据分析 Agent：后端 uv + FastAPI + PydanticAI v2 + 常驻 Jupyter 内核；前端 bun + Vite + React 19 + ai-elements + ECharts。

设计文档：`design-architecture.md`（v2 架构）· `agent-design.md`（Agent 配置与功能清单）· `implementation-roadmap.md`（M0-M5 路线图）。

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
