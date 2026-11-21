# CSC pass checklist

- [x] Fetch GitHub `main`, capture `34c4f2`, and open the shared pass worktree.
- [x] Prepare the locked Python environment and confirm editable imports resolve from the pass checkout.
- [x] Fix workspace move ownership, stale-source detection, and CLI results (CSC-11, CSC-12, CSC-08).
- [x] Fix migration snapshots and grouped edit capture (CSC-13, CSC-04).
- [x] Fix editable update registration retry (CSC-07).
- [x] Verify installer and CI documentation cleanup (CSC-09, CSC-06).
- [x] Reconcile the CSC dispositions, backlog, and changelog.
- [x] Complete one integrated review and pass the applicable verification.
- [x] Open the draft PR and publish the implementation checkpoints.

## Verification evidence

- Six workspace cases, one grouped edit case, two migration cases, and one editable retry case failed as expected on the baseline.
- Focused post-fix checks passed for workspace and maintenance (40), config and dotenv (39), update and CLI (88), and installer rollback, Windows fixtures, and docs (71).
- The independent reviewer returned **APPROVE WITH ONE SCOPED CORRECTION** on tree `932f10`. The move now rechecks path link guards under the existing locks.
- Reviewed code tree `4f5cd5` passed 1,169 core tests (40 skipped), all 9 GUI tests including Chromium interaction, all 8 example smoke checks, Ruff lint and format, and the lock check. Pyright reported zero errors and three Windows-only import warnings on Linux.
- Native Windows and macOS execution remains unverified. The local suite uses disposable fixtures.
