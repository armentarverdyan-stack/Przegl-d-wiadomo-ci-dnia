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
from urllib.parse import urljoin

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


def parse_feed(content):
    """Zwraca (świeże_wpisy, liczba_wszystkich, data_najnowszego)."""
    feed = feedparser.parse(content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_H)
    items, newest = [], None
    for e in feed.entries:
        ts = e.get("published_parsed") or e.get("updated_parsed")
        if ts:
            dt = datetime.fromtimestamp(mktime(ts), timezone.utc)
            newest = dt if newest is None or dt > newest else newest
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
    return items, len(feed.entries), newest


def discover_feeds(home):
    """Szuka <link rel="alternate" type="application/rss+xml"> na stronie głównej."""
    r = requests.get(home, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    found = []
    for tag in re.findall(r"<link[^>]+>", r.text, re.I):
        if re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
            m = re.search(r'href=["\']([^"\']+)', tag, re.I)
            if m:
                found.append(urljoin(home, html.unescape(m.group(1))))
    return found[:4]


def fetch(src):
    """Próbuje kolejno: url, urls[], a na końcu autodetekcji z strony 'home'.
    Jedno padnięte źródło nie może wywrócić całości."""
    candidates = ([src["url"]] if src.get("url") else []) + list(src.get("urls", []))
    problems, stale = [], None
    tried_discovery = False
    while candidates or (src.get("home") and not tried_discovery):
        if not candidates:
            tried_discovery = True
            try:
                candidates = [u for u in discover_feeds(src["home"]) if u not in problems]
            except Exception as exc:
                problems.append(f"autodetekcja: {str(exc)[:60]}")
                break
            if not candidates:
                problems.append("autodetekcja: brak kanału RSS na stronie")
                break
        url = candidates.pop(0)
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
            r.raise_for_status()
            items, total, newest = parse_feed(r.content)
            if items:
                return src, items, None
            if total == 0:
                problems.append(f"{url}: odpowiedź bez wpisów (nie RSS?)")
            else:
                stale = newest
                problems.append(f"{url}: tylko stare wpisy"
                                + (f" (ostatni {newest:%Y-%m-%d})" if newest else ""))
        except Exception as exc:
            problems.append(f"{url}: {str(exc)[:70]}")
    msg = "; ".join(problems[:3]) or "brak adresu"
    return src, [], msg[:300]


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
                "max_tokens": 16000,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": build_prompt(blocs)}],
            },
            timeout=300,
        )
        if r.status_code >= 400:
            # treść błędu z API mówi najwięcej (zły model, brak środków, zły klucz)
            msg = f"API zwróciło {r.status_code}: {r.text[:300]}"
            print("  ✗ " + msg, file=sys.stderr)
            return None, "Podsumowanie nie powiodło się. " + msg
        body = r.json()
        text = "".join(b.get("text", "") for b in body.get("content", [])
                       if b.get("type") == "text").strip()
        if not text:
            types_ = [b.get("type") for b in body.get("content", [])]
            msg = (f"API odpowiedziało, ale bez tekstu (stop_reason={body.get('stop_reason')}, "
                   f"bloki={types_}, model={MODEL}).")
            print("  ✗ " + msg, file=sys.stderr)
            return None, "Podsumowanie nie powiodło się. " + msg
        print(f"Podsumowanie OK ({len(text)} znaków, model {MODEL})", file=sys.stderr)
        return text, None
    except Exception as exc:
        msg = f"Podsumowanie nie powiodło się: {type(exc).__name__}: {str(exc)[:250]}"
        print("  ✗ " + msg, file=sys.stderr)
        return None, msg


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
