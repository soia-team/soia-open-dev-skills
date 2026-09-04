# 输入契约

脚本接收一个 JSON object。`title` 必填；`scope` 默认 `task`，可选 `task`、`change_set`、`project`；`view` 默认 `auto`，可选 `auto`、`progress`、`overview`、`call_chain`、`data_flow`、`boundary`、`conformance`、`full`。`task` 表示当前展示请求，不强制只有一个文件或一个逻辑单元。

## 字段

```json
{
  "scope": "change_set",
  "view": "full",
  "title": "Retry status boundary review",
  "objective": "让 reviewer 能重建跨文件逻辑",
  "stage": "审查",
  "metrics": [{"label": "进行中", "value": 2, "tone": "active"}],
  "steps": [{"name": "追踪请求", "status": "completed", "detail": "从入口跟到 port"}],
  "facts": [{"title": "观察", "detail": "直接看到的事实", "claim_type": "observed", "references": [{"file": "src/api/routes.ts", "line": 42}]}],
  "files": [{"path": "src/api/routes.ts", "owner": "HTTP adapter", "layer": "adapter", "role": "职责或变更", "references": [{"file": "src/api/routes.ts", "line": 42}]}],
  "call_chain": {"nodes": ["routes.handle", "Service.decide"], "edges": [{"from": "routes.handle", "to": "Service.decide", "label": "调用", "claim_type": "observed", "references": [{"file": "src/api/routes.ts", "line": 42}]}]},
  "data_flow": {"steps": [{"from": "Input", "to": "Domain", "transform": "转换", "claim_type": "inferred", "references": [{"file": "src/service.ts", "line": 18}]}]},
  "boundaries": [{"name": "Service boundary", "responsibility": "拥有策略", "depends_on": "Port", "direction": "inward", "claim_type": "observed", "references": [{"file": "src/service.ts", "line": 18}]}],
  "conformance": [{"rule": "依赖指向 port", "expected": "service 不直接依赖 storage", "observed": "符合", "status": "pass", "claim_type": "observed", "references": [{"file": "src/service.ts", "line": 3}]}],
  "verification": [{"check": "测试", "evidence": "命令和结果", "status": "passed", "claim_type": "observed", "references": [{"file": "tests/service.test.ts", "line": 55}]}],
  "risks": [{"title": "风险", "detail": "影响和缓解措施", "claim_type": "inferred", "references": []}],
  "blockers": [{"title": "阻塞", "detail": "待补证据", "claim_type": "unknown", "references": []}],
  "next_steps": [{"name": "下一步", "detail": "补齐核实项", "claim_type": "unknown", "references": []}]
}
```

`files` 也接受 `changed_files`、`file_matrix`、`changes` 或 `code_changes`。架构调用关系也接受 `architecture`、`architecture_calls` 或 `call_graph`；验证也接受 `evidence` 或 `checks`。

`progress` 视图读取 `metrics`、`steps`、`blockers` 和 `next_steps`；任务项可用 `owner` 与 `next`/`next_action` 提供紧凑负责人和下一门。它不会渲染代码矩阵、调用链或完整证据墙，除非改选相应 view。

## claim 与引用

每条 fact、finding、evidence、边、边界和符合性记录可带 `claim_type`：

- `observed`：直接从规则、契约、diff 或代码中看到。
- `inferred`：由已引用事实推导，但不是直接文本证据。
- `unknown`：尚未取得证据；不要用猜测填充。

`references` 可为 `{file, line}`、文件字符串或列表；也可在条目顶层使用 `file`/`path` 加 `line`。生成器原样显示 `file:line`，不扫描文件、不计算行号、不验证引用是否真实；这些责任属于生成前的 Agent。
