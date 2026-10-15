# Repository protection settings

Apply one GitHub ruleset to the default branch `main` after both collaborators have repository access.

## Required settings

- Restrict direct updates to `main`; changes enter through pull requests.
- Require one approval from the repository owner, `@devxpatel11`, through `CODEOWNERS`.
- Dismiss stale approvals when new commits are pushed.
- Require all review conversations to be resolved.
- Require the branch to be current before merge.
- Block force pushes and branch deletion.
- Prefer squash merge; disable merge commits on `main` if the team agrees.
- Grant only `@devxpatel11` a pull-request-only bypass so the owner can accept or reject changes without enabling direct pushes.

Add required status checks only after their workflow exists and has completed successfully on `main`; never configure a nonexistent check that blocks every PR. At minimum, the eventual check should run `python scripts/verify.py`, unit tests, and applicable integration tests on Python 3.12.

## Repository options

- Default branch: `main`.
- Automatically delete merged feature branches.
- Keep the pull request template enabled.
- Collaborators may keep write access for feature branches, but they cannot update `main` directly or merge pull requests into it.
- Keep `.github/CODEOWNERS` set to `* @devxpatel11`; do not add collaborator bypasses.

The `Protect main` repository ruleset enforces these settings. Keep this document synchronized with any future ruleset change.
