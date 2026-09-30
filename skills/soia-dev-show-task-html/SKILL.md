---
name: soia-dev-show-task-html
description: 用户要求时把任务进度、调用关系或数据流画成最小视图，复杂布局才出 HTML；普通问答与常规回执不用。触发：展示这个任务、画调用关系、数据流怎么走
version: 0.5.2
created_at: 2026-09-04 15:43:10
updated_at: 2026-09-30 13:14:57
created_by: gpt-5.6-luna
updated_by: claude opus 5.5
---

# soia-dev-show-task-html

## 客户可读说明

**能做什么：** 把当前问题、进度或代码关系讲明白，直接给最小有用视图，少写前言；不默认做看板、报告或证据墙。

**如何使用：** 说“展示这个任务”或指出想看懂的关系。默认用当前话题，范围会实质改变答案时才问。

## 选最小视图

- 一个事实或一步动作：直接回答，不强行画图。
- 几项对应关系用短表格；逻辑分支用伪代码；调用、组件或目录用树；跨组件交互和时序用 Mermaid。保留会改变理解的状态归属与模块边界。
- 解释改动用关键 diff；大部分是新内容、删略会藏住归属/顺序，或用户要可复制目标时，给完整相关片段。
- 确实需要空间布局、交互或较多视觉信息时才出一页聚焦 HTML，围绕用户要理解的重点组织，不加默认 KPI、评分、分类统计或固定回执。

只取支持当前结论的材料。进度不强制扫代码；调用关系须核对相关实现，推断或未知用普通话标清。需要区分结构与运行、选对比方式时读[表达参考](references/view-patterns.md)。图紧邻它说明的结论，不把所有视图都做一遍。

## HTML（按需）

沿用已有产品风格，文字可复制，兼顾桌面与窄屏；动态文本转义，不执行不可信输入，默认离线、无外部资源。输出到系统临时目录或客户指定位置，不覆盖未知文件。验收时实际打开/渲染核对内容与布局，再给可点击结果；没渲染就直说。

已有结构化输入、批量生成或客户要固定看板时才读[可选生成器](references/generator.md)；手写 HTML 不受其 schema 限制。

## 使用边界

### 依赖与安装

对话视图无依赖；可选生成器只需 Python 3 标准库。单技能 `npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-show-task-html`；整域 `claude plugin install soia-dev@soia` 或 `codex plugin add soia-dev@soia`（先接入市场 soia-team/soia-open-skills）；WorkBuddy 见[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)；命令不构成安装授权。

**私密信息与中间数据：** 不需要 key 或登录态；最小范围取材并脱敏，不外传源码，不建状态或缓存。

**日志与完成回执：** 视图本身就是结果；HTML 附位置和未验证缺口，不另交固定格式报告。
