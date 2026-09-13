# N2：画布资产与确定性重放（canvas-assets）

## Why

路线图 v3 N2（implementation-roadmap.md §3）：三层架构的**产品内核**，且全程无 AI——
图表 = ChartAsset（processor 脚本 + params + 数据源绑定），重渲染是 clean kernel 里的
确定性重放，过输出 schema 闸门才落画布。N3 的 AI 只会成为"对着这套 schema 写代码的
作者"。本阶段末冻结 processor 协议与渲染契约（design-architecture §2.6）。

## What Changes

- backend `canvas/`：models（ChartAsset/ParamField/DataSourceBinding/OutputSchema/
  GateReport）、assets（workspace/assets/{id}/ FS 权威 + sqlite 索引 + meta_hash 漂移
  标 broken + versions/{n}.tar + expected_version CAS）、gate（纯函数：columns 集合→
  dtype 族→row_bounds→payload 2MB；draft 首闸盖章 output_schema）、kernels（clean 预热
  池复用 exec/kernel_pool，reset 残留实测）、replay（编译 processor 进内核 → 注入
  lazy ctx{params,data,log} → process(ctx) → 哨兵 JSON 回收 → 闸门 → render.json/config.json）
- backend `schemas/chart.py`：RenderData（列式 tables）+ ChartConfig（chart_type 8 类
  白名单 / option_template 纯 JSON / data_map 通道映射 / appearance 高宽字体图例色板）
- api：POST /api/assets（手工建卡=写 processor 源码+绑定，即验）、GET /api/assets
  （冷加载）、detail/render/replay/params(PUT)/canvas(PATCH placement)/rollback/history/DELETE；
  history 行入 replays 表（审计前身）
- frontend：**VSCode 三栏工作台**（左数据源树·中画布·右 AI 面板灰态占位）；
  ChartCard ECharts 渲染器（列式 dataset + data_map 编码 + 纯 JSON 防线）；ParamForm
  （param_spec 驱动；affects=appearance 本地即时重渲染零网络 / data 才 replay）；
  GateBanner 失败留屏上版 + ⚠；版本历史/回滚 UI；**linear-app token 换皮**
  （tokens.css → index.css 变量，--chart-1..5=ECharts 默认色板，亮色回退 shadcn）
- fixtures：3 个手写种子 processor（bar TopN / line 月趋势 / pivot 表）当回归集

明确不做：AI 工具与 /chat（N3）、promote（依赖 adhoc，N3）、审批 UI（N3 起弹窗，
N2 的写资产=可信本地用户直接可用）。

## Impact

- Affected specs: `specs/canvas-assets/spec.md`（新增）
- Affected code: backend canvas/ + schemas/ + api/{assets,canvas}.py；frontend 主题与
  三栏壳、canvas 组件族；复用 catalog/reader（绑定懒加载）与 exec/kernel_pool（clean 池）
- 验收锚点：v3 DoD #2 四条（字节级一致合同锁、零 LLM、闸门失败留屏、外观零网络）
- 风险前置项：clean kernel 冷启动延迟与 reset 残留——本阶段首日实测，结论回写 design.md
