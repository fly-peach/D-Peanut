# Design

## 决策

1. **内核 = 后端 venv 解释器**：KernelPool 用 _CurrentEnvSpecManager 强制 python3 解析到
   当前进程解释器，消除机器级 kernelspec 的 PATH 漂移；pandas/duckdb 可用性与后端一致。
2. **内核生命周期**：shutdown 先 stop_channels() 再 shutdown_kernel(now=True)——
   宽松关闭会滞留 ZMQ io 线程/子进程（pytest 会话挂死实证）；内核状态在会话结束时即可弃。
3. **执行客户端复用**：KernelClient 在 start() 创建一次并持有，execute 复用；每次新建
   client 会泄漏 socket/线程。
4. **WSL/DrvFS 性能**：仓库在 /mnt/e，venv 用 UV_PROJECT_ENVIRONMENT=~/.venvs/data-agent
   放到 ext4；内核启动由分钟级降到秒级。CI/Docker 不受影响（各自环境在原生 fs）。
5. **容器端口**：宿主 8010 → 容器 8000（本机 8000 已被 ragbase-api 占用）。
6. **数据部分（data part）**：DataChunk(type="data-plan"/"data-artifact"/...) 原生可用，
   M2 事件映射表按此冻结；tool 事件帧（tool-input-start/delta/available、
   tool-output-available）与 design-architecture §3.2 一致。

## Risks / Trade-offs

- pytest-timeout(signal) 与长内核测试组合：per-test 120s 兜底；内核测试已稳定在秒级。
- ai-elements registry 无 response 组件（CLI 版本差异）：静态页直接用 streamdown 渲染，
  M3 接 useChat 时再评估。
