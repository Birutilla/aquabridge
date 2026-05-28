#!/usr/bin/env python3
"""
AquaBridge News Fetcher v2 - category coverage, parallel fetch, normalized matching.
Display order: technology | industry | market | environment | regulatory
Selection: min 2 tech / min 2 industry / min 2 market / max 2 env / max 2 regulatory
Total: up to 12 articles

pip install feedparser deep-translator beautifulsoup4 requests
"""

import json, re, subprocess, sys, unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
OUTPUT_JSON = SCRIPT_DIR / "news-data.json"
MAX_ARTICLES = 12


def normalize(text):
    """Strip accents and lowercase for accent-insensitive matching."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


SOURCES = [
    {"name": "mundoacuicola", "label": "Mundo Acuicola", "type": "rss",
     "url": "https://www.mundoacuicola.cl/new/feed/"},
    {"name": "aquacl", "label": "AQUA", "type": "rss",
     "url": "https://www.aqua.cl/feed/"},
    {"name": "salmonexpert", "label": "Salmon Expert", "type": "html",
     "url": "https://www.salmonexpert.cl/"},
]

# All keywords written WITHOUT accents for consistent normalize() matching
CATEGORIES = {
    "technology": {
        "label": "Technology", "min": 2, "max": 99,
        "pos": ["sensor","sensores","monitoreo","monitoring","tecnologia",
                "software","plataforma","platform","digitalizacion","automatizacion",
                "inteligencia artificial","machine learning","iot","oxigeno","co2",
                "tdg","gas disuelto","biomasa","biomass","caligus","piojo","sea lice",
                "srs","piscirickettsia","vision artificial","computer vision","telemetria",
                "innovacion","innovation","herramienta","equipo","equipment","dispositivo",
                "algoritmo","robot","dron","camara","deteccion","prediccion","predictivo",
                "predictivas","eficiencia alimentaria","alimentador","sistema inteligente",
                "watermind","aqura","bioproc","biomarc","bioled","cpi equipment","pro-oceanus",
                "sensor dissolved","real-time","tiempo real","automatizado","automatica",
                "startup","app","aplicacion","solucion digital","soluciones digitales",
                "soluciones predictivas","solucion predictiva","gestion del riesgo",
                "optimizar operaciones","optimizacion","anticipar eventos","pitch",
                "inteligencia predictiva","alerta temprana","early warning"],
        "neg": ["futbol","deporte","arte","receta","turismo","concurso"],
    },
    "industry": {
        "label": "Industry & General", "min": 2, "max": 99,
        "pos": ["industria","industry","sector","gremio","salmonchile","aquasur",
                "feria","evento","event","congreso","conference","simposio","seminario",
                "acuicultura","aquaculture","salmonicultura",
                "trabajadores","empleo","employment","region de los lagos","patagonia",
                "puerto montt","puerto varas","chiloe","aysen","50 anos","aniversario",
                "informe anual","estudio","investigacion","universidad",
                "research","ciencia","nutricion"],
        "neg": ["futbol","deporte","receta"],
    },
    "market": {
        "label": "Market & Business", "min": 2, "max": 99,
        "pos": ["exportacion","exportaciones","export","exports","precio","precios",
                "price","mercado","market","demanda","demand","oferta","supply",
                "produccion","production","cosecha","harvest","toneladas","tonnes",
                "ingreso","ingresos","revenue","ventas","sales","utilidad","profit",
                "inversion","investment","empresa","company","corporacion",
                "mowi","cermaq","camanchaca","multiexport","blumar","aquachile",
                "ventisqueros","bolsa","stock","acciones","bono","bond",
                "fusion","adquisicion","acquisition","acuerdo comercial",
                "trimestre","quarter","crecimiento","growth","expansion",
                "noruega","norway","asia","china","estados unidos","europa",
                "resultado","resultados","ganancia","perdida"],
        "neg": ["futbol","deporte","arte","receta"],
    },
    "environment": {
        "label": "Environment & Sustainability", "min": 0, "max": 2,
        "pos": ["sostenibilidad","sustainability","sustentabilidad","medio ambiente",
                "ambiental","fitoplancton","bloom","floracion","marea roja","alga",
                "algal bloom","mortalidad","mortality","escape","escapes",
                "certificacion","certification","asc","bap","msc","bienestar animal",
                "animal welfare","carbono","carbon","huella","footprint",
                "residuos","waste","contaminacion","contamination","pollution",
                "antibiotico","antibiotic","temperatura","temperature",
                "cambio climatico","climate change","ecosistema","biodiversidad",
                "manejo sanitario","bioseguridad","biosecurity","sello azul",
                "reporte de impacto","educacion ambiental","abastecimiento sostenible"],
        "neg": ["futbol","deporte","receta"],
    },
    "regulatory": {
        "label": "Regulatory & Policy", "min": 0, "max": 2,
        "pos": ["ley","law","reglamento","regulation","regulacion","sernapesca","subpesca",
                "subsecretaria","gobierno","government","ministerio","presidenta","presidente",
                "decreto","normativa","norma","fiscalizacion","concesion","concesiones",
                "permiso","licencia","autorizacion","politica","policy","ley de pesca",
                "seremi","congreso","senado","diputados","tribunal","multa","sancion",
                "reforma","reform","aprobo","promulgo","anuncio","lafkenche",
                "cambio legal","diputado","ejecutivo","modifica","acuerdo politico",
                "reconstruccion","destraba"],
        "neg": ["futbol","deporte","arte","receta","sello azul","certificacion"],
    },
}

CATEGORY_ORDER = ["technology", "industry", "market", "environment", "regulatory"]

CATEGORY_LABELS = {
    "technology":  {"es": "Tecnologia",   "en": "Technology",                  "no": "Teknologi"},
    "regulatory":  {"es": "Regulatorio",  "en": "Regulatory & Policy",         "no": "Regulering og politikk"},
    "market":      {"es": "Mercado",       "en": "Market & Business",           "no": "Marked og naringsliv"},
    "environment": {"es": "Medioambiente", "en": "Environment & Sustainability", "no": "Miljo og baerekraft"},
    "industry":    {"es": "Industria",     "en": "Industry & General",          "no": "Bransjenyheter"},
}

STOPWORDS = {"de","del","la","el","los","las","en","un","una","y","a","que","se",
             "su","por","con","para","al","es","son","han","the","of","in","and",
             "to","for","is","are","has","its","into","from","this"}

# Without accents (normalize() strips them from article text too)
SALMON_REQUIRED = [
    "salmon","salmonicultura","salmon farming","salmonero","salmonera",
    "acuicultura","aquaculture","trucha","trout","coho","smolt","piscicultura",
    "mowi","cermaq","camanchaca","multiexport","blumar","aquachile","ventisqueros",
    "sernapesca","salmonchile","subpesca","salmones","loch duart","invermar",
    "caligus","srs","piscirickettsia","sea lice","skretting","biomar","cargill",
]

EXCLUDED_TOPICS = [
    "agroalimentario","agricultura ","ganaderia","bovino","vacuno","avicultura",
    "horticultura","viticultura","fruticultura","cereales","apicultura",
    "forestal","silvicultura","contenido patrocinado","publicidad",
]

SPONSORED_RE = re.compile(
    r"^(Contenido Patrocinado|Patrocinado|Publicidad|Sponsored|Anuncio)\s*",
    flags=re.IGNORECASE)


def is_salmon_relevant(article):
    text = normalize(article["title"] + " " + article["description_es"])
    if not any(kw in text for kw in SALMON_REQUIRED):
        return False
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
        title = entry.get("title", "").strip()
        link  = entry.get("link", "").strip()
        date  = entry.get("published", entry.get("updated", ""))
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        if not content:
            content = entry.get("summary", "")
        desc = re.sub(r"<[^>]+>", " ", content)
        desc = re.sub(r"\s+", " ", desc).strip()[:700]
        if title and link:
            articles.append({"title": title, "url": link, "date": date,
                              "description_es": desc, "source": source["label"],
                              "source_id": source["name"]})
    return articles


def fetch_html_salmonexpert(source):
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("requests/bs4 not installed.", file=sys.stderr); return []
    print(f"  Fetching HTML: {source['url']}")
    try:
        resp = requests.get(source["url"], timeout=15,
                            headers={"User-Agent": "Mozilla/5.0 (AquaBridgeNewsBot/2.0)"})
        resp.raise_for_status()
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr); return []
    soup = BeautifulSoup(resp.text, "html.parser")
    articles, seen = [], set()
    pat = re.compile(r"https://www\.salmonexpert\.cl/[a-z0-9\-]+/[a-z0-9\-]+/\d+")
    for a in soup.find_all("a", href=pat):
        url = a["href"].strip()
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(strip=True)
        if not title or len(title) < 10:
            parent = a.find_parent(["article", "div", "li"])
            if parent:
                h = parent.find(["h1", "h2", "h3"])
                if h:
                    title = h.get_text(strip=True)
        if title and len(title) > 10:
            title = SPONSORED_RE.sub("", title).strip()
            if not title or len(title) < 10:
                continue
            articles.append({"title": title, "url": url, "date": "",
                              "description_es": "", "source": source["label"],
                              "source_id": source["name"]})

    # Pre-filter candidates by title salmon relevance
    candidates = [a for a in articles
                  if any(kw in normalize(a["title"]) for kw in SALMON_REQUIRED)]
    if len(candidates) < 5:
        candidates = articles[:30]
    candidates = candidates[:25]

    def fetch_desc(art):
        """Priority: .articleHeader subtitle -> .bodytext p -> og:description."""
        try:
            import requests
            from bs4 import BeautifulSoup
            r = requests.get(art["url"], timeout=10,
                             headers={"User-Agent": "Mozilla/5.0 (AquaBridgeNewsBot/2.0)"})
            r.raise_for_status()
            s = BeautifulSoup(r.text, "html.parser")

            def clean(t):
                return SPONSORED_RE.sub("", t).strip()

            # 1. Article subtitle/lead
            subtitle = s.select_one(".articleHeader .subtitle, .articleHeader p.subtitle")
            if subtitle:
                text = clean(subtitle.get_text(strip=True))
                if len(text) > 60:
                    return art["url"], text[:700]

            # 2. First paragraph(s) in .bodytext
            bodytext = s.find("div", class_="bodytext")
            if bodytext:
                paras = [clean(p.get_text(strip=True))
                         for p in bodytext.find_all("p", recursive=False)
                         if len(p.get_text(strip=True)) > 60]
                if paras:
                    combined = " ".join(paras[:2])[:700]
                    if len(combined) > 60:
                        return art["url"], combined

            # 3. og:description fallback
            meta = (s.find("meta", attrs={"property": "og:description"}) or
                    s.find("meta", attrs={"name": "description"}))
            if meta and meta.get("content", "").strip():
                desc = clean(meta["content"].strip())
                if len(desc) > 30:
                    return art["url"], desc[:700]

        except Exception:
            pass
        return art["url"], ""

    print(f"  Fetching descriptions for {len(candidates)} articles (parallel)...")
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
    print(f"  -> {len(articles)} articles found, {fetched} with descriptions")
    return articles


def classify_and_score(article):
    text = normalize(article["title"] + " " + article["description_es"])
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
    words = normalize(title).split()
    sig = [w for w in words if len(w) > 4 and w not in STOPWORDS]
    return frozenset(sig[:8])


def apply_cross_source_boost(articles):
    fps = [title_fingerprint(a["title"]) for a in articles]
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
    discarded = set()
    for i in range(len(articles)):
        if i in discarded:
            continue
        cluster = [i]
        for j in range(i + 1, len(articles)):
            if j in discarded:
                continue
            if fps[i] and fps[j] and len(fps[i] & fps[j]) >= 2:
                cluster.append(j)
        if len(cluster) > 1:
            best = max(cluster, key=lambda idx: articles[idx]["score"])
            for idx in cluster:
                if idx != best:
                    discarded.add(idx)
    unique = [a for i, a in enumerate(articles) if i not in discarded]
    removed = len(articles) - len(unique)
    if removed:
        print(f"  Deduplication: removed {removed} near-duplicate articles")
    return unique


def select_with_quotas(articles):
    by_cat = defaultdict(list)
    for art in articles:
        by_cat[art["category"]].append(art)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x["score"], reverse=True)

    selected, seen, cat_count = [], set(), defaultdict(int)

    # Pass 1: fill minimums
    for cat_key in CATEGORY_ORDER:
        min_q = CATEGORIES[cat_key]["min"]
        for art in by_cat.get(cat_key, []):
            if cat_count[cat_key] >= min_q:
                break
            if art["url"] not in seen:
                selected.append(art)
                seen.add(art["url"])
                cat_count[cat_key] += 1

    # Pass 2: fill remaining slots by score, respecting max
    remaining = MAX_ARTICLES - len(selected)
    if remaining > 0:
        pool = sorted(articles, key=lambda x: x["score"], reverse=True)
        for art in pool:
            if remaining <= 0:
                break
            if art["url"] in seen:
                continue
            cat = art["category"]
            if cat_count[cat] >= CATEGORIES[cat]["max"]:
                continue
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
            results.append("")
            continue
        try:
            results.append(t.translate(text[:4900]) or text)
        except Exception as e:
            print(f"  Translate error ({target_lang}): {e}", file=sys.stderr)
            results.append(text)
    return results


def main():
    print(f"\n{'='*60}")
    print(f"AquaBridge News Fetcher v2 -- {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    all_articles = []
    for source in SOURCES:
        print(f"[{source['name']}]")
        if source["type"] == "rss":
            arts = fetch_rss(source)
        elif source["name"] == "salmonexpert":
            arts = fetch_html_salmonexpert(source)
        else:
            arts = []
        print(f"  -> {len(arts)} articles")
        all_articles.extend(arts)

    if not all_articles:
        print("No articles fetched. Aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"\nClassifying {len(all_articles)} articles...")
    for art in all_articles:
        cat, score = classify_and_score(art)
        art["category"] = cat
        art["score"] = score
        art["cross_source"] = False

    before = len(all_articles)
    all_articles = [a for a in all_articles if is_salmon_relevant(a)]
    print(f"  Salmon gate: {before - len(all_articles)} removed, {len(all_articles)} remain")

    all_articles = apply_cross_source_boost(all_articles)
    boosted = sum(1 for a in all_articles if a["cross_source"])
    print(f"  {boosted} articles boosted (appear on 2+ sources)")

    print("\nCategory breakdown:")
    for cat_key in CATEGORY_ORDER:
        pool = sorted([a for a in all_articles if a["category"] == cat_key],
                      key=lambda x: x["score"], reverse=True)
        mn = CATEGORIES[cat_key]["min"]
        mx = CATEGORIES[cat_key]["max"]
        limit_str = f"min:{mn}" if mx == 99 else f"max:{mx}"
        print(f"  {CATEGORIES[cat_key]['label']:32s} {len(pool):3d} articles  ({limit_str})")
        for a in pool[:4]:
            cross = " [CROSS]" if a["cross_source"] else ""
            print(f"      [{a['score']:+d}]{cross} {a['title'][:65]}")

    selected = select_with_quotas(all_articles)
    print(f"\nFinal selection ({len(selected)}):")
    for i, art in enumerate(selected, 1):
        cross = " [cross-source]" if art["cross_source"] else ""
        has_d = "OK" if art["description_es"] else "NO DESC"
        print(f"  {i:2}. [{art['score']:+d}] [{CATEGORIES[art['category']]['label']}]{cross} [{has_d}]")
        print(f"      {art['title'][:72]}")

    print("\nTranslating...")
    titles_en = translate_batch([a["title"] for a in selected], "en")
    titles_no = translate_batch([a["title"] for a in selected], "no")
    descs_en  = translate_batch([a["description_es"] for a in selected], "en")
    descs_no  = translate_batch([a["description_es"] for a in selected], "no")

    output_articles = []
    for i, art in enumerate(selected):
        output_articles.append({
            "title":          {"es": art["title"],          "en": titles_en[i], "no": titles_no[i]},
            "url":            art["url"],
            "date":           art["date"],
            "summary":        {"es": art["description_es"], "en": descs_en[i],  "no": descs_no[i]},
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

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {OUTPUT_JSON}")

    print("\nPushing to GitHub...")
    try:
        subprocess.run(["git", "-C", str(REPO_ROOT), "add", str(OUTPUT_JSON)],
                       check=True, capture_output=True)
        res = subprocess.run(["git", "-C", str(REPO_ROOT), "commit", "-m",
                              f"news: auto-update {datetime.now().strftime('%Y-%m-%d')}"],
                             capture_output=True, text=True)
        if "nothing to commit" in res.stdout:
            print("  No changes.")
        else:
            subprocess.run(["git", "-C", str(REPO_ROOT), "push"],
                           check=True, capture_output=True)
            print("  Pushed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
                           "-C", str(REPO_ROOT), "push"],
                           check=True, capture_output=True)
            print("  Pushed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
