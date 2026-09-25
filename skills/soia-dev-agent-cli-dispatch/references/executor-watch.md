# 执行者判活、等待与退出原因归类

长任务派发后用 `scripts/executor_watch.py` 判断执行者是否还在推进、有界等待它结束，并把退出原因归成固定类别。只在需要判活或收尾归类时加载；单次短调用直接看退出码与产物即可。

## 判活：三个信号各取两次

`probe` 在间隔两端各取一次样，比较三个信号：

1. 进程是否存在；
2. 进程及其全部子孙进程的 CPU 时间合计是否增长（codex、dsh 的实际工作常在子进程里）；
3. 被监视的文件字节数是否增长：执行者的 stdout/stderr 重定向文件、dsh 会话文件 `session.v4.jsonl.zstd`、codex rollout 文件等，用 `--log` 重复传入。

结果为 `alive_progressing`（CPU 或任一文件增长）、`alive_idle`（仍在但两项都不增长）或 `exited`。单次取样、`head` 截断后的日志和 UI 状态都不作为判活证据。

```bash
python3 scripts/executor_watch.py probe --pid <pid> --log <stdout.log> --log <session-file> --interval 10
```

## 有界等待

`wait` 反复调用 `probe`，直到进程退出（退出码 0）、连续无进展超过 `--idle-limit` 秒（`stalled`，退出码 5）或超过 `--timeout` 秒（`timeout`，退出码 6）。它替代手写的 `kill -0` 循环；`stalled` 只是提示，结束执行者前仍按调用方的纪律先确认。

```bash
python3 scripts/executor_watch.py wait --pid <pid> --log <stdout.log> --interval 30 --idle-limit 900 --timeout 7200
```

## 退出原因归类

`classify` 在本机读取捕获的 stdout、stderr 和最后一条消息（codex `-o` 文件），只输出类别、用于用量记录的 `outcome`、完成度估计和命中的规则 ID，不回显原文。dsh 在多种失败下退出码仍为 0，因此以文本规则为准。

| 类别 | 典型信号 | `outcome` | 完成度 |
|---|---|---|---|
| `provider_not_registered` | dsh `NO_ADAPTER: no adapter registered for provider` | `blocked` | none |
| `session_not_found` | dsh `session "…" does not exist`；会话头 cwd 与目录不符 | `blocked` | none |
| `sandbox_git_write_denied` | `.git/…/index.lock` 的 `Operation not permitted`；`sandbox escalation … requires approval` | `blocked` | partial：改动可能留在工作区未提交，由主控核对后提交 |
| `executor_blocked_awaiting_decision` | 退出码 0 且最后一条消息含「未修改」「未提交」「暂停」「等待你选择」「未开始改动」等 | `blocked` | none |
| `auth` / `quota` | 认证失败；`usage limit`、余额不足 | `blocked` | none |
| `rate_limit` / `transport` | 429、限流；连接中断 | `failed` | unknown |
| `task_failed` | `unrecognized arguments` 等具体错误；无规则命中但退出码非 0 | `failed` | unknown |
| `timeout` | 等待超时或调用方标记超时 | `failed` | unknown |

- 具体错误优先于「等待裁决」措辞：执行者在消息里说暂停，但 stderr 已有脚本参数错误时，归 `task_failed`，并在 `matched_rules` 保留 `last_message_awaiting_decision`。
- `blocked` 类别不计入成功率分母，见 `references/usage-records.md`；它们多是配置、环境或交还决策，不代表执行者能力。
- 归类是执行层结论；产物质量仍由主控核对 diff 与验收命令。

```bash
python3 scripts/executor_watch.py classify --executor dsh --stdout <out> --stderr <err> --exit-code 0
python3 scripts/executor_watch.py classify --executor codex --stderr <err> --last-message <last-message-file> --exit-code 0 > <classify.json>
python3 scripts/usage_record.py from-codex --info <codex-info.json> --classification <classify.json> --requested-model <model> --append
```

规则来自 2026-09-25 作业台执行窗口的真实失败样本（路径已脱敏）。遇到未归类的失败，把脱敏后的错误行补进 `RULES` 并加自检用例，不要在调用方另写一套判断。
