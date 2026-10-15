# Main access policy handoff

- Task ID / branch / commit: MAIN-ACCESS / `chore/main-access-policy` / recorded by the pull request.
- Implemented behavior: all changes to `main` require a pull request; only repository owner `@devxpatel11` can approve and complete the merge; collaborators cannot update `main` directly.
- Changed files and contract changes: `.github/CODEOWNERS`, `docs/repository-settings.md`, and this note; no protocol, API, metrics, or runtime contract changes.
- Exact commands run and actual results: `python scripts/verify.py` -> foundation verified; `python -m pytest -q -p no:cacheprovider` -> 94 passed in 12.22s; `git diff --check` -> passed. GitHub CI is recorded on the pull request.
- Expected versus actual acceptance criteria: the active ruleset blocks direct `main` updates and exposes only `@devxpatel11` as a pull-request-only bypass; final code-owner enforcement is enabled after this file lands.
- Raw evidence paths: GitHub ruleset `Protect main` (ID `25198331`) and this repository policy documentation.
- Known limitations / blocked items: repository owners can modify repository settings; account security remains outside the ruleset.
- Next task ready? yes, after GitHub CI and final ruleset verification pass.
- README notes path: `docs/readme-notes/MAIN-ACCESS.md`.
