"""Update check against GitHub Releases.

Only reads the "latest release" document and shows the release page. Nothing
is downloaded or installed by the app itself. Whatever the server sends is
treated as data: the version must parse, and the page URL must be an https
GitHub URL for the configured repository before it is ever opened.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from autoclick_pro import __version__
from autoclick_pro.winhttp import HttpError, http_get

# GitHub "owner/name" that publishes releases. Empty keeps update checks off.
UPDATE_REPO = ""

CHECK_INTERVAL_SECONDS = 7 * 24 * 3600
_VERSION_RE = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")

Fetcher = Callable[[str], bytes]


class UpdateError(Exception):
    """The check could not be completed; the message is safe to show."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    notes: str


def parse_version(text: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(text.strip()) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f"Not a release version: {text!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def is_valid_repo(repo: str) -> bool:
    return bool(_REPO_RE.match(repo or ""))


def api_url(repo: str) -> str:
    if not is_valid_repo(repo):
        raise UpdateError("The update source is not configured.")
    return f"https://api.github.com/repos/{repo}/releases/latest"


def releases_page(repo: str) -> str:
    return f"https://github.com/{repo}/releases/latest"


def is_safe_release_url(url: str, repo: str) -> bool:
    """True for https://github.com/<repo>/... only."""
    parts = urlsplit(url) if isinstance(url, str) else None  # Server data: may not be text.
    return bool(
        parts
        and parts.scheme == "https"
        and parts.hostname == "github.com"
        and parts.port is None
        and not parts.username
        and parts.path.lower().startswith(f"/{repo.lower()}/")
    )


def parse_release(document: bytes, repo: str) -> UpdateInfo:
    try:
        data = json.loads(document.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError("The update server sent an unreadable answer.") from exc
    if not isinstance(data, dict):
        raise UpdateError("The update server sent an unexpected answer.")
    tag = data.get("tag_name")
    try:
        version = ".".join(str(n) for n in parse_version(tag if isinstance(tag, str) else ""))
    except ValueError as exc:
        raise UpdateError("The latest release has no usable version number.") from exc
    page = data.get("html_url")
    url = page if isinstance(page, str) and is_safe_release_url(page, repo) else releases_page(repo)
    body = data.get("body")
    notes = body.strip()[:2000] if isinstance(body, str) else ""
    return UpdateInfo(version, url, notes)


def check_for_update(
    repo: str = UPDATE_REPO,
    current: str = __version__,
    fetch: Fetcher | None = None,
    *,
    url: str | None = None,
) -> UpdateInfo | None:
    """Return the newer release, or None when ``current`` is up to date."""
    target = url or api_url(repo)
    getter = fetch or (lambda u: http_get(u, user_agent=f"AutoClickPro/{current}"))
    try:
        document = getter(target)
    except HttpError as exc:
        raise UpdateError(f"Could not reach the update server: {exc}") from exc
    info = parse_release(document, repo)
    return info if is_newer(info.version, current) else None
