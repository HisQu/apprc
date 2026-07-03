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

[private]
_check-pypi-api-key:
    @test -n "${PYPI_API_KEY-}" || { \
        echo "PYPI_API_KEY is required. Usage: PYPI_API_KEY=\"pypi-...\" just publish-pypi" >&2; \
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
# > --all-extras: Install all published extras from [project.optional-dependencies], such as rag.
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

# Generate the PyPI-safe README from the GitHub README
pypi-readme:
    python src/apprc_dev/packaging/pypi_readme.py

# Build release artifacts with the configured pyproject backend
build:
    just pypi-readme
    uv build --no-sources

# Validate package metadata and README rendering before publishing
publish-check:
    just build
    uv run --with twine --no-project -- twine check dist/*

# Usage: PYPI_API_KEY="pypi-..." just publish-pypi
# Rebuild, validate, and upload release artifacts to PyPI.
publish-pypi *ARGS:
    just _check-uv
    just _check-pypi-api-key
    just _check-clean-worktree
    rm -rf dist/
    just publish-check
    uv publish --token "$PYPI_API_KEY" {{ARGS}}

# Bump the project version, commit the version files, and create an annotated v-tag.
bump-version bump="patch":
    just _check-uv
    just _check-clean-worktree "bumping the version"
    @next_version="$(uv version --bump "{{bump}}" --dry-run --short)"; \
    tag="v${next_version}"; \
    if git rev-parse --verify --quiet "refs/tags/${tag}" >/dev/null; then \
        echo "Tag ${tag} already exists. Choose another bump." >&2; \
        exit 1; \
    fi; \
    uv version --bump "{{bump}}" --no-sync; \
    uv export -o pylock.toml --all-extras --all-groups --quiet; \
    git add pyproject.toml uv.lock pylock.toml; \
    git commit -m "Bump version to ${next_version}"; \
    git tag -a "${tag}" -m "Release ${tag}"
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
    "$check_env/bin/python" - <<'PY'
    import importlib.metadata as metadata
    import importlib.util
    import sys

    import apprc

    assert apprc.AppRC.__name__ == "AppRC"
    assert apprc.Config.__name__ == "Config"
    assert isinstance(apprc.ConfigBase, type)
    assert callable(apprc.field)
    assert {"AppRC", "Config", "ConfigBase", "field"}.issubset(apprc.__all__)

    requirements = metadata.requires("apprc") or []
    core_requirements = [
        requirement
        for requirement in requirements
        if "extra ==" not in requirement
    ]
    assert not any(
        requirement.lower().split(";", maxsplit=1)[0].strip().startswith("textual")
        for requirement in core_requirements
    )
    assert "tui" in (metadata.metadata("apprc").get_all("Provides-Extra") or [])
    assert any(
        requirement.lower().startswith("textual") and "tui" in requirement
        for requirement in requirements
    )
    assert importlib.util.find_spec("textual") is None
    assert not any(
        module_name == "textual" or module_name.startswith("textual.")
        for module_name in sys.modules
    )
    print("apprc base install smoke passed")
    PY

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
