#!/usr/bin/env python3
"""每日信息汇总：读取 sources.yaml 中的信息源，抓取新内容，生成静态网页。

用法：python briefing.py
输出：
  data/      历史数据（随仓库保存）
  site/      生成的网页（发布到 GitHub Pages）
"""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DAYS = DATA / "days"
SITE = ROOT / "site"
TEMPLATE = ROOT / "template" / "index.html"
STATE = DATA / "state.json"

BJ = timezone(timedelta(hours=8))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 30
NO_DATE_FIRST_RUN = 5  # 网页抓取的源首次运行时，只收前几条


# ---------------------------------------------------------------- 工具函数

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def item_key(link: str, title: str) -> str:
    base = (link or "").strip() or (title or "").strip()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def clean_text(raw: str, limit: int = 180) -> str:
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def news_url(query: str, lang: str, region: str | None) -> str:
    q = quote_plus(f"{query} when:2d")
    if lang == "zh":
        return f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    gl = region or "US"
    return f"https://news.google.com/rss/search?q={q}&hl=en-{gl}&gl={gl}&ceid={gl}:en"


def fetch(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.content


def to_dt(struct) -> datetime | None:
    if not struct:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------- 解析

def parse_rss(content: bytes, src: dict) -> list[dict]:
    fp = feedparser.parse(content)
    if not fp.entries:
        reason = getattr(fp, "bozo_exception", None)
        raise ValueError(f"没有读到条目{('：' + str(reason)[:80]) if reason else ''}")
    items = []
    is_news = src["type"] == "news"
    for e in fp.entries:
        title = clean_text(e.get("title", ""), 300)
        link = e.get("link", "")
        if not title or not link:
            continue
        origin = ""
        if is_news:
            origin = (e.get("source") or {}).get("title", "") if isinstance(e.get("source"), dict) else ""
            if origin and title.endswith(" - " + origin):
                title = title[: -len(origin) - 3].strip()
        summary = "" if is_news else clean_text(e.get("summary", "") or e.get("description", ""))
        published = to_dt(e.get("published_parsed") or e.get("updated_parsed"))
        items.append({
            "title": title,
            "link": link,
            "summary": summary,
            "origin": origin,
            "published": published,
        })
    return items


def parse_html(content: bytes, src: dict) -> list[dict]:
    soup = BeautifulSoup(content, "lxml")
    items, seen = [], set()
    for a in soup.select(src["selector"]):
        href = a.get("href")
        if not href:
            continue
        link = urljoin(src["url"], href)
        title = a.get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", title)
        if len(title) < 6 or link in seen or link.rstrip("/") == src["url"].rstrip("/"):
            continue
        seen.add(link)
        items.append({"title": title[:200], "link": link, "summary": "", "origin": "", "published": None})
    if not items:
        raise ValueError("页面上没有找到符合规则的链接（网站可能改版）")
    return items


def collect(src: dict) -> tuple[dict, list[dict] | None, str | None]:
    try:
        if src["type"] == "news":
            url = news_url(src["query"], src.get("lang", "en"), src.get("region"))
            return src, parse_rss(fetch(url), src), None
        if src["type"] == "rss":
            return src, parse_rss(fetch(src["url"]), src), None
        if src["type"] == "html":
            return src, parse_html(fetch(src["url"]), src), None
        return src, None, f"未知类型 {src['type']}"
    except requests.HTTPError as exc:
        return src, None, f"网站返回 {exc.response.status_code}"
    except requests.Timeout:
        return src, None, "连接超时"
    except requests.RequestException as exc:
        return src, None, f"无法连接：{type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        return src, None, str(exc)[:120]


# ---------------------------------------------------------------- 关注词

def build_matcher(keywords: dict):
    rules = []
    for group, words in (keywords or {}).items():
        for w in words:
            w = str(w)
            if re.search(r"[A-Za-z]", w):
                pat = re.compile(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", re.I)
            else:
                pat = re.compile(re.escape(w))
            rules.append((group, w, pat))

    def match(text: str) -> list[str]:
        hits = []
        for group, word, pat in rules:
            if pat.search(text) and word not in hits:
                hits.append(word)
        return hits[:6]

    return match


# ---------------------------------------------------------------- 主流程

def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text("utf-8"))
    return {"seen": {}, "sources": []}


def main() -> int:
    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text("utf-8"))
    settings = cfg.get("settings", {})
    max_age = timedelta(days=settings.get("max_age_days", 3))
    keep_days = settings.get("keep_days", 60)
    default_limit = settings.get("default_limit", 20)
    match = build_matcher(cfg.get("keywords"))
    excludes = [str(w).lower() for w in (cfg.get("exclude") or [])]

    def excluded(title: str) -> bool:
        t = title.lower()
        return any(w in t for w in excludes)

    DAYS.mkdir(parents=True, exist_ok=True)
    state = load_state()
    seen: dict = state["seen"]
    known_sources = set(state.get("sources", []))

    sources = []
    for cat in cfg["categories"]:
        for src in cat["sources"]:
            src = dict(src)
            src["category"] = cat["id"]
            src["sid"] = f"{cat['id']}/{src['name']}"
            sources.append(src)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(collect, sources))

    t_now = now_utc()
    today = t_now.astimezone(BJ).strftime("%Y-%m-%d")
    new_items, status = [], []

    for src, items, err in results:
        entry = {"name": src["name"], "category": src["category"], "ok": err is None,
                 "fetched": 0, "new": 0, "error": err or ""}
        if err:
            status.append(entry)
            continue
        entry["fetched"] = len(items)
        first_time = src["sid"] not in known_sources
        fresh = []
        for idx, it in enumerate(items):
            key = item_key(it["link"], it["title"])
            if key in seen:
                continue
            seen[key] = today
            if it["published"] and t_now - it["published"] > max_age:
                continue
            if it["published"] is None and first_time and idx >= NO_DATE_FIRST_RUN:
                continue
            if excluded(it["title"]):
                continue
            it["id"] = key
            fresh.append(it)
        fresh.sort(key=lambda x: x["published"] or t_now, reverse=True)
        fresh = fresh[: src.get("limit", default_limit)]
        for it in fresh:
            text = f"{it['title']} {it['summary']}"
            new_items.append({
                "id": it["id"],
                "title": it["title"],
                "link": it["link"],
                "summary": it["summary"],
                "source": src["name"],
                "origin": it["origin"],
                "category": src["category"],
                "published": it["published"].isoformat() if it["published"] else None,
                "hits": match(text),
            })
        entry["new"] = len(fresh)
        known_sources.add(src["sid"])
        status.append(entry)

    # 同一天多次运行时合并
    day_file = DAYS / f"{today}.json"
    if day_file.exists():
        old = json.loads(day_file.read_text("utf-8"))
        old_ids = {i["id"] for i in old.get("items", [])}
        merged = old.get("items", []) + [i for i in new_items if i["id"] not in old_ids]
    else:
        merged = new_items
    # 按当前的关注词和排除词重新整理当天全部条目（改了配置当天就生效）
    merged = [i for i in merged if not excluded(i["title"])]
    for i in merged:
        i["hits"] = match(f"{i['title']} {i['summary']}")

    per_source = {}
    for it in merged:
        per_source[it["source"]] = per_source.get(it["source"], 0) + 1
    for s in status:
        s["new"] = per_source.get(s["name"], 0) if s["ok"] else 0

    day_data = {
        "date": today,
        "generated_at": t_now.astimezone(BJ).isoformat(timespec="minutes"),
        "categories": [{"id": c["id"], "name": c["name"]} for c in cfg["categories"]],
        "items": merged,
        "status": status,
    }
    day_file.write_text(json.dumps(day_data, ensure_ascii=False, indent=1), "utf-8")

    # 清理过期历史
    cutoff = (t_now.astimezone(BJ) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for f in DAYS.glob("*.json"):
        if f.stem < cutoff:
            f.unlink()
    seen_cutoff = (t_now.astimezone(BJ) - timedelta(days=max(keep_days, 90))).strftime("%Y-%m-%d")
    state["seen"] = {k: v for k, v in seen.items() if v >= seen_cutoff}
    state["sources"] = sorted(known_sources)
    STATE.write_text(json.dumps(state, ensure_ascii=False), "utf-8")

    dates = sorted((f.stem for f in DAYS.glob("*.json")), reverse=True)
    (DATA / "index.json").write_text(
        json.dumps({"title": settings.get("title", "每日信息汇总"), "dates": dates}, ensure_ascii=False), "utf-8")

    # 生成网站目录
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True)
    shutil.copy(TEMPLATE, SITE / "index.html")
    shutil.copy(DATA / "index.json", SITE / "data" / "index.json")
    shutil.copytree(DAYS, SITE / "data" / "days")
    (SITE / ".nojekyll").write_text("")

    ok = sum(1 for s in status if s["ok"])
    print(f"{today}: 本次新增 {len(new_items)} 条，当天累计 {len(merged)} 条，信息源 {ok}/{len(status)} 正常")
    for s in status:
        flag = "OK " if s["ok"] else "ERR"
        print(f"  [{flag}] {s['category']:<10} {s['name']:<24} 抓到 {s['fetched']:>3}  当天 {s['new']:>3}  {s['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
