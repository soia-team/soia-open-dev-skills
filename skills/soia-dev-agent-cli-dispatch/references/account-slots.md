# 账号槽位 / Account slots

> 现状核对：2026-11-18。只在同一个 CLI 需要并排用多个账号时加载本文件；单账号派发不需要。

## 是什么

一个槽位 = 某个 CLI 的一组环境变量覆盖，用来把这个 CLI 的登录态隔离开。不写 `--slot` 就是 `default`：不改任何变量，用主目录里的那份登录。

- 槽位登记在私有配置里（`~/.config/soia-skills/soia-dev-agent-cli-dispatch/config.yml` 的 `slots:` 与 `slot_rotation:`，模板见 `assets/config.example.yml`），不进仓库。
- 每个槽位只写：槽位名、`cli`（`references/supported-agents.yml` 里的执行器 id）、要覆盖的变量名与取值模板、可选备注。模板里 `~` 与 `{home}` 指用户主目录，`{slot}` 指槽位名。
- 配置里不写账号邮箱、凭据值、凭据文件内容；变量名形如 `*KEY*`、`*TOKEN*`、`*SECRET*`、`*AUTH*`，或取值、备注里出现邮箱形状的内容，`scripts/account_slots.py` 直接拒绝。
- 登录由客户本人在该槽位下完成（见下表），本技能不代登录、不复制认证文件、不建软链。

## 选槽位：只有「指定」和「轮流」

```bash
python3 scripts/account_slots.py list [--cli agy]                         # 列槽位，取值以 ~ 显示
python3 scripts/account_slots.py resolve --cli agy --slot acct2           # 指定
python3 scripts/account_slots.py resolve --cli agy --rotate [--peek]      # 轮流（--peek 只看不推进）
python3 scripts/account_slots.py exec --cli agy --slot acct2 -- agy models
eval "$(python3 scripts/account_slots.py resolve --cli agy --slot acct2 --format shell)"
```

- 轮流按 `slot_rotation.<cli>` 的顺序循环；没配时为 `default` 加该 CLI 已登记的槽位（按名字排序）。状态文件 `<state>/slots/rotation.json` 只记每个 CLI 上一次用的槽位名和时间，`0600`。
- **不按剩余额度自动调度。** 余量只作人工参考（agy 见下文「查看各槽位额度」）；某个槽位额度耗尽时，按常规额度门 `hold`，换槽位由调用方或客户显式决定。
- 槽位与执行器不匹配（如把 codex 槽位给 agy）、槽位未登记：脚本报错退出，不回落到 `default`。

## 接入派单、路由与用量

| 环节 | 用法 | 记录什么 |
|---|---|---|
| 预检报告 | 在该槽位的环境下探测额度，报告顶层写 `"slot": "<名>"`（缺省 = `default`） | 槽位名 |
| `scripts/route_model.py` | `--slot <名>`；必须与报告的 `slot` 一致，否则 `quota_binding_conflict` | 回执 `selected_slot` |
| `scripts/run_matrix.py` | case 字段 `slot`，或 `--slot <名>` 给没写 `slot` 的 case | manifest 每个 case 记 `slot`；非 `default` 的额度键为 `<键>@<槽位>`，一个账号耗尽不会连带封锁另一个账号 |
| 单次派发 | `account_slots.py exec --cli <id> --slot <名> -- <命令>`，子进程另有 `SOIA_DISPATCH_SLOT=<名>` | — |
| `scripts/usage_record.py` | 自动取 manifest case 的 `slot`；其他来源用 `--slot <名>` | 记录字段 `slot`（无则 `default`） |
| `scripts/usage_aggregate.py` | `--by-slot` 按槽位拆分分组，`--slot <名>` 只看一个槽位 | — |

manifest、用量记录与回执只写槽位名，不写槽位展开后的路径。

## 各 CLI 的隔离方式

| CLI | 覆盖变量 | 状态 | 说明 |
|---|---|---|---|
| agy（Antigravity CLI） | `HOME` | 已实测（2026-11-18，agy 1.5.10） | 见下节 |
| Codex | `CODEX_HOME` | 未验证 | 官方配置根（默认 `~/.codex`），放 `config.toml`、登录与 `sessions/`。本技能未实测两套登录并存；`scripts/codex_session_info.py` 会读 `$CODEX_HOME`，在同一槽位环境下运行或传 `--codex-home` |
| Claude Code | `CLAUDE_CONFIG_DIR` | 未验证 | 改配置目录。本技能未实测多账号；部分平台的登录凭据可能存在系统钥匙串而非该目录，能否真正分开以实测为准 |
| dsh | `DSH_HOME` | 部分实测 | 2026-09-25 在隔离 `DSH_HOME` 下复现过会话与 profile 行为（无凭据、未调模型）；多账号登录未验证。`scripts/dsh_session_usage.py` 需传 `--dsh-home` 指向该槽位 |

未验证的 CLI 第一次用槽位时，先只跑该 CLI 的只读登录或模型列表命令，确认确实是另一个账号，再派真实任务。

### agy：独立 `HOME`

- 2026-11-18 实测：`HOME=~/.agy-profiles/<槽位>` 下 agy 需要单独登录（客户本人在该 `HOME` 下首次运行 `agy` 完成浏览器授权），之后 `agy models`、`agy -p "/usage"` 返回的是该账号的数据（当日默认账号与另两个槽位账号的模型列表、额度分组都不同）。
- 换 `HOME` 会影响 agent 在任务里跑的所有命令。git / npm / pnpm / playwright 等的配置与缓存可以按需软链回主目录（例如 `.gitconfig`、`.npmrc`、`.cache`、`.local`）；没链回的目录（如 `~/.ssh`）在槽位下不可见。链哪些由客户决定，本技能不代建。
- agy 二进制在 `~/.local/bin` 时，槽位 `HOME` 下要能找到它（软链 `.local`，或派单时用绝对命令路径）。

## 查看各槽位额度（agy）

```bash
python3 scripts/agy_quota.py                 # 默认登录 + 所有 agy 槽位，人读视图
python3 scripts/agy_quota.py --slot acct2 --json
```

逐个槽位只跑官方只读命令，不起模型轮次、不耗额度：`agy -p "/usage" --output-format json`、`agy -p "/credits" --output-format json`、`agy models`；各槽位并行，单槽位约 40 秒。不读凭据文件、日志或会话库，调用时设 `AGY_CLI_HIDE_ACCOUNT_INFO=1`，输出只含解析后的字段。

| 字段 | 来源 | 说明 |
|---|---|---|
| 套餐名 | CLI 不提供 | agy 1.5.10 print 模式没有套餐/tier 字段（只在交互界面横幅显示），报告写「CLI 不提供」，不推断 |
| 模型组与组内模型 | `/usage` 的 `groups[].name`、`description` | 例：`Gemini Models`、`Claude and GPT models`；有的账号另有 `Gemini 4 Argon` 单独一组，组说明原样保留为「CLI 说明」 |
| 5 小时 / 7 天窗口剩余与重置时间 | `/usage` 的 `buckets[].window`（`5h` / `weekly`）、`remaining_fraction`、`reset_time` | 百分比由 `remaining_fraction` 换算；时间为 UTC |
| AI credits 剩余 | `/credits` 的 `remaining_credits` | — |
| 能用的模型 | `agy models` 第一列 | 账号范围内的列表 |

这份报告是给人选槽位的参考，不是 `route_model.py` 的额度预检报告；要走路由门时，仍按 `references/dispatch-contract.md`「额度预检」在该槽位下产出带 `slot` 的报告。
