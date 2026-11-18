#!/usr/bin/env bash
# One-line install script (OLIS) for a public GitHub release.
# Expected one-line install command template:
#   curl -fsSL <PUBLIC_SCRIPT_URL> | bash
# Requirements: Linux x86-64, Bash, sha256sum, awk, and curl.
# 1. Download the latest native setup executable and SHA256SUMS.
# 2. Verify the matching checksum before executing any downloaded file.
# 3. Run the native setup executable, which performs the installation.
# 4. Remove temporary downloads and return the native setup exit status.

(
    set -eu
    [ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || {
        echo "This OLIS requires Linux x86-64." >&2
        exit 1
    }
    repository='@@REPOSITORY@@'
    setup='@@SETUP@@'
    temporary=$(mktemp -d)
    trap 'status=$?; rm -rf -- "$temporary" || :; exit "$status"' EXIT
    command -v curl >/dev/null || { echo "OLIS requires curl." >&2; exit 1; }
    base="https://github.com/$repository/releases/latest/download"
    curl -fsSL "$base/$setup" -o "$temporary/$setup"
    curl -fsSL "$base/SHA256SUMS" -o "$temporary/SHA256SUMS"
    expected=$(awk -v name="$setup" '
        $2 == name {
            count++
            if (NF != 2 || length($1) != 64 || $1 ~ /[^0-9a-fA-F]/) bad=1
            hash=$1
        }
        END { if (count != 1 || bad) exit 1; print hash }
    ' "$temporary/SHA256SUMS") || {
        echo "The native setup has no unique valid checksum entry." >&2
        exit 1
    }
    printf '%s  %s\n' "$expected" "$temporary/$setup" | sha256sum --check --status || {
        echo "Native setup checksum verification failed. Rerun the one-line install command." >&2
        exit 1
    }
    chmod +x "$temporary/$setup"
    # > Give a piped OLIS's setup access to the terminal for normal prompts.
    if [ -z "${BASH_SOURCE[0]-}" ] && { exec 3</dev/tty; } 2>/dev/null; then
        "$temporary/$setup" <&3
    else
        "$temporary/$setup"
    fi
)
