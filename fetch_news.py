#!/usr/bin/env python3
"""
AquaBridge News Fetcher — v2 with category coverage
Mon/Thu via scheduled task. Fetches news, classifies into 5 categories,
boosts cross-source stories, applies quotas for balanced coverage,
translates EN+NO, writes news-data.json, git pushes.

Display order: technology | industry | market | environment | regulatory
Selection: min 2 tech · min 2 industry · min 2 market · max 2 env · max 2 regulatory
Total: up to 12 articles

pip install feedparser deep-translator beautifulsoup4 requests
"""

import json, re, subprocess, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
OUTPUT_JSON = SCRIPT_DIR / "news-data.json"
MAX_ARTICLES = 12

SOURCES = [
    {"name":"mundoacuicola","label":"Mundo Acuícola","type":"rss",
     "url":"https://www.mundoacuicola.cl/new/feed/"},
    {"name":"aquacl","label":"AQUA","type":"rss",
     "url":"https://www.aqua.cl/feed/"},
    {"name":"salmonexpert","label":"Salmon Expert","type":"html",
     "url":"https://www.salmonexpert.cl/"},
]

CATEGORIES = {
    # min: guaranteed slots filled first; max: hard ceiling
    "technology": {
        "label": "Technology", "min": 2, "max": 99,
        "pos": ["sensor","sensores","monitoreo","monitoring","tecnología","tecnologia",
                "software","plataforma","platform","datos","digitalización","automatización",
                "inteligencia artificial","machine learning","iot","oxígeno","oxigeno","co2",
                "tdg","gas disuelto","biomasa","biomass","caligus","piojo","sea lice",
                "srs","piscirickettsia","visión artificial","computer vision","telemetría",
                "innovación","innovation","herramienta","equipo","equipment","dispositivo",
                "algoritmo","robot","dron","cámara","detección","predicción",
                "eficiencia alimentaria","alimentador","sistema","system","aqura","bioproc","biomarc","bioled"],
        "neg": ["fútbol","deporte","arte","receta","turismo","concurso"],
    },
    "industry": {
        "label": "Industry & General", "min": 2, "max": 99,
        "pos": ["industria","industry","sector","gremio","salmonchile","sernapesca",
                "aquasur","feria","evento","event","congreso","conference","simposio",
                "acuicultura","aquaculture","salmonicultura","producción nacional",
                "trabajadores","empleo","employment","región de los lagos","patagonia",
                "puerto montt","puerto varas","chiloé","aysén","50 años","aniversario",
                "informe","report","estudio","study","investigación","universidad",
                "research","ciencia","science"],
        "neg": ["fútbol","deporte","receta"],
    },
    "market": {
        "label": "Market & Business", "min": 2, "max": 99,
        "pos": ["exportación","exportaciones","export","exports","precio","precios",
                "price","mercado","market","demanda","demand","oferta","supply",
                "producción","production","cosecha","harvest","toneladas","tonnes",
                "ingreso","ingresos","revenue","ventas","sales","utilidad","profit",
                "inversión","investment","empresa","company","compañía","corporación",
                "mowi","cermaq","camanchaca","multiexport","blumar","aquachile",
                "ventisqueros","bolsa","stock","acciones","bono","bond",
                "fusión","adquisición","acquisition","contrato","acuerdo",
                "trimestre","quarter","crecimiento","growth","expansión",
                "noruega","norway","asia","china","estados unidos","europa"],
        "neg": ["fútbol","deporte","arte","receta"],
    },
    "environment": {
        "label": "Environment & Sustainability", "min": 0, "max": 2,
        "pos": ["sostenibilidad","sustainability","sustentabilidad","medio ambiente",
                "ambiental","fitoplancton","bloom","floración","marea roja","alga",
                "floracion","algal bloom","mortalidad","mortality","escape","escapes",
                "certificación","certification","asc","bap","msc","bienestar animal",
                "animal welfare","carbono","carbon","huella","footprint",
                "residuos","waste","contaminación","contamination","pollution",
                "antibiótico","antibiotic","temperatura","temperature",
                "cambio climático","climate change","ecosistema","biodiversidad",
                "manejo sanitario","bioseguridad","biosecurity","sello azul","reporte de impacto",
                "educación ambiental","abastecimiento sostenible","huella de carbono"],
        "neg": ["fútbol","deporte","receta"],
    },
    "regulatory": {
        "label": "Regulatory & Policy", "min": 0, "max": 2,
        "pos": ["ley","law","reglamento","regulation","regulación","sernapesca","subpesca",
                "subsecretaría","gobierno","government","ministerio","president","presidenta",
                "decreto","normativa","norma","fiscalización","concesión","concesiones",
                "permiso","licencia","autorización","política","policy","ley de pesca",
                "seremi","congreso","senado","diputados","tribunal","multa","sanción",
                "reforma","reform","aprobó","promulgó","anunció","lafkenche",
                "cambio legal","legal","diputado","ejecutivo","modifica","acuerdo político"],
        "neg": ["fútbol","deporte","arte","receta","sello azul","certificación"],
    },
}

# Display order on the news page
CATEGORY_ORDER = ["technology","industry","market","environment","regulatory"]

CATEGORY_LABELS = {
    "technology":  {"es":"Tecnología",     "en":"Technology",                 "no":"Teknologi"},
    "regulatory":  {"es":"Regulatorio",    "en":"Regulatory & Policy",        "no":"Regulering og politikk"},
    "market":      {"es":"Mercado",         "en":"Market & Business",          "no":"Marked og næringsliv"},
    "environment": {"es":"Medioambiente",   "en":"Environment & Sustainability","no":"Miljø og bærekraft"},
    "industry":    {"es":"Industria",       "en":"Industry & General",         "no":"Bransjenyheter"},
}

STOPWORDS = {"de","del","la","el","los","las","en","un","una","y","a","que","se",
             "su","por","con","para","al","es","son","han","the","of","in","and",
             "to","for","is","are","has","its","into","from","this"}


# ── Salmon relevance gate ──────────────────────────────────────────────────
# An article MUST mention at least one of these to be considered at all.
SALMON_REQUIRED = [
    "salmón","salmon","salmonicultura","salmon farming","salmonero","salmonera",
    "acuicultura","aquaculture","trucha","trout","coho","smolt","piscicultura",
    "mowi","cermaq","camanchaca","multiexport","blumar","aquachile","ventisqueros",
    "sernapesca","salmonchile","subpesca","salmones","loch duart","invermar",
    "caligus","srs","piscirickettsia","sea lice","skretting","biomar","cargill",
]

# Explicit exclusion: these topics are never relevant even if other kws match
EXCLUDED_TOPICS = [
    "agroalimentario","agricultura ","ganadería","bovino","vacuno","avicultura",
    "horticultura","viticultura","fruticultura","cereales","apicultura",
    "forestal","silvicultura","contenido patrocinado","publicidad",
]

def is_salmon_relevant(article):
    text = (article["title"] + " " + article["description_es"]).lower()
    # Must contain at least one salmon/aquaculture term
    if not any(kw in text for kw in SALMON_REQUIRED):
        return False
    # Must not be a clearly unrelated agri-food topic
    if any(kw in text for kw in EXCLUDED_TOPICS):
        return False
    return True


def fetch_rss(source):
    try:
        import feedparser
    except ImportError:
        print("feedparser not installed.", file=sys.stderr); return []
    print(f"  Fetching RSS: {source['url']}")
    feed = feedparser.parse(source["url"])
    articles = []
    for entry in feed.entries[:40]:
        title = entry.get("title","").strip()
        link  = entry.get("link","").strip()
        date  = entry.get("published", entry.get("updated",""))
        content = ""
        if hasattr(entry,"content") and entry.content:
            content = entry.content[0].get("value","")
        if not content:
            content = entry.get("summary","")
        desc = re.sub(r"<[^>]+>"," ",content)
        desc = re.sub(r"\s+"," ",desc).strip()[:700]
        if title and link:
            articles.append({"title":title,"url":link,"date":date,
                              "description_es":desc,"source":source["label"],
                              "source_id":source["name"]})
    return articles


def fetch_html_salmonexpert(source):
    try:
        import requests
        from bs4 import BeautifulSoup
        from concurrent.futures import ThreadPoolExecutor, as_completed
    except ImportError:
        print("requests/bs4 not installed.", file=sys.stderr); return []
    print(f"  Fetching HTML: {source['url']}")
    try:
        resp = requests.get(source["url"], timeout=15,
                            headers={"User-Agent":"Mozilla/5.0 (AquaBridgeNewsBot/2.0)"})
        resp.raise_for_status()
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr); return []
    soup = BeautifulSoup(resp.text,"html.parser")
    articles, seen = [], set()
    pat = re.compile(r"https://www\.salmonexpert\.cl/[a-z0-9\-]+/[a-z0-9\-]+/\d+")
    for a in soup.find_all("a", href=pat):
        url = a["href"].strip()
        if url in seen: continue
        seen.add(url)
        title = a.get_text(strip=True)
        if not title or len(title) < 10:
            parent = a.find_parent(["article","div","li"])
            if parent:
                h = parent.find(["h1","h2","h3"])
                if h: title = h.get_text(strip=True)
        if title and len(title) > 10:
            # Strip sponsored-content labels that bleed into titles
            title = re.sub(r"^(Contenido Patrocinado|Patrocinado|Publicidad|Sponsored)\s*", "", title, flags=re.IGNORECASE).strip()
            if not title or len(title) < 10:
                continue
            articles.append({"title":title,"url":url,"date":"",
                              "description_es":"","source":source["label"],
                              "source_id":source["name"]})

    # Pre-filter by title salmon relevance so we only fetch pages that matter
    salmon_terms = SALMON_REQUIRED  # already defined at module level
    def title_is_salmon(art):
        t = art["title"].lower()
        return any(kw in t for kw in salmon_terms)

    candidates = [a for a in articles if title_is_salmon(a)]
    # Fall back to first 30 if pre-filter is too aggressive
    if len(candidates) < 5:
        candidates = articles[:30]
    candidates = candidates[:25]

    def fetch_desc(art):
        """Fetch og:description for a single article. Returns (url, description)."""
        try:
            r = requests.get(art["url"], timeout=10,
                             headers={"User-Agent":"Mozilla/5.0 (AquaBridgeNewsBot/2.0)"})
            r.raise_for_status()
            s = BeautifulSoup(r.text, "html.parser")
            meta = (s.find("meta", attrs={"property":"og:description"}) or
                    s.find("meta", attrs={"name":"description"}))
            if meta and meta.get("content","").strip():
                desc = meta["content"].strip()
                desc = re.sub(r"^(Contenido Patrocinado|Patrocinado|Publicidad|Sponsored)\s*",
                              "", desc, flags=re.IGNORECASE).strip()
                return art["url"], desc[:700]
        except Exception:
            pass
        return art["url"], ""

    print(f"  Fetching descriptions for {len(candidates)} SalmonExpert articles (parallel)...")
    desc_map = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_desc, art): art for art in candidates}
        for future in as_completed(futures):
            url, desc = future.result()
            if desc:
                desc_map[url] = desc

    for art in articles:
        if art["url"] in desc_map:
            art["description_es"] = desc_map[art["url"]]

    fetched = sum(1 for a in articles if a["description_es"])
    print(f"  → {len(articles)} articles found, {fetched} with descriptions")
    return articles


def classify_and_score(article):
    text = (article["title"] + " " + article["description_es"]).lower()
    best_cat, best_score = "industry", 0
    for cat_key, cat in CATEGORIES.items():
        score = 0
        for kw in cat["pos"]:
            if kw in text:
                score += 3 if " " in kw else 2
        for kw in cat["neg"]:
            if kw in text:
                score -= 4
        if score > best_score:
            best_score = score
            best_cat = cat_key
    return best_cat, best_score


def title_fingerprint(title):
    words = re.sub(r"[^a-záéíóúüñ\s]"," ",title.lower()).split()
    sig = [w for w in words if len(w) > 4 and w not in STOPWORDS]
    return frozenset(sig[:8])


def apply_cross_source_boost(articles):
    """Boost score for stories appearing on 2+ sources, then deduplicate.
    When the same story appears on multiple sources, keep only the one with
    the highest score (after boost) and discard the rest."""
    fps = [title_fingerprint(a["title"]) for a in articles]

    # Step 1: mark cross-source articles and apply boost
    for i, art in enumerate(articles):
        if not fps[i]:
            continue
        for j, other in enumerate(articles):
            if i == j or other["source_id"] == art["source_id"]:
                continue
            if len(fps[i] & fps[j]) >= 2:
                art["cross_source"] = True
                art["score"] += 4
                break

    # Step 2: deduplicate — for each cluster of near-duplicate articles,
    # keep only the highest-scoring one
    kept = []
    discarded = set()
    for i, art in enumerate(articles):
        if i in discarded:
            continue
        cluster = [i]
        for j in range(i + 1, len(articles)):
            if j in discarded:
                continue
            if fps[i] and fps[j] and len(fps[i] & fps[j]) >= 2:
                cluster.append(j)
        if len(cluster) > 1:
            # Keep the one with the highest score
            best = max(cluster, key=lambda idx: articles[idx]["score"])
            for idx in cluster:
                if idx != best:
                    discarded.add(idx)
        kept.append(articles[i])

    unique = [a for i, a in enumerate(articles) if i not in discarded]
    removed = len(articles) - len(unique)
    if removed:
        print(f"  Deduplication: removed {removed} near-duplicate articles")
    return unique


def select_with_quotas(articles):
    """
    Selection strategy:
      1. Fill minimums for tech / industry / market (2 each = 6 slots).
      2. Fill remaining slots (up to MAX_ARTICLES=12) by score, but never
         exceed the per-category max (env ≤ 2, regulatory ≤ 2; others unlimited).
      3. Sort final list by CATEGORY_ORDER then score descending.
    """
    by_cat = defaultdict(list)
    for art in articles:
        by_cat[art["category"]].append(art)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x["score"], reverse=True)

    selected, seen, cat_count = [], set(), defaultdict(int)

    # Pass 1: guarantee minimums for tech / industry / market
    for cat_key in CATEGORY_ORDER:
        min_q = CATEGORIES[cat_key]["min"]
        for art in by_cat.get(cat_key, []):
            if cat_count[cat_key] >= min_q: break
            if art["url"] not in seen:
                selected.append(art)
                seen.add(art["url"])
                cat_count[cat_key] += 1

    # Pass 2: fill remaining slots by score, respecting per-category max
    remaining = MAX_ARTICLES - len(selected)
    if remaining > 0:
        pool = sorted(articles, key=lambda x: x["score"], reverse=True)
        for art in pool:
            if remaining <= 0: break
            if art["url"] in seen: continue
            cat = art["category"]
            if cat_count[cat] >= CATEGORIES[cat]["max"]: continue
            selected.append(art)
            seen.add(art["url"])
            cat_count[cat] += 1
            remaining -= 1

    cat_rank = {k: i for i, k in enumerate(CATEGORY_ORDER)}
    selected.sort(key=lambda x: (cat_rank.get(x["category"], 99), -x["score"]))
    return selected[:MAX_ARTICLES]


def translate_batch(texts, target_lang):
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        return texts
    t = GoogleTranslator(source="es", target=target_lang)
    results = []
    for text in texts:
        if not text.strip():
            results.append(""); continue
        try:
            results.append(t.translate(text[:4900]) or text)
        except Exception as e:
            print(f"  Translate error ({target_lang}): {e}", file=sys.stderr)
            results.append(text)
    return results


def main():
    print(f"\n{'='*60}")
    print(f"AquaBridge News Fetcher v2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Fetch
    all_articles = []
    for source in SOURCES:
        print(f"[{source['name']}]")
        if source["type"] == "rss":
            arts = fetch_rss(source)
        elif source["name"] == "salmonexpert":
            arts = fetch_html_salmonexpert(source)
        else:
            arts = []
        print(f"  → {len(arts)} articles")
        all_articles.extend(arts)

    if not all_articles:
        print("No articles fetched. Aborting.", file=sys.stderr); sys.exit(1)

    # 2. Classify
    print(f"\nClassifying {len(all_articles)} articles...")
    for art in all_articles:
        cat, score = classify_and_score(art)
        art["category"] = cat
        art["score"] = score
        art["cross_source"] = False

    # 2b. Salmon relevance gate
    before = len(all_articles)
    all_articles = [a for a in all_articles if is_salmon_relevant(a)]
    print(f"  Salmon gate: {before - len(all_articles)} articles removed, {len(all_articles)} remain")

    # 3. Cross-source boost
    all_articles = apply_cross_source_boost(all_articles)
    boosted = sum(1 for a in all_articles if a["cross_source"])
    print(f"  {boosted} articles boosted (appear on 2+ sources)")

    # 4. Category summary
    print("\nCategory breakdown:")
    for cat_key in CATEGORY_ORDER:
        pool = sorted([a for a in all_articles if a["category"]==cat_key],
                      key=lambda x: x["score"], reverse=True)
        mn = CATEGORIES[cat_key]["min"]; mx = CATEGORIES[cat_key]["max"]
        limit_str = f"min:{mn}" if mx == 99 else f"max:{mx}"
        print(f"  {CATEGORIES[cat_key]['label']:32s} {len(pool):3d} articles  ({limit_str})")
        for a in pool[:3]:
            cross = " [CROSS]" if a["cross_source"] else ""
            print(f"      [{a['score']:+d}]{cross} {a['title'][:65]}")

    # 5. Select
    top10 = select_with_quotas(all_articles)
    print(f"\nFinal selection ({len(top10)}):")
    for i, art in enumerate(top10, 1):
        cross = " [cross-source]" if art["cross_source"] else ""
        print(f"  {i:2}. [{art['score']:+d}] [{CATEGORIES[art['category']]['label']}]{cross}")
        print(f"      {art['title'][:72]}")

    # 6. Translate
    print("\nTranslating...")
    titles_en = translate_batch([a["title"] for a in top10], "en")
    titles_no = translate_batch([a["title"] for a in top10], "no")
    descs_en  = translate_batch([a["description_es"] for a in top10], "en")
    descs_no  = translate_batch([a["description_es"] for a in top10], "no")

    # 7. Assemble
    output_articles = []
    for i, art in enumerate(top10):
        output_articles.append({
            "title":          {"es":art["title"],         "en":titles_en[i],"no":titles_no[i]},
            "url":            art["url"],
            "date":           art["date"],
            "summary":        {"es":art["description_es"],"en":descs_en[i], "no":descs_no[i]},
            "source":         art["source"],
            "source_id":      art["source_id"],
            "category":       art["category"],
            "category_label": CATEGORY_LABELS[art["category"]],
            "score":          art["score"],
            "cross_source":   art["cross_source"],
        })

    payload = {
        "updated":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "articles": output_articles,
    }

    # 8. Write JSON
    with open(OUTPUT_JSON,"w",encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {OUTPUT_JSON}")

    # 9. Git push
    print("\nPushing to GitHub...")
    try:
        subprocess.run(["git","-C",str(REPO_ROOT),"add",str(OUTPUT_JSON)],
                       check=True, capture_output=True)
        res = subprocess.run(["git","-C",str(REPO_ROOT),"commit","-m",
                              f"news: auto-update {datetime.now().strftime('%Y-%m-%d')}"],
                             capture_output=True, text=True)
        if "nothing to commit" in res.stdout:
            print("  No changes.")
        else:
            subprocess.run(["git","-C",str(REPO_ROOT),"push"],
                           check=True, capture_output=True)
            print("  Pushed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
