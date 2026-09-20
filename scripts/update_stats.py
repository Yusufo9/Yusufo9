#!/usr/bin/env python3
"""
Build script for the Yusufo9 profile README.

Fills templates/profile.svg (the original GitAscii layout, converted to a
template) with live GitHub data and writes dist/profile.svg.

Dynamic parts:
  * avatar (inlined as base64 - SVGs inside a README cannot load external URLs)
  * GITHUB METRICS   - stars, repos, followers, following, forks, gists
  * STREAK STATS     - total contributions, current / longest streak
  * DNA card         - archetype percentages computed from contribution mix
  * Minecraft chat   - the user's most recent public GitHub events

Usage:
    GITHUB_TOKEN=... python scripts/update_stats.py

Without GITHUB_TOKEN it falls back to `gh auth token` for local runs.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
USERNAME = CONFIG["username"]
TEMPLATE = ROOT / "templates" / "profile.svg"
DIST = ROOT / "dist"

# widget ids inside templates/profile.svg (GitAscii layout, y = translate offset)
HEADER_WIDGET = "widget_1789911876234"   # avatar + repositories (y 0..260)
PILLS_WIDGET = "widget_1789912840027"    # social pills (y 268..312) - rendered as separate clickable images
STACK_WIDGETS = {"widget_1789911437611", "widget_1789914059752", "widget_1789911536345"}  # tech stack cards -> clickable tiles
BODY_TOP = (320, 524)                    # ABOUT // DOSSIER .. divider
BODY_BOTTOM = (758, 1380)                # GITHUB METRICS .. Minecraft terminal
README_TEMPLATE = ROOT / "templates" / "README.md"
ICONS = ROOT / "templates" / "icons"
FONTS = ROOT / "templates" / "fonts"
BAND_TEMPLATE = ROOT / "templates" / "band.svg"

API = "https://api.github.com"
NOW = datetime.now(timezone.utc)

# Minecraft chat palette
WHITE, GRAY, DARK = "#ffffff", "#aaaaaa", "#555555"
GREEN, YELLOW, AQUA = "#55ff55", "#ffff55", "#55ffff"
GOLD, RED, PINK = "#ffaa00", "#ff5555", "#ff55ff"


# --------------------------------------------------------------------------- #
# Auth / HTTP
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


SESSION = requests.Session()
SESSION.headers.update(
    {
        "Authorization": f"bearer {get_token()}",
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-profile-readme",
    }
)


def gql(query: str, variables: dict) -> dict:
    resp = SESSION.post(f"{API}/graphql", json={"query": query, "variables": variables}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def rest(path: str, **params) -> dict | list:
    resp = SESSION.get(f"{API}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
USER_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    createdAt
    avatarUrl(size: 260)
    followers { totalCount }
    following { totalCount }
    starredRepositories { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
    pinnedItems(first: 6, types: REPOSITORY) { nodes { ... on Repository { name } } }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC, orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { name description stargazerCount forkCount isFork isArchived pushedAt primaryLanguage { name color } }
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
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      totalRepositoryContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_user() -> dict:
    stars = forks = forked = 0
    languages: dict[str, int] = {}
    nodes: list[dict] = []
    after, base = None, None
    while True:
        data = gql(USER_QUERY, {"login": USERNAME, "after": after})["user"]
        base = base or data
        repos = data["repositories"]
        nodes.extend(repos["nodes"])
        for n in repos["nodes"]:
            stars += n["stargazerCount"]
            forks += n["forkCount"]
            forked += n["isFork"]
            if n["primaryLanguage"]:
                lang = n["primaryLanguage"]["name"]
                languages[lang] = languages.get(lang, 0) + 1
        if not repos["pageInfo"]["hasNextPage"]:
            break
        after = repos["pageInfo"]["endCursor"]

    profile = rest(f"/users/{USERNAME}")  # public_gists isn't exposed to GITHUB_TOKEN via GraphQL
    pinned = [n["name"] for n in base["pinnedItems"]["nodes"]]
    nodes.sort(key=lambda n: (n["name"] not in pinned, pinned.index(n["name"]) if n["name"] in pinned else 0))
    return {
        "repo_list": [n for n in nodes if not n["isArchived"]][:8],
        "created_at": datetime.fromisoformat(base["createdAt"].replace("Z", "+00:00")),
        "avatar_url": base["avatarUrl"],
        # REST is what github.com/<user> displays (GraphQL omits orgs / suspended accounts)
        "followers": profile.get("followers", base["followers"]["totalCount"]),
        "following": profile.get("following", base["following"]["totalCount"]),
        "starred": base["starredRepositories"]["totalCount"],
        "contributed_to": base["repositoriesContributedTo"]["totalCount"],
        "repos": profile.get("public_repos", base["repositories"]["totalCount"]),
        "stars": stars,
        "forks": forks,
        "forked_repos": forked,
        "gists": profile.get("public_gists", 0),
        "languages": languages,
        "top_language": max(languages, key=languages.get) if languages else "TypeScript",
    }


def fetch_contributions(created_at: datetime) -> dict:
    """Walk every year since account creation and collect daily contributions."""
    days: dict[date, int] = {}
    totals = {"commits": 0, "prs": 0, "issues": 0, "reviews": 0, "repos_created": 0, "contributions": 0}
    season_commits = 0

    start = created_at
    while start < NOW:
        end = min(start + timedelta(days=365), NOW)
        c = gql(CONTRIB_QUERY, {"login": USERNAME, "from": start.isoformat(), "to": end.isoformat()})["user"][
            "contributionsCollection"
        ]
        commits = c["totalCommitContributions"] + c["restrictedContributionsCount"]
        totals["commits"] += commits
        totals["prs"] += c["totalPullRequestContributions"]
        totals["issues"] += c["totalIssueContributions"]
        totals["reviews"] += c["totalPullRequestReviewContributions"]
        totals["repos_created"] += c["totalRepositoryContributions"]
        totals["contributions"] += c["contributionCalendar"]["totalContributions"]
        if end.year == NOW.year:
            season_commits += commits
        for week in c["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[date.fromisoformat(d["date"])] = d["contributionCount"]
        start = end + timedelta(seconds=1)

    return {**totals, "season_commits": season_commits, **compute_streaks(days)}


def compute_streaks(days: dict[date, int]) -> dict:
    empty = {"current": (0, None, None), "longest": (0, None, None), "first": None}
    if not days:
        return empty

    ordered = sorted(days)
    first_active = next((d for d in ordered if days[d] > 0), None)

    longest, cur, longest_span, cur_start = 0, 0, (None, None), None
    for d in ordered:
        if days[d] > 0:
            cur += 1
            cur_start = cur_start or d
            if cur > longest:
                longest, longest_span = cur, (cur_start, d)
        else:
            cur, cur_start = 0, None

    # today may still be empty, so the current streak is allowed to end yesterday
    today = ordered[-1]
    d = today if days.get(today, 0) > 0 else today - timedelta(days=1)
    current, current_end = 0, d
    while days.get(d, 0) > 0:
        current += 1
        d -= timedelta(days=1)

    return {
        "current": (current, d + timedelta(days=1), current_end) if current else (0, None, None),
        "longest": (longest, *longest_span),
        "first": first_active,
    }


def fetch_events() -> list[dict]:
    """Up to 300 most recent public events (GitHub keeps ~90 days)."""
    events: list[dict] = []
    try:
        for page in range(1, 4):
            batch = rest(f"/users/{USERNAME}/events/public", per_page=100, page=page)
            events.extend(batch)
            if len(batch) < 100:
                break
    except requests.HTTPError as exc:  # never let the activity feed break the build
        print(f"  warning: events unavailable ({exc})")
    return events


def fetch_avatar_data_uri(url: str) -> str:
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    mime = resp.headers.get("Content-Type", "image/png").split(";")[0]
    return f"data:{mime};base64,{base64.b64encode(resp.content).decode()}"


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def esc(value) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fmt_date(d: date | datetime | None) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ") if d else ""


def fmt_range(start: date | None, end: date | None) -> str:
    if not start:
        return "-"
    if start == end:
        return fmt_date(start)
    return f"{fmt_date(start)} - {fmt_date(end)}"


def ago(iso: str) -> str:
    delta = NOW - datetime.fromisoformat(iso.replace("Z", "+00:00"))
    s = int(delta.total_seconds())
    if s < 3600:
        return f"{max(1, s // 60)}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    if s < 86400 * 30:
        return f"{s // 86400}d ago"
    return f"{s // (86400 * 30)}mo ago"


def clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# Minecraft chat (recent GitHub events)
# --------------------------------------------------------------------------- #
MAX_LINE = 96  # 13px JetBrains Mono (0.6em advance) across the 776px chat viewport


def head_commit_message(repo: str, sha: str | None) -> str:
    """The events API no longer ships commit messages, so look the head commit up."""
    if not sha:
        return ""
    try:
        return rest(f"/repos/{repo}/commits/{sha}")["commit"]["message"].splitlines()[0]
    except (requests.HTTPError, KeyError, IndexError):
        return ""


def event_segments(ev: dict) -> list[tuple[str, str]]:
    """Translate one GitHub event into Minecraft-chat coloured segments."""
    me = f"@{USERNAME}"
    t = ev["type"]
    p = ev.get("payload", {})
    full = ev["repo"]["name"]
    repo = full.split("/", 1)[1] if full.lower().startswith(USERNAME.lower() + "/") else full

    if t == "PushEvent":
        n = p.get("size") or len(p.get("commits") or []) or 1
        msg = clip(head_commit_message(full, p.get("head")), 42)
        seg = [("<", WHITE), (me, GREEN), (f"> pushed {n} commit{'s' if n != 1 else ''} to ", WHITE), (repo, GOLD)]
        if msg:
            seg += [(f': "{msg}"', GRAY)]
        return seg
    if t == "PullRequestEvent":
        pr = p.get("pull_request", {})
        num, title = pr.get("number", "?"), clip(pr.get("title", ""), 36)
        if p.get("action") == "closed" and pr.get("merged"):
            return [("<", WHITE), (me, GREEN), (f"> Merged PR #{num} into ", WHITE), (repo, GOLD), (f': "{title}"', GRAY)]
        verb = p.get("action", "touched")
        return [("<", WHITE), (me, GREEN), (f"> {verb} PR #{num} in ", WHITE), (repo, GOLD), (f': "{title}"', GRAY)]
    if t == "CreateEvent":
        kind, ref = p.get("ref_type"), p.get("ref")
        if kind == "repository":
            return [("[World] ", YELLOW), (me, GREEN), (" generated a new world: ", YELLOW), (repo, GOLD)]
        return [("[World] ", YELLOW), (me, GREEN), (f" spawned {kind} ", YELLOW), (ref or "", AQUA), (" in ", YELLOW), (repo, GOLD)]
    if t == "DeleteEvent":
        return [("[World] ", YELLOW), (me, GREEN), (f" removed {p.get('ref_type')} ", YELLOW), (p.get("ref") or "", AQUA), (" from ", YELLOW), (repo, GOLD)]
    if t == "WatchEvent":
        return [("[STAR] ", AQUA), (me, GREEN), (" is now watching ", AQUA), (full, GOLD)]
    if t == "ForkEvent":
        return [("[Fork] ", PINK), (me, GREEN), (" forked ", PINK), (full, GOLD), (" -> ", PINK), (p.get("forkee", {}).get("full_name", ""), AQUA)]
    if t == "IssuesEvent":
        issue = p.get("issue", {})
        num, title = issue.get("number", "?"), clip(issue.get("title", ""), 36)
        if p.get("action") == "closed":
            return [("[!] Issue #", RED), (str(num), GOLD), (" was slain by ", RED), (me, GREEN), (" in ", RED), (repo, GOLD)]
        return [("[!] A wild Issue #", RED), (str(num), GOLD), (" appeared in ", RED), (repo, GOLD), (f': "{title}"', GRAY)]
    if t == "IssueCommentEvent":
        num = p.get("issue", {}).get("number", "?")
        body = clip(p.get("comment", {}).get("body", ""), 40)
        return [("<", WHITE), (me, GREEN), (f"> #{num} @ ", WHITE), (repo, GOLD), (f": {body}", GRAY)]
    if t == "PullRequestReviewEvent":
        num = p.get("pull_request", {}).get("number", "?")
        return [("[Advancement] ", PINK), (me, GREEN), (" reviewed PR #", YELLOW), (str(num), GOLD), (" in ", YELLOW), (repo, GOLD)]
    if t == "PullRequestReviewCommentEvent":
        num = p.get("pull_request", {}).get("number", "?")
        return [("<", WHITE), (me, GREEN), (f"> review note on PR #{num} in ", WHITE), (repo, GOLD)]
    if t == "ReleaseEvent":
        tag = p.get("release", {}).get("tag_name", "")
        return [("[Advancement] ", PINK), (me, GREEN), (" has completed the challenge ", YELLOW), (f"[Release {tag}]", PINK), (" in ", YELLOW), (repo, GOLD)]
    if t == "PublicEvent":
        return [("[Server] ", GRAY), (repo, GOLD), (" is now open to all players", YELLOW)]
    if t == "MemberEvent":
        return [("[Server] Player ", GRAY), ("@" + p.get("member", {}).get("login", "?"), GREEN), (" joined ", YELLOW), (repo, GOLD)]
    return [("[Server] ", GRAY), (me, GREEN), (f" triggered {t.removesuffix('Event')} in ", YELLOW), (repo, GOLD)]


def chat_line(segments: list[tuple[str, str]], y: int, delay_ms: int, bold: bool = False) -> str:
    # enforce the viewport width on the whole line, trimming from the end
    budget = MAX_LINE
    trimmed = []
    for text, color in segments:
        if budget <= 0:
            break
        if len(text) > budget:
            text = text[: max(0, budget - 1)].rstrip() + "…"
        trimmed.append((text, color))
        budget -= len(text)

    weight = ' font-weight="bold"' if bold else ""
    shadow = "".join(f'<tspan fill="#222222"{weight}>{esc(t)}</tspan>' for t, _ in trimmed)
    main = "".join(f'<tspan fill="{c}"{weight}>{esc(t)}</tspan>' for t, c in trimmed)
    return (
        f'<g transform="translate(0, {y})"><g class="mc-line" style="animation-delay: {delay_ms}ms">'
        f'<text class="mc-font chat-line" x="1" y="1">{shadow}</text>'
        f'<text class="mc-font chat-line" x="0" y="0">{main}</text>'
        f"</g></g>"
    )


def render_minecraft(user: dict, contrib: dict, events: list[dict]) -> tuple[str, str]:
    me = f"@{USERNAME}"
    lines: list[tuple[list[tuple[str, str]], bool]] = [
        ([("[Server] ", GRAY), ("Player ", YELLOW), (me, GREEN), (" joined the game ", YELLOW), (f"(Client: {user['top_language']})", GRAY)], False)
    ]
    for ev in events[:4]:
        lines.append((event_segments(ev) + [(f"  · {ago(ev['created_at'])}", DARK)], ev["type"] in ("ReleaseEvent", "PullRequestReviewEvent")))
    while len(lines) < 5:  # quiet account: pad with lore so the terminal never looks broken
        lines.append(([("[Server] ", GRAY), ("The world is quiet... ", DARK), (me, GREEN), (" is AFK (probably compiling)", DARK)], False))
    lines.append(
        ([("[System] Server uptime: 100% · Total Commits this season: ", GRAY), (str(contrib["season_commits"]), GREEN), ("  · Streak: ", GRAY), (f"{contrib['current'][0]}d", GOLD)], False)
    )

    chat = "".join(chat_line(seg, 26 * i, 120 * i + 200, bold) for i, (seg, bold) in enumerate(lines))
    latest = events[0] if events else None
    prompt = "&gt; /deploy --branch main --env production"
    if latest:
        prompt += f"  # last event {ago(latest['created_at'])}"
    return chat, prompt


# --------------------------------------------------------------------------- #
# DNA archetype card
# --------------------------------------------------------------------------- #
TRAITS = ["Builder", "Maintainer", "Open Source", "Community", "Explorer"]

# Every public GitHub event type maps to the characteristics it expresses.
# Points are summed per trait; the card shows each trait's share of all activity.
EVENT_TRAITS: dict[str, dict[str, int]] = {
    "PushEvent":                     {"Builder": 3},
    "CreateEvent":                   {"Builder": 1, "Explorer": 2},
    "DeleteEvent":                   {"Maintainer": 2},
    "PullRequestEvent":              {"Maintainer": 2, "Open Source": 1},
    "PullRequestReviewEvent":        {"Community": 3, "Maintainer": 1},
    "PullRequestReviewCommentEvent": {"Community": 2},
    "IssuesEvent":                   {"Maintainer": 2},
    "IssueCommentEvent":             {"Community": 2},
    "CommitCommentEvent":            {"Community": 2},
    "ReleaseEvent":                  {"Maintainer": 3},
    "GollumEvent":                   {"Maintainer": 2},
    "ForkEvent":                     {"Open Source": 3, "Explorer": 1},
    "WatchEvent":                    {"Explorer": 3},
    "PublicEvent":                   {"Open Source": 3},
    "MemberEvent":                   {"Community": 2},
    "SponsorshipEvent":              {"Community": 3},
}
FOREIGN_REPO_BONUS = {"Open Source": 3}  # any event in a repo you don't own

# Lifetime baseline from the contribution graph, so the card isn't only the last 90 days.
LIFETIME_TRAITS = {
    "commits":        {"Builder": 1},
    "prs":            {"Maintainer": 1, "Open Source": 1},
    "issues":         {"Maintainer": 1},
    "reviews":        {"Community": 2},
    "repos_created":  {"Explorer": 1},
    "contributed_to": {"Open Source": 3},
    "followers":      {"Community": 1},
    "starred":        {"Explorer": 1},
}


def compute_dna(user: dict, contrib: dict, events: list[dict]) -> list[tuple[str, int]]:
    points = dict.fromkeys(TRAITS, 0.0)

    for ev in events:
        for trait, w in EVENT_TRAITS.get(ev["type"], {"Explorer": 1}).items():
            points[trait] += w
        if not ev["repo"]["name"].lower().startswith(USERNAME.lower() + "/"):
            for trait, w in FOREIGN_REPO_BONUS.items():
                points[trait] += w

    source = {**contrib, "contributed_to": user["contributed_to"], "followers": user["followers"], "starred": user["starred"]}
    for key, traits in LIFETIME_TRAITS.items():
        for trait, w in traits.items():
            points[trait] += source.get(key, 0) * w

    total = sum(points.values()) or 1
    return [(trait, round(100 * points[trait] / total)) for trait in TRAITS]


def render_dna(dna: list[tuple[str, int]]) -> str:
    border, dim, amber, red, text, gold = "#3e2815", "#21262d", "#ffb454", "#ff5555", "#e5e5e5", "#ffbd2e"
    primary = max(dna, key=lambda kv: kv[1])[0].upper()
    frames = []
    for k in range(16):
        t = k / 15
        p = 1 - (1 - t) ** 2  # ease-out, like the original reveal
        # 44 columns: │ + 2 + label 12 + bar 14 + 1 + pct 4 + 9 + │
        rows = []
        for label, pct in dna:
            v = round(pct * p)
            filled = round(v * 14 / 100)
            rows.append(
                f'<tspan fill="{border}">│</tspan>  <tspan fill="{text}">{label:<12}</tspan>'
                f'<tspan fill="{amber}">{"█" * filled}</tspan><tspan fill="{dim}">{" " * (14 - filled)}</tspan> '
                f'<tspan fill="{red}" font-weight="bold">{v:>3}%</tspan>{" " * 9}<tspan fill="{border}">│</tspan>'
            )
        hr = f'<tspan fill="{border}">│</tspan>  <tspan fill="{border}">{"─" * 40}</tspan><tspan fill="{border}">│</tspan>'
        body = [
            f'<tspan fill="{border}">┌{"─" * 42}┐</tspan>',
            f'<tspan fill="{border}">│</tspan>{" " * 20}<tspan fill="{amber}" font-weight="bold">DNA</tspan>{" " * 19}<tspan fill="{border}">│</tspan>',
            hr,
            *rows,
            hr,
            f'<tspan fill="{border}">│</tspan>  <tspan fill="{gold}" font-weight="bold">PRIMARY ARCHETYPE</tspan>{" " * 23}<tspan fill="{border}">│</tspan>',
            f'<tspan fill="{border}">│</tspan>  <tspan fill="{amber}" font-weight="bold">&gt; THE {primary}</tspan>{" " * (34 - len(primary))}<tspan fill="{border}">│</tspan>',
            f'<tspan fill="{border}">└{"─" * 42}┘</tspan>',
        ]
        frames.append(
            f'<g class="frame-{k}">'
            + "".join(f'<text x="20" y="{25 + 17 * i}">{line}</text>' for i, line in enumerate(body))
            + "</g>"
        )
    return "\n".join(frames)


# --------------------------------------------------------------------------- #
# Repositories carousel (header card, replaces the old CORE STACK pills)
# --------------------------------------------------------------------------- #
CARD_W, CARD_H, CARD_PITCH = 492, 56, 64
REPO_ICON = (
    "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 "
    "0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 "
    "0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 "
    ".25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z"
)


def repo_card(repo: dict, y: int) -> str:
    lang = repo.get("primaryLanguage") or {}
    desc = clip(repo.get("description") or "No description yet", 50)
    meta = f"★ {repo['stargazerCount']}   ⑂ {repo['forkCount']}"
    parts = [
        f'<g class="repo-card" transform="translate(0, {y})">',
        f'<rect width="{CARD_W}" height="{CARD_H}" rx="10" fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.1)"/>',
        f'<g transform="translate(16, 14) scale(1.1)"><path fill="#8b949e" d="{REPO_ICON}"/></g>',
        f'<text x="44" y="24" fill="#f5f5f5" font-size="15" font-weight="700">{esc(repo["name"])}</text>',
        f'<text x="44" y="43" fill="rgba(255,255,255,0.55)" font-size="12">{esc(desc)}</text>',
        f'<text x="{CARD_W - 16}" y="43" text-anchor="end" fill="rgba(255,255,255,0.5)" font-size="12">{esc(meta)}</text>',
    ]
    if lang:
        parts += [
            f'<circle cx="{CARD_W - 16 - 4}" cy="20" r="4" fill="{lang.get("color") or "#8b949e"}"/>',
            f'<text x="{CARD_W - 16 - 14}" y="24" text-anchor="end" fill="rgba(255,255,255,0.75)" font-size="12">{esc(lang["name"])}</text>',
        ]
    parts.append("</g>")
    return "".join(parts)


def render_repos(repos: list[dict]) -> dict[str, str]:
    if not repos:
        repos = [{"name": "No public repositories yet", "description": "The world is still being generated...", "stargazerCount": 0, "forkCount": 0}]
    track_h = CARD_PITCH * len(repos)
    loop = repos + repos  # second copy makes the scroll seamless
    cards = "".join(repo_card(r, CARD_PITCH * i) for i, r in enumerate(loop))
    return {
        "REPO_CARDS": cards,
        "REPO_TRACK_HEIGHT": str(track_h),
        "REPO_SCROLL_SECONDS": str(max(6, 3 * len(repos))),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    print(f"Fetching data for @{USERNAME} ...")
    user = fetch_user()
    contrib = fetch_contributions(user["created_at"])
    events = fetch_events()
    avatar = fetch_avatar_data_uri(user["avatar_url"])
    dna = compute_dna(user, contrib, events)
    chat, prompt = render_minecraft(user, contrib, events)

    cur_n, cur_s, cur_e = contrib["current"]
    lon_n, lon_s, lon_e = contrib["longest"]
    values = {
        "AVATAR_DATA_URI": avatar,
        "STARS": esc(user["stars"]),
        "REPOS": esc(user["repos"]),
        "FOLLOWERS": esc(user["followers"]),
        "FOLLOWING": esc(user["following"]),
        "FORKS": esc(user["forks"]),
        "GISTS": esc(user["gists"]),
        "TOTAL_CONTRIBUTIONS": esc(contrib["contributions"]),
        "CONTRIB_RANGE": esc(f"{fmt_date(contrib['first'] or user['created_at'])} - Present"),
        "CURRENT_STREAK": esc(cur_n),
        "CURRENT_STREAK_RANGE": esc(fmt_range(cur_s, cur_e)),
        "LONGEST_STREAK": esc(lon_n),
        "LONGEST_STREAK_RANGE": esc(fmt_range(lon_s, lon_e)),
        "MC_CHAT_LINES": chat,
        "MC_PROMPT": prompt,
        "DNA_FRAMES": render_dna(dna),
        "UPDATED_AT": esc(NOW.strftime("%Y-%m-%d %H:%M UTC")),
        **render_repos(user["repo_list"]),
    }
    summary = {k: v for k, v in values.items() if k not in ("AVATAR_DATA_URI", "MC_CHAT_LINES", "DNA_FRAMES", "REPO_CARDS")}
    print(f"  repos: {[r['name'] for r in user['repo_list']]}")
    print("  " + json.dumps(summary, ensure_ascii=False))
    print("  DNA " + ", ".join(f"{k} {v}%" for k, v in dna))
    print(f"  events: {len(events)} -> {[e['type'] for e in events[:4]]}")

    src = TEMPLATE.read_text(encoding="utf-8")

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"no value for placeholder {{{{{key}}}}}")
        return values[key]

    write_outputs(re.sub(r"\{\{([A-Z0-9_]+)\}\}", sub, src))


# --------------------------------------------------------------------------- #
# Output: the profile is one GitAscii canvas, but links inside an <img> are dead
# on GitHub, so the social pill row is emitted as separate images the README
# wraps in <a> tags. Everything else keeps its exact original layout.
# --------------------------------------------------------------------------- #
WIDGET_RE = re.compile(r'^    <g transform="translate\((\d+), (\d+)\)" id="widget-(widget_\d+)">', re.M)


def split_widgets(svg: str) -> tuple[str, list[tuple[int, int, str, str]], str]:
    """Return (global <style>, [(x, y, id, markup)], footer) from the canvas."""
    style = re.search(r"<style>.*?</style>", svg, re.S).group(0)
    starts = list(WIDGET_RE.finditer(svg))
    footer_at = svg.index('  <text x="792"')
    widgets = []
    for i, m in enumerate(starts):
        stop = starts[i + 1].start() if i + 1 < len(starts) else footer_at
        widgets.append((int(m.group(1)), int(m.group(2)), m.group(3), svg[m.start():stop].rstrip() + "\n"))
    footer = svg[footer_at:svg.rindex("</svg>")]
    return style, widgets, footer


def font_css() -> str:
    """@font-face rules with the woff2 files inlined (an <img> SVG cannot fetch fonts)."""
    rules = []
    for weight, file in ((400, "JetBrainsMono-Regular.woff2"), (700, "JetBrainsMono-Bold.woff2")):
        path = FONTS / file
        if path.exists():
            b64 = base64.b64encode(path.read_bytes()).decode()
            rules.append(
                f"@font-face{{font-family:'JetBrains Mono';font-style:normal;font-weight:{weight};"
                f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
            )
    return "<style>" + "".join(rules) + "</style>" if rules else ""


FONT_CSS = font_css()


def canvas(style: str, body: str, width: int, height: int, fonts: bool = True) -> str:
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        f'{FONT_CSS if fonts else ""}{style}\n{body}{"" if body.endswith(chr(10)) else chr(10)}</svg>\n'
    )


def shift(markup: str, dy: int) -> str:
    return re.sub(
        r'^    <g transform="translate\((\d+), (\d+)\)"',
        lambda m: f'    <g transform="translate({m.group(1)}, {int(m.group(2)) - dy})"',
        markup, count=1, flags=re.M,
    )


def write(name: str, content: str) -> None:
    DIST.mkdir(exist_ok=True)
    (DIST / name).write_text(content, encoding="utf-8", newline="\n")
    print(f"  wrote dist/{name} ({len(content) // 1024} KB)")


def write_outputs(svg: str) -> None:
    style, widgets, footer = split_widgets(svg)
    by_id = {w[2]: w for w in widgets}

    # 1. header, split in two so each half can be a link (profile / repositories tab)
    header = by_id[HEADER_WIDGET][3]
    for name, x0, w in (("header-avatar.svg", 0, 260), ("header-repos.svg", 260, 540)):
        write(name, (
            f'<svg width="{w}" height="260" viewBox="{x0} 0 {w} 260" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
            f'{FONT_CSS if x0 else ""}{style}\n{header}</svg>\n'
        ))

    # 2. social pills, one file each so the README can link them
    pills_svg = by_id[PILLS_WIDGET][3]
    defs = re.search(r"<defs>.*?</defs>", pills_svg, re.S).group(0)
    for m in re.finditer(r'    <g id="pill-([a-z]+)-(\d+)-\d+">.*?\n    </g>', pills_svg, re.S):
        name, x = m.group(1), int(m.group(2))
        width = int(re.search(r'<rect x="%d" y="2" width="(\d+)"' % x, m.group(0)).group(1)) + 2
        pill = (
            f'<svg width="{width}" height="48" viewBox="{x - 1} 0 {width} 48" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
            f"{style}\n{defs}\n{m.group(0)}\n</svg>\n"
        )
        write(f"pill-{name}.svg", pill)

    # 3. body, split around the tech stack so the stack can be real links
    skip = STACK_WIDGETS | {HEADER_WIDGET, PILLS_WIDGET}
    top = "".join(shift(w[3], BODY_TOP[0]) for w in widgets if BODY_TOP[0] <= w[1] < BODY_TOP[1] and w[2] not in skip)
    write("body-top.svg", canvas(style, top, 800, BODY_TOP[1] - BODY_TOP[0]))
    body_footer = re.sub(r'y="(\d+)"', lambda m: f'y="{int(m.group(1)) - BODY_BOTTOM[0]}"', footer, count=1)
    bottom = "".join(shift(w[3], BODY_BOTTOM[0]) for w in widgets if w[1] >= BODY_BOTTOM[0])
    write("body-bottom.svg", canvas(style, bottom + body_footer, 800, BODY_BOTTOM[1] - BODY_BOTTOM[0]))

    # 4. tech stack tiles + README
    write_readme(write_stack_tiles())


# --------------------------------------------------------------------------- #
# Tech stack: the original cards are rebuilt from small tiles so every icon can
# be an <a> in the README. Tile widths are percentages of the 800px canvas, so
# the rows scale exactly like the SVG bands above and below (mobile included).
# --------------------------------------------------------------------------- #
CANVAS_W = 800
BG, BORDER, LABEL = "#060606", "#252525", "#7a7a7a"
TILE_STYLE = (
    "<style>.tile{opacity:0;animation:tile-in .6s cubic-bezier(.22,1,.36,1) forwards}"
    "@keyframes tile-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}</style>"
)
MONO = "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace"


def pct(w: float) -> str:
    return f"{w * 100 / CANVAS_W:.3f}%"


def tile_svg(w: int, h: int, inner: str, top=False, bottom=False, left=False, right=False, fonts=False) -> str:
    edges = []
    if top:
        edges.append(f'<rect x="0" y="0" width="{w}" height="1" fill="{BORDER}"/>')
    if bottom:
        edges.append(f'<rect x="0" y="{h - 1}" width="{w}" height="1" fill="{BORDER}"/>')
    if left:
        edges.append(f'<rect x="0" y="0" width="1" height="{h}" fill="{BORDER}"/>')
    if right:
        edges.append(f'<rect x="{w - 1}" y="0" width="1" height="{h}" fill="{BORDER}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'{FONT_CSS if fonts else ""}{TILE_STYLE}<rect width="{w}" height="{h}" fill="{BG}"/>{"".join(edges)}{inner}</svg>\n'
    )


def icon_markup(name: str, x: int, y: int, size: int) -> str:
    src = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    body = re.search(r"<svg[^>]*>(.*)</svg>", src, re.S).group(1)
    return f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 256 256" fill="none">{body}</svg>'


def write_stack_tiles() -> list[list[dict]]:
    """Emit dist/stack/*.svg; return README rows: [[{file,w,url?,alt}, ...], ...]."""
    (DIST / "stack").mkdir(parents=True, exist_ok=True)
    label_h = 44
    lines: list[list[dict]] = []

    for row in CONFIG["stack"]:
        header_line: list[dict] = []
        icon_line: list[dict] = []
        for card in row:
            slug = re.sub(r"[^a-z0-9]+", "-", card["label"].lower()).strip("-")
            w, icon, pitch = card["width"], card["icon"], card["pitch"]
            body_h = card["height"] - label_h
            items = card["items"]

            # card header: label on its own full-width tile (top border + sides)
            label = (
                f'<text class="tile" x="24" y="32" fill="{LABEL}" font-family="{MONO}" '
                f'font-size="13" font-weight="500" letter-spacing="2">{esc(card["label"])}</text>'
            )
            f = f"stack/{slug}.svg"
            write(f, tile_svg(w, label_h, label, top=True, left=True, right=True, fonts=True))
            header_line.append({"file": f, "w": w, "alt": card["label"]})

            # icon strip: same geometry as the original strip (left padded or centered)
            strip_w = (len(items) - 1) * pitch + icon
            pad_l = (w - strip_w) // 2 if card.get("align") == "center" else 24
            pad_r = w - pad_l - strip_w
            for i, item in enumerate(items):
                first, last = i == 0, i == len(items) - 1
                tw = icon + (pitch - icon) + (pad_l if first else 0) + (pad_r - (pitch - icon) if last else 0)
                x = pad_l if first else 0
                inner = f'<g class="tile" style="animation-delay:{120 + 70 * i}ms">{icon_markup(item["icon"], x, 0, icon)}</g>'
                f = f"stack/{slug}-{item['icon']}.svg"
                write(f, tile_svg(tw, body_h, inner, bottom=True, left=first, right=last))
                icon_line.append({"file": f, "w": tw, "url": item["url"], "alt": item.get("name", item["icon"])})
        lines += [header_line, icon_line]
    return lines


def write_bands() -> str:
    """Optional themed text sections from config['bands'] -> dist/band-<id>.svg + README html."""
    html = []
    template = BAND_TEMPLATE.read_text(encoding="utf-8") if BAND_TEMPLATE.exists() else ""
    for band in CONFIG.get("bands", []):
        lines = band.get("lines", [])
        line_h = 22
        height = 44 + line_h * len(lines) + (14 if lines else 0)
        body = "".join(
            f'<text class="anim-target" x="24" y="{58 + line_h * i}" font-size="13" fill="{esc(band.get("color", "#e5e5e5"))}" '
            f'style="animation-delay: {450 + 90 * i}ms">{esc(line)}</text>'
            for i, line in enumerate(lines)
        )
        svg = (
            template.replace("{{FONT_CSS}}", FONT_CSS)
            .replace("{{HEIGHT}}", str(height)).replace("{{INNER_H}}", str(height - 2))
            .replace("{{TITLE}}", esc(band.get("title", "")))
            .replace("{{RIGHT}}", esc(band.get("right", "")))
            .replace("{{ACCENT}}", esc(band.get("accent", "#c5ff4a")))
            .replace("{{BODY}}", body)
        )
        file = f"band-{band['id']}.svg"
        write(file, svg)
        img = f'<img src="./dist/{file}" alt="{esc(band.get("title", band["id"]))}" width="100%">'
        html.append(f'<a href="{esc(band["url"])}">{img}</a>' if band.get("url") else img)
    return "\n".join(html)


def write_readme(lines: list[list[dict]]) -> None:
    html = []
    for line in lines:
        imgs = []
        for t in line:
            img = f'<img src="./dist/{t["file"]}" alt="{esc(t["alt"])}" title="{esc(t["alt"])}" width="{pct(t["w"])}" align="top">'
            imgs.append(f'<a href="{esc(t["url"])}">{img}</a>' if t.get("url") else img)
        html.append("<div>" + "".join(imgs) + "</div>")  # no whitespace between tiles -> no gaps

    readme = README_TEMPLATE.read_text(encoding="utf-8").replace("{{STACK}}", "\n".join(html))
    readme = readme.replace("{{BANDS}}", write_bands())
    for key, url in CONFIG["links"].items():
        readme = readme.replace("{{LINK_" + key.upper() + "}}", esc(url))
    (ROOT / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print("  wrote README.md")


if __name__ == "__main__":
    main()
