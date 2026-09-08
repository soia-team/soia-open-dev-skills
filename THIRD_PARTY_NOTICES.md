# THIRD_PARTY_NOTICES

> Last updated: 2026-09-08
> License values are metadata snapshots. Recheck the upstream source before reuse.

## Managed external CLIs

| Upstream | License snapshot | Used by | Relationship |
|---|---|---|---|
| [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) | Apache-2.0 | `soia-dev-agent-cli-dispatch` | User-installed external AI CLI that the skill can dispatch. |
| [google-antigravity/antigravity-cli](https://github.com/google-antigravity/antigravity-cli) | NOASSERTION | `soia-dev-agent-cli-dispatch` | User-installed external AI CLI (`agy`) that the skill can dispatch; no code is copied. |

The dispatcher can also invoke other user-installed AI CLIs. They are execution targets rather than dependencies distributed by this repository and are not enumerated here.

## Method references

- [HumanLayer show-me](https://github.com/humanlayer/skills/blob/main/plugins/show-me/skills/show-me/SKILL.md): smallest-useful-view approach referenced by `soia-dev-show-task-html`. The Chinese workflow is newly written; no upstream code or verbatim skill text is distributed.
- [lencx coding-protocol](https://github.com/lencx/skills/blob/b848e124111be50a795cc961558247e7751825e2/skills/coding-protocol/SKILL.md) and [Matt Pocock engineering skills](https://github.com/mattpocock/skills/tree/3cca18b368ae95cdbdebbff572ccafa662551015/skills/engineering): references for risk-based constraints, focused implementation and review. No upstream files, scripts or verbatim instructions are copied.

## Maintenance

- NOASSERTION upstreams remain external tools; do not copy their code.
- Record newly documented upstream links or install commands here.
