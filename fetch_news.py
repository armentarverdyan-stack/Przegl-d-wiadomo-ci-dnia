#!/usr/bin/env python3
"""Codzienny przegląd: pobiera RSS z wielu źródeł, opcjonalnie robi podsumowanie
porównujące narracje (Claude API) i zapisuje docs/data.json dla PWA.

Użycie:
    pip install feedparser requests
    export ANTHROPIC_API_KEY=...   # opcjonalnie; bez klucza będą tylko nagłówki
    python fetch_news.py
"""
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs", "data.json")
MAX_PER_FEED = 10
MAX_AGE_H = 48
UA = "Mozilla/5.0 (compatible; DailyBrief/1.0)"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
BLOC_ORDER = ["Polska", "Armenia", "Zachód", "Rosja", "Chiny", "Indie"]


def clean(text, limit=220):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text[:limit]


def fetch(src):
    try:
        r = requests.get(src["url"], headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_H)
        items = []
        for e in feed.entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            if ts:
                dt = datetime.fromtimestamp(mktime(ts), timezone.utc)
                if dt < cutoff:
                    continue
            title = clean(e.get("title"), 200)
            if not title:
                continue
            items.append({
                "title": title,
                "summary": clean(e.get("summary") or e.get("description")),
                "link": e.get("link", ""),
            })
            if len(items) >= MAX_PER_FEED:
                break
        if not items:
            return src, [], "brak świeżych wpisów"
        return src, items, None
    except Exception as exc:  # jedno padnięte źródło nie może wywrócić całości
        return src, [], str(exc)[:120]


def build_prompt(blocs):
    parts = []
    for bloc in BLOC_ORDER:
        if bloc not in blocs:
            continue
        parts.append(f"=== BLOK: {bloc} ===")
        for s in blocs[bloc]:
            parts.append(f"-- {s['source']}")
            for it in s["items"]:
                line = f"* {it['title']}"
                if it["summary"] and it["summary"] != it["title"]:
                    line += f" — {it['summary'][:150]}"
                parts.append(line)
    return "\n".join(parts)


SYSTEM = """Jesteś analitykiem mediów. Dostajesz nagłówki z ostatnich 48 godzin \
z mediów podzielonych na bloki: Polska, Armenia, Zachód, Rosja, Chiny, Indie. \
Nagłówki bywają po rosyjsku, angielsku, polsku. Pisz po polsku, zwięźle, \
bez waty, dla czytelnika czytającego na telefonie. Interesuje go tylko polityka \
i gospodarka (pomiń sport, celebrytów, kryminalne ciekawostki).

Format (markdown: ## nagłówki, **pogrubienia**, listy z -):
## Polska
## Armenia
## Świat – polityka
## Świat – gospodarka
## Gdzie narracje się rozjeżdżają

W każdej sekcji wybierz 3–5 najważniejszych tematów. Przy temacie, gdy dotyczy go \
więcej niż jeden blok, podaj krótko: co twierdzą media zachodnie, rosyjskie, \
chińskie, indyjskie (tylko te, które o tym piszą) oraz osobno **Wspólny rdzeń** \
(to, co potwierdzają niezależnie od siebie różne bloki) i **Spór** (czym się różnią: \
fakty vs. interpretacja vs. dobór słów). W Polsce rozróżniaj też linie redakcyjne \
(np. TVP/Republika/wPolityce vs. Onet/Gazeta/Rzeczpospolita).

Zasady: opisujesz co media przedstawiają, nie rozstrzygasz prawdy na wiarę. \
Nie dopisuj faktów spoza nagłówków. Jeśli temat opiera się na jednym źródle, \
napisz to wprost. Zaznaczaj, gdy czegoś brakuje (np. blok nie napisał nic o danym temacie \
– to też informacja). Cytuj źródła z nazwy (np. TASS, BBC)."""


def summarize(blocs):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None, "Brak ANTHROPIC_API_KEY – pokazuję same nagłówki."
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 4000,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": build_prompt(blocs)}],
            },
            timeout=180,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"])
        return text, None
    except Exception as exc:
        return None, f"Podsumowanie nie powiodło się: {str(exc)[:200]}"


def main():
    with open(os.path.join(ROOT, "sources.json"), encoding="utf-8") as f:
        sources = json.load(f)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fetch, sources))

    blocs, failed = {}, []
    for src, items, err in results:
        if err:
            failed.append({"source": src["name"], "bloc": src["bloc"], "error": err})
        if items:
            blocs.setdefault(src["bloc"], []).append({"source": src["name"], "items": items})

    total = sum(len(s["items"]) for b in blocs.values() for s in b)
    print(f"Pobrano {total} nagłówków, błędy: {len(failed)}", file=sys.stderr)
    for f_ in failed:
        print(f"  ✗ {f_['source']}: {f_['error']}", file=sys.stderr)

    digest, note = (None, "Nie udało się pobrać żadnych nagłówków.") if not total else summarize(blocs)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "digest": digest,
            "note": note,
            "blocs": {b: blocs[b] for b in BLOC_ORDER if b in blocs},
            "failed": failed,
        }, f, ensure_ascii=False, indent=1)
    print(f"Zapisano {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
