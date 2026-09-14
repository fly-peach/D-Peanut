# ai-coding-loop Specification

## ADDED Requirements

### Requirement: 编码 Agent 工具环（十工具签名冻结）

系统 SHALL 提供 coding agent（模型经 RunSettings 注入，OpenAI 兼容网关与 test 提供者），
工具集为 browse_datasource / inspect_profile / query_data / run_in_kernel / read_asset /
write_processor / validate_asset / patch_params / save_asset / emit_adhoc_chart；
write_processor 与 save_asset 需人工审批，save_asset 强制 status=validated，
reflect（执行失败重试）≤3、max_steps=12、token/费用预算熔断。
工具环运行于官方 pydantic-ai-harness 能力栈包络之下（n5 起为正式配置）：FileSystem
（DATA_ROOT 只读）、Shell（白名单 ls/du/wc/find，拒绝密钥环境变量）、Planning、
WarnNearLimits（200k token / 12 迭代预警）、ToolOutputLimits；ClearToolResults 与 SubAgents
刻意省略（ProcessHistory 独占折叠；SubAgents 绑死模型会破坏每 Run 注入不变量）；
query_data 对无界查询自动追加 LIMIT ≤1000；十工具签名不受影响。

#### Scenario: 错列名自动修复

- **WHEN** 脚本化模型先用不存在的列 run_in_kernel，收到 traceback 后修正重跑并走完
  write→validate→save
- **THEN** 出现 ≥1 次失败回灌与最终 validated；事件流含试跑代码、闸门 GateReport
  摘要、data-asset-changed 与 data-final；成本落 Run 表

#### Scenario: save 未过闸被拒

- **WHEN** validate 从未通过的资产直接 save_asset
- **THEN** 服务端拒绝并返回需先过闸的提示，资产保持 draft

### Requirement: 审批门与续跑（AI SDK 原生二段流）

危险执行（verifier blocked）与写资产 SHALL 转 approval-request：run 以
DeferredToolRequests 结束并发出 tool-approval-request 帧；用户决议经第二次 /chat
携完整消息历史续跑（deferred_tool_results）；拒绝后模型收到 denial 且不得重试同一调用。

#### Scenario: 批准后继续

- **WHEN** write_processor 挂起 → 前端批准 → 续跑请求进入
- **THEN** 资产以审批决议继续执行到 save，全程同一 message id 流式衔接

#### Scenario: 拒绝给替代

- **WHEN** 审批被拒绝
- **THEN** 模型收到 denial 信息，最终 FinalAnswer 给替代方案而非重复提交写请求

### Requirement: UIMessage 事件归属表（冻结）

AI 面事件 SHALL 按归属表输出：text-* / tool-input-* / tool-output-available(ExecResult 摘要
入流与 run_steps.output_digest) / tool-approval-request / data-asset-changed(仅通知不含数据本体) /
adhoc 图经 ToolReturn.metadata / 最终结论经 final_result 工具件（FinalAnswer 结构化输出）/
data-run+finish；画布数据本体只走 REST。
官方 adapter 的 reasoning 帧原样透传至前端 Reasoning 组件，恢复副本吸收 reasoning-delta。
断线续传=第二次 /chat 携历史；AI toggle 关闭时 /chat 返回 409。

#### Scenario: 通知帧不携数据

- **WHEN** save_asset 成功
- **THEN** 流内 data-asset-changed 仅含 {asset_id, version, gate_passed, trigger:"ai"}，
  渲染数据由前端 GET /api/assets/{id}/render 获取

### Requirement: 轻模式与 promote

即席问数 SHALL 经 emit_adhoc_chart 输出一次性卡（不落资产）；promote 端点将 adhoc 的
源码与字面量参数固化为 draft 资产（provenance=promote），并注入改写请求由 AI 完成
合规 processor。

#### Scenario: 阅后即焚与沉淀

- **WHEN** 问"总 GMV" → adhoc 卡；用户点"转为图表卡"
- **THEN** 不建资产的问数即时返回；promote 后存在 draft 资产且 provenance 链指向
  adhoc_id，随后 AI 过闸 save 成为画布卡

### Requirement: 模型配置热生效

Settings SHALL 管理 provider 预设/base_url/模型名/temperature（敏感 key 存 secrets
掩码回显），model_factory 每 Run 现构模型实例；模型可声明 supports_forced_tool_choice=false（settings 键 llm_supports_forced_tool_choice，
thinking 类），此时经 OpenAI profile 注入 openai_supports_tool_choice_required=false，
强制工具选择降级为 auto；POST /api/settings/llm/test 发最小真实请求并透出可自诊错误；
AI toggle 持久于 settings。

#### Scenario: 无密钥测试连接

- **WHEN** 未配置 key 点击测试连接
- **THEN** 返回 {ok:false, error 含缺 key/网络原因}，不抛 5xx

#### Scenario: thinking 模型降级工具选择

- **WHEN** 模型配置 supports_forced_tool_choice=false 构建 OpenAIChatModel
- **THEN** 注入 openai_supports_tool_choice_required=false 的 profile，工具选择以 auto 下发
  而非 required

### Requirement: 会话生命周期管理

系统 SHALL 提供会话管理端点：POST /api/sessions 创建、GET /api/sessions 列出、
PATCH /api/sessions/{sid} 改名（非空、≤80 字符，空标题 422）、DELETE /api/sessions/{sid}
删除并回收该会话常驻内核；未命名会话收到首条用户消息时 SHALL 以其内容自动命名
（≤60 字符，且不覆盖已有标题）。

#### Scenario: 首条消息自动命名

- **WHEN** 无标题会话发出第一条用户消息
- **THEN** 会话标题自动取自该消息（截断 ≤60 字符），后续人工改名不被覆盖

#### Scenario: 删除即回收内核

- **WHEN** DELETE /api/sessions/{sid} 成功返回
- **THEN** 该会话的 ipykernel 子进程被 shutdown，内核池中不再存在该会话
