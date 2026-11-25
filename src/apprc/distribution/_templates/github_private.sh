#!/usr/bin/env bash
# One-line install script (OLIS) for a private GitHub release.
# Expected one-line install command template:
#   Stable: curl -fsSL <PUBLIC_SCRIPT_URL> | bash
#   Beta:   curl -fsSL <PUBLIC_SCRIPT_URL> | bash -s -- --beta
#   RC:     curl -fsSL <PUBLIC_SCRIPT_URL> | bash -s -- --release-candidate
# Requirements: Linux x86-64, Bash, GNU coreutils, awk, and gh authenticated with gh auth login.
# 1. Download the selected native setup executable and SHA256SUMS.
# 2. Verify the matching checksum before executing any downloaded file.
# 3. Run the native setup executable, which performs the installation.
# 4. Remove temporary downloads and return the native setup exit status.

(
    set -euo pipefail
    [ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || {
        echo "This OLIS requires Linux x86-64." >&2
        exit 1
    }
    repository='@@REPOSITORY@@'
    setup='@@SETUP@@'
    temporary=$(mktemp -d)
    trap 'status=$?; rm -rf -- "$temporary" || :; exit "$status"' EXIT
    command -v gh >/dev/null || { echo "OLIS requires gh and gh auth login." >&2; exit 1; }
    # == Select the release and prepare setup arguments
    # > Consume one installer channel flag and forward the other arguments in order.
    channel=
    regular_requested=false
    setup_args=()
    while (($#)); do
        case $1 in
            --) break ;;
            -b|--beta|-rc|--release-candidate)
                if [[ -n $channel ]]; then
                    echo "Choose one release channel: --beta or --release-candidate." >&2
                    exit 1
                fi
                case $1 in
                    -b|--beta) channel=b ;;
                    *) channel=rc ;;
                esac
                ;;
            --regular)
                regular_requested=true
                setup_args+=("$1")
                ;;
            *) setup_args+=("$1") ;;
        esac
        shift
    done
    set -- "${setup_args[@]}" "$@"

    release_tag_args=()
    if [[ -n $channel ]]; then
        if [[ $regular_requested == true ]]; then
            echo "A beta or RC install uses Preview and cannot be combined with --regular." >&2
            exit 1
        fi

        # > GitHub marks both channels as prereleases. The tag distinguishes them.
        if ! release_rows=$(gh api --paginate "repos/$repository/releases?per_page=100" \
            --jq '.[] | [.tag_name, .prerelease, .draft] | @tsv'); then
            echo "GitHub release lookup failed. Check gh auth login and repository access." >&2
            exit 1
        fi
        number='(0|[1-9][0-9]*)'
        tag_pattern="^v${number}\.${number}\.${number}${channel}${number}$"

        # > Compare digit groups numerically so b10 sorts after b2.
        selected_tag=$(
            while IFS=$'\t' read -r tag prerelease draft; do
                if [[ $prerelease == true && $draft == false && $tag =~ $tag_pattern ]]; then
                    printf '%s\n' "$tag"
                fi
            done <<< "$release_rows" | LC_ALL=C sort -V | tail -n 1
        )
        if [[ -z $selected_tag ]]; then
            echo "No published prerelease with a vX.Y.Z${channel}N tag was found in $repository." >&2
            exit 1
        fi
        release_tag_args=("$selected_tag")
        set -- --preview "$@"
    fi

    # > Fetch both assets from the same release. With no tag, gh selects latest stable.
    gh release download "${release_tag_args[@]}" \
        -R "$repository" -p "$setup" -p SHA256SUMS -D "$temporary"
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
    # > Forward setup options only after verifying the downloaded executable.
    chmod +x "$temporary/$setup"
    # > Give a piped OLIS's setup access to the terminal for normal prompts.
    if [ -z "${BASH_SOURCE[0]-}" ] && { exec 3</dev/tty; } 2>/dev/null; then
        "$temporary/$setup" "$@" <&3
    else
        "$temporary/$setup" "$@"
    fi
)
