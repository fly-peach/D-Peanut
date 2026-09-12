# 数据分析 Agent 开源项目调研

> 调研方式：浏览器直接访问 GitHub 仓库（搜索页遇限流，改为定点深挖），README + 关键源码。
> 日期：本次会话内完成。

## 一、全景图

| 项目 | 定位 | 一句话思想 |
|---|---|---|
| [microsoft/TaskWeaver](https://github.com/microsoft/TaskWeaver)（已归档） | code-first 数据分析 agent 框架 | 规划器 + 代码解释器双角色，执行历史和内存数据都进上下文 |
| [sinaptik-ai/pandas-ai](https://github.com/sinaptik-ai/pandas-ai) | 对话式数据分析库 | `df.chat("...")`，schema 向量库 RAG + 沙箱执行生成代码 |
| [microsoft/data-formulator](https://github.com/microsoft/data-formulator) | 可视化探索工作台 | Data Thread 分支探索 + 数据源连接器记忆 |
| [eosphoros-ai/DB-GPT](https://github.com/eosphoros-ai/DB-GPT) | agentic 数据助手平台 | 计划→SQL/代码→沙箱→报告，AWEL 编排，skills 打包领域知识 |
| [Canner/WrenAI](https://github.com/Canner/WrenAI) | GenBI 语义层 | "生成式 BI 的上限取决于 context 层"——MDL 语义层给 agent 可信口径 |
| [RamiAwar/dataline](https://github.com/RamiAwar/dataline) | 隐私优先数据分析 | 默认对 LLM 隐藏数据本体，只发 schema/元数据 |
| [openinterpreter/open-interpreter](https://github.com/openinterpreter/open-interpreter) | 通用代码 agent（已转型 Codex fork） | harness 模拟：同一模型换 harness 表现差异巨大 |

另可参考：Vanna（text-to-SQL 用 DDL/文档/SQL 问答对训练 RAG）、MetaGPT DataInterpreter（REACT 式 code-first）。

## 二、源码深挖笔记

### 1. TaskWeaver（最值得抄架构）
源码：`taskweaver/planner/planner.py`、`taskweaver/planner/planner_prompt.yaml`、`taskweaver/code_interpreter/code_verification.py`

- **角色制多智能体**：Planner 是一个 Role，持有 workers 字典；系统提示词把每个 worker 的 `get_intro()` 拼进去。
- **结构化通信**：LLM 输出被解析成 Post（含 send_to 路由字段），send_to 的 enum 直接由 worker 别名集合动态生成——路由即 schema。
- **两阶段规划**（planner_prompt.yaml）：`init_plan` 分解子任务并标注依赖（Sequential/Parallel）→ `plan` 阶段合并相邻无依赖步骤精炼。
- **自修复循环**：JSON 解析失败 → 附加 revise_message 打回给 planner 自己，最多重试 3 次（`max_self_ask_num`）。
- **代码静态校验**：`code_verification.py` 用 AST NodeVisitor 做模块 import 黑/白名单 + 函数调用白名单，执行前拦截。
- **有状态执行**：保留对话历史 + 代码执行历史 + 内存中的 DataFrame；高维表格数据不必序列化进聊天记录。
- **其他**：SharedMemoryEntry 跨角色共享 plan；RoundCompressor 压缩长对话；ExperienceGenerator 从历史会话提炼经验复用；默认容器化执行 + 会话隔离。
- 状态：2026-03 已归档，但架构思想仍是最完整的参考实现。

### 2. pandas-ai
源码结构：`pandasai/{agent,core,query_builders,sandbox,vectorstores,data_loader}`，agent 逻辑在 `agent/base.py`。

- 对话入口极薄：`df.chat(query)` / `pai.chat(query, df1, df2)`，多 DataFrame 自动 join 推理。
- **schema RAG**：表多时用 vectorstore 存表 schema 描述，按查询检索相关表再生成代码。
- **pipeline 式处理**：prompt 组装 → 代码生成 → 沙箱执行（可选 pandasai-docker 容器）→ 结果校验 → 返回文本/DataFrame/图表。
- query_builders 把 NL 查询转 SQL 的部分独立模块化。
- 通过 LiteLLM 支持多模型。

### 3. data-formulator（交互思想最独特）
- 核心观察：**分析问题是演化的**——每个答案引出追问/对比/新方向，长聊天历史让人迷失。
- **Data Threads**：像 Git 分支一样分支探索，多条路径并存对比，可视化锚定上下文。
- **Data Connectors + data memory**：统一连接文件/数据库/数仓/BI，并记住数据源之间的关系（agent 回答前先搞清关系）。
- DuckDB 撑大数据；Flint 图表语言把紧凑 spec 编译成精致图表；图表推荐 + 风格精炼 agent。

### 4. DB-GPT
- 产品五支柱：agentic 分析（计划→步骤→工具）、自主 SQL+代码、多源接入、**skills 打包领域知识**、沙箱执行。
- AWEL（Agentic Workflow Expression Language）：把 agent 流程表达为 DAG 编排。
- 终点是产物：图表/看板/HTML 报告/分析摘要，不是聊天。

### 5. dataline
- **隐私第一**：默认把数据本体对 LLM 隐藏，只发 schema/元数据，查询结果本地取回（可开关）。
- 本地存储一切；支持 Postgres/MySQL/Snowflake/SQLite/CSV 等；输出可导出图表/表格/报告。

### 6. WrenAI
- 命题："Generative BI is only as good as the context it stands on."
- **MDL 语义层**：在裸 schema 之上叠加业务语义、审批过的口径定义、示例、记忆、治理规则 + 非结构化知识（文档/wiki）。
- text-to-SQL 变成"受治理的 text-to-SQL"，跨 22+ 数据源。

### 7. open-interpreter（2026 转型）
- 已从"本地跑代码的解释器 agent"转型为 OpenAI Codex fork，专注低成本模型的 harness 模拟。
- 两个可迁移思想：① **同一模型在不同 harness 下表现差异巨大**，低成本模型尤其依赖 harness 工程；② 工具中立可移植标准：AGENTS.md、.agents/skills、MCP、ACP。

## 三、共性思想提炼（设计我们自己的 agent 时直接可用）

1. **代码是行动的通用接口（code-first）**：生成 pandas/SQL/DuckDB 代码而非枚举工具，表达力上限最高。这是所有头部项目的共同选择。
2. **有状态执行**：Python 会话常驻，DataFrame 留在内存跨轮复用；执行历史（代码+结果摘要）进入上下文。
3. **执行前校验 + 失败反思**：AST 静态检查（模块/函数白名单）→ 执行 → 报错回灌修正，重试有上限。
4. **沙箱隔离**：容器/子进程执行，多用户会话互相隔离。
5. **上下文工程是第一公民**：
   - schema 摘要 + 数据抽样（head/统计）注入 prompt；
   - 表多走向量检索（pandas-ai / Vanna 模式）；
   - 业务口径走语义层（WrenAI MDL），比裸 schema 可信一个量级；
   - 敏感数据默认不出域（dataline 模式）。
6. **两级规划**：先粗分解标依赖，再合并精炼（TaskWeaver）；固定流程用 DAG（AWEL）。
7. **记忆与经验**：轮内 shared memory + 跨会话经验提炼。
8. **探索式交互**：数据分析天然非线性——分支线程、图表推荐、可视化确认比单线聊天更贴合（data-formulator）。
9. **产物导向**：终点是报告/图表/SQL/结论，不是对话轮次。
10. **遵守可移植标准**：AGENTS.md、.agents/skills、MCP，不锁死生态。

## 四、对 E:data-agent 的落地建议

**推荐骨架**：Planner → Coder → Executor（常驻内核）→ Verifier 循环，外加 schema RAG 与沙箱。

**MVP 分层路线**：
1. v0：单会话 code interpreter——DuckDB/pandas 代码生成 + 报错回灌修正循环 + 数据预览注入；
2. v1：schema 向量库 + 多表选择 + 查询结果缓存；
3. v2：会话持久化 + 经验提炼 + 语义层（业务口径元数据）；
4. v3：分支探索 UI / 报告产物。

下一步可以用本仓库已初始化的 OpenSpec 跑 `/openspec-propose` 把 v0 设计固化成 specs + tasks。

---

# 附录：第二批调研（不同思想路线）

## 五、第二批项目深挖笔记

### 8. microsoft/lida —— 可视化生成的模块化管线
- 流水线：**Summarizer → Goal Explorer → VisGenerator → Editor → Explainer → Evaluator/Repair → Recommendation → Infographics**，每步是独立语义模块，可单独调用。
- **数据压缩摘要是基石**：先对数据集生成紧凑 JSON 摘要（字段/类型/统计/样本），下游所有 prompt 只带摘要不带原始数据。
- 「可视化即代码」、grammar-agnostic（matplotlib/altair/d3 皆可），生成代码 → 执行 → 自评 → 修复闭环。

### 9. xlang-ai/OpenAgents —— 产品级 Data Agent
- 三 agent 之一是 Data Agent（Python/SQL + 数据工具），跑在真实 Jupyter 后端上。
- 卖点是**应用层工程**：为非专家用户优化的 Web UI、针对常见失败的快速恢复路径、低延迟响应设计——论文明确批评多数框架只管 PoC 不管应用层。

### 10. MetaGPT DataInterpreter（roles/di/）
- 源码：`metagpt/roles/di/data_interpreter.py`。
- **notebook 常驻执行**（ExecuteNbCode 在 Jupyter 内核里跑），状态跨步保持。
- **BM25ToolRecommender：工具也要 RAG**——工具注册后按任务 BM25 检索相关子集进 prompt，不全量塞。
- react / plan_and_act 双模式可切换；LLM 输出 thought + `state: bool` 显式判断任务是否完成。
- 已演化出 role_zero（MCP 工具 + 命令式交互），说明该路线在向通用 agent 底座收敛。

### 11. vanna-ai/vanna（已归档 2026-03）—— 治理型 text-to-SQL
- 经典思想：用 **DDL / 业务文档 / SQL 问答对**训练向量库，生成时检索注入（RAG 而非微调）。
- 2.0 主打企业治理：**身份贯穿每一层**（system prompt → 工具执行 → SQL 自动行级过滤）、审计日志、生命周期钩子、`<vanna-chat>` 可嵌入流式组件（SQL/表格/图表/摘要多格式流式输出）。

### 12. tablegpt/TableGPT2（浙大）—— 模型侧路线
- 主张：与其通用 LLM + 复杂脚手架，不如**让模型原生吃表格**——列画像编码进模型上下文（多模态列编码器），TableGPT2-7B 专攻 table QA。
- agent 实现基于 LangGraph；自带 RealTabBench 评测集 + ipy-kernel 集成。

### 13. ZJU-OmniAI/Data-Copilot —— 设计师 + 调度员
- **离线**：LLM 通过自我请求 + 迭代精炼，自主设计一整套接口工具（create_tool/、tool_lib/）。
- **在线**：只做调度，串/并行调用既有接口，把异构数据源变成图/表/文本。
- 思想：把「运行时自由代码生成」换成「离线自造稳定工具层」，换取可预测性、低成本、可复用。

### 14. quadratichq/quadratic（已闭源）—— 网格原生执行
- AI 电子表格：格子级 Python/JS/SQL 单元格，Python 走 **Pyodide WASM 浏览器内执行**。
- 2025 后主仓库转闭源，仅留 MCP 插件（把电子表格操作暴露为 MCP server 供 agent 调用）——又一个「agent 走 MCP 接口」的信号。

### 15. WecoAI/aideml（AIDE）—— 树搜索代替线性循环
- 每个 Python 脚本是解空间中的一个节点，LLM 生成补丁产生子节点，**指标反馈驱动剪枝与引导**（explore/exploit）。
- MLE-bench 实测：树搜索比最强线性 agent（OpenHands）**多拿 4 倍 Kaggle 奖牌**；被 AI Scientist-v2、RE-Bench 采用。
- 启示：当任务有客观可算指标（准确率/误差）时，线性 REPL 循环不是最优——要搜索与回溯。

## 六、第二批补充结论

11. **数据摘要是统一上下文层**：LIDA 的 summarizer、TableGPT2 的列画像、dataline 的 schema-only，本质都是「给模型构造有损压缩的数据画像」，绝不塞原始数据。
12. **工具多了也要检索**（MetaGPT 的 BM25 工具推荐器），与 schema RAG 同构。
13. **线性循环 vs 树搜索**：探索式分析用循环，指标明确的分析用搜索回溯（AIDE）。
14. **离线造工具 + 在线调度**（Data-Copilot）是 code-first 的稳定化变体，适合高频重复场景。
15. **身份与治理贯穿全链路**（Vanna 2.0）：做多用户产品时，权限要渗到 SQL 生成与执行层，不是 UI 层的事。
16. **生态信号**：第一波（2023–24）代码解释器类项目大量归档或转型（TaskWeaver、Vanna 归档，open-interpreter 转型，Quadratic 闭源）；活下来的要么做成了完整产品（pandas-ai、data-formulator、DB-GPT、WrenAI），要么退到模型/算法层（TableGPT2、AIDE）。**做自己的 agent 应学模式，而不是 fork 死代码库。**
