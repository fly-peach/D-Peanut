# Tasks

## 1. 底座
- [ ] 1.1 agents/deps.py：RunSettings / AgentDeps / PromptContext / RunState（reflect 计数、code_cache、asset 事件队列）
- [ ] 1.2 agents/model_factory.py：provider→OpenAIChatModel+OpenAIProvider / test→TestModel；llm/test 端点 + settings LLM 字段
- [ ] 1.3 exec/verifier.py：AST 白名单（import 集 + blocked 模式）Verdict(safe|blocked, reason)，表驱动单测 ≥12
- [ ] 1.4 runs/store.py：sessions/messages/runs/run_steps/adhoc sqlite；usage/cost/parent_run_id
- [ ] 1.5 runs/budget.py：BudgetExceeded + usage 阈值

## 2. Agent 与工具
- [ ] 2.1 agents/prompts.py：静态七块 + processor 模板常量 + render_dynamic_prompt（dataset 目录、变量态、toggle、上次失败摘要）
- [ ] 2.2 agents/tools.py 十工具（薄壳，签名按 agent-design §3）：run_in_kernel 接会话 KernelPool + code_cache；write/validate/save 走 canvas 服务；requires_approval×2；verifier 条件审批
- [ ] 2.3 agents/data_agent.py：装配（output_type=[FinalAnswer, DeferredToolRequests]、retries=2、end_strategy=graceful、max_steps=12）
- [ ] 2.4 runs/stream.py：ChatRunner——build_run_input→adapter(deferred_tool_results 判定首跑/续跑)→run_stream(deps)→事件消费（usage 累计、data-asset-changed drain、data-final、budget 中断）→encode_stream
- [ ] 2.5 api/sessions.py：POST/GET/DELETE sessions + POST /chat SSE（toggle 409；TestClient 用 provider=test）；POST /runs/{id}/cancel；confirm 占位 409

## 3. 轻模式与 promote
- [ ] 3.1 emit_adhoc_chart 落 adhoc 表 + ToolReturn.metadata；3.2 POST /api/assets/promote（seed 抽取+draft）；单测：promote 产物 provenance/draft/合成消息文本

## 4. 测试（离线）
- [ ] 4.1 FunctionModel 全环：browse→run_in_kernel→write(审批挂起帧)→续跑→validate→save(审批)→FinalAnswer；断言帧序含 tool-approval-request、data-asset-changed、data-final
- [ ] 4.2 错列名自修：试跑炸→traceback 回灌→修正；reflect 第 4 次拒绝；save 前未 validated 拒绝
- [ ] 4.3 toggle：ai_enabled=false → /chat 409；llm/test 无 key → {ok:false, error}
- [ ] 4.4 回归：Spike A 帧序 + 既有全绿；ruff

## 5. 前端
- [ ] 5.1 api/chatTransport.ts + stores/chatStore（useChat 单例 per session）；会话列表 UI（左栏 tab：画布/会话）
- [ ] 5.2 components/chat/*：MessageList（text→Streamdown、tool 卡：run_in_kernel 代码+stdout、state 渲染）、ConfirmDialog(approve/deny)、AdhocChartCard(复用 ChartCard 渲染核)、FinalAnswer 卡（numbers 来源展开+成本徽章）
- [ ] 5.3 Workspace 右面板接真流 + AI toggle（顶栏开关，禁用态灰显）+ data-asset-changed→canvasStore 刷新
- [ ] 5.4 Settings 模型区：provider 预设下拉/base_url/模型名/key 掩码/temperature/[测试连接] 按钮结果 toast
- [ ] 5.5 tsc -b + vite build 零错误

## 6. 部署与收尾
- [ ] 6.1 docker 重建：provider=test 冒烟 /chat SSE（curl 看帧）；截图环境修复后补三旅程
- [ ] 6.2 DoD #3 自动化五条全绿；design.md 冻结段回填；归档
