# 代码审查视图

复杂 HTML 的目的，是让 reviewer 在 AI 一次生成数百上千行、跨十几个文件时快速重建逻辑；不是把 diff 再复制一遍。

## 生成前证据门

Agent 先读取当前 scope 的项目规则、`AGENTS.md`/贡献约束、架构规范、设计契约、真实 diff 和相关代码。建立文件 → owner/layer → 方法/接口/表/API → 调用链 → 数据流的证据链。每条 finding/evidence 标注 `observed`、`inferred` 或 `unknown`，并尽量给准确 `file:line`。

## 视图选择

| view | 选择 |
|---|---|
| `auto` | 只选有数据且能解释当前重点的最小必要区块；不铺空区块 |
| `progress` | KPI、任务状态、阻塞和下一步；用于 5 秒阶段汇报，不展开代码证据墙 |
| `overview` | 范围、目标、阶段/步骤和少量已核实事实 |
| `call_chain` | 入口到核心 service/domain/port/adapter 的节点和方向 |
| `data_flow` | 输入 → 转换 → domain/service/port → adapter/storage/external → view |
| `boundary` | 文件 owner/layer、模块职责、依赖方向和边界证据 |
| `conformance` | 项目架构、目录/文件、类/接口/方法、表/API 和技术规范的应符合/实际观察/结论 |
| `full` | 所有已提供且非空的上述区块，再加验证、风险、阻塞和下一步 |

简单关系直接在对话中使用最小表、调用树或 Mermaid；复杂跨文件改动才运行 HTML 生成器。不要为了“完整”把未经证实的关系画成确定箭头。
