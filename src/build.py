#!/usr/bin/env python3
"""Generator für ta-abriss-hamburg.de (nur Python-Standardbibliothek).

Aufruf (im Repo-Hauptordner):
  python3 src/build.py                         Website im Repo bauen
  python3 src/build.py --out DIR --preview     komplette Vorschau nach DIR (mit Hinweisbalken)
  python3 src/build.py --content src/test ...  anderes Inhaltsverzeichnis verwenden

Erzeugt:
  <slug>.html je JSON in src/content/ (Leistungen, Bezirke, Stadtteile, Umland, Ratgeber),
  einsatzgebiet.html (Übersicht aus src/site.json), impressum.html, datenschutz.html,
  index.html (nur die Bereiche zwischen den Markern @head, @header, @umland, @footer),
  sitemap.xml; prüft robots.txt.

Fehlt für eine Seite aus src/site.json die JSON-Datei, wird sie übersprungen und nirgends
verlinkt (Menü, Footer, Chips, Übersicht, Sitemap; Links im Inhalt werden zu reinem Text).
"""
import argparse
import datetime
import html
import json
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

TYPES = ("leistung", "bezirk", "stadtteil", "umland", "ratgeber")
ORTSTYPEN = ("bezirk", "stadtteil", "umland")
UEBERSICHT = "einsatzgebiet"  # erzeugte Übersichtsseite einsatzgebiet.html
SECTION_TAGS = {"p", "ul", "ol", "li", "strong", "em", "h3", "a"}
INLINE_TAGS = {"strong", "em", "a"}
A_ATTRS = {"href", "title", "rel"}
REQUIRED = ("slug", "type", "menu", "title", "description", "label", "h1", "lead", "facts",
            "image", "form_leistung", "form_ort", "sections", "faq")
KNOWN = set(REQUIRED) | {"stadtteile", "sources", "notes_for_review", "note_stellen"}
MAX_WEITERE_ORTE = 8

CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l5 5L20 6"/></svg>'
PHONE_SVG = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5'
             'L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>')
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
        for key in ("menue_umland", "startseite_umland"):
            for x in d.get(key, []):
                if self.kind.get(x) != "umland":
                    raise BuildError(f"site.json: {key}: '{x}' steht nicht in 'umland'")
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

    def bild_src(self, key):
        """Relativer Pfad eines Bildes aus 'bilder' (Schlüssel bleibt gleich, Dateiname steht in 'datei')."""
        return "img/" + self.bilder[key]["datei"]

    def bild_url(self, key):
        return self.base + self.bild_src(key)

    def content_slugs(self):
        return [it["slug"] for it in self.leistungen + self.bezirke + self.ratgeber + self.stadtteile + self.umland]

    def url(self, slug):
        return self.base + slug + ".html"

    def bezirk_of(self, stadtteil):
        return self.entry[stadtteil["bezirk"]]


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
        if slug in self.site.kind:
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
    if c["type"] == "bezirk":
        if not (isinstance(st, list) and st and all(is_str(x) for x in st)):
            e("bezirk braucht 'stadtteile' (Liste mit Texten)")
    elif c["type"] in ("stadtteil", "umland") and st is not None:
        if not (isinstance(st, list) and all(is_str(x) for x in st)):
            e("'stadtteile' muss eine Liste mit Texten sein (darf leer sein)")
        elif st and c["type"] == "stadtteil":
            warn(f"{where}: 'stadtteile' wird bei Stadtteil-Seiten nicht angezeigt")
    if c["type"] == "ratgeber":
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

    def has(self, slug):
        """Gibt es die Seite im Build? Nur dann wird sie verlinkt."""
        return slug in self.generated or slug == UEBERSICHT or self.site.kind.get(slug) == "recht"

    def pages(self, items):
        return [x for x in items if self.has(x["slug"])]

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
            if slug and slug in self.site.kind and not self.has(slug):
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
    <a class="btn" href="{esc(contact_href)}">Kostenlose Besichtigung {ARR}</a>
    <noscript><a class="btn alt" href="#start">Menü schließen</a></noscript>
  </div>''')
    return '<nav id="menu" class="menu" aria-label="Menü">\n  ' + "\n  ".join(parts) + "\n</nav>"


def render_footer(ctx, current, on_home, fab_href):
    s, f = ctx.site, ctx.site.firma
    li = lambda it: f'<li><a href="{esc(it["slug"])}.html"{cur(it["slug"] == current)}>{esc(it["name"])}</a></li>'
    leist = "".join(li(x) for x in ctx.pages(s.leistungen))
    bez = "".join(li(x) for x in ctx.pages(s.bezirke))
    rest = "".join(li(x) for x in ctx.pages(s.ratgeber) + s.rechtliches)
    alle = (f'<p class="foot-all"><a href="{UEBERSICHT}.html"{cur(current == UEBERSICHT)}>Alle Orte im Einsatzgebiet '
            f'<span aria-hidden="true">→</span></a></p>')
    cols = []
    if leist:
        cols.append(f'  <div><h3>Leistungen</h3><ul class="two">{leist}</ul></div>')
    cols.append(f'  <div><h3>Bezirke</h3>' + (f'<ul class="two">{bez}</ul>' if bez else "") + f'{alle}</div>')
    cols.append(f'  <div><h3>Ratgeber &amp; Rechtliches</h3><ul>{rest}</ul></div>')
    out = [f'''<footer><div class="wrap foot">
  <div class="firma">
    <h3>{esc(f["name"])}</h3>
    <p>Inh. {esc(f["inhaber"])}<br>{esc(f["strasse"])}<br>{esc(f["plz"])} {esc(f["ort"])}</p>
    <ul><li><a href="tel:{esc(f["telefon_link"])}">Telefon: {esc(f["telefon"])}</a></li><li><a href="mailto:{esc(f["email"])}">{esc(f["email"])}</a></li></ul>
  </div>
''' + "\n".join(cols) + '\n</div></footer>']
    if fab_href:
        out.append(f'\n<a class="btn fab" href="{esc(fab_href)}">Anfrage {ARR}</a>')
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


def mini_card(ctx, it):
    b = ctx.site.bilder[it["bild"]]
    return f'''<article class="mini reveal">
      <img src="{esc(ctx.site.bild_src(it["bild"]))}" width="{b["w"]}" height="{b["h"]}" alt="{esc(b["alt"])}" loading="lazy">
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


def weitere_orte(ctx, entry):
    """Andere Umland-Seiten: gleicher Kreis zuerst, dann gleiches Bundesland, dann die übrigen."""
    others = [u for u in ctx.pages(ctx.site.umland) if u["slug"] != entry["slug"]]
    rank = lambda u: 0 if u["kreis"] == entry["kreis"] else 1 if u["land"] == entry["land"] else 2
    return sorted(others, key=rank)[:MAX_WEITERE_ORTE]  # sorted ist stabil: sonst Reihenfolge aus site.json


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
    return f'''<div class="subhero">
  <img class="photo" src="{esc(ctx.site.bild_src(image))}" alt="{esc(img["alt"])}" width="{img["w"]}" height="{img["h"]}" fetchpriority="high">
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
    firma_ref = {"@id": s.base + "#firma"}
    data_page = c["menu"].strip()
    if kind in ORTSTYPEN and "abriss" not in data_page.lower():
        data_page = "Abriss " + data_page
    bezirk = s.bezirk_of(entry) if kind == "stadtteil" else None

    # Brotkrumen: (Name, Link auf der Seite, URL im JSON-LD)
    trail = [("Startseite", ctx.home, s.base)]
    if kind == "leistung":
        trail.append(("Leistungen", ctx.home_link("leistungen", False), s.base + "#leistungen"))
    elif kind == "ratgeber":
        trail.append(("Ratgeber", ctx.home_link("fragen", False), s.base + "#fragen"))
    else:
        trail.append(("Einsatzgebiet", UEBERSICHT + ".html", s.url(UEBERSICHT)))
    if bezirk:
        ok = ctx.has(bezirk["slug"])
        trail.append((bezirk["name"], bezirk["slug"] + ".html" if ok else None, s.url(bezirk["slug"]) if ok else None))

    ld = [breadcrumb_ld([(n, u) for n, _, u in trail] + [(c["h1"], url)])]
    service = {"@context": "https://schema.org", "@type": "Service", "name": c["h1"],
               "serviceType": "Abriss und Rückbau", "description": c["description"], "provider": firma_ref}
    if kind == "leistung":
        ld.append({"@context": "https://schema.org", "@type": "Service", "name": c["h1"], "serviceType": c["menu"],
                   "description": c["description"], "provider": firma_ref,
                   "areaServed": {"@type": "City", "name": "Hamburg"}, "url": url})
    elif kind == "bezirk":
        ld.append(dict(service, areaServed={"@type": "AdministrativeArea", "name": entry["gebiet"]}, url=url))
    elif kind == "stadtteil":
        ld.append(dict(service, areaServed={"@type": "Place", "name": "Hamburg-" + entry["name"],
                                            "containedInPlace": {"@type": "AdministrativeArea", "name": bezirk["gebiet"]}},
                       url=url))
    elif kind == "umland":
        ld.append(dict(service, areaServed={"@type": "City", "name": entry["name"],
                                            "containedInPlace": {"@type": "AdministrativeArea", "name": entry["kreis"]}},
                       url=url))
    else:
        ld.append({"@context": "https://schema.org", "@type": "Article", "headline": c["h1"],
                   "description": c["description"], "datePublished": ctx.today, "dateModified": ctx.today,
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
    if kind == "umland" and c.get("stadtteile"):
        chips = "".join(f"<span>{esc(x)}</span>" for x in c["stadtteile"])
        secs.append(f'<section>\n      <h2>Ortsteile von {esc(entry["name"])}</h2>\n      <div class="chips">{chips}</div>\n    </section>')
    if kind == "leistung" and ctx.pages(s.bezirke):
        secs.append(f'<section>\n      <h2>In diesen Bezirken sind wir im Einsatz</h2>\n      <div class="chips">{chip_links(ctx.pages(s.bezirke))}</div>\n    </section>')
    if kind == "ratgeber":
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
        cards_shown = True
        cards = "\n    ".join(mini_card(ctx, x) for x in leist)
        after.append(f'''<section class="sec-alt"><div class="wrap">
  <div class="head reveal">
    <p class="label">Leistungen</p>
    <h2>Unsere Leistungen in {esc(entry["name"])}</h2>
  </div>
  <div class="minis">
    {cards}
  </div>
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
    if kind == "umland":
        alle = (f'\n  <p class="go-wrap"><a class="go-all" href="{UEBERSICHT}.html">Alle Orte im Einsatzgebiet '
                f'<span aria-hidden="true">→</span></a></p>')
        others = weitere_orte(ctx, entry)
        if others:
            after.append(nav_section("Einsatzgebiet", "Weitere Orte im Umland", chip_links(others), alle))
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
        render_footer(ctx, entry["slug"], False, None),
    ])
    return doc(head, body, f"src/legal/{entry['slug']}.html")


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
        render_footer(ctx, "404", False, None),
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
    return pairs


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
    business = {
        "@context": "https://schema.org", "@type": "HomeAndConstructionBusiness", "@id": s.base + "#firma",
        "name": f["name"], "description": f["beschreibung"], "url": s.base, "image": s.bild_url("abriss"),
        "logo": s.base + "logo.png",
        "telephone": f["telefon_schema"], "email": f["email"],
        "address": {"@type": "PostalAddress", "streetAddress": f["strasse"], "postalCode": f["plz"],
                    "addressLocality": f["ort"], "addressCountry": "DE"},
        "areaServed": [{"@type": "AdministrativeArea", "name": b["gebiet"]} for b in s.bezirke]
                      + [{"@type": "City", "name": u["name"]} for u in ctx.pages(s.umland)],
    }
    head = head_assets(ctx, extra_noindex=True) + [jsonld(business), jsonld(faq_jsonld(s, home_faq_pairs(src)))]
    out = fill_marker(src, "head", "\n".join(head))
    out = fill_marker(out, "header", render_header(ctx, "index", True, "#anfrage"))
    out = fill_marker(out, "umland", home_umland(ctx))
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


def sitemap(site, slugs, today):
    urls = [site.base] + [site.url(x) for x in slugs]
    rows = "\n".join(f"  <url><loc>{esc(u)}</loc><lastmod>{today}</lastmod></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + "\n</urlset>\n")


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
            if isinstance(c, dict) and str(c.get("slug")) not in site.kind and p.stem not in site.kind:
                warn(f"{p.name}: Slug steht nicht in src/site.json – übersprungen")
                continue
            if validate(c, p, site, errors, warn):
                contents[c["slug"]] = c
    missing = [x for x in site.content_slugs() if x not in contents]
    if missing:
        warn(f"Kein Inhalt für {len(missing)} Seite(n) in {content_dir.name}/ – übersprungen und nirgends verlinkt: "
             + ", ".join(missing))

    home_src = (ROOT / "index.html").read_text(encoding="utf-8")
    ctx = Ctx(site, args.preview, today, contents.keys(), home_src)
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
    if not args.preview:
        has = lambda items: [x["slug"] for x in ctx.pages(items)]
        slugs = has(site.leistungen + site.bezirke + site.ratgeber) + [UEBERSICHT] + has(site.stadtteile + site.umland)
        files["sitemap.xml"] = sitemap(site, slugs, today)

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
