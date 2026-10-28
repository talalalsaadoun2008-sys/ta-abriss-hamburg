#!/usr/bin/env python3
"""Generator für ta-abriss-hamburg.de (nur Python-Standardbibliothek).

Aufruf (im Repo-Hauptordner):
  python3 src/build.py                         Website im Repo bauen
  python3 src/build.py --out DIR --preview     komplette Vorschau nach DIR (mit Hinweisbalken)
  python3 src/build.py --content src/test ...  anderes Inhaltsverzeichnis verwenden

Erzeugt:
  <slug>.html je JSON in src/content/ (Leistungen, Bezirke, Stadtteile, Umland, Ratgeber),
  einsatzgebiet.html (Übersicht aus src/site.json), impressum.html, datenschutz.html,
  index.html (nur die Bereiche zwischen den Markern @head, @header, @zahlen, @umland, @footer),
  sitemap.xml (lastmod je Seite = letzte Git-Änderung ihrer Quelldatei, nicht das Build-Datum); prüft robots.txt.
Seitenrahmen: Ortsseiten zeigen nur die Leistungskarten aus site.json „kernleistungen“ (plus Link „Alle …
Leistungen“), die Fußzeile nur „kernleistungen“ und „fusszeile_ratgeber“; das Menü listet alle Seiten.
Fotos: Liegt neben img/x.jpg eine gleich große img/x.webp (src/tools/make_webp.py), wird das Foto als
<picture> mit WebP und dem JPG als Rückfall ausgegeben; sonst als <img> wie bisher.

Fehlt für eine Seite aus src/site.json die JSON-Datei, wird sie übersprungen und nirgends
verlinkt (Menü, Footer, Chips, Übersicht, Sitemap; Links im Inhalt werden zu reinem Text).

Richtpreise stehen in src/preise.json (optional). Nur Leistungsseiten mit eingetragenen Zahlen
bekommen vor dem Kontaktformular einen Abschnitt „Richtpreise“ (Tabelle, mit JavaScript Rechner).

Leistung in einem Bezirk (type "leistung_ort", z. B. entruempelung-hamburg-altona.html):
  Diese Seiten stehen NICHT in src/site.json. Der Build findet sie über die Inhaltsdatei:
  src/content/<slug>.json mit "type": "leistung_ort", "leistung": <Slug einer Leistung aus site.json>,
  "bezirk": <Slug eines Bezirks aus site.json> und den üblichen Pflichtfeldern (REQUIRED) plus "sources".
  Slug-Regel: <leistung ohne "-hamburg">-<bezirk ohne "abriss-">,
  z. B. entruempelung-hamburg + abriss-hamburg-altona -> entruempelung-hamburg-altona.
  Automatisch verlinkt (nur vorhandene Seiten): Leistungsseite („<Leistung> in Ihrem Bezirk“),
  Bezirksseite („Weitere Leistungen in <Bezirk>“), die Seite selbst (Leistung, Bezirk, andere Bezirke),
  sitemap.xml und llms.txt – nicht in Menü und Footer. Anleitung: src/content/LEISTUNG_ORT_ANLEITUNG.md
"""
import argparse
import datetime
import functools
import html
import json, urllib.parse
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

LEISTUNG_ORT = "leistung_ort"  # Leistung in einem Bezirk, ohne Eintrag in site.json (siehe Kopf)
TYPES = ("leistung", "bezirk", "stadtteil", "umland", "ratgeber", LEISTUNG_ORT)
ORTSTYPEN = ("bezirk", "stadtteil", "umland")
UEBERSICHT = "einsatzgebiet"  # erzeugte Übersichtsseite einsatzgebiet.html
ABOUT = "ueber-uns"  # Über-uns-Seite: läuft als ratgeber, aber mit AboutPage-Daten und ohne Quellen-Pflicht
SECTION_TAGS = {"p", "ul", "ol", "li", "strong", "em", "h3", "a"}
INLINE_TAGS = {"strong", "em", "a"}
A_ATTRS = {"href", "title", "rel"}
REQUIRED = ("slug", "type", "menu", "title", "description", "label", "h1", "lead", "facts",
            "image", "form_leistung", "form_ort", "sections", "faq")
KNOWN = set(REQUIRED) | {"stadtteile", "sources", "notes_for_review", "note_stellen", "leistung", "bezirk", "galerie"}
MAX_WEITERE_ORTE = 8

CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l5 5L20 6"/></svg>'
PHONE_SVG = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5'
             'L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>')
CHAT_SVG = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z"/>'
            '<path d="M8 9.5h8M8 12.5h5"/></svg>')
WA_TEXT = "Hallo T&A, ich habe eine Anfrage: "


def wa_link(f, text=WA_TEXT):
    return f"https://wa.me/{f['whatsapp']}?text=" + urllib.parse.quote(text)


ARR = '<span class="arr" aria-hidden="true">→</span>'
A_RE = re.compile(r'<a\s[^>]*?href=(["\'])(.*?)\1[^>]*>(.*?)</a>', re.S)


class BuildError(Exception):
    pass


def esc(s):
    return html.escape(str(s), quote=True)


def is_str(v):
    return isinstance(v, str) and v.strip() != ""


def jsonld(obj):
    """JSON-LD-Block; '</' wird escaped, damit kein </script> im Text das Tag beendet."""
    text = json.dumps(obj, ensure_ascii=False, indent=None).replace("</", "<\\/")
    return '<script type="application/ld+json">' + text + "</script>"


# ---------------------------------------------------------------------------
# Seitenliste
# ---------------------------------------------------------------------------
class Site:
    def __init__(self, path):
        d = json.loads(path.read_text(encoding="utf-8"))
        self.raw = d
        self.base = d["base_url"]
        self.firma = d["firma"]
        self.anker = d["startseite_anker"]
        self.leistungen = d["leistungen"]
        self.bezirke = d["bezirke"]
        self.stadtteile = d.get("stadtteile", [])
        self.umland = d.get("umland", [])
        self.ratgeber = d["ratgeber"]
        self.rechtliches = d["rechtliches"]
        self.bilder = d["bilder"]
        self.form_options = d["formular_leistungen"]
        self.uebersicht = d.get("einsatzgebiet") or {}
        self.menue_umland = d.get("menue_umland", [])
        self.startseite_umland = d.get("startseite_umland", [])
        # Kurzer Seitenrahmen: Ortsseiten zeigen nur diese Leistungskarten, die Fußzeile nur diese Leistungen
        # und Ratgeber (jeweils mit Link „Alle …“ auf die Startseite). Das Menü listet weiterhin alles.
        self.kernleistungen = d.get("kernleistungen", [])
        self.fusszeile_ratgeber = d.get("fusszeile_ratgeber", [])
        self.kind = {}
        self.entry = {}
        for kind, items in (("leistung", self.leistungen), ("bezirk", self.bezirke),
                            ("stadtteil", self.stadtteile), ("umland", self.umland),
                            ("ratgeber", self.ratgeber), ("recht", self.rechtliches)):
            for it in items:
                slug = it.get("slug")
                if not (isinstance(slug, str) and re.fullmatch(r"[a-z0-9-]+", slug)):
                    raise BuildError(f"site.json: ungültiger Slug {slug!r} ({kind})")
                if slug in (UEBERSICHT, "index", "sitemap"):
                    raise BuildError(f"site.json: Slug '{slug}' ist für den Build reserviert")
                if slug in self.kind:
                    raise BuildError(f"site.json: Slug doppelt: {slug}")
                if not is_str(it.get("name")):
                    raise BuildError(f"site.json: {slug} braucht 'name'")
                self.kind[slug] = kind
                self.entry[slug] = it
        for st in self.stadtteile:
            if self.kind.get(st.get("bezirk")) != "bezirk":
                raise BuildError(f"site.json: Stadtteil {st['slug']}: 'bezirk' muss der Slug einer Bezirksseite sein "
                                 f"(ist {st.get('bezirk')!r})")
        for u in self.umland:
            for k in ("kreis", "land"):
                if not is_str(u.get(k)):
                    raise BuildError(f"site.json: Umland {u['slug']} braucht '{k}'")
        for key, art in (("menue_umland", "umland"), ("startseite_umland", "umland"), ("kernleistungen", "leistung"),
                         ("fusszeile_ratgeber", "ratgeber")):
            for x in d.get(key, []):
                if self.kind.get(x) != art:
                    raise BuildError(f"site.json: {key}: '{x}' steht nicht in '{'leistungen' if art == 'leistung' else art}'")
            if len(set(d.get(key, []))) != len(d.get(key, [])):
                raise BuildError(f"site.json: {key}: Eintrag doppelt")
        for k in ("title", "description", "label", "h1", "lead", "hinweis"):
            if not is_str(self.uebersicht.get(k)):
                raise BuildError(f"site.json: einsatzgebiet.{k} fehlt")
        for key, b in self.bilder.items():
            datei = b.get("datei")
            if not (isinstance(datei, str) and re.fullmatch(r"[a-z0-9-]+\.(jpg|jpeg|png|webp)", datei)):
                raise BuildError(f"site.json: bilder.{key} braucht 'datei' (z. B. 'abriss-ziegelwand.jpg', nur a-z, 0-9, -)")
            if not (ROOT / "img" / datei).is_file():
                raise BuildError(f"site.json: bilder.{key}: img/{datei} fehlt")
        for it in self.leistungen:
            if it.get("bild") not in self.bilder:
                raise BuildError(f"site.json: Leistung {it['slug']}: 'bild' muss eines von {', '.join(self.bilder)} sein")
        # Leistung in einem Bezirk: alle möglichen Slugs; Seiten kommen erst mit ihrer Inhaltsdatei dazu (register_lo)
        self.rang = {it["slug"]: i for i, it in enumerate(self.leistungen + self.bezirke)}
        self.lo_moeglich = {}
        for le in self.leistungen:
            for bz in self.bezirke:
                lo = lo_slug(le["slug"], bz["slug"])
                if lo in self.kind:
                    raise BuildError(f"site.json: Slug {lo} ist für die Seite {le['name']} in {bz['name']} reserviert")
                self.lo_moeglich[lo] = (le["slug"], bz["slug"])
        self.leistung_orte = []  # Einträge {slug, name (= Bezirk), leistung, bezirk} der gefundenen Seiten

    def register_lo(self, c, path, errors):
        """Inhaltsdatei vom Typ leistung_ort als Seite anmelden (statt Eintrag in site.json). False bei Fehlern."""
        where = path.name
        e = lambda msg: errors.append(f"{where}: {msg}")
        le, bz, slug = c.get("leistung"), c.get("bezirk"), c.get("slug")
        ok = True
        if self.kind.get(le) != "leistung":
            e(f"'leistung' muss der Slug einer Leistung aus src/site.json sein (z. B. entruempelung-hamburg), ist {le!r}")
            ok = False
        if self.kind.get(bz) != "bezirk":
            e(f"'bezirk' muss der Slug eines Bezirks aus src/site.json sein "
              f"({', '.join(b['slug'] for b in self.bezirke)}), ist {bz!r}")
            ok = False
        if not ok:
            return False
        soll = lo_slug(le, bz)
        if slug != soll or path.stem != soll:
            e(f"slug und Dateiname müssen '{soll}' heißen (Leistung {le} + Bezirk {bz}; Regel: "
              f"<leistung ohne '-hamburg'>-<bezirk ohne 'abriss-'>), sind slug {slug!r}, Datei {path.stem!r}")
            return False
        if slug in self.kind:
            e(f"Seite {slug} gibt es schon")
            return False
        entry = {"slug": slug, "name": self.entry[bz]["name"], "leistung": le, "bezirk": bz}
        self.kind[slug] = LEISTUNG_ORT
        self.entry[slug] = entry
        self.leistung_orte.append(entry)
        self.leistung_orte.sort(key=lambda x: (self.rang[x["leistung"]], self.rang[x["bezirk"]]))
        return True

    def bild_src(self, key):
        """Relativer Pfad eines Bildes aus 'bilder' (Schlüssel bleibt gleich, Dateiname steht in 'datei')."""
        return "img/" + self.bilder[key]["datei"]

    def bild_url(self, key):
        return self.base + self.bild_src(key)

    def content_slugs(self):
        return [it["slug"] for it in self.leistungen + self.leistung_orte + self.bezirke + self.ratgeber + self.stadtteile
                + self.umland]

    def url(self, slug):
        return self.base + slug + ".html"

    def bezirk_of(self, stadtteil):
        return self.entry[stadtteil["bezirk"]]


def lo_slug(leistung, bezirk):
    """Slug der Seite „Leistung in einem Bezirk“: entruempelung-hamburg + abriss-hamburg-altona -> entruempelung-hamburg-altona."""
    return leistung.removesuffix("-hamburg") + "-" + bezirk.removeprefix("abriss-")


def internal_slug(site, href):
    """Slug einer internen Unterseite (<slug>.html, auch als volle Adresse) oder None."""
    if re.match(r"https?://", href):
        if not href.startswith(site.base):
            return None
        href = href[len(site.base):]
    m = re.fullmatch(r"([a-z0-9-]+)\.html", href.partition("#")[0])
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Prüfung der Inhalte
# ---------------------------------------------------------------------------
class FragmentChecker(HTMLParser):
    """Lässt nur erlaubte Tags zu, prüft Verschachtelung und sammelt Links."""

    def __init__(self, allowed):
        super().__init__(convert_charrefs=True)
        self.allowed = allowed
        self.errors = []
        self.links = []
        self.stack = []

    def _tag(self, tag, attrs):
        if tag not in self.allowed:
            self.errors.append(f"Tag <{tag}> ist nicht erlaubt (erlaubt: {', '.join(sorted(self.allowed))})")
            return
        names = [a for a, _ in attrs]
        if tag == "a":
            bad = [a for a in names if a not in A_ATTRS]
            if bad:
                self.errors.append(f"<a> mit nicht erlaubtem Attribut: {', '.join(bad)}")
            href = dict(attrs).get("href")
            if not href:
                self.errors.append("<a> ohne href")
            else:
                self.links.append(href)
        elif names:
            self.errors.append(f"<{tag}> darf keine Attribute haben ({', '.join(names)})")

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs)
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self._tag(tag, attrs)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.errors.append(f"<{self.stack.pop()}> nicht geschlossen")
            self.stack.pop()
        else:
            self.errors.append(f"</{tag}> ohne öffnendes Tag")

    def handle_comment(self, data):
        self.errors.append("HTML-Kommentare sind nicht erlaubt")

    def handle_decl(self, decl):
        self.errors.append("Deklarationen sind nicht erlaubt")

    def handle_pi(self, data):
        self.errors.append("Processing Instructions sind nicht erlaubt")

    def finish(self):
        self.close()
        for t in self.stack:
            self.errors.append(f"<{t}> nicht geschlossen")
        return self


def check_fragment(text, allowed):
    c = FragmentChecker(allowed)
    c.feed(text)
    return c.finish()


class Linker:
    """Prüft Links aus Inhalten gegen die vorhandenen Seiten."""

    def __init__(self, site, generated, home_ids, warn):
        self.site = site
        self.generated = set(generated)
        self.home_ids = home_ids
        self.warn = warn
        self.pending = {}  # Ziel-Slug ohne Inhalt -> Fundstellen

    def check(self, href, where):
        """Gibt eine Fehlermeldung zurück oder None."""
        if href.startswith(("mailto:", "tel:")):
            return None
        if re.match(r"https?://", href):
            if not href.startswith(self.site.base):
                return None  # externer Link
            self.warn(f"{where}: interner Link als volle Adresse ({href}) – bitte relativ verlinken")
            href = href[len(self.site.base):] or "./"
        path, _, frag = href.partition("#")
        if path in ("", "./", "index.html"):
            if path == "":
                return None if frag else f"leerer Link"
            if frag and frag not in self.home_ids:
                return f"Link {href}: Anker #{frag} gibt es auf der Startseite nicht"
            return None
        m = re.fullmatch(r"([a-z0-9-]+)\.html", path)
        if not m:
            return f"Link {href}: keine bekannte Seite (Seiten relativ als <slug>.html verlinken)"
        slug = m.group(1)
        if slug in self.generated or slug == UEBERSICHT or self.site.kind.get(slug) == "recht":
            return None
        if slug in self.site.kind or slug in self.site.lo_moeglich:
            self.pending.setdefault(slug, []).append(where.split(" ")[0])
            return None
        return f"Link {href}: Seite {slug}.html gibt es nicht (nicht in src/site.json)"


def validate(c, path, site, errors, warn):
    where = path.name
    before = len(errors)
    e = lambda msg: errors.append(f"{where}: {msg}")
    if not isinstance(c, dict):
        e("JSON muss ein Objekt sein")
        return False
    for k in REQUIRED:
        if k not in c:
            e(f"Feld '{k}' fehlt")
    for k in c:
        if k not in KNOWN:
            warn(f"{where}: unbekanntes Feld '{k}' wird ignoriert")
    if any(k not in c for k in REQUIRED):
        return False
    for k in ("slug", "type", "menu", "title", "description", "label", "h1", "lead", "image", "form_leistung"):
        if not is_str(c[k]):
            e(f"Feld '{k}' muss ein nicht leerer Text sein")
    if not isinstance(c["form_ort"], str):
        e("Feld 'form_ort' muss ein Text sein (darf leer sein)")
    if c["slug"] != path.stem:
        e(f"slug '{c['slug']}' passt nicht zum Dateinamen")
    if c["type"] not in TYPES:
        e(f"type muss {', '.join(TYPES)} sein")
    kind = site.kind.get(c["slug"])
    if kind is None:
        e(f"slug '{c['slug']}' steht nicht in src/site.json")
    elif kind != c["type"]:
        e(f"type '{c['type']}' passt nicht zu src/site.json ({kind})")
    if not (isinstance(c["facts"], list) and len(c["facts"]) == 3 and all(is_str(x) for x in c["facts"])):
        e("facts muss genau 3 Texte enthalten")
    if c["image"] not in site.bilder:
        e(f"image muss eines von {', '.join(site.bilder)} sein")
    if c["form_leistung"] not in site.form_options:
        e(f"form_leistung muss eines von {', '.join(site.form_options)} sein")
    if not (isinstance(c["sections"], list) and c["sections"]):
        e("sections muss eine nicht leere Liste sein")
    else:
        for i, s in enumerate(c["sections"], 1):
            if not (isinstance(s, dict) and is_str(s.get("h2")) and is_str(s.get("html"))):
                e(f"sections[{i}] braucht 'h2' und 'html'")
    if not isinstance(c["faq"], list):
        e("faq muss eine Liste sein")
    else:
        for i, f in enumerate(c["faq"], 1):
            if not (isinstance(f, dict) and is_str(f.get("q")) and is_str(f.get("a"))):
                e(f"faq[{i}] braucht 'q' und 'a'")
    st = c.get("stadtteile")
    if c["type"] != LEISTUNG_ORT:
        for k in ("leistung", "bezirk"):
            if k in c:
                warn(f"{where}: Feld '{k}' gibt es nur bei type '{LEISTUNG_ORT}' – wird ignoriert")
    else:
        if st:
            warn(f"{where}: 'stadtteile' wird bei {LEISTUNG_ORT}-Seiten nicht angezeigt")
        src = c.get("sources")
        if not (isinstance(src, list) and src):
            e(f"{LEISTUNG_ORT} braucht 'sources' (interne Belege für die lokalen Angaben, werden nicht angezeigt)")
        else:
            for i, s in enumerate(src, 1):
                if not (isinstance(s, dict) and is_str(s.get("title")) and re.match(r"https?://", str(s.get("url", "")))):
                    e(f"sources[{i}] braucht 'title' und eine http(s)-'url'")
        le = site.entry.get(c.get("leistung"))
        if le:
            soll = le["name"].replace(" & ", " und ")
            if soll in site.form_options and c["form_leistung"] != soll:
                warn(f"{where}: form_leistung ist '{c['form_leistung']}', passend zur Leistung wäre '{soll}'")
    if c["type"] == "bezirk":
        if not (isinstance(st, list) and st and all(is_str(x) for x in st)):
            e("bezirk braucht 'stadtteile' (Liste mit Texten)")
    elif c["type"] in ("stadtteil", "umland") and st is not None:
        if not (isinstance(st, list) and all(is_str(x) for x in st)):
            e("'stadtteile' muss eine Liste mit Texten sein (darf leer sein)")
        elif st and c["type"] == "stadtteil":
            warn(f"{where}: 'stadtteile' wird bei Stadtteil-Seiten nicht angezeigt")
    gal = c.get("galerie")  # eigene Arbeitsfotos: [{"bild": Schlüssel aus site.json bilder, "text": Bildunterschrift}]
    if gal is not None:
        if not (isinstance(gal, list) and gal and all(isinstance(g, dict) and g.get("bild") in site.bilder
                                                       and is_str(g.get("text")) for g in gal)):
            e("galerie: Liste von {bild (Schlüssel aus site.json bilder), text} erwartet")
    if c["type"] == "ratgeber" and (c["slug"] != ABOUT or c.get("sources")):
        src = c.get("sources")
        if not (isinstance(src, list) and src):
            e("ratgeber braucht 'sources'")
        else:
            for i, s in enumerate(src, 1):
                if not (isinstance(s, dict) and is_str(s.get("title")) and re.match(r"https?://", str(s.get("url", "")))):
                    e(f"sources[{i}] braucht 'title' und eine http(s)-'url'")
    # Bei leistung/bezirk/stadtteil/umland bleiben 'sources' als interner Beleg in der JSON-Datei (nicht ausgegeben).
    if is_str(c.get("title")) and len(c["title"]) > 65:
        warn(f"{where}: title ist {len(c['title'])} Zeichen lang (Google zeigt ca. 60)")
    if is_str(c.get("description")):
        n = len(c["description"]) + (0 if c.get("type") == "ratgeber" else len(meta_suffix(site)))
        if n > 160:
            warn(f"{where}: Google-Beschreibung ist mit Häkchen-Zeile {n} Zeichen lang (Google zeigt ca. 155)")
    return len(errors) == before  # nur fehlerfreie Inhalte gehen in die Linkprüfung


def check_links_in(c, linker, errors):
    where = c["slug"] + ".json"
    frags = [(f"sections[{i}].html", s["html"], SECTION_TAGS) for i, s in enumerate(c["sections"], 1)]
    frags += [(f"faq[{i}].a", f["a"], INLINE_TAGS) for i, f in enumerate(c["faq"], 1) if "<" in f["a"]]
    for label, text, allowed in frags:
        chk = check_fragment(text, allowed)
        for msg in chk.errors:
            errors.append(f"{where} {label}: {msg}")
        for href in chk.links:
            msg = linker.check(href, f"{where} {label}")
            if msg:
                errors.append(f"{where} {label}: {msg}")


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, site, preview, today, generated, home_src):
        self.site = site
        self.preview = preview
        self.today = today
        self.generated = set(generated)
        self.home = "index.html" if preview else "./"
        self.home_src = home_src
        self.content_rel = "src/content"
        self.preise = None  # Richtpreise aus src/preise.json (load_preise)

    def has(self, slug):
        """Gibt es die Seite im Build? Nur dann wird sie verlinkt."""
        return slug in self.generated or slug == UEBERSICHT or self.site.kind.get(slug) == "recht"

    def pages(self, items):
        return [x for x in items if self.has(x["slug"])]

    def lo_pages(self, leistung=None, bezirk=None):
        """Vorhandene Seiten „Leistung in einem Bezirk“, Reihenfolge wie Leistungen/Bezirke in site.json."""
        return [x for x in self.site.leistung_orte if self.has(x["slug"])
                and leistung in (None, x["leistung"]) and bezirk in (None, x["bezirk"])]

    def home_link(self, anchor, on_home):
        if on_home:
            return "#" + anchor
        if anchor == "start":
            return self.home
        return self.home + "#" + anchor

    def fix_home_links(self, text):
        """Links auf die Startseite in Inhalten an den Build anpassen (Vorschau: index.html, live: ./ wie canonical)."""
        if not self.preview:
            return re.sub(r'href="index\.html(#[^"]*)?"', lambda m: f'href="./{m.group(1) or ""}"', text)
        return re.sub(r'href="\./(#[^"]*)?"', lambda m: f'href="index.html{m.group(1) or ""}"', text)

    def drop_dead_links(self, text):
        """Links auf Seiten aus site.json, für die es (noch) keinen Inhalt gibt, werden zu reinem Text."""
        def rep(m):
            slug = internal_slug(self.site, html.unescape(m.group(2)))
            if slug and (slug in self.site.kind or slug in self.site.lo_moeglich) and not self.has(slug):
                return m.group(3)
            return m.group(0)
        return A_RE.sub(rep, text)

    def content_html(self, text):
        return self.fix_home_links(self.drop_dead_links(text))


def head_assets(ctx, extra_noindex=False):
    out = [
        '<link rel="preload" href="assets/fonts/barlow-condensed-latin-800-normal.woff2" as="font" type="font/woff2" crossorigin>',
        '<link rel="stylesheet" href="assets/fonts.css">',
        '<link rel="stylesheet" href="assets/site.css">',
        '<script src="assets/site.js" defer></script>',
        '<noscript><style>button.burger{display:none}.menu:target{display:block}</style></noscript>',
    ]
    if ctx.preview and extra_noindex:
        out.append('<meta name="robots" content="noindex">')
    return out


def cur(is_current):
    return ' aria-current="page"' if is_current else ""


def render_header(ctx, current, on_home, contact_href):
    s = ctx.site
    brand = "#start" if on_home else ctx.home
    nav = "".join(f'<a href="{esc(ctx.home_link(a["anker"], on_home))}">{esc(a["kopfzeile"])}</a>'
                  for a in s.anker if a.get("kopfzeile"))
    bars = '<span class="bars" aria-hidden="true"><i></i><i></i><i></i></span>'
    out = []
    if ctx.preview:
        out.append('<div class="draft" role="note"><div class="wrap">Vorschau – noch nicht online</div></div>')
    out.append(f'''<header class="top"><div class="wrap">
  <a class="brand" href="{esc(brand)}"><b><i>T&amp;A</i><i aria-hidden="true">T&amp;A</i></b><span>Abriss &amp; Rückbau</span></a>
  <nav class="links" aria-label="Hauptnavigation">
    {nav}
  </nav>
  <div class="tools">
    <a class="btn header-cta" href="{esc(contact_href)}">Anfrage {ARR}</a>
    <button class="burger" type="button" aria-expanded="false" aria-controls="menu" aria-label="Menü öffnen">{bars}</button>
    <noscript><a class="burger" href="#menu" aria-label="Menü öffnen">{bars}</a></noscript>
  </div>
</div></header>''')
    out.append(render_menu(ctx, current, on_home, contact_href))
    return "\n".join(out)


def menu_list(items, cls=""):
    lis = "".join(f'\n      <li><a href="{esc(h)}"{cur(c)}>{esc(t)}</a></li>' for h, t, c in items)
    c = f' class="{cls}"' if cls else ""
    return f"<ul{c}>{lis}\n    </ul>"


def render_menu(ctx, current, on_home, contact_href):
    s, f = ctx.site, ctx.site.firma
    main = [(ctx.home_link(a["anker"], on_home), a["name"], on_home and a["anker"] == "start") for a in s.anker]
    page = lambda it: (it["slug"] + ".html", it["name"], it["slug"] == current)
    alle = (f'<a class="menu-all" href="{UEBERSICHT}.html"{cur(current == UEBERSICHT)}>Alle Stadtteile und Orte '
            f'<span aria-hidden="true">→</span></a>')
    groups = [
        ("g-leist", "m-leist", "Leistungen", [page(x) for x in ctx.pages(s.leistungen)], "cols", ""),
        ("g-bez", "m-bez", "Abriss nach Bezirk", [page(x) for x in ctx.pages(s.bezirke)], "cols", ""),
        ("g-uml", "m-uml", "Umland", [page(s.entry[x]) for x in s.menue_umland if ctx.has(x)], "cols", alle),
        ("g-rat", "m-rat", "Ratgeber", [page(x) for x in ctx.pages(s.ratgeber)], "", ""),
        ("g-recht", "m-recht", "Rechtliches", [page(x) for x in s.rechtliches], "cols", ""),
    ]
    parts = [f'<div class="grp g-main">\n    {menu_list(main)}\n  </div>']
    for gcls, hid, title, items, lcls, extra in groups:
        inner = []
        if items:
            lst = menu_list(items, lcls).replace("<ul", f'<ul aria-labelledby="{hid}"', 1)
            inner += [f'<p class="menu-h" id="{hid}">{esc(title)}</p>', lst]
        if extra:
            if not items:  # noch keine Umland-Seite: Link bekommt eine eigene Überschrift
                inner.append(f'<p class="menu-h" id="{hid}">Einsatzgebiet</p>')
            inner.append(extra)
        if inner:
            parts.append(f'<div class="grp {gcls}">\n    ' + "\n    ".join(inner) + '\n  </div>')
    parts.append(f'''<div class="menu-cta">
    <a class="btn alt" href="tel:{esc(f["telefon_link"])}">{PHONE_SVG}{esc(f["telefon"])}</a>
    <a class="btn alt" href="{esc(wa_link(f))}" target="_blank" rel="noopener">{CHAT_SVG}WhatsApp</a>
    <a class="btn" href="{esc(contact_href)}">Kostenlose Besichtigung {ARR}</a>
    <noscript><a class="btn alt" href="#start">Menü schließen</a></noscript>
  </div>''')
    return '<nav id="menu" class="menu" aria-label="Menü">\n  ' + "\n  ".join(parts) + "\n</nav>"


def kern_leistungen(ctx):
    """Leistungen für Ortsseiten-Karten und Fußzeile: 'kernleistungen' aus site.json (nur Seiten mit Inhalt),
    ohne Eintrag dort alle Leistungen."""
    s = ctx.site
    kern = [s.entry[x] for x in s.kernleistungen if ctx.has(x)]
    return kern or ctx.pages(s.leistungen)


def render_footer(ctx, current, on_home, fab_href):
    """Kurze Fußzeile: wichtigste Leistungen und Ratgeber mit Link „Alle …“, Bezirke, kurze Umland-Liste,
    Über uns und Rechtliches. Vollständige Listen stehen im Menü und auf der Startseite."""
    s, f = ctx.site, ctx.site.firma
    li = lambda it: f'<li><a href="{esc(it["slug"])}.html"{cur(it["slug"] == current)}>{esc(it["name"])}</a></li>'
    mehr = lambda href, text, aktiv=False: (f'<p class="foot-all"><a href="{esc(href)}"{cur(aktiv)}>{esc(text)} '
                                           f'<span aria-hidden="true">→</span></a></p>')
    kern = kern_leistungen(ctx)
    leist = "".join(li(x) for x in kern)
    bez = "".join(li(x) for x in ctx.pages(s.bezirke))
    rat_alle = [x for x in ctx.pages(s.ratgeber) if x["slug"] != ABOUT]
    rat = [x for x in rat_alle if x["slug"] in s.fusszeile_ratgeber] if s.fusszeile_ratgeber else rat_alle
    rest = "".join(li(x) for x in ctx.pages([s.entry[ABOUT]] if ABOUT in s.entry else []) + s.rechtliches)
    uml ="".join(li(s.entry[x]) for x in s.menue_umland if ctx.has(x))  # kurze Ortsliste, Linktext = Ortsname
    alle = mehr(f"{UEBERSICHT}.html", "Alle Orte im Einsatzgebiet", current == UEBERSICHT)
    ids = home_ids(ctx.home_src)
    cols = []
    if leist:
        weitere = mehr(ctx.home_link("leistungen", on_home), "Alle Leistungen") if len(kern) < len(ctx.pages(s.leistungen)) else ""
        cols.append(f'  <div><h3>Leistungen</h3><ul class="two">{leist}</ul>{weitere}</div>')
    cols.append(f'  <div><h3>Bezirke</h3>' + (f'<ul class="two">{bez}</ul>' if bez else "") + f'{alle}</div>')
    if uml:
        cols.append(f'  <div class="foot-uml"><h3>Umland</h3><ul class="two">{uml}</ul></div>')
    rat_mehr = (mehr(ctx.home_link("ratgeber", on_home), "Alle Ratgeber")
                if len(rat) < len(rat_alle) and "ratgeber" in ids else "")
    rat_ul = f'<ul>{"".join(li(x) for x in rat)}</ul>' if rat else ""
    cols.append(f'  <div class="foot-rat"><h3>Ratgeber &amp; Rechtliches</h3>{rat_ul}{rat_mehr}<ul>{rest}</ul></div>')
    out = [f'''<footer><div class="wrap foot">
  <div class="firma">
    <h3>{esc(f["name"])}</h3>
    <p>Inh. {esc(f["inhaber"])}<br>{esc(f["strasse"])}<br>{esc(f["plz"])} {esc(f["ort"])}</p>
    <ul><li><a href="tel:{esc(f["telefon_link"])}">Telefon: {esc(f["telefon"])}</a></li><li><a href="mailto:{esc(f["email"])}">{esc(f["email"])}</a></li></ul>
    <p class="partner"><span>Partner für Entrümpelung:</span> <a href="https://hafenraeumer.de" rel="nofollow">HafenRäumer</a> · <a href="https://hinnerk-entruempelung.de/">Hinnerk – Entrümpelung Hamburg</a></p>
  </div>
''' + "\n".join(cols) + '\n</div></footer>']
    # Kontaktleiste auf jeder Seite und jeder Bildschirmgröße, immer sichtbar: Anrufen, WhatsApp, Anfrage.
    # Seiten ohne eigenes Formular verlinken „Anfrage“ auf das Formular der Startseite.
    req = fab_href or ctx.home_link("anfrage", on_home)
    out.append(f'\n<div class="fab-bar"><div class="fab">'
               f'<a class="btn alt fab-tel" href="tel:{esc(f["telefon_link"])}" aria-label="Anrufen: {esc(f["telefon"])}">'
               f'{PHONE_SVG}Anrufen<span class="fab-num">&nbsp;{esc(f["telefon"])}</span></a>'
               f'<a class="btn alt fab-wa" href="{esc(wa_link(f))}" target="_blank" rel="noopener" aria-label="WhatsApp: {esc(f["telefon"])}">{CHAT_SVG}WhatsApp</a>'
               f'<a class="btn fab-req" href="{esc(req)}">Anfrage {ARR}</a></div></div>')
    return "".join(out)


def facts_html(facts):
    return "\n      ".join(f"<span>{CHECK_SVG}{esc(x)}</span>" for x in facts)


def inline_html(text):
    """FAQ-Antwort: reiner Text wird escaped, sonst geprüftes Inline-HTML übernommen."""
    return text if "<" in text else esc(text)


def absolutize(site, fragment):
    def rep(m):
        href = m.group(1)
        if re.match(r"(https?:|mailto:|tel:)", href):
            return m.group(0)
        if href.startswith("./"):
            href = href[2:]
        if href.startswith("index.html"):
            href = href[len("index.html"):]
        return f'href="{site.base}{href}"'
    return re.sub(r'href="([^"]*)"', rep, fragment)


def faq_jsonld(site, pairs):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q,
         "acceptedAnswer": {"@type": "Answer", "text": absolutize(site, a)}} for q, a in pairs]}


def ld_bild(site, name):
    """Absolute Bildadresse für JSON-LD (Dateiname aus site.json 'bilder')."""
    return site.bild_url(name)


def ld_adresse(f):
    return {"@type": "PostalAddress", "streetAddress": f["strasse"], "postalCode": f["plz"],
            "addressLocality": f["ort"], "addressCountry": "DE"}


def ld_firma(site):
    """Kurzform der Firma für Unterseiten (provider, author, publisher). Gleiche @id wie auf der Startseite;
    Name, Adresse und Telefon stehen mit drin, damit jede Seite für sich vollständig ist."""
    f = site.firma
    return {"@type": "HomeAndConstructionBusiness", "@id": site.base + "#firma", "name": f["name"], "url": site.base,
            "telephone": f["telefon_schema"], "address": ld_adresse(f)}


def git_daten(path):
    """(erste, letzte) Version einer Datei laut Git als Datum JJJJ-MM-TT. Ohne Git-Historie heute;
    ungespeicherte Änderungen zählen als heute. So bleibt datePublished bei jedem Build gleich."""
    heute = datetime.date.today().isoformat()
    git = lambda *a: subprocess.run(["git", "-C", str(path.parent), *a], capture_output=True, text=True,
                                    timeout=20, check=True).stdout
    try:
        tage = [x[:10] for x in git("log", "--follow", "--format=%aI", "--", path.name).split()]
        offen = git("status", "--porcelain", "--", path.name).strip()
    except (OSError, subprocess.SubprocessError):
        return heute, heute
    if not tage:
        return heute, heute
    return tage[-1], heute if offen else tage[0]


def breadcrumb_ld(items):
    """items: Liste (Name, absolute URL); Einträge ohne URL werden ausgelassen."""
    items = [(n, u) for n, u in items if u]
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i, "name": n, "item": u} for i, (n, u) in enumerate(items, 1)]}


def crumbs_html(items):
    """items: Liste (Name, href oder None); der letzte Eintrag ist die aktuelle Seite."""
    lis = []
    for i, (name, href) in enumerate(items):
        if i == len(items) - 1:
            lis.append(f'  <li><span aria-current="page">{esc(name)}</span></li>')
        elif href:
            lis.append(f'  <li><a href="{esc(href)}">{esc(name)}</a></li>')
        else:
            lis.append(f'  <li><span>{esc(name)}</span></li>')
    return '<nav class="crumbs wrap" aria-label="Brotkrumen"><ol>\n' + "\n".join(lis) + '\n</ol></nav>'


def image_size(path):
    """(Breite, Höhe) einer JPG- oder WebP-Datei aus dem Dateikopf (nur Standardbibliothek), sonst None."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    le = lambda a, b: int.from_bytes(data[a:b], "little")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":  # verlustbehaftet
            return le(26, 28) & 0x3FFF, le(28, 30) & 0x3FFF
        if chunk == b"VP8L" and data[20:21] == b"\x2f":  # verlustfrei
            bits = le(21, 25)
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8X":  # erweitert (z. B. mit Farbprofil)
            return le(24, 27) + 1, le(27, 30) + 1
        return None
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):  # JPEG: Segmente bis zum Bildkopf (SOFn) durchgehen
        if data[i] != 0xFF:
            return None
        m = data[i + 1]
        if m == 0xFF or m == 0x01 or 0xD0 <= m <= 0xD8:  # Füllbyte oder Marker ohne Länge
            i += 1 if m == 0xFF else 2
            continue
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


@functools.lru_cache(maxsize=None)
def webp_for(src):
    """'img/x.webp', wenn neben dem Foto img/x.jpg eine gleich große x.webp liegt, sonst None.

    Ist die WebP anders groß als das JPG (z. B. Foto ersetzt, WebP nicht neu erzeugt), wird sie nicht
    benutzt; check_images() meldet das als Warnung."""
    jpg = ROOT / src
    if jpg.suffix.lower() not in (".jpg", ".jpeg"):
        return None
    webp = jpg.with_suffix(".webp")
    if not webp.is_file() or image_size(webp) != image_size(jpg):
        return None
    return Path(src).with_suffix(".webp").as_posix()


def picture_html(src, attrs):
    """Foto aus img/: <img>, oder <picture> mit WebP und dem JPG als Rückfall, wenn es die .webp daneben gibt.

    src: Pfad wie im HTML, z. B. "img/abriss.jpg" (unabhängig vom Dateinamen).
    attrs: weitere <img>-Attribute als dict in Ausgabereihenfolge ("class" steht vor src; Wert None = ohne Wert).
    Ohne .webp ist die Ausgabe genau das bisherige <img>."""
    attrs = dict(attrs)
    parts = [f'class="{esc(attrs.pop("class"))}"'] if "class" in attrs else []
    parts.append(f'src="{esc(src)}"')
    parts += [esc(k) if v is None else f'{esc(k)}="{esc(v)}"' for k, v in attrs.items()]
    img = "<img " + " ".join(parts) + ">"
    webp = webp_for(src)
    if not webp:
        return img
    return f'<picture><source type="image/webp" srcset="{esc(webp)}">{img}</picture>'


def mini_card(ctx, it):
    b = ctx.site.bilder[it["bild"]]
    img = picture_html(ctx.site.bild_src(it["bild"]), {"width": b["w"], "height": b["h"], "alt": b["alt"], "loading": "lazy"})
    return f'''<article class="mini reveal">
      {img}
      <div class="body">
        <h3><a href="{esc(it["slug"])}.html">{esc(it["name"])}</a></h3>
        <p>{esc(it["kurz"])}</p>
        <span class="go" aria-hidden="true">Mehr zu {esc(it["name"])}&nbsp;<span>→</span></span>
      </div>
    </article>'''


def chip_links(items):
    return "".join(f'<a href="{esc(it["slug"])}.html">{esc(it["name"])}</a>' for it in items)


def stadtteil_page(ctx, bezirk_slug, name):
    """Stadtteil-Seite zu einem Eintrag der Bezirksliste ('Barmbek-Nord' gehört zu 'Barmbek')."""
    for st in ctx.pages(ctx.site.stadtteile):
        if st["bezirk"] == bezirk_slug and (name == st["name"] or name.startswith(st["name"] + "-")):
            return st
    return None


def _nachbarn(liste, entry):
    """Andere Einträge der Liste, von entry aus abwechselnd der nächste und der vorige, im Kreis herum."""
    n = len(liste)
    i = next(k for k, x in enumerate(liste) if x["slug"] == entry["slug"])
    out = []
    for d in range(1, n):
        for x in (liste[(i + d) % n], liste[(i - d) % n]):
            if x["slug"] != entry["slug"] and x not in out:
                out.append(x)
    return out


def weitere_orte(ctx, entry):
    """Andere Umland-Seiten: gleicher Kreis zuerst, dann gleiches Bundesland, dann die übrigen.

    Innerhalb jeder Gruppe die Nachbarn in der Reihenfolge von site.json (grob nach Entfernung von Hamburg),
    abwechselnd danach und davor, im Kreis herum. So verlinkt jede Seite andere Orte, und jede Seite wird gleich
    oft verlinkt (in Kreisen mit mehr als MAX_WEITERE_ORTE Seiten genau MAX_WEITERE_ORTE-mal) – nicht nur die
    ersten Orte eines Kreises."""
    alle = ctx.pages(ctx.site.umland)
    if entry not in alle:
        alle = alle + [entry]
    kreis = [u for u in alle if u["kreis"] == entry["kreis"]]
    land = [u for u in alle if u["land"] == entry["land"]]
    out = []
    for gruppe in (kreis, land, alle):
        for u in _nachbarn(gruppe, entry):
            if len(out) < MAX_WEITERE_ORTE and u not in out:
                out.append(u)
    rank = lambda u: (0 if u["kreis"] == entry["kreis"] else 1 if u["land"] == entry["land"] else 2, alle.index(u))
    return sorted(out, key=rank)


def contact_section(ctx, form_leistung, form_ort, data_page):
    m = re.findall(r'<section class="band" id="anfrage">.*?</section>', ctx.home_src, re.S)
    if len(m) != 1:
        raise BuildError('index.html: Kontaktbereich <section class="band" id="anfrage"> nicht eindeutig gefunden')
    sec = m[0]

    def need(old, new):
        nonlocal sec
        if sec.count(old) != 1:
            raise BuildError(f"index.html: im Kontaktbereich fehlt '{old}'")
        sec = sec.replace(old, new)

    need('data-page="Startseite"', f'data-page="{esc(data_page)}"')
    if form_leistung:
        opt = f"<option>{esc(form_leistung)}</option>"
        need(opt, f"<option selected>{esc(form_leistung)}</option>")
    if form_ort.strip():
        need('<input id="ort" name="ort"', f'<input id="ort" name="ort" value="{esc(form_ort.strip())}"')
    return sec


def subhero(ctx, image, label, h1, lead, facts=None):
    f = ctx.site.firma
    img = ctx.site.bilder[image]
    facts_div = f'''
    <div class="facts">
      {facts_html(facts)}
    </div>''' if facts else ""
    photo = picture_html(ctx.site.bild_src(image), {"class": "photo", "alt": img["alt"], "width": img["w"], "height": img["h"],
                                              "fetchpriority": "high"})
    return f'''<div class="subhero">
  {photo}
  <div class="wrap">
    <p class="label">{esc(label)}</p>
    <h1>{esc(h1)}</h1>
    <p class="lead">{esc(lead)}</p>
    <div class="ctas">
      <a class="btn" href="#anfrage">Kostenlose Besichtigung {ARR}</a>
      <a class="btn line" href="tel:{esc(f["telefon_link"])}">{PHONE_SVG}{esc(f["telefon"])}</a>
    </div>{facts_div}
  </div>
</div>'''


# ---------------------------------------------------------------------------
# Richtpreise (src/preise.json) – kein Preis-Markup im JSON-LD, nur sichtbarer Text
# ---------------------------------------------------------------------------
PREIS_EINHEITEN = ("pauschal", "m2")
PREIS_FELDER = {"name", "einheit", "flaeche", "ab", "bis", "mindestens"}
PREIS_TEXTE = ("inklusive", "zuzueglich")


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def load_preise(path, site, preview, errors, warn):
    """Liest die Richtpreise: {'inklusive', 'zuzueglich', 'seiten': {slug: [Zeile, …]}}.
    Nur Zeilen mit Zahl in 'ab' zählen. Fehlt die Datei oder ist alles null, gibt es keine Preis-Abschnitte."""
    leer = {"inklusive": "", "zuzueglich": "", "seiten": {}}
    if not path.exists():
        return leer
    where = path.name
    e = lambda msg: errors.append(f"{where}: {msg}")
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        e(f"kein gültiges JSON ({ex})")
        return leer
    if not (isinstance(d, dict) and isinstance(d.get("leistungen"), dict)):
        e("braucht ein Objekt 'leistungen' (Slug der Leistungsseite → Liste von Preiszeilen)")
        return leer
    for k in d:
        if k not in ("hinweis", "leistungen") + PREIS_TEXTE:
            warn(f"{where}: unbekanntes Feld '{k}' wird ignoriert")
    texte = {}
    for k in PREIS_TEXTE:
        v = d.get(k)
        if v is not None and not isinstance(v, str):
            e(f"'{k}' muss ein Text sein")
        texte[k] = v.strip() if isinstance(v, str) else ""
    seiten = {}
    for slug, rows in d["leistungen"].items():
        if site.kind.get(slug) != "leistung":
            e(f"'{slug}' ist keine Leistungsseite aus src/site.json")
            continue
        if not isinstance(rows, list):
            e(f"{slug}: braucht eine Liste von Preiszeilen")
            continue
        gut = []
        for i, r in enumerate(rows, 1):
            w = f"{slug}[{i}]"
            if not isinstance(r, dict):
                e(f"{w}: Preiszeile muss ein Objekt sein")
                continue
            for k in r:
                if k not in PREIS_FELDER:
                    warn(f"{where}: {w}: unbekanntes Feld '{k}' wird ignoriert")
            if not is_str(r.get("name")):
                e(f"{w}: 'name' fehlt")
                continue
            if r.get("einheit") not in PREIS_EINHEITEN:
                e(f"{w}: 'einheit' muss {' oder '.join(PREIS_EINHEITEN)} sein")
                continue
            if r.get("flaeche") is not None and not isinstance(r["flaeche"], str):
                e(f"{w}: 'flaeche' muss ein Text sein")
            z = {}
            for k in ("ab", "bis", "mindestens"):
                v = r.get(k)
                if v is not None and not is_num(v):
                    e(f"{w}: '{k}' muss null oder eine Zahl über 0 sein (ohne Anführungszeichen, Punkt statt Komma), "
                      f"ist {v!r}")
                z[k] = v if is_num(v) else None
            if z["ab"] is None:
                if z["bis"] or z["mindestens"]:
                    e(f"{w}: 'bis' oder 'mindestens' ohne 'ab'")
                continue
            if z["bis"] is not None and z["bis"] < z["ab"]:
                e(f"{w}: 'bis' ist kleiner als 'ab'")
            if z["mindestens"] is not None and r["einheit"] != "m2":
                e(f"{w}: 'mindestens' gibt es nur bei einheit 'm2'")
            fl = r.get("flaeche")
            gut.append(dict(z, name=r["name"].strip(), einheit=r["einheit"],
                            flaeche=fl.strip() if isinstance(fl, str) else ""))
        if gut:
            seiten[slug] = gut
    fehlt = [k for k in PREIS_TEXTE if not texte[k]]
    if seiten and fehlt:
        folge = ("Vorschau zeigt gelbe Platzhalter, live erscheinen die Richtpreise erst mit Text" if preview
                 else "Richtpreise werden erst mit Text ausgegeben")
        warn(f"{where}: Preise eingetragen, aber {' und '.join(repr(k) for k in fehlt)} leer – {folge}")
    return dict(texte, seiten=seiten)


def zahl(n):
    """1500 -> '1.500', 42.5 -> '42,50'."""
    s = f"{int(n):,}" if float(n).is_integer() else f"{n:,.2f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def preis_text(r):
    """(Preis, Zusatz) für die Tabelle, z. B. ('ab 1.200 €', '') oder ('40 – 55 €', 'pro m² Wohnfläche')."""
    nb = " "
    if r["bis"] and r["bis"] > r["ab"]:
        main = f"{zahl(r['ab'])}{nb}–{nb}{zahl(r['bis'])}{nb}€"
    else:
        main = f"ab {zahl(r['ab'])}{nb}€"
    sub = ""
    if r["einheit"] == "m2":
        sub = "pro m²" + (" " + r["flaeche"] if r["flaeche"] else "")
        if r["mindestens"]:
            sub += f", mindestens {zahl(r['mindestens'])}{nb}€"
    return main, sub


def preis_section(ctx, slug, name):
    """Abschnitt „Richtpreise“ vor dem Kontaktformular einer Leistungsseite – nur mit Zahlen aus preise.json.
    Die Tabelle steht immer im HTML (geht ohne JavaScript); der Rechner (nur bei Preisen pro m²) ist
    'hidden' und wird von assets/site.js eingeschaltet."""
    p = ctx.preise
    rows = p["seiten"].get(slug) if p else None
    if not rows:
        return None
    if not all(p[k] for k in PREIS_TEXTE) and not ctx.preview:
        return None  # nie mit Platzhalter live

    def text(k):
        return esc(p[k]) if p[k] else '<span class="ph">bitte eintragen – bestätigt Talal</span>'

    trs = []
    for r in rows:
        main, sub = preis_text(r)
        sub = f"<span>{esc(sub)}</span>" if sub else ""
        trs.append(f'<tr><th scope="row">{esc(r["name"])}</th><td><b>{esc(main)}</b>{sub}</td></tr>')
    rechner = ""
    if any(r["einheit"] == "m2" for r in rows):
        data = json.dumps([{k: r[k] for k in ("name", "einheit", "flaeche", "ab", "bis", "mindestens")} for r in rows],
                          ensure_ascii=False, separators=(",", ":"))
        sel, out_for = "", "rp-flaeche"
        if len(rows) > 1:
            opts = "".join(f'<option value="{i}">{esc(r["name"])}</option>' for i, r in enumerate(rows))
            sel = f'\n      <label for="rp-pos">Was soll gemacht werden?<select id="rp-pos">{opts}</select></label>'
            out_for = "rp-pos rp-flaeche"
        fl = next(r["flaeche"] for r in rows if r["einheit"] == "m2") or "Fläche"
        rechner = f'''
    <div class="rechner" role="group" aria-labelledby="rp-h" data-rechner="{esc(data)}" hidden>
      <p class="label" id="rp-h">Richtpreis berechnen</p>{sel}
      <label for="rp-flaeche" class="rp-flaeche"><span>{esc(fl)} in m²</span><input id="rp-flaeche" type="text" inputmode="decimal" autocomplete="off" placeholder="z. B. 80"></label>
      <output id="rp-out" for="{out_for}" aria-live="polite"></output>
    </div>'''
    tbody = "\n        ".join(trs)
    return f'''<section id="richtpreis" class="sec-alt"><div class="wrap">
  <div class="head reveal">
    <p class="label">Kosten</p>
    <h2>Richtpreise für {esc(name)}</h2>
    <p>Richtpreis – den verbindlichen Festpreis gibt es nach der kostenlosen Besichtigung.</p>
  </div>
  <div class="preis">
    <table class="preise">
      <thead><tr><th scope="col">Leistung</th><th scope="col">Richtpreis</th></tr></thead>
      <tbody>
        {tbody}
      </tbody>
    </table>{rechner}
    <div class="preis-info">
      <p><strong>Im Richtpreis enthalten:</strong> {text("inklusive")}</p>
      <p><strong>Nicht enthalten:</strong> {text("zuzueglich")}</p>
      <p>Den Festpreis nennen wir nach der kostenlosen Besichtigung vor Ort oder per Video. Er hängt davon ab, was wir sehen, z. B. Zugang, Material und Menge. Alle Preise und Rechenbeispiele: <a href="abriss-kosten-hamburg.html">Was kostet ein Abriss in Hamburg?</a></p>
      <a class="btn" href="#anfrage" data-rp-cta>Festpreis anfragen {ARR}</a>
    </div>
  </div>
</div></section>'''


# ---------------------------------------------------------------------------
# Seiten
# ---------------------------------------------------------------------------
ICON_LINKS = ['<link rel="icon" href="favicon.ico" sizes="48x48">',
              '<link rel="icon" href="favicon.svg" type="image/svg+xml">',
              '<link rel="apple-touch-icon" href="apple-touch-icon.png">']
ICON_FILES = ("favicon.svg", "favicon.ico", "apple-touch-icon.png", "logo.png")


def meta_suffix(site):
    """Häkchen-Zeile für die Google-Beschreibung der Leistungs- und Ortsseiten (Telefon aus site.json)."""
    return f" ✓ Kostenlose Besichtigung ✓ Festpreis ☎ {site.firma['telefon']}"


def page_head(ctx, *, title, description, canonical=None, og=None, ld=(), noindex=False):
    s = ctx.site
    out = ['<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
           f"<title>{esc(title)}</title>"]
    if description:
        out.append(f'<meta name="description" content="{esc(description)}">')
    if noindex:
        out.append('<meta name="robots" content="noindex">')
    if canonical:
        out.append(f'<link rel="canonical" href="{esc(canonical)}">')
    if og:
        for k, v in og:
            out.append(f'<meta property="og:{k}" content="{esc(v)}">')
    out.append('<meta name="theme-color" content="#e2571c">')
    out += ICON_LINKS
    out += head_assets(ctx, extra_noindex=not noindex)
    out += [jsonld(x) for x in ld]
    return "\n".join(out)


def render_content_page(ctx, c):
    s, f = ctx.site, ctx.site.firma
    slug, kind = c["slug"], c["type"]
    entry = s.entry[slug]
    url = s.url(slug)
    firma_ref = ld_firma(s)
    data_page = c["menu"].strip()
    if kind in ORTSTYPEN and "abriss" not in data_page.lower():
        data_page = "Abriss " + data_page
    bezirk = s.bezirk_of(entry) if kind == "stadtteil" else None
    lo_le = s.entry[entry["leistung"]] if kind == LEISTUNG_ORT else None  # Leistung und Bezirk der Seite
    lo_bz = s.entry[entry["bezirk"]] if kind == LEISTUNG_ORT else None

    # Brotkrumen: (Name, Link auf der Seite, URL im JSON-LD)
    trail = [("Startseite", ctx.home, s.base)]
    if kind == "leistung":
        trail.append(("Leistungen", ctx.home_link("leistungen", False), s.base + "#leistungen"))
    elif kind == LEISTUNG_ORT:  # Startseite › Leistungen › Entrümpelung › Altona
        trail.append(("Leistungen", ctx.home_link("leistungen", False), s.base + "#leistungen"))
        ok = ctx.has(lo_le["slug"])
        trail.append((lo_le["name"], lo_le["slug"] + ".html" if ok else None, s.url(lo_le["slug"]) if ok else None))
    elif kind == "ratgeber" and slug != ABOUT:
        trail.append(("Ratgeber", ctx.home_link("fragen", False), s.base + "#fragen"))
    elif slug == ABOUT:
        pass  # Startseite › Über uns
    else:
        trail.append(("Einsatzgebiet", UEBERSICHT + ".html", s.url(UEBERSICHT)))
    if bezirk:
        ok = ctx.has(bezirk["slug"])
        trail.append((bezirk["name"], bezirk["slug"] + ".html" if ok else None, s.url(bezirk["slug"]) if ok else None))

    # letzter Eintrag heißt wie in der sichtbaren Brotkrumen-Leiste
    ld = [breadcrumb_ld([(n, u) for n, _, u in trail] + [(entry["name"], url)])]
    service = {"@context": "https://schema.org", "@type": "Service", "@id": url + "#leistung", "name": c["h1"],
               "serviceType": "Abriss und Rückbau", "description": c["description"], "provider": firma_ref}
    if kind == "leistung":  # Name wie im Leistungskatalog der Startseite (gleiche @id)
        ld.append(dict(service, name=entry["name"], serviceType=c["menu"],
                       areaServed={"@type": "City", "name": "Hamburg"}, url=url))
    elif kind == "bezirk":
        ld.append(dict(service, areaServed={"@type": "AdministrativeArea", "name": entry["gebiet"]}, url=url))
    elif kind == LEISTUNG_ORT:
        ld.append(dict(service, serviceType=lo_le["name"],
                       areaServed={"@type": "AdministrativeArea", "name": lo_bz["gebiet"]}, url=url))
    elif kind == "stadtteil":
        ld.append(dict(service, areaServed={"@type": "Place", "name": "Hamburg-" + entry["name"],
                                            "containedInPlace": {"@type": "AdministrativeArea", "name": bezirk["gebiet"]}},
                       url=url))
    elif kind == "umland":
        ld.append(dict(service, areaServed={"@type": "City", "name": entry["name"],
                                            "containedInPlace": {"@type": "AdministrativeArea", "name": entry["kreis"]}},
                       url=url))
    elif slug == ABOUT:
        ld.append({"@context": "https://schema.org", "@type": "AboutPage", "name": c["h1"], "url": url,
                   "description": c["description"], "about": firma_ref, "mainEntity": firma_ref, "inLanguage": "de-DE"})
    else:
        erst, zuletzt = git_daten(ROOT / ctx.content_rel / f"{slug}.json")
        ld.append({"@context": "https://schema.org", "@type": "Article", "headline": c["h1"],
                   "description": c["description"], "datePublished": erst, "dateModified": zuletzt,
                   "author": firma_ref, "publisher": firma_ref, "mainEntityOfPage": url,
                   "image": s.bild_url(c["image"]), "inLanguage": "de-DE"})
    faq = [(x["q"], ctx.drop_dead_links(inline_html(x["a"]))) for x in c["faq"]]  # (Frage, fertiges HTML)
    if faq:
        ld.append(faq_jsonld(s, [(x["q"], ctx.drop_dead_links(x["a"])) for x in c["faq"]]))

    og = [("type", "article" if kind == "ratgeber" else "website"), ("locale", "de_DE"),
          ("site_name", f["name"]), ("title", c["title"]), ("description", c["description"]),
          ("image", s.bild_url(c["image"])), ("url", url)]
    meta = c["description"] if kind == "ratgeber" else c["description"] + meta_suffix(s)
    head = page_head(ctx, title=c["title"], description=meta, canonical=url, og=og, ld=ld)

    # Inhalt
    secs = []
    for sec in c["sections"]:
        secs.append(f'<section>\n      <h2>{esc(sec["h2"])}</h2>\n      {ctx.content_html(sec["html"].strip())}\n    </section>')
    if kind == "bezirk":
        chips = []
        for x in c["stadtteile"]:
            st = stadtteil_page(ctx, slug, x)
            chips.append(f'<a class="chip-page" href="{esc(st["slug"])}.html">{esc(x)}</a>' if st else f"<span>{esc(x)}</span>")
        secs.append(f'<section>\n      <h2>Stadtteile im Bezirk {esc(entry["name"])}</h2>\n      <div class="chips">{"".join(chips)}</div>\n    </section>')
    if kind == "bezirk" and ctx.lo_pages(bezirk=slug):
        chips = "".join(f'<a class="chip-page" href="{esc(x["slug"])}.html">{esc(s.entry[x["leistung"]]["name"])}</a>'
                        for x in ctx.lo_pages(bezirk=slug))
        secs.append(f'<section>\n      <h2>Weitere Leistungen in {esc(entry["name"])}</h2>\n      <div class="chips">{chips}</div>\n    </section>')
    if kind == "umland" and c.get("stadtteile"):
        chips = "".join(f"<span>{esc(x)}</span>" for x in c["stadtteile"])
        secs.append(f'<section>\n      <h2>Ortsteile von {esc(entry["name"])}</h2>\n      <div class="chips">{chips}</div>\n    </section>')
    if kind == "leistung" and ctx.lo_pages(leistung=slug):  # eigene Seiten je Bezirk statt der Abriss-Bezirksseiten
        chips = "".join(f'<a href="{esc(x["slug"])}.html">{esc(x["name"])}</a>' for x in ctx.lo_pages(leistung=slug))
        secs.append(f'<section>\n      <h2>{esc(entry["name"])} in Ihrem Bezirk</h2>\n      <div class="chips">{chips}</div>\n    </section>')
    elif kind == "leistung" and ctx.pages(s.bezirke):
        secs.append(f'<section>\n      <h2>In diesen Bezirken sind wir im Einsatz</h2>\n      <div class="chips">{chip_links(ctx.pages(s.bezirke))}</div>\n    </section>')
    if kind == "ratgeber" and c.get("sources"):
        items = []
        for src in c["sources"]:
            host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", src["url"]))
            items.append(f'<li><a href="{esc(src["url"])}" rel="noopener">{esc(src["title"])}</a><span class="host">{esc(host)}</span></li>')
        secs.append('<section>\n      <h2>Quellen</h2>\n      <ol class="sources">' + "".join(items) + '</ol>\n'
                    '      <p class="note">Diese Übersicht ersetzt keine Rechtsberatung. Im Zweifel fragen Sie bei der zuständigen Stelle nach, etwa '
                    + esc(c.get("note_stellen", "beim Bezirksamt oder bei der Stadtreinigung")) + '.</p>\n    </section>')

    side = f'''<aside class="side" aria-labelledby="side-h">
    <p class="label">Kostenlos &amp; unverbindlich</p>
    <h2 id="side-h">Besichtigung anfragen</h2>
    <div class="lines">
      <div><span class="label">Telefon</span><strong><a href="tel:{esc(f["telefon_link"])}">{esc(f["telefon"])}</a></strong></div>
      <div><span class="label">E-Mail</span><strong><a href="mailto:{esc(f["email"])}">{esc(f["email"])}</a></strong></div>
      <div class="next"><span class="label">Nächster Termin</span><strong data-slot>Mo–Fr ab 16:30, Sa ab 9:00</strong></div>
    </div>
    <a class="btn" href="#anfrage">Zum Anfrageformular {ARR}</a>
  </aside>'''

    after = []
    cards_shown = False
    leist = ctx.pages(s.leistungen)
    if kind in ORTSTYPEN and leist:
        # nur die Kernleistungen als Karten (kurzer Rahmen), alle übrigen über „Alle … Leistungen“ auf der Startseite
        cards_shown = True
        kern = kern_leistungen(ctx)
        cards = "\n    ".join(mini_card(ctx, x) for x in kern)
        n3 = " n3" if len(kern) % 3 == 0 and len(kern) % 4 else ""
        alle = (f'\n  <p class="go-wrap"><a class="go-all" href="{esc(ctx.home_link("leistungen", False))}">Alle {len(leist)} '
                f'Leistungen ansehen <span aria-hidden="true">→</span></a></p>' if len(kern) < len(leist) else "")
        after.append(f'''<section class="sec-alt"><div class="wrap">
  <div class="head reveal">
    <p class="label">Leistungen</p>
    <h2>Unsere Leistungen in {esc(entry["name"])}</h2>
  </div>
  <div class="minis{n3}">
    {cards}
  </div>{alle}
</div></section>''')
    if faq:
        qa = "\n    ".join(f'<details><summary>{esc(q)}</summary><p>{ctx.fix_home_links(a)}</p></details>' for q, a in faq)
        tight = "" if cards_shown else ' class="sec-tight"'
        after.append(f'''<section id="fragen"{tight}><div class="wrap">
  <div class="head reveal">
    <p class="label">Häufige Fragen</p>
    <h2>Fragen und Antworten</h2>
  </div>
  <div class="faq reveal">
    {qa}
  </div>
</div></section>''')
    if c.get("galerie"):
        figs = []
        for g in c["galerie"]:
            b = s.bilder[g["bild"]]
            img = picture_html(s.bild_src(g["bild"]), {"width": b["w"], "height": b["h"], "alt": b["alt"], "loading": "lazy"})
            figs.append(f'<figure class="reveal">{img}<figcaption>{esc(g["text"])}</figcaption></figure>')
        after.append(f'''<section class="sec-tight"><div class="wrap">
  <div class="head reveal">
    <p class="label">Aus unserer Arbeit</p>
    <h2>So sieht es bei uns aus</h2>
  </div>
  <div class="galerie">
    {"\n    ".join(figs)}
  </div>
</div></section>''')
    preise = preis_section(ctx, slug, entry["name"]) if kind == "leistung" else None
    if preise:
        after.append(preise)
    after.append(contact_section(ctx, c["form_leistung"], c["form_ort"], data_page))

    def nav_section(label, h2, chips, extra=""):
        return f'''<section><div class="wrap">
  <div class="head reveal">
    <p class="label">{esc(label)}</p>
    <h2>{esc(h2)}</h2>
  </div>
  <div class="chips">{chips}</div>{extra}
</div></section>'''

    if kind == "leistung":
        others = [x for x in leist if x["slug"] != slug]
        if others:
            cards = "\n    ".join(mini_card(ctx, x) for x in others)
            n3 = " n3" if len(others) == 3 else ""
            after.append(f'''<section><div class="wrap">
  <div class="head reveal">
    <p class="label">Alles aus einer Hand</p>
    <h2>Weitere Leistungen</h2>
  </div>
  <div class="minis{n3}">
    {cards}
  </div>
</div></section>''')
    if kind == "bezirk":
        others = [x for x in ctx.pages(s.bezirke) if x["slug"] != slug]
        if others:
            after.append(nav_section("Einsatzgebiet", "Weitere Bezirke", chip_links(others)))
    if kind == "stadtteil":
        others = [x for x in ctx.pages(s.stadtteile) if x["bezirk"] == bezirk["slug"] and x["slug"] != slug]
        chips = chip_links(others)
        if ctx.has(bezirk["slug"]):
            chips += f'<a class="chip-all" href="{esc(bezirk["slug"])}.html">Ganzer Bezirk {esc(bezirk["name"])}</a>'
        if chips:
            after.append(nav_section("Einsatzgebiet", f"Weitere Stadtteile im Bezirk {bezirk['name']}", chips))
    if kind == LEISTUNG_ORT:
        # Andere Bezirke derselben Leistung und weitere Leistungen im Bezirk; gibt es dazu (noch) keine Seiten,
        # stehen die Links auf Leistung und Bezirk zusammen in einem Abschnitt „Mehr zu …“.
        rest = []
        le_all = (f'<a class="chip-all" href="{esc(lo_le["slug"])}.html">{esc(lo_le["name"])} in ganz Hamburg</a>'
                  if ctx.has(lo_le["slug"]) else "")
        bz_all = (f'<a class="chip-all" href="{esc(lo_bz["slug"])}.html">Abriss in {esc(lo_bz["gebiet"])}</a>'
                  if ctx.has(lo_bz["slug"]) else "")
        others = [x for x in ctx.lo_pages(leistung=lo_le["slug"]) if x["slug"] != slug]
        if others:
            after.append(nav_section("Einsatzgebiet", f"{lo_le['name']} in weiteren Bezirken", chip_links(others) + le_all))
        elif le_all:
            rest.append(le_all)
        others = [x for x in ctx.lo_pages(bezirk=lo_bz["slug"]) if x["slug"] != slug]
        if others:
            chips = "".join(f'<a href="{esc(x["slug"])}.html">{esc(s.entry[x["leistung"]]["name"])}</a>' for x in others)
            after.append(nav_section(f"Bezirk {lo_bz['name']}", f"Weitere Leistungen in {lo_bz['name']}", chips + bz_all))
        elif bz_all:
            rest.append(bz_all)
        if rest:
            h2 = (f"Mehr zu {lo_le['name']} und {lo_bz['name']}" if len(rest) == 2
                  else f"Mehr zu {lo_le['name']}" if rest[0] == le_all else f"Mehr zum Bezirk {lo_bz['name']}")
            after.append(nav_section("Weiterlesen", h2, "".join(rest)))
    if kind == "umland":
        alle = (f'\n  <p class="go-wrap"><a class="go-all" href="{UEBERSICHT}.html">Alle Orte im Einsatzgebiet '
                f'<span aria-hidden="true">→</span></a></p>')
        others = weitere_orte(ctx, entry)
        if others:
            im_kreis = all(u["kreis"] == entry["kreis"] for u in others) and re.match(r"(Land)?[Kk]reis ", entry["kreis"])
            h2 = f"Weitere Orte im {entry['kreis']}" if im_kreis else "Weitere Orte im Umland"
            after.append(nav_section("Einsatzgebiet", h2, chip_links(others), alle))
        else:
            after.append(f'<section><div class="wrap">{alle}\n</div></section>')

    crumbs = crumbs_html([(n, h) for n, h, _ in trail] + [(entry["name"], None)])
    hero = subhero(ctx, c["image"], c["label"], c["h1"], c["lead"], c["facts"])
    body = "\n\n".join([
        render_header(ctx, slug, False, "#anfrage"),
        '<main id="start">\n' + crumbs + "\n" + hero + '\n\n<div class="wrap page">\n  <div class="prose">\n    '
        + "\n    ".join(secs) + "\n  </div>\n  " + side + "\n</div>\n\n" + "\n\n".join(after) + "\n</main>",
        render_footer(ctx, slug, False, "#anfrage"),
    ])
    return doc(head, body, f"{ctx.content_rel}/{slug}.json")


def render_einsatzgebiet(ctx):
    """Übersicht aller Orte: Bezirke mit ihren Stadtteil-Seiten, Umland nach Kreis."""
    s, f, e = ctx.site, ctx.site.firma, ctx.site.uebersicht
    url = s.url(UEBERSICHT)
    ld = [breadcrumb_ld([("Startseite", s.base), ("Einsatzgebiet", url)])]
    og = [("type", "website"), ("locale", "de_DE"), ("site_name", f["name"]), ("title", e["title"]),
          ("description", e["description"]), ("image", s.bild_url("abriss")), ("url", url)]
    head = page_head(ctx, title=e["title"], description=e["description"] + meta_suffix(s), canonical=url, og=og, ld=ld)

    def row(title_html, chips, sub=""):
        sub = f'<p class="label">{esc(sub)}</p>' if sub else ""
        chips = f'\n      <div class="chips">{chips}</div>' if chips else ""
        return f'<li>\n      <div class="ort-h"><h3>{title_html}</h3>{sub}</div>{chips}\n    </li>'

    def area(sid, label, h2, rows, cls="", extra=""):
        rows = "\n    ".join(rows)
        return f'''<section id="{sid}"{cls}><div class="wrap">
  <div class="head reveal">
    <p class="label">{esc(label)}</p>
    <h2>{esc(h2)}</h2>
  </div>
  <ul class="orte reveal">
    {rows}
  </ul>{extra}
</div></section>'''

    bez_rows = []
    for b in s.bezirke:
        st = ctx.pages([x for x in s.stadtteile if x["bezirk"] == b["slug"]])
        if ctx.has(b["slug"]):
            title = f'<a href="{esc(b["slug"])}.html">{esc(b["name"])} <span aria-hidden="true">→</span></a>'
        else:
            title = esc(b["name"])
        bez_rows.append(row(title, chip_links(st)))

    kreise = {}
    for u in ctx.pages(s.umland):
        kreise.setdefault((u["kreis"], u["land"]), []).append(u)
    uml_rows = [row(esc(k), chip_links(orte), land) for (k, land), orte in kreise.items()]
    laender = " · ".join(dict.fromkeys(land for _, land in kreise))

    q, sep, rest = e["hinweis"].partition("? ")
    text = f"<strong>{esc(q)}?</strong> {esc(rest)}" if sep else esc(e["hinweis"])
    hinweis = f'''
  <div class="note hinweis reveal">
    <p>{text}</p>
    <a class="btn" href="#anfrage">Zum Anfrageformular {ARR}</a>
  </div>'''

    sections = []
    if uml_rows:
        sections.append(area("bezirke", "Hamburg", "Hamburger Bezirke", bez_rows))
        sections.append(area("umland", laender, "Umland", uml_rows, ' class="sec-alt"', hinweis))
    else:
        sections.append(area("bezirke", "Hamburg", "Hamburger Bezirke", bez_rows, "", hinweis))
    sections.append(contact_section(ctx, "Weiß ich noch nicht", "", "Einsatzgebiet"))

    crumbs = crumbs_html([("Startseite", ctx.home), ("Einsatzgebiet", None)])
    hero = subhero(ctx, "abriss", e["label"], e["h1"], e["lead"])
    body = "\n\n".join([
        render_header(ctx, UEBERSICHT, False, "#anfrage"),
        '<main id="start">\n' + crumbs + "\n" + hero + "\n\n" + "\n\n".join(sections) + "\n</main>",
        render_footer(ctx, UEBERSICHT, False, "#anfrage"),
    ])
    return doc(head, body, "src/site.json")


def render_legal(ctx, entry, fragment):
    s = ctx.site
    head = page_head(ctx, title=entry["title"], description=None, noindex=True)
    body = "\n\n".join([
        render_header(ctx, entry["slug"], False, ctx.home_link("anfrage", False)),
        f'<main id="start" class="wrap legal"><div>\n{ctx.fix_home_links(fragment.strip())}\n</div></main>',
        render_footer(ctx, entry["slug"], False, ctx.home_link("anfrage", False)),
    ])
    return doc(head, body, f"src/legal/{entry['slug']}.html")


def render_llms(ctx):
    """llms.txt: kurzer Steckbrief der Firma für KI-Suchen (ChatGPT, Perplexity, Google-KI …).
    Alles aus site.json und preise.json, damit nichts von der Website abweicht."""
    s, f = ctx.site, ctx.site.firma
    q = [f"„{n}“" for n in [f["name"]] + f.get("auch_genannt", [])]  # Name und Kurznamen aus site.json
    namen = q[0] if len(q) == 1 else ", ".join(q[:-1]) + " oder " + q[-1]
    ln = [x["name"] for x in ctx.pages(s.leistungen)]  # Leistungen aus site.json (nur Seiten mit Inhalt)
    leist = ln[0] if len(ln) == 1 else ", ".join(ln[:-1]) + " sowie " + ln[-1] if ln else "Abriss und Rückbau"
    L = [f"# {f['name']}", "",
         f"> {f['name']} ist ein Abrissbetrieb aus Hamburg-Altona ({f['strasse']}, {f['plz']} {f['ort']}), "
         f"Inhaber {f['inhaber']}. Unsere Leistungen für Privatkunden, Vermieter und Hausverwaltungen in ganz Hamburg "
         f"und im Umland: {leist}.", "",
         "Wichtig zur Einordnung: Gemeint ist dieses Unternehmen, wenn jemand nach " + namen + " sucht.", "",
         "## Kontakt", "",
         f"- Telefon und WhatsApp: {f['telefon']} ({f['telefon_schema']})",
         f"- E-Mail: {f['email']}",
         f"- Adresse: {f['strasse']}, {f['plz']} {f['ort']} (Altona)",
         "- Erreichbar: Montag bis Samstag, 8 bis 20 Uhr",
         f"- Website: {s.base}", "",
         "## So arbeiten wir", "",
         "- Kostenlose und unverbindliche Besichtigung, vor Ort oder per Video",
         "- Rückmeldung innerhalb eines Werktags",
         "- Festpreis nach der Besichtigung, Abtransport und Entsorgung inklusive",
         "- Termine auch abends und samstags",
         "- Asbest entfernt immer ein dafür zugelassener Fachbetrieb, tragende Wände nur mit Statiker", "",
         "## Leistungen", ""]
    for x in ctx.pages(s.leistungen):
        L.append(f"- [{x['name']}]({s.url(x['slug'])}): {x['kurz']}")
        lo = ctx.lo_pages(leistung=x["slug"])
        if lo:
            L.append(f"  - {x['name']} auch in: " + ", ".join(f"[{y['name']}]({s.url(y['slug'])})" for y in lo))
    p = ctx.preise
    if p and p["seiten"] and all(p[k] for k in PREIS_TEXTE):
        L += ["", "## Ab-Preise (Privatkunden, inkl. Umsatzsteuer)", ""]
        for slug, rows in p["seiten"].items():
            for r in rows:
                main, sub = preis_text(r)
                L.append(f"- {r['name']}: {main}" + (f" ({sub})" if sub else ""))
        L += ["", f"Enthalten: {p['inklusive']}. Nicht enthalten: {p['zuzueglich']}. "
              "Den verbindlichen Festpreis gibt es nach der kostenlosen Besichtigung."]
    L += ["", "## Einsatzgebiet", "",
          "Alle sieben Hamburger Bezirke: " + ", ".join(b["name"] for b in s.bezirke) + ". "
          f"Dazu {len(ctx.pages(s.umland))} Orte im Umland, etwa " + ", ".join(u["name"] for u in ctx.pages(s.umland)[:8]) + ".", "",
          f"- [Alle Orte im Einsatzgebiet]({s.url(UEBERSICHT)})", "", "## Mehr lesen", ""]
    if ctx.has(ABOUT):
        L.append(f"- [Über uns]({s.url(ABOUT)})")
    for x in ctx.pages(s.ratgeber):
        if x["slug"] != ABOUT:
            L.append(f"- [{x['name']}]({s.url(x['slug'])})")
    L += [f"- [Impressum]({s.url('impressum')})", ""]
    return "\n".join(L)


def render_404(ctx):
    """Fehlerseite für GitHub Pages."""
    s = ctx.site
    head = page_head(ctx, title="Seite nicht gefunden | " + s.firma["name"], description=None, noindex=True)
    links = "\n".join(f'      <li><a href="{esc(x["slug"])}.html">{esc(x["name"])}</a></li>' for x in ctx.pages(s.leistungen))
    body = "\n\n".join([
        render_header(ctx, "404", False, ctx.home_link("anfrage", False)),
        f'''<main id="start" class="wrap legal"><div>
<h1>Diese Seite gibt es nicht</h1>
<p>Vielleicht hat sich die Adresse geändert oder es war ein Tippfehler. Hier geht es weiter:</p>
<ul>
      <li><a href="{ctx.home_link("start", False)}">Zur Startseite</a></li>
{links}
      <li><a href="{UEBERSICHT}.html">Alle Stadtteile und Orte im Einsatzgebiet</a></li>
      <li><a href="{ctx.home_link("anfrage", False)}">Kostenlose Besichtigung anfragen</a></li>
</ul>
</div></main>''',
        render_footer(ctx, "404", False, ctx.home_link("anfrage", False)),
    ])
    out = doc(head, body, "src/build.py (render_404)")
    if not ctx.preview:  # GitHub zeigt die Seite unter jeder falschen Adresse, auch /a/b/c – daher Pfade ab Wurzel
        out = re.sub(r'(\s(?:href|src)=")(?!https?:|mailto:|tel:|#|/|data:)', r"\1/", out)
        out = out.replace('="/./', '="/')
    return out


def doc(head, body, source):
    return (f'<!doctype html>\n<!-- Erzeugt von src/build.py aus {source} – Änderungen bitte dort vornehmen -->\n'
            f'<html lang="de">\n<head>\n{head}\n</head>\n<body>\n\n{body}\n\n</body>\n</html>\n')


def fill_marker(src, name, content):
    pat = re.compile(r"<!-- @%s -->.*?<!-- /@%s -->" % (name, name), re.S)
    if len(pat.findall(src)) != 1:
        raise BuildError(f"index.html: Marker <!-- @{name} --> … <!-- /@{name} --> fehlt oder ist doppelt")
    return pat.sub(lambda m: f"<!-- @{name} -->\n{content.rstrip()}\n<!-- /@{name} -->", src)


def home_faq_pairs(src):
    m = re.search(r'<section id="fragen".*?</section>', src, re.S)
    if not m:
        raise BuildError('index.html: Abschnitt id="fragen" nicht gefunden')
    pairs = []
    for q, a in re.findall(r"<details><summary>(.*?)</summary>\s*<p>(.*?)</p>\s*</details>", m.group(0), re.S):
        pairs.append((html.unescape(q.strip()), html.unescape(a.strip())))
    if not pairs:
        raise BuildError("index.html: keine Fragen im Abschnitt #fragen gefunden")
    shown = m.group(0).count("<details")
    if shown != len(pairs):  # sonst stünde eine sichtbare Frage nicht im FAQ-JSON-LD
        raise BuildError(f"index.html: {shown} Fragen in #fragen, aber nur {len(pairs)} in der Form "
                         "<details><summary>Frage</summary><p>Antwort</p></details>")
    return pairs


def home_zahlen(ctx):
    """Zähler-Streifen der Startseite: Bezirke und Umland-Orte, gezählt aus src/site.json (Umland nur mit Seite)."""
    s = ctx.site
    b = s.bezirke
    out = [f'  <li><a href="#gebiet"><b>{len(b)}</b> <span class="u">Bezirke</span> '
           f'<span class="t">in Hamburg, von {esc(b[0]["name"])} bis {esc(b[-1]["name"])}</span></a></li>']
    n = len(ctx.pages(s.umland))
    if n:
        out.append(f'  <li><a href="{UEBERSICHT}.html#umland"><b>{n}</b> <span class="u">{"Ort" if n == 1 else "Orte"}</span> '
                   f'<span class="t">im Hamburger Umland</span></a></li>')
    return "\n".join(out)


def home_umland(ctx):
    """Satz unter der Bezirkstabelle der Startseite; Orte ohne Seite stehen als reiner Text da."""
    s = ctx.site
    names = [f'<a href="{esc(x)}.html">{esc(s.entry[x]["name"])}</a>' if ctx.has(x) else esc(s.entry[x]["name"])
             for x in s.startseite_umland]
    out = []
    if names:
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " oder " + names[-1]
        out.append(f'    <p class="gebiet-mehr">Auch im Umland, z. B. in {joined}.</p>')
    out.append(f'    <p class="go-wrap"><a class="go-all" href="{UEBERSICHT}.html">Alle Stadtteile und Orte im Einsatzgebiet '
               f'<span aria-hidden="true">→</span></a></p>')
    return "\n".join(out)


def render_index(ctx):
    s, f = ctx.site, ctx.site.firma
    src = ctx.home_src
    # Öffnungszeiten Mo–Sa 8–20 (von Talal am 22.10.2026 für das Google-Profil bestätigt); keine Preisspanne.
    business = {
        "@context": "https://schema.org", "@type": "HomeAndConstructionBusiness", "@id": s.base + "#firma",
        "name": f["name"], "alternateName": f.get("auch_genannt", []), "description": f["beschreibung"], "url": s.base, "image": s.bild_url("abriss"),
        "logo": s.base + "logo.png",
        "telephone": f["telefon_schema"], "email": f["email"],
        "address": ld_adresse(f),
        "founder": {"@type": "Person", "name": f["inhaber"]},
        "knowsAbout": [x["name"] for x in s.leistungen] + ["Rückbau", "Abriss in Hamburg"],
        "openingHoursSpecification": [{"@type": "OpeningHoursSpecification",
                                       "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
                                       "opens": "08:00", "closes": "20:00"}],
        "areaServed": [{"@type": "AdministrativeArea", "name": b["gebiet"]} for b in s.bezirke]
                      + [{"@type": "City", "name": u["name"]} for u in ctx.pages(s.umland)],
    }
    if f.get("profile"):  # belegte Einträge (Google, Branchenbücher), sobald sie online sind
        business["sameAs"] = f["profile"]
    if ctx.has(ABOUT):
        business["subjectOf"] = {"@type": "AboutPage", "url": s.url(ABOUT)}
    geo = f.get("geo")  # nur mit belegten Koordinaten in site.json, z. B. "geo": {"breite": 53.12345, "laenge": 9.12345}
    if geo:
        if not all(isinstance(geo.get(k), (int, float)) for k in ("breite", "laenge")):
            raise BuildError("site.json: firma.geo braucht 'breite' und 'laenge' als Zahlen")
        business["geo"] = {"@type": "GeoCoordinates", "latitude": geo["breite"], "longitude": geo["laenge"]}
    leist = ctx.pages(s.leistungen)
    if leist:
        business["hasOfferCatalog"] = {"@type": "OfferCatalog", "name": "Leistungen", "itemListElement": [
            {"@type": "Offer", "itemOffered": {"@type": "Service", "@id": s.url(x["slug"]) + "#leistung",
                                               "name": x["name"], "url": s.url(x["slug"])}} for x in leist]}
    head = head_assets(ctx, extra_noindex=True) + [jsonld(business), jsonld(faq_jsonld(s, home_faq_pairs(src)))]
    out = fill_marker(src, "head", "\n".join(head))
    out = fill_marker(out, "header", render_header(ctx, "index", True, "#anfrage"))
    out = fill_marker(out, "umland", home_umland(ctx))
    out = fill_marker(out, "zahlen", home_zahlen(ctx))
    out = fill_marker(out, "footer", render_footer(ctx, "index", True, "#anfrage"))
    return out


def home_ids(src):
    return set(re.findall(r'\sid="([^"]+)"', src))


def check_home_links(ctx, linker, errors):
    """Von Hand gepflegte Links der Startseite prüfen (ohne die erzeugten Bereiche)."""
    src = re.sub(r"<!-- @(\w+) -->.*?<!-- /@\1 -->", "", ctx.home_src, flags=re.S)
    for href in re.findall(r'<a\s[^>]*?href="([^"]+)"', src):
        if href.startswith("#"):
            continue
        msg = linker.check(href, "index.html")
        if msg:
            errors.append(f"index.html: {msg}")


def check_home_images(ctx, errors):
    """Von Hand eingetragene Bilder der Startseite (<img src>, og:image) müssen in img/ liegen."""
    src = re.sub(r"<!-- @(\w+) -->.*?<!-- /@\1 -->", "", ctx.home_src, flags=re.S)
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)  # Beispiele in Kommentaren nicht prüfen
    refs = re.findall(r'<img\s[^>]*?src="([^"]+)"', src) + re.findall(r'<meta property="og:image" content="([^"]+)"', src)
    for ref in refs:
        rel = ref[len(ctx.site.base):] if ref.startswith(ctx.site.base) else ref
        if not re.match(r"[a-z]+:", rel) and not (ROOT / rel).is_file():
            errors.append(f"index.html: Bild {ref} fehlt")


def check_stadtteil_chips(site, contents, warn):
    """Jede Stadtteil-Seite sollte in der Stadtteil-Liste ihres Bezirks vorkommen (dort wird sie verlinkt)."""
    for st in site.stadtteile:
        bez = contents.get(st["bezirk"])
        if st["slug"] not in contents or not bez:
            continue
        if not any(x == st["name"] or x.startswith(st["name"] + "-") for x in bez["stadtteile"]):
            warn(f"{st['bezirk']}.json: Stadtteil '{st['name']}' fehlt in 'stadtteile' – dort nicht verlinkt")


def check_nap(site, home_src, contents, warn):
    """NAP (Name, Adresse, Telefon): überall genau die Schreibweise aus src/site.json.
    Von Hand gepflegte Kopien (index.html: Beschreibung und Kontaktbereich, der auf jede Seite kommt;
    src/legal/*.html; assets/site.js) und die Inhaltstexte werden gegen site.json geprüft,
    damit z. B. eine neue Telefonnummer nicht nur an einem Teil der Stellen ankommt."""
    f = site.firma
    hand = {"index.html": re.sub(r"<!-- @(\w+) -->.*?<!-- /@\1 -->|<title>.*?</title>", "", home_src, flags=re.S)}
    for p in sorted((SRC / "legal").glob("*.html")):
        hand[f"src/legal/{p.name}"] = p.read_text(encoding="utf-8")
    js = ROOT / "assets" / "site.js"
    texts = dict(hand, **({"assets/site.js": js.read_text(encoding="utf-8")} if js.exists() else {}))
    for slug, c in contents.items():  # sichtbare Texte ohne title (Kurzform „| T&A“ im Titel ist gewollt)
        parts = [c[k] for k in ("label", "h1", "lead", "description") if is_str(c.get(k))] + list(c["facts"])
        parts += [s["h2"] + " " + s["html"] for s in c["sections"]] + [x["q"] + " " + x["a"] for x in c["faq"]]
        texts[f"{slug}.json"] = "\n".join(parts)
    nsn = f["telefon_link"].removeprefix("+49")
    own_tel = re.compile(r"(?<![\w+])(?:\+49|0049|0)(?:\s*\(0\))?[\s/().-]{0,3}"
                         + r"[\s/().-]{0,3}".join(nsn) + r"(?!\d)")
    mobile = re.compile(r"(?<![\w+])(?:\+49|0049|0)(?:\s*\(0\))?[\s/().-]{0,3}1[5-7]\d(?:[\s/().-]{0,3}\d){6,9}(?!\d)")
    tel_ok = {f["telefon"], f["telefon_link"], f["telefon_schema"]}
    street = re.sub(r"\s*\d+\s*[a-zA-Z]?$", "", f["strasse"])
    stem = re.sub(r"(?i)[\s-]*(straße|strasse|str\.?)$", "", street)
    street_re = re.compile(re.escape(stem) + r"[\s-]*(?:straße|strasse|str\b\.?)(?:\s*\d+\s*[a-zA-Z]?\b)?", re.I)
    plz_re = re.compile(r"\b" + re.escape(f["plz"]) + r"\b(?!\s+" + re.escape(f["ort"]) + r"(?![\w-]))(?:\s+[^\s<,.;]+)?")
    domain = f["email"].partition("@")[2]
    for where, raw in texts.items():
        t = html.unescape(raw)
        bad = {m.group(0) for m in own_tel.finditer(t) if m.group(0) not in tel_ok}
        bad |= {m.group(0) for m in mobile.finditer(t) if re.sub(r"\D", "", m.group(0)).lstrip("0").removeprefix("49").lstrip("0") != nsn}
        bad |= {m.group(0).strip() for m in street_re.finditer(t) if m.group(0).strip() not in (f["strasse"], street)}
        bad |= {m.group(0) for m in plz_re.finditer(t)}
        bad |= {m.group(0) for m in re.finditer(r"[\w.+-]+@" + re.escape(domain), t) if m.group(0) != f["email"]}
        bad |= {m.group(0) for m in re.finditer(r"mailto:([^?\"'\s<>]+)", t) if m.group(1) != f["email"]}
        bad |= {m.group(0) for m in re.finditer(r"\bT\s*[&+]\s*A\s+(?:Abriss|Abbruch|Rückbau)\b(?:\s*[&+]\s*\w+)?", t)
                if m.group(0) != f["name"] and m.group(0) not in f.get("auch_genannt", [])}  # Kurznamen aus site.json erlaubt
        bad |= {m.group(0) for m in re.finditer(r"\bT(?:\s+[&+]\s*|[&+]\s+|\+)A\b", t)}
        for x in sorted(bad):
            warn(f"{where}: Schreibweise '{x}' weicht von src/site.json ab (NAP: Name, Adresse, Telefon, E-Mail)")
    need = {"index.html": ("telefon", "email", "adresse"),
            "src/legal/impressum.html": ("name", "inhaber", "strasse", "plz_ort", "telefon", "email"),
            "src/legal/datenschutz.html": ("name", "inhaber", "adresse", "telefon", "email")}
    werte = dict(f, adresse=f"{f['strasse']}, {f['plz']} {f['ort']}", plz_ort=f"{f['plz']} {f['ort']}")
    for where, keys in need.items():
        if where in hand:
            for k in keys:
                if werte[k] not in html.unescape(hand[where]):
                    warn(f"{where}: {k} '{werte[k]}' aus src/site.json fehlt – Kontaktdaten dort von Hand angleichen")
def check_images(files, warn):
    """Fotos in den fertigen Seiten (auch Handbereiche von index.html): Datei vorhanden, width/height im
    Seitenverhältnis des echten Bildes (sonst springt die Seite beim Laden), jede WebP passt zu ihrem JPG."""
    found = {}
    for name, text in files.items():
        for tag in re.findall(r"<(?:img|source)\s[^>]*>", text if name.endswith(".html") else ""):
            a = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
            src = html.unescape(a.get("src") or a.get("srcset") or "").lstrip("/")
            if not src.startswith("img/"):
                continue
            size = image_size(ROOT / src)
            w, h = a.get("width", ""), a.get("height", "")
            if not (ROOT / src).is_file():
                msg = f"{src} fehlt"
            elif tag.startswith("<source"):
                continue
            elif not (w.isdigit() and h.isdigit() and int(h)):
                msg = f'<img src="{src}"> ohne width/height'
            elif size and abs(int(w) / int(h) - size[0] / size[1]) > 0.01:
                msg = f"{src}: width/height {w}×{h} passt nicht zum Bild ({size[0]}×{size[1]})"
            else:
                continue
            found.setdefault(msg, set()).add(name)
    for msg, pages in found.items():
        pages = sorted(pages)
        warn(f"Bild: {msg} ({', '.join(pages[:3])}{' …' if len(pages) > 3 else ''})")
    for webp in sorted((ROOT / "img").glob("*.webp")):
        jpg = next((p for p in (webp.with_suffix(".jpg"), webp.with_suffix(".jpeg")) if p.is_file()), None)
        if not jpg:
            warn(f"img/{webp.name}: kein gleichnamiges JPG daneben – wird nicht benutzt")
        elif image_size(webp) != image_size(jpg):
            warn(f"img/{webp.name} ist anders groß als {jpg.name} (veraltet?) – wird nicht benutzt, bitte "
                 "python3 src/tools/make_webp.py ausführen")


@functools.lru_cache(maxsize=None)
def git_letzte_aenderungen(*pfade):
    """{Pfad relativ zum Repo: Datum JJJJ-MM-TT der letzten Änderung laut Git} für alle Dateien unter den Pfaden,
    mit einem einzigen git log (statt einem Aufruf je Seite). Dateien mit ungespeicherten Änderungen zählen als
    heute (wie in git_daten). Ohne Git-Historie: leeres dict."""
    heute = datetime.date.today().isoformat()
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True,
                                    timeout=60, check=True).stdout
    try:
        log = git("log", "--format=%x01%aI", "--name-only", "--", *pfade)
        offen = git("status", "--porcelain", "--untracked-files=all", "--", *pfade)
    except (OSError, subprocess.SubprocessError):
        return {}
    daten, datum = {}, None
    for line in log.splitlines():
        if line.startswith("\x01"):
            datum = line[1:11]
        elif line.strip() and datum:
            daten.setdefault(line.strip(), datum)  # git log läuft vom neuesten Commit rückwärts
    for line in offen.splitlines():
        p = line[3:].split(" -> ")[-1].strip().strip('"')
        if p:
            daten[p] = heute
    return daten


def lastmod_daten(ctx, slugs):
    """Echtes Änderungsdatum je Seite für sitemap.xml: letzte Änderung ihrer Quelldatei laut Git
    (Inhalts-JSON; Startseite: index.html; Übersicht: src/site.json; Leistungen mit Richtpreisen: auch
    src/preise.json). Änderungen am gemeinsamen Seitenrahmen zählen nicht – sonst stünde nach jedem Build
    überall „heute“, und Google ignoriert lastmod. Ohne Git-Datum: heute."""
    rel = ctx.content_rel.rstrip("/")
    daten = git_letzte_aenderungen(rel, "src/site.json", "src/preise.json", "index.html")
    heute = ctx.today
    preise = (ctx.preise or {}).get("seiten", {})

    def quelle(slug):
        if slug is None:
            return [daten.get("index.html")]
        if slug == UEBERSICHT:
            return [daten.get("src/site.json")]
        q = [daten.get(f"{rel}/{slug}.json")]
        if slug in preise:
            q.append(daten.get("src/preise.json"))
        return q

    out = {}
    for slug in [None] + list(slugs):
        q = [d for d in quelle(slug) if d]
        out[slug] = max(q) if q else heute
    return out


def sitemap(site, slugs, today, lastmod=None):
    """lastmod: {slug (None = Startseite): Datum}; ohne Eintrag gilt today."""
    lastmod = lastmod or {}
    urls = [(site.base, lastmod.get(None, today))] + [(site.url(x), lastmod.get(x, today)) for x in slugs]
    rows = "\n".join(f"  <url><loc>{esc(u)}</loc><lastmod>{d}</lastmod></url>" for u, d in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + "\n</urlset>\n")


# ---------------------------------------------------------------------------
# Vorlagen-Prüfung: fertige Seiten auf typische Vorlagen- und Kopierfehler prüfen.
# Nur Warnungen, die Ausgabe wird dadurch nicht verändert.
# ---------------------------------------------------------------------------
VP_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
VP_BLOCK = {"p", "li", "ul", "ol", "div", "section", "article", "aside", "nav", "header", "footer", "main", "h1", "h2",
            "h3", "h4", "summary", "details", "br", "option", "select", "label", "td", "th", "tr", "form", "button",
            "title", "input", "textarea", "noscript"}
VP_FILLED = {"title", "h1", "h2", "h3", "h4", "p", "li", "ul", "ol", "summary", "a", "button", "label", "option", "strong", "em"}
VP_RES = {"img": ("src", "srcset"), "source": ("src", "srcset"), "script": ("src",), "iframe": ("src",),
          "video": ("src", "poster"), "audio": ("src",), "embed": ("src",), "object": ("data",)}
VP_RELS = {"stylesheet", "preload", "modulepreload", "icon", "apple-touch-icon", "manifest", "mask-icon"}
VP_PLATZHALTER = re.compile(r"(?i:\b(?:todo|fixme|lorem|ipsum)\b)|\b(?:TBD|XXX|undefined|None|NaN)\b"
                            r"|\{[^{}]{0,40}\}|\[[^\[\]]{0,40}\]|[\[\]{}]|%s")
VP_DOPPELT_OK = {"die", "der", "das", "den", "dem", "des"}
VP_WORT_OK = {"Stellen", "Heistmer", "Bernekesbutle", "Horstmühle", "Krempermarsch", "Deutschland", "Deutschlands", "Deutsche", "Deutschen", "Kellinghusenstraße", "Holsteinring", "Wahlstedte", "Hohenasperfeld", "Wilstermarsch", "Wilsterau", "Wilsteraner", "Aukrugdörfern", "Horstweg", "Brunsbüttelkoog"}  # normale Wörter, die nur zufällig mit einem Ortsnamen beginnen
VP_ENDUNG_OK = {"r", "rn", "rs", "er", "ern", "ers", "erin", "erinnen", "s", "es", "isch", "ische", "ischen", "ischer", "isches",
                "weit"}
VP_PRAEP = re.compile(r"\b(in|im|am|bei|beim|von|vom|zu|zum|zur|nach|aus|für|mit|auf|ins)\s+(in|im|am|zum|zur|vom|beim|ins|auf)\b")


class VorlagenParser(HTMLParser):
    """Sammelt aus einer fertigen Seite, was die Vorlagen-Prüfung braucht."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.titles = self.h1 = 0
        self.meta = {}
        self.refs = []      # (Tag, Attribut, Adresse)
        self.links = []     # href aller <a>
        self.ids = set()
        self.problems = []
        self.texts = []     # sichtbarer Text, Blöcke durch \n getrennt
        self.attr_texts = []
        self.stack = []     # [tag, gefüllt, Abschnitt mit Inhalt, aria-hidden, class]
        self.prev_end = False
        self.raw = 0        # in <script>/<style>

    def _fill(self, gives_name):
        """Inhalt gefunden: Elemente im Stapel sind nicht leer (Links/Buttons nur bei lesbarem Namen)."""
        for ent in self.stack:
            if gives_name or ent[0] not in ("a", "button"):
                ent[1] = True
        for t in reversed(self.stack):  # Abschnitt hat Inhalt außer Überschriften
            if t[0] in ("h1", "h2", "h3", "h4") or (t[0] == "p" and t[4] == "label"):
                break
            if t[0] == "section":
                t[2] = True

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self.titles += 1
        elif tag == "h1":
            self.h1 += 1
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link" and set((a.get("rel") or "").split()) & VP_RELS:
            self.refs.append(("link", "href", a.get("href", "")))
        elif tag == "a":
            self.links.append(a.get("href"))
            if not a.get("href"):
                self.problems.append("<a> ohne href")
        for attr in VP_RES.get(tag, ()):
            for part in (a.get(attr) or "").split(","):
                if part.strip():
                    self.refs.append((tag, attr, part.strip().split()[0]))
        for u in re.findall(r"url\(\s*['\"]?([^'\")]+)", a.get("style") or ""):
            self.refs.append((tag, "style", u))
        if tag == "img" and "alt" not in a:
            self.problems.append(f"<img src=\"{a.get('src')}\"> ohne alt-Text")
        for k in ("alt", "title", "aria-label", "placeholder", "value"):
            if a.get(k):
                self.attr_texts.append(a[k])
        if tag in ("script", "style"):
            self.raw += 1
        if tag in VP_BLOCK:
            self.texts.append("\n")
        elif self.prev_end:
            self.texts.append(" ")
        self.prev_end = False
        if (tag == "img" and a.get("alt", "").strip()) or tag in ("input", "select", "textarea"):
            self._fill(True)
        elif tag in ("svg", "img"):
            self._fill(False)
        if tag in VP_VOID:
            self.prev_end = True
            return
        self.stack.append([tag, bool((a.get("aria-label") or "").strip()), False, a.get("aria-hidden") == "true",
                           a.get("class", "")])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VP_VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.raw:
            self.raw -= 1
        if not any(e[0] == tag for e in self.stack):
            return
        while self.stack:
            ent = self.stack.pop()
            if ent[0] in VP_FILLED and not ent[1]:
                self.problems.append(f"leeres <{ent[0]}>" + (" (Link ohne Text)" if ent[0] == "a" else ""))
            if ent[0] == "section" and ent[1] and not ent[2]:
                self.problems.append("Abschnitt <section> nur mit Überschrift, ohne Inhalt")
            elif ent[0] == "section" and not ent[1]:
                self.problems.append("leerer Abschnitt <section>")
            if ent[0] == tag:
                break
        if tag in VP_BLOCK:
            self.texts.append("\n")
        self.prev_end = True

    def handle_data(self, data):
        if self.raw:
            return
        self.texts.append(data)
        self.prev_end = False
        if data.strip():
            self._fill(not any(e[3] for e in self.stack))


def _vp_slug(text):
    t = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _vp_ortsnamen(site, contents):
    """(Namen, die nicht an anderen Wörtern kleben dürfen; bekannte Wörter aus Orts- und Ortsteilnamen)."""
    alle = {"Hamburg"} | {it["name"] for it in site.bezirke + site.stadtteile + site.umland}
    alle |= {b.get("gebiet", "") for b in site.bezirke}
    for c in contents.values():
        alle |= set(c.get("stadtteile") or [])
    bekannt = {w for n in alle for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", n)}
    namen = {"Hamburg"}
    for it in site.bezirke + site.stadtteile + site.umland:
        namen |= {w for w in re.split(r"[ ()\-]+", it["name"]) if len(w) >= 5 and w[0].isupper() and w not in ("Mitte", "Klein")}
    return namen, bekannt


def vorlage_check_text(text, namen, bekannt, where, warn):
    """Platzhalter, doppelte Wörter und angeklebte Ortsnamen in sichtbarem Text."""
    alt = "|".join(sorted((re.escape(n) for n in namen), key=len, reverse=True))
    klebt_hinten = re.compile(r"(?<![A-Za-zÄÖÜäöüß])(" + alt + r")([A-Za-zÄÖÜäöüß]+)")
    klebt_vorn = re.compile(r"([a-zäöüß])(" + alt + r")(?![a-zäöüß])")
    seen = set()

    def w(msg):
        if msg not in seen:
            seen.add(msg)
            warn(f"{where}: {msg}")

    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        cut = lambda m: "…" + line[max(0, m.start() - 25):m.end() + 25] + "…"
        for m in VP_PLATZHALTER.finditer(line):
            w(f"Platzhalter/Rest „{m.group(0)}“ im Text {cut(m)}")
        for m in re.finditer(r"\b([A-Za-zÄÖÜäöüß]{2,})\s+\1\b(?!-)", line):
            if m.group(1).lower() not in VP_DOPPELT_OK:
                w(f"doppeltes Wort „{m.group(0)}“ {cut(m)}")
        for m in VP_PRAEP.finditer(line):
            if m.group(1) != m.group(2):  # gleiche Wörter meldet schon die Prüfung oben
                w(f"doppelte Präposition „{m.group(0)}“ {cut(m)}")
        for m in re.finditer(r"[a-zäöüß]{2}[.!?][A-ZÄÖÜ][a-zäöüß]|\S [,.;:!?](?![\d.])", line):
            w(f"Leerzeichen fehlt oder steht vor dem Satzzeichen {cut(m)}")
        for m in klebt_hinten.finditer(line):
            wort, endung = m.group(0), m.group(2)
            if endung not in VP_ENDUNG_OK and wort not in bekannt and wort not in VP_WORT_OK:
                w(f"Ortsname „{m.group(1)}“ klebt am Wort: „{wort}“ {cut(m)}")
        for m in klebt_vorn.finditer(line):
            w(f"Ortsname „{m.group(2)}“ klebt am Wort davor {cut(m)}")


def vorlage_check_orte(site, contents, warn):
    """Ortsseiten: Ortsname passt zu Slug, Titel, h1, Formular; keine Stadtteile aus fremden Bezirken."""
    seen = set()
    warn = lambda msg, _w=warn: msg in seen or seen.add(msg) or _w(msg)
    bez_of = {}
    for b in site.bezirke:
        for x in (contents.get(b["slug"]) or {}).get("stadtteile") or []:
            bez_of.setdefault(x, []).append(b)
    for x, bs in bez_of.items():
        if len(bs) > 1:
            warn(f"Stadtteil '{x}' steht in der Stadtteil-Liste mehrerer Bezirke: {', '.join(b['slug'] + '.json' for b in bs)}")
    bez_by_name = {}
    for b in site.bezirke:
        bez_by_name[b["name"]] = bez_by_name[b.get("gebiet") or b["name"]] = b
    seiten_orte = {it["name"] for it in site.bezirke + site.umland}
    for slug, c in contents.items():
        kind, where = c["type"], slug + ".json"
        if kind not in ORTSTYPEN and kind != LEISTUNG_ORT:
            continue
        e = site.entry[slug]
        if kind == LEISTUNG_ORT:  # Ort ist der Bezirk; Slug prüft schon register_lo
            le, e = site.entry[e["leistung"]], site.entry[e["bezirk"]]
            own = e
            wort = re.split(r"[ &]", le["name"])[0].lower()  # z. B. „entrümpelung“, „pflaster“, „hecke“
            for k in ("h1", "title"):
                if wort not in c[k].lower():
                    warn(f"{where}: {k} nennt die Leistung '{le['name']}' nicht: {c[k]}")
            fremd = [b for b in site.bezirke if b is not e]
            for k in ("h1", "title", "menu", "label", "form_ort"):  # nicht lead/description: „Sitz in Altona“ ist erlaubt
                for b in fremd:
                    for n in {b["name"], b["gebiet"]}:
                        if re.search(r"(?<![\wäöüß-])" + re.escape(n) + r"(?![\wäöüß-])", c[k]):
                            warn(f"{where}: {k} nennt den Bezirk {n}, die Seite ist aber für {e['name']}: {c[k]}")
        else:
            own = e if kind == "bezirk" else site.bezirk_of(e) if kind == "stadtteil" else None
            ns = _vp_slug(e["name"])
            if not any((i == 0 or slug[i - 1] == "-") and (ns == slug[i:] or ns.startswith(slug[i:] + "-"))
                       for i in range(len(slug))):
                warn(f"{where}: Slug passt nicht zum Ortsnamen '{e['name']}'")
        short = re.split(r"[ (]", e["name"])[0]
        for k in ("h1", "title", "description", "menu", "form_ort"):
            if (k != "form_ort" or c[k].strip()) and short not in c[k]:
                warn(f"{where}: {k} nennt den Ort '{short}' nicht: {c[k]}")
        m = re.search(r"\bBezirk ([^·]+?)\s*(?:·|$)", c["label"])
        if own and m and m.group(1) not in (own["name"], own.get("gebiet")):
            warn(f"{where}: label nennt einen anderen Bezirk: {c['label']}")
        if kind == "umland" and "Kreis" in c["label"] and e["kreis"] not in c["label"]:
            warn(f"{where}: label nennt einen anderen Kreis: {c['label']} (laut site.json {e['kreis']})")
        for x in c.get("stadtteile") or []:
            if x in seiten_orte and x != e["name"]:
                warn(f"{where}: '{x}' steht als Stadt-/Ortsteil von {e['name']} in 'stadtteile', ist aber ein eigener Ort")
        txt = " ".join([c["lead"]] + [s["html"] for s in c["sections"]] + [f["a"] for f in c["faq"]])
        txt = html.unescape(re.sub(r"<[^>]+>", "", txt))
        if own:
            for m in re.finditer(r"\b(?:im|des) Bezirks? (Hamburg-[A-ZÄÖÜ][a-zäöüß]+|[A-ZÄÖÜ][a-zäöüß]+)", txt):
                b = bez_by_name.get(m.group(1))
                if b and b is not own:
                    warn(f"{where}: Text nennt „{m.group(0)}“, die Seite gehört aber zum Bezirk {own['name']}")
        if kind == "umland":
            for m in re.finditer(r"\b(?:Orts|Stadt)teil(?:e|en)? (?:von|der Stadt|der Gemeinde) ([A-ZÄÖÜ][\wäöüß-]+)", txt):
                if m.group(1) != short and m.group(1) in {re.split(r"[ (]", x)[0] for x in seiten_orte}:
                    warn(f"{where}: Text nennt „{m.group(0)}“ auf der Seite für {e['name']}")
            pat = re.escape(short) + r" (?:gehört|liegt) (?:\S+ ){0,3}?(?:zum|im) (?:Land)?[Kk]reis ([A-ZÄÖÜ][\wäöüß-]+)"
            for m in re.finditer(pat, txt):
                if m.group(1) not in e["kreis"]:
                    warn(f"{where}: Text nennt „{m.group(0)}“, laut site.json liegt {e['name']} im {e['kreis']}")
        for st, bs in bez_of.items():
            pat = r"(?<![\w-])" + re.escape(st) + r"(?![\w-]) (?:liegt |gehört )?(?:im|zum) Bezirk (Hamburg-[A-ZÄÖÜ][a-zäöüß]+|[A-ZÄÖÜ][a-zäöüß]+)"
            for m in re.finditer(pat, txt):
                b = bez_by_name.get(m.group(1))
                if b and b not in bs:
                    warn(f"{where}: „{m.group(0)}“ – {st} gehört zum Bezirk {bs[0]['name']}")
        for i, s in enumerate(c["sections"], 1):
            if re.search(r"</h3>\s*(?:<h3>|$)", s["html"].strip()):
                warn(f"{where} sections[{i}]: Zwischenüberschrift <h3> ohne Text darunter")


def _lo_saetze(site, contents, c):
    """Sätze ab 10 Wörtern, Orts- und Bezirksnamen und Zahlen neutralisiert (für den Kopien-Vergleich)."""
    namen = {"Hamburg"} | {it["name"] for it in site.bezirke + site.stadtteile} | {b["gebiet"] for b in site.bezirke}
    for x in contents.values():
        if x["type"] == "bezirk":
            namen |= set(x.get("stadtteile") or [])
    alt = "|".join(sorted((re.escape(n) for n in namen if n), key=len, reverse=True))
    teile = [c["lead"]] + [x["h2"] + ". " + x["html"] for x in c["sections"]] + [x["q"] + " " + x["a"] for x in c["faq"]]
    t = html.unescape(re.sub(r"<[^>]+>", " ", " ".join(teile)))
    out = {}
    for satz in re.split(r"(?<=[.!?:])\s+", re.sub(r"\s+", " ", t)):
        n = re.sub(r"(?<![\wäöüß-])(?:" + alt + r")(?![\wäöüß])", "ORT", satz)
        n = re.sub(r"\d+(?:[.,]\d+)?", "N", n).lower()
        n = " ".join(re.sub(r"[^\wäöüß]+", " ", n).split())
        if len(n.split()) >= 10:
            out.setdefault(n, satz.strip())
    return out


def check_lo_kopien(site, contents, warn):
    """Seiten „Leistung in einem Bezirk“ dürfen keine Sätze von anderen dieser Seiten oder von ihrer
    Leistungsseite übernehmen – auch nicht mit ausgetauschtem Ortsnamen."""
    lo = [x for x in contents.values() if x["type"] == LEISTUNG_ORT]
    saetze = {x["slug"]: _lo_saetze(site, contents, x) for x in lo}
    for x in lo:
        par = x["leistung"]
        if par in contents and par not in saetze:
            saetze[par] = _lo_saetze(site, contents, contents[par])
    for i, a in enumerate(lo):
        andere = [b["slug"] for b in lo[i + 1:]] + ([a["leistung"]] if a["leistung"] in saetze else [])
        for b in andere:
            gleich = [saetze[a["slug"]][k] for k in saetze[a["slug"]] if k in saetze[b]]
            if gleich:
                warn(f"{a['slug']}.json: {len(gleich)} Satz/Sätze wie auf {b}.json (Ortsnamen ausgeblendet), z. B. "
                     f"„{gleich[0][:90]}…“ – für den Bezirk eigenständig schreiben")


def vorlage_check_pages(site, contents, files, warn):
    """Alle fertigen Seiten: Sprache, genau ein h1, Titel/Beschreibung, nur lokale Quellen, alt-Texte,
    Links mit Text, keine leeren Abschnitte, keine Platzhalter, keine doppelten oder angeklebten Ortsnamen."""
    namen, bekannt = _vp_ortsnamen(site, contents)
    ids, links = {}, []
    for name, src in files.items():
        if not name.endswith(".html"):
            continue
        p = VorlagenParser()
        p.feed(src)
        p.close()
        ids[name] = p.ids
        w = lambda msg: warn(f"{name}: {msg}")
        if p.lang != "de":
            w(f'<html lang="{p.lang}"> statt lang="de"')
        if p.h1 != 1:
            w(f"{p.h1} Hauptüberschriften <h1> statt genau einer")
        if p.titles != 1:
            w(f"{p.titles} <title> statt genau einem")
        if "noindex" not in p.meta.get("robots", "") and not p.meta.get("description", "").strip():
            w("Meta-Beschreibung fehlt")
        for tag, attr, u in p.refs:
            if re.match(r"(?:[a-z][a-z0-9+.-]*:)?//", u, re.I) or re.match(r"https?:", u, re.I):
                w(f"<{tag} {attr}> lädt von fremder Adresse: {u}")
            elif not u.startswith("data:"):
                path = u.partition("#")[0].partition("?")[0].lstrip("/")
                if path and path not in files and not (ROOT / path).is_file():
                    w(f"<{tag} {attr}> verweist auf fehlende Datei: {u}")
        for k in ("og:image", "og:url"):
            if p.meta.get(k) and not p.meta[k].startswith(site.base):
                w(f"{k} zeigt auf fremde Adresse: {p.meta[k]}")
        for msg in dict.fromkeys(p.problems):
            n = p.problems.count(msg)
            w(msg + (f" ({n}×)" if n > 1 else ""))
        for m in re.finditer(r"\b([A-ZÄÖÜ][a-zäöüß]{2,})-\1\b", src):
            w(f"doppelter Ortsname „{m.group(0)}“ (auch in Attributen/JSON-LD)")
        text = "".join(p.texts) + "\n" + "\n".join(p.attr_texts) + "\n" + "\n".join(
            [p.meta.get(k, "") for k in ("description", "og:title", "og:description")])
        vorlage_check_text(text, namen, bekannt, name, warn)
        links += [(name, h) for h in p.links if h]
    for name, href in links:
        if re.match(r"(?:[a-z]+:|//)", href, re.I):
            continue
        path, _, frag = href.partition("#")
        if path.startswith("/"):  # 404.html der Live-Seite: Pfade ab Wurzel
            path = path.lstrip("/") or "index.html"
        target = name if not path else "index.html" if path in ("./", ".", "index.html") else path
        if target not in ids:
            if not (ROOT / target).is_file():
                warn(f"{name}: Link auf fehlende Seite {href}")
        elif frag and frag not in ids[target]:
            warn(f"{name}: Link {href}: Anker #{frag} gibt es dort nicht")
    vorlage_check_orte(site, contents, warn)
    check_lo_kopien(site, contents, warn)


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Baut die Website ta-abriss-hamburg.de")
    ap.add_argument("--out", help="Ausgabeordner (Standard: Repo-Hauptordner)")
    ap.add_argument("--preview", action="store_true", help="Vorschau mit Hinweisbalken, Startseiten-Links als index.html (nur mit --out)")
    ap.add_argument("--content", help="Inhaltsordner mit <slug>.json (Standard: src/content)")
    args = ap.parse_args(argv)
    if args.preview and not args.out:
        ap.error("--preview nur zusammen mit --out DIR (die Vorschau darf nicht ins Repo)")

    warnings, errors = [], []
    warn = warnings.append
    site = Site(SRC / "site.json")
    content_dir = Path(args.content).resolve() if args.content else SRC / "content"
    out_dir = Path(args.out).resolve() if args.out else ROOT
    today = datetime.date.today().isoformat()

    if out_dir == ROOT and args.preview:
        raise BuildError("Vorschau nicht ins Repo schreiben")

    # Inhalte laden und prüfen
    contents = {}
    if not content_dir.is_dir():
        warn(f"Inhaltsordner {content_dir} fehlt")
    else:
        for p in sorted(content_dir.glob("*.json")):
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as ex:
                errors.append(f"{p.name}: kein gültiges JSON ({ex})")
                continue
            if isinstance(c, dict) and c.get("type") == LEISTUNG_ORT:
                if not site.register_lo(c, p, errors):
                    continue
            elif isinstance(c, dict) and p.stem in site.lo_moeglich:
                errors.append(f"{p.name}: Seite „Leistung in einem Bezirk“ braucht \"type\": \"{LEISTUNG_ORT}\" "
                              "sowie 'leistung' und 'bezirk'")
                continue
            elif isinstance(c, dict) and str(c.get("slug")) not in site.kind and p.stem not in site.kind:
                warn(f"{p.name}: Slug steht nicht in src/site.json – übersprungen")
                continue
            if validate(c, p, site, errors, warn):
                contents[c["slug"]] = c
    missing = [x for x in site.content_slugs() if x not in contents]
    if missing:
        warn(f"Kein Inhalt für {len(missing)} Seite(n) in {content_dir.name}/ – übersprungen und nirgends verlinkt: "
             + ", ".join(missing))

    preise = load_preise(SRC / "preise.json", site, args.preview, errors, warn)
    home_src = (ROOT / "index.html").read_text(encoding="utf-8")
    ctx = Ctx(site, args.preview, today, contents.keys(), home_src)
    ctx.preise = preise
    try:
        ctx.content_rel = content_dir.relative_to(ROOT).as_posix()
    except ValueError:
        ctx.content_rel = content_dir.as_posix()
    linker = Linker(site, contents.keys(), home_ids(home_src), warn)
    for c in contents.values():
        check_links_in(c, linker, errors)
    check_home_links(ctx, linker, errors)
    check_home_images(ctx, errors)
    check_stadtteil_chips(site, contents, warn)
    check_nap(site, home_src, contents, warn)
    sub = {k: sorted(set(v) - {"index.html"}) for k, v in linker.pending.items()}
    sub = {k: v for k, v in sub.items() if v}
    if sub:
        warn("Links auf Seiten ohne Inhalt, als reiner Text ausgegeben: " + "; ".join(
            f"{k}.html ← {', '.join(v)}" for k, v in sub.items()))
    home_dead = [k for k, v in linker.pending.items() if "index.html" in v]
    if home_dead:
        warn("index.html (von Hand gepflegt) verlinkt Seiten ohne Inhalt – bitte dort anpassen: "
             + ", ".join(f"{k}.html" for k in home_dead))

    if errors:
        for w in warnings:
            print("WARNUNG:", w, file=sys.stderr)
        for e in errors:
            print("FEHLER:", e, file=sys.stderr)
        print(f"Abbruch: {len(errors)} Fehler, nichts geschrieben.", file=sys.stderr)
        return 1

    # Seiten rendern (erst alles im Speicher, dann schreiben)
    files = {"index.html": render_index(ctx)}
    for entry in site.rechtliches:
        frag = (SRC / "legal" / f"{entry['slug']}.html").read_text(encoding="utf-8")
        files[f"{entry['slug']}.html"] = render_legal(ctx, entry, frag)
    order = [x for x in site.content_slugs() if x in contents]
    for slug in order:
        files[f"{slug}.html"] = render_content_page(ctx, contents[slug])
    files[f"{UEBERSICHT}.html"] = render_einsatzgebiet(ctx)
    files["404.html"] = render_404(ctx)
    files["llms.txt"] = render_llms(ctx)
    if not args.preview:
        has = lambda items: [x["slug"] for x in ctx.pages(items)]
        slugs = (has(site.leistungen) + [x["slug"] for x in ctx.lo_pages()] + has(site.bezirke + site.ratgeber)
                 + [UEBERSICHT] + has(site.stadtteile + site.umland))
        files["sitemap.xml"] = sitemap(site, slugs, today, lastmod_daten(ctx, slugs))
    vorlage_check_pages(site, contents, files, warn)
    check_images(files, warn)

    out_dir.mkdir(parents=True, exist_ok=True)
    if out_dir != ROOT:
        for d in ("assets", "img"):
            if (out_dir / d).exists():
                shutil.rmtree(out_dir / d)
            shutil.copytree(ROOT / d, out_dir / d)
        for name in ICON_FILES:
            shutil.copy2(ROOT / name, out_dir / name)
        if not args.preview:
            shutil.copy2(ROOT / "robots.txt", out_dir / "robots.txt")
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")

    robots = ROOT / "robots.txt"
    line = f"Sitemap: {site.base}sitemap.xml"
    if line not in robots.read_text(encoding="utf-8").splitlines():
        if out_dir == ROOT:
            robots.write_text(robots.read_text(encoding="utf-8").rstrip("\n") + f"\n\n{line}\n", encoding="utf-8")
            print("robots.txt: Sitemap-Zeile ergänzt")
        else:
            warn("robots.txt: Sitemap-Zeile fehlt")

    for w in warnings:
        print("WARNUNG:", w, file=sys.stderr)
    where = "Repo" if out_dir == ROOT else str(out_dir)
    mode = " (Vorschau)" if args.preview else ""
    print(f"Fertig{mode}: {len(files)} Dateien nach {where} geschrieben: {', '.join(files)}")
    print(f"{len(order)} Unterseiten aus {content_dir}, {len(warnings)} Warnungen")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as ex:
        print("FEHLER:", ex, file=sys.stderr)
        sys.exit(1)
