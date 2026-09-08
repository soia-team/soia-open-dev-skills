# MCP 各宿主的配置形态与实测矩阵

> 主文件「环境与 daemon → 4. MCP 路线」的展开：配置形态、能力边界、逐家实测结果、派 run 的硬约束。
> **先看下面的「0.19.2 能力恢复」再看「0.18.x 能力边界」**——后者是历史记录，机器还没升级时才用得上。

## 0.19.2 能力恢复（实测，2026-08-18）——现在从这节开始读

**结论：0.18.x 的 MCP workspace 门在 0.19.2 上已经不再出现，同一套配置下 MCP 恢复为读写既有项目
与派新生成任务的首选通路。** 下面「0.18.x 能力边界」记录的那套"sidecar 不传 workspace header"
限制，在本次实测里没有重现。

- **`list_projects` 恢复正常**：对已绑定 workspace 的真实项目（桌面版创建的项目基本都已绑定），
  返回全部 4 个真实项目，且每条额外带了 0.18.1 实测里没有的 `workspaceId` 字段。**用了两条独立
  路径验证，结果一致**：stdio 直连 `daemon-cli.mjs mcp`（和 0.18.1 那次侦察同一种方法），以及
  当前正在使用的 Claude Code 长驻 MCP 连接（同一份官方配置，未做任何改动）。
- **`start_run` 恢复正常**：对已绑定项目返回 `runId`，`get_run` 能拿到 `pluginId:
  example-web-prototype` 与 `appliedPluginSnapshotId: 407017da-...`，与本机会话早期一次成功的
  run 完全一致——不是巧合命中"刚创建、还没绑定"的短暂窗口（那个窗口本身也随之失去意义：已绑定
  项目现在直接可用，不用再赌时间差）。
- **根因未定位**：不知道是上游哪次改动修复的，也没有验证 0.19.0/0.19.1 之间的哪个版本开始生效——
  只确认了 0.18.1（受影响）与 0.19.2（不受影响）这两个点。升级到 0.19.2 之间的版本时不要假设
  已经修好，按下面的判据实测确认。
- **验证范围到此为止**：只验证了 stdio 直连与 Claude Code 长连接这两条路径。codex/opencode/pi/
  cursor/workbuddy 在 0.19.2 上的连通性**未重新实测**，下面「实测矩阵」仍是 0.18.1 时期的结果；
  升级后要用于其它宿主，请按矩阵旁的验证命令重跑，不要直接沿用旧结论。

**判据**：用 `scripts/detect_route.py --json` 的 `routes.mcp.evidence.workspace_gap`——`affected`
按活着的 daemon 版本判断（取 `/api/health` 的 `version`，见 `desktop_ctl.meets_minimum_version()`），
0.19.2+ 不会再报 `affected: true`；仍是 0.18.x 时会报 `affected: true` 并带 `workaround`。不要凭
安装时间或"应该已经升级了"去猜。

**配置不用改**：官方界面（设置 → Open Design MCP）给的示例命令会把当前版本号写死在路径里
（如 `versions/0.19.2/payload/...`），但本技能生成的配置走 `resolve_launcher_payload()` 动态解析
（见下面「装 MCP」一节），**这次从 0.18.1 升到 0.19.2 全程没有手动改过配置，重启后自动解析到新
版本路径**。界面给的命令仅供参考或临时排障，长期使用请用本技能生成的配置。

## 0.18.x 能力边界（历史记录，实测 2026-08-07）——机器还没升级到 0.19.2 时仍然成立

**结论：MCP 连通性（配置、握手、工具调用）在 0.18.1 上完全恢复，但对已绑定 workspace 的项目
——也就是桌面版创建、且只要 App 还开着通常一分钟内就会自动绑定的几乎所有项目——`list_projects`
/`get_project`/`get_file`/`list_files`/`search_files`/`get_artifact`/`start_run`（按名或按活动
上下文取项目时）全部不可用。** 这不是配置问题，改配置、加环境变量都修不了；根因在打包内 MCP
sidecar 自身代码。**这条限制在 0.19.2 上没有重现**（见上一节），但没有验证是哪个上游改动修复的，
机器仍停在 0.18.x 时请继续按本节处理。以下是完整证据链，供复核或日后升级重新验证。

#### 实测的完整 22 工具清单

用权威配置以 stdio 直起 `daemon-cli.mjs mcp`，发 `initialize` + `tools/list`，`serverInfo`
为 `{"name":"open-design","version":"0.2.0"}`，`protocolVersion` 为 `2024-11-05`：

```
collect_brief          confirm_brief           list_projects
get_active_context      get_artifact            get_project
get_file                search_files            list_files
create_artifact         write_file              delete_file
delete_project          create_project          list_skills
list_plugins            start_vela_login        get_vela_login_status
start_run               get_run                 cancel_run
list_agents
```

（v0.13.0 时期只文档化了 `start_run`/`get_run` 两个；实际 0.18.1 一直有这一整套，`tools/list`
在两个版本应该都能拿到完整签名——本次只对 0.18.1 做了 stdio 直连验证。）

#### 根因：sidecar 从不附带 workspace header，也不读任何环境变量

打包内 MCP server 实现（`chunks/chunk-*.mjs`，18000+ 行，`SERVER_NAME="open-design"`,
`SERVER_VERSION="0.2.0"`）里，`list_projects`/`get_project` 等工具的实现是：

```js
case "list_projects":
  return ok(await getJson(`${baseUrl}/api/projects`));
// ...
async function getJson(url) {
  const resp = await fetch(url);          // ← 没有第二个 headers 参数
  ...
}
```

全文件 `grep process.env` **零命中**——sidecar 代码里没有任何地方读环境变量，更不用说拿去
构造 `x-od-workspace-id`/`x-od-workspace-member-id` header。`/api/projects`（不带 id）本身
只返回从未绑定 workspace 的项目（见 [desktop-app.md](desktop-app.md) 的「workspace 上下文门」），
所以 `list_projects` 长期回 `{"projects":[]}`；`get_project`/`get_file`/`list_files` 走
`/api/projects/:id`，对已绑定项目直接 400 `WORKSPACE_CONTEXT_REQUIRED`。

**穷举测试过的候选环境变量，逐个通过 stdio 直起 sidecar + 真实调用验证，均无效**：

| 候选 env | 结果 |
| --- | --- |
| （不设，权威配置原样） | `list_projects` → `{"projects":[]}` |
| `OD_DEV_WORKSPACE_CONTEXT`（JSON 字符串，daemon 主进程确实读它，但只用于日后可能的开发态注入，MCP sidecar 代码不读） | 无效，结果同上 |
| `OD_WORKSPACE_ID` / `OD_WORKSPACE_MEMBER_ID`（按命名规律猜测，实际不存在这两个变量） | 无效，结果同上 |
| `OD_WORKSPACE_CONTEXT_SOURCE=local` | 无效，结果同上 |

四次测试用的是四个**独立**的 sidecar 进程（每次重新 stdio 直起，不是同一进程反复调用），
排除了"前一次调用留下缓存"这类混淆。另有一次是当前正在使用的、Claude Code 长驻 MCP 连接
（同一份权威配置，含 `OD_MCP_BOOTSTRAP_*`），结果一致。

#### 什么仍然有效

- **`create_project` + 短暂窗口内的 `list_projects`/`get_project`**：新建的项目最初是
  "未绑定" 状态，此时能被 `list_projects` 看到（因为它走的正是"只返回未绑定项目"那条老接口）。
  但这个窗口**不可靠**——实测同一个刚创建的项目，在 App 保持打开、约一分钟后被自动绑定
  （`app.sqlite.workspace_projects` 多出一行），此后 `get_project`/`start_run` 对它同样
  报 `no projects on this daemon`。**没有在这个窗口内成功跑完一次 `start_run`**——尝试时
  窗口已经关闭，报错方式与已绑定项目完全一样，不构成可依赖的契约。
- **`get_run(runId)`**：只按 id 查、不经过项目名/列表解析，不受这道门影响，正常返回，且字段
  比 v0.13.0 更丰富（见下文「派 run 的契约」）。
- **`get_active_context`**：只要客户最近 5 分钟内点过 App 里的项目就能正确返回
  `{"active":true,"projectId":...}`；但拿到这个 id 后再去调 `get_project()`/`list_files()`
  （它们会用这个 id 打 `/api/projects/:id`）一样会撞上 400——active context 能查到，不代表
  后续操作能成功。
- **`list_agents`/`list_skills`/`list_plugins`**：不涉及具体项目，不受影响，正常返回真实数据
  （实测 `list_agents` 返回 12 个 agent 的完整型号列表）。

#### 已绑定项目现在怎么读写：改走 HTTP（0.18.x）

> 0.19.2+ 直接用 MCP 的 `list_projects`/`get_project`/`get_file` 等工具即可，见上一节；
> 本小节是 0.18.x 上的降级方案，仍然有效，未升级的机器继续照此处理。

见 [desktop-app.md](desktop-app.md) 的「workspace 上下文门」一节与 `scripts/desktop_ctl.py`——
带上 `x-od-workspace-id`/`x-od-workspace-member-id` 两个 header 直接 HTTP 调用，实测完全恢复，
能拿到全部真实项目与文件内容。

#### 派新生成任务：`od chat new` 验证可行，`od automation` 验证不可行（0.18.x）

> 0.19.2+ 直接用 MCP 的 `start_run` 即可，见上一节「0.19.2 能力恢复」；本小节是 0.18.x 上
> `start_run` 打不通时的命令行降级方案，仍然有效，未升级的机器继续照此处理。

命令行侧，`daemon-cli.mjs --help` 实测（2026-08-07）确认 v0.13.0 的 `od run start/watch/info`
**已下线**，取而代之的相关子命令：

- **`od chat new --project <id> --workspace <wsId> --workspace-member <memberId> [--seed-from
  <cid>] [--title "<t>"] [--json]`**——**实测成功**：对已绑定 workspace 的真实项目
  （`soia-family-study-design`）建会话，返回 200 与真实 `conversation.id`。这是唯一一条实测
  证实"显式传 workspace 参数能穿透这道门"的命令行路径，`--help` 里明确标注这两个 flag 是
  "Explicit Workspace id/member id for the bound project"，说明这是官方预期的用法，不是巧合。
  测试后已用 `DELETE /api/projects/<id>/conversations/<cid>` 清理测试会话，未在客户项目里
  留下痕迹。
- **`od automation create --target reuse=<id> ...`**——**实测不可行**：这条命令不接受
  `--workspace`/`--workspace-member`（传了直接报 `unknown flag: --workspace`），对已绑定项目
  返回 `403 {"code":"WORKSPACE_ACCESS_DENIED","message":"the routine belongs to a different
  Workspace"}`。`od automation create --target new-project`（面向全新项目）未测试。
  `od automation list`（只读）本身不需要 workspace 参数，正常返回。

**"建会话之后怎么触发一次真正的生成"——本次侦察未验证，不写成可用命令。** 建会话只是第一步；
`od chat new` 之后应该怎么发消息触发生成、消息体格式是什么，超出了本次侦察范围（会产生真实的
模型调用费用，未在没有更明确契约前贸然尝试）。**当前唯一确定可靠的方式是客户在 App 界面里手动
发起。** 上层技能/流程不应假装存在一条全自动的"HTTP/CLI 直接派生成任务"通路。

#### 装 MCP：客户端与配置形态

不走网络端口，而是用 Electron Helper 以 Node 模式跑打包内的 `daemon-cli.mjs mcp`：

```json
"open-design": {
  "command": "<launcher>/versions/<version>/payload/Open Design.app/Contents/Frameworks/Open Design Helper.app/Contents/MacOS/Open Design Helper",
  "args": ["<launcher>/versions/<version>/payload/Open Design.app/Contents/Resources/app/prebundled/daemon/daemon-cli.mjs", "mcp"],
  "env": {
    "OD_DATA_DIR": "<APP_SUPPORT>/namespaces/<namespace>/data",
    "OD_SIDECAR_IPC_PATH": "/tmp/open-design/ipc/<namespace>/daemon.sock",
    "OD_MCP_BOOTSTRAP_COMMAND": "/usr/bin/open",
    "OD_MCP_BOOTSTRAP_ARGS": "[\"-g\",\"-j\",\"<install.json 的 launchPath，通常是 /Applications/Open Design.app>\",\"--args\",\"--headless\"]",
    "ELECTRON_RUN_AS_NODE": "1"
  }
}
```

`<launcher>` = `<APP_SUPPORT>/launcher/channels/<channel>/namespaces/<namespace>`，
`<version>` 取 `runtime.json.active.version`——完整解析逻辑见
[desktop-app.md](desktop-app.md)「launcher 版本化路径」一节，`scripts/desktop_ctl.py` 的
`resolve_launcher_payload()` 已实现，`install_od_mcp.py` 已改用它生成配置，不要手写路径。

**这一点在 0.18.1 → 0.19.2 的真实升级里验证过：** 客户从 App 的设置 → Open Design MCP 页面
拿到的官方示例命令，把 `<version>` 写死成当时的版本号（如 `versions/0.19.2/payload/...`）；
本技能生成的配置不写死，桌面版自动升级后重新解析即自动指向新版本目录，**全程不用手改配置**。
界面给的写死版本命令仅适合临时排障或对照，不要当长期配置抄进 agent 配置文件。

**这是 v0.13.0 配置（`command`/`args` 固定指向 `/Applications/Open Design.app`）在 0.18.1 上会
踩的坑**：固定路径可能连到过期版本（本机实测 `/Applications` 下是 0.18.0，真正在跑的是
0.18.1），表现为 sidecar 能起来、握手也成功，但连到的是一个空/过期 daemon——`OD_MCP_BOOTSTRAP_*`
两个新增 env 才是让它在 daemon 不可达时自举拉起正确 App 的机制，v0.13.0 配置没有这两个键。

`OD_SIDECAR_IPC_PATH` 正是「`od://` scheme 只在 MCP sidecar 上下文里可用」的原因。
`namespace` 要从 `detect_route.py` 的输出取，不要写死 `release-stable`。

**装 MCP 不能靠客户端 UI。** Claude 桌面版的 Add custom connector 只接受
`Remote MCP server URL`，本地 stdio server 加不进去；那个 Connectors 菜单列的是
托管型连接器，本地 server 不会出现在里面。只能写配置文件或用 `claude mcp add`。
用 `install_od_mcp.py` 处理各家格式差异（已适配上面两个新增 env）。

#### 实测矩阵（2026-08-05；连通性 2026-08-07 用 0.18.1 配置复核，结论不变；**未在 0.19.2 上整体重测**）

**只写实际跑过的，未验证的一律标未验证。** 证据强度分三级：
配置被解析 < 连接握手成功 < 工具调用返回真实数据。

| Agent | 配置落点与键名 | 验证命令 | 结果 |
| --- | --- | --- | --- |
| Claude Code | `~/.claude.json` → `mcpServers` | `claude mcp list` | ✅ **工具调用**（本会话全程在用） |
| codex | `~/.codex/config.toml` → `[mcp_servers.x]` + `[.env]` | `codex mcp list` / `get` / `exec` | ✅ **工具调用**：`mcp: open-design/list_projects started → (completed)`，返回 5 个项目 id |
| opencode | `~/.config/opencode/opencode.json` → **`mcp`**（非 `mcpServers`） | `opencode mcp list` | ✅ **连接握手**：状态 `connected`；未取得工具调用输出 |
| cursor | `~/.cursor/mcp.json` → `mcpServers` | 未验证 | ⬜ 格式已核对（与 Claude 同构），**未装未测** |
| WorkBuddy | **UI 配置**（插件 → MCP → Add），非配置文件 | 客户端界面 | ⬜ 参数已核对，**脚本不适用**——见下 |
| pi | `~/.pi/agent/mcp.json`（装 `pi-mcp-adapter` 后）→ `mcpServers` | `pi -p "调用 open-design MCP 的 list_projects..." --mode text` | ✅ **工具调用**：返回 5 个真实项目 id，见下 |
| qwen | `settings.json` 无 MCP 键 | — | ➖ 不适用（`shells/init-mcp.sh` 是改 Claude 配置的工具，非自身 MCP） |

**上表「返回 N 个项目 id」这几条是 v0.13.0 时代的结果，0.18.1 上不再可复现**——见「0.18.x 能力
边界」一节：同一个 `list_projects` 调用当时对已绑定 workspace 的项目返回空数组。上表仍然如实
证明了**连通性/配置格式没问题**（这部分结论继续成立，0.18.1 上用新配置复核过 Claude Code、
codex、opencode、pi 四家，握手/工具调用本身依旧成功），只是"工具调用返回真实数据"这一级证据在
0.18.1 上已经不能靠 `list_projects` 拿到，改用上面验证过的 `list_agents`（本机 0.18.1 实测返回
12 个 agent 的完整型号列表）或 `get_run(<已知 runId>)` 来验证"配置真的通到底了"。

**0.19.2 上（见「0.19.2 能力恢复」一节）`list_projects` 对 Claude Code 长连接与 stdio 直连这两条
路径重新变回了最高一级证据**（工具调用返回真实数据），不用再退而求其次去查 `list_agents`。
codex/opencode/pi/cursor 在上表里的连通性结论沿用 0.18.1 记录，**升级后请重新跑一遍对应验证命令
确认 `list_projects` 是否也已恢复**，不要假设所有宿主都和 Claude Code 一样已验证。

两条来自实测的要点：

- **opencode 的 `env` 走 `/usr/bin/env` 前缀注入**（它的条目结构是 argv 数组 + `type`/`enabled`，
  未见 env 字段）。这个方案已验证可连：`opencode mcp list` 显示 `✓ connected`，
  且同列表中 `pencil` 显示 `✗ failed ENOENT`，证明该状态是真实探测而非静态回显。
- **codex 的 `Status: enabled` 只是配置状态，不代表连得上。** 要确证必须让它真跑一次：

  ```bash
  codex exec --skip-git-repo-check "调用 open-design MCP 的 list_projects，原样列出项目 id"
  ```

  输出里出现 `mcp: open-design/list_projects (completed)` 才算数。

回退：脚本写入前会备份成 `<配置文件>.bak-od`，或用各家自带命令移除
（如 `codex mcp remove open-design`）。

#### pi：核心不带 MCP，装 `pi-mcp-adapter` 扩展后可用（2026-08-05 实测 v0.83.0）

**pi 核心本身没有 MCP 概念**，这条结论没变：`pi --help` 的子命令只有
`install / remove / uninstall / update / list / config / auth`，没有 `mcp`；
默认的 `~/.pi/agent/settings.json` 也没有任何 MCP 字段。

但它的扩展机制（`pi install npm:@foo/bar`）里有个现成的第三方包能补上这一层：

```bash
pi install npm:pi-mcp-adapter
```

装完后 `settings.json.packages` 里多一条 `"npm:pi-mcp-adapter"`，`pi` 启动时会加载它，
并新建 `~/.pi/agent/mcp.json` 作为 pi 自己的 MCP 注册表，结构是：

```json
{ "mcpServers": {}, "imports": [] }
```

`mcpServers` 这一层和 claude-code/cursor 同构（`mcpServers.<name> = {command, args, env}`），
可以直接复用本文档开头那段配置形态原样写进去。

**不要用 `pi-mcp-adapter init` 的 imports 模式。** 这条命令会扫描本机 cursor / claude-code /
claude-desktop / codex / opencode 五个宿主，把它们**全部**已配置的 MCP server 借过来写进
`imports` 字段，而不是只借 open-design 这一条。实测踩过的坑：

- codex 里 `[mcp_servers.computer-use]` 本来就是 `enabled = false`（codex 自己都没启用），
  且 `command` 是相对路径 `./Codex Computer Use.app/...` + `cwd = "."`——codex 启动时会把
  cwd 切到 `~/.codex/computer-use/` 才能解析。import 机制照抄了 command 和 cwd，**既不尊重
  `enabled=false` 开关，也没保留 codex 的 cwd 上下文**，在 pi 里必然 `spawn ... ENOENT`。
- cursor 和 opencode 都定义了名为 `pencil` 的 server 但路径完全不同（分别指向
  `~/.qoder/extensions/...` 和 `~/.pencil/mcp/...`），**同名冲突**，import 合并后用到坏的那个。
- cursor 的 `claude-mem`（一个 node 脚本）通过 import 起了但连接被对方关闭，
  没有单独验证是脚本本身的问题还是缺上下文。

正确做法是清空 `imports`，只在 `mcpServers` 里直接定义 open-design，和 codex/opencode 那两条
路线保持同一种模式（各家独立配置各自需要的 server，不整体互相借用）：

```json
{
  "mcpServers": {
    "open-design": {
      "command": "<launcher>/versions/<version>/payload/Open Design.app/Contents/Frameworks/Open Design Helper.app/Contents/MacOS/Open Design Helper",
      "args": ["<launcher>/versions/<version>/payload/Open Design.app/Contents/Resources/app/prebundled/daemon/daemon-cli.mjs", "mcp"],
      "env": {
        "OD_DATA_DIR": "<APP_SUPPORT>/namespaces/<namespace>/data",
        "OD_SIDECAR_IPC_PATH": "/tmp/open-design/ipc/<namespace>/daemon.sock",
        "OD_MCP_BOOTSTRAP_COMMAND": "/usr/bin/open",
        "OD_MCP_BOOTSTRAP_ARGS": "[\"-g\",\"-j\",\"<install.json 的 launchPath>\",\"--args\",\"--headless\"]",
        "ELECTRON_RUN_AS_NODE": "1"
      }
    }
  },
  "imports": []
}
```

验证用非交互模式（`--print`/`-p`），不用进 TUI：

```bash
pi -p "调用 open-design MCP 的 list_agents 工具，只输出它返回的原始 agent 列表" --mode text
```

**v0.13.0 时代（2026-08-05）实测输出是 5 个真实项目 id/name（用的是 `list_projects`）**，
达到矩阵里最高一级证据（工具调用返回真实数据）。0.18.1 上 `list_projects` 已不再能拿到已绑定
项目（见「0.18.x 能力边界」），验证连通性改用 `list_agents` 这类不受 workspace 门影响的工具；
pi 在 0.19.2 上是否也已恢复未重新实测，按上面「验证范围到此为止」的说明，升级后请重新用这条
命令确认。

#### WorkBuddy：UI 配置，脚本不适用

WorkBuddy 在客户端里配 MCP（插件 → MCP → Add），**没有可写的配置文件落点**，
所以 `install_od_mcp.py` 对它只打印不写。界面要填的字段与对应值：

| 界面字段 | 填什么 | 能不能写死 |
| --- | --- | --- |
| 启动命令 | `…/Open Design Helper.app/Contents/MacOS/Open Design Helper` | 可以（App 安装路径固定） |
| 参数 1 | `…/app/prebundled/daemon/daemon-cli.mjs` | 可以 |
| 参数 2 | `mcp` | 可以 |
| `ELECTRON_RUN_AS_NODE` | `1` | **必填固定值**。缺了它 Helper 会以 GUI 模式启动，MCP 起不来 |
| `OD_DATA_DIR` | `<APP_SUPPORT>/namespaces/<namespace>/data` | **不能写死**，`namespace` 随安装变 |
| `OD_SIDECAR_IPC_PATH` | `/tmp/open-design/ipc/<namespace>/daemon.sock` | **不能写死**，同上 |
| `OD_MCP_BOOTSTRAP_COMMAND`（0.18.1 新增） | `/usr/bin/open` | 可以（固定 OS 工具路径） |
| `OD_MCP_BOOTSTRAP_ARGS`（0.18.1 新增） | `["-g","-j","<install.json 的 launchPath>","--args","--headless"]`（一段 JSON 数组文本，整体填进这一个字段） | **不建议写死**，`launchPath` 理论上随安装变，虽然本机实测就是 `/Applications/Open Design.app` |
| 启动命令/参数 1/2 里的可执行文件路径（0.18.1 变化） | 用 `<launcher>/versions/<version>/payload/...` 下的实际路径，**不是** `/Applications/Open Design.app` 下那份 | **不能写死**——本机实测 `/Applications` 下是 0.18.0，真正在跑的是 versions 目录下的 0.18.1，两者不是同一份文件；`version` 随自动升级变化 |
| 环境变量传递 | 留空 | — |
| **工作目录** | **留空** | OD MCP 通过 IPC socket 连 daemon，不依赖 cwd。实测佐证：codex 的 `cwd: -`、opencode 未设 cwd，两者均连通且 codex 完成了工具调用 |

两个 `<namespace>` 用 `detect_route.py --json` 的 `routes.mcp.evidence.ipc_sockets`
取，不要照抄本文里的 `release-stable`。

查当前装了没（Claude Code）：

```bash
claude mcp list
```

#### 派 run 的契约（v0.13.0 时期写下的三条教训——**先决条件是能跑起来**）

0.18.1 上 `start_run` 对已绑定项目因为「0.18.x 能力边界」一节说的 workspace 门根本起不了 run，
以下内容当时只对「MCP 自己新建、还没被自动绑定的项目」那个短暂窗口成立。**0.19.2 起 `start_run`
本身已经恢复（见「0.19.2 能力恢复」），先决条件重新满足，下面三条教训对所有已绑定项目直接适用，
不再局限于那个短暂窗口。**

```
start_run(project, prompt)  → 立刻返回 runId，OD 自己 spawn agent 去做
get_run(runId)              → queued|running|succeeded|failed|canceled
```

`get_run` 0.18.1 实测返回的字段比这两行描述丰富得多，除了 `status`，还有
`agentMessage`（agent 的文字回复，成功但没产出文件时——例如被上面的 workspace 门挡住某个
子步骤——里面会有具体原因）、`studioUrl`（可点开在浏览器里看这轮对话的 Open Design 页面）、
`executionDiagnostics`（排队/首个模型响应/工具调用等分阶段耗时和 token/cache 明细）、
`hint`（daemon 自己给的下一步建议，例如"没有产物时把 agentMessage 转达给用户"）。

三条实测教训：

1. **prompt 里必须内联 `tokens.css` 全文。** run 内的 agent 读
   `design-systems/<id>/` 会拿到 404，它看不到挂载的设计系统文件。只在 prompt 里
   写「请遵守 Warm Editorial」是不够的——agent 只能靠猜或反推。可行的替代是让它
   参考项目里一个已经正确应用了该系统的页面。
2. **`toolBundle.mcpServers` 默认是空的**，run 内的 agent 只有 Bash/Read/Write，
   没有任何 MCP 工具。要给它加，得在 OD 界面「集成 → 外部 MCP 服务器」配置
   （落在 `.od/mcp-config.json`）。这个方向和上面那个 MCP 是**反的**：那里 OD 是
   客户端，这里 OD 是服务端，别混。
3. **实时进度不在 API 里，在磁盘上。** `get_run` 只给状态，看不到 agent 在干什么。
   要「打印」就 tail 事件流：

   ```bash
   tail -f "<data>/runs/<runId>/events.jsonl"
   ```

   事件形如 `{"id","event","data","timestamp"}`；`event` 为 `pipeline_stage_started`
   / `pipeline_stage_completed` / `agent`（`data.type` 再分 `tool_use` / `tool_result`
   / `text`）/ `diagnostic` / `error`。这是四种官方入口都没提供的能力。

一次 run 通常 5–30 分钟。**文件 mtime 长时间不变是 agent 在思考，不是卡死**，
不要因此 `cancel_run`，更不要改用 `write_file` 自己把设计写了——那样就绕过了
OD 的生成管线，产出质量和「派给 OD」不是一回事。
