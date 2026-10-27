"""Wie viel Text einer gebauten Seite gehört nur zu ihr – und wie viel ist Seitenrahmen?

Aufruf (im Repo-Hauptordner, nach python3 src/build.py):
  python3 src/tools/rahmen_anteil.py                       Standardauswahl (Ortsseiten, Leistungen, Startseite)
  python3 src/tools/rahmen_anteil.py abriss-halstenbek.html index.html
  python3 src/tools/rahmen_anteil.py --dir /tmp/live ...    anderer Build-Ordner (ohne --preview bauen)
  python3 src/tools/rahmen_anteil.py --typen               Durchschnitt je Seitentyp über alle Seiten

Gemessen wird der sichtbare Text (ohne <script>, <style>, <noscript>, ohne Elemente mit hidden),
in Wörtern. Jeder Textknoten zählt als „wiederkehrend“, wenn genau derselbe Text auf mindestens
--schwelle (Standard 3) gebauten Seiten vorkommt (Menü, Fußzeile, Karten, Formular, Chips …).
Seitenspezifisch = Text in <main>, der nicht wiederkehrend ist.
Anteil = seitenspezifische Wörter / alle sichtbaren Wörter der Seite.
Nur Lesen, ändert nichts.
"""
import argparse
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ["abriss-hamburg-lurup.html", "abriss-hamburg-rissen.html", "abriss-hamburg-sasel.html",
            "abriss-hamburg-altona.html", "abriss-halstenbek.html", "abriss-norderstedt.html",
            "kleinabriss-hamburg.html", "entruempelung-hamburg.html", "index.html"]
SKIP = {"script", "style", "noscript", "template"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
WORT = re.compile(r"[0-9A-Za-zÄÖÜäöüß€]+")


class Text(HTMLParser):
    """Sammelt Textknoten mit Bereich: kopf (Kopfzeile + Menü), main, fuss (Fußzeile + Kontaktleiste), sonst."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, bereich oder None, versteckt)
        self.teile = []  # (bereich, text)

    def _bereich(self):
        for _, b, _ in reversed(self.stack):
            if b:
                return b
        return "sonst"

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        b = None
        if tag == "main":
            b = "main"
        elif tag == "footer" or "fab-bar" in cls:
            b = "fuss"
        elif (tag == "header" and "top" in cls) or (tag == "nav" and a.get("id") == "menu") or "draft" in cls:
            b = "kopf"
        versteckt = tag in SKIP or "hidden" in a
        self.stack.append((tag, b, versteckt))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if not any(t == tag for t, _, _ in self.stack):
            return
        while self.stack:
            t, _, _ = self.stack.pop()
            if t == tag:
                break

    def handle_data(self, data):
        if any(v for _, _, v in self.stack):
            return
        t = " ".join(data.split())
        if WORT.search(t):
            self.teile.append((self._bereich(), t))


def teile_von(path):
    p = Text()
    p.feed(path.read_text(encoding="utf-8"))
    p.close()
    return p.teile


def woerter(t):
    return len(WORT.findall(t))


def typ_von(name, site):
    slug = name.removesuffix(".html")
    for key, typ in (("leistungen", "leistung"), ("bezirke", "bezirk"), ("stadtteile", "stadtteil"),
                     ("umland", "umland"), ("ratgeber", "ratgeber")):
        if any(x["slug"] == slug for x in site.get(key, [])):
            return typ
    if name == "index.html":
        return "startseite"
    if re.fullmatch(r"[a-z-]+-hamburg-[a-z-]+\.html", name):
        return "leistung_ort"
    return "sonst"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("seiten", nargs="*", help="Dateinamen der gebauten Seiten (Standard: Auswahl)")
    ap.add_argument("--dir", default=str(ROOT), help="Build-Ordner (Standard: Repo)")
    ap.add_argument("--schwelle", type=int, default=3, help="ab so vielen Seiten gilt ein Text als wiederkehrend")
    ap.add_argument("--typen", action="store_true", help="Durchschnitt je Seitentyp über alle Seiten")
    ap.add_argument("--json", action="store_true", help="Ergebnis als JSON")
    args = ap.parse_args(argv)
    d = Path(args.dir)
    dateien = sorted(p for p in d.glob("*.html") if p.name != "404.html")
    if not dateien:
        print(f"Keine HTML-Dateien in {d}", file=sys.stderr)
        return 1
    alle = {p.name: teile_von(p) for p in dateien}
    haeufig = Counter()
    for teile in alle.values():
        haeufig.update({t for _, t in teile})

    def messen(name):
        z = Counter()
        for b, t in alle[name]:
            n = woerter(t)
            z["gesamt"] += n
            if b == "main":
                z["main_eigen" if haeufig[t] < args.schwelle else "main_rahmen"] += n
            else:
                z[b] += n
        z["anteil"] = round(100 * z["main_eigen"] / z["gesamt"], 1) if z["gesamt"] else 0.0
        return z

    site = json.loads((ROOT / "src" / "site.json").read_text(encoding="utf-8"))
    if args.typen:
        gruppen = {}
        for name in alle:
            gruppen.setdefault(typ_von(name, site), []).append(messen(name))
        zeilen = []
        for typ, ms in sorted(gruppen.items()):
            mittel = {k: round(sum(m[k] for m in ms) / len(ms), 1) for k in ("gesamt", "main_eigen", "anteil")}
            zeilen.append(dict(mittel, typ=typ, seiten=len(ms)))
        if args.json:
            print(json.dumps(zeilen, ensure_ascii=False, indent=1))
            return 0
        print(f"{'Typ':<14}{'Seiten':>7}{'Wörter':>9}{'eigen':>8}{'Anteil':>9}")
        for z in zeilen:
            print(f"{z['typ']:<14}{z['seiten']:>7}{z['gesamt']:>9}{z['main_eigen']:>8}{z['anteil']:>8}%")
        return 0

    namen = args.seiten or [x for x in STANDARD if x in alle]
    fehlt = [x for x in namen if x not in alle]
    if fehlt:
        print("Nicht gefunden: " + ", ".join(fehlt), file=sys.stderr)
        return 1
    erg = {n: messen(n) for n in namen}
    if args.json:
        print(json.dumps(erg, ensure_ascii=False, indent=1))
        return 0
    print(f"Text wiederkehrend ab {args.schwelle} Seiten · Build: {d}")
    print(f"{'Seite':<36}{'gesamt':>7}{'Kopf':>6}{'Fuß':>6}{'Main-Rahmen':>12}{'eigen':>7}{'Anteil eigen':>14}")
    for n, z in erg.items():
        print(f"{n:<36}{z['gesamt']:>7}{z['kopf']:>6}{z['fuss']:>6}{z['main_rahmen']:>12}{z['main_eigen']:>7}"
              f"{z['anteil']:>13}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
