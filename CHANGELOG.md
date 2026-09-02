# Changelog

本文件由 soia-meta-skill-release 在每次正式发版时自动更新，与 GitHub Release 同源；
更早的版本演进见 git 提交历史与 GitHub Releases。

## v1.11.0 — 2026-09-02

dispatch 技能适配 2026-09-02 Claude 模型体系：Fable 5.1/Opus 5 目录、fallback/辅助模型/unrecognized 解析、Independence Gate、模型探测脚本

## 新增
- feat(dispatch): adapt claude model handling to the 2026-09-02 CLI reality (#67)

## 维护
- chore(release): promote train to 1.11.0-SNAPSHOT (feat in dev) (#68)
- chore(release): open next train after v1.10.0 (#66)

## v1.10.0 — 2026-08-31

dispatch 技能:vision-exp low 档 Pi 实测证据入档、DSH 诊断试点合格记录、codex 沙箱禁监听边界登记;技能 1.4.0

## 新增
- feat(dispatch): record pi vision-exp low smoke and codex sandbox listen limits

## 维护
- chore(dispatch): bump skill to 1.4.0 and open 1.10.0 train
- docs(dispatch): record dsh vision-exp diagnosis trial evidence
- chore(release): open next train after v1.9.3 (#64)

## v1.9.3 — 2026-08-28

Add truthful DeepSeek V4 Flash Vision dispatch metadata and unverified routing gates.

## 新增
- feat(dispatch): register DeepSeek vision model (#62)

## 维护
- chore(release): open next train after v1.9.2 (#61)

## v1.9.2 — 2026-08-21

dispatch 技能 1.3.5：修正 dsh patch/settings 优先级错误断言、pi 中文×工具死循环入册、派发端点验证纪律

## 修复
- fix(agent-cli-dispatch): 修正 dsh patch/settings 优先级错误断言+pi 中文×工具死循环入册（1.3.5）

## 维护
- chore(release): open next train after v1.9.1 (#59)

## v1.9.1 — 2026-08-20

agent-cli-dispatch：dsh 补 settings.yaml 持久化与 NO_ADAPTER 诊断、历史会话触发陷阱、模型身份验证阶梯

## 维护
- docs(agent-cli-dispatch): dsh 补 settings.yaml 持久化/NO_ADAPTER 诊断、会话触发陷阱、身份验证阶梯（1.3.4）
- chore(release): open next train after v1.9.0 (#57)

## v1.9.0 — 2026-08-20

dispatch claude code 调用默认 auto + dsh 执行器支持

## 新增
- feat(agent-cli-dispatch): claude code 调用默认 --permission-mode auto (1.3.3) (#55)
- feat(agent-cli-dispatch): 支持 dsh 执行器并沉淀本地端点派发纪律

## 维护
- chore(train): dev 含 feat（dsh 执行器 + claude permission auto），列车提为 minor
- chore(release): open next train after release

## v1.8.0 — 2026-08-06

agent-cli-dispatch pi 运行时与执行器能力矩阵、渐进式披露重构、私密数据章节收口

## 新增
- feat(dispatch): pi runtime support, progressive disclosure and executor capabilities (#47)
- feat(dispatch): add pi (pi-coding-agent) executor support (#40)

## 修复
- fix(skills): 8 个技能补齐 description 触发词，符合 SKILL_SPEC 路由契约 (#50)
- fix(metadata): real timestamps from git history (was 00:00:00) (#46)

## 维护
- chore(release): feat 在列,版本列车提为 next-minor
- chore(skills): 补上安装章节改动遗漏的版本 bump (#52)
- docs(skills): 安装章节补齐三个一等宿主 (#51)
- docs(agents): branch off main; releases fast-forward dev onto main (#49)
- chore(skills): close private data handling warnings (#48)
- chore(release): switch dev train to patch level (#44)
- chore(release): open next train after v1.7.0 (#43)
- release: finalize v1.7.0 (drop -SNAPSHOT) (#41)
- docs(changelog): seed with current release baseline (#39)
- docs(agents): dev-branch integration workflow (#38)
- chore(release): open dev branch — audit on dev, version train 1.7.0-SNAPSHOT

## v1.7.0 — 2026-08-03

dispatch 新增 pi (pi-coding-agent) 执行器支持

## 新增
- feat(dispatch): add pi (pi-coding-agent) executor support (#40)

## 维护
- docs(changelog): seed with current release baseline (#39)
- docs(agents): dev-branch integration workflow (#38)
- chore(release): open dev branch — audit on dev, version train 1.7.0-SNAPSHOT

## v1.6.0 — 2026-08-01

工程协议、代码审查、缺陷修复、任务执行与终端操作。
