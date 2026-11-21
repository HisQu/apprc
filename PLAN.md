# AppRC CSC correctness and cleanup

**Goal**

Fix the agreed correctness issues, verify the integrated result, and deliver it in a draft PR.

**Specifics**

The pass starts from GitHub `main` at `34c4f2` and uses the shared branch `codex/apprc-csc-correctness`. [CSC report](code-smells.md) · [Checklist](TODO.md)

| Work | Scope |
| --- | --- |
| Workspace moves | CSC-11 and CSC-12 track directory ownership and reject changed workspace records under existing locks. CSC-08 reports the committed destination and cleanup warnings. |
| Configuration writes | CSC-13 binds migration revisions to captured bytes. CSC-04 uses one workspace and destination set per grouped edit. |
| Editable updates | CSC-07 uses the existing confirmed registration path and its idempotent initialization contract to finish a retry with current Git and dependencies. |
| Installer and documentation cleanup | CSC-06 documents the active CI profiles. CSC-09 removes the dead pre-activation Windows registration rollback path. |

CSC-01, CSC-02, CSC-03, CSC-05, and CSC-10 are deferred. CSC-01 and CSC-02 move to P3. The scoped fixes use existing locks, revision checks, persisted records, and public interfaces.

Extend the existing test suite with deterministic regressions. Check the failure on the baseline where practical, then run focused checks and one independent integrated review. Run the applicable local test, Ruff, and Pyright checks on the reviewed changes. All installation fixtures use disposable data.

The coordinator commits and pushes scoped checkpoints and keeps one draft PR current. Completion requires the fixes, verification evidence, review, and dispositions available in the draft. The branch and worktree remain available for the user's later integration decision.
