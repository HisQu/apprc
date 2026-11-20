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

# > Publish stable packages through PyPI. Keep this policy in version control.
RELEASE_PYPI := "true"
# Hosted CI is advisory during allowance outages; local tests remain required.
RELEASE_REQUIRE_CI := "false"

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
_check-gh:
    @command -v gh >/dev/null || { \
        echo "gh not found. Install it from https://cli.github.com/ and retry." >&2; \
        exit 127; \
    }
    @gh auth status >/dev/null 2>&1 || { \
        echo "gh is not authenticated. Run 'gh auth login' and retry." >&2; \
        exit 1; \
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
    uv sync --all-packages --frozen --all-extras --all-groups

# ---------------------------------------------------------------
# Install flows
# ---------------------------------------------------------------
# Key rule: CI and teammates should *not* relock by accident.
# We therefore install with `--locked` which errors if uv.lock is stale.
# If it errors, you intentionally run `just lock` or `just upgrade`.
# > --all-packages: Select every workspace project, including the GUI distribution.
# > --all-extras: Install any declared extras. The terminal wrapper is a dev dependency.
# > --all-groups: Install all local groups from [dependency-groups], such as dev.
# > --no-default-groups: Skip uv's default groups, including dev, for runtime-only installs.
# > --frozen: Sync from uv.lock while ignoring pyproject.toml
# > --locked: Exit non-zero if pyproject.toml differs from uv.lock


# Install or sync everything from uv.lock into venv. (CI should use this)
# `python -m pip install -e ".[<all_extras>]" --group dev`
sync:
    just _note-direnv
    just _check-uv
    uv sync --all-packages --all-extras --all-groups --locked
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
    uv sync --all-packages --all-extras --all-groups --locked


# Re-lock with --upgrade ONLY git-based dependencies & uv sync from the new lock.
upgrade-repos *ARGS:
    @echo "⬆️  Upgrading only git-based dependencies to latest revisions..."
    uv lock \
        # --upgrade-package mongodbapi \
        # --upgrade-package gta \
        # --upgrade-package embedding \
        {{ARGS}}
    uv sync --all-packages --all-extras --all-groups --locked
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
    uv sync --all-packages --all-extras --all-groups
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
        --all-packages \
        --all-extras \
        --all-groups \
        --quiet \
        --no-progress
    uv lock --check --quiet
    echo "☑️ Python {{version}}: environment ready; running CI checks."
    uv run --python "{{version}}" --locked --no-sync ruff format . --check
    uv run --python "{{version}}" --locked --no-sync ruff check .
    uv run --python "{{version}}" --locked --no-sync \
        pyright --venvpath "$(dirname "$UV_PROJECT_ENVIRONMENT")"
    uv run --python "{{version}}" --locked --no-sync pytest
    uv run --python "{{version}}" --locked --no-sync \
        python -m compileall -q src tests examples/example_apps/src
    echo "☑️ Python {{version}}: CI checks passed."

[private]
_release-artifact-check directory:
    #!/usr/bin/env bash
    set -euo pipefail
    directory={{quote(directory)}}
    artifact_root="$(mktemp -d)"
    readme_candidate="$artifact_root/README.pypi.md"
    trap 'rm -rf "$artifact_root"' EXIT

    python src/apprc_dev/packaging/pypi_readme.py --destination "$readme_candidate"
    if ! cmp -s README.pypi.md "$readme_candidate"; then
        diff -u README.pypi.md "$readme_candidate" || true
        echo "README.pypi.md is stale. Regenerate it with python src/apprc_dev/packaging/pypi_readme.py." >&2
        exit 1
    fi
    python src/apprc_dev/packaging/terminal_metadata.py --check
    PYTHONPATH=src python src/apprc_dev/packaging/gui_metadata.py --check
    PYTHONPATH=src python -m apprc_dev.packaging.example_metadata --check
    for project in apprc-core apprc apprc-gui; do
        uv build --python 3.12 --no-sources --no-create-gitignore --no-build-logs --package "$project" --out-dir "$directory"
    done
    uv run --with twine --no-project -- twine check "$directory"/*
    uv run --isolated --no-project --python 3.12 \
        python src/apprc_dev/packaging/artifact_check.py "$directory"
    PYTHONPATH=src python -m apprc_dev.packaging.release_assets seal "v$(uv version --short)" "$directory"

# Rehearse the complete local release gate without publishing.
publish-check:
    #!/usr/bin/env bash
    set -euo pipefail
    just _check-uv
    check_root="$(mktemp -d)"
    trap 'rm -rf "$check_root"' EXIT
    just _ci-check-python 3.12 "$check_root/.venv"
    mkdir "$check_root/packages"
    just _release-artifact-check "$check_root/packages"
    echo "Local release rehearsal passed. No files were uploaded."

# Prepare a checked version commit and annotated local release tag.
release-prepare level="patch":
    #!/usr/bin/env bash
    set -euo pipefail
    just _check-uv
    just _check-clean-worktree "preparing the release"

    requested={{quote(level)}}
    case "$requested" in
        major|minor|patch) next_version="$(uv version --bump "$requested" --dry-run --short)" ;;
        *) next_version="$requested" ;;
    esac
    PYTHONPATH=src python -c 'import sys; from apprc_dev.packaging.release_notes import validate_next_version; validate_next_version(*sys.argv[1:])' "$(uv version --short)" "$next_version"
    tag="v${next_version}"
    if git rev-parse --verify --quiet "refs/tags/${tag}" >/dev/null; then
        echo "Tag ${tag} already exists. Choose another release level." >&2
        exit 1
    fi

    echo "Preparing ${tag} locally. Nothing will upload until you push main and ${tag}."

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
            cp "$release_root/gui-pyproject.toml" \
                src/apprc_dev/packaging/gui/pyproject.toml
            cp "$release_root/examples-pyproject.toml" \
                examples/example_apps/pyproject.toml
            python src/apprc_dev/packaging/terminal_metadata.py
        fi
        rm -rf "$release_root"
        exit "$exit_code"
    }
    trap cleanup EXIT

    python src/apprc_dev/packaging/release_notes.py \
        "${next_version}" \
        --output "$notes_file"

    cp pyproject.toml uv.lock pylock.toml "$release_root/"
    cp src/apprc_dev/packaging/gui/pyproject.toml \
        "$release_root/gui-pyproject.toml"
    cp examples/example_apps/pyproject.toml \
        "$release_root/examples-pyproject.toml"
    restore_version_files=true
    uv version "$next_version" --frozen
    python src/apprc_dev/packaging/terminal_metadata.py
    PYTHONPATH=src python src/apprc_dev/packaging/gui_metadata.py
    PYTHONPATH=src python -m apprc_dev.packaging.example_metadata
    uv lock
    uv export -o pylock.toml --all-extras --all-groups --quiet
    uv lock --check --quiet

    git commit \
        --only \
        pyproject.toml uv.lock pylock.toml \
        src/apprc_dev/packaging/terminal/pyproject.toml \
        src/apprc_dev/packaging/gui/pyproject.toml \
        examples/example_apps/pyproject.toml \
        -m "Bump version to ${next_version}"
    restore_version_files=false
    if ! git tag -a "${tag}" -m "Release ${tag}"; then
        echo "Version commit succeeded, but tag creation failed. Retry with:" >&2
        echo "git tag -a ${tag} -m 'Release ${tag}'" >&2
        exit 1
    fi

    echo
    echo "================================================================="
    echo "✅  RELEASE ${tag} PREPARED LOCALLY"
    echo "================================================================="
    echo
    echo "Nothing has been uploaded."
    echo
    echo "NEXT COMMAND, THIS STARTS THE RELEASE:"
    echo
    echo "  just release-push ${tag}"
    echo
    echo "Run from main to build locally and publish the GitHub Release."
    echo "====================================================================="

# Build, verify, and publish the annotated tag at main's current commit.
release-push tag:
    #!/usr/bin/env bash
    set -euo pipefail
    just _check-clean-worktree "pushing the release"
    just _check-gh
    tag={{quote(tag)}}
    version="$(uv version --short)"
    if [[ "$(git branch --show-current)" != main || "$tag" != "v$version" ]]; then
        echo "Release pushes require main and a tag matching the committed version." >&2
        exit 1
    fi
    ref="refs/tags/$tag"
    commit="$(git rev-parse HEAD)"
    if ! git cat-file -e "$ref^{tag}" 2>/dev/null || [[ "$(git rev-parse "$ref^{commit}")" != "$commit" ]]; then
        echo "Annotated tag $tag must reference the current main commit." >&2
        exit 1
    fi
    release_pypi="$(just --no-dotenv --evaluate RELEASE_PYPI)"
    require_ci="$(just --no-dotenv --evaluate RELEASE_REQUIRE_CI)"
    [[ "$release_pypi" == true || "$release_pypi" == false ]]
    [[ "$require_ci" == true || "$require_ci" == false ]]

    cache=".cache/apprc/releases/$tag"
    mkdir -p "$cache"
    exec 9>"$cache/.lock"
    flock 9
    notes="$cache/release-notes.md"
    python src/apprc_dev/packaging/release_notes.py "$version" \
        --tag "$tag" --project-version "$version" --output "$notes"
    bundle="$cache/$commit"
    if [[ ! -d "$bundle" ]]; then
        pending="$(mktemp -d "$cache/.partial.XXXXXX")"
        trap 'rm -rf "$pending"' EXIT
        just _ci-check-python 3.12 "$pending/.venv"
        mkdir "$pending/packages"
        just _release-artifact-check "$pending/packages"
        mv "$pending/packages" "$bundle"
    fi
    PYTHONPATH=src python -m apprc_dev.packaging.release_assets verify "$tag" "$bundle"

    git push --atomic origin refs/heads/main:refs/heads/main "$ref:$ref"
    if [[ "$require_ci" == true ]]; then
        just _wait-release-ci "$tag" "$commit"
    fi
    PYTHONPATH=src python -m apprc_dev.packaging.release_assets publish "$tag" "$bundle" \
        --commit "$commit" --notes "$notes"
    if [[ "$release_pypi" == true && "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        just publish-pypi "$tag"
    fi

[private]
_wait-release-ci tag commit:
    #!/usr/bin/env bash
    set -euo pipefail
    for attempt in {1..30}; do
        run_id="$(gh run list --workflow ci.yml --event push --branch {{quote(tag)}} \
            --commit {{quote(commit)}} --json databaseId --jq '.[0].databaseId // empty')"
        if [[ -n "$run_id" ]]; then
            gh run watch "$run_id" --exit-status
            exit 0
        fi
        sleep 2
    done
    echo "No hosted CI run for this tag and commit. Retry release-push when CI is available." >&2
    exit 1

# Prepare, build, and publish a release.
release level="patch":
    #!/usr/bin/env bash
    set -euo pipefail
    just release-prepare {{quote(level)}}
    tag="v$(uv version --short)"
    if ! just release-push "$tag"; then
        echo "Retry with: just release-push $tag" >&2
        exit 1
    fi

# Publish the artifacts attached to an existing GitHub Release.
publish-pypi tag:
    #!/usr/bin/env bash
    set -euo pipefail
    just _check-gh
    tag={{quote(tag)}}
    [[ "$(just --no-dotenv --evaluate RELEASE_PYPI)" == true ]] || {
        echo "PyPI publication is disabled by RELEASE_PYPI." >&2
        exit 1
    }

    if [[ ! "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
        echo "Invalid release tag '${tag}'; expected vMAJOR.MINOR.PATCH." >&2
        exit 1
    fi
    if ! is_draft="$(gh release view "$tag" --json isDraft --jq .isDraft)"; then
        echo "GitHub Release ${tag} does not exist." >&2
        exit 1
    fi
    if [[ "$is_draft" == "true" ]]; then
        echo "GitHub Release ${tag} is still a draft and cannot be published." >&2
        exit 1
    fi
    wheel_count="$(gh release view "$tag" --json assets --jq '[.assets[].name | select(endswith(".whl"))] | length')"
    sdist_count="$(gh release view "$tag" --json assets --jq '[.assets[].name | select(endswith(".tar.gz"))] | length')"
    if [[ "$wheel_count" != 3 || "$sdist_count" != 3 ]]; then
        echo "GitHub Release ${tag} must contain exactly three wheels and three source archives." >&2
        exit 1
    fi

    gh workflow run release.yml --raw-field "release_tag=${tag}"
    echo "Requested PyPI publication for ${tag}. Follow the workflow URL above."

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
    uv sync --all-packages --check --all-extras --all-groups


# ---------------------------------------------------------------
# Example recipe written in python (executes venv/python):
# pyyy:
#     #!/usr/bin/env python3
#     import sys
#     print(sys.executable)
#     print('Hello from python!')
