# data-catalog Specification

## ADDED Requirements

### Requirement: 三源数据集注册与可寻址

系统 SHALL 将本地文件（CSV/Parquet/XLSX 含多 sheet）、挂载文件夹（glob 展开物化为独立子
Dataset）、sqlite 库（表/列反射）统一注册为 Dataset；`DatasetRef{name, revision}` 全局唯一
可寻址；所有路径经 DATA_ROOT jail 断言；本阶段 Dataset 契约（含 TableProfile）冻结供上层复用。

#### Scenario: 文件夹批量注册

- **WHEN** 注册含 200 个 CSV 的挂载文件夹
- **THEN** 异步扫描在 5 分钟内物化为 200 个可独立寻址、各自画像的子 Dataset，
  目录与详情端点可见各自 scan/profile 状态

#### Scenario: jail 越界拒绝

- **WHEN** 注册路径 resolve 后不在 DATA_ROOT 之下
- **THEN** 返回 400 且索引无任何写入

### Requirement: 增量扫描与 revision 指纹

folder rescan SHALL 基于 mtime+size 树指纹做 diff：仅变更文件 bump revision 并将画像标
outdated、新增建子 Dataset、删除标 failed；symlink 不参与扫描。

#### Scenario: 只动变更项

- **WHEN** 改动文件夹内一个文件后 rescan
- **THEN** 仅该子 Dataset 的 revision+1 且画像待重算，其余子 Dataset 状态与画像缓存不变

### Requirement: 数据画像与 prompt 预算

系统 SHALL 产出列级画像（dtype/缺失率/基数/数值范围/时间列识别/类别 TOP-N/3 样本值/主键提示），
按 revision 缓存；序列化注入 prompt 时每表 ≤500 token，超限按"样本值→TOP-N→数值范围"逆序裁剪。

#### Scenario: 画像正确性

- **WHEN** 对含时间列、高基数列、缺失列的 fixture 画像
- **THEN** 各列统计字段符合预期且时间列被识别（含范围）；重复画像命中缓存不重算

### Requirement: 隐私边界与连接串安全

privacy_mode 开启的 Dataset，其画像 sample_values 必须清空、preview 端点只回统计摘要；
SQL 连接串仅存 workspace/secrets.json（0600），索引/API 响应/日志/prompt 全链路零明文。

#### Scenario: 隐私模式无原始行

- **WHEN** privacy_mode 开启后调用 preview 与 profile
- **THEN** 响应不含任何原始行数据与样本值，仅统计摘要

#### Scenario: 连接串零泄漏

- **WHEN** 注册并访问 sqlite 源的详情/画像/preview
- **THEN** 响应体、sqlite 索引与捕获日志中均不出现连接串明文

### Requirement: 统一读取接口

系统 SHALL 提供 `read_dataset(ref, columns?, limit?) -> DataFrame` 唯一读取路径
（CSV/Parquet 经 DuckDB、XLSX 经 pandas 注册临时视图），供画像、preview 与后续的
AI 查询、资产绑定复用，不允许旁路读法。

#### Scenario: 限行读取

- **WHEN** 对大 CSV 以 limit=20 读取
- **THEN** 返回前 20 行且未做全表物化（列裁剪 + 行数限制下推）

### Requirement: 前端数据源管理可见

前端 SHALL 提供数据源页：三源注册表单（含 sheet 选择与 glob 输入）、扫描/画像状态轮询展示、
画像卡与 preview 表、隐私开关、重命名与删除。

#### Scenario: 注册到就绪闭环

- **WHEN** 在页面注册一个 CSV 并轮询
- **THEN** 状态从 pending 走到 ready，画像卡与 preview 渲染，删除后从目录消失；
  `tsc -b` 与 `vite build` 零错误
