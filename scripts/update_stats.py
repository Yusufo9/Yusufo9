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
OUTPUT = ROOT / "dist" / "profile.svg"

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
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC, orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { stargazerCount forkCount isFork primaryLanguage { name } }
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
    after, base = None, None
    while True:
        data = gql(USER_QUERY, {"login": USERNAME, "after": after})["user"]
        base = base or data
        repos = data["repositories"]
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
    return {
        "created_at": datetime.fromisoformat(base["createdAt"].replace("Z", "+00:00")),
        "avatar_url": base["avatarUrl"],
        "followers": base["followers"]["totalCount"],
        "following": base["following"]["totalCount"],
        "starred": base["starredRepositories"]["totalCount"],
        "contributed_to": base["repositoriesContributedTo"]["totalCount"],
        "repos": base["repositories"]["totalCount"],
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
    try:
        return rest(f"/users/{USERNAME}/events/public", per_page=60)
    except requests.HTTPError as exc:  # never let the activity feed break the build
        print(f"  warning: events unavailable ({exc})")
        return []


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
MAX_LINE = 104  # ~11px monospace across the 776px chat viewport


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
def score(value: float, cap: float) -> int:
    """0-100 on a log curve so a young account still shows some DNA."""
    if value <= 0:
        return 0
    return max(0, min(100, round(100 * math.log1p(value) / math.log1p(cap))))


def compute_dna(user: dict, contrib: dict) -> list[tuple[str, int]]:
    return [
        ("Builder", score(contrib["commits"], 600)),
        ("Maintainer", score(user["repos"] * 3 + contrib["prs"] * 2 + contrib["issues"], 120)),
        ("Open Source", score(user["contributed_to"] * 4 + user["stars"] * 2 + user["forked_repos"], 120)),
        ("Community", score(user["followers"] * 2 + user["following"] + contrib["reviews"] * 3 + contrib["issues"], 150)),
        ("Explorer", score(user["starred"] + len(user["languages"]) * 4 + user["repos"], 120)),
    ]


def render_dna(dna: list[tuple[str, int]]) -> str:
    border, dim, amber, red, text, gold = "#3e2815", "#21262d", "#ffb454", "#ff5555", "#e5e5e5", "#ffbd2e"
    primary = max(dna, key=lambda kv: kv[1])[0].upper()
    frames = []
    for k in range(16):
        t = k / 15
        p = 1 - (1 - t) ** 2  # ease-out, like the original reveal
        rows = []
        for label, pct in dna:
            v = round(pct * p)
            filled = round(v * 16 / 100)
            rows.append(
                f'<tspan fill="{border}">│</tspan>  <tspan fill="{text}">{label:<12}</tspan>'
                f'<tspan fill="{amber}">{"█" * filled}</tspan><tspan fill="{dim}">{" " * (16 - filled)}</tspan> '
                f'<tspan fill="{red}" font-weight="bold">{v:>3}%</tspan>{" " * 13}<tspan fill="{border}">│</tspan>'
            )
        hr = f'<tspan fill="{border}">│</tspan>  <tspan fill="{border}">{"─" * 46}</tspan><tspan fill="{border}">│</tspan>'
        body = [
            f'<tspan fill="{border}">┌{"─" * 48}┐</tspan>',
            f'<tspan fill="{border}">│</tspan>{" " * 23}<tspan fill="{amber}" font-weight="bold">DNA</tspan>{" " * 22}<tspan fill="{border}">│</tspan>',
            hr,
            *rows,
            hr,
            f'<tspan fill="{border}">│</tspan>  <tspan fill="{gold}" font-weight="bold">PRIMARY ARCHETYPE</tspan>{" " * 29}<tspan fill="{border}">│</tspan>',
            f'<tspan fill="{border}">│</tspan>  <tspan fill="{amber}" font-weight="bold">&gt; THE {primary}</tspan>{" " * (40 - len(primary))}<tspan fill="{border}">│</tspan>',
            f'<tspan fill="{border}">└{"─" * 48}┘</tspan>',
        ]
        frames.append(
            f'<g class="frame-{k}">'
            + "".join(f'<text x="20" y="{25 + 17 * i}">{line}</text>' for i, line in enumerate(body))
            + "</g>"
        )
    return "\n".join(frames)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    print(f"Fetching data for @{USERNAME} ...")
    user = fetch_user()
    contrib = fetch_contributions(user["created_at"])
    events = fetch_events()
    avatar = fetch_avatar_data_uri(user["avatar_url"])
    dna = compute_dna(user, contrib)
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
    }
    summary = {k: v for k, v in values.items() if k not in ("AVATAR_DATA_URI", "MC_CHAT_LINES", "DNA_FRAMES")}
    print("  " + json.dumps(summary, ensure_ascii=False))
    print("  DNA " + ", ".join(f"{k} {v}%" for k, v in dna))
    print(f"  events: {len(events)} -> {[e['type'] for e in events[:4]]}")

    src = TEMPLATE.read_text(encoding="utf-8")

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"no value for placeholder {{{{{key}}}}}")
        return values[key]

    out = re.sub(r"\{\{([A-Z0-9_]+)\}\}", sub, src)
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(out, encoding="utf-8", newline="\n")
    print(f"  wrote {OUTPUT.relative_to(ROOT)} ({len(out) // 1024} KB)")


if __name__ == "__main__":
    main()
