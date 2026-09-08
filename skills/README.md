# SOIA Open Skills Catalog

> Generated from `skills/*/SKILL.md` and optional `agents/openai.yaml`.
> Do not edit by hand. Run `python3 scripts/generate_skill_catalog.py`.
> Discoverable by `npx skills add soia-team/soia-open-dev-skills -l`: 20 skills.

## Source Fields

- `SKILL.md` is the canonical cross-agent instruction file. Capabilities, dependencies, setup, workflow steps, logs, and completion summaries must live there.
- `agents/openai.yaml` is optional UI/catalog metadata for OpenAI/Codex-style surfaces and SOIA registry display: `display_name`, `short_description`, and `default_prompt`.
- Claude Code and generic skills.sh-compatible agents must be assumed to consume `SKILL.md`; do not put required workflow steps only in `agents/openai.yaml`.
- Legacy `metadata.json` files are not used to generate this catalog.

## Development

| Skill | Description | Default Prompt |
|---|---|---|
| [`soia-dev-agent-cli-dispatch`](./soia-dev-agent-cli-dispatch/) | Host-agnostic external AI model/CLI dispatch for coding, review, analysis, research, documentation, and content tasks, with explicit or automatic model/reasoning selection, Token/cost receipts, model-integrity checks, qu... | Use soia-dev-agent-cli-dispatch to send this task to an external AI agent/CLI (codex/claude/agy/gemini/kimi/opencode/qwen/pi/deepcode), keeping Antigravity consumer auth separate from Gemini enterprise/API-key/Vertex lanes, honoring explicit model/reasoning choices or verified auto-routing, then report requested vs actual model, detailed Token usage, API-equivalent cost, validation evidence, and recovery state. |
| [`soia-dev-agent-md-advisor`](./soia-dev-agent-md-advisor/) | 诊断与精简 AI 项目指令，保留有效约束并解决重复和冲突 | 使用 $soia-dev-agent-md-advisor 处理当前请求，保留现有有效约束并报告实际验证与未覆盖范围。 |
| [`soia-dev-archify-diagrams`](./soia-dev-archify-diagrams/) | 生成可维护的 Archify JSON 图表，核对渲染与预览产物 | 使用 $soia-dev-archify-diagrams 处理当前请求，保留现有有效约束并报告实际验证与未覆盖范围。 |
| [`soia-dev-audit-ui`](./soia-dev-audit-ui/) | 分别验证界面技术行为与 UX 视觉质量，只报告可定位的问题 | 使用 $soia-dev-audit-ui 处理当前请求，保留已批准约束并说明实际证据与未验证范围。 |
| [`soia-dev-design-ui`](./soia-dev-design-ui/) | 围绕用户任务设计信息结构、交互状态与视觉，保持已批准样式 | 使用 $soia-dev-design-ui 处理当前请求，保留已批准约束并说明实际证据与未验证范围。 |
| [`soia-dev-doc-sync`](./soia-dev-doc-sync/) | 核对代码、发布事实和有效裁决与文档之间的漂移，按授权同步派生内容 |  |
| [`soia-dev-draft-feature-spec`](./soia-dev-draft-feature-spec/) | 把产品需求写成可验收规格，明确范围、异常路径与未决事项 | 使用 $soia-dev-draft-feature-spec 处理当前请求，保留已批准约束并说明实际证据与未验证范围。 |
| [`soia-dev-drawio-visio-diagrams`](./soia-dev-drawio-visio-diagrams/) | 读取 VSDX，转换、理解并升级为可编辑 draw.io 图表。 | Use $soia-dev-drawio-visio-diagrams to inspect this VSDX safely, convert it into an editable draw.io source, apply requested upgrades without overwriting the original, and validate exported artifacts. |
| [`soia-dev-enforce-coding-protocol`](./soia-dev-enforce-coding-protocol/) | 用短协议约束工程范围与验证，按实际风险加检查，不另起流程。 | 请用 $soia-dev-enforce-coding-protocol 约束本次改动的范围与验证。 |
| [`soia-dev-github-ops`](./soia-dev-github-ops/) | Use gh CLI for GitHub issue, PR, checks, review, workflow run, release, and collaborator-permission operations, plus a pre-merge rule-review procedure and an author-side address-the-review-and-fix procedure, with structu... | Use soia-dev-github-ops: review this open PR against the repo's own rules and tell me whether it's safe to merge. |
| [`soia-dev-govern-architecture`](./soia-dev-govern-architecture/) | 按设计、评审或漂移模式核对职责与契约，给出可验证的架构判断 | 使用 $soia-dev-govern-architecture 处理当前请求，保留已批准约束并说明实际证据与未验证范围。 |
| [`soia-dev-implement-task`](./soia-dev-implement-task/) | 将需求、缺陷与 findings 收敛到一个有边界、可验证的实施流程。 | 请用 $soia-dev-implement-task 完成本次实现或修复，并验证实际结果。 |
| [`soia-dev-officecli-ops`](./soia-dev-officecli-ops/) | 安全读取、复制后修改并验证 Word、Excel 与 PowerPoint 文件 | 使用 $soia-dev-officecli-ops 处理当前请求，保留现有有效约束并报告实际验证与未覆盖范围。 |
| [`soia-dev-open-design-ops`](./soia-dev-open-design-ops/) | 检查 Open Design 并交付可验证的 HTML 原型、deck、动画与导出 | 使用 $soia-dev-open-design-ops 处理当前请求，保留现有有效约束并报告实际验证与未覆盖范围。 |
| [`soia-dev-project-scaffold`](./soia-dev-project-scaffold/) | 沿用已有项目约定，只补缺少的 AI 协作入口和文档导航 | 使用 $soia-dev-project-scaffold 处理当前请求，保留现有有效约束并报告实际验证与未覆盖范围。 |
| [`soia-dev-release-plan-checklist`](./soia-dev-release-plan-checklist/) | 设计软件发布预检、灰度、停止与回滚清单，不执行部署 | 使用 $soia-dev-release-plan-checklist 处理当前请求，保留现有有效约束并报告实际验证与未覆盖范围。 |
| [`soia-dev-review-code`](./soia-dev-review-code/) | 对固定代码候选或技能包做一次只读审查，报告有证据的实际问题。 | 请用 $soia-dev-review-code 只读审查这次改动，不自动修复或合并。 |
| [`soia-dev-show-task-html`](./soia-dev-show-task-html/) | 用最小视图解释当前话题，简单关系直接画，复杂关系再做聚焦 HTML。 | 请用 $soia-dev-show-task-html 展示当前话题，直接选最小有用视图。 |
| [`soia-dev-terminal-ops`](./soia-dev-terminal-ops/) | 观察长任务与日志，多信号判断停滞并安全停止或恢复明确进程 | 使用 $soia-dev-terminal-ops 处理当前请求，保留现有有效约束并报告实际验证与未覆盖范围。 |
| [`soia-dev-test-draft-doc`](./soia-dev-test-draft-doc/) | 从需求与变更设计可执行用例和验收对照，不冒充实际测试执行 | 使用 $soia-dev-test-draft-doc 处理当前请求，保留现有有效约束并报告实际验证与未覆盖范围。 |

## Registry Export

Generate v7 SOIA registry manifests from the same sources when needed:

```bash
python3 scripts/generate_skill_catalog.py --registry-out <soia-repo>/runtime/registry/skills
```
