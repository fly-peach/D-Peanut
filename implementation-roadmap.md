# 实施路线图：从 MVP 到逐层封装

> 核心思想：先造最里层的引擎，把技术风险前置清零；然后逐层向外包——协议、界面、信任、稳健、产品。每层结束都有可演示、可回归的产物；**层与层的边界接口在进入外层后只加不改**，这就是「逐层优化封装」的落点。

## 0. 封装顺序与次序原则

由内向外六层：

1. **引擎层**：内核 + 工具 + Agent 循环（在 CLI 里可用）
2. **协议层**：Run 状态机 + UIMessage 流桥接
3. **交互层**：前端工作台（第一个可用的产品形态）
4. **信任层**：审批 / 数值追溯 / 隐私 / 成本可视化
5. **稳健层**：持久化 / 长会话压缩 / 部署
6. **产品层（v1+）**：连接器 / 知识库 / 报告 / 多用户 / 沙箱

次序四原则：
- **风险前置**：三个 spike 在 M0 清零、桥接在 M2 冻结——技术不确定性在前 1/3 消化，后面全是确定性组装
- **每层可演示**：CLI 演示 → curl 看流 → 浏览器可用 → 完整 DoD，进度永远看得见
- **接口冻结**：KernelRunner 签名、UIMessage 事件映射表、REST 面，进入外层后只扩展不修改
- **测试随层走**：纯函数（verifier/profiler/事件映射）单测；引擎行为用 fixture 数据集回归；流协议做契约测试

## 1. M0 脚手架与 Spike（约 3-5 天）

目标：技术风险清零 + CI 建立。

- backend：`uv init`、ruff + pytest、目录骨架（design-architecture §2.2）
- frontend：`bun create vite`、Tailwind4 + shadcn、ai-elements 装件、静态 Conversation 渲染
- **Spike A**：v2 下 VercelAIAdapter——import 路径 / extras / 自定义 data part 支持（pytest 直测，不需要前端）
- **Spike B**：kernel_pool 最小版——子进程内核、execute/capture/interrupt、验证 DataFrame 常驻
- **Spike C**：bun + Vite + ai-elements 在本机 Windows 跑通
- CI：`uv sync --frozen && ruff check && pytest`；`bun install --frozen-lockfile && tsc --noEmit && bun run build`

验收：三个 spike 各有一个通过的测试或页面；main 分支 clone 即跑。

## 2. M1 引擎层（约 1 周）——CLI 里可用的 data agent

按依赖顺序实现：

1. Agent 实例化（agent-design §1-§4 落地）：instructions 七块、AgentDeps、output_type=FinalAnswer
2. `execute_code`（含 AST verifier 纯函数 + 单测）→ kernel runner 接入
3. `sql_query`（DuckDB attach 上传文件）→ `get_profile` / `preview_data`（LIDA 式画像）
4. `submit_plan` → `plot_chart`（此阶段先落文件，不渲染）
5. reflect 循环 ≤3 + ModelRetry + max_steps/预算熔断
6. CLI 入口 `uv run data-agent chat`（rich 终端对话）

验收：agent-design 的 DoD #2——fixture 数据集上故意错列名，观察到自动修复并最终成功；画像注入满足 token 预算。
沉淀：verifier / profiler / 全部工具签名带单测——**引擎层接口在此冻结**。

## 3. M2 协议层（约 3-4 天）——引擎接到 UIMessage 流

1. Run 状态机 + SQLite store（steps/tokens/cost）+ 事件发射
2. VercelAIAdapter granular 三方法（build_run_input / run_stream / encode_stream）嵌入 Run 执行器
3. REST v0：sessions / chat / runs / cancel（confirm 占位）
4. 事件映射表（data-plan / data-artifact / data-confirm / data-run）冻结为前后端契约文档

验收：不用前端，`curl -N` 或 30 行临时页能看到计划→代码→文本全流式；断线重连续传；Run 表可审计。
意义：**此层之后前端只认协议不认后端实现**——后续后端怎么重构都不影响 UI。

## 4. M3 交互层（约 1 周）——浏览器里可用的 MVP

1. useChat transport 接 /chat；Conversation + Message 渲染
2. Tool 组件：execute_code 代码流 + 执行结果
3. Task 组件：计划卡状态流转
4. Composer（@ 引用数据源）+ 会话侧栏最小版
5. 上传页 + 画像预览卡

验收：DoD #1——上传 100MB CSV → 提问 → 图表落画布，全程无刷新。
产出：可给 3-5 个真实用户试用的版本，用反馈决定 M4 细节优先级。

## 5. M4 信任层（约 4-5 天）——从「能聊」到「可信」

1. artifact store + 产物画布（ChartCard / TableCard / FileCard / 下载）
2. plot_chart 完整实现：ChartSpec → ECharts option + 数据快照
3. AST 危险模式 → 审批型 deferred tool + ConfirmDialog（批准/拒绝/改写）
4. 修复横幅 n/3、成本徽章、FinalAnswer.numbers 数值追溯面板
5. 隐私模式全链路：prompt 侧脱敏 + 审计日志

验收：DoD #3（审批拒绝后 Agent 给替代方案）+ DoD #5（日志可审计不含原始行）。

## 6. M5 稳健层（约 3-4 天）——日常可用

1. 会话持久化完善 + 前端 resume 体验
2. 轮次压缩（超过阈值触发历史摘要）
3. 熔断打磨 / 错误页 / 结构化日志（Logfire 可选）
4. PNG / XLSX 导出；部署：FastAPI StaticFiles 同域托管或 docker-compose

验收：DoD #4（断网 10s 重连完整恢复）。打 **tag v0.1.0——MVP 完成**。

## 7. MVP 之后的向外扩展（每项 = 一层薄封装）

v1 产品层（按需排序）：
- DB 连接器：`load_database` 工具 + 连接管理（数据服务的新实现，引擎不动）
- 知识库/口径：复用 `search_schema` 位，接入向量库知识分区（VA 思想）
- 经验库：成功轨迹提炼入库（TW experience）
- HTML 报告组装与分享 · JWT 多用户 + 审计 · 容器沙箱（**kernel_runner 换实现，接口不变**）

v2 差异化：Data Threads（Run 树化）→ 语义层/指标口径（画像升级为 MDL）→ 指标型任务切树搜索（AIDE）。

规律：v1 每一项都不动 spine——连接器是 data 层新实现、知识库是 memory 层新实现、沙箱是 exec 层新实现。层边界冻结的价值在这里兑现。

## 8. 过程实践

- **OpenSpec 驱动**：每个 M = 一个 change 提案（propose → apply → archive），验收直接抄本文各节
- **演示脚本制**：每层结束录 2 分钟 demo，进度可见
- **fixture 回归集**：3-5 个固定数据集 + 20 个标准问句，每次动 spine 必跑
- **分支策略**：main 永远可跑；M 层 feature 分支，验收后合入打 tag

## 9. 工期粗估

全职：M0-M5 ≈ 4 周（M0 3-5 天 / M1 1 周 / M2 3-4 天 / M3 1 周 / M4 4-5 天 / M5 3-4 天）；业余时间约 ×3。最大不确定项是 Spike A 与 M2 桥接（协议在演进），所以放在最前面消化。