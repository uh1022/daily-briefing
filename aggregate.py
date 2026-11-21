"""把同一事件的多条报道合并成一组，并给每组打重点分。纯规则，不用大模型。"""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""
a an the and or of to in on for with by at from as is are was were be been has have had its it this that
into over after before amid as about than more most new says said say will can could may might not no
how why what when who which while up out off per vs via report reports today latest update news
""".split())

CJK = re.compile("[\u4e00-\u9fff]+")
WORD = re.compile(r"[a-z0-9]+")
CATEGORY_PRIORITY = ["explosives", "mining", "ai", "tech"]


def _norm_num(tok: str) -> str:
    # 111b / 111bn / 111 -> 111；去掉千分位影响
    m = re.fullmatch(r"(\d+)(b|bn|m|mn|k)?", tok)
    return m.group(1) if m else tok


def tokens(title: str) -> set[str]:
    t = title.lower().replace("’", "'")
    t = re.sub(r"'s\b", "", t)
    t = re.sub(r"(\d),(\d)", r"\1\2", t)
    out = set()
    for w in WORD.findall(t):
        if w in STOP or len(w) < 2:
            continue
        if w.endswith("s") and len(w) > 4 and not w.endswith("ss"):
            w = w[:-1]
        out.add(_norm_num(w))
    for run in CJK.findall(t):
        if len(run) == 1:
            out.add(run)
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    return out


def cluster(items: list[dict], keyword_weights: dict[str, float], threshold: float = 0.42) -> list[dict]:
    """items: 当天条目。返回按重点分排序的分组列表。"""
    toks = [tokens(i["title"]) for i in items]
    df = Counter(t for ts in toks for t in ts)
    n = max(len(items), 1)
    idf = {t: math.log(1 + n / c) for t, c in df.items()}

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    weight = [sum(idf[t] for t in ts) for ts in toks]
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            shared = toks[a] & toks[b]
            if len(shared) < 2:
                continue
            w = sum(idf[t] for t in shared)
            denom = min(weight[a], weight[b]) or 1
            same_src = items[a]["source"] == items[b]["source"] and (items[a].get("origin") or "") == (items[b].get("origin") or "")
            if w / denom >= (0.75 if same_src else threshold):
                parent[find(a)] = find(b)

    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)

    clusters = []
    for members in groups.values():
        its = [items[i] for i in members]
        publishers = {(i.get("origin") or i["source"]).strip().lower() for i in its}
        cats = Counter(i["category"] for i in its)
        top = max(cats.values())
        category = next(c for c in CATEGORY_PRIORITY + list(cats) if cats.get(c) == top)
        hits = sorted({h for i in its for h in i.get("hits", [])})
        kw_score = max((keyword_weights.get(h, 1.0) for h in hits), default=0.0)
        latest = max((i["published"] or "" for i in its), default="")
        # 代表标题：优先直接订阅源（有摘要），其次标题最短的一条
        rep = sorted(its, key=lambda i: (0 if i.get("summary") else 1, len(i["title"])))[0]
        score = 3.0 * len(publishers) + 2.0 * kw_score + (1.0 if rep.get("summary") else 0.0)
        clusters.append({
            "category": category,
            "title": rep["title"],
            "link": rep["link"],
            "items": [i["id"] for i in sorted(its, key=lambda i: i["published"] or "", reverse=True)],
            "sources": len(publishers),
            "hits": hits,
            "latest": latest or None,
            "score": round(score, 2),
        })
    clusters.sort(key=lambda c: (c["score"], c["latest"] or ""), reverse=True)
    for idx, c in enumerate(clusters):
        c["id"] = f"c{idx}"
    return clusters
