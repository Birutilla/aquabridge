#!/usr/bin/env python3
"""
AquaBridge News Fetcher — v2 with category coverage
Mon/Thu via scheduled task. Fetches news, classifies into 5 categories,
boosts cross-source stories, applies quotas for balanced coverage,
translates EN+NO, writes news-data.json, git pushes.

Categories: technology | regulatory | market | environment | industry
Quota: 3 tech · 2 regulatory · 2 market · 2 environment · 1 industry

pip install feedparser deep-translator beautifulsoup4 requests
"""

import json, re, subprocess, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
OUTPUT_JSON = SCRIPT_DIR / "news-data.json"
MAX_ARTICLES = 10

SOURCES = [
    {"name":"mundoacuicola","label":"Mundo Acuícola","type":"rss",
     "url":"https://www.mundoacuicola.cl/new/feed/"},
    {"name":"aquacl","label":"AQUA","type":"rss",
     "url":"https://www.aqua.cl/feed/"},
    {"name":"salmonexpert","label":"Salmon Expert","type":"html",
     "url":"https://www.salmonexpert.cl/"},
]

CATEGORIES = {
    "technology": {
        "label": "Technology", "quota": 3,
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
    "regulatory": {
        "label": "Regulatory & Policy", "quota": 2,
        "pos": ["ley","law","reglamento","regulation","regulación","sernapesca","subpesca",
                "subsecretaría","gobierno","government","ministerio","president","presidenta",
                "decreto","normativa","norma","fiscalización","concesión","concesiones",
                "permiso","licencia","autorización","política","policy","ley de pesca",
                "seremi","congreso","senado","diputados","tribunal","multa","sanción",
                "reforma","reform","aprobó","promulgó","anunció","lafkenche",
                "cambio legal","legal","diputado","ejecutivo","modifica","acuerdo político"],
        "neg": ["fútbol","deporte","arte","receta","sello azul","certificación"],
    },
    "market": {
        "label": "Market & Business", "quota": 2,
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
        "label": "Environment & Sustainability", "quota": 2,
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
    "industry": {
        "label": "Industry & General", "quota": 1,
        "pos": ["industria","industry","sector","gremio","salmonchile","sernapesca",
                "aquasur","feria","evento","event","congreso","conference","simposio",
                "acuicultura","aquaculture","salmonicultura","producción nacional",
                "trabajadores","empleo","employment","región de los lagos","patagonia",
                "puerto montt","puerto varas","chiloé","aysén","50 años","aniversario",
                "informe","report","estudio","study","investigación","universidad",
                "research","ciencia","science"],
        "neg": ["fútbol","deporte","receta"],
    },
}

CATEGORY_ORDER = ["technology","regulatory","market","environment","industry"]

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
        desc = ""
        parent = a.find_parent(["article","div","li"])
        if parent:
            p = parent.find("p")
            if p: desc = p.get_text(strip=True)[:700]
        if title and len(title) > 10:
            articles.append({"title":title,"url":url,"date":"",
                              "description_es":desc,"source":source["label"],
                              "source_id":source["name"]})
    return articles[:40]


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
    fps = [title_fingerprint(a["title"]) for a in articles]
    for i, art in enumerate(articles):
        if not fps[i]: continue
        for j, other in enumerate(articles):
            if i == j or other["source_id"] == art["source_id"]: continue
            if len(fps[i] & fps[j]) >= 2:
                art["cross_source"] = True
                art["score"] += 4
                break
    return articles


def select_with_quotas(articles):
    by_cat = defaultdict(list)
    for art in articles:
        by_cat[art["category"]].append(art)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x["score"], reverse=True)

    selected, seen = [], set()
    for cat_key in CATEGORY_ORDER:
        quota = CATEGORIES[cat_key]["quota"]
        filled = 0
        for art in by_cat.get(cat_key, []):
            if filled >= quota: break
            if art["url"] not in seen:
                selected.append(art); seen.add(art["url"]); filled += 1

    remaining = MAX_ARTICLES - len(selected)
    if remaining > 0:
        for art in sorted(articles, key=lambda x: x["score"], reverse=True):
            if remaining <= 0: break
            if art["url"] not in seen:
                selected.append(art); seen.add(art["url"]); remaining -= 1

    cat_rank = {k:i for i,k in enumerate(CATEGORY_ORDER)}
    selected.sort(key=lambda x: (cat_rank.get(x["category"],99), -x["score"]))
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

    # 3. Cross-source boost
    all_articles = apply_cross_source_boost(all_articles)
    boosted = sum(1 for a in all_articles if a["cross_source"])
    print(f"  {boosted} articles boosted (appear on 2+ sources)")

    # 4. Category summary
    print("\nCategory breakdown:")
    for cat_key in CATEGORY_ORDER:
        pool = sorted([a for a in all_articles if a["category"]==cat_key],
                      key=lambda x: x["score"], reverse=True)
        quota = CATEGORIES[cat_key]["quota"]
        print(f"  {CATEGORIES[cat_key]['label']:32s} {len(pool):3d} articles  (quota:{quota})")
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
