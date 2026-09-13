# Design

## 决策

1. **N1 阶段 Dataset 索引即权威**：`workspace/index.db` 的 datasets/profiles 两张表存全部
   元数据与画像缓存（revision 键）；content_hash 自愈是 N2 assets 的事，本阶段不涉及。
   `rebuild_index` 提供"从扫描源重建"命令（folder/sql 可重放，单文件路径失联标 failed）。
2. **注册即返回 + 异步流水线**：POST /datasets 落库 pending → BackgroundTasks 依次
   scan→profile，状态 `pending|scanning|ready|stale|failed`（scan_status 与
   profile_status 两列独立）；前端轮询 GET detail。不引入任务队列——单进程足够，
   N2 若重放占时再评估。
3. **folder 物化 children**：扫描后每个命中文件成为独立 FileDataset（parent_id 指回），
   各自可寻址、各自画像、N2 可单独绑定；fingerprint = `sha1(sorted(relpath:mtime:size))`
   树指纹；rescan 做 diff：新增→建 child、mtime 变→child revision+1 且画像标 outdated、
   删除→child 标 failed；**symlink 一律忽略**（防环）。
4. **XLSX 走 pandas 临时视图**（沿用旧 M1 决策）：DuckDB excel 扩展需网络安装；
   CSV/Parquet 直接 attach。sheet 在注册时列出供选择，多 sheet = 多 FileDataset（sheet 后缀）。
5. **profiler 在后端进程内跑，不占内核**：pandas/DuckDB 直接算——row_count、dtype、
   null_rate、cardinality（approx）、数值 min/max、类别 TOP-N、时间列识别（抽样 5k 行
   try-parse 率 >0.9 判时间列 + 报范围）、每列 3 个 sample_values、pk_hint（基数==行数）。
   序列化进 prompt 的预算 ≤500 token/表：超限按"样本值→TOP-N→范围"逆序裁剪（纯函数
   `render_profile_for_prompt(profile, budget)`，表驱动单测）。
6. **连接串安全三道闸**：明文只进 `secrets.json`（0600、不入 git、不进索引）；Dataset 行只存
   `conn_ref` 键名；API 响应与日志过统一脱敏 filter（测试断言响应体与 caplog 无明文）。
   N1 的 sql 源仅 sqlite（DuckDB ATTACH DATABASE 反射）；PG/MySQL 推 N4 后。
7. **reader 契约先立**：`read_dataset(ref, columns=None, limit=None) -> DataFrame`——
   N1 服务 preview/画像；N3 的 query_data、N2 的 bindings 懒加载复用同一函数，避免第三套读路径。
8. **privacy_mode 是 Dataset 属性**（默认取 settings 全局值）：开启后 sample_values 清空、
   preview 端点拒绝返回原始行（只回统计摘要）；画像缓存按 (revision, privacy) 双键，
   切换不重算基础统计。
9. **路径 jail**：所有注册路径 `Path.resolve().is_relative_to(DATA_ROOT)`，违例 400；
   Windows 宿主机路径 ↔ 容器路径差异在 compose 两卷 + 文档解决，代码只见容器内绝对路径。
10. **前端最小闭环**：pages/Datasources 单页 + catalogStore（zustand，注册后轮询至 ready，
    指数退避上限 5s）；复用 shadcn 基件与 ai-elements 无关；echarts 本页不引入。

## 接口（api/datasets.py，对齐 design-architecture §3.1）

```
POST /api/datasets                 {kind, path|root+glob|conn_ref+db+table|privacy_mode?}
GET  /api/datasets[?kind=]         目录（含状态摘要）
GET  /api/datasets/{id}            详情（scan/profile status、children 计数）
POST /api/datasets/{id}/rescan     folder 手动增量
GET  /api/datasets/{id}/profile    TableProfile（privacy 生效后的形态）
GET  /api/datasets/{id}/preview?n= preview（privacy 开启→统计摘要；n≤50）
PATCH /api/datasets/{id}           重命名 / 描述 / 隐私开关
DELETE /api/datasets/{id}          N1 直接删（N2 起加引用检查；此处留 hook）

GET|PUT /api/settings              SettingsService 骨架：GET 合并 settings 表+secrets 掩码
                                   （secrets 只回后4位，PUT 缺省字段=不覆盖）；仅运行配置
                                   （DATA_ROOT 展示/隐私默认/画像预算），LLM 表单与
                                   llm/test 归 N3（model_factory 热加载）
```

## Risks / Trade-offs

- **200 文件扫描性能**：逐文件画像在 120s pytest 超时内必须完成（DoD 给的是 5min，
  测试用 200 个小文件，目标 <60s）；画像抽样上限（如 10k 行）保证单文件成本恒定。
- **BackgroundTasks 与测试**：TestClient 会同步等待后台任务；集成测直接 await 内部
  `scan_and_profile(dataset_id)` 纯函数化入口，不赌框架行为。
- **sqlite 反射的表变更**：N1 不做自动 schema diff，rescan 时重反射并比对指纹（简单实现：
  schema_hash）；漂移只标 stale 不通知。
- **folder 中途失败**：单 child 画像炸不拖垮整批（逐 child try，失败标 failed + last_error）。
- zustand/轮询是前端新面：与 M0 静态演示页并存，Workspace 主页 N3 才做。

## 已冻结（N1 末，只加不改）

- `DatasetRef{dataset_id, name, revision}`（catalog/models.py）
- `Dataset`（kind=file|folder|sql；status 枚举；privacy_mode 三态 None=跟随全局）+
  `FileMeta/FolderMeta/SqlMeta`（SqlMeta 只存 conn_ref）
- `TableProfile/ColumnProfile`（含 is_time/pk_hint/top_values/sample_values）
- `read_dataset(ds, *, conn_target?, columns?, limit?)` / `count_rows(ds, *, conn_target?)`
  （catalog/reader.py——N2 bindings 懒加载与 N3 query_data 必须复用此入口）
