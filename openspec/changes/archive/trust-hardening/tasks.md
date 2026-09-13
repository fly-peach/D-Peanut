# Tasks

## 1. 后端
- [x] 1.1 memory/compaction.py：ProcessHistory capability——阈值(8k tokens est)以上
      将旧消息折叠为 CompactionPart 摘要占位（保留最近 16 条）；build_agent 挂载；
      单测：50 条历史 run 后注入的 model request 被压缩且近因保留
- [x] 1.2 ChatRunner on_complete：dump_messages 副本入 messages 表（user+assistant 全量）；
      GET /sessions/{sid}/messages → UIMessage[]；单测：一轮 chat 后 messages 端点可回放 parts
- [x] 1.3 自动重扫：lifespan asyncio 任务（interval 配置，0=关）→ folder rescan →
      revision 变 → 绑定资产 meta.stale_data=true（GET /assets 可见）；单测 interval 逻辑 + 漂移标记
- [x] 1.4 结构化日志：logging handler + redact filter；异常路径 error 带 run_id/asset_id；
      caplog 断言无明文 secret
- [x] 1.5 并发用例：同资产双 replay/params 交错——CAS 409 + 数据一致（测试即可）

## 2. 前端
- [x] 2.1 lib/diffLines.ts：简单 LCS 行 diff（+/- 计数与着色）；单测
- [x] 2.2 ToolCard 审批面板升级：write_processor 拉旧 source 显 diff + 风险 reason；
      save_asset 显 params + last_gate
- [x] 2.3 ChartCard：PNG 导出（getDataURL）、"查看数据"弹层 + CSV 导出（列式→CSV 转义）
- [x] 2.4 stale_data 角标 + 点击引导重跑
- [x] 2.5 pages/Audit.tsx（tab 第4项）：资产选择 → versions/replays 时间线；
      run 列表（GET /sessions/{sid}/messages 关联展示 steps）
- [x] 2.6 ChatPanel 恢复：会话切换/刷新 → GET messages 初始化
- [x] 2.7 tsc + vite build 零错误

## 3. 部署与收尾
- [x] 3.1 docker 重建 + 全 e2e（三旅程脚本：注册→AI 建卡(approve)→改数据→重跑→promote→
      toggle 关→表单）curl 级
- [ ] 3.2 browser-use 截图【遗留·环境阻塞】：Windows→WSL 入站被拦（curl 000，容器内 e2e 全绿）；需 wsl --shutdown 重建 relay（会中断同机其它容器，待用户择时）
- [x] 3.3 DoD #4 断言全绿；回归全绿 + ruff；spec/README/CLAUDE 同步；归档；
      merge main；tag v0.1.0
