# Tasks

## 0. 环境与骨架

- [x] 0.1 起分支 n1-data-catalog；后端 `uv add openpyxl`、前端 `bun add zustand`，锁文件入库
- [x] 0.2 建包骨架：`catalog/{models,registry,scan,reader,profiler,sampler}.py`、
      `catalog/sources/{file,folder,sql}.py`；空实现不破坏现有 8 个测试全绿

## 1. settings 与 workspace 引导

- [x] 1.1 `settings.py`：DATA_ROOT / WORKSPACE_ROOT / 画像预算常量 / preview 上限 n /
      全局 privacy_mode 默认；单测断言 env 优先级
- [x] 1.2 `catalog/registry.py`：workspace/index.db 建表（datasets、profiles、
      settings(key,value_json)），DatasetRef 三 kind 的 pydantic 模型 + 状态枚举（表驱动单测）
- [x] 1.3 secrets store：读写 secrets.json（0600）、conn_ref 分配、统一脱敏 filter；
      单测——明文绝不进 sqlite / 不进日志
- [x] 1.4 SettingsService + `api/settings.py` 骨架：GET 合并视图（secrets 掩码后4位）/
      PUT 分写（敏感→secrets.json，非敏感→settings 表，缺省字段不覆盖）；
      不含 LLM 表单与 llm/test（N3）；TestClient 单测断言"GET 永不含明文 key"

## 2. 数据导入层核心

- [x] 2.1 `sources/file.py`：格式嗅探（csv/parquet/xlsx）；xlsx 用 openpyxl 读 sheet 名列表，
      多 sheet 物化为多个 FileDataset（sheet 后缀命名）
- [x] 2.2 `scan.py`：folder glob 展开 + 树指纹 + rescan diff（新增建 child / mtime 变 bump
      revision + outdated / 删除标 failed）；symlink 忽略
      - 单测：临时目录 fixture，200 小 CSV <60s，增量仅动变更项
- [x] 2.3 `sources/sql.py`：sqlite ATTACH 反射表/列，schema_hash 指纹；conn_ref 间接引用
      - 单测：样例库反射正确；响应体与 caplog 无明文连接串断言
- [x] 2.4 `profiler.py` + prompt 序列化纯函数 `render_profile_for_prompt(profile, budget=500)`
      （逆序裁剪 样本值→TOP-N→范围）
      - 单测：fixture 含时间列/高基数/缺失列，各画像字段断言；预算超限裁剪正确
- [x] 2.5 `sampler.py`：preview 逻辑，privacy 开关生效时返回统计摘要替代原始行
- [x] 2.6 `reader.py`：read_dataset(ref, columns, limit)——csv/parquet 走 DuckDB，xlsx 走 pandas；
      N2/N3 复用同一函数（docstring 注明契约冻结）

## 3. REST + 后台流水线

- [x] 3.1 `catalog/pipeline.py`：scan_and_profile(dataset_id) 纯入口（BackgroundTasks 与测试共用），
      逐 child try 失败不拖垮批次（failed + last_error）
- [x] 3.2 `api/datasets.py`：proposal §接口 的 8 个端点；路径 jail 400；privacy PATCH；
      folder rescan；DELETE hook（N1 直接删，留引用检查 TODO）
- [x] 3.3 `main.py` 挂路由 + workspace 启动引导；TestClient 集成测：
      三类注册→轮询 ready→profile/preview→PATCH 隐私→DELETE
- [x] 3.4 compose.yaml 加 DATA_ROOT/WORKSPACE_ROOT 两卷；dev 用 .env.example 文档化

## 4. 前端数据源页

- [x] 4.1 `api/client.ts`：datasets 端点封装；`stores/catalogStore.ts`：zustand +
      指数退避轮询（上限 5s），status pending/scanning/ready/failed 驱动 UI
- [x] 4.2 `pages/Datasources`：三类注册表单（kind 切换；folder 填路径+glob；xlsx 出 sheet 多选）、
      列表（状态徽章）、详情抽屉（画像卡 + preview 表 + 隐私开关 + 重命名/删除）
- [x] 4.3 路由接进 App.tsx（静态 demo 页保留为工作台占位）；tsc -b + vite build 零错误（浏览器人工点击待用户验收）

## 5. 验收与冻结

- [x] 5.1 DoD #1 四场景全绿：① 200 CSV folder 注册 <5min 全部可寻址（60s 预算）；
      ② mtime 改动 rescan 只重标该 child；③ sqlite 源响应+日志零连接串明文；
      ④ privacy 下 preview 仅统计摘要
- [x] 5.2 回归：ruff check 零告警；uv run pytest 全绿（含既有 spike A/B 8 测试）；
      bun run build 零错误
- [x] 5.3 `specs/data-catalog/spec.md` 场景→测试映射核对（每条 Requirement 有对应测试）
- [ ] 5.4 冻结记录：Dataset / DatasetRef / TableProfile / read_dataset 四契约字段写入
      design.md「已冻结」段；归档本 change（delta specs 合并进 openspec/specs/）

## 6. 场景→测试映射（5.3）

| Requirement / Scenario | 测试 |
|---|---|
| 三源注册·folder 批量 | test_perf_scan::test_folder_200_files_under_60s；test_api_datasets::test_folder_expand_with_failure_isolation |
| 三源注册·jail 越界 | test_api_datasets::test_jail_rejected；test_settings::test_jail_rejects_escape |
| 增量扫描·只动变更项 | test_api_datasets::test_rescan_touches_only_changed；test_scan::test_diff_entries / test_fingerprint_stable |
| 画像正确性+缓存 | test_profiler::TestColumnStats；test_catalog_registry::test_profile_cache_keyed_by_revision |
| 预算 ≤500 token 裁剪 | test_profiler::TestPromptRender::test_budget_trim_order |
| 隐私无原始行 | test_api_datasets::test_privacy_toggle_returns_summary_only；test_profiler::test_privacy_strips_raw_values |
| 连接串零泄漏 | test_api_datasets::test_sqlite_registration_no_secret_leak；test_settings::test_secret_plaintext_never_touches_index_db；test_secrets_store |
| 统一读取·下推/限行 | test_reader::TestPushdownContract + test_csv_full_and_limited |
| 前端可见（自动化部分） | tsc -b + vite build 零错误；浏览器点击 = 人工验收 |
