<div align="center">

<img src="assets/icon.png" width="88" alt="">

# SOIA Open Dev Skills

**让 AI 改代码，不再「应该没问题」就交差**

12 个按需技能：先明确边界，直接实施，用实际结果验证

[English](README.en.md) · 中文 · [全生态门户](https://github.com/soia-team/soia-open-skills)

<p align="center">
  <img alt="plugin version" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fsoia-team%2Fsoia-open-dev-skills%2Fmain%2F.claude-plugin%2Fplugin.json&query=%24.version&label=plugin&color=F5A623&prefix=v">
  <img alt="skills" src="https://img.shields.io/badge/技能-12-brightgreen">
  <img alt="hosts" src="https://img.shields.io/badge/宿主-Claude%20%C2%B7%20Codex%20%C2%B7%20WorkBuddy-8A2BE2">
  <img alt="license" src="https://img.shields.io/github/license/soia-team/soia-open-dev-skills?color=blue">
</p>

</div>

---

## 它解决什么

按任务选一个清楚的入口，读必要上下文，做最小完整改动，再验证真实行为。普通任务不默认叠加 panel、对抗或多轮审查。

```mermaid
flowchart LR
    A["需求 · 缺陷<br/>审查发现"] --> B["定边界<br/>改哪些 · 不改哪些"]
    B --> C["最小改动"]
    C --> D["验证<br/>真跑一遍，不看'应该'"]
    D --> E["结果<br/>改动、证据与缺口"]
    D -.不通过.-> C
```

## 12 个技能

### 01 改动闭环　`需求或缺陷 → 有边界、有验证、有复核的改动`

| 技能 | 职责 | 开箱 |
|---|---|:-:|
| [`soia-dev-enforce-coding-protocol`](skills/soia-dev-enforce-coding-protocol/SKILL.md) | 短协议：范围、权限与风险相称的验证，不另起流程 | ✅ |
| [`soia-dev-implement-task`](skills/soia-dev-implement-task/SKILL.md) | 需求实现、缺陷修复与 findings 共用一个实施流程 | ✅ |
| [`soia-dev-review-code`](skills/soia-dev-review-code/SKILL.md) | 固定候选，一次只读审查；不自动修复或合并 | ✅ |

### 02 测试与发版　`需求或变更 → 测试计划、发布清单与灰度门`

| 技能 | 职责 | 开箱 |
|---|---|:-:|
| [`soia-dev-test-draft-doc`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-test-draft-doc.md) | 从需求、PRD 或变更说明生成测试计划、用例与验收对照 | ✅ |
| [`soia-dev-release-plan-checklist`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-release-plan-checklist.md) | 生成发布清单、预检门、灰度验证与发布后核对 | ✅ |

### 03 仓库运维　`仓库现状 → 一致的文档、合规的 PR、可用的基线`

| 技能 | 职责 | 开箱 |
|---|---|:-:|
| [`soia-dev-github-ops`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-github-ops.md) | GitHub `gh` CLI 运维、PR 合规审查与修复 | 🟡 |
| [`soia-dev-doc-sync`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-doc-sync.md) | 审计并修复 docs、README、CHANGELOG、VERSION 与真源之间的事实漂移 | ✅ |
| [`soia-dev-project-scaffold`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-project-scaffold.md) | 为新 Git 项目生成最小 AI 协作基线（AGENTS.md + docs 导航） | ✅ |

### 04 终端与 AI 协作　`长任务与多 AI → 可控的执行与派发`

| 技能 | 职责 | 开箱 |
|---|---|:-:|
| [`soia-dev-terminal-ops`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-terminal-ops.md) | 长任务、tmux 会话、日志抓取、停滞诊断；杀进程走 TERM→复查→KILL 确认门 | ✅ |
| [`soia-dev-agent-cli-dispatch`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-agent-cli-dispatch.md) | 外部 AI CLI 调度与模型路由，受控派活与用量回执 | 🟡 |
| [`soia-dev-agent-md-advisor`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-agent-md-advisor.md) | AI 项目指令与配置设计顾问：诊断、起草与改写建议 | ✅ |

### 05 代码变更理解　`AI 代码变更 → 架构调用、数据流与证据视图`

| 技能 | 职责 | 开箱 |
|---|---|:-:|
| [`soia-dev-show-task-html`](https://github.com/soia-team/soia-open-skills/blob/main/docs/skills/soia-dev-show-task-html.md) | 用最小视图解释当前话题；简单关系直接画，复杂关系再做聚焦 HTML | ✅ |

✅ 装完即用　🟡 需先完成登录或申请 API key，技能会在执行前告诉你缺什么

## 安装

三个宿主任选；默认单技能，明确选择整域插件时包含本仓 12 个技能。

发布与本机安装分开：默认按项目、明确宿主、单个技能定向安装；全局、整域或全宿主范围只有客户明确选择并先看 dry-run 后执行，发布不会自动同步到本机。

```bash
claude plugin marketplace add soia-team/soia-open-skills && claude plugin install soia-dev@soia
```

```bash
codex plugin marketplace add soia-team/soia-open-skills && codex plugin add soia-dev@soia
```

WorkBuddy 是桌面端没有 CLI，由技能代劳——对 AI 说「装到 WorkBuddy」，或直接跑：

```bash
python3 <soia-open-skills>/skills/soia-meta-skill-release/scripts/install_workbuddy_experts.py soia-dev
```

装完重启客户端，在【专家中心 → 我的专家】召唤 **Soia · 研发工程师**。

> 只想要单个技能可走 npx：`npx skills add soia-team/soia-open-dev-skills -g -a '*' -s <技能名> -y`——与插件二选一，并存会产生双份索引且各自漂移。

## 不负责什么

- **不做假修复**。让测试通过的最短路径若是改断言或加跳过，那不是修复——技能会要求说清真实原因。
- **不擅自扩大范围**。顺手重构、顺手改格式都要先确认。
- **不替你做产品决策**。范围取舍与优先级由人拍板。
- **不碰凭据**。仓里发现明文 key 只报告位置，不代为迁移或删除。
- **不含公司内部流程**。行业特定的需求、测试、发版规范在私有仓，不开源。

## 贡献

改动技能后提交前跑：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' && python3 scripts/audit_skills.py --strict && python3 scripts/generate_expert_manifest.py --check
```

完整流程见门户仓 [CONTRIBUTING.md](https://github.com/soia-team/soia-open-skills/blob/main/CONTRIBUTING.md)。

## License

MIT —— 见 [LICENSE](./LICENSE)。
