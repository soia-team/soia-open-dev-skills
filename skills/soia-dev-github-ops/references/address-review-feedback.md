# Address Review Feedback (author side)


Use when the user is the PR *author* and hands you a review to act on: "帮我修复
这个 PR" / "把这个评审意见改了" / a PR or review URL with "按评审改一下" /
"reviewer 要我改的都改了". This is the mirror image of Pre-Merge Rule Review:
that one produces advice for a reviewer; this one consumes a reviewer's advice
and turns it into verified local fixes. Push and re-review requests require
their own authorization. It never merges — see Step 5.

### Step 0 — Resolve the PR and pull the review as findings

From a PR URL, a review URL (`.../pull/<n>#pullrequestreview-<id>`), or a bare
number, resolve `<owner>/<repo>` and `<n>`, then fetch the review text. The
review body, inline diff comments, AND plain conversation-tab comments are all
findings input — they live on three separate endpoints, so fetch all three
(a reviewer's ask typed in the conversation box is an *issue* comment, not a
PR review comment, and is easy to miss):

```bash
gh pr view <n> --repo <owner>/<repo> \
  --json number,title,headRefName,baseRefName,state,reviewDecision,url,isCrossRepository,headRepositoryOwner,maintainerCanModify
# review summaries (CHANGES_REQUESTED / COMMENTED / APPROVED), newest last:
gh api --paginate repos/<owner>/<repo>/pulls/<n>/reviews \
  --jq '.[] | {id, user: .user.login, state, body}'
# inline diff comments (file + line + body), often where the real detail is:
gh api --paginate repos/<owner>/<repo>/pulls/<n>/comments \
  --jq '.[] | {path, line, user: .user.login, body}'
# conversation-tab comments (no file/line) — a third, disjoint channel:
gh api --paginate repos/<owner>/<repo>/issues/<n>/comments \
  --jq '.[] | {user: .user.login, body}'
```

`--paginate` matters: without it `gh api` returns only the first 30 items, so a
heavily-reviewed PR would silently drop later comments. Normalize every
distinct point the reviewer raised into one finding with a stable id, severity
(take the reviewer's tier if given), file:line, and the quoted ask. If a review
URL was given, prioritize that specific review's body; still scan the other two
channels, since detail and follow-up asks land there too.

### Step 1 — Get onto the PR branch (do not fix on the wrong branch)

Precondition: you must be inside a local clone of `<owner>/<repo>` — `gh pr
checkout` checks out into the current repo, it does not clone. If cwd is not a
clone of that repo, `cd` into one or clone it first; running `gh pr checkout`
from an unrelated repo silently checks the PR out against the wrong remote.

```bash
gh pr checkout <n> --repo <owner>/<repo>
git status -sb   # confirm you are on <headRefName>, clean tree
```

If the PR head is on a fork you cannot push to (`isCrossRepository: true` and
`maintainerCanModify: false` when you are not the fork owner), stop and say so
— the fix would have nowhere to go. If the local tree is dirty, stop and
surface it rather than fixing on top of unrelated uncommitted work.

### Step 2 — Use soia-dev-implement-task for the findings

Pass the normalized findings, confirmed branch and authorized scope to
`soia-dev-implement-task`'s findings branch. It owns diagnosis, fix/reject/defer,
minimal edits and focused verification; do not repeat its workflow here.
If missing, pause this branch and report the dependency, without automatic
installation or an all-host install command.

A reviewer finding is a claim, not a verdict: implementation may legitimately
`reject` one with evidence or `defer` it with a tracked follow-up. Do not
silently skip any — every point the reviewer raised must end with a fix,
reject, or defer that you can show.

### Step 3 — Optional self-review before pushing

Use the implementation's focused checks and final diff verification. Only
run `soia-dev-review-code` when the user or project explicitly requires it;
do not reopen a panel or adversarial cycle because fixes were made.

### Step 4 — Push back to the PR branch

Commit with a message that references which review points it addresses, then
push — this updates the existing PR, never opens a new one:

```bash
git push
```

Use a bare `git push`, not `git push origin <headRefName>`: after `gh pr
checkout` the branch is already configured to track the correct remote
(the fork for a cross-repo PR, `origin` for a same-repo PR), and `git push
origin ...` would push to the wrong repo for a fork PR — silently creating a
stray branch on the base repo without updating the PR. Pushing to an open PR's
branch is an externally visible update to shared work, so confirm the diff with
the user before pushing if they haven't already told you to push in this
exchange.

### Step 5 — Request re-review, do NOT merge

The author does not merge their own PR that a reviewer marked
`CHANGES_REQUESTED` — that bypasses the exact gate the reviewer just raised.
After pushing, re-request review or post a comment only when authorized:

```bash
gh pr edit <n> --repo <owner>/<repo> --add-reviewer <reviewer-login>
# or leave a comment summarizing what was addressed:
gh pr comment <n> --repo <owner>/<repo> --body "<per-finding: fixed / rejected+why / deferred+where>"
```

Report: implementation results (each finding → fixed/rejected/deferred with
evidence), whether pushing was authorized and completed, and whether re-review
was requested. Do not claim an unperformed remote action. State
explicitly that merging is the reviewer's call, not this procedure's — even if
the author has write/admin permission and could merge. Only merge if the user,
in a later message after seeing this report, explicitly says to.
