"""Von wie vielen Seiten wird eine Seite verlinkt? (über die gebauten HTML-Dateien)

Aufruf (im Repo-Hauptordner, nach python3 src/build.py):
  python3 src/tools/eingehende_links.py abriss-holm abriss-jork.html     bestimmte Seiten
  python3 src/tools/eingehende_links.py --unter 3                      alle Seiten mit weniger als 3 Links im Inhalt
  python3 src/tools/eingehende_links.py --dir /tmp/live ...            anderer Build-Ordner (ohne --preview bauen)

Gezählt werden verschiedene andere Seiten (nicht die Zahl der Links). „Inhalt“ = Links innerhalb von <main>;
„gesamt“ zählt auch Menü, Kopf- und Fußzeile mit (die stehen auf jeder Seite gleich).
Nur Lesen, ändert nichts.
"""
import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://ta-abriss-hamburg.de/"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.links = []  # (href, in_main)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append((a["href"], "main" in self.stack))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass


def ziel(href):
    """Dateiname der verlinkten Seite oder None (extern, Anker, mailto …)."""
    if href.startswith(BASE):
        href = href[len(BASE):] or "./"
    if re.match(r"(?:[a-z]+:|//)", href, re.I):
        return None
    path = href.partition("#")[0].partition("?")[0].lstrip("/")
    if path in ("", ".", "./"):
        return "index.html" if href.partition("#")[0] else None
    return path if path.endswith(".html") else None


def zaehlen(d):
    ein = {}  # Ziel -> {"gesamt": set(Quellen), "inhalt": set(Quellen)}
    for p in sorted(d.glob("*.html")):
        if p.name == "404.html":
            continue
        lp = Links()
        lp.feed(p.read_text(encoding="utf-8"))
        for href, in_main in lp.links:
            z = ziel(href)
            if not z or z == p.name:
                continue
            e = ein.setdefault(z, {"gesamt": set(), "inhalt": set()})
            e["gesamt"].add(p.name)
            if in_main:
                e["inhalt"].add(p.name)
    return ein


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("seiten", nargs="*", help="Slugs oder Dateinamen")
    ap.add_argument("--dir", default=str(ROOT), help="Build-Ordner (Standard: Repo)")
    ap.add_argument("--unter", type=int, help="alle Seiten mit weniger als N verlinkenden Seiten im Inhalt")
    ap.add_argument("--quellen", action="store_true", help="verlinkende Seiten (Inhalt) mit ausgeben")
    args = ap.parse_args(argv)
    d = Path(args.dir)
    ein = zaehlen(d)
    alle = sorted(p.name for p in d.glob("*.html") if p.name not in ("404.html", "impressum.html", "datenschutz.html"))
    if args.unter is not None:
        namen = [n for n in alle if len(ein.get(n, {}).get("inhalt", ())) < args.unter]
    else:
        namen = [s if s.endswith(".html") else s + ".html" for s in args.seiten]
    if not namen:
        print("Keine Seiten." if args.unter is not None else "Bitte Seiten oder --unter N angeben.")
        return 0
    print(f"{'Seite':<42}{'Inhalt':>7}{'gesamt':>8}")
    for n in namen:
        e = ein.get(n, {"gesamt": set(), "inhalt": set()})
        if not (d / n).exists():
            print(f"{n:<42}  (Seite nicht im Build)")
            continue
        print(f"{n:<42}{len(e['inhalt']):>7}{len(e['gesamt']):>8}")
        if args.quellen:
            print("    " + ", ".join(sorted(e["inhalt"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
