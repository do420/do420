#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import math
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

USER = "do420"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = Path(__file__).resolve().parents[1] / "assets" / "paper.svg"

EXCLUDED_REPOS = {"microsoft/BitNet", "microsoft/promptflow"}
MAJOR_STAR_THRESHOLD = 1000
MAX_MAJOR_REPOS = 3

TOPICS = {
    "Accelerator portability": [
        "accelerator", "current_accelerator", "device_type", "device index",
        "privateuse1", "privateuse", "hardcoded \"cuda\"", "cuda", "npu", "ascend",
        "xpu", "dlpack"
    ],
    "PyTorch dispatch": [
        "dispatchkey", "dispatch_key", "custom_op", "torch._c", "__dlpack__",
        "autograd", "tensor.", "_tensor.py", "torch.library"
    ],
    "vLLM runtime & KV cache": [
        "kv pool", "kv-cache", "kv transfer", "lookup rpc", "lookupkey",
        "scheduler", "request thread", "cache miss", "paged_attention",
        "runtime", "socket", "zmq"
    ],
    "Dependency & build isolation": [
        "build-system.requires", "requirements.txt", "dependency",
        "pep 517", "isolated build", "torchvision", "dependencylistconsistency"
    ],
}

COLORS = ["#3859c8", "#1496a5", "#7254c9", "#cb7730", "#31845d"]


def api(path: str):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "do420-profile-paper",
            **({"Authorization": "Bearer " + TOKEN} if TOKEN else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def search_prs():
    q = urllib.parse.quote(f"author:{USER} is:pr is:public")
    return api(f"/search/issues?q={q}&per_page=100&sort=created&order=desc").get("items", [])


def search_issues_count():
    q = urllib.parse.quote(f"author:{USER} is:issue is:public")
    return int(api(f"/search/issues?q={q}&per_page=1").get("total_count", 0))


def pytorch_bot_merge(repo: str, number: int) -> bool:
    if repo != "pytorch/pytorch":
        return False
    try:
        comments = api(f"/repos/{repo}/issues/{number}/comments?per_page=100")
    except Exception:
        return False
    bodies = [(c.get("body") or "").lower() for c in comments]
    command = any("@pytorchbot merge" in b for b in bodies)
    started = any(
        "merge started" in b
        and "pytorch" in (c.get("user", {}).get("login", "").lower())
        for c, b in zip(comments, bodies)
    )
    return command and started


def load_data():
    cache = {}
    data = []
    for item in search_prs():
        url = item.get("html_url", "")
        m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
        if not m:
            continue
        repo, number = m.group(1), int(m.group(2))
        if repo in EXCLUDED_REPOS:
            continue
        pr = api(f"/repos/{repo}/pulls/{number}")
        if repo not in cache:
            cache[repo] = api(f"/repos/{repo}")
        meta = cache[repo]
        merged = bool(pr.get("merged_at"))
        if not merged and pr.get("state") == "closed":
            merged = pytorch_bot_merge(repo, number)
        data.append(
            {
                "repo": repo,
                "number": number,
                "title": pr.get("title") or item.get("title") or "",
                "body": pr.get("body") or item.get("body") or "",
                "state": pr.get("state") or "closed",
                "merged": merged,
                "created_at": pr.get("created_at") or item.get("created_at"),
                "updated_at": pr.get("updated_at") or item.get("updated_at"),
                "stars": int(meta.get("stargazers_count") or 0),
                "fork": bool(meta.get("fork")),
                "url": url,
            }
        )
    return sorted(data, key=lambda p: p.get("created_at") or "", reverse=True)


def focus_scores(prs):
    now = datetime.now(timezone.utc)
    scores = {}
    for topic, terms in TOPICS.items():
        total = 0.0
        for p in prs:
            stamp = p.get("updated_at") or p.get("created_at")
            if not stamp:
                continue
            age = max(
                0.0,
                (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds()
                / 86400,
            )
            decay = math.exp(-0.006 * age)
            corpus = f'{p["title"]} {p["body"]} {p["repo"]}'.lower()
            total += decay * min(3, sum(term in corpus for term in terms))
        scores[topic] = total
    return scores


def tx(
    x, y, s, size=10, fill="#161616", weight="400",
    anchor="start", family="Times New Roman, Times, serif",
):
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}px" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">'
        f"{html.escape(str(s), quote=True)}</text>"
    )


def shorten(text, n=72):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def render(prs):
    public_count = len(prs)
    open_count = sum(p["state"] == "open" for p in prs)
    issue_count = search_issues_count()

    major_map = {}
    for p in prs:
        if not p["fork"] and p["stars"] >= MAJOR_STAR_THRESHOLD:
            major_map[p["repo"]] = p
    major = sorted(major_map.values(), key=lambda p: p["stars"], reverse=True)[:MAX_MAJOR_REPOS]
    major_names = {p["repo"] for p in major}
    merged_major = sum(1 for p in prs if p["repo"] in major_names and p["merged"])

    scores = focus_scores(prs)
    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:4]
    max_score = max((v for _, v in top), default=1.0)

    s = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="790" viewBox="0 0 1000 790">',
        """<style>
.paper{font-family:"Times New Roman",Times,serif}
.sans{font-family:Arial,sans-serif}
.draw{stroke-dasharray:1600;stroke-dashoffset:1600;animation:draw 1.8s ease-out forwards}
.grow{transform-box:fill-box;transform-origin:left center;transform:scaleX(0);animation:grow .8s ease-out forwards}
.fade{animation:fade .45s ease-out both}
.pulse{animation:pulse 2.4s ease-in-out infinite}
@keyframes draw{to{stroke-dashoffset:0}}
@keyframes grow{to{transform:scaleX(1)}}
@keyframes fade{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:translateX(0)}}
@keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
@media(prefers-reduced-motion:reduce){.draw,.grow,.fade,.pulse{animation:none!important}.draw{stroke-dashoffset:0}.grow{transform:none!important}.fade{opacity:1}}
</style>""",
        '<rect width="1000" height="790" fill="#fffefa"/>',
        '<rect x="22" y="18" width="956" height="754" fill="none" stroke="#bfc3c8"/>',
        '<line x1="48" y1="54" x2="952" y2="54" stroke="#111" stroke-width="1.25"/>',
        tx(48, 46, "DO420-OSS · PROFILE EDITION", 11.5, "#5f6469", "700", family="Arial,sans-serif"),
        tx(952, 46, "PREPRINT", 11.5, "#5f6469", "700", "end", family="Arial,sans-serif"),
        tx(500, 85, "Longitudinal Analysis of Deniz Özcan's Open-Source Software Contributions",
           26.5, "#111", "700", "middle"),
        tx(500, 107, "Deniz Özcan  ·  Research Engineer", 17, "#222", "400", "middle"),
        tx(500, 125, f"Observed {datetime.now(timezone.utc).date().isoformat()}  ·  public GitHub data",
           12.0, "#62676b", "400", "middle", family="Arial,sans-serif"),
        tx(48, 153, "ABSTRACT", 11.5, "#111", "700", family="Arial,sans-serif"),
        tx(48, 169, "This profile summarizes public pull-request activity with emphasis on upstream participation,",
           13.0, "#2c2f32"),
        tx(48, 183, "recent technical focus, and activity over time. All displayed quantities are regenerated from GitHub.",
           13.0, "#2c2f32"),
        '<line x1="48" y1="197" x2="952" y2="197" stroke="#c9cdd1"/>',
    ]

    metrics = [
        (public_count, "PUBLIC PRs"),
        (open_count, "OPEN PRs"),
        (issue_count, "PUBLIC ISSUES"),
        (merged_major, "MERGED · MAJOR OSS"),
        (len(major), "MAJOR OSS REPOS"),
    ]
    xs = [48, 229, 410, 591, 772]
    ws = [169, 169, 169, 169, 180]
    for (n, label), x, w in zip(metrics, xs, ws):
        s += [
            f'<rect x="{x}" y="213" width="{w}" height="56" fill="#fbfbfa" stroke="#cbd0d4"/>',
            tx(x + 12, 239, n, 26, "#111", "700"),
            tx(x + 12, 256, label, 11.5, "#646a6f", "700", family="Arial,sans-serif"),
        ]

    left_x, left_w = 48, 560
    right_x, right_w = 644, 308

    s += [
        tx(left_x, 300, "1. CONTRIBUTION TRAJECTORY", 13.5, "#111", "700"),
        tx(left_x, 318, "Weekly count of public PRs in the observed corpus.", 12.0, "#454a4e"),
        '<rect x="62" y="335" width="532" height="118" fill="#fcfcfb" stroke="#d4d7da"/>',
        '<line x1="78" y1="439" x2="578" y2="439" stroke="#222"/>',
        '<line x1="78" y1="365" x2="578" y2="365" stroke="#e2e4e6"/>',
        '<line x1="78" y1="402" x2="578" y2="402" stroke="#e2e4e6"/>',
    ]

    buckets = Counter()
    for p in prs:
        if p.get("created_at"):
            dt = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
            monday = (dt - timedelta(days=dt.weekday())).date()
            buckets[monday] += 1
    ordered = sorted(buckets.items())
    if ordered:
        vmax = max(v for _, v in ordered)
        pts = []
        for i, (_, v) in enumerate(ordered):
            x = 84 if len(ordered) == 1 else 84 + 480 * i / (len(ordered) - 1)
            y = 439 - 74 * v / max(1, vmax)
            pts.append((x, y))
        d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"
        for a, b in zip(pts, pts[1:]):
            mx = (a[0] + b[0]) / 2
            d += f" C {mx:.1f} {a[1]:.1f}, {mx:.1f} {b[1]:.1f}, {b[0]:.1f} {b[1]:.1f}"
        s += [
            f'<path d="{d}" fill="none" stroke="#3859c8" stroke-width="3.4" class="draw"/>',
            f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="4.6" fill="#cb7730" class="pulse"/>',
        ]
    s += [
        tx(left_x, 468, "Figure 1. Weekly public pull-request activity.", 11.0, "#4e5358"),
        tx(left_x, 480, "The trajectory reflects contribution timing, not code volume or review quality.", 10.8, "#6a6f73"),
    ]

    s += [
        tx(right_x, 300, "2. METHOD", 13.5, "#111", "700"),
        tx(right_x, 318, "Public PRs are grouped by repository and weighted by recency", 12.0, "#454a4e"),
        tx(right_x, 331, "for the topical summary below.", 12.0, "#454a4e"),
        tx(right_x + right_w / 2, 357, "Sₜ = Σₑ∈E exp(−λΔtₑ) · Iₜ(e)", 15.5, "#111", "400", "middle"),
        tx(right_x + right_w / 2, 376, "E: observed contributions   ·   t: topic   ·   Iₜ(e): indicator",
           11.0, "#656b70", "400", "middle", family="Arial,sans-serif"),
        tx(right_x + right_w / 2, 388, "Δtₑ: contribution age   ·   λ: decay rate   ·   Sₜ: topic score",
           11.0, "#656b70", "400", "middle", family="Arial,sans-serif"),
        tx(right_x, 414, "Higher Sₜ indicates stronger recent evidence for topic t.", 11.5, "#4c5156"),
    ]

    s += [
        tx(left_x, 515, "3. TECHNICAL FOCUS", 13.5, "#111", "700"),
        tx(left_x, 533, "Specific recurring implementation themes in Deniz Özcan's public contributions.", 12.0, "#454a4e"),
    ]
    y = 553
    for i, (topic, val) in enumerate(top):
        width = 350 * (val / max_score if max_score else 0)
        s += [
            tx(left_x, y + 13, topic, 11.5, "#3f4449", family="Arial,sans-serif"),
            f'<rect x="{left_x+165}" y="{y}" width="345" height="18" fill="#e9ecef"/>',
            f'<rect x="{left_x+165}" y="{y}" width="{width:.1f}" height="18" fill="{COLORS[i]}" class="grow" style="animation-delay:{i*0.07:.2f}s"/>',
        ]
        y += 29
    s += [
        tx(left_x, 694, "Figure 2. Relative signal across specific implementation themes.", 11.0, "#4e5358"),
    ]

    selected = next(
        (p for p in prs if p["repo"] == "pytorch/pytorch" and p["number"] == 193943),
        None,
    )

    s += [
        tx(right_x, 468, "4. SELECTED OBSERVATION", 13.5, "#111", "700"),
        tx(right_x, 486, "One upstream contribution, shown in the same visual language as the paper.", 11.0, "#454a4e"),
    ]
    if selected:
        cy = 501
        label = "pytorch/pytorch #193943"
        title = shorten(selected["title"], 48)
        s.append(
            '<g class="fade">'
            f'<rect x="{right_x}" y="{cy}" width="{right_w}" height="78" fill="#fbfbfa" stroke="#d2d5d8"/>'
            f'<rect x="{right_x}" y="{cy}" width="5" height="78" fill="{COLORS[0]}"/>'
            + tx(right_x + 14, cy + 20, label, 9.2, COLORS[0], "700", family="Arial,sans-serif")
            + tx(right_x + 14, cy + 45, title, 10.6, "#202327")
            + tx(right_x + 14, cy + 66, "MERGED", 10.0, "#5c6267", "700", family="Arial,sans-serif")
            + '</g>'
        )

    s += [
        '<line x1="48" y1="707" x2="952" y2="707" stroke="#c9cdd1"/>',
        tx(48, 727, "Notes", 10.0, "#111", "700", family="Arial,sans-serif"),
        tx(48, 742, "Public activity only. Major OSS repositories use a current ≥1,000-star threshold.", 10.5, "#5d6267"),
        tx(48, 755, "The figure is regenerated automatically from GitHub activity.", 10.5, "#5d6267"),
        tx(952, 727, "DO420", 10.5, "#111", "700", "end", family="Arial,sans-serif"),
        tx(952, 742, "research profile", 10.5, "#5d6267", "400", "end", family="Arial,sans-serif"),
        "</svg>",
    ]
    return "\n".join(s)


if __name__ == "__main__":
    prs = load_data()
    if not prs:
        raise SystemExit("No public PR data returned; refusing to overwrite the profile.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(prs), encoding="utf-8")
