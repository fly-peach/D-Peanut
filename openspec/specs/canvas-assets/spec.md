# canvas-assets Specification

## ADDED Requirements

### Requirement: 图表资产持久化

系统 SHALL 将图表资产 ChartAsset 持久为 workspace 目录（processor.py/params.json/
meta.json/versions/render.json/config.json，FS 为事实源）+ sqlite 索引镜像；索引与
meta 内容哈希漂移时资产标 broken；参数与保存操作受 expected_version 乐观锁保护，
版本快照支持回滚，重放历史入审计。

#### Scenario: 漂移检测

- **WHEN** 外部手改 processor.py 后读取资产
- **THEN** meta_hash 校验失败，status=broken，界面可得原因；恢复一致后解除

#### Scenario: 并发写冲突

- **WHEN** 两个客户端携同一 expected_version 先后更新参数
- **THEN** 后者收 409，重读最新版本后才可再提交

### Requirement: processor 协议（N2 末冻结）

processor SHALL 导出 PARAM_SPEC/DEFAULTS/process(ctx)，ctx={params, data(绑定别名→
懒加载 DataFrame), log}，返回 (RenderData, ChartConfig) 唯一出口；重放执行永远使用
clean kernel（%reset 预热池），禁止依赖任何会话变量。

#### Scenario: 重放确定性合同锁

- **WHEN** 同一种子资产以同参数重放 100 次
- **THEN** 每次 RenderData 序列化字节完全一致，且全程零 LLM 依赖（pydantic_ai 未被加载）

#### Scenario: 建卡即验

- **WHEN** POST /api/assets 提交含 processor 源码的资产
- **THEN** 三导出校验通过后同步执行一次 clean-kernel 重放，返回 GateReport；未过闸不进 validated

### Requirement: 输出 schema 闸门

重放输出 SHALL 依次通过 columns 集合、dtype 族、row_bounds、payload(≤2MB)、超时(≤30s)
检查；draft 首次过闸以实际输出盖章 OutputSchema；失败时上一版渲染留画布并携带
⚠ 状态与结构化 errors。

#### Scenario: 数据漂移被熔断

- **WHEN** 源数据列变更后手动重跑使输出缺列
- **THEN** GateReport.passed=false 且 errors 指明缺失列，画布继续显示上一版 render

### Requirement: 前端确定性渲染与参数分层

画布 SHALL 由前端 ECharts 消费 (RenderData 列式, ChartConfig) 渲染；appearance 参数
改动仅前端重渲染零网络；data 参数改动经 PUT+replay；渲染器拒绝 option_template 中的
函数字符串注入；画布冷加载与对话流无关（GET 幂等恢复）。

#### Scenario: 外观改动零请求

- **WHEN** 用户在表单修改图表高度/字体
- **THEN** 不发任何网络请求即时重渲染（测试断言 appearance-only 路径零 fetch）

#### Scenario: 刷新即恢复

- **WHEN** 浏览器刷新
- **THEN** GET /api/assets 冷加载重建全部卡片与布局，无需任何流重放
