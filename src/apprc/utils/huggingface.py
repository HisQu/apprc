"""Optional Hugging Face sync helpers kept outside the core utils facade."""

from __future__ import annotations

# == Standard Library ========================
import logging
import os
from importlib import import_module
from pathlib import Path

LOG = logging.getLogger(__name__)


def sync_hf_repo_into(
    local_root: Path,
    repo_id: str,
    revision: str | None = None,
    allow_patterns: list[str] | str | None = None,
    ignore_patterns: list[str] | str | None = None,
) -> Path:
    """Pull a Hugging Face repo snapshot into a specific local folder.

    Uses ``snapshot_download(..., local_dir=...)`` so repeated pulls update a
    chosen folder while maintaining Hugging Face cache metadata below it.

    :param local_root: Target folder.
    :param repo_id: Hub repository id, for example ``"Org/name"``.
    :param revision: Branch, tag, or commit hash.
    :param allow_patterns: Optional glob patterns to include.
    :param ignore_patterns: Optional glob patterns to exclude.
    :return: The local root for convenience.
    """
    try:
        snapshot_download = getattr(
            import_module("huggingface_hub"),
            "snapshot_download",
        )
    except Exception as exc:
        raise RuntimeError(
            "huggingface_hub is required for Hugging Face sync. "
            "Install it as an optional runtime dependency to use this helper."
        ) from exc

    local_root.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=str(local_root),
        allow_patterns=allow_patterns,
        ignore_patterns=ignore_patterns,
    )
    return local_root


def sync_hf_if_configured(local_root: Path) -> None:
    """Sync from Hugging Face when ``OPA_RAG_HF_REPO`` is exported.

    :param local_root: Target folder for the configured repository.
    """
    repo_id = os.getenv("OPA_RAG_HF_REPO")
    if not repo_id:
        return

    revision = os.getenv("OPA_RAG_HF_REVISION") or None
    LOG.info(f"Syncing Hugging Face repo '{repo_id}' into '{local_root}'...")
    sync_hf_repo_into(
        local_root=local_root,
        repo_id=repo_id,
        revision=revision,
    )
