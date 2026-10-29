# 知识库提交后"等待领取"间隙用 KB 作用域有界宽限维持轮询

状态：implemented
类型：bug-fix
Owner：frontend/src/modules/knowledge/model/knowledgeBase.js

## 问题

用户提交解析/入库后，文件停在 `uploaded` 等待 ARQ worker 领取；领取前 `processing_count` 为 0 且 `uploaded` 不属于 `isProcessingFile`，`ensureAutoRefreshForProcessing` 在下一次后台读取时立即判定"无处理活动"并停止自动刷新，列表停在"等待领取"直到用户手动刷新。上一版实现改为由全局后台任务 store 维持轮询，作者指出这会让与本 KB 无关的活跃任务延长当前页轮询，要求围绕知识库自身作业状态判断、避免全局轮询，并保留手动停止。

## 决策

### 实现方案

停止判定仍只看当前 KB 自己读到的文件与统计，不引入任何全局信号。提交类动作（解析/入库）成功时授予 `AUTO_REFRESH_SUBMISSION_GRACE_POLLS=12` 轮宽限；`ensureAutoRefreshForProcessing` 在"无 pending"分支先经纯函数 `consumeSubmissionGrace` 判定：仅当本 KB 列表中存在 `uploaded`（等待领取）文件且宽限未耗尽时继续轮询并递减，否则按僵尸状态停止。tick 的 stale 退避停止路径同样先消耗宽限。`toggleAutoRefresh` 保持原语义：用户手动关闭得到 `autoRefreshManualOverride`（auto 信号不得重启），手动开启视为新一轮观察并重置宽限，manual 来源不受 ensure 自动停止。元信息接口 `getKnowledgeBaseInfo` 的响应可能不含 files，改为 `ensureAutoRefreshForProcessing(..., hasFileSignal)` 携带信号完整度：files 缺失时只能开启、不能当作"无活动"停止或消耗宽限（旧实现同样存在此误判）。

## 替代方案

- 全局后台任务 store 维持轮询：被作者拒绝——无关任务延长当前 KB 轮询，且轮询信号不再由 KB 数据拥有。
- worker 领取时更新状态、前端不感知：拒绝——前端无法区分"排队等待领取"与"僵尸 uploaded"，只能无限轮询或提前停止。
- 延长 stale 上限：拒绝——全局放宽，僵尸状态收尾更慢，且不针对领取间隙。

## 后果

- 提交后的领取间隙内列表持续自动更新，最长额外 12 轮（间隔 10s、按退避封顶 30s），有界；无关 KB/全局任务不影响本 KB 轮询决策。
- 僵尸 `uploaded`（无提交动作）仍按原判定立即停止；手动停止行为不变。
- `consumeSubmissionGrace` 为导出纯函数，停止决策可脱离定时器单测。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 提交后 uploaded 等待领取期间保持轮询 | 间隙被立即停止、需手动刷新 | `submitFileJob` + `ensureAutoRefreshForProcessing` | `test/unit/knowledge_auto_refresh_gap.test.js`（提交后 8 轮读取仍轮询） | 移除提交时宽限授予后该用例失败（实测） | Passed |
| 宽限有界，僵尸等待最终自动停止 | 无限轮询 | `consumeSubmissionGrace` | 同文件"宽限有界"用例（≤16 次读取内停止） | 宽限耗尽仍继续时断言失败 | Passed |
| 宽限只由提交授予、manual 语义保留 | 无关 uploaded 延长轮询 / 手动开关被破坏 | `toggleAutoRefresh` + ensure 分支 | 同文件"手动开启"与"processing 收尾"用例 | 不适用 | Passed |
| 元信息无 files 不误判为无活动 | 提前停止且清零宽限 | `getKnowledgeBaseInfo` | `hasFileSignal` 参数 + 上述提交用例（info mock 无 files） | 恢复无条件 stop 分支时提交用例失败 | Passed |
| 回归 | 既有知识库行为漂移 | `test/unit` | `pnpm run test:unit` → 884 passed；`eslint` 干净；`pnpm run build` 成功 | 不适用 | Passed |

未验证范围：真实浏览器中 worker 领取后的端到端刷新时序 `Not run`（单元层以列表 mock 覆盖状态序列；后端队列语义由既有集成测试拥有）。
