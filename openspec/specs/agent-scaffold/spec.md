# agent-scaffold Specification

## ADDED Requirements

### Requirement: 每会话常驻内核

系统 SHALL 为每个会话维护一个独立 ipykernel 子进程，跨工具调用保持执行状态。

#### Scenario: DataFrame 跨轮常驻

- **WHEN** 同一会话先执行定义 DataFrame 的代码，再执行引用该变量的代码
- **THEN** 第二次执行能直接读到变量并输出正确结果，无需重新定义

#### Scenario: 超时中断与恢复

- **WHEN** 单次执行超过超时阈值
- **THEN** 内核被中断并返回明确错误，且内核在紧随其后的执行中可正常响应

### Requirement: UIMessage 流桥接

系统 SHALL 通过 PydanticAI 官方 VercelAIAdapter（granular 三方法）把 Agent 运行流编码为
AI SDK UIMessage SSE 流，且支持自定义 data part 承载领域事件。

#### Scenario: 离线端到端流

- **WHEN** 一个使用 TestModel 的 Agent 经 build_run_input / run_stream / encode_stream 运行
- **THEN** 产出 start / tool-input-start / tool-input-delta / tool-input-available /
  tool-output-available / text-delta / finish 帧并以 data: [DONE] 结束

#### Scenario: 自定义数据部分

- **WHEN** 构造 DataChunk(type="data-plan", data=...)
- **THEN** 领域载荷以自定义 data part 形态承载，可直接映射计划/产物事件

### Requirement: 前端基座可构建

前端工具链（bun + Vite + Tailwind 4 + shadcn + ai-elements）SHALL 在仓库内可安装、可类型检查、
可构建，并提供静态 Conversation 渲染演示页。

#### Scenario: 构建与静态渲染

- **WHEN** 执行 tsc -b 与 vite build
- **THEN** 两者零错误通过；演示页以 Conversation/Task/Tool/PromptInput 组件渲染样例对话