# 桌面版 App 的运维细节

> 主文件「环境与 daemon → 3. 桌面版 App」的展开。只在真的碰到这些症状时读。

#### launcher 版本化路径（0.18.1 实测，2026-08-07）

v0.13.0 时代桌面版的可执行文件固定在 `/Applications/Open Design.app` 下；升级到 launcher
分发后，这个假设不再成立：

```
~/Library/Application Support/Open Design/launcher/channels/<channel>/namespaces/<namespace>/
├── runtime.json     ← launcher 自己维护的"当前生效版本"指针（最权威）
├── install.json     ← launchPath：OS 级启动入口，通常就是 /Applications/Open Design.app
└── versions/
    ├── 0.18.0/payload/Open Design.app/...
    └── 0.18.1/payload/Open Design.app/...   ← 真正在跑的往往是这个
```

`runtime.json` 实测内容：

```json
{"active": {"generation": 2, "version": "0.18.1"}, "channel": "stable", "namespace": "release-stable"}
```

`install.json` 实测内容：

```json
{"channel": "stable", "launchPath": "/Applications/Open Design.app", "namespace": "release-stable"}
```

**两处路径不能相互替代**——本机实测 `install.json.launchPath` 指向的 `/Applications/Open
Design.app` 版本号是 `0.18.0`，而 `runtime.json.active.version` 指向、且 MCP 配置
`command`/`args` 实际在跑的是 `versions/0.18.1/payload/`。前者是 launcher 维护的 OS 级启动
入口（Spotlight/Dock 双击打开的那个，Squirrel 式自更新可能还没来得及把它推到最新），后者才是
"现在真正提供 daemon/MCP 服务的那份代码"。`OD_MCP_BOOTSTRAP_ARGS` 里 `open -j` 要打开的是
**前者**（拉起 App 本身，版本随 launcher 自己更新即可），`command`/`args` 要指向的是**后者**
（必须是当前生效版本，写死或指向旧版本都会连不上或行为对不上）。

解析顺序（`scripts/desktop_ctl.py` 的 `resolve_launcher_payload()` 已实现，不要重新手写）：

1. 读 `runtime.json` 的 `active.version`——比自己排序 `versions/` 目录名更权威，能区分
   "磁盘上残留的旧版本目录" 和 "真正在跑的那个"（例如升级到一半的中间状态，`versions/` 下
   已经有更高版本号的目录，但 `runtime.json` 还没切过去）。
2. 读不出时，退化为扫描 `versions/` 目录取语义版本最大、且确实包含 `daemon-cli.mjs` 的那个。
3. 都失败：回退固定路径 `/Applications/Open Design.app`（兼容非 launcher 的旧式安装，或
   launcher 目录结构本身就不存在的场景）。

实测本机两个版本目录（`0.18.0` 与 `0.18.1`）内置的 `design-systems/warm-editorial/tokens.css`
逐字节一致（`diff` 无输出）——**这次侦察没有发现内容漂移**，但两个目录本质是不同版本，不保证
永远一致；`references/design-systems.md` 里直接从 `/Applications/...` 读设计系统文件的写法
同理应改用 `resolve_launcher_payload()["app_bundle"]` 而非硬编码 `/Applications`。

#### workspace 上下文门（0.18.1 实测，2026-08-07）

**症状**：`GET /api/projects` 返回 `{"projects":[]}`，即使磁盘上项目目录完好（本机
`soia-family-study-design` 有 32 个 `pages/*.html`）；`GET /api/projects/<id>` 或文件路由
返回 `400 {"code":"WORKSPACE_CONTEXT_REQUIRED"}`。

**根因**（源码定位：打包内 `chunks/server-*.mjs`，函数名逐版本可能变但逻辑不变）：

1. `GET /api/projects`（不带 id）内部调用 `listUnboundProjects2(db)`——**只返回从未绑定过
   workspace 的项目**。桌面版创建的项目会被自动绑定到一个本机生成的 personal workspace
   （见下），绑定后就从这个列表消失，不代表项目不存在或 daemon 坏了。
2. 真正能看到全部项目的是 `GET /api/workspaces/<workspaceId>/projects`，以及单项目的
   `GET /api/projects/<id>`——这两类路由（连同文件读取、run 相关路由）都要求请求带
   `x-od-workspace-id` 与 `x-od-workspace-member-id` 两个 header，否则 400
   `WORKSPACE_CONTEXT_REQUIRED`。校验函数默认（`OD_WORKSPACE_CONTEXT_SOURCE` 未设为
   `"vela"` 时）**直接信任 header 自证的身份**，不查云端账户——本机场景下这两个值不是凭据，
   不需要登录 Vela/云端账户。

**这两个值本机怎么拿**（`app.sqlite` 只读查询，`scripts/desktop_ctl.py` 的
`resolve_workspace_identity()` 已自动化，以下是它做的事、可以照抄手动核验）：

```bash
sqlite3 -readonly \
  "$HOME/Library/Application Support/Open Design/namespaces/release-stable/data/app.sqlite" \
  "SELECT DISTINCT workspace_id FROM workspace_projects;"
# → 本机实测：y72... 这类 25 位小写字母数字 id（cuid2 风格），本机是唯一一个
#   personal workspace，4 个项目全部绑定在这一个 id 下

sqlite3 -readonly \
  "$HOME/Library/Application Support/Open Design/namespaces/release-stable/data/app.sqlite" \
  "SELECT created_by_workspace_member_id, updated_by_workspace_member_id
     FROM workspace_projects WHERE workspace_id = '<上面查到的 id>' LIMIT 1;"
# 本机实测两列均为 NULL（daemon 称之为 "unattributed"，一样被接受）；
# 这时退回同一 workspace 下其它资源记录的建立者：
sqlite3 -readonly \
  "$HOME/Library/Application Support/Open Design/namespaces/release-stable/data/app.sqlite" \
  "SELECT created_by_workspace_member_id FROM workspace_resources
     WHERE workspace_id = '<同上>' AND created_by_workspace_member_id IS NOT NULL LIMIT 1;"
```

**独立交叉验证**（不止一条证据链）：桌面版自己的日志（`namespaces/<ns>/logs/desktop/latest.log`）
里能直接搜到它自己发起的请求带着这两个值——`GET /api/workspace/events?workspaceId=<同上>&
workspaceMemberId=<同上>`——与 sqlite 查到的完全一致，证明这不是巧合或误读表结构。

**实测：带上 header 后完全恢复**：

```bash
WSID=<上面查到的 workspace_id>
MEMBERID=<上面查到的 member_id>
curl -s "http://127.0.0.1:<port>/api/workspaces/$WSID/projects" \
  -H "x-od-workspace-id: $WSID" -H "x-od-workspace-member-id: $MEMBERID"
# → 200，返回全部 4 个真实项目，含 entryFile、designSystemId、linkedDirs 等完整元数据；
#   不带这两个 header 时同一路由是 400 WORKSPACE_CONTEXT_REQUIRED
```

`GET /api/projects/<id>`（取单项目详情，含列表路由没有的 `resolvedDir` 字段）、
`GET /api/projects/<id>/files/<name>`（取文件原始内容）同样需要这两个 header，机制一致。

**这不是本机独有的巧合性 bug**：同一次侦察里，一个真实的历史生成 run（`get_run` 读到的
`agentMessage`）里，Open Design 自己内部的图片导出工具也报了同样的错——"实际图片导出此前被
缺失的工作区成员上下文阻断"——说明这道门是 0.18.1 内部普遍生效的机制，不只影响外部调用方。

**MCP sidecar 不受益于上面这套 header 方案（0.18.x 上如此）**：sidecar 内部直接 `fetch()` 这些
路由，代码里没有任何地方读环境变量或附带这两个 header（详见
[mcp-hosts.md](mcp-hosts.md)「0.18.x 能力边界」一节），所以在 0.18.x 上本节的修复只对
HTTP/`desktop_ctl.py` 生效，不能让 MCP 工具跟着恢复。**0.19.2 实测（2026-08-18）：同一套配置下
MCP 自己也恢复了**（`list_projects`/`start_run` 对已绑定项目正常返回），不再需要靠本节这套
header 方案给 MCP 兜底；完整证据见 [mcp-hosts.md](mcp-hosts.md)「0.19.2 能力恢复」一节。

#### `POST /api/runs`：HTTP 派活的完整契约与两个陷阱（MCP 不可用时的应急通路）

> 0.19.2+ 上 MCP 的 `start_run` 已经恢复（见 [mcp-hosts.md](mcp-hosts.md)「0.19.2 能力恢复」），
> 能用 MCP 就不要用这条路——本节两个陷阱都是实测踩出来的真实代价，不是理论风险。这条通路只在
> MCP 不可用（0.18.x，或未来其它原因导致 MCP 连不上）时作为应急。

**契约**：`POST /api/runs`，body 接受 `projectId` / `conversationId` / `requestId` / `prompt` /
`plugin`，和其它已绑定项目的路由一样需要 `x-od-workspace-id` / `x-od-workspace-member-id` 两个
header，否则同样 400 `WORKSPACE_CONTEXT_REQUIRED`。

```bash
curl -s -X POST "http://127.0.0.1:<port>/api/runs" \
  -H "x-od-workspace-id: $WSID" -H "x-od-workspace-member-id: $MEMBERID" \
  -H "Content-Type: application/json" \
  -d '{"projectId":"<id>","prompt":"<brief>"}'
# 可选加 "plugin":"<pluginId>"——见下面陷阱二，不是默认该加的参数
```

实测两种失败模式，**都不是"报错退出"，而是"看似成功但结果不对"，更危险**：

1. **不带 `plugin` 参数**：agent 确实听了 brief，但**产物落点与命名不受控**——实测三个 run 把
   HTML 写到了**项目根目录**而不是 brief 里指定的 `pages/`，文件名也不是 brief 指定的（变成了
   `family-study-product-overview.html` / `family-study-product-studio.html` 这类 agent 自己
   起的名字），且质量违反了项目规范（实测字号 9/10/11px、红线命中 2 处）。**不能假设"没带 plugin
   就是纯粹听 prompt 摆布"**，落点和命名依然会被 agent 自由发挥。
2. **带 `plugin: example-web-prototype`**：**比不带 plugin 更糟**——插件自带的种子指令（这里是
   "单页高保真产品工作室原型"那一套）**优先级压过 prompt**。实测用一个极简任务验证（"只建一个
   只有一行字的 HTML"）：agent 仍然去做编辑型 Hero → 工作流 → 价值证据那一整套，还自行判断
   "现有文件已经对应目标，我在它上面精修而不是另造新文件"，最终**一个文件都没有按要求生成**。
   **不要用"加 plugin 参数"当成陷阱一的修复手段**——这是本次侦察里两个连续的错误归因之一（先
   猜"没落盘是因为没带 plugin"，再猜"带 plugin 就能修"，都被实测推翻），加了 plugin 换来的是
   完全不同、且更难预期的另一种失败。

**验收纪律**：核对产物必须扫**整个项目目录树**，不能只看 brief 里点名的那个子目录（如
`pages/`）——陷阱一的三个文件正是因为只查了 `pages/` 才被漏掉、误判成"什么都没生成"。brief 里
应显式写「不在项目根目录创建任何文件」，即便这样写了也要在事后核对，不能假设 agent 会遵守。

**结论**：`POST /api/runs` 是有价值的备用通路（MCP 完全不可用时，至少还能让 OD 的 agent 按大致
方向干活），但代价是产物落点不受控、且不能靠加 `plugin` 参数收窄行为——上层技能/流程用它时必须
预期这两条，并要求逐文件核对而不是只信任退出码或 agent 自己的文字汇报。

#### 客户报「打开应用看不到项目了，只能重启」

这是桌面版的已知形态，不是数据丢失。根因是 **UI 与 daemon 是独立进程**：daemon 挂掉或换端口后 UI 仍然活着，于是界面能打开、项目列表却空白（代理还在往已死的旧端口转发，返回 `ECONNREFUSED`）。

诊断与处置：

1. 先按上面的命令探测是否还有活着的 daemon API；没有就是 daemon 掉了。
2. 数据都在磁盘上，**重启 App 即可**，不要试图修复或迁移数据。
3. 检查 `<data>/projects/` 下有没有 0 字节的孤儿目录——那是 daemon 在建项目途中崩溃的残骸
   （目录建了、`app.sqlite` 没写入）。确认为空后可以删。
4. 日志在 `<namespace>/logs/{daemon,desktop,launcher}/`；`launcher/after-quit.log` 反复出现
   `desktop.sock ENOENT` 属于正常的启动时序，不是故障根因。

**因此：任何要长期留存的设计资产都必须有一份在客户自己的 git 仓库里**，桌面版目录只当镜像。

#### 桌面版的项目元数据（HTTP API 之外的必修课）

`app.sqlite` 的 `projects` 表**没有文件清单、也没有 `entryFile` 字段**——文件从磁盘扫描，
而 `entryFile` 埋在 `metadata_json` 里：

```json
{"kind":"prototype","entryFile":"index.html","skipDiscoveryBrief":true}
```

由此产生两个反复踩到的坑：

- `PATCH /api/projects/:id` 传 `{"entryFile":"..."}` 会返回 200，但**不会写进 metadata_json**，
  项目卡片仍是空白预览。
- 直接把文件 `rsync`/`cp` 进项目目录后，卡片同样空白——因为没有 `entryFile` 指明渲染哪个文件。

正确做法：`POST /api/projects` 建项目（`{"id","name"}`，id 必填），把文件放进
`resolvedDir`（`GET /api/projects/:id` 会返回），为每个可渲染文件补一份
`<file>.artifact.json`（照同目录已有产物的格式：`version/kind/title/entry/renderer/status/exports`），
最后确认 `metadata_json.entryFile` 指向入口文件。**改 `app.sqlite` 前先备份，并且只在 App 未在写入时改；改完需要重启 App 才会重新读取。**

#### 删除本地插件要删三处

`DELETE /api/plugins/<id>` 这个路由**不存在**（返回 404）。桌面版跑复刻类
workflow 会在项目内生成本地插件（`sourceKind: local`），删它必须同时清三处，
少一处界面就还显示：

1. 项目内的产物：`<data>/projects/<projectId>/plugin-source/<pluginId>/`
2. 插件安装目录：`<data>/plugins/<pluginId>/`
3. 注册记录：`app.sqlite` 的 `installed_plugins` 表（改前先备份）

删完仍会显示是 daemon 的内存缓存，**重启 App 才消失**。
