# N4：信任与稳健（trust-hardening）→ v0.1.0

## Why

路线图 v3 N4：从"能跑"到"敢托付"。补齐 DoD #4 四场景（长会话压缩、资产全生命周期审计、
断网双通道恢复、并发 CAS），并落地体验件（审批 diff 预览、PNG/CSV 导出、数据刷新标记、
folder 自动重扫、结构化日志）。N4 完成打 tag v0.1.0 = MVP。

## What Changes

- backend：
  - `memory/compaction.py`：ProcessHistory(capability) + CompactionPart——超 token 阈值
    把旧历史压成摘要段，保留近 N 条全量（实测 pydantic-ai 2.43 capabilities API）
  - ChatRunner：on_complete → adapter.dump_messages 持久化会话消息副本 +
    `GET /api/sessions/{sid}/messages`（断线/刷新恢复对话的真源）
  - folder 自动重扫：lifespan asyncio 周期任务（settings.auto_rescan_interval_s，默认 0 关）；
    变更 child revision → 其绑定资产标 stale_data（meta 记 dataset drift，画布显"数据已更新"）
  - 结构化日志：logging 统一 formatter + SecretsStore.redact 挂 handler filter
- frontend：
  - 审批升级：write_processor 批准面板显示 **源码行级 diff**（旧版 vs 新版，自研
    diffLines 纯函数）+ verifier 风险说明；save_asset 面板显示 params 与闸门状态
  - 卡工具条：PNG 导出（echarts getDataURL）、查看数据 + CSV 导出（RenderData→CSV）
  - 数据漂移 UX：绑定 dataset revision 变化的卡显示"数据已更新·待重跑"角标
  - 审计页 pages/Audit.tsx：资产生命周期（versions+replays 合并）+ run/steps 明细
  - 恢复：刷新后右面板拉 /sessions/{sid}/messages 重建对话（画布冷加载已有）
- 部署：docker compose 全重建 + browser-use 三旅程截图（环境允许时）；tag v0.1.0

明确不做（诚实取舍，记 v1）：secrets 静态加密（主密钥来源未决，0600+脱敏+轮换 UI 先行）、
审批弹窗里的"改写"入口（拒绝+重述即可）、全局审计筛选器（页面级列表足够）。

## Impact

- Affected specs: `specs/trust-hardening/spec.md`（新增）；agent-scaffold spec 加
  clean 池隔离 scenario（N2 合同锁已覆盖，补 spec 表述）
- Affected code: backend memory/ + runs/stream.py + api/sessions.py + main.py lifespan;
  frontend chat/canvas 组件 + pages/Audit + diffLines 工具
- 验收锚点：v3 DoD #4 四条 + 三旅程端到端（provider=test 可演示，真实 key 由用户替换）
