# Contributing to AppRC

## Table of Contents

1. [Contributing to AppRC](#contributing-to-apprc)
   1. [Table of Contents](#table-of-contents)
2. [Quick start](#quick-start)
3. [Issues and backlog](#issues-and-backlog)
4. [Changelog](#changelog)

## Quick start

1. Read [AGENTS.md](AGENTS.md) and this guide before repository work.
2. Follow [Development](docs/Development.md) for environment setup and the
   technical procedure relevant to your change.
3. Check [GitHub Issues](https://github.com/HisQu/apprc/issues) and
   [BACKLOG.md](BACKLOG.md) for related work. Update the records connected to
   your contribution and link resolving or partial work from its pull request.

## Issues and backlog

> [!CAUTION]
> This is git-tracked: Never record secrets, absolute paths, credentials, private host data, or speculative security claims. Use only repository-relative paths for source files. Use complete URLs for GitHub Issues.


> [!IMPORTANT]
> 
> ## Rules
> GitHub Issues own durable work, evidence, discussion, and resolution. `BACKLOG.md` organizes issue-backed planned Passes in their current execution order. `TODO.md` beside `PLAN.md` is the active Pass's operational checklist.
> 1) Keep the BACKLOG header and Table of Contents. Link every actionable entry to its GitHub Issue and keep each entry concise.
> 1) Order planned Passes and their entries by the current execution order. Reorder them when dependencies or blockers change. Independent Tasks within an authorized Pass may continue while another Task is blocked.
> 1) Create an issue for genuine, actionable work. Search all open and closed issues first, and reuse a matching issue only when it covers the same outstanding scope. Do not create another issue just because a task stalled. Record blockers on the existing issue; create a separate issue only for separate actionable work.
> 1) Reference related issues in both records when they represent related work. Keep the references bidirectional and use complete issue URLs in `BACKLOG.md`.
> 1) Keep `accepted`, `needs info`, and `Deferred` independent. `accepted` identifies work in the user's focus and does not mean all information is available. `needs info` identifies a specific unanswered question that blocks the next step. `Deferred` identifies work deliberately held for later. Accepted work may also need information or be deferred. Remove `needs info` when the required information is supplied. Promote Deferred work only when it is deliberately scheduled.
> 1) Keep `Deferred` in a final section after the planned Passes. Do not treat a `needs info` label as a reason to defer work automatically.
> 1) When GitHub Actions is unavailable, apply the required workflow labels through `gh` or the GitHub API.
> 1) Keep the existing **Types**, **Priorities**, and **Effort** definitions below. Do not create type, priority, or effort labels from those report values.
> 1) If an issue is fully resolved, use a closing reference such as `Closes #123` in the pull request to `main` and remove the completed backlog entry in the same change. Add a `CHANGELOG.md` entry only when the change has a notable user- or contributor-facing effect. For a partial fix, use an ordinary reference such as `Refs #123` and keep the unresolved issue and backlog scope open.
> 1) Schedule a reopened issue only after a fresh scheduling decision in `BACKLOG.md`.
> 1) Every agent maintains the issue, backlog, TODO, and changelog records related to its work. Reconcile them while discovering, organizing, working, deferring, and completing work.
> 1) Record any pending GitHub write, its source evidence, and its current outcome in the active `TODO.md`. Before retiring the TODO, transfer unfinished GitHub operations through the existing unfinished-work handoff. If a GitHub write fails, keep a local pending-publication record with the evidence and report the synchronization as unfinished. Do not claim that it succeeded or discard the only copy of the finding.
> 1) **Types:**
>       - **Bug risk**: Potential defect with concrete evidence, not yet confirmed.
>       - **Code smell**: Implementation, architectural, maintainability or clarity issue that is not currently a defect.
>       - **Docs drift**: Documentation is stale, incomplete, or inconsistent.
>       - **Tooling**: Issue with build, test, lint, type-check, and general slowdown of developer workflow.
>       - **Security**: Evidence-backed security risk. Use Question for uncertainty.
>       - **Question**: Design, behavior, or ownership uncertainty needing investigation & maybe decision.
> 
> 1) **Priorities:**
>       - **P1**: Should be handled ASAP.
>       - **P2**: Should be handled before next release or milestone.
>       - **P3**: Useful cleanup for a later focused pass.
> 1) **Effort:**
>       - **E1**: Issue deserves its own focused pass.
>       - **E2**: Can be batched with a few other issues.
>       - **E3**: Can be batched with many other issues.
> 1) **Format:**
> ```markdown
> 
> <br>
> 
> # Planned Pass: <pass name>
>
> ## <Priority> / <Effort> [<Type>] - *Short problem title*
> - **Issue:** complete GitHub issue URL
> - **Area:** `path/or/symbol`
> - **Observed while:** short context
> - **Why not fixed now:** scope, risk, uncertainty, or user decision needed
> - **Evidence:** concrete observation
> - **Context:** explanation to ensure the problem is understood in the big-picture of the repo.
> - **Suggested next step:** smallest reasonable follow-up. Reference related issues as complete URLs.
> 
> <br>
> 
> # Deferred
>
> ## <Priority> / <Effort> [<Type>] - *Short problem title*
> - **Issue:** complete GitHub issue URL
> - **Area:** `path/or/symbol`
> - ...
> ```



<br>

---

<br>

## Changelog

Follow the rules below when editing [CHANGELOG.md](CHANGELOG.md).

> [!IMPORTANT]
> ## Rules
> 1. Follow [Keep a Changelog 2.0.0](https://keepachangelog.com/en/2.0.0/) and [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).
> 2. Keep stable sections and the current cumulative section for each in-progress target. Git tags preserve earlier preview snapshots.
> 3. Use `## [X.Y.Z] - YYYY-MM-DD (b1)` or `## [X.Y.Z] - YYYY-MM-DD (rc1)` for a preview. Update the date and stage in the same heading as the target progresses. For stable, use `## [X.Y.Z] - YYYY-MM-DD`. Append `[YANKED]` only for a yanked release. Keep all six categories under [Unreleased] and omit empty categories from released sections.
> 4. Include only curated changes with a notable effect on users or contributors. Exclude routine internal refactors, test-only work, and other changes without a user- or contributor-facing effect; resolving an issue alone does not require an entry.
> 5. File entries under their actual category. Start every breaking entry with **Breaking:** 💥 under that category, identify affected users, and include migration guidance when possible.
> 6. Use the emoji mapping informed by [Gitmoji](https://github.com/carloscuesta/gitmoji) and [conventional-changelog-emoji](https://github.com/favoloso/conventional-changelog-emoji): ✨ Added, 🛠️ Changed, 🗑️ Deprecated, 🔥 Removed, 🐛 Fixed, and 🔒 Security.
> 7. Keep one cumulative section per target version. Describe the changes that ship since the previous stable release, including earlier preview changes still present in the current build. Each GitHub Release gets a snapshot of that section. Keep only the latest published beta download.
> 8. Use 🐛 Fixed only for defects in previously released behavior; describe new features under ✨ Added.
> 9. List [Unreleased] and stable major/minor `X.Y.0` releases in the TOC. Place version reference definitions immediately after the TOC. [Unreleased] compares the latest existing release tag with HEAD. For cumulative sections, compare the previous stable tag with the current tagged build. Use only existing tags.
>
> Local presentation exceptions: retain the project header, this policy link, TOC, and `<br>` / `---` layout; use emoji-prefixed category headings and the inline 💥 breaking marker; keep all six category headings under [Unreleased] even when empty; list only [Unreleased] and stable `X.Y.0` releases in the TOC; place reference definitions immediately after the TOC instead of at the bottom.
