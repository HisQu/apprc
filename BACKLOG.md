# Backlog

Treat this as the concise organization of issue-backed planned Passes in their current execution order.
See [Contributing](CONTRIBUTING.md#issues-and-backlog) for issue and backlog rules and formats.


<br>

<br>

---

<br>

## Table Of Contents

1. [Backlog](#backlog)
   1. [Table Of Contents](#table-of-contents)
2. [Deferred](#deferred)
   1. [P3 / E1 \[Tooling\] - *Windows and macOS installation validation is deferred*](#p3--e1-tooling---windows-and-macos-installation-validation-is-deferred)

<br>

---

<br>

# Deferred

<a id="p2--e1-tooling---windows-and-macos-installation-ci-fails"></a>

## P3 / E1 [Tooling] - *Windows and macOS installation validation is deferred*
- **Issue:** https://github.com/HisQu/apprc/issues/49
- **Area:** `src/apprc/distribution/runtime`, `src/apprc/user_files/app_home/locations.py`, `src/apprc/interfaces/tui`, and their native tests.
- **Observed while:** Reviewing native failures in CI run 42605623620.
- **Why not fixed now:** Explicitly deferred. Keep CI Linux-only.
- **Evidence:** Linux passed while Windows and macOS jobs exposed native installer, dependencies and UI failures.
- **Context:** The Windows ACL correction still needs native verification. [AppRC #31](https://github.com/HisQu/apprc/issues/31) covers related shortcut evidence.
- **Suggested next step:** Run the documented native checks when suitable environments are available, including shortcut and executable version verification.

<a id="p3--e3-bug-risk---verify-managed-desktop-shortcuts-on-windows"></a>

See [AppRC #31](https://github.com/HisQu/apprc/issues/31) for the related Windows shortcut investigation.
