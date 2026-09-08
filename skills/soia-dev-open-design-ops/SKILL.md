---
name: soia-dev-open-design-ops
description: 操作 Open Design 环境、项目与导出，并交付 HTML 原型、deck 和动画。触发：检查 Open Design、制作 HTML deck、继续设计会话
version: 1.7.0
created_at: 2026-07-20 14:16:00
updated_at: 2026-09-08 17:24:05
created_by: gpt-5.6-sol
updated_by: gpt-5
---

# soia-dev-open-design-ops

## 客户可读说明

**能做什么：** 操作 Open Design 环境、设计系统、目录、项目、会话和渲染/导出；也承接 HTML 原型、幻灯片、动画的工具流程。UI 方法和视觉审查分别由 design-ui / audit-ui 承担，不强制安装或串行加载。

**如何使用：** 给目标与已有项目/素材；生成时说明内容、品牌、画幅和输出，导出时给格式与路径。PPTX 要区分截图保真与可编辑，HTML deck/动画不能被 PPTX 或静态图代替。

## 先识别运行路线

从技能目录运行 `python3 scripts/detect_route.py --json`。它区分 CLI checkout、desktop、desktop-mcp、none；只采用实际可用路线，不因缺 CLI 的 Node/pnpm 就把可用桌面版判为故障。

- CLI 路线才用 check_env.py 与 daemon_ctl.py；desktop 路线用 desktop_ctl.py detect/doctor，MCP 按当前可调用工具和版本证据判断。
- 桌面版端口、launcher payload 和 workspace 上下文每次现场探测；不缓存端口、不把 macOS 自带 /usr/bin/od 当作 Open Design CLI。
- 空的全局项目列表不证明没有项目；检查 workspace 范围。未知版本/能力不冒充支持，不造 API payload。
- 无可用路线时停住相关操作，提供补齐选择；不自动 clone、安装、重启或修改 provider 配置。

环境/daemon、桌面与 CLI 差异、目录、设计系统、导出和 resume 的命令见[操作参考](references/operations.md)。其中带版本的条目是历史验证边界，执行前以当前 help、工具 schema 和实际响应复核，不能直接视作最新事实。

## 生成、修改与导出

原型、HTML deck、动画或风格探索时读[产物流程](references/artifact-workflows.md)。沿用用户指定 Open Design 路线，不因耗时改成自己写文件并冒充其生成结果；宿主或用户已选 provider 时不静默切换。

复用正确项目与会话；新增页面优先放同一项目，多个旧项目只做资产对比，不自动合并或删除。有效规范决定设计约束；DESIGN.md、token 与组件样例冲突时指出并按已批准优先级处理，不自行用实现覆盖用户裁决。

- functional skills 与 rendering templates 分开查询。
- 长 run 查看实际事件与状态；长时间无文本不是取消条件，运行中不重启 daemon。
- 独立核对实际产物及其所在项目目录，不能只信 run 自报完成或只看点名子目录。
- 原生 resume 需原 project/conversation 和 runtime 证据；重建上下文不称为原生续跑。
- 归档/同步代码仓使用 od_sync.py 的预览，再按授权写入；不触碰 Open Design 原始数据目录。

## 验收与安全

按实际路线验证环境，不要求每条路线都跑 CLI 检查。真实渲染后核对相关画幅、可读性、溢出、交互或动画时间线；导出核格式、页数/时长与可打开性。渲染、导出、生产实现和客户端实机交互分别报告。

本机 daemon 默认 loopback，不为接通而暴露公网、绕过 workspace 身份或改 upstream 源码。停止、删除、覆盖、远端写入、安装与注册 MCP 前核对目标和本次授权；旧项目即使已迁移也不自动删除。

## 使用边界

### 依赖与安装

按所选路线依赖 Open Design 本体；桌面路线无需源码 checkout。普通配置只保存非秘密路径与偏好，必要时使用 ~/.config/soia-skills/soia-dev-open-design-ops/config.yml 或 SOIA_DEV_OPEN_DESIGN_OPS_CONFIG_FILE；不需要时不创建。

默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-open-design-ops`。
整域须明确选择：Claude Code 用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`，市场为 soia-team/soia-open-skills。
WorkBuddy 使用[专家说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。安装、发版、MCP 注册均不由这些说明自动授权。

**私密信息与中间数据：** provider 凭据由官方登录态管理，不打印 config/env 或身份值。只读探测不落盘；临时预览用 OS 临时目录，正式产物写批准位置；归档/覆盖先预览并保留恢复来源。daemon 状态使用其既有受管目录，不在技能仓创建客户运行数据。

**日志与完成回执：** 给出实际路线、产物、验证与缺口；端口探测、runId 或退出码不能单独证明交付成功。
