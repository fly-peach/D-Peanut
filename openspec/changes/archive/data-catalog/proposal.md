# N1：数据导入层（data-catalog）

## Why

路线图 v3 N1（implementation-roadmap.md §2）：三层架构的地基。把本地文件夹 / 文件 / SQL 库
统一注册为**可寻址、已画像**的 Dataset，N2 画布资产绑定它、N3 AI 编码环探查它。数据接口
（Dataset / DatasetRef / TableProfile 契约）在本阶段末冻结——上层此后只加不改。

## What Changes

- backend 新增 `catalog/` 包：models / registry（sqlite 索引）/ scan（指纹 diff）/
  sources{file,folder,sql} / profiler / sampler / reader
- `api/datasets.py`：注册（异步扫描+画像）、目录、详情、rescan、profile、preview、
  重命名、删除 全套 REST + BackgroundTasks
- `settings.py` + SettingsService + 运行期 workspace 引导：`workspace/index.db`（含
  settings 表）、`secrets.json`（0600）；`GET|PUT /api/settings` 骨架（运行配置读写 +
  secrets 掩码回显，**不含 LLM 表单**——N1/N2 零 AI 不迫使用户配 key）；
  compose 加 `DATA_ROOT` / `WORKSPACE_ROOT` 两卷；路径 jail（resolve 断言）
- 画像器：列级统计 + 时间列识别 + 键提示 + 3 样本值；**≤500 token/表** 序列化预算；
  privacy_mode 清样本值；连接串 conn_ref 间接引用全链路零明文
- frontend：数据源页（注册表单 / 状态轮询 / 画像与预览卡 / 隐私开关 / 重命名删除）
- 依赖：`uv add openpyxl`（XLSX）、`bun add zustand`（锁文件随代码提交）

明确不做（推后）：N2 的 ChartAsset/闸门/重放；N3 的 AI 工具与 /chat；PG/MySQL 反射（N4 后）；
folder 自动监听（N4，手动 rescan 起步）；向量检索（v1）。

## Impact

- Affected specs: `specs/data-catalog/spec.md`（新增）
- Affected code: backend `catalog/`、`api/datasets.py`、`settings.py`、`main.py`（挂载）；
  frontend `pages/Datasources`、`api/`、`stores/`；`compose.yaml`
- 验收锚点：v3 DoD #1（200 文件 <5min、增量 rescan 只动变更项、连接串零泄漏、隐私无原始行）；
  Spike B 内核测试不受影响（N1 不碰 exec/）
