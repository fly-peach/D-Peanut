# Tasks

## 0. 准备
- [ ] 0.1 分支 n2-canvas-assets（✅ 已建）；首日 kernel 实测（✅ 0.71s/reset 无残留，结论入 design）

## 1. 契约层
- [ ] 1.1 `schemas/chart.py`：RenderData/RenderTable/RenderColumn/ChartConfig/Appearance/DataMap（pydantic，8 类白名单常量）
- [ ] 1.2 `canvas/models.py`：ParamField/DataSourceBinding/OutputSchema(表+列+界)/ChartAsset/GateReport/ReplayResult
- [ ] 1.3 `canvas/gate.py` 纯函数 + 表驱动单测 ≥10（列集合/dtype 族/行界/载荷/timeout 语义）

## 2. 资产服务
- [ ] 2.1 `canvas/assets.py`：FS 目录读写（原子 tmp+rename）、meta_hash 漂移 broken、versions tar 快照、expected_version CAS、索引表建表
- [ ] 2.2 单测：create/get/update/rollback/drift/CAS 冲突

## 3. 执行面
- [ ] 3.1 `canvas/kernels.py`：预热池（size=REPLAY_POOL_SIZE 默认2）、%reset -f、失败弃核补新
- [ ] 3.2 `canvas/replay.py`：哨兵协议 + LazyData 注入（内核内 data_agent.catalog.reader 懒加载）+ 结果解析 + 首闸盖章 + render/config 落盘 + replays 审计
- [ ] 3.3 合同锁测试：3 个种子 processor（tests/fixtures/processors/：bar 城市TopN / line 月度趋势 / pivot 渠道×城市表）× replay×100 RenderData 字节级一致；断言 pydantic_ai 不在 sys.modules（零 LLM）

## 4. REST
- [ ] 4.1 `api/assets.py`：proposal 列的 10 端点；create 的 AST 三导出校验；params 校验按 PARAM_SPEC；409/404 语义
- [ ] 4.2 main 接线（workspace assets 目录、replay 服务注入 app.state）；TestClient 集成：建卡→validated→改参(data)→replay→闸门失败留屏→appearance 通道（纯前端断言在 5.4）→rollback→history→delete

## 5. 前端
- [ ] 5.1 linear-app 换皮：tokens.css 翻译进 index.css `:root/.dark`（含 --chart-1..5 暗底友好序列色）
- [ ] 5.2 三栏壳：App→Workspace/Datasources/Settings(占位)；左栏数据源树（catalogStore 复用）；右 AI 面板 disabled 占位
- [ ] 5.3 `stores/canvasStore` + `api/client.ts` 扩展（assets 端点、冷加载、逐卡 render 懒取）
- [ ] 5.4 ChartCard：echarts 动态 import、chart_type base option 生成 + data_map 编码 + option_template 深合并 + appearance 应用（height/width/font/legend）+ 纯 JSON 拒绝单测（vitest 或 tsc+手测清单，取轻）
- [ ] 5.5 ParamForm（param_spec 驱动；affects 分流：appearance 本地重渲染零网络 / data 走 PUT+replay）+ GateBanner（失败 ⚠ 上版留屏）+ 重跑按钮 + 版本历史/回滚弹层 + placement 拖动（轻实现：CSS grid span 调整即可，不上自由拖拽库）
- [ ] 5.6 tsc -b + vite build 零错误

## 6. 部署与验收
- [ ] 6.1 docker 重建起服务：API 级 e2e（建卡/replay/失败留屏）+ browser-use 截图三张（画布出图/参数表单/闸门失败态）；daemon 问题先修（close --all/日志/~/.config/browser-harness）
- [ ] 6.2 DoD #2 四条自动化断言全绿；回归 68+N 全绿、ruff 零告警
- [ ] 6.3 design.md 回填「已冻结」段；归档本 change（spec 合入 specs/）
