"""Open a URL in an existing macOS Google Chrome profile.

Usage:
    python3 -m scripts.open_chrome_profile
    python3 -m scripts.open_chrome_profile --url https://x.com/home --profile Default
    python3 -m scripts.open_chrome_profile --check-only --profile "Profile 1"

The script checks Chrome's local profile metadata only. It does not read cookies,
passwords, or site sessions, so it can confirm Chrome-account sign-in but cannot prove
that a specific website is authenticated.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_CHROME_USER_DATA_DIR = Path.home() / "Library/Application Support/Google/Chrome"
DEFAULT_WORKER_CHROME_USER_DATA_DIR = (
    Path.home() / "Library/Application Support/Stockball Market/Chrome"
)
DEFAULT_URL = "https://x.com/home"


@dataclass(frozen=True)
class ChromeProfileStatus:
    profile_directory: str
    profile_name: str | None
    signed_in: bool
    account_email: str | None


def discover_default_profile(user_data_dir: Path) -> str:
    """Return Chrome's last-used signed-in profile, falling back safely."""
    local_state = _load_local_state(user_data_dir)
    profile = local_state.get("profile", {})
    if not isinstance(profile, dict):
        profile = {}
    info_cache = profile.get("info_cache", {})
    if not isinstance(info_cache, dict):
        info_cache = {}

    candidates: list[str] = []
    last_used = _optional_string(profile.get("last_used"))
    if last_used:
        candidates.append(last_used)
    active = profile.get("last_active_profiles", [])
    if isinstance(active, list):
        candidates.extend(str(value) for value in active)
    candidates.extend(str(value) for value in info_cache)

    for candidate in dict.fromkeys(candidates):
        entry = info_cache.get(candidate, {})
        if (user_data_dir / candidate).is_dir() and isinstance(entry, dict):
            if entry.get("is_consented_primary_account"):
                return candidate
    for candidate in dict.fromkeys(candidates):
        if (user_data_dir / candidate).is_dir():
            return candidate
    raise ValueError(f"No usable Chrome profile found in: {user_data_dir}")


def load_profile_status(user_data_dir: Path, profile_directory: str) -> ChromeProfileStatus:
    profile_path = user_data_dir / profile_directory
    if not profile_path.is_dir():
        raise ValueError(f"Chrome profile does not exist: {profile_path}")

    local_state = _load_local_state(user_data_dir)

    profile_info = (
        local_state.get("profile", {})
        .get("info_cache", {})
        .get(profile_directory, {})
    )
    if not isinstance(profile_info, dict):
        profile_info = {}
    account_email = profile_info.get("user_name")
    return ChromeProfileStatus(
        profile_directory=profile_directory,
        profile_name=_optional_string(profile_info.get("name")),
        signed_in=bool(profile_info.get("is_consented_primary_account")),
        account_email=_optional_string(account_email),
    )


def _load_local_state(user_data_dir: Path) -> dict[str, object]:
    local_state_path = user_data_dir / "Local State"
    try:
        local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Chrome local state file does not exist: {local_state_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Chrome local state file is not valid JSON: {local_state_path}") from exc
    if not isinstance(local_state, dict):
        raise ValueError(f"Chrome local state must be an object: {local_state_path}")
    return local_state


def open_chrome_profile(
    *,
    url: str,
    profile_directory: str,
    user_data_dir: Path,
    chrome_application: str,
) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--url must be an absolute HTTP(S) URL")
    subprocess.run(
        [
            "open",
            "-n",
            "-a",
            chrome_application,
            "--args",
            f"--user-data-dir={user_data_dir}",
            f"--profile-directory={profile_directory}",
            url,
        ],
        check=True,
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open an existing signed-in Google Chrome profile")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"page to open, default: {DEFAULT_URL}")
    parser.add_argument(
        "--profile",
        help="Chrome profile directory; defaults to Chrome's last-used signed-in profile",
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        help="Chrome user-data directory",
    )
    parser.add_argument(
        "--dedicated-profile",
        action="store_true",
        help="use Stockball's persistent Chrome profile instead of your normal Chrome profile",
    )
    parser.add_argument("--chrome-application", default="Google Chrome")
    parser.add_argument("--check-only", action="store_true", help="do not launch Chrome")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.dedicated_profile:
            user_data_dir = args.user_data_dir or DEFAULT_WORKER_CHROME_USER_DATA_DIR
            user_data_dir.mkdir(parents=True, exist_ok=True)
            profile = args.profile or "Default"
            status = None
        else:
            user_data_dir = args.user_data_dir or DEFAULT_CHROME_USER_DATA_DIR
            profile = args.profile or discover_default_profile(user_data_dir)
            status = load_profile_status(user_data_dir, profile)
        if not args.check_only:
            open_chrome_profile(
                url=args.url,
                profile_directory=profile,
                user_data_dir=user_data_dir,
                chrome_application=args.chrome_application,
            )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Chrome profile launch failed: {exc}", file=sys.stderr)
        return 1

    if status is None:
        print(f"Using dedicated Stockball Chrome profile: {user_data_dir}")
        print("Sign in to X in this window once, then fully close this Chrome window before fetching.")
    else:
        state = "signed in" if status.signed_in else "not signed in"
        name = status.profile_name or status.profile_directory
        print(f"Chrome profile {name!r} ({status.profile_directory}) is {state}.")
        if status.account_email:
            print(f"Chrome account: {status.account_email}")
    if not args.check_only:
        print(f"Opened: {args.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
