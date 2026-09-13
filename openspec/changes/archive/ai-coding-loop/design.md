# Design

## 决策

1. **十工具是薄壳**：全部通过 AgentDeps 注入的服务对象（catalog pipeline/repo、canvas
   assets/replay、session kernel 句柄、run 状态）干活，与 REST 共用底层——
   write_processor=assets.create/save_source+同步 validate；validate_asset=
   ReplayService.replay(trigger="validate")；save_asset=status→on_canvas+CAS。
   审批挂载：write_processor/save_asset `requires_approval=True`；run_in_kernel/
   query_data 内 verifier 命中 blocked 抛 `ApprovalRequired`（条件审批）。
2. **审批续跑走 /chat 双段流**（实测 pydantic-ai 2.43 适配器原生）：
   `output_type=[FinalAnswer, DeferredToolRequests]` → 适配器发
   tool-approval-request 帧 → 前端 addToolApprovalResponse → 第二次 POST /chat 携
   完整 messages（含 approval 结果 parts）→ `adapter.deferred_tool_results()` 非 None
   时以 message_history 续跑。Run 表记录挂起/续跑链（parent_run_id）。/runs/{id}/confirm
   仅保留路由返回 409（防旧文档误导）。
3. **会话与历史**：sessions/messages 落 sqlite；/chat 请求体 = AI SDK run input，
   message history 由适配器 load_messages 转出（server 只持久化审计副本 +
   run 级 usage/cost）；context_builder 注入动态 instructions（Dataset 目录+按需画像
   ≤500 token 用 catalog/profiler.render_profile_for_prompt；试跑内核变量清单
   `%who_ls` 简化版——执行 `dir()` 过滤）。
4. **EventSink 与通知帧**：工具改动画布后（validate/save），经 deps.emit 队列收集
   `data-asset-changed {asset_id, version, gate_passed, trigger:"ai"}`；stream.py
   在 encode_stream 消费循环中把队列事件包装 DataChunk 插入流（帧序契约测试锁）。
5. **reflect≤3 与闸门自修**：AgentDeps.run_state 计数器；run_in_kernel 失败回灌
   traceback 不计数由模型自决，**第 4 次拒绝执行**返回固定提示；validate 失败
   errors 结构化返回（GateReport.errors），save_asset 前强制 status=validated
   （服务端硬校验，不依赖提示词自觉）。
6. **model_factory**：RunSettings{provider(预设名|custom|test), base_url, model_name,
   temperature=0.2, max_tokens} → `OpenAIChatModel(model_name, provider=OpenAIProvider(
   base_url, api_key))`（api_key 从 secrets 取 llm.api_key）；provider=test →
   TestModel(custom_text_outputs 可注入演示脚本)。每 Run 现构，热生效。
   llm/test 端点：临时构 model 发 `run_sync("ping", output_type=str)` 8 token 限，
   透传异常字符串（key 脱敏）。
7. **轻模式与 promote**：emit_adhoc_chart 不落盘，ToolReturn(
   content="已出图", metadata=AdhocChartPayload{render,config,code_ref})；
   run_in_kernel 在 deps.run_state.code_cache 存 code_ref→源码+stdout（LRU 20）。
   POST /api/assets/promote {adhoc_id} → 取 code_ref 源码 + 正则抽字面量生成
   PARAM_SPEC 草案 → assets.create(draft, provenance=promote) + 注入合成 user
   消息"改写为合规 processor"（下一次 /chat 由前端自动带上）。adhoc payload 存
   sqlite adhoc 表（供 promote 与审计）。
8. **前端 chat 接入**：ai@7 useChat + DefaultChatTransport(api=/api/sessions/{sid}/chat)；
   消息 parts 渲染映射：text→Streamdown；tool-{name} state=input-streaming/output-error/
   approval-requested(ConfirmDialog)/output-available；data-asset-changed→canvasStore
   懒刷新；data-final→结论卡+来源展开；data-run→成本徽章。AI toggle 顶栏开关写
   settings(ai_enabled)，关闭时 /chat 409、输入框禁用变灰。
9. **预算/步数**：max_steps=12（agent.iter options → usage 检查每工具后）；budget:
   RunSettings.budget_usd/budget_tokens，run_stream 消费循环里读 usage 超限抛
   BudgetExceeded → 发 data-run(failed)+finish 终止；run 表落 usage/cost。

## 接口增量

```
POST /api/sessions · GET /api/sessions[?limit] · DELETE /api/sessions/{sid}
POST /api/sessions/{sid}/chat      # AI SDK run input → UIMessage SSE（含审批二段）
POST /api/assets/promote           # {adhoc_id, name?} → draft asset（AI 续写）
GET|PUT /api/settings              # + llm 字段（key 掩码）
POST /api/settings/llm/test        # → {ok, latency_ms, model, error}
POST /api/runs/{run_id}/cancel     # 会话内核 interrupt + run failed
```

## Risks / Trade-offs

- TestModel 对 deferred 帧的覆盖度未知 → N3 第一个测试就验 FunctionModel 触发
  ApprovalRequired → approval-request 帧；不通则降级：测试只验工具内 ApprovalRequired
  异常转译（服务端断言），UI 帧以真实模型冒烟补
- encode_stream 循环中插 DataChunk 的时机（事件队列边界） → 以"每个 tool 帧 flush 后
  drain 队列"为规则，帧序测试锁定
- useChat 对 approval-response 的 API 名称（addToolApprovalResponse vs addToolResult）
  以 ai@7 实测为准；前端实现封装在 chatTransport.ts 单点
- code_cache 是进程内状态：重启丢 → adhoc 表持久化 payload，promote 依赖 DB 不依赖 cache

## 已冻结（N3 末回填）

- （待填）十工具签名 / UIMessage 事件归属表

## 已冻结（N3 末，只加不改）

十工具签名（tools.py）：browse_datasource(name_prefix?,kind?) / inspect_profile(dataset,
columns?,sample_rows?) / query_data(dataset,sql,limit) / run_in_kernel(code,purpose)->
ToolReturn[ExecSummary]{metadata.code_ref} / read_asset(asset_id) / write_processor(source,
bindings,name?,asset_id?,params?,chart_type)⚑ / validate_asset(asset_id) / patch_params
(asset_id,params) / save_asset(asset_id,canvas?)⚑ / emit_adhoc_chart(title,render,config,
code_ref)→"…(adhoc: ad_xxx)"。⚑=requires_approval。
事件归属：text-*|tool-*|tool-approval-request|data-asset-changed|data-run|finish；
[chat] deps→dispatch dict 转换在 adapter 内——服务侧必须持有 RunState 原始引用。
审批续跑 = 第二次 /chat（AI SDK v6 approval parts + sendAutomaticallyWhen 判全部
approval-responded）；UsageLimits(request/token/cost) 原生承载 max_steps 与预算。
