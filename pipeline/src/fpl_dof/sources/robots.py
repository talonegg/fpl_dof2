"""``robots.txt``, fetched and evaluated before anything else is requested (NFR-10).

**Why this is shared rather than written per adapter.** It is a compliance mechanism, and a
compliance mechanism implemented twice is a compliance mechanism that is implemented once and
approximately once. E5 shipped it inside the FBref adapter and the Understat adapter did not have
it at all — which was not visible until somebody enabled Understat and found the site now serves
``Disallow: /`` to everyone (D-23). One implementation, used by every scraped source, is what makes
"we respect robots.txt" a property of the project rather than of whichever adapter was written last.

The fetch goes through the shared :class:`~fpl_dof.sources.fetch.Fetcher` like every other request,
so the check is itself rate-limited, snapshotted and cached rather than being an extra unaccounted
request against somebody else's site.
"""

from __future__ import annotations

import urllib.robotparser
from typing import TYPE_CHECKING

from fpl_dof.sources.errors import SourceError

if TYPE_CHECKING:
    from fpl_dof.sources.base import IngestRequest, SourceAdapter

ROBOTS_RESOURCE = "robots"
ROBOTS_SUFFIX = ".txt.gz"


class RobotsDisallowedError(SourceError):
    """The site's own rules forbid the page. Not an error to retry, and not one to work around."""


def fetch_robots(
    adapter: SourceAdapter, request: IngestRequest
) -> urllib.robotparser.RobotFileParser:
    """Fetch and parse the site's crawling rules."""
    resource = adapter.resource(ROBOTS_RESOURCE)
    fetched = adapter.fetcher.fetch(
        adapter.url_for("robots.txt"),
        source=adapter.name,
        source_version=adapter.version,
        resource=resource.name,
        key=ROBOTS_RESOURCE,
        cache_ttl_seconds=resource.cache_ttl_seconds,
        force_refresh=request.force_refresh,
        offline=request.offline,
        now=request.now,
        suffix=ROBOTS_SUFFIX,
    )
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(fetched.payload.decode("utf-8", errors="replace").splitlines())
    return parser


def check_allowed(
    adapter: SourceAdapter, path: str, robots: urllib.robotparser.RobotFileParser
) -> None:
    """Raise unless the site permits this path. The wildcard agent, deliberately.

    Checking ``*`` rather than this project's own User-Agent is the conservative reading: a site
    that has not heard of us has still told us what it wants, and a rule written for everybody is
    written for us.
    """
    if not robots.can_fetch("*", adapter.url_for(path)):
        raise RobotsDisallowedError(
            f"robots.txt disallows {path}; the page is not fetched",
            source=adapter.name,
            resource=ROBOTS_RESOURCE,
            key=path,
        )


__all__ = [
    "ROBOTS_RESOURCE",
    "ROBOTS_SUFFIX",
    "RobotsDisallowedError",
    "check_allowed",
    "fetch_robots",
]
