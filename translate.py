"""英文 → 中文机器翻译（不用大模型）。

在 GitHub 的服务器上运行，打开网页时不需要访问任何翻译服务。
依次尝试：微软翻译（Edge 浏览器内置翻译所用的免费接口）→ 谷歌翻译免费接口。
两者都是非官方免费接口，可能随时变化；失败时条目保持英文，不影响其他功能。
"""
from __future__ import annotations

import re
import time

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Edg/130.0"
CJK = re.compile("[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]{3,}")
BATCH = 40


def needs_translation(text: str) -> bool:
    return bool(text) and not CJK.search(text) and bool(LATIN.search(text))


class _Microsoft:
    name = "微软翻译"

    def __init__(self):
        self.token, self.at = None, 0.0

    def _auth(self):
        if not self.token or time.time() - self.at > 480:
            r = requests.get("https://edge.microsoft.com/translate/auth", headers={"User-Agent": UA}, timeout=20)
            r.raise_for_status()
            self.token, self.at = r.text.strip(), time.time()
        return self.token

    def batch(self, texts: list[str]) -> list[str]:
        r = requests.post(
            "https://api-edge.cognitive.microsofttranslator.com/translate",
            params={"from": "en", "to": "zh-Hans", "api-version": "3.0"},
            headers={"Authorization": f"Bearer {self._auth()}", "Content-Type": "application/json", "User-Agent": UA},
            json=[{"Text": t} for t in texts],
            timeout=40,
        )
        r.raise_for_status()
        out = [d["translations"][0]["text"] for d in r.json()]
        if len(out) != len(texts):
            raise ValueError("返回条数不一致")
        return out


class _Google:
    name = "谷歌翻译"

    def one(self, text: str) -> str:
        r = requests.post(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t"},
            data={"q": text},
            headers={"User-Agent": UA},
            timeout=20,
        )
        r.raise_for_status()
        return "".join(seg[0] for seg in r.json()[0] if seg and seg[0])

    def batch(self, texts: list[str]) -> list[str]:
        out = []
        for t in texts:
            out.append(self.one(t))
            time.sleep(0.15)
        return out


def translate_items(items: list[dict]) -> dict:
    """给条目补上 title_zh / summary_zh（已有的跳过）。返回统计信息。"""
    jobs = []  # (item, 字段)
    for it in items:
        if "title_zh" not in it and needs_translation(it["title"]):
            jobs.append((it, "title"))
        if "summary_zh" not in it and needs_translation(it.get("summary", "")):
            jobs.append((it, "summary"))
    stats = {"total": len(jobs), "done": 0, "engines": {}, "error": ""}
    if not jobs:
        return stats

    engines = [_Microsoft(), _Google()]
    for start in range(0, len(jobs), BATCH):
        chunk = jobs[start:start + BATCH]
        texts = [it[field] for it, field in chunk]
        for eng in engines:
            try:
                result = eng.batch(texts)
            except Exception as exc:  # noqa: BLE001
                stats["error"] = f"{eng.name}：{type(exc).__name__}"
                continue
            for (it, field), zh in zip(chunk, result):
                zh = (zh or "").strip()
                if zh and zh != it[field]:
                    it[f"{field}_zh"] = zh
                    stats["done"] += 1
            stats["engines"][eng.name] = stats["engines"].get(eng.name, 0) + len(chunk)
            break
    return stats
