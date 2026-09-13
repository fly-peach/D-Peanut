# trust-hardening Specification

## ADDED Requirements

### Requirement: 长会话历史压缩

系统 SHALL 以 ProcessHistory capability 在历史超阈值时注入 CompactionPart 摘要边界，
保留最近若干条全量消息；压缩不得丢失已落库资产引用，会话可继续。

#### Scenario: 50 轮后仍可用

- **WHEN** 同一会话累计历史超过阈值后继续对话
- **THEN** 进入模型的历史被压缩（近因全量保留），run 正常完成，资产引用不丢失

### Requirement: 断线双通道恢复

对话面 SHALL 服务端持久化消息副本（UIMessage 形态端点），刷新/断线后前端可整段重建；
画布面冷加载幂等。两通道互不依赖。

#### Scenario: 刷新恢复

- **WHEN** 一轮带工具调用的对话完成后浏览器刷新
- **THEN** 右面板消息（含工具卡状态）从 GET /sessions/{sid}/messages 恢复；
  画布卡片与渲染数据完整；断网 10s 重连后再次成立

### Requirement: 审批信息升级

写资产审批面板 SHALL 展示行级源码 diff（相对当前版本）与 verifier 风险原因；
上画布审批展示 params 与最近闸门结果。

#### Scenario: 改版可见

- **WHEN** AI 对已有资产再次 write_processor
- **THEN** 批准面板呈现新旧 processor 的行级增删（+/-）与变更规模，非原始 JSON 倾倒

### Requirement: 数据漂移可见

数据源变更（自动重扫或手动 rescan 导致绑定 revision 漂移）时，受影响资产 SHALL
标记 stale_data 并在画布以角标提示"数据已更新·待重跑"；不自动重放、不静默改图。

#### Scenario: 新数据到达

- **WHEN** 挂载文件夹中 CSV 更新且（自动/手动）重扫完成
- **THEN** 绑定该数据的卡显示 stale 角标；点击重跑过闸后消失；期间旧渲染保留

### Requirement: 审计与导出

每个资产 SHALL 提供全生命周期审计视图（版本快照 + 每次重放的触发者/结果/耗时/错误），
run 提供步骤与用量明细；图表卡可导出 PNG，渲染数据可导出 CSV；全链路日志经统一
脱敏 filter（密钥零明文）。

#### Scenario: 追责链

- **WHEN** 打开某资产审计页
- **THEN** 可见 create/validate/save/replay 全事件时序与每闸错误；同 run 的步骤
  tool/状态/摘要可查；日志与响应体不含密钥明文
