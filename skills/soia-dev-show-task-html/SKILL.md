---
name: soia-dev-show-task-html
description: 用最小视图帮用户看懂当前话题；简单关系直接画，复杂关系才做聚焦 HTML。触发：show me、展示这个任务、给我画一下、输出任务视图、把进度画出来
version: 0.5.0
created_at: 2026-09-04 15:43:10
updated_at: 2026-09-12 12:00:00
created_by: gpt-5.6-luna
updated_by: deepseek-flash
---

# soia-dev-show-task-html

## 客户可读说明

**能做什么：** 把当前问题、进度或代码关系讲明白。直接给最小有用视图，少写前言；不默认做看板、报告或证据墙。

**如何使用：** 说“展示这个任务”或指出想看懂的关系即可。默认用当前话题，只有范围会实质改变答案时才问。

## 选最小视图

- 一个事实或一步动作：直接回答，不强行画图。
- 几项对应关系用短表格；逻辑分支用伪代码；调用、组件或目录用各自的树；跨组件交互和时序用 Mermaid。保留会改变理解的状态归属与模块边界。
- 解释改动用关键 diff；大部分是新内容、删略会隐藏归属/顺序，或用户需要可复制目标时，给完整的相关片段。
- 内容确实需要空间布局、交互或较多视觉信息：才生成一页聚焦 HTML。围绕用户要理解的重点组织，不加默认 KPI、评分、分类统计或固定回执。

只取支持当前结论的材料。进度不强制扫描代码；调用关系须核对相关实现，推断或未知用普通话标清，不强制 JSON 或证据标签。

需要区分结构与运行、选择对比方式时，按需读[表达参考](references/view-patterns.md)；不用为简单回答加载。图示紧邻它说明的结论，不把所有视图都做一遍。

## HTML（按需）

沿用已有产品风格，文字可复制，兼顾桌面与窄屏；动态文本安全转义，不执行不可信输入，默认离线且无外部资源。输出到系统临时目录或客户指定位置，不覆盖未知文件。验收时实际打开/渲染核对内容与布局，再给可点击结果；未渲染就明确说明。

已有结构化输入、批量生成或客户明确要固定看板时，才读[可选生成器](references/generator.md)；手写 HTML 不受它的 schema 限制。

## 使用边界

### 依赖与安装

对话视图无依赖；可选生成器只需 Python 3 标准库。安装与发布分别确认，默认项目、明确宿主、单技能。
项目安装：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-show-task-html`；执行前核实当前 CLI 参数。
整域需明确选择：先接入市场 `soia-team/soia-open-skills`，Claude Code 用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装；上述命令不构成安装授权。

**私密信息与中间数据：** 不需要 key 或登录态；最小范围取材并脱敏，不外传源码，不建立状态或缓存。

**日志与完成回执：** 视图本身就是主要结果；HTML 附位置和必要验证缺口即可，不另交固定格式报告。
