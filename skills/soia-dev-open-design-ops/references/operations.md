# Open Design 操作参考

这里保留 2026-08 已验证的版本与命令边界，不是最新能力承诺。命令以技能目录为工作目录；执行前先按 SKILL.md 探测实际路线，再核对当前 help/schema。本文的旧版本降级规则只适用于命中的版本，授权与安全以主入口为准。

## 环境与 daemon

> **入口判断先做一次，且必须先做**：本机可能装了三条彼此独立的路线——CLI 源码
> checkout、桌面版 App、MCP。装了哪条完全取决于客户怎么安装。
>
> ```bash
> python3 scripts/detect_route.py          # 人读
> python3 scripts/detect_route.py --json   # 机读，供上层分流
> ```
>
> 输出 `route` 为 `cli` / `desktop` / `desktop-mcp` / `none`，据此选择本节的对应小节：
>
> | route | 用哪节 | 不要做什么 |
> | --- | --- | --- |
> | `cli` | 1–2 | — |
> | `desktop` | 3 | **不要跑 `check_env.py` / `daemon_ctl.py`** |
> | `desktop-mcp` | 3 为主，4 为辅 | 同上；**MCP 能力边界按版本区分，见 4**——0.18.x 上读写既有项目走 3 的 `desktop_ctl.py`，MCP 只对它自己新建、还没绑定 workspace 的项目短暂可用；0.19.2+ 已恢复，MCP 直接可用 |
> | `none` | 按 `suggestions` 修复 | 不要硬跑任何一节 |
>
> **这一步不能省。** 只装了桌面版的机器上跑 `check_env.py` 必然返回
> `status=error`（缺 `node_24` / `pnpm_10_33` / `daemon_7456_unreachable`），
> 那是「没装 CLI 路线」的正确结论，**不是环境坏了**。把它当故障会让整条流程
> 停在一个根本不需要的前置上。

### 1. 检测环境（CLI / 源码 checkout 路线）

从本 skill 目录运行：

```bash
python3 scripts/check_env.py
```

脚本离线检查 `node`、`pnpm`、`OPEN_DESIGN_HOME` 与关键仓库文件，输出 `status`、`missing`、`checks` 和 `suggestions` JSON。Node 不是 24.x、pnpm 不是 10.33.x 时返回不兼容状态，不自动升级。

### 2. 启停与健康检查

```bash
python3 scripts/daemon_ctl.py start
python3 scripts/daemon_ctl.py status
python3 scripts/daemon_ctl.py health
python3 scripts/daemon_ctl.py stop
```

`start` 使用 upstream Quickstart 的 `pnpm tools-dev run web` 控制面，显式传 `--daemon-port`，并以 detached/nohup-style 后台进程记录 PID 与日志。不要使用已移除的 `pnpm dev`、`pnpm daemon` 或 `pnpm start` aliases。健康检查以 `GET /api/skills` 返回 `skills` 数组为准；`/api/health` 只说明进程级存活，不证明技能目录可用。

默认 URL 是 `http://127.0.0.1:7456`。只允许 loopback URL；需要远端部署、反向代理或 `0.0.0.0` 时，本技能停止并要求客户按 upstream 安全配置处理，不替客户公开本机 daemon。

### 3. 桌面版 App（与 CLI daemon 是两套，别混用）

客户装了桌面版 App 时，上面的 CLI daemon 路线基本不适用：

- **数据目录不同**：桌面版在 `~/Library/Application Support/Open Design/namespaces/<namespace>/data/`
  （`namespace` 通常是 `release-stable`），CLI 在仓库的 `.od/`。**两边互相看不见对方的项目**。
- **`od` CLI 在打包版里不进 PATH**。官方文档写 `od status`、`curl od://app/...`，但打包安装后：
  - `/usr/bin/od` 是 macOS 自带的**八进制转储工具**，直接敲 `od status` 会调错程序、报一堆无关错误；
  - `curl` 不认识 `od://` 这个 Electron 自定义 scheme，`curl -s od://app/api/health` 返回空；
  - 实测 `--daemon-url od://app` 在命令行下也解析失败（即使显式给了 `OD_SIDECAR_IPC_PATH`），
    该 scheme 目前只在 MCP sidecar 上下文里可用。
  - **可执行文件路径不能写死**（0.18.1 实测 2026-08-07）：升级到 launcher 分发后，桌面版真正在跑的
    `Open Design Helper` / `daemon-cli.mjs` 落在 `~/Library/Application Support/Open
    Design/launcher/channels/<channel>/namespaces/<namespace>/versions/<version>/payload/` 下，
    `version` 随自动升级变化；`/Applications/Open Design.app` 还在，但它是 launcher 维护的
    "OS 启动入口"，版本可能落后于真正在跑的那个（本机实测前者 0.18.0、后者 0.18.1）。旧配置
    只认 `/Applications` 固定路径，升级后会连到过期或不存在的可执行文件，表现为 daemon 看似启动了
    实则是空壳。用 `desktop_ctl.resolve_launcher_payload()` 动态解析，不要手写路径：

    ```bash
    python3 -c "
    import sys; sys.path.insert(0, 'scripts')
    import desktop_ctl, json
    print(json.dumps(desktop_ctl.resolve_launcher_payload(), indent=2))
    "
    ```

  打包版的 `od` 等价调用（实测可用，`$HELPER`/`$CLI` 取上面命令的 `helper`/`daemon_cli` 字段）：

  ```bash
  od(){ ELECTRON_RUN_AS_NODE=1 "$HELPER" "$CLI" "$@"; }
  ```

  **它默认打 `http://127.0.0.1:7456`（CLI daemon 的端口），对桌面版无效**，
  所以每条命令都要显式带 `--daemon-url http://127.0.0.1:<探测到的端口>`。

- **端口每次启动都变，且没有默认值；同一台机器上可能同时活着不止一个 daemon 端口**
  （本机实测两个 daemon 各自独立、互不同步，另有一个 Next.js UI 端口）。判活标准
  0.18.1 起是 `GET /api/health` 返回 `{"ok":true,"version":"..."}`——**不能再用
  `/api/projects` 的返回形状判断**，见下一条。已脚本化，优先用它，不要每次手敲：

  ```bash
  python3 scripts/desktop_ctl.py detect      # 活着的 daemon API 端口（可能不止一个）
  python3 scripts/desktop_ctl.py projects    # 列项目，并标出谁缺 entryFile
  python3 scripts/desktop_ctl.py doctor      # 「看不到项目」一键体检
  ```

  `desktop_ctl.py` 是**只读诊断**：不改客户数据、不重启 App、不打印凭据；
  daemon 不可达时以非零退出码和明确 hint 收场，不假装正常。
- **workspace 上下文门**（0.18.1 新增，实测 2026-08-07）：`GET /api/projects`（不带 id）不再报错，
  但只返回**从未绑定过 workspace** 的项目——桌面版创建的项目基本都已绑定，所以这条老接口长期
  回空数组是**正常现象，不是 daemon 坏了或客户没有项目**。已绑定项目要用
  `GET /api/workspaces/<workspaceId>/projects` 或 `GET /api/projects/<id>`，且必须带
  `x-od-workspace-id` / `x-od-workspace-member-id` header，否则 400 `WORKSPACE_CONTEXT_REQUIRED`。
  本机单用户、从未登录云端账户的场景一样要带——这两个值不是凭据，是本机生成的 workspace/member id，
  daemon 默认直接信任 header 自证的身份。`desktop_ctl.py` 已经自动处理（`resolve_workspace_identity()`
  只读查 `app.sqlite` 推导这两个值），上面三个子命令不需要额外操作；只有自己手写 HTTP 调用时才需要
  关心这一段——完整机制、根因与实测证据见 [references/desktop-app.md](desktop-app.md)。
- **桌面版启动会接管并停掉 CLI daemon**，所以两者不能同时用。

打包版 `od` 的等价调用、项目元数据（`entryFile` 与 `.artifact.json`）、「看不到项目」的诊断、
workspace 上下文门的完整机制与实测证据、删除本地插件要清的三处——见
[references/desktop-app.md](desktop-app.md)。

### 4. MCP 路线（0.19.2 起恢复为首选；0.18.x 仍按历史边界降级）

桌面版把自己暴露成一个 MCP server，`tools/list` 实测 22 个工具（`list_projects`、
`get_project`、`get_file`、`list_files`、`search_files`、`get_artifact`、`create_project`、
`create_artifact`、`write_file`、`delete_file`、`delete_project`、`list_skills`、`list_plugins`、
`list_agents`、`start_run`、`get_run`、`cancel_run`、`get_active_context`、`collect_brief`、
`confirm_brief`、`start_vela_login`、`get_vela_login_status`，完整签名见
[references/mcp-hosts.md](mcp-hosts.md)）。

**能力边界按 daemon 版本二选一，判据用 `detect_route.py` 里 `routes.mcp.evidence.workspace_gap`
（源自活着的 daemon `/api/health` 的 `version`），不要凭安装时间猜：**

| 能力（已绑定 workspace 的项目） | 0.18.x | 0.19.2+ |
| --- | --- | --- |
| `list_projects`/`get_project`/`get_file`/`start_run` 等 | 不可用：空数组或 `WORKSPACE_CONTEXT_REQUIRED`（sidecar 不传 workspace header，上游限制） | **恢复**（2026-08-18 实测，stdio 直连 + Claude Code 长连接双路径验证）：返回真实数据；`start_run` 的 `runId`/`pluginId`/`appliedPluginSnapshotId` 与会话早期成功 run 一致 |
| 读写既有项目首选通路 | `desktop_ctl.py`/HTTP（带 workspace header） | MCP 直接可用；`desktop_ctl.py` 仍可作跨 agent 备选 |
| 派新生成任务首选通路 | 客户在 App 界面手动发起 | MCP `start_run` 直接可用 |

**只验证了 stdio 直连与 Claude Code 长连接这两条路径**——codex/opencode/pi/cursor/workbuddy 在
0.19.2 上未重新实测，[references/mcp-hosts.md](mcp-hosts.md)「实测矩阵」仍是 0.18.1
时期结果，升级后按矩阵旁的验证命令重跑确认，不要直接沿用。0.18.x 完整根因、原有降级分工
（`desktop_ctl.py` 读写 + 客户手动发起生成）——见 [references/mcp-hosts.md](mcp-hosts.md)
「0.18.x 能力边界」一节。

MCP 之外还有一条 HTTP `POST /api/runs` 派活通路，仅在 MCP 不可用（0.18.x）时作为应急，代价见
[references/desktop-app.md](desktop-app.md)「`POST /api/runs`」一节——产物落点不受控，
带 `plugin` 参数时插件自带的种子指令还会压过 prompt；能用 MCP 就不要用它。

完整实测记录（多环境变量组合、raw stdio JSON-RPC 会话、四条独立复现路径的原始输出）、旧版本
（v0.13.0）仍成立的三条硬约束（prompt 需内联 `tokens.css`、`toolBundle.mcpServers` 默认为空、
实时进度只在磁盘 `events.jsonl`）——见 [references/mcp-hosts.md](mcp-hosts.md)。

### 5. 把设计同步回客户代码仓

桌面版的数据目录随时可能因重装、换机或 daemon 故障而看不到，**任何要长期留存的
设计资产都必须有一份在客户自己的 git 仓库里**。更要紧的是：设计稿与生产实现会
各自漂移而没人发现——稿里 10px、实现里 13px，两边单看都不像错。

```bash
# 归档：OD 的 pages/ specs/ index.html → <repo>/docs/design/（默认预览）
python3 scripts/od_sync.py --project <id> --repo <repo-root> --archive
python3 scripts/od_sync.py --project <id> --repo <repo-root> --archive --apply

# 核对：稿 vs 实现的 :root 令牌漂移、:root 外裸色值、可选红线
python3 scripts/od_sync.py --project <id> --repo <repo-root> --check \
  --design pages/<page>.html --impl <path-in-repo> [--redlines <file>]
```

`--check` 有漂移即非零退出，可挂进 CI。

**红线扫描必须剥离注释，且只报上下文不下结论。** 写得好的代码库会在注释里写明
纪律（「绝不做完成率排名」「不显示倒计时」），不剥离注释就会把**遵守的证据**
当成违规报出来——实测某单文件应用 5 类命中里 4 类是注释；剥离后剩 2 类，其中
一类还是视频文件名。所以扫描器输出上下文供人工判定，不直接判违规。

### 6. 一个产品只开一个设计项目

不要每做一个页面就新建一个 Open Design 项目——散成一堆之后，客户改任何一页都要先想「这是哪个项目」。

推荐结构（一个项目，文件名与线上路由一一对应）：

```
<project>/
├── index.html            入口：全路由对照表，标明哪些有稿、哪些待设计
├── pages/<route>.html    每个线上路由一个页面稿
└── specs/*.md            分层设计规范（基础体系 + 各页专项）
```

新页面通过在**同一个项目**里跑 run 生成，产出落进 `pages/`，再到 `index.html` 里把它从
「待设计」挪到「已有设计稿」。旧项目只在资产已核验迁移且客户明确批准删除目标后处理；否则保留原件。

**`od run start/watch/info` 在 0.18.1 打包版里已下线**（`daemon-cli.mjs --help` 实测确认，
2026-08-07；CLI 源码 checkout 路线是否仍有这三个子命令取决于 checkout 的版本，未验证）。**这个
"对既有项目全自动触发新生成"的缺口，0.19.2 起已经由 MCP `start_run` 补上**（见上一节「4. MCP
路线」，对已绑定项目直接可用，优先用它，不用再走下面这条 `od chat new` 迂回路径）。以下是 0.18.1
实测结论——机器仍停在 0.18.x、或需要脱离 MCP 单用 `od` CLI 时仍然适用，已验证与未验证的现状：

- **建会话本身已验证可行**：`od chat new --project <projectId> --workspace <wsId>
  --workspace-member <memberId> --daemon-url "$DAEMON_URL" --json` 对已绑定项目返回
  200 和真实 `conversation.id`（`wsId`/`memberId` 取 `desktop_ctl.resolve_workspace_identity()`）。
- **建会话之后怎么触发一次真正的生成，本次侦察未验证**，不写成可用命令。`od automation
  create --target reuse=<projectId>` 实测**不支持** workspace 参数，对已绑定项目直接 403
  `WORKSPACE_ACCESS_DENIED`，不是可用替代。
- **当前唯一确定可靠的方式：客户在 App 界面里手动发起本轮生成。** 新会话建好后，把
  `studioUrl`（`get_project`/`get_run` 的返回里都有，形如
  `http://127.0.0.1:<port>/projects/<id>/conversations/<cid>`）发给客户，请客户点开并在
  界面里发出 brief；agent 侧不要假装能替客户点这一下。
- 排查已发起的 run 仍然看 `<data>/runs/<runId>/events.jsonl`：agent 的文字输出在
  `data.type=="text"` 的事件里，`get_run(runId)`（MCP，只按 id 查、不经过项目名解析，
  不受上面的 workspace 门影响）现在还会带 `studioUrl`、`agentMessage`、`executionDiagnostics`
  等字段，比 v0.13.0 更丰富。

**run 活不过 daemon 重启**：桌面版 daemon 掉线或重启后，进行中的 run 会连同记录一起消失
（`get_run` 返回 `NOT_FOUND`），且不留产物。所以长 run 期间不要重启 App；
真的重启了就按上面的方式重新建会话、请客户重新发起，不要花时间找回原来那个 runId。

## 设计系统管理与项目接入

### Design System Project 三件套

新建或维护正式 Open Design Design System Project 时，以 upstream `_schema` 为源，最低契约为：

```text
<design-system-slug>/
├── manifest.json
├── DESIGN.md
└── tokens.css
```

- `manifest.json` 使用 `od-design-system-project/v1`，folder slug 与 manifest id 一致。
- `DESIGN.md` 是给 agent 的 canonical design prose；`tokens.css` 是 canonical compiled semantic tokens。
- 新系统不得把 `DESIGN.md`-only 当 authoring target。rich package 的可选文件与 token 约束以 upstream `docs/design-systems.md`、`design-systems/_schema/AGENTS.md` 和 TypeScript schema 为准。

### 包一致性校验

**内置包会自相矛盾，不能只读 `DESIGN.md` 就动手。** 冲突时的裁决优先级：

```
tokens.css  >  components.html  >  DESIGN.md / USAGE.md
```

实测证据（`warm-editorial` 的五处冲突）、内置包在磁盘上的位置、挂载与校验命令——见
[references/design-systems.md](design-systems.md)。

### 用户项目的 `DESIGN.md`-only 兼容接入

现有项目可先把设计规则放在 `<user-project>/DESIGN.md`。daemon 对已注册的 legacy/user-installed 目录保留 `DESIGN.md`-only discovery，但这是兼容 fallback。项目接入优先走 CLI/App 的 local import，让 daemon 扫描并建立可编辑设计系统：

```bash
node <open-design-root>/apps/daemon/dist/cli.js design-systems import-local <user-project> --name "<project-name>" --json
node <open-design-root>/apps/daemon/dist/cli.js design-systems list --json
```

首次实例可把某个真实产品项目的 `<product-project>/DESIGN.md` 配到私有 `OPEN_DESIGN_PROJECT_DESIGN_MD`，再以 `<product-project>` 执行 `import-local`；不要复制或写死维护者路径。若 `dist/cli.js` 不存在，先在 checkout 中运行 `pnpm --filter @open-design/daemon build`。

常用管理命令以 `od design-systems help` 的实际输出为准；v0.13.0 已有 list/show/rename/download/import-local/import-github/import-shadcn。rename、delete、覆盖导入或 token rebuild 影响持久状态，先展示目标与现状再确认。

## 目录查询

### Functional skills

```bash
python3 scripts/list_skills.py
python3 scripts/list_skills.py --category slides
```

脚本调用 daemon `GET /api/skills`，输出 `name`、`description`、`od.mode` 与 category；`--category` 是对 API 返回结果做本地精确过滤，因为该路由本身没有 server-side category query。

### Rendering templates

渲染模板由 `GET /api/design-templates` 与 checkout 的 `design-templates/` 提供，不属于 `/api/skills`。需要模板时用 App 的 New Project “Start from” rail 或直接查询该 API；不要用 `list_skills.py` 假装覆盖模板目录。

Deck 先在三类入口中选一类，再交给上层流程做设计决定：

- `simple-deck`：design-system 驱动、单文件、约束明确的水平 deck；
- `guizang-ppt`：电子杂志/WebGL 系，包含 Monocle、WIRED、Kinfolk、Domus、Lab 五个方向；
- `html-ppt`：HTML PPT Studio 系，提供 full-deck、theme、layout、animation 与 presenter runtime 目录。

## 渲染与导出

### 提交渲染任务

1. 在 App 选择 runtime、design template 与 design system，提交 prompt；filesystem-capable runtime 写 canonical project files，text-only/BYOK runtime 返回完整 `<artifact>`。
2. 从 App 打开项目并验证预览；或让 daemon-spawned agent 使用注入的 `OD_BIN`、`OD_DAEMON_URL`、`OD_PROJECT_ID`、`OD_PROJECT_DIR`。
3. 不直接 POST 未文档化的 chat/run payload。自动化优先使用已构建的 `od` CLI；App-only 交互由 agent 按 upstream 文档驱动。

### HTML

HTML 是 project 中的 canonical artifact。用 App Download → HTML，或读取/复制项目内源文件。v0.13.0 的 `od export` 没有 `--format html`，不得伪造该格式；项目文件 API/route 仅在确有 project id 与路径时使用。

### PDF 与 PPTX

构建 daemon CLI 后，可用 upstream v0.13.0 的稳定命令：

```bash
node <open-design-root>/apps/daemon/dist/cli.js export <project-file.html> \
  --project <project-id> --format pdf --out <output.pdf>
node <open-design-root>/apps/daemon/dist/cli.js export <deck.html> \
  --project <project-id> --format pptx --out <output.pptx>
```

内置 PPTX 是一页一张截图，适合像素保真交付，不是可编辑 shape/text deck。可编辑 PPTX 推荐链：

1. 以 HTML deck 为视觉真相源；
2. 调 functional skill `pptx-generator` 生成可编辑 `.pptx`；
3. 调 `pptx-html-fidelity-audit` 比较 HTML/PPTX，修 footer overflow、裁切、字体/italic 与节奏漂移；
4. 打开最终 PPTX，核对页数、画幅、关键文本与无越界。

### MP4

MP4 使用 HyperFrames HTML 渲染器，不冒充通用视频导出：

```bash
node <open-design-root>/apps/daemon/dist/cli.js media generate \
  --surface video --model hyperframes-html \
  --project <project-id> --composition-dir <project-relative-composition-dir> \
  --output <output.mp4>
```

composition 目录必须包含 upstream 要求的 `hyperframes.json`/`meta.json`/`index.html`。daemon 实际驱动 `npx hyperframes render`；任务排队后按 CLI 返回的 task id 使用 `od media wait`，最后验证文件存在、MIME、时长与可播放性。

## 会话 resume（v0.13.0）

Native resume 由 daemon 自动完成，不是用户手工 `od resume`：

1. 重新打开原 project 与原 conversation，不新建会话；
2. 发送 follow-up turn；
3. daemon 对支持的 runtime 复用已捕获的 native session id，使 Codex、OpenCode、Pi 与 Open Design Cloud 等 v0.13.0 支持项跨 turn 延续；
4. 检查 run 结果与 touched files，确认不是 cold start。

如果 session handle 过期、runtime 不支持或 CLI 拒绝 resume，明确报告是“resume unavailable/expired”，再由客户决定是否以历史消息重建上下文；不得把重建冒充原生 resume。daemon 重启后仍以实际 conversation/run metadata 为证据。

## 私有配置命令包装器

需要显式加载 config 执行受控 upstream 命令时：

```bash
python3 scripts/run_with_env.py -- pnpm tools-dev status
python3 scripts/run_with_env.py -- pnpm --filter @open-design/daemon build
```

包装器只允许 Corepack/pnpm 的已知 Open Design 生命周期与 build/install/version 形态；拒绝 shell、`env`、`printenv`、任意 executable 和 pnpm exec/dlx。不得用 `set -x`，不得打印 env 值。
