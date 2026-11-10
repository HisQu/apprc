"""Side-effect-free identity extraction for immutable GitHub requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImmutableGitHubSource:
    """Raw source identity; transport and filesystem normalization stay with callers."""

    owner: str
    repository: str
    commit: str
    subdirectory: str | None

    @property
    def repository_url(self) -> str:
        """Return the HTTPS repository locator without changing its spelling."""
        return f"https://github.com/{self.owner}/{self.repository}"


def parse_immutable_github_source(
    requirement: str,
) -> ImmutableGitHubSource | None:
    """Extract one immutable GitHub identity without validating acquisition proof.

    Repository suffixes and project fragments are retained verbatim. Callers
    remain responsible for digest, RECORD and filesystem policy.

    :param requirement: Exact requirement, without trimming or URL decoding.
    :return: Raw identity for a full lowercase commit, otherwise ``None``.
    """
    if "\r" in requirement or "\n" in requirement:
        return None
    match = re.fullmatch(
        r"git\+https://github\.com/([^/@]+)/([^/@]+)@([0-9a-f]{40})"
        r"(?:#subdirectory=([^\\\x00\r\n]+))?",
        requirement,
    )
    if match is None:
        return None
    owner, repository, commit, subdirectory = match.groups()
    return ImmutableGitHubSource(owner, repository, commit, subdirectory)
