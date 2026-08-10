"""Structured error taxonomy for source access.

Callers branch on the *kind* of failure, never on a message string. The distinction that matters
downstream is: can this run continue with what it already has (DP-15, degrade rather than break),
or is the data genuinely absent?
"""

from __future__ import annotations


class SourceError(RuntimeError):
    """Base for anything that went wrong reaching or reading a source."""

    def __init__(self, message: str, *, source: str, resource: str, key: str | None = None) -> None:
        super().__init__(message)
        self.source = source
        self.resource = resource
        self.key = key


class SourceUnavailableError(SourceError):
    """Transport failed, or the server errored, after every retry was exhausted."""


class SourceRateLimitedError(SourceUnavailableError):
    """The server told us to slow down. Distinct because the correct response is to back off."""


class SourceNotFoundError(SourceError):
    """The server answered, and the resource does not exist. Retrying will not help."""


class SourceContractError(SourceError):
    """The response arrived but did not look like what the adapter expects.

    This is the one that matters most: a silently changed upstream shape is how a pipeline starts
    producing confident nonsense.
    """


class OfflineWithoutSnapshotError(SourceError):
    """Offline mode was requested and no bronze snapshot exists to fall back on."""
