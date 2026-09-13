# N3：AI 编码环（ai-coding-loop）

## Why

路线图 v3 N3：把 coding agent 接上已冻结的两层（catalog Dataset 契约、canvas
processor/渲染契约）。AI 的职责收窄且明确——画布的作者：探查数据 → 常驻内核试跑 →
write_processor（审批）→ validate_asset 过闸自修 → save_asset 落画布（审批）；
轻模式即席问数不留资产；promote 把 adhoc 固化为资产；AI toggle 控制 AI 在场。
十工具签名与事件归属表在本阶段末冻结。

## What Changes

- `agents/` 重写：deps（AgentDeps/RunSettings/PromptContext）、prompts（v3 七块纪律 +
  processor 模板 + 动态 catalog 摘要）、tools（十工具，requires_approval 挂
  write_processor/save_asset，run_in_kernel/query_data 走 verifier 分级
  ApprovalRequired）、data_agent 装配、model_factory
- `runs/` 补全：granular 桥 /chat SSE（build_run_input/run_stream/encode_stream +
  deps 注入 + DataChunk 通知帧 data-asset-changed/data-final/data-run）、
  sessions+messages+runs+run_steps sqlite store、budget 熔断、reflect≤3 计数
- 审批 = AI SDK v6 原生模式（适配器已带 tool-approval-request/denied 帧与
  deferred_tool_results() 转译）：**续跑复用 /chat 第二段流**，/runs/{id}/confirm
  降级为兼容占位（409 无此 run）
- 模型配置：GET|PUT settings 补 LLM 字段 + POST /api/settings/llm/test（最小真实请求，
  错误透出）；provider=test → TestModel（CI/演示无密钥可跑通全环）
- 轻模式：emit_adhoc_chart（ToolReturn.metadata 内联 AdhocChartPayload）+
  POST /api/assets/promote（确定性 seed：code_ref 的源码+字面量抽参 → draft +
  合成消息注入）；run_in_kernel 缓存 code_ref→(code, stdout) 供 promote
- CLI 取消（D10）；rich CLI 不实现
- frontend：右 AI 面板接 useChat（DefaultChatTransport → /api/sessions/{sid}/chat）、
  工具卡（试跑代码/stdout/traceback）、ConfirmDialog（approve/deny → addToolApprovalResponse）、
  adhoc 卡 + promote 按钮、AI toggle 顶栏、修复横幅、成本徽章、Settings 模型区
  （provider 预设/base_url/key 掩码/[测试连接]）
- 测试：TestModel/FunctionModel 离线全环（探→试→write 审批挂起→续跑→validate→save）、
  错列名 gate 自修、toggle 关闭 409、拒绝审批不重试、llm/test 错误透出（mock model 层）

明确不做（推后）：审批 diff 预览/审计页/压缩/并发打磨（N4）、知识库/向量（v1）。

## Impact

- Affected specs: `specs/ai-coding-loop/spec.md`（新增）
- Affected code: backend agents/ runs/ api/{sessions,runs,settings} main；
  frontend api/stores/components/chat/pages-Workspace 右面板+顶栏+Settings
- 复用冻结件：canvas/replay（validate 免弹窗同一底层）、catalog/reader、
  exec/kernel_pool（会话池与 clean 池分离）、Spike A 帧序契约测试
- 验收锚点：v3 DoD #3 五条（TestModel 全环）+ 真实模型冒烟（待用户提供 key）
