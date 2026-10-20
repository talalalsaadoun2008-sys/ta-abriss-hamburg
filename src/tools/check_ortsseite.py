"""Qualitätsschranke für neue Ortsseiten (gegen Doorway-/Massen-Seiten).

Aufruf:  python3 src/tools/check_ortsseite.py <slug> [<slug> ...]
Exit 0 = alle Seiten bestehen, Exit 1 = mindestens eine fällt durch (Gründe werden ausgegeben).
Eine Seite, die durchfällt, darf NICHT veröffentlicht werden.

Geprüft wird je Seite:
- Pflichtfelder, 3–5 Abschnitte, 3–4 FAQ, Text 380–950 Wörter (inkl. FAQ)
- mindestens 4 Quellen von mindestens 3 verschiedenen Websites
- Bauaufsicht und die richtige Landesbauordnung werden genannt
- kein Satz (ab 8 Wörtern) steht fast gleich auf einer anderen Seite (Ortsnamen werden dafür neutralisiert)
- höchstens 8 % der 8-Wort-Folgen kommen auf irgendeiner anderen einzelnen Seite vor
"""
import json, re, sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "src" / "content"
SITE = json.loads((ROOT / "src" / "site.json").read_text(encoding="utf-8"))
BAUORDNUNG = {"Schleswig-Holstein": ("LBO", "Landesbauordnung"),
              "Niedersachsen": ("NBauO", "Niedersächsische Bauordnung"),
              "Mecklenburg-Vorpommern": ("LBauO", "Landesbauordnung Mecklenburg-Vorpommern"),
              "Bremen": ("BremLBO", "Bremische Landesbauordnung")}


def text_of(c):
    parts = [s["h2"] + ". " + s["html"] for s in c["sections"]] + [f["q"] + " " + f["a"] for f in c["faq"]]
    t = re.sub(r"<[^>]+>", " ", " ".join(parts))
    return re.sub(r"\s+", " ", t.replace(" ", " ")).strip()


def names():
    n = {"Hamburg"}
    for grp in ("bezirke", "stadtteile", "umland"):
        for it in SITE.get(grp, []):
            n |= set(re.split(r"[ ()/]+", it["name"])) | {it["name"]}
            if it.get("kreis"):
                n |= set(it["kreis"].split())
    for p in CONTENT.glob("*.json"):
        c = json.loads(p.read_text(encoding="utf-8"))
        n |= set(c.get("stadtteile") or [])
    return sorted({x for x in n if len(x) >= 4 and x[0].isupper()}, key=len, reverse=True)


NAMES = names()
NAME_RE = re.compile(r"\b(" + "|".join(re.escape(x) for x in NAMES) + r")\b")


def norm(t):
    t = NAME_RE.sub("ORT", t.lower() if False else t)
    t = re.sub(r"\d+([.,]\d+)?", "N", t)
    return re.sub(r"[^\wäöüß ]+", " ", t.lower())


def shingles(t, k=8):
    w = norm(t).split()
    return {" ".join(w[i:i + k]) for i in range(len(w) - k + 1)}


def sentences(t):
    return [s for s in re.split(r"(?<=[.!?:])\s+", t) if len(s.split()) >= 8]


def check(slug, corpus):
    errs = []
    p = CONTENT / f"{slug}.json"
    if not p.exists():
        return [f"{slug}: Datei fehlt"]
    c = json.loads(p.read_text(encoding="utf-8"))
    for k in ("slug", "type", "title", "description", "h1", "lead", "facts", "sections", "faq", "sources", "form_ort"):
        if k not in c:
            errs.append(f"Feld {k} fehlt")
    if errs:
        return errs
    if not 3 <= len(c["sections"]) <= 5:
        errs.append(f"{len(c['sections'])} Abschnitte (3–5 erlaubt)")
    if not 3 <= len(c["faq"]) <= 4:
        errs.append(f"{len(c['faq'])} FAQ (3–4 erlaubt)")
    t = text_of(c)
    n = len(t.split())
    if not 380 <= n <= 950:
        errs.append(f"{n} Wörter (380–950 nötig)")
    srcs = [s.get("url", "") for s in c["sources"]]
    doms = {urlparse(u).netloc.removeprefix("www.") for u in srcs if u.startswith("http")}
    if len(srcs) < 4 or len(doms) < 3:
        errs.append(f"{len(srcs)} Quellen von {len(doms)} Websites (mind. 4 von 3)")
    entry = next((u for u in SITE.get("umland", []) if u["slug"] == slug), None)
    if entry and entry.get("land") in BAUORDNUNG:
        kurz, lang = BAUORDNUNG[entry["land"]]
        if kurz not in t and lang not in t:
            errs.append(f"Bauordnung ({kurz}) nicht genannt")
    if "Bauaufsicht" not in t and "Bauamt" not in t:
        errs.append("zuständige Bauaufsicht nicht genannt")
    own = shingles(t)
    own_sent = {norm(s).strip() for s in sentences(t)}
    for other, (osh, osent) in corpus.items():
        if other == slug:
            continue
        same = own_sent & osent
        if same:
            errs.append(f"{len(same)} Satz/Sätze fast gleich wie auf {other}, z. B. „{next(iter(same))[:80]}…“")
        if own and len(own & osh) / len(own) > 0.08:
            errs.append(f"{len(own & osh) / len(own):.0%} gleiche Wortfolgen mit {other} (max. 8 %)")
    return errs


def main(slugs):
    corpus = {}
    for p in CONTENT.glob("*.json"):
        c = json.loads(p.read_text(encoding="utf-8"))
        if c.get("type") in ("umland", "stadtteil", "bezirk"):
            t = text_of(c)
            corpus[p.stem] = (shingles(t), {norm(s).strip() for s in sentences(t)})
    bad = 0
    for s in slugs:
        e = check(s, corpus)
        print(("FEHLER " if e else "ok     ") + s + ("" if not e else "\n  - " + "\n  - ".join(e)))
        bad += bool(e)
    print(f"{len(slugs) - bad} bestanden, {bad} durchgefallen")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
