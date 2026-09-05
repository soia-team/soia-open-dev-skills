# AGENTS.md — soia-open-dev-skills

本文件只定义本仓特有边界。通用技能契约见 `SKILL_SPEC.md`，数据落盘规则见
`DATA_STORAGE_SPEC.md`，贡献步骤见 `CONTRIBUTING.md`；不要把这些长规范复制回本文件。

## 规则适用与任务完成

- 宿主实际加载的全局规则、父目录规则与本文件共同适用；本文件补充本仓事实和边界，不把共享贡献手册的旧示例当作新的授权。遇到无法按层级消解的实质冲突，指出具体条款，仅暂停受影响动作。
- 解释、诊断或审阅只读取相关规则与证据，不自动授权修复、安装或发布；明确要求实施且范围已清楚时，完成修改、适度验证和结果交付，不只返回计划。
- 已批准范围内的常规补丁、相关只读检查和验证连续推进；只在缺少会实质改变结果的信息、重叠改动无法安全保留，或下一步超出授权时询问。已确认且目标与影响未变的计划不重复确认。
- 未提交改动属于原作者；不清理、不混入提交、不覆盖。无关脏文件不阻断可隔离工作，真实重叠只暂停冲突部分。
- 不因仓名或“完整交付”默认启动多模型、子 Agent、全生态扫描、全量安装或产品治理流程；仅在用户要求、适用项目角色规则或任务风险明确需要时采用对应流程。
- 提交、远端写入、合并、部署、发布、发送消息、权限变更、凭据操作及重要数据删除仍遵守各自授权门；本地修改完成不代表这些后续动作已获授权。
- 交付说明实际改动、验证结果、未验证项及阻塞。要求实施的任务应做到授权边界内可验证的完成；区分本次已请求但待批的剩余步骤与未请求的后续动作；未请求的发布/安装不属于本次未完成工作。

## 仓库定位

本仓发布通用 `soia-dev-*` 工程技能。技能必须能被不了解维护者机器、账号、vault
和内部 workspace 的客户独立安装与使用。SOIA 产品 proposal/board 治理不因仓名自动触发。

## 开始前

1. 检查当前分支与工作树，保留并隔离无关改动。
2. 修改技能前读取该技能完整 `SKILL.md`；只按需读取它直接链接的 reference。
3. 新增、拆分、改名或实质重构技能时读取 `SKILL_SPEC.md` 和模板。
4. 涉及 config、state、cache、temp、凭据或交付物时读取 `DATA_STORAGE_SPEC.md`。

## 本仓硬边界

- 只接受 `soia-dev-*` 技能；域归属和 4–6 段命名由 `scripts/audit_skills.py` 校验。
- 不提交真实 key、token、cookie、session、密码、账号标识、私有 `config.yml` 或 `.env`。
- 不提交维护者绝对路径、私有目录结构、家庭/健康/财务等个人上下文。
- 客户差异通过 CLI 参数、环境变量或 v2 私有配置处理：
  `~/.config/soia-skills/<skill-name>/config.yml`。
- provider 凭据留在官方登录态或系统凭据库，不复制进普通配置或日志。
- 删除重要数据、覆盖未知内容或他人改动、发送、发布、权限变更、远端写入和创建 worktree 前必须获得明确授权。已授权文件集内的常规补丁编辑不属于这里的“覆盖”；已批准的同一 worktree 路径、分支和用途不重复确认，改变目标或影响时重新确认。
- 不把外部 Agent 自报“完成”当作完成；主控必须独立验证真实产物。

## 技能目录契约

```text
skills/<skill-name>/
├── SKILL.md                    # 唯一跨宿主核心流程
├── agents/openai.yaml          # 可选 UI 元数据，不承载必需流程
├── references/                # 持久规范、机器可读能力事实
├── assets/                    # 客户复制模板、静态输入资产
├── examples/                  # 可复用且脱敏的实例
├── reports/                   # 带日期的历史测试/调研报告，不作运行时真源
└── scripts/                   # 可执行实现与校验器
```

技能根目录不要散放配置、报告或快速说明。禁止新增 per-skill README、INSTALL、
CHANGELOG、QUICK_REFERENCE、ARCHITECTURE 或 `metadata.json`。

## 真源与同步顺序

- 可执行行为：代码、schema、机器可读配置、测试。
- 稳定流程：`SKILL.md`。
- 供应商差异和说明：`references/`。
- 历史证据：`reports/`，必须标日期和证据边界。
- `skills/README.md` 是生成物，只能运行生成器更新。
- 同一可变列表只保留一份机器可读真源，Markdown 只链接和解释。

## 验证

日常修改按影响面验证；纯指令文档先核对 diff、链接和规则一致性，行为变化运行受影响测试。涉及技能行为、脚本、依赖或公共工具的提交前运行以下完整门禁；纯指令/说明文档提交不机械套用全仓测试，最终集成与 CI 必选门不因局部验证通过而省略：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/generate_skill_catalog.py --check
python3 scripts/audit_skills.py --strict
git diff --check
```

修改复杂技能的行为时还要运行其自检以及至少一个受影响的 fixture 或真实前向测试，核对输出内容而不只看退出码；真实前向测试的联网、付费和机器变更仍受授权约束，受限时报告未验证项。

通用 `quick_validate.py` 只接受 skills.sh 标准 frontmatter，当前不识别本仓强制的
`version`、时间、作者和依赖字段；它只能作辅助检查，不能替代本仓 audit，也不能为让它
通过而删除本仓字段。

## Git 与发布

- `dev` 是集成分支；功能 PR 指向 `dev`，等待 `audit` 通过后再合并。
- `main` 永远等于最新正式版，不接收 PR；定稿 PR 先进入 `dev`，之后仅由已授权的 `soia-meta-skill-release` 流程经 CI 与祖先关系校验快进到 `main`。
- 普通开发不直接 push `dev`/`main`，不在 feature PR 修改插件 `-SNAPSHOT` 版本；正式发布的快进例外见下节。
- 本地 checkout 安装只能称为“本地调试安装”；最终安装验收必须使用已推送远程仓。
- 合并、发布和客户端更新是独立动作，不因代码检查通过而自动执行。

## Git Workflow

- **Branch off `main`** (the latest formal release), then open the PR against
  `dev` and wait for the `audit` check. Verify the expected `main` → `dev`
  ancestry and actual merge conflicts; ancestry alone is not proof of a clean merge. Branch off `dev` only when your change
  genuinely builds on unreleased work, and say so in the PR body.
- `main` never receives PRs. It moves only by **fast-forward from `dev`** during
  a formal release driven by `soia-meta-skill-release`, so `main` and `dev` then
  point at the same commit. 普通开发不直接 push `main` 或 `dev`；唯一例外是已获本次发布授权、通过 CI 且祖先关系校验成立后，由发布流程快进 `dev` → `main`。
- Plugin manifests on `dev` carry a `-SNAPSHOT` version naming the next release
  target. Do not change manifest versions in feature PRs; versions move only
  during a release.
