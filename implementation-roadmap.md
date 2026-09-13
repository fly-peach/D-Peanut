# 实施路线图 v3：三层架构，从数据底座到可信产品

> 核心思想不变：**先造最里层，把技术风险前置清零；逐层向外封装；每层结束可演示可回归；层边界接口进入外层后只加不改。**
> v2→v3 变化：产品定义改为三层（数据导入 catalog / 画布 canvas / AI 对话框 agents），原 M1-M5 六层里程碑作废，重排为 **N1-N4**；M0 已完成资产（内核池、适配器桥、CI/Docker、前端基座）全部沿用。设计依据：design-architecture.md v3 + agent-design.md v3。

## 0. 封装次序与冻结点

由内向外：

1. **N1 数据底座**：Dataset 注册/扫描/画像/读取——数据可被寻址
2. **N2 画布资产**：ChartAsset + clean-kernel 重放 + schema 闸门 + 前端渲染——**不依赖 AI 的产品内核先成立**
3. **N3 AI 编码环**：coding agent 十工具 + 轻模式 + promote + AI toggle——AI 作为"作者"接上
4. **N4 信任稳健**：审批预览 / 审计 / 压缩 / 并发 / 部署打磨 → tag **v0.1.0**

次序四原则（v3 表述）：
- **风险前置**：重放确定性与 clean kernel 冷启动在 N2 首日消化（v3 最大技术不确定项，替代旧 Spike A 位置）
- **每层可演示**：N1 数据源页 → N2 手画三张能重跑的卡（零 AI！）→ N3 对话建卡 → N4 完整 DoD
- **接口冻结点**：**N1 末** Dataset/DatasetRef 契约；**N2 末** processor 协议 + RenderData/ChartConfig + 闸门（此后 AI 只准对着 schema 写码）；**N3 末** 十工具签名 + 事件归属表
- **测试随层走**：纯函数（verifier/gate/profiler）表驱动单测；重放确定性回归集是 v3 架构合同锁；对话流用 TestModel 离线契约测试（Spike A 测试升格）

## 1. M0 已完成（2026-09，归档）

脚手架 + 三 spike 全绿：`exec/kernel_pool.py`（每会话 ipykernel、跨轮常驻、超时中断恢复）、VercelAIAdapter granular 三方法 + DataChunk 自定义 data part（tests/test_spike_a_*）、bun/Vite/Tailwind4/shadcn/ai-elements 构建链、CI 三 job、多阶段 Docker + compose :8010。详见 openspec/changes/archive/m0-scaffold-spikes/。

> 旧 M1（引擎层/CLI）与 M2（协议层）的 change 计划随 v3 产品定义重定义而作废删除；其仍成立的组件设计（profiler/duck/verifier 测试清单、TestModel 轨迹测法、预算/reflect 计数、画像 token 预算）按下列 N 阶段标注回收。

## 2. N1 数据导入层（约 1 周）—— change `data-catalog`

1. `catalog/models.py` + `registry.py`：Dataset 三 kind、DatasetRef(revision)、sqlite 索引 + rebuild_index（content_hash 自愈归 N2 assets）
2. `sources/file.py`：CSV/Parquet/XLSX（pandas 读，绕 DuckDB excel 扩展——旧 M1 决策）；`sources/sql.py`：sqlite 反射起步（PG/MySQL N4 后）；secrets.json + conn_ref
3. `scan.py`：folder glob 展开物化 child + mtime+size 树指纹 diff
4. `profiler.py / sampler.py / reader.py`：旧 M1 设计整体搬（≤500 token/表预算、隐私清样本值、XLSX 临时视图、DuckDB 谓词下推）
5. `api/datasets.py` 全套端点 + compose 加 DATA_ROOT/WORKSPACE_ROOT 两卷 + 路径 jail
6. `settings.py` + SettingsService：settings 表 + `api/settings.py` 骨架（运行配置读写/secrets 掩码，**不含 LLM 表单**——N1/N2 零 AI 不该被迫配 key）
7. 前端数据源页：注册表单、扫描/画像状态轮询、画像/预览卡、隐私开关

**验收**：DoD #1（200 文件 <5min、增量 rescan、连接串零泄漏、隐私无原始行）。
**冻结**：Dataset/DatasetRef/TableProfile 契约——N2/N3 只读不改。

## 3. N2 画布资产与重放（约 1.5 周）—— change `canvas-assets`（全程无 AI）

1. 首日专项：clean kernel 预热池（`canvas/kernels.py`）冷启动与 reset 残留实测 → 定池策略（v3 风险前置项）
2. `canvas/models.py`：ChartAsset/ParamField/Binding/OutputSchema/RenderData/ChartConfig + `schemas/chart.py`
3. `canvas/assets.py`：FS 读写（原子 tmp+rename）、版本快照、乐观锁、index 漂移标 broken
4. `canvas/gate.py`：闸门纯函数（columns→dtype→row_bounds→payload 2MB），表驱动单测
5. `canvas/replay.py`：processor 编译进 clean 命名空间 → process(ctx) → 闸门 → render.json/config.json；draft 首闸盖章 output_schema
6. `api/assets.py + canvas.py`：replay/render/params/canvas/rollback/history 端点（闸门失败 = 200+passed:false）
7. 前端：画布页 ChartCard（ECharts dataset 消费 + 纯 JSON 契约渲染器）、ParamForm（param_spec 驱动）、重跑按钮、GateBanner 上版留屏、外观参数前端本地重 setOption、表格卡
8. fixture：**3 个手写种子 processor（bar/line/pivot）当回归集**——replay×100 字节级一致合同锁

**验收**：DoD #2 全部四条。
**冻结**：processor 协议 + 渲染 schema + 闸门语义。

## 4. N3 AI 编码环（约 1.5 周）—— change `ai-coding-loop`

1. `agents/`：deps/prompts（七块新纪律 + processor 模板 + 动态 catalog 摘要注入）/tools 十工具/approval 装配
2. `runs/`：/chat（toggle 409 语义）+ granular 桥 + data-asset-changed 通知帧 + FinalAnswer/cost；budget 熔断（旧 M1 设计搬）；store 补 usage/审批
3. 模型配置：`agents/model_factory.py`（每 Run 现造 OpenAIChatModel+OpenAIProvider，保存热生效）+ `POST /api/settings/llm/test` + Settings 页模型区（provider 预设下拉/base_url/key 掩码/[测试连接]）
4. deferred 审批续跑：DeferredToolRequests → 前端 ConfirmDialog → /confirm 携结果 + 历史续跑
5. 轻模式：emit_adhoc_chart（ToolReturn.metadata 内联卡）+ `POST /assets/promote` 确定性 seed + 合成消息改写环
6. 前端：useChat 接真流（替换 M0 静态演示）、工具卡、ConfirmDialog、adhoc 卡 + promote 按钮、AI toggle 顶栏、修复横幅/成本徽章
7. 测试：`agent.override(TestModel/FunctionModel)` 离线全环轨迹（探→试→write→validate 炸→修→save）；Spike A 帧序升格为契约测试；live 标记默认 skip

**验收**：DoD #3 全部五条。
**冻结**：十工具签名 + 事件归属表（design-architecture §3.2）。

## 5. N4 信任与稳健（约 1 周）—— change `trust-hardening`

1. 审批弹窗升级：verifier 命中项 + processor diff 预览；option_template 注入面渲染器单测
2. replay/审批审计查询页；资产全生命周期视图
3. 历史压缩（memory/：ProcessHistory + CompactionPart）；并发 save CAS 用例
4. folder 自动重扫（watchdog 或 cron，依 N1 实测）；SQL 连接串加密与轮换 UI
5. 断线双通道恢复打磨；错误页/结构化日志；PNG/CSV 导出补齐
6. 打 tag **v0.1.0 = MVP 完成**

**验收**：DoD #4 四条 + 旧 DoD #4/#5 语义平移（断网重连、审计日志）。

## 6. v1+ 向外扩展（每项 = 一层薄封装，构建在画布模型之上）

- 向量检索 `search_schema`（defer_loading 复活）/ 知识库口径 / 经验库（成功轨迹）——memory 层新实现
- PG/MySQL 连接器全量 / 容器沙箱——**kernel 与 reader 换实现，接口不变**
- HTML 报告：画布资产 → 报告导出（新表述，替代旧"报告组装"）
- JWT 多用户 + 审计强化 · Arrow 引用式渲染（>2MB 产物）
- Data Threads 分支探索 / 语义层（Dataset 画像 → MDL）/ AIDE 式指标搜索

规律不变：v1 每一项都不动 spine。层边界冻结的价值在此兑现。

## 7. 过程实践

- **OpenSpec 驱动**：N1-N4 各一个 change（propose → apply → archive），验收直接抄本文各节；旧 m1-engine-layer change 已删除（未提交未实现，不进归档）
- **演示脚本制**：每层录 2 分钟 demo；N2 的"零 AI 三卡重跑"是 v3 产品论点的活广告
- **fixture 回归集**：3 种子 processor + 20 标准问句 + 错列名/隐私/大 payload 负例，每次动 spine 必跑
- **分支策略**：main 永远可跑；现存的 agent / data-processor / data-repoter 三个空分支不合用即删，N 阶段用 `n1-data-catalog` 等新名

## 8. 工期粗估

全职：N1-N4 ≈ 4-5 周（N1 1 周 / N2 1.5 周 / N3 1.5 周 / N4 1 周）；业余 ×3。最大不确定项 = **重放确定性与 clean kernel 冷启动**（N2 首日消化），次项 = TestModel 多步工具环脚本复杂度（N3 先做最小闭环验证）。
