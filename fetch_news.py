#!/usr/bin/env python3
"""
AquaBridge News Fetcher
Runs twice weekly (Mon/Thu) via scheduled task.
Fetches salmon industry news from three sources, scores for relevance,
picks top 10, translates to EN and NO, writes Website/news-data.json,
then git commits and pushes.

Dependencies: feedparser, deep-translator, beautifulsoup4, requests
Install: pip install feedparser deep-translator beautifulsoup4 requests
"""

import json
import re
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # Website/
REPO_ROOT   = SCRIPT_DIR.parent                        # AquaBridge/
OUTPUT_JSON = SCRIPT_DIR / "news-data.json"

# ── Sources ────────────────────────────────────────────────────────────────
SOURCES = [
    {
        "name": "mundoacuicola",
        "label": "Mundo Acuícola",
        "type": "rss",
        "url": "https://www.mundoacuicola.cl/new/feed/",
    },
    {
        "name": "aquacl",
        "label": "AQUA",
        "type": "rss",
        "url": "https://www.aqua.cl/feed/",
    },
    {
        "name": "salmonexpert",
        "label": "Salmon Expert",
        "type": "html",
        "url": "https://www.salmonexpert.cl/",
    },
]

MAX_ARTICLES = 10

# ── Relevance scoring ──────────────────────────────────────────────────────
HIGH_KEYWORDS = [
    "sensor", "monitoreo", "tecnología", "sistema", "solución",
    "software", "plataforma", "datos", "digitalización", "automatización",
    "inteligencia artificial", "ia", "oxígeno", "co2", "tdg", "gas disuelto",
    "biomasa", "caligus", "piojo", "srs", "piscirickettsia", "mortalidad",
    "vacuna", "tratamiento", "innovación", "herramienta", "equipo",
    "productividad", "eficiencia", "sanidad", "bioseguridad", "acústica",
    "visión artificial", "machine learning", "iot", "remoto", "telemetría",
    "certificación", "exportaciones", "mercado", "precio", "producción",
    "regulación", "sernapesca", "salmonchile", "acuicultura", "salmonicultura",
    "salmón", "trucha", "smolt", "piscicultura",
]
LOW_KEYWORDS = [
    "fútbol", "deporte", "cultura", "arte", "receta", "turismo",
    "concurso", "aniversario", "trabajadores", "rrhh",
]

def score_article(title: str, description: str) -> int:
    text = (title + " " + description).lower()
    score = 0
    for kw in HIGH_KEYWORDS:
        if kw in text:
            score += 2
    for kw in LOW_KEYWORDS:
        if kw in text:
            score -= 3
    return score


# ── Fetchers ───────────────────────────────────────────────────────────────
def fetch_rss(source: dict) -> list[dict]:
    try:
        import feedparser
    except ImportError:
        print("feedparser not installed. Run: pip install feedparser", file=sys.stderr)
        return []

    print(f"  Fetching RSS: {source['url']}")
    feed = feedparser.parse(source["url"])
    articles = []
    for entry in feed.entries[:30]:
        title = entry.get("title", "").strip()
        link  = entry.get("link", "").strip()
        date  = entry.get("published", entry.get("updated", ""))
        # Try to get full content, fall back to summary
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        if not content:
            content = entry.get("summary", "")
        # Strip HTML tags for plain text description
        desc = re.sub(r"<[^>]+>", " ", content)
        desc = re.sub(r"\s+", " ", desc).strip()
        # Limit description length
        if len(desc) > 600:
            desc = desc[:597] + "..."
        if title and link:
            articles.append({
                "title": title,
                "url": link,
                "date": date,
                "description_es": desc,
                "source": source["label"],
                "source_id": source["name"],
            })
    return articles


def fetch_html_salmonexpert(source: dict) -> list[dict]:
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("requests/bs4 not installed. Run: pip install requests beautifulsoup4", file=sys.stderr)
        return []

    print(f"  Fetching HTML: {source['url']}")
    try:
        resp = requests.get(source["url"], timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AquaBridgeNewsBot/1.0)"
        })
        resp.raise_for_status()
    except Exception as e:
        print(f"  Error fetching {source['url']}: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen_urls = set()

    # Article links follow pattern: /[tags]/[slug]/[numeric-id]
    link_pattern = re.compile(
        r"https://www\.salmonexpert\.cl/[a-z0-9\-]+/[a-z0-9\-]+/\d+"
    )

    for a_tag in soup.find_all("a", href=link_pattern):
        url = a_tag["href"].strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Try to find a title near this link
        title = a_tag.get_text(strip=True)
        if not title or len(title) < 10:
            # Look for heading sibling/parent
            parent = a_tag.find_parent(["article", "div", "li"])
            if parent:
                h = parent.find(["h1", "h2", "h3"])
                if h:
                    title = h.get_text(strip=True)

        # Try to get a description snippet
        desc = ""
        parent = a_tag.find_parent(["article", "div", "li"])
        if parent:
            p = parent.find("p")
            if p:
                desc = p.get_text(strip=True)[:600]

        if title and len(title) > 10:
            articles.append({
                "title": title,
                "url": url,
                "date": "",
                "description_es": desc,
                "source": source["label"],
                "source_id": source["name"],
            })

    return articles[:30]


# ── Translation ────────────────────────────────────────────────────────────
def translate_batch(texts: list[str], target_lang: str) -> list[str]:
    """Translate a list of Spanish texts to target_lang (en or no)."""
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        print("deep-translator not installed. Run: pip install deep-translator", file=sys.stderr)
        return texts  # Return originals as fallback

    translator = GoogleTranslator(source="es", target=target_lang)
    results = []
    for text in texts:
        if not text.strip():
            results.append("")
            continue
        try:
            # Google Translate has a 5000-char limit per call
            if len(text) > 4900:
                text = text[:4900]
            translated = translator.translate(text)
            results.append(translated or text)
        except Exception as e:
            print(f"  Translation error ({target_lang}): {e}", file=sys.stderr)
            results.append(text)  # Fallback to original
    return results


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"AquaBridge News Fetcher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Fetch from all sources
    all_articles = []
    for source in SOURCES:
        print(f"[{source['name']}]")
        if source["type"] == "rss":
            articles = fetch_rss(source)
        elif source["name"] == "salmonexpert":
            articles = fetch_html_salmonexpert(source)
        else:
            articles = []
        print(f"  → {len(articles)} articles fetched")
        all_articles.extend(articles)

    if not all_articles:
        print("\nNo articles fetched. Aborting.", file=sys.stderr)
        sys.exit(1)

    # 2. Score and rank
    print(f"\nScoring {len(all_articles)} total articles for relevance...")
    for art in all_articles:
        art["score"] = score_article(art["title"], art["description_es"])

    all_articles.sort(key=lambda x: x["score"], reverse=True)

    # 3. Deduplicate by title similarity
    seen_titles = []
    unique = []
    for art in all_articles:
        title_lower = art["title"].lower()
        is_dup = any(
            title_lower[:40] in t or t[:40] in title_lower
            for t in seen_titles
        )
        if not is_dup:
            seen_titles.append(title_lower)
            unique.append(art)

    top10 = unique[:MAX_ARTICLES]
    print(f"Selected top {len(top10)} articles (score range: {top10[0]['score']} to {top10[-1]['score']})")
    for i, art in enumerate(top10, 1):
        print(f"  {i:2}. [{art['score']:+d}] {art['title'][:70]}")

    # 4. Translate to EN and NO
    print("\nTranslating titles...")
    titles_es = [art["title"] for art in top10]
    titles_en = translate_batch(titles_es, "en")
    titles_no = translate_batch(titles_es, "no")

    print("Translating descriptions...")
    descs_es = [art["description_es"] for art in top10]
    descs_en = translate_batch(descs_es, "en")
    descs_no = translate_batch(descs_es, "no")

    # 5. Assemble output
    output_articles = []
    for i, art in enumerate(top10):
        output_articles.append({
            "title":    {"es": art["title"],       "en": titles_en[i], "no": titles_no[i]},
            "url":      art["url"],
            "date":     art["date"],
            "summary":  {"es": art["description_es"], "en": descs_en[i], "no": descs_no[i]},
            "source":   art["source"],
            "source_id": art["source_id"],
            "score":    art["score"],
        })

    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "articles": output_articles,
    }

    # 6. Write JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {OUTPUT_JSON}")

    # 7. Git commit and push
    print("\nPushing to GitHub...")
    try:
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "add", str(OUTPUT_JSON)],
            check=True, capture_output=True
        )
        commit_msg = f"news: auto-update {datetime.now().strftime('%Y-%m-%d')}"
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "commit", "-m", commit_msg],
            capture_output=True, text=True
        )
        if "nothing to commit" in result.stdout:
            print("  No changes to commit.")
        else:
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "push"],
                check=True, capture_output=True
            )
            print("  ✓ Pushed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
