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