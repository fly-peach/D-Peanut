# Design

## 首日实测（clean kernel 风险前置项，2026-09-14，WSL ext4 venv）

- 冷启动 0.71s；热执行往返 ~5ms；`%reset -f` 清干净用户命名空间（跨 cell 验证无残留）；
  内核解释器=后端 venv（pandas 3.0.5、duckdb、`data_agent.*` 可 import）
- 结论：预热池=N 个常驻内核 + 每次重放前 `%reset -f`；reset 失败（超时/炸）→ 弃用该核
  shutdown + 补新。默认池 size=2，env `REPLAY_POOL_SIZE` 可调

## 决策

1. **FS 权威 + sqlite 镜像**：`workspace/assets/{id}/`（meta.json/processor.py/
   params.json/versions/{n}.tar/render.json/config.json）；index.db `assets` 表存
   检索列（name/status/version/meta_hash/placement）；每次读校验 meta.json hash≠meta_hash
   → status=broken（手改/漂移可见化）；save/replay 用 `expected_version` CAS。
2. **processor 协议（N2 末冻结）**：三导出 `PARAM_SPEC: list[dict]`（元素=ParamField：
   key/label/type/default/min/max/options/dataset_ref/affects: data|appearance）、
   `DEFAULTS: dict`、`process(ctx) -> (RenderData, ChartConfig)`；ctx = ProcessorContext
   (params, data: LazyData, log)。**禁旁路出口**（无 emit），禁会话变量（clean kernel 自证）。
3. **重放执行链**（replay.py）：取核 → `%reset -f` → 注入 shim（定义 LazyData：按
   bindings 元数据 dict{alias: {kind,path/format/sheet | conn+table}} + 暴露
   `__da_load(alias)` 在**内核内**用 catalog.reader 同源逻辑懒加载 df——同一 venv 同
   一套 reader 代码，`from data_agent.catalog.reader import read_dataset`）→
   `importlib` 编译 processor.py → `process(ctx)` → 结果 pydantic model_dump 后
   print 哨兵包 JSON（`<<<DA_RESULT>>>…<<<END>>>`；log 走 `<<<DA_LOG>>>` 行）→ 端解析 →
   gate → 写 render.json/config.json + replays 审计行。30s 超时=闸门失败（passed:false+timeout）。
4. **连接串边界**：sql 绑定的 conn_target 由 replay 服务从 secrets 解析后**只注入内核**
   （本机可信执行体），不进 processor 源码、不进任何 API 响应；df.attrs 挂 dataset_ref 供溯源。
5. **闸门盖章**：draft 无 output_schema → 首闸以当次实际输出反推盖章（columns 集合语义、
   dtype 族、row_bounds[0, max(10k,10×本次)]、payload 2MB）；此后每次重放必须过同一 schema。
   失败：render.json **不覆盖**（上版留屏），GateReport(passed=false, errors[]) 存 meta.last_gate。
6. **渲染契约**：RenderData.tables{name → RenderTable{dimensions, source:列式}}；
   ChartConfig{chart_type(8白名单), option_template(纯 JSON), data_map{channel→"table.column"},
   appearance{height,width,font_size,color_palette,show_legend,show_label}}。前端
   ChartCard 按 chart_type 建 base option + data_map 编码 + option_template 深合并；
   渲染器拒收含 `function`/`=>`/`javascript:` 的字符串值（注入防线，单测）。
7. **参数双通道**（affects）：appearance 参数表单改动 → 前端直接改 appearance 重
   setOption **零网络**；data 参数 → PUT /params（按 PARAM_SPEC 强校验）+ POST /replay。
8. **版本**：save/params/replay 通过（status→validated/on_canvas 的变化点）打包
   versions/{n}.tar；rollback=解包+version+1（新快照记 rollback 来源）；history=meta
   版本表+replays 审计合并视图。
9. **手工建卡端点**（N2 无 AI）：POST /api/assets {name, source, bindings, params?} →
   校验三导出（args 层轻量：AST 解析顶层赋值）→ 写 draft → 同步跑一次 replay 验 →
   validated；成功响应含 GateReport。这是 N3 write_processor/validate_asset 的同一底层。
10. **三栏壳**：App.tsx 变 `Workspace(三栏) | Datasources | Settings占位`；左栏复用
    catalogStore 树；右 AI 面板 disabled 占位（N3 换 useChat）；画布 placement 存 sqlite
    assets 表（x/y/w/h/z，PATCH 纯本地布局不动数据）。

## 接口（api/assets.py + canvas.py）

```
POST /api/assets                {name, source, bindings, params?} → asset(+GateReport)
GET  /api/assets                冷加载：索引+placement+last_gate+render 摘要行
GET  /api/assets/{id}           详情（source/param_spec/params/schema/history 头）
GET  /api/assets/{id}/render    {render, config, version, gate_passed}
POST /api/assets/{id}/replay    同步重放 → 同 render 形态 + GateReport
PUT  /api/assets/{id}/params    {params, expected_version} → 200 已标 dirty / 409 版本冲突
PATCH /api/assets/{id}/canvas   placement
POST /api/assets/{id}/rollback  {to_version}
GET  /api/assets/{id}/history   版本+重放审计
DELETE /api/assets/{id}
```

## Risks / Trade-offs

- 哨兵 JSON 回收被用户代码 print 干扰 → 用 uuid 哨兵对（每次重放随机），解析取最后一段
- reset 后 `data_agent` import 缓存仍在 sys.modules（无害：只读逻辑），df 变量全清 ✅
- 大表绑定的内核内懒加载内存风险 → LazyData 只按需读 + reader 谓词下推；processor 规范
  模板要求先聚合（写进 N3 prompts，N2 fixture 示范）
- payload 2MB 内联 render.json → 画布冷加载 GET /assets 只回索引，逐卡拉 /render（懒）
- sqlite 写并发（replay 同时改 params）→ 单连接短事务 + CAS，冲突方重试读

## 已冻结（N2 末回填区，验收时填写）

- （待填）processor 协议 / RenderData / ChartConfig / GateReport / replay 语义

## 已冻结（N2 末，只加不改）

- `process(ctx) -> (RenderData, ChartConfig)`；`PARAM_SPEC/DEFAULTS` 必须为字面量（AST 可提取）
- `RenderData{tables{dim,列式source}, row_count, payload_bytes}`；`ChartConfig{chart_type∈8白名单,
  option_template 纯 JSON, data_map{通道→"table.column"}, appearance}`
- `GateReport{passed, checks[], errors[]}`；闸门顺序 columns(子集)→dtype族→行界→2MB→30s；
  draft 首闸盖章 = 当次输出
- 端点形态：create 即验、replay 200+passed:false（4xx 只留给操作错误）、PUT params CAS
- 资产目录布局 asset/{meta.json, processor.py, params.json, versions/, render.json, config.json}
