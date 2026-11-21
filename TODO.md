# CSC pass checklist

- [x] Fetch GitHub `main`, capture `34c4f2`, and open the shared pass worktree.
- [x] Prepare the locked Python environment and confirm editable imports resolve from the pass checkout.
- [x] Fix workspace move ownership, stale-source detection, and CLI results (CSC-11, CSC-12, CSC-08).
- [x] Fix migration snapshots and grouped edit capture (CSC-13, CSC-04).
- [x] Fix editable update registration retry (CSC-07).
- [x] Verify installer and CI documentation cleanup (CSC-09, CSC-06).
- [x] Reconcile the CSC dispositions, backlog, and changelog.
- [ ] Complete one integrated review and pass the applicable verification.
- [ ] Push all checkpoints and confirm the draft PR is current.

## Verification evidence

- Six workspace cases, one grouped edit case, two migration cases, and one editable retry case failed as expected on the baseline.
- Focused post-fix checks passed for workspace and maintenance (40), config and dotenv (39), update and CLI (88), and installer rollback, Windows fixtures, and docs (71).
