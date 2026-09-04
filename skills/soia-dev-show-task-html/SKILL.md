---
name: soia-dev-show-task-html
description: 将开发任务、代码变更或项目结构转成最小可用视图：简单关系直接画，复杂跨文件调用链与数据流生成离线 HTML。用于快速看懂 AI 生成代码并检查架构边界与规范符合性。触发：「show me」「展示这个任务」「给我画一下」
version: 0.2.0
created_at: 2026-09-04 15:43:10
updated_at: 2026-09-04 16:05:28
created_by: gpt-5.6-luna
updated_by: gpt-5.6-luna
---

# soia-dev-show-task-html

帮助用户用最小必要视图看懂 AI 代码变更。默认范围是当前展示请求（`task`），也支持 `change_set` 和 `project`；脚本只渲染调用方已核实的 JSON，不扫描仓库、不猜测事实。

> Help the user understand the current topic visually. Skip the preamble and keep prose brief. Pick the smallest view that makes the key point clear.

## 客户可读说明

### 这个技能可以做什么

- 简单关系：在对话中给最小表格、调用树或 Mermaid。
- 复杂跨文件改动：生成离线、响应式、可复制文字的 HTML，展示文件 owner/layer、调用链、数据流、模块边界、规范符合性、验证证据、风险、阻塞和下一步。

### 客户如何使用

先说明范围和重点，例如“展示这个变更集的核心调用链”。复杂 HTML 前，Agent 必须读取当前 scope 的项目规则、架构/设计契约、真实 diff 和相关代码；将事实标为 `observed`、有链路依据的推断标为 `inferred`，无证据标为 `unknown`，并保留准确 `file:line`。脚本不负责这些核实工作。

输入字段、scope/view 选项和引用格式见 [references/input-schema.md](references/input-schema.md)。审查视角和最小区块选择见 [references/code-review-views.md](references/code-review-views.md)。复杂输入再读取这些 reference，简单对话图不必读取。

### 依赖与安装

运行依赖只有 Python 3 标准库；不需要 API key、登录态、浏览器、第三方服务或网络。

发布与本机安装分开，发布不会自动同步宿主。默认按项目、明确宿主、单个技能定向安装；项目/全局、单技能/整域、单宿主/全宿主均可支持，但范围不明先询问，扩大到全局或 `*` 全量前先展示 dry-run 和目标清单。若当前环境没有可验证的安装命令，不要发明命令；本 checkout 只代表本地调试。

### 私密信息与中间数据

只读取完成当前 scope 所需的规则、契约、diff 和代码；输入先移除 key、token、cookie、密码、会话、账号标识和私有绝对路径。脚本不外联、不执行输入，所有 HTML 文本安全转义。默认输出到 OS 临时目录，不写 state、cache、配置或仓库目录；指定 `--output` 才形成客户交付物，默认不覆盖已有文件。

### 日志与完成回执

回执至少说明 scope/view、读取并渲染的非空区块、`observed/inferred/unknown` 分布、输出类别、真实验证命令和未覆盖证据；不回显敏感输入。发布或安装状态不得从本地调试推断。

## 核心流程

1. 判断是简单对话图还是复杂 HTML，并确认 `task`、`change_set` 或 `project` 范围；范围不明先询问。
2. 读取 scope 对应的项目规则、架构/设计契约、真实 diff 和相关代码，整理为带 `claim_type` 与 `file:line` 的 JSON；不把猜测写成观察。
3. 选择最小 `view`；`auto` 只渲染已提供且非空的必要区块。复杂输入运行 `scripts/show_task_html.py`，默认临时目录；仅客户明确指定时传 `--output`，覆盖需明确允许并传 `--force`。
4. 核对真实 HTML：内容、引用、转义、无外部资源、响应式和可复制性；回报输出位置、命令、缺口和下一步。

## 生成器与验证

```bash
python3 <skill-dir>/scripts/show_task_html.py --selftest
python3 <skill-dir>/scripts/show_task_html.py --input <scope.json> --scope <task|change_set|project> --view <auto|overview|call_chain|data_flow|boundary|conformance|full>
```

生成器是确定性的，只渲染输入，不读仓库、不联网、不写当前时间。通用跨文件审查 fixture 位于 `examples/task.json`；无效 scope/view、缺少标题、危险标记、非法输出路径和未授权覆盖都应显式失败。

交付前至少运行 selftest 和一次真实前向测试，并核对实际 HTML 内容，不只看退出码。

## 资源

- [输入契约与引用格式](references/input-schema.md)：复杂 HTML 前按需读取。
- [审查视图与区块选择](references/code-review-views.md)：需要决定视角、证据和最小视图时读取。
