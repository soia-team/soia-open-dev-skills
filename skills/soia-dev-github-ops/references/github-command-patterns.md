# GitHub 命令模式

只在需要当前操作的命令示例时读取；授权和安全门以 SKILL.md 为准。以下命令不是执行授权，删除分支不随合并自动发生。

## Query Patterns

Prefer `--json` and `--jq` for agent-readable output.

```bash
# Auth and repo sanity checks
gh auth status
gh repo view --json nameWithOwner,defaultBranchRef,isPrivate

# Open PRs
gh pr list --repo <owner>/<repo> --state open \
  --json number,title,state,author,headRefName,baseRefName,updatedAt

# Single PR status
gh pr view <number> --repo <owner>/<repo> \
  --json number,title,state,mergeable,mergeStateStatus,reviewDecision,headRefName,baseRefName

# PR checks
gh pr checks <number> --repo <owner>/<repo> \
  --json name,state,bucket,startedAt,completedAt,link

# Issues
gh issue list --repo <owner>/<repo> --state open \
  --json number,title,state,labels,assignees,updatedAt

# Workflow runs
gh run list --repo <owner>/<repo> --limit 20 \
  --json databaseId,status,conclusion,workflowName,headBranch,createdAt,url
```

When reporting results, include:

- repo: `<owner>/<repo>`
- object: PR / issue / run / release
- identifier: number, run id, or tag
- status: open / closed / merged / passing / failing / cancelled
- next action or blocker

## PR Lifecycle

Create PRs with a concise body containing summary and verification evidence.

```bash
gh pr create --repo <owner>/<repo> \
  --base <base-branch> \
  --head <feature-branch> \
  --title "<type>: <short change>" \
  --body "$(cat <<'EOF'
## Summary
- <what changed>

## Verification
- <command>: <result>
EOF
)"
```

Review operations:

```bash
gh pr review <number> --repo <owner>/<repo> --approve --body "<review note>"
gh pr review <number> --repo <owner>/<repo> --request-changes --body "<required changes>"
gh pr comment <number> --repo <owner>/<repo> --body "<comment>"
```

Before merge:

```bash
gh pr view <number> --repo <owner>/<repo> \
  --json mergeable,mergeStateStatus,reviewDecision,statusCheckRollup \
  --jq '{mergeable, mergeStateStatus, reviewDecision, checks: .statusCheckRollup}'
```

Only merge within the current explicitly approved plan; select the merge method required by the repository:

```bash
gh pr merge <number> --repo <owner>/<repo> --squash
```

## CI Failure Triage

Use this order:

1. Identify the failing run and job.
2. Read the first actionable error in the failed log.
3. Classify the failure.
4. Reproduce locally only if the repo has enough context and the command is safe.
5. Report the exact failing command, file, or external blocker.

```bash
gh run view <run-id> --repo <owner>/<repo> --json status,conclusion,workflowName,jobs,url
gh run view <run-id> --repo <owner>/<repo> --log-failed
```

Common classes:

| Class | Signal | Next step |
|---|---|---|
| Compile | compiler, typecheck, or lint error | Read the first error and map to file/line |
| Test | assertion failure or failing test name | Reproduce that test locally if possible |
| Environment | missing tool, package, or cache | Check setup steps and runner image |
| Permission | `Resource not accessible` or denied secret | Check workflow permissions and fork context |
| Quota/timeout | quota message or cancelled after timeout | Report external limit or split work |

## Release Operations

Release creation is a publish action. Confirm the tag/name/body against the current approved publishing plan; ask only when that authorization is missing or the target/impact changes:

```bash
gh release create <tag> --repo <owner>/<repo> \
  --title "<release title>" \
  --notes-file <notes-file>
```

After release, verify:

```bash
gh release view <tag> --repo <owner>/<repo> \
  --json tagName,name,isDraft,isPrerelease,publishedAt,url
```
