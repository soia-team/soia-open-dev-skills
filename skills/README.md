# SOIA Open Skills Catalog

> Generated from `skills/*/SKILL.md` and optional `agents/openai.yaml`.
> Do not edit by hand. Run `python3 scripts/generate_skill_catalog.py`.
> Discoverable by `npx skills add soia-team/soia-open-dev-skills -l`: 12 skills.

## Source Fields

- `SKILL.md` is the canonical cross-agent instruction file. Capabilities, dependencies, setup, workflow steps, logs, and completion summaries must live there.
- `agents/openai.yaml` is optional UI/catalog metadata for OpenAI/Codex-style surfaces and SOIA registry display: `display_name`, `short_description`, and `default_prompt`.
- Claude Code and generic skills.sh-compatible agents must be assumed to consume `SKILL.md`; do not put required workflow steps only in `agents/openai.yaml`.
- Legacy `metadata.json` files are not used to generate this catalog.

## Development

| Skill | Description | Default Prompt |
|---|---|---|
| [`soia-dev-agent-cli-dispatch`](./soia-dev-agent-cli-dispatch/) | Host-agnostic external AI model/CLI dispatch for coding, review, analysis, research, documentation, and content tasks, with explicit or automatic model/reasoning selection, Token/cost receipts, model-integrity checks, qu... | Use soia-dev-agent-cli-dispatch to send this task to an external AI agent/CLI (codex/claude/agy/gemini/kimi/opencode/qwen/pi/deepcode), keeping Antigravity consumer auth separate from Gemini enterprise/API-key/Vertex lanes, honoring explicit model/reasoning choices or verified auto-routing, then report requested vs actual model, detailed Token usage, API-equivalent cost, validation evidence, and recovery state. |
| [`soia-dev-agent-md-advisor`](./soia-dev-agent-md-advisor/) | AGENTS.md / CLAUDE.md / GEMINI.md 与 .claude 配置设计顾问：审查诊断、新项目起草、最佳实践问答三种模式，六维度诊断长度预算/可执行性/分区路由/重复矛盾/入口一致性/时效。 | Use soia-dev-agent-md-advisor: 审查我的 AGENTS.md/CLAUDE.md 配置，按六维度给我一份问题清单和改写建议，先别动手改，等我确认。 |
| [`soia-dev-doc-sync`](./soia-dev-doc-sync/) | 审计并修复任意代码仓的 docs、README、CHANGELOG、VERSION 与明确真源之间的事实漂移；先建立真源优先级与证据，再按依赖顺序同步派生文档 |  |
| [`soia-dev-enforce-coding-protocol`](./soia-dev-enforce-coding-protocol/) | 用短协议约束工程范围与验证，按实际风险加检查，不另起流程。 | 请用 $soia-dev-enforce-coding-protocol 约束本次改动的范围与验证。 |
| [`soia-dev-github-ops`](./soia-dev-github-ops/) | Use gh CLI for GitHub issue, PR, checks, review, workflow run, release, and collaborator-permission operations, plus a pre-merge rule-review procedure and an author-side address-the-review-and-fix procedure, with structu... | Use soia-dev-github-ops: review this open PR against the repo's own rules and tell me whether it's safe to merge. |
| [`soia-dev-implement-task`](./soia-dev-implement-task/) | 将需求、缺陷与 findings 收敛到一个有边界、可验证的实施流程。 | 请用 $soia-dev-implement-task 完成本次实现或修复，并验证实际结果。 |
| [`soia-dev-project-scaffold`](./soia-dev-project-scaffold/) | 为任意新 Git 项目创建最小 AI 协作基线。 | Use $soia-dev-project-scaffold to create a minimal AGENTS.md and docs baseline for a new Git project. |
| [`soia-dev-release-plan-checklist`](./soia-dev-release-plan-checklist/) | 生成互联网软件发版的预检、灰度与发布后验证清单。 | 为服务 A 的生产发布生成版本、制品、预检门、灰度、回滚和发布后验证清单。 |
| [`soia-dev-review-code`](./soia-dev-review-code/) | 对固定代码候选或技能包做一次只读审查，报告有证据的实际问题。 | 请用 $soia-dev-review-code 只读审查这次改动，不自动修复或合并。 |
| [`soia-dev-show-task-html`](./soia-dev-show-task-html/) | 用最小视图解释当前话题，简单关系直接画，复杂关系再做聚焦 HTML。 | 请用 $soia-dev-show-task-html 展示当前话题，直接选最小有用视图。 |
| [`soia-dev-terminal-ops`](./soia-dev-terminal-ops/) | Monitor long-running POSIX jobs and recover stalled processes safely | Use $soia-dev-terminal-ops to monitor this long-running command, diagnose progress with multiple signals, and apply the TERM-to-KILL confirmation gates if recovery is needed. |
| [`soia-dev-test-draft-doc`](./soia-dev-test-draft-doc/) | Turn requirements or a PRD into a test plan, cases, regression checklist, and acceptance matrix. |  |

## Registry Export

Generate v7 SOIA registry manifests from the same sources when needed:

```bash
python3 scripts/generate_skill_catalog.py --registry-out <soia-repo>/runtime/registry/skills
```
