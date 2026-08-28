"""Credential resolution for MCP connections.

Servers reference credentials by name (``auth_ref``); the actual secret is
resolved at connection time by a :class:`CredentialResolver` and is never
stored in the registry or the domain model.
"""

from __future__ import annotations

import os
from typing import Protocol


class CredentialResolver(Protocol):
    def resolve(self, auth_ref: str) -> str | None: ...


class EnvCredentialResolver:
    """Reads the secret from the environment variable named by ``auth_ref``."""

    def resolve(self, auth_ref: str) -> str | None:
        return os.environ.get(auth_ref)
