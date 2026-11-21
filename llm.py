"""可选的大模型整理：挑重点、写中文标题、一句话要点和每类综述。

只在设置了 LLM_API_KEY 时启用。接口为 OpenAI 兼容格式（/chat/completions），
DeepSeek、通义千问、Kimi、智谱、OpenRouter 及多数中转服务都支持。
  LLM_API_KEY   密钥（放在 GitHub Secrets）
  LLM_BASE_URL  接口地址，例如 https://api.deepseek.com/v1
  LLM_MODEL     模型名，例如 deepseek-chat
任何一步出错都返回 None，页面自动用规则结果。
"""
from __future__ import annotations

import json
import os
import re

import requests

MAX_CANDIDATES = 15
MAX_HIGHLIGHTS = 5

SYSTEM = (
    "你是行业情报编辑，读者从事民爆（工业炸药、雷管、爆破服务）和矿业服务，关注海外尤其非洲的矿业项目，"
    "也关注 AI 与技术进展。你的任务是从给定的当天新闻里挑出真正重要的进展，用简洁的中文写出来。\n"
    "规则：\n"
    "1. 只能使用给定材料里的信息，不得补充材料里没有的事实、数字或背景；不确定就不写。\n"
    "2. 重要性看：对行业格局、价格、政策、安全、大公司动向、技术突破的影响；多家媒体报道的通常更重要。"
    "股票资金流向、日常行情播报、软文广告不算重点。\n"
    "3. 候选里如果有几条其实是同一件事，把它们的编号放进同一个 ids。\n"
    "4. 只输出 JSON，不要任何其他文字。"
)


def _config():
    key = os.environ.get("LLM_API_KEY", "").strip()
    base = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("LLM_MODEL", "").strip()
    if not key:
        return None, "未设置 LLM_API_KEY"
    if not base or not model:
        return None, "未设置 LLM_BASE_URL 或 LLM_MODEL"
    if not base.endswith("/chat/completions"):
        base += "/chat/completions"
    return (key, base, model), None


def _call(cfg, prompt: str) -> str:
    key, url, model = cfg
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _parse(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # 部分推理模型会带思考过程
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("返回内容里没有 JSON")
    return json.loads(m.group(0))


def digest_category(cfg, cat_name: str, clusters: list[dict], items_by_id: dict) -> dict:
    lines = []
    for c in clusters[:MAX_CANDIDATES]:
        its = [items_by_id[i] for i in c["items"][:4]]
        titles = " / ".join(dict.fromkeys(i["title"] for i in its))
        summary = next((i["summary"] for i in its if i.get("summary")), "")
        pubs = ", ".join(dict.fromkeys((i.get("origin") or i["source"]) for i in its))
        lines.append(f"[{c['id']}] {titles}\n    来源（{c['sources']} 家）：{pubs}" + (f"\n    摘要：{summary}" if summary else ""))
    prompt = (
        f"分类：{cat_name}\n今天的候选新闻（已按规则初步排序，编号在方括号里）：\n\n" + "\n".join(lines) +
        f"\n\n请输出 JSON：\n"
        "{\n"
        '  "summary": "今日综述，2-3 句，概括这一类最重要的进展；没有重要内容就写一句说明",\n'
        '  "highlights": [\n'
        '    {"ids": ["c0"], "headline": "中文标题，不超过 30 字", "point": "一句话要点，不超过 60 字，说清发生了什么、为什么值得关注"}\n'
        "  ],\n"
        '  "titles_zh": {"c3": "其余候选的中文标题（原文是中文的可以不写）"}\n'
        "}\n"
        f"highlights 按重要性从高到低，最多 {MAX_HIGHLIGHTS} 条，宁缺毋滥。"
    )
    data = _parse(_call(cfg, prompt))
    valid = {c["id"] for c in clusters[:MAX_CANDIDATES]}
    highlights = []
    for h in data.get("highlights", [])[:MAX_HIGHLIGHTS]:
        ids = [i for i in h.get("ids", []) if i in valid]
        if ids and h.get("headline"):
            highlights.append({"ids": ids, "headline": str(h["headline"])[:60], "point": str(h.get("point", ""))[:160]})
    titles = {k: str(v)[:80] for k, v in (data.get("titles_zh") or {}).items() if k in valid}
    return {"summary": str(data.get("summary", ""))[:400], "highlights": highlights, "titles_zh": titles}


def build_digest(categories: list[dict], clusters: list[dict], items_by_id: dict) -> tuple[dict | None, str]:
    cfg, err = _config()
    if not cfg:
        return None, err
    out, errors = {}, []
    for cat in categories:
        cl = [c for c in clusters if c["category"] == cat["id"]]
        if not cl:
            continue
        try:
            out[cat["id"]] = digest_category(cfg, cat["name"], cl, items_by_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{cat['name']}：{type(exc).__name__} {str(exc)[:80]}")
    if not out:
        return None, "；".join(errors) or "没有内容"
    return {"model": cfg[2], "categories": out, "errors": errors}, ""
