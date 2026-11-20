"""Run confirmed updates outside the processes and environment they replace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO, TypedDict

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent))

from apprc.distribution.runtime._process_waiter import (
    _open_process_waiter,
    _wait_open_process,
)
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.installation._namespace_lock import namespace_lock


class UpdateWork(TypedDict):
    """One confirmed mutation and its optional editable preconditions."""

    command: list[str]
    workdir: str
    setup_digest: str | None
    authority: str
    revision: str
    current_head: str | None
    branch: str | None
    upstream: str | None
    candidate: str | None
    git: str | None
    sync: list[str]
    validate_environment: list[str]
    sync_retry: str
    registration_retry: str


def _git_value(git: str, cwd: Path, *args: str, env: Mapping[str, str]) -> str:
    return subprocess.run(
        [git, "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.rstrip("\n")


def run_update(
    work: UpdateWork, env: Mapping[str, str], *, output: TextIO | None = None
) -> int:
    """Apply a verified setup or finish the recorded Git, uv, registration sequence."""
    cwd = Path(work["workdir"])
    authority = Path(work["authority"])
    if work["setup_digest"] is not None:
        setup = Path(work["command"][0])
        assert_no_links(setup)
        with setup.open("rb") as stream:
            if (
                hashlib.file_digest(stream, "sha256").hexdigest()
                != work["setup_digest"]
            ):
                raise ValueError("The verified setup changed before execution.")
    else:
        git = work["git"]
        if git is None:
            raise ValueError("The editable update has no Git executable.")

        def require_directory(path: Path) -> None:
            assert_no_links(path)
            if not path.is_dir():
                raise ValueError("The recorded installation is unavailable.")

        with namespace_lock(
            authority.parent,
            prepare_directory=require_directory,
            guard_path=assert_no_links,
        ):
            assert_no_links(authority)
            if (
                hashlib.sha256(authority.read_bytes()).hexdigest()
                != work["revision"]
            ):
                raise ValueError("The installation changed. Run update again.")
            if (
                _git_value(
                    git,
                    cwd,
                    "status",
                    "--porcelain",
                    "--untracked-files=normal",
                    env=env,
                )
                or _git_value(git, cwd, "rev-parse", "HEAD", env=env)
                != work["current_head"]
                or _git_value(git, cwd, "symbolic-ref", "HEAD", env=env)
                != work["branch"]
                or _git_value(
                    git,
                    cwd,
                    "rev-parse",
                    "--symbolic-full-name",
                    "@{upstream}",
                    env=env,
                )
                != work["upstream"]
            ):
                raise ValueError(
                    "The checkout changed after confirmation. Run update again."
                )
            candidate = work["candidate"]
            if candidate is None:
                raise ValueError("The editable update has no confirmed commit.")
            if candidate != work["current_head"]:
                subprocess.run(
                    [git, "-C", str(cwd), "merge", "--ff-only", candidate],
                    check=True,
                    env=env,
                    stdout=output,
                )
                print(f"Git advanced to {candidate[:12]}.", flush=True)
            else:
                print("Git was already current.", flush=True)
            try:
                subprocess.run(
                    work["validate_environment"],
                    cwd=cwd,
                    check=True,
                    env=env,
                    stdout=output,
                )
            except (OSError, subprocess.CalledProcessError) as error:
                raise ValueError(
                    f"The checkout no longer selects the recorded environment. Restore its workspace layout or explicitly register the new environment from {cwd}."
                ) from error
            try:
                subprocess.run(
                    work["sync"],
                    cwd=cwd,
                    check=True,
                    env=env,
                    stdout=output,
                )
            except (OSError, subprocess.CalledProcessError) as error:
                raise ValueError(
                    f"Dependency sync failed. From {cwd}, retry {work['sync_retry']}."
                ) from error
            print("Dependencies synchronized.", flush=True)

    try:
        result = subprocess.run(
            work["command"], cwd=cwd, check=False, env=env, stdout=output
        )
        code = result.returncode
    except OSError as error:
        if work["setup_digest"] is not None:
            raise
        raise ValueError(
            f"Registration failed. From {cwd}, retry {work['registration_retry']}."
        ) from error
    if code and work["setup_digest"] is None:
        print(
            f"Registration failed. From {cwd}, retry {work['registration_retry']}.",
            file=sys.stderr,
            flush=True,
        )
    return code


def _main(plan_file: Path) -> int:
    """Acknowledge the handoff only after acquiring the original process handles."""
    stage = plan_file.parent
    try:
        assert_no_links(plan_file)
        payload = json.loads(plan_file.read_bytes())
        waiters = [
            _open_process_waiter(pid, start)
            for pid, start in payload["processes"]
        ]
        print("APPRC-UPDATE-READY", flush=True)
        if sys.stdin.readline() != "EXIT\n":
            return 1
        # > The first output stream is only for readiness. Use inherited stderr for results.
        sys.stdout = sys.stderr
        for waiter in waiters:
            _wait_open_process(waiter)
        return run_update(payload["work"], os.environ, output=sys.stderr)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Update failed: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(_main(Path(sys.argv[1])))
