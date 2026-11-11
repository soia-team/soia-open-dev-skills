# SOIA Open Skills Catalog

> Generated from `skills/*/SKILL.md` and optional `agents/openai.yaml`.
> Do not edit by hand. Run `python3 scripts/generate_skill_catalog.py`.
> Discoverable by `npx skills add soia-team/soia-open-dev-skills -l`: 9 skills.

## Source Fields

- `SKILL.md` is the canonical cross-agent instruction file. Capabilities, dependencies, setup, workflow steps, logs, and completion summaries must live there.
- `agents/openai.yaml` is optional UI/catalog metadata for OpenAI/Codex-style surfaces and SOIA registry display: `display_name`, `short_description`, and `default_prompt`.
- Claude Code and generic skills.sh-compatible agents must be assumed to consume `SKILL.md`; do not put required workflow steps only in `agents/openai.yaml`.
- Legacy `metadata.json` files are not used to generate this catalog.

## Development

| Skill | Description | Default Prompt |
|---|---|---|
| [`soia-dev-agent-cli-dispatch`](./soia-dev-agent-cli-dispatch/) | Host-agnostic external AI model/CLI dispatch for coding, review, analysis, research, documentation, and content tasks, with explicit or automatic model/reasoning selection, Token/cost receipts, model-integrity checks, qu... | Use soia-dev-agent-cli-dispatch to send this task to an external AI agent/CLI (any executor listed in references/supported-agents.yml), keeping Antigravity consumer auth separate from Gemini enterprise/API-key/Vertex lanes, honoring explicit model/reasoning choices or verified auto-routing, then report requested vs actual model, detailed Token usage, API-equivalent cost, validation evidence, and recovery state. |
| [`soia-dev-audit-ui`](./soia-dev-audit-ui/) | 分别验证界面技术行为与 UX 视觉质量，只报告可定位的问题 | 使用 $soia-dev-audit-ui 处理当前请求，保留已批准约束并说明实际证据与未验证范围。 |
| [`soia-dev-design-ui`](./soia-dev-design-ui/) | 围绕用户任务设计信息结构、交互状态与视觉，保持已批准样式 | 使用 $soia-dev-design-ui 处理当前请求，保留已批准约束并说明实际证据与未验证范围。 |
| [`soia-dev-enforce-coding-protocol`](./soia-dev-enforce-coding-protocol/) | 用短协议约束工程范围与验证，按实际风险加检查，不另起流程。 | 请用 $soia-dev-enforce-coding-protocol 约束本次改动的范围与验证。 |
| [`soia-dev-github-ops`](./soia-dev-github-ops/) | Use gh CLI for GitHub issue, PR, checks, review, workflow run, release, and collaborator-permission operations, plus a pre-merge rule-review procedure and an author-side address-the-review-and-fix procedure, with structu... | Use soia-dev-github-ops: review this open PR against the repo's own rules and tell me whether it's safe to merge. |
| [`soia-dev-govern-architecture`](./soia-dev-govern-architecture/) | 按设计、评审或漂移模式核对职责与契约，给出可验证的架构判断 | 使用 $soia-dev-govern-architecture 处理当前请求，保留已批准约束并说明实际证据与未验证范围。 |
| [`soia-dev-implement-task`](./soia-dev-implement-task/) | 将需求、缺陷与 findings 收敛到一个有边界、可验证的实施流程。 | 请用 $soia-dev-implement-task 完成本次实现或修复，并验证实际结果。 |
| [`soia-dev-review-code`](./soia-dev-review-code/) | 对固定代码候选或技能包做一次只读审查，报告有证据的实际问题。 | 请用 $soia-dev-review-code 只读审查这次改动，不自动修复或合并。 |
| [`soia-dev-show-task-html`](./soia-dev-show-task-html/) | 用最小视图解释当前话题，简单关系直接画，复杂关系再做聚焦 HTML。 | 请用 $soia-dev-show-task-html 展示当前话题，直接选最小有用视图。 |

## Registry Export

Generate v7 SOIA registry manifests from the same sources when needed:

```bash
python3 scripts/generate_skill_catalog.py --registry-out <soia-repo>/runtime/registry/skills
```
