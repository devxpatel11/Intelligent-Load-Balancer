# Contribution and merge workflow

This project uses task branches, isolated worktrees, frozen contracts, path ownership, and sequential reviewed merges. The goal is to prevent two people from editing the same shared file and to make dependency order explicit.

## Start a task

From the primary checkout:

```powershell
git switch main
git pull --ff-only
git worktree add ..\ThermoSched-A1 -b feature/A1-protocol-selectors main
```

Use the matching task ID and a short description. Member B uses the same pattern, for example `feature/B1-backend`. Never reuse a worktree for another active task.

## During a task

1. Stay inside the ownership boundaries in `AGENTS.md`.
2. Treat `docs/protocol.md`, `docs/contracts.md`, and `docs/metrics.md` as read-only unless the task is an agreed contract-change PR.
3. Member B does not edit `README.md`; write `docs/readme-notes/Bn.md` instead.
4. Commit only relevant files and inspect `git diff --check`, `git diff`, and `git status` before review.
5. Record exact test commands and actual output in the task note. Do not write “tests pass” without evidence.

## Update before review

```powershell
git fetch origin
git merge origin/main
python scripts/verify.py
```

Run the task's relevant unit/integration checks after the merge. If the branch has never been pushed or reviewed, a local rebase is acceptable. Once review begins, merge `origin/main` instead of force-pushing rewritten history.

## Pull request and merge order

- Use the repository pull request template.
- A reviews B's work; B reviews A's work.
- Merge a provider before its consumer (for example, C0 before A1/B1, A1 before B1 integration, A2 before B2 live API integration).
- Only one pull request merges at a time.
- Prefer squash merge so each task is one identifiable `main` commit.
- After every merge, the next PR updates from the new `main`, resolves conflicts on its own branch, and reruns checks.
- Delete the merged feature branch and remove its worktree only after the merge is confirmed.

## Conflict policy

- Stop if a conflict touches a frozen contract or a file owned by the other member. Resolve it together; do not choose one side blindly.
- For implementation conflicts in your owned file, preserve both intended behaviors and rerun the relevant tests.
- For `README.md`, Member A reconciles merged code and both members' task notes; generated conflict markers must never be committed.
- Do not use `git reset --hard`, force-push `main`, or kill unrelated processes to clear ports.

## Suggested protected-main settings

The intended GitHub rules are documented in `docs/repository-settings.md`. Until those settings are enabled remotely, both members must follow them manually: no direct pushes, one cross-review approval, resolved conversations, current branch, and successful required checks.
