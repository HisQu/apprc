# ===============================================================
# Justfile for Python projects using uv + pyproject.toml
# ===============================================================
# Why this exists:
# - One command to install exactly what's in uv.lock (safe for CI).
# - A clear, explicit path to re-lock/upgrade when you WANT changes.
# - Optional exports for the "I only understand requirements.txt" crowd.
#
# References (summarized):
# - uv auto-locks by default; --locked disables that and errors if stale. 
# - uv can export a requirements.txt-style file and can also "compile" one.
#   See: uv concepts: lock/sync, uv export, uv pip compile.
#
# Dependencies: uv (and optionally direnv). Python itself is handled by uv.
# ===============================================================

# Let recipes use Bash features and fail-fast in pipelines
set shell := ["bash", "-euo", "pipefail", "-c"]

# Run `just` with no recipe to list tasks
default:
    @just --list

# ---------------------------------------------------------------
# Internal guards (kept private so they don't clutter `just --list`)
# ---------------------------------------------------------------
[private]
_note-direnv:
    @if command -v direnv >/dev/null; then \
        test -n "${VIRTUAL_ENV-}" || echo "ℹ direnv detected but VIRTUAL_ENV not active. Run: direnv allow && direnv reload"; \
    fi

[private]
_check-uv:
    : ${UV_PROJECT_ENVIRONMENT:="$PWD/.venv"}
    @command -v uv >/dev/null || { \
        echo "✗ uv not found. Install from https://docs.astral.sh/uv/ then retry." >&2; \
        exit 127; \
    }

[private]
_check-clean-worktree action="publishing":
    @git diff --quiet || { \
        echo "Unstaged changes exist. Commit or stash before {{action}}." >&2; \
        exit 1; \
    }
    @git diff --cached --quiet || { \
        echo "Staged changes exist. Commit before {{action}}." >&2; \
        exit 1; \
    }
    @test -z "$(git ls-files --others --exclude-standard)" || { \
        echo "Untracked files exist. Commit, ignore, or remove them before {{action}}:" >&2; \
        git ls-files --others --exclude-standard >&2; \
        exit 1; \
    }

# ---------------------------------------------------------------
# Clean / environment helpers
# ---------------------------------------------------------------

# Remove transient junk: uv cache,  __pycache__, .pytest_cache, .mypy_cache, .ruff_cache. Does NOT touch uv.lock or your venv.
clean:
    @echo "🧹 Cleaning caches and build artifacts..."
    find . \
      \( -path "./.git" -o -path "./.venv" -o -path "./.direnv" \) -prune -o \
      -type d \( -name "__pycache__" -o -name "*.egg-info" \) \
      -prune -exec rm -rf {} + || true
    rm -rf .pytest_cache .mypy_cache .ruff_cache dist build || true
    uv cache prune || true


# Rebuilds python venv from uv.lock
reset-venv:
    @echo "♻ Rebuilding virtual environment..."
    uv venv --seed --clear
    uv sync --frozen --all-extras --all-groups

# ---------------------------------------------------------------
# Install flows
# ---------------------------------------------------------------
# Key rule: CI and teammates should *not* relock by accident.
# We therefore install with `--locked` which errors if uv.lock is stale.
# If it errors, you intentionally run `just lock` or `just upgrade`.
# > --all-extras: Install all published extras from [project.optional-dependencies], such as tui.
# > --all-groups: Install all local groups from [dependency-groups], such as dev.
# > --no-default-groups: Skip uv's default groups, including dev, for runtime-only installs.
# > --frozen: Sync from uv.lock while ignoring pyproject.toml
# > --locked: Exit non-zero if pyproject.toml differs from uv.lock


# Install or sync everything from uv.lock into venv. (CI should use this)
# `python -m pip install -e ".[<all_extras>]" --group dev`
sync:
    just _note-direnv
    just _check-uv
    uv sync --all-extras --all-groups --locked
alias install := sync

# ---------------------------------------------------------------
# Locking and upgrading
# ---------------------------------------------------------------
# Examples:
#   just lock                   # resolve using current constraints
#   just lock --upgrade         # allow upgrades while resolving
#   just lock --python 3.12     # resolve for a specific interpreter

# Creates uv.lock based on pyproject.toml and exports pylock.toml.
lock *ARGS:
    just _check-uv
    uv lock {{ARGS}}
    uv export -o pylock.toml --all-extras --all-groups --quiet

# Re-lock with --upgrade & install from the new lock.
upgrade *ARGS:
    just lock --upgrade {{ARGS}}
    uv sync --all-extras --all-groups --locked


# Re-lock with --upgrade ONLY git-based dependencies & uv sync from the new lock.
upgrade-repos *ARGS:
    @echo "⬆️  Upgrading only git-based dependencies to latest revisions..."
    uv lock \
        # --upgrade-package mongodbapi \
        # --upgrade-package gta \
        # --upgrade-package embedding \
        {{ARGS}}
    uv sync --all-extras --all-groups --locked
alias uprep := upgrade-repos


# --- Switch python versions -------

# Switches major Python version for the project. Usage: just py-switch 3.13t
py-switch version="3.13":
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🐍 Switching project Python to {{version}}"
    # > Ensure the requested interpreter exists.
    uv python install {{version}}
    # > Persist the project's default interpreter request.
    uv python pin {{version}}
    # > Recreate the project venv with that interpreter.
    uv venv --python {{version}} --seed --clear
    # > Sync dependencies for the recreated environment.
    uv sync --all-extras --all-groups
    # > Verify via uv, so shell activation state cannot mislead you.
    uv run python -c 'import sys; print(sys.version); print(sys.executable)'




# ---------------------------------------------------------------
# Testing
# ---------------------------------------------------------------

[private]
_ci-check-python version environment:
    #!/usr/bin/env bash
    set -euo pipefail
    export UV_PROJECT_ENVIRONMENT="{{environment}}"
    export UV_LINK_MODE=copy
    unset VIRTUAL_ENV
    echo "🐍 Python {{version}}: preparing isolated release environment..."
    uv sync \
        --python "{{version}}" \
        --locked \
        --all-extras \
        --all-groups \
        --quiet \
        --no-progress
    uv lock --check --quiet
    echo "✓ Python {{version}}: environment ready; running CI checks."
    uv run --python "{{version}}" --locked --no-sync ruff format . --check
    uv run --python "{{version}}" --locked --no-sync ruff check .
    uv run --python "{{version}}" --locked --no-sync \
        pyright --venvpath "$(dirname "$UV_PROJECT_ENVIRONMENT")"
    uv run --python "{{version}}" --locked --no-sync pytest
    uv run --python "{{version}}" --locked --no-sync \
        python -m compileall -q src tests examples/example_apps/src
    echo "✓ Python {{version}}: CI checks passed."

[private]
_release-artifact-check notes_output:
    #!/usr/bin/env bash
    set -euo pipefail
    version="$(uv version --short)"
    tag="${GITHUB_REF_NAME:-v${version}}"
    notes_output="{{notes_output}}"
    artifact_root="$(mktemp -d)"
    readme_candidate="$artifact_root/README.pypi.md"
    smoke_root="$artifact_root/smoke"
    smoke_script="$(realpath src/apprc_dev/packaging/install_smoke.py)"
    mkdir -p "$smoke_root"
    trap 'rm -rf "$artifact_root"' EXIT

    mkdir -p "$(dirname "$notes_output")"
    python src/apprc_dev/packaging/release_notes.py \
        "$version" \
        --tag "$tag" \
        --project-version "$version" \
        --output "$notes_output"

    python src/apprc_dev/packaging/pypi_readme.py \
        --destination "$readme_candidate"
    if ! cmp -s README.pypi.md "$readme_candidate"; then
        diff -u README.pypi.md "$readme_candidate" || true
        echo "README.pypi.md is stale. Regenerate and commit it with:" >&2
        echo "python src/apprc_dev/packaging/pypi_readme.py" >&2
        exit 1
    fi

    rm -rf dist
    uv build --python 3.12 --no-sources

    shopt -s nullglob
    wheels=(dist/*.whl)
    sdists=(dist/*.tar.gz)
    if [[ "${#wheels[@]}" -ne 1 || "${#sdists[@]}" -ne 1 ]]; then
        echo "Expected exactly one wheel and one sdist in dist/." >&2
        exit 1
    fi

    expected_wheel="apprc-${version}-py3-none-any.whl"
    expected_sdist="apprc-${version}.tar.gz"
    if [[ "$(basename "${wheels[0]}")" != "$expected_wheel" ]]; then
        echo "Expected wheel ${expected_wheel}, found ${wheels[0]}." >&2
        exit 1
    fi
    if [[ "$(basename "${sdists[0]}")" != "$expected_sdist" ]]; then
        echo "Expected sdist ${expected_sdist}, found ${sdists[0]}." >&2
        exit 1
    fi

    wheel="$(realpath "${wheels[0]}")"
    sdist="$(realpath "${sdists[0]}")"
    uv run --with twine --no-project -- twine check "$wheel" "$sdist"

    (
        cd "$smoke_root"
        for python_version in 3.12 3.13 3.14; do
            uv run \
                --isolated \
                --python "$python_version" \
                --with "$wheel" \
                python "$smoke_script"
        done
        uv run \
            --isolated \
            --python 3.12 \
            --with "$sdist" \
            python "$smoke_script"
    )

    uv publish \
        --dry-run \
        --trusted-publishing never \
        --token unused-local-dry-run-token \
        --check-url https://pypi.org/simple/apprc/ \
        "$wheel" \
        "$sdist"

# Rehearse the complete local release gate without publishing
publish-check:
    #!/usr/bin/env bash
    set -euo pipefail
    just _check-uv
    check_root="$(mktemp -d)"
    trap 'rm -rf "$check_root"' EXIT

    for python_version in 3.12 3.13 3.14; do
        just _ci-check-python \
            "$python_version" \
            "$check_root/python-${python_version}/.venv"
    done
    just _release-artifact-check "$check_root/release-notes.md"

# Prepare a checked version commit and annotated local release tag
bump-version bump="patch":
    #!/usr/bin/env bash
    set -euo pipefail
    just _check-uv
    just _check-clean-worktree "bumping the version"

    next_version="$(uv version --bump "{{bump}}" --dry-run --short)"
    tag="v${next_version}"
    if git rev-parse --verify --quiet "refs/tags/${tag}" >/dev/null; then
        echo "Tag ${tag} already exists. Choose another bump." >&2
        exit 1
    fi

    release_root="$(mktemp -d)"
    notes_file="$release_root/release-notes.md"
    restore_version_files=false
    cleanup() {
        exit_code=$?
        trap - EXIT
        if [[ "$restore_version_files" == true ]]; then
            cp "$release_root/pyproject.toml" pyproject.toml
            cp "$release_root/uv.lock" uv.lock
            cp "$release_root/pylock.toml" pylock.toml
        fi
        rm -rf "$release_root"
        exit "$exit_code"
    }
    trap cleanup EXIT

    python src/apprc_dev/packaging/release_notes.py \
        "${next_version}" \
        --output "$notes_file"

    cp pyproject.toml uv.lock pylock.toml "$release_root/"
    restore_version_files=true
    uv version --bump "{{bump}}" --no-sync
    uv export -o pylock.toml --all-extras --all-groups --quiet
    just publish-check

    git commit \
        --only pyproject.toml uv.lock pylock.toml \
        -m "Bump version to ${next_version}"
    restore_version_files=false
    if ! git tag -a "${tag}" -m "Release ${tag}"; then
        echo "Version commit succeeded, but tag creation failed. Retry with:" >&2
        echo "git tag -a ${tag} -m 'Release ${tag}'" >&2
        exit 1
    fi
alias bump := bump-version

# Verify the published PyPI package in a fresh plain-pip virtualenv.
verify-pypi requirement="apprc":
    #!/usr/bin/env bash
    set -euo pipefail
    check_env="/tmp/apprc-pypi-check"
    rm -rf "$check_env"
    python -m venv "$check_env"
    "$check_env/bin/python" -m pip install --upgrade pip
    "$check_env/bin/python" -m pip install --no-cache-dir "{{requirement}}"
    "$check_env/bin/python" src/apprc_dev/packaging/install_smoke.py

# Run GitHub Actions triggered by push locally using act
gitactions:
    act push \
      --secret-file .env.secret \
      -P ubuntu-latest=catthehacker/ubuntu:act-latest \
      --container-options "-v $HOME/.act-uv-cache:/root/.cache/uv" \
      --action-offline-mode



# ---------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------

# Example: just run -- python -m yourpkg --help
# Runs your package’s CLI or module under the locked environment.
run *CMD:
    just _check-uv
    uv run --locked -- {{CMD}}

# Print effective dependency tree (won’t modify lock when used with --locked)
tree:
    just _check-uv
    uv tree --locked || uv tree

# Show uv + Python info for debugging bug reports
diagnose:
    just _check-uv
    uv --version
    uv python list || true
    uv sync --check --all-extras --all-groups


# ---------------------------------------------------------------
# Example recipe written in python (executes venv/python):
# pyyy:
#     #!/usr/bin/env python3
#     import sys
#     print(sys.executable)
#     print('Hello from python!')
