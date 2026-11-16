# ruff: noqa: F401
"""Installation authority discovery, strict persistence and coordination."""

from apprc.user_files.installation.codec import (
    decode_cleanup_inventory,
    encode_cleanup_inventory,
)
from apprc.user_files.installation.inventory import symlink_revision
