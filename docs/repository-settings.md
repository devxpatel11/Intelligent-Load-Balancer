# Repository protection settings

Apply one GitHub ruleset to the default branch `main` after both collaborators have repository access.

## Required settings

- Restrict direct updates to `main`; changes enter through pull requests.
- Require one approval from the other member.
- Dismiss stale approvals when new commits are pushed.
- Require all review conversations to be resolved.
- Require the branch to be current before merge.
- Block force pushes and branch deletion.
- Prefer squash merge; disable merge commits on `main` if the team agrees.
- Do not allow routine bypasses. Repository administrators may retain emergency recovery access.

Add required status checks only after their workflow exists and has completed successfully on `main`; never configure a nonexistent check that blocks every PR. At minimum, the eventual check should run `python scripts/verify.py`, unit tests, and applicable integration tests on Python 3.12.

## Repository options

- Default branch: `main`.
- Automatically delete merged feature branches.
- Keep the pull request template enabled.
- Invite both members with write access; neither member self-approves.
- Fill actual GitHub usernames before adding `CODEOWNERS`; do not commit invented handles.

These are intended remote settings, not claims that GitHub has already enforced them. Until enabled, follow the same rules manually through `CONTRIBUTING.md`.
