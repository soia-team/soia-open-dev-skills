# 可选结构化生成器

只有已有 JSON、批量生成或客户明确要固定看板时读取；不是默认展示流程。

1. 读取[输入契约](input-schema.md)选择已有字段；代码关系核对实际实现，进度只需任务状态和已有证据。需要选代码审查区块时读[视图参考](code-review-views.md)。
2. 运行脚本；默认写系统临时目录。客户指定交付路径时传 `--output`，已确认覆盖时才传 `--force`。
3. 验收真实输出：内容、引用、转义、离线资源和宽窄屏布局；不要只看退出码。

```bash
python3 <skill-dir>/scripts/show_task_html.py --selftest
python3 <skill-dir>/scripts/show_task_html.py --input <input.json> --view <auto|progress|overview|call_chain|data_flow|boundary|conformance|full>
```

生成器只渲染输入，不扫描仓库、不验证引用、不联网。完整 fixture 在 `examples/task.json`。生成器首次使用、升级或修改后运行 selftest；已有同版本证据不重复跑。

这些 schema/视图约束只属于生成器，不能反向要求普通对话或手写 HTML 填写全部字段。回执只给结果位置与会影响使用的缺口，不要求 scope/view 和分类计数报告。
