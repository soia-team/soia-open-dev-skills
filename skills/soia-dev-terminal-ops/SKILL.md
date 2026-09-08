---
name: soia-dev-terminal-ops
description: 管理长任务与后台日志，诊断停滞并安全停止或恢复明确进程。触发：后台跑这个、进程疑似卡住、安全停止进程
version: 1.2.0
created_at: 2026-07-07 14:44:10
updated_at: 2026-09-08 17:24:05
created_by: claude opus 4.6
updated_by: gpt-5
---

# soia-dev-terminal-ops

## 客户可读说明

**能做什么：** 在 POSIX/macOS/Linux 中管理长任务、日志与恢复。普通短命令不用本技能；Windows 原生不在兼容范围，可使用已具备的 WSL/POSIX 环境。

**如何使用：** 指定命令/工作目录或已有 PID/session 及目标。先用宿主现有会话与等待能力；确需脱离会话运行时才用 tmux，不因超过固定秒数自动后台化。

## 运行与观察

- 确认工作目录、目标进程和授权，安全传 argv；不拼接不可信 shell，也不把秘密放进命令回显或日志。
- 保存会话/PID、日志位置和可观察状态；保留命令退出码，不能把 tee 的成功当成原任务成功。
- 判断停滞要跨采样比较日志/业务心跳、累计 CPU、子进程、网络/IPC 中的相关信号。单次低 CPU、S 状态、无输出或一个超时都不是死锁证据。
- 观察窗口按任务特性或用户设置，不虚构通用阈值。正常等待、疑似停滞、信号不足分别说明；需要未来持续监控时使用宿主的监控机制，不靠无限轮询承诺。

常见只读检查：

    ps -o pid,ppid,stat,etime,time,command -p <PID>
    tmux list-sessions
    tmux capture-pane -p -t <SESSION>
    tail -n <LINES> <LOG_FILE>

网络检查可用 lsof；缺少相关工具只降低该信号覆盖，不自动安装。

## 安全停止与恢复

停止前重新核对 PID、父 PID、命令和任务归属，防止 PID 复用。说明中断写入/重复副作用风险，取得明确停止授权；不用宽泛 pkill/killall。

先 TERM，在合理宽限内复查退出与产物状态；仍存活且确需 KILL 时说明数据损失风险并取得该动作授权，再核对同一目标。恢复/替代命令先判断是否重复写入、费用或远端动作，不静默重跑。

## 输出与留存

优先纯 stdout 或宿主会话日志。额外临时日志用 OS 临时目录或客户指定目录；项目日志沿用项目规则，不默认写 cwd。高影响动作需要持久审计时，只记脱敏目标、时间、授权与结果并约定保留范围，不保存环境/日志全文或删除未知日志。

可选偏好保存在 ~/.config/soia-skills/soia-dev-terminal-ops/config.yml，通过 SOIA_DEV_TERMINAL_OPS_CONFIG_FILE 覆盖；无需时不建配置。报告实际状态、信号缺口、退出码与未完成项，不把进程退出当成产物已验证。

## 使用边界

### 依赖与安装

需要 POSIX shell、ps、kill；仅 tmux 路线依赖 tmux，lsof 为可选只读信号。
默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-terminal-ops`，执行前核实当前参数。
整域需明确选择：Claude Code 使用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 使用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；市场为 soia-team/soia-open-skills，完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装。上述命令不构成安装或发布授权。

**私密信息与中间数据：** 只使用授权材料并对引用脱敏；不需要凭据、不默认建立配置/state/cache。要求保存的交付物写批准位置，临时数据用 OS 临时目录；不将客户原文写进技能仓库。

**日志与完成回执：** 结果本身是主要交付；说明实际变更或未改动、关键依据与未验证部分，不强制额外报告。
