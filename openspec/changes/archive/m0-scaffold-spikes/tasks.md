# Tasks

## 1. 环境
- [x] 1.1 探测 WSL（Ubuntu 26.04）/ Docker（29.8 + compose v5.5.1）/ uv / bun
- [x] 1.2 安装原生 bun 1.4.2 与 uv 托管 Python 3.12.14
- [x] 1.3 git 初始化、.gitignore、main 基线提交、m0-scaffold-spikes 分支

## 2. Backend 脚手架
- [x] 2.1 pyproject.toml + uv.lock + ruff/pytest 配置 + 目录骨架（§2.2）
- [x] 2.2 FastAPI main.py（/healthz + 可选静态托管）与 runs/state 骨架

## 3. Spike A：VercelAIAdapter 桥接
- [x] 3.1 granular 三方法 surface 验证（pydantic-ai 2.43.0）
- [x] 3.2 AI SDK v5 run-input 解析（SubmitMessage）
- [x] 3.3 TestModel 离线端到端 SSE 帧序断言
- [x] 3.4 自定义 data part：DataChunk(type="data-...") 可携带领域载荷

## 4. Spike B：kernel_pool
- [x] 4.1 KernelPool.start/execute/capture/interrupt（ipykernel 子进程）
- [x] 4.2 DataFrame 跨 execute 常驻断言
- [x] 4.3 中断后内核可恢复断言；shutdown 强杀 + stop_channels 防进程滞留

## 5. 前端脚手架
- [x] 5.1 create-vite + Tailwind 4 + shadcn 组件基座 + 路径别名
- [x] 5.2 ai-elements 装件：conversation/message/tool/task/prompt-input
- [x] 5.3 静态 Conversation 演示页；tsc -b 与 vite build 通过

## 6. CI 与 Docker
- [x] 6.1 GitHub Actions：backend / frontend / docker 三 job
- [x] 6.2 多阶段 Dockerfile + compose.yaml（宿主 8010:8000，healthcheck）
- [x] 6.3 镜像构建 + 容器部署到 WSL Docker + /healthz 与首页验证
