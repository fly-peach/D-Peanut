# M0：脚手架与 Spike

## Why

路线图 M0（implementation-roadmap.md §1）：技术风险前置清零 + CI 建立。三个 spike 分别验证
PydanticAI v2 流桥接、常驻内核工具化、bun×ai-elements 前端链路——它们是 M1/M2/M3 的地基，
不确定必须在最前面消化。

## What Changes

- backend/：uv + FastAPI + PydanticAI v2 脚手架，目录骨架对齐 design-architecture §2.2
- frontend/：bun + Vite + React 19 + Tailwind 4 + shadcn + ai-elements，静态 Conversation 渲染
- Spike A：VercelAIAdapter granular 三方法 + 自定义 data part（pytest，离线 TestModel）
- Spike B：kernel_pool 子进程内核 execute/capture/interrupt + DataFrame 跨轮常驻（pytest）
- Spike C：前端工具链 + tsc -b + vite build 在 WSL 内跑通
- CI：backend（uv/ruff/pytest）+ frontend（bun/tsc/build）+ docker build 三个 job
- Docker：多阶段镜像（bun 构建前端 → uv 后端同域托管静态产物），compose 部署到 WSL 内 Docker

## Impact

- Affected specs: `specs/agent-scaffold/spec.md`（新增）
- Affected code: 新增 backend/ 与 frontend/ 两个应用；仓库初始化 git（main + m0 分支）
