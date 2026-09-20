#!/usr/bin/env python3
"""
Build script for the Yusufo9 profile README.

1. Fetches live GitHub metrics for the configured user via the GraphQL API
   (stars, public repos, followers, following, forks, commits, streaks).
2. Downloads the avatar and inlines it as a base64 data URI
   (SVGs rendered inside a README cannot load external resources).
3. Injects everything into the templates in /templates and writes the
   production SVGs to /dist.

Usage:
    GITHUB_TOKEN=... python scripts/update_stats.py

Without GITHUB_TOKEN the script falls back to `gh auth token` for local runs.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
DIST = ROOT / "dist"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
USERNAME = CONFIG["username"]

GRAPHQL_URL = "https://api.github.com/graphql"


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
        if token:
            return token
    except (OSError, subprocess.CalledProcessError):
        pass
    sys.exit("error: no GITHUB_TOKEN / GH_TOKEN set and `gh auth token` unavailable")


TOKEN = get_token()
SESSION = requests.Session()
SESSION.headers.update(
    {
        "Authorization": f"bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-profile-readme",
    }
)


def gql(query: str, variables: dict) -> dict:
    resp = SESSION.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
USER_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    createdAt
    avatarUrl(size: 200)
    followers { totalCount }
    following { totalCount }
    gists(privacy: PUBLIC) { totalCount }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { stargazerCount forkCount }
    }
  }
}
"""

CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_user() -> dict:
    stars = forks = 0
    after = None
    base = None
    while True:
        data = gql(USER_QUERY, {"login": USERNAME, "after": after})["user"]
        base = base or data
        repos = data["repositories"]
        stars += sum(n["stargazerCount"] for n in repos["nodes"])
        forks += sum(n["forkCount"] for n in repos["nodes"])
        if not repos["pageInfo"]["hasNextPage"]:
            break
        after = repos["pageInfo"]["endCursor"]

    return {
        "created_at": datetime.fromisoformat(base["createdAt"].replace("Z", "+00:00")),
        "avatar_url": base["avatarUrl"],
        "followers": base["followers"]["totalCount"],
        "following": base["following"]["totalCount"],
        "gists": base["gists"]["totalCount"],
        "repos": base["repositories"]["totalCount"],
        "stars": stars,
        "forks": forks,
    }


def fetch_contributions(created_at: datetime) -> dict:
    """Walk every year since account creation and collect daily contributions."""
    now = datetime.now(timezone.utc)
    days: dict[date, int] = {}
    total_commits = 0
    total_contribs = 0

    start = created_at
    while start < now:
        end = min(start + timedelta(days=365), now)
        coll = gql(
            CONTRIB_QUERY,
            {"login": USERNAME, "from": start.isoformat(), "to": end.isoformat()},
        )["user"]["contributionsCollection"]
        total_commits += coll["totalCommitContributions"] + coll["restrictedContributionsCount"]
        total_contribs += coll["contributionCalendar"]["totalContributions"]
        for week in coll["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[date.fromisoformat(d["date"])] = d["contributionCount"]
        start = end + timedelta(seconds=1)

    return {
        "commits": total_commits,
        "total_contributions": total_contribs,
        **compute_streaks(days),
    }


def compute_streaks(days: dict[date, int]) -> dict:
    if not days:
        return {
            "current_streak": 0, "current_start": "", "current_end": "",
            "longest_streak": 0, "longest_start": "", "longest_end": "",
            "first_contribution": "",
        }

    ordered = sorted(days)
    first_active = next((d for d in ordered if days[d] > 0), None)

    # Longest streak
    longest = cur = 0
    longest_span = (None, None)
    cur_start = None
    for d in ordered:
        if days[d] > 0:
            cur = cur + 1 if cur else 1
            cur_start = cur_start or d
            if cur > longest:
                longest, longest_span = cur, (cur_start, d)
        else:
            cur, cur_start = 0, None

    # Current streak (today may still be empty, so allow it to start yesterday)
    today = ordered[-1]
    d = today if days.get(today, 0) > 0 else today - timedelta(days=1)
    current = 0
    current_end = d
    while days.get(d, 0) > 0:
        current += 1
        d -= timedelta(days=1)
    current_start = d + timedelta(days=1)

    return {
        "current_streak": current,
        "current_start": fmt(current_start) if current else "",
        "current_end": fmt(current_end) if current else "",
        "longest_streak": longest,
        "longest_start": fmt(longest_span[0]) if longest else "",
        "longest_end": fmt(longest_span[1]) if longest else "",
        "first_contribution": fmt(first_active) if first_active else "",
    }


def fmt(d: date | None) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ") if d else ""


def fetch_avatar_data_uri(url: str) -> str:
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    mime = resp.headers.get("Content-Type", "image/png").split(";")[0]
    return f"data:{mime};base64,{base64.b64encode(resp.content).decode()}"


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def esc(value) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render(template_name: str, out_name: str, values: dict) -> None:
    src = (TEMPLATES / template_name).read_text(encoding="utf-8")

    def sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"{template_name}: no value for placeholder {{{{{key}}}}}")
        return values[key]

    out = re.sub(r"\{\{([A-Z0-9_]+)\}\}", sub, src)
    DIST.mkdir(exist_ok=True)
    (DIST / out_name).write_text(out, encoding="utf-8", newline="\n")
    print(f"  wrote dist/{out_name}")


def badge_row(items: list[str], x: int, y: int, color: str, max_w: int = 600, gap: int = 8, char_w: int = 8) -> str:
    """Lay out pixel badges horizontally, wrapping to a new line if needed."""
    parts = []
    cx, cy = x, y
    for i, label in enumerate(items):
        w = len(label) * char_w + 22
        if cx + w > x + max_w:
            cx, cy = x, cy + 34
        parts.append(
            f'<g class="badge" style="animation-delay:{0.15 * i + 0.4:.2f}s">'
            f'<rect x="{cx}" y="{cy}" width="{w}" height="24" rx="2" fill="#0d1117" stroke="{color}" stroke-width="1.5" opacity="0.9"/>'
            f'<rect x="{cx + 4}" y="{cy + 8}" width="8" height="8" fill="{color}"/>'
            f'<text x="{cx + 17}" y="{cy + 16.5}" fill="{color}" font-size="12">{esc(label)}</text>'
            f"</g>"
        )
        cx += w + gap
    return "".join(parts)


def main() -> None:
    print(f"Fetching metrics for @{USERNAME} ...")
    user = fetch_user()
    contrib = fetch_contributions(user["created_at"])
    avatar = fetch_avatar_data_uri(user["avatar_url"])
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    stats = {
        "STARS": esc(user["stars"]),
        "REPOS": esc(user["repos"]),
        "FOLLOWERS": esc(user["followers"]),
        "FOLLOWING": esc(user["following"]),
        "FORKS": esc(user["forks"]),
        "COMMITS": esc(contrib["commits"]),
        "GISTS": esc(user["gists"]),
        "TOTAL_CONTRIBUTIONS": esc(contrib["total_contributions"]),
        "CURRENT_STREAK": esc(contrib["current_streak"]),
        "CURRENT_STREAK_RANGE": esc(
            f'{contrib["current_start"]} - {contrib["current_end"]}' if contrib["current_streak"] else "No active streak"
        ),
        "LONGEST_STREAK": esc(contrib["longest_streak"]),
        "LONGEST_STREAK_RANGE": esc(
            f'{contrib["longest_start"]} - {contrib["longest_end"]}' if contrib["longest_streak"] else "-"
        ),
        "CONTRIB_RANGE": esc(f'{contrib["first_contribution"] or fmt(user["created_at"].date())} - Present'),
        "UPDATED_AT": esc(updated),
    }
    print("  " + json.dumps({k: v for k, v in stats.items() if k != "UPDATED_AT"}))

    common = {
        "USERNAME": esc(USERNAME),
        "DISPLAY_NAME": esc(CONFIG["display_name"]),
        "TAGLINE": esc(CONFIG["tagline"]),
        "AVATAR_DATA_URI": avatar,
        **stats,
    }

    print("Rendering templates ...")
    render(
        "header.svg",
        "header.svg",
        {**common, "CORE_STACK_BADGES": badge_row(CONFIG["core_stack"], 250, 154, "#ffb454", max_w=610)},
    )
    render("stats.svg", "stats.svg", common)
    render(
        "stack.svg",
        "stack.svg",
        {
            **common,
            "DEVOPS_BADGES": badge_row(CONFIG["stack"]["devops_backend"], 40, 114, "#ffb454", max_w=270, char_w=7),
            "PROBLEM_BADGES": badge_row(CONFIG["stack"]["problem_solving"], 340, 114, "#ff5555", max_w=270, char_w=7),
            "WEB_BADGES": badge_row(CONFIG["stack"]["web_stack"], 640, 114, "#c5ff4a", max_w=220, char_w=7),
        },
    )

    pills = [
        ("pill-yusuf.svg", CONFIG["display_name"], "#ffb454"),
        ("pill-chaotic.svg", "chaotic_yusuf", "#ff5555"),
        ("pill-gmail.svg", "Gmail", "#c5ff4a"),
    ]
    for out_name, label, color in pills:
        width = len(label) * 9 + 50
        render(
            "pill.svg",
            out_name,
            {
                "LABEL": esc(label),
                "COLOR": color,
                "WIDTH": str(width),
                "INNER_W": str(width - 6),
                "TEXT_X": str((width + 22) // 2),
            },
        )
    print("Done.")


if __name__ == "__main__":
    main()
