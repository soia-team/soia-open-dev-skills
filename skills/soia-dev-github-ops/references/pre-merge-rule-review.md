# Pre-Merge Rule Review


Use for: "审核下这个 PR 该不该合" / "这个 PR 符不符合规则，帮我看看" / a bare PR
list URL the user wants reviewed / "review 一下 `<repo>` 的 pull/`<n>`".

The output of this procedure is advice, not a merge trigger. The user
reviews the findings and decides. A request to review is not a request to
merge — this holds even if the same message also pre-authorizes merging
("review PR 42, merge it if it's fine"). Pre-authorization is conditional on
findings the user has not seen yet, so it cannot substitute for the
confirmation Safety Model requires before `gh pr merge`. Always post the
graded findings from Step 4 first, then treat the next message as the actual
merge confirmation — never merge in the same turn the report is produced.

### Step 0 — Resolve which PR

If the user gave a PR list URL or repo without a specific number, list the
open PRs first and ask which one to review — do not guess:

```bash
gh pr list --repo <owner>/<repo> --state open \
  --json number,title,author,updatedAt
```

### Step 1 — Pull the facts (read-only, no confirmation needed)

```bash
gh pr view <number> --repo <owner>/<repo> \
  --json title,body,author,baseRefName,headRefName,state,additions,deletions,changedFiles,labels,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup

gh pr diff <number> --repo <owner>/<repo>

gh pr checks <number> --repo <owner>/<repo> --json name,state,bucket
```

### Step 2 — Find this repo's own rules (do not borrow another repo's)

These four are the common ones, but they aren't the full list for every repo —
list the actual root directory and check for any `*_SPEC.md`/`*.md` rule file
by name, not just these:

- `CLAUDE.md` / `AGENTS.md` — agent behavior conventions
- `CONTRIBUTING.md`
- `.github/PULL_REQUEST_TEMPLATE.md` — if it has a checklist, the PR body
  should address each item
- If the changed files live under a subdirectory that has its own
  `AGENTS.md`/`README.md` (common in this org's repos: "read the zone's own
  rules before touching it"), read that too

This org's skill repos in particular also carry `SKILL_SPEC.md` (skill
authoring rules — version bump discipline, frontmatter requirements),
`DATA_STORAGE_SPEC.md` (where credentials/config/cache may and may not live),
and `THIRD_PARTY_NOTICES.md` (any new adapted code or dependency must be
registered there) — check for these by name specifically when the PR's repo
is one of the `soia-*-skills` repos, since a diff that skips registering a
new third-party adaptation is a real, previously-seen failure mode here, not
a hypothetical one.

If no rule file exists, say so plainly in the final report instead of
inventing rules from memory of other repositories.

### Step 3 — Use soia-dev-review-code for the cross-check

Give `soia-dev-review-code` the fixed candidate, diff and actual project rules
from Steps 1–2. It owns the single read-only review; this procedure does not
add a second checklist, adversarial round or automatic panel.

If the skill is missing, pause this review branch and report the dependency.
Installation requires a separately confirmed scope; ordinary GitHub queries
are not blocked by a missing review skill.

### Step 4 — Report

Use `soia-dev-review-code`'s result as the body of the reply (verdict
first, findings by tier, coverage notes), plus these two additions that are
specific to this GitHub procedure and not part of the generic methodology:

- CI/mergeable status from Step 1 — report what was actually observed, don't
  re-guess it.
- Explicit handoff: "the merge decision is yours" — never follow this report
  with `gh pr merge` in the same turn, even if the original request
  pre-authorized merging; wait for the user's next message after they have
  seen the findings.
