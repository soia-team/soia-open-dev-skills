# 设计系统包的一致性校验

> 主文件「设计系统管理与项目接入」的展开：包内自相矛盾时以谁为准，附实测证据。

### 包一致性校验（用任何设计系统之前先做）

**内置包内部会自相矛盾，不能只读 `DESIGN.md` 就动手。** 以 `warm-editorial` 为例，
实测有五处叙述与可执行文件冲突：

| DESIGN.md / USAGE.md 说 | 可执行文件实际 |
| --- | --- |
| accent `#C0512F` | `tokens.css` 是 `#9b5b32` |
| 次强调 forest `#2F5B4F` | `tokens.css` 里**不存在这个令牌** |
| 卡片无阴影 | `components.html` 的 `.panel` 带 `--elev-raised` |
| 输入框只要下划线 | `input` 有 1px 边框 + `--radius-sm` 圆角 |
| 禁止渐变 | `.page` 是 135° 三色 `linear-gradient` |

**优先级（冲突时照此裁决）**：

```
tokens.css  >  components.html  >  DESIGN.md / USAGE.md
```

理由是 `USAGE.md` 自己规定的读取顺序就把 `tokens.css` 定位为「粘进第一个
`<style>` 块」的执行真源，`components.html` 定位为「精确选择器与状态」，
`DESIGN.md` 只是视觉意图散文。散文和令牌打架时，按令牌走。

内置包在 App 里，不在项目目录。0.18.1 起可执行文件路径是动态的（见
[desktop-app.md](desktop-app.md)「launcher 版本化路径」），`/Applications/Open Design.app`
可能落后于真正在跑的版本——取 `resolve_launcher_payload()["app_bundle"]` 而不是硬编码：

```bash
APP_BUNDLE=$(python3 -c "
import sys; sys.path.insert(0, 'scripts')
import desktop_ctl
print(desktop_ctl.resolve_launcher_payload()['app_bundle'])
")
ls "$APP_BUNDLE/Contents/Resources/open-design/design-systems/<id>/"
# DESIGN.md  tokens.css  components.html  components.manifest.json  USAGE.md  …
```

（本机实测 0.18.0 与 0.18.1 两个版本目录下的 `warm-editorial/tokens.css` 逐字节一致，
未发现内容漂移，但两者本质是不同版本，不保证永远一致，仍应动态取。）

用 HTTP API 拿元信息和 `DESIGN.md` 正文（`.body` 字段）：

```bash
curl -s "http://127.0.0.1:<port>/api/design-systems"                    # 列全部
curl -s "http://127.0.0.1:<port>/api/design-systems/<id>?include=files" # 含 body
```

挂到项目：

```bash
curl -s -X PATCH "http://127.0.0.1:<port>/api/projects/<projectId>" \
  -H 'content-type: application/json' -d '{"designSystemId":"<id>"}'
```

挂载成功后 `start_run` 的返回里会带 `designSystemId` 与
`designSystemSelectionSource: "project"`，以此确认真的生效。

另外两条硬约束，来自 `USAGE.md` 且必须转达给任何生成方：

- `:root` 令牌块之外**不许出现裸 hex / rgb**，全部走 `var()`。注意
  `components.html` 自己就违反了这条（`.page` 的渐变写的是裸 hex），照抄会把问题
  带进产物——换成等值 token 即可。
- 只用 `components.manifest.json` 里 `present: true` 的组件组。`present: false`
  的（如 `warm-editorial` 的 icons、keyboard）表示这套系统**没有**该组件，不要发明。
