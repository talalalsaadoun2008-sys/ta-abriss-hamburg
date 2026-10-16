#!/usr/bin/env python3
"""Generator für ta-abriss-hamburg.de (nur Python-Standardbibliothek).

Aufruf (im Repo-Hauptordner):
  python3 src/build.py                         Website im Repo bauen
  python3 src/build.py --out DIR --preview     komplette Vorschau nach DIR (mit Hinweisbalken)
  python3 src/build.py --content src/test ...  anderes Inhaltsverzeichnis verwenden

Erzeugt:
  <slug>.html je JSON in src/content/, impressum.html, datenschutz.html,
  index.html (nur die Bereiche zwischen den Markern @head, @header, @footer),
  sitemap.xml; prüft robots.txt.
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

TYPES = ("leistung", "bezirk", "ratgeber")
SECTION_TAGS = {"p", "ul", "ol", "li", "strong", "em", "h3", "a"}
INLINE_TAGS = {"strong", "em", "a"}
A_ATTRS = {"href", "title", "rel"}
REQUIRED = ("slug", "type", "menu", "title", "description", "label", "h1", "lead", "facts",
            "image", "form_leistung", "form_ort", "sections", "faq")
KNOWN = set(REQUIRED) | {"stadtteile", "sources", "notes_for_review"}

CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l5 5L20 6"/></svg>'
PHONE_SVG = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5'
             'L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>')
ARR = '<span class="arr" aria-hidden="true">→</span>'


class BuildError(Exception):
    pass


def esc(s):
    return html.escape(str(s), quote=True)


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
        self.ratgeber = d["ratgeber"]
        self.rechtliches = d["rechtliches"]
        self.bilder = d["bilder"]
        self.form_options = d["formular_leistungen"]
        self.kind = {}
        self.entry = {}
        for kind, items in (("leistung", self.leistungen), ("bezirk", self.bezirke),
                            ("ratgeber", self.ratgeber), ("recht", self.rechtliches)):
            for it in items:
                if it["slug"] in self.kind:
                    raise BuildError(f"site.json: Slug doppelt: {it['slug']}")
                self.kind[it["slug"]] = kind
                self.entry[it["slug"]] = it

    def content_slugs(self):
        return [it["slug"] for it in self.leistungen + self.bezirke + self.ratgeber]

    def url(self, slug):
        return self.base + slug + ".html"


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
        if slug in self.generated or self.site.kind.get(slug) == "recht":
            return None
        if slug in self.site.kind:
            self.pending.setdefault(slug, []).append(where.split(" ")[0])
            return None
        return f"Link {href}: Seite {slug}.html gibt es nicht (nicht in src/site.json)"


def is_str(v):
    return isinstance(v, str) and v.strip() != ""


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
    if c["type"] == "bezirk":
        st = c.get("stadtteile")
        if not (isinstance(st, list) and st and all(is_str(x) for x in st)):
            e("bezirk braucht 'stadtteile' (Liste mit Texten)")
    if c["type"] == "ratgeber":
        src = c.get("sources")
        if not (isinstance(src, list) and src):
            e("ratgeber braucht 'sources'")
        else:
            for i, s in enumerate(src, 1):
                if not (isinstance(s, dict) and is_str(s.get("title")) and re.match(r"https?://", str(s.get("url", "")))):
                    e(f"sources[{i}] braucht 'title' und eine http(s)-'url'")
    # Bei leistung/bezirk bleiben 'sources' als interner Beleg in der JSON-Datei (nicht ausgegeben).
    if is_str(c.get("title")) and len(c["title"]) > 65:
        warn(f"{where}: title ist {len(c['title'])} Zeichen lang (Google zeigt ca. 60)")
    if is_str(c.get("description")) and len(c["description"]) > 160:
        warn(f"{where}: description ist {len(c['description'])} Zeichen lang (Google zeigt ca. 155)")
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

    def home_link(self, anchor, on_home):
        if on_home:
            return "#" + anchor
        if anchor == "start":
            return self.home
        return self.home + "#" + anchor

    def fix_home_links(self, text):
        """Links auf die Startseite in Inhalten an den Build anpassen (Vorschau: index.html)."""
        if not self.preview:
            return text
        return re.sub(r'href="\./(#[^"]*)?"', lambda m: f'href="index.html{m.group(1) or ""}"', text)


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
  <a class="brand" href="{esc(brand)}"><b>T&amp;A</b><span>Abriss &amp; Rückbau</span></a>
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
    groups = [
        ("g-leist", "m-leist", "Leistungen", [page(x) for x in s.leistungen], "cols"),
        ("g-bez", "m-bez", "Abriss nach Bezirk", [page(x) for x in s.bezirke], "cols"),
        ("g-rat", "m-rat", "Ratgeber", [page(x) for x in s.ratgeber], ""),
        ("g-recht", "m-recht", "Rechtliches", [page(x) for x in s.rechtliches], "cols"),
    ]
    parts = [f'<div class="grp g-main">\n    {menu_list(main)}\n  </div>']
    for gcls, hid, title, items, lcls in groups:
        lst = menu_list(items, lcls).replace("<ul", f'<ul aria-labelledby="{hid}"', 1)
        parts.append(f'<div class="grp {gcls}">\n    <p class="menu-h" id="{hid}">{esc(title)}</p>\n    {lst}\n  </div>')
    parts.append(f'''<div class="menu-cta">
    <a class="btn alt" href="tel:{esc(f["telefon_link"])}">{PHONE_SVG}{esc(f["telefon"])}</a>
    <a class="btn" href="{esc(contact_href)}">Kostenlose Besichtigung {ARR}</a>
    <noscript><a class="btn alt" href="#start">Menü schließen</a></noscript>
  </div>''')
    return '<nav id="menu" class="menu" aria-label="Menü">\n  ' + "\n  ".join(parts) + "\n</nav>"


def render_footer(ctx, current, on_home, fab_href):
    s, f = ctx.site, ctx.site.firma
    li = lambda it: f'<li><a href="{esc(it["slug"])}.html"{cur(it["slug"] == current)}>{esc(it["name"])}</a></li>'
    leist = "".join(li(x) for x in s.leistungen)
    bez = "".join(li(x) for x in s.bezirke)
    rest = "".join(li(x) for x in s.ratgeber + s.rechtliches)
    out = [f'''<footer><div class="wrap foot">
  <div class="firma">
    <h3>{esc(f["name"])}</h3>
    <p>Inh. {esc(f["inhaber"])}<br>{esc(f["strasse"])}<br>{esc(f["plz"])} {esc(f["ort"])}</p>
    <ul><li><a href="tel:{esc(f["telefon_link"])}">Telefon: {esc(f["telefon"])}</a></li><li><a href="mailto:{esc(f["email"])}">{esc(f["email"])}</a></li></ul>
  </div>
  <div><h3>Leistungen</h3><ul class="two">{leist}</ul></div>
  <div><h3>Bezirke</h3><ul class="two">{bez}</ul></div>
  <div><h3>Ratgeber &amp; Rechtliches</h3><ul>{rest}</ul></div>
</div></footer>''']
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


def mini_card(ctx, it):
    b = ctx.site.bilder[it["bild"]]
    return f'''<article class="mini reveal">
      <img src="img/{esc(it["bild"])}.jpg" width="{b["w"]}" height="{b["h"]}" alt="{esc(b["alt"])}" loading="lazy">
      <div class="body">
        <h3><a href="{esc(it["slug"])}.html">{esc(it["name"])}</a></h3>
        <p>{esc(it["kurz"])}</p>
        <span class="go" aria-hidden="true">Mehr zu {esc(it["name"])}&nbsp;<span>→</span></span>
      </div>
    </article>'''


def chip_links(items):
    return "".join(f'<a href="{esc(it["slug"])}.html">{esc(it["name"])}</a>' for it in items)


def contact_section(ctx, c, data_page):
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
    opt = f"<option>{esc(c['form_leistung'])}</option>"
    need(opt, f"<option selected>{esc(c['form_leistung'])}</option>")
    if c["form_ort"].strip():
        need('<input id="ort" name="ort"', f'<input id="ort" name="ort" value="{esc(c["form_ort"].strip())}"')
    return sec


# ---------------------------------------------------------------------------
# Seiten
# ---------------------------------------------------------------------------
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
    out.append('<link rel="icon" href="favicon.svg" type="image/svg+xml">')
    out += head_assets(ctx, extra_noindex=not noindex)
    out += [jsonld(x) for x in ld]
    return "\n".join(out)


def render_content_page(ctx, c):
    s, f = ctx.site, ctx.site.firma
    slug, kind = c["slug"], c["type"]
    entry = s.entry[slug]
    url = s.url(slug)
    img = s.bilder[c["image"]]
    firma_ref = {"@id": s.base + "#firma"}
    mid = {"leistung": ("Leistungen", "leistungen"), "bezirk": ("Einsatzgebiet", "gebiet"),
           "ratgeber": ("Ratgeber", "fragen")}[kind]
    data_page = c["menu"].strip()
    if kind == "bezirk" and "abriss" not in data_page.lower():
        data_page = "Abriss " + data_page

    ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Startseite", "item": s.base},
        {"@type": "ListItem", "position": 2, "name": mid[0], "item": s.base + "#" + mid[1]},
        {"@type": "ListItem", "position": 3, "name": c["h1"], "item": url}]}]
    if kind == "leistung":
        ld.append({"@context": "https://schema.org", "@type": "Service", "name": c["h1"], "serviceType": c["menu"],
                   "description": c["description"], "provider": firma_ref,
                   "areaServed": {"@type": "City", "name": "Hamburg"}, "url": url})
    elif kind == "bezirk":
        ld.append({"@context": "https://schema.org", "@type": "Service", "name": c["h1"],
                   "serviceType": "Abriss und Rückbau", "description": c["description"], "provider": firma_ref,
                   "areaServed": {"@type": "AdministrativeArea", "name": entry["gebiet"]}, "url": url})
    else:
        ld.append({"@context": "https://schema.org", "@type": "Article", "headline": c["h1"],
                   "description": c["description"], "datePublished": ctx.today, "dateModified": ctx.today,
                   "author": firma_ref, "publisher": firma_ref, "mainEntityOfPage": url,
                   "image": f"{s.base}img/{c['image']}.jpg", "inLanguage": "de-DE"})
    if c["faq"]:
        ld.append(faq_jsonld(s, [(x["q"], x["a"]) for x in c["faq"]]))

    og = [("type", "article" if kind == "ratgeber" else "website"), ("locale", "de_DE"),
          ("site_name", f["name"]), ("title", c["title"]), ("description", c["description"]),
          ("image", f"{s.base}img/{c['image']}.jpg"), ("url", url)]
    head = page_head(ctx, title=c["title"], description=c["description"], canonical=url, og=og, ld=ld)

    # Inhalt
    secs = []
    for sec in c["sections"]:
        secs.append(f'<section>\n      <h2>{esc(sec["h2"])}</h2>\n      {ctx.fix_home_links(sec["html"].strip())}\n    </section>')
    if kind == "bezirk":
        chips = "".join(f"<span>{esc(x)}</span>" for x in c["stadtteile"])
        secs.append(f'<section>\n      <h2>Stadtteile im Bezirk {esc(entry["name"])}</h2>\n      <div class="chips">{chips}</div>\n    </section>')
    if kind == "leistung":
        secs.append(f'<section>\n      <h2>In diesen Bezirken sind wir im Einsatz</h2>\n      <div class="chips">{chip_links(s.bezirke)}</div>\n    </section>')
    if kind == "ratgeber":
        items = []
        for src in c["sources"]:
            host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", src["url"]))
            items.append(f'<li><a href="{esc(src["url"])}" rel="noopener">{esc(src["title"])}</a><span class="host">{esc(host)}</span></li>')
        secs.append('<section>\n      <h2>Quellen</h2>\n      <ol class="sources">' + "".join(items) + '</ol>\n'
                    '      <p class="note">Diese Übersicht ersetzt keine Rechtsberatung. Im Zweifel fragen Sie beim zuständigen Bezirksamt nach.</p>\n    </section>')

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
    if kind == "bezirk":
        cards = "\n    ".join(mini_card(ctx, x) for x in s.leistungen)
        after.append(f'''<section class="sec-alt"><div class="wrap">
  <div class="head reveal">
    <p class="label">Leistungen</p>
    <h2>Unsere Leistungen in {esc(entry["name"])}</h2>
  </div>
  <div class="minis">
    {cards}
  </div>
</div></section>''')
    if c["faq"]:
        qa = "\n    ".join(f'<details><summary>{esc(x["q"])}</summary><p>{ctx.fix_home_links(inline_html(x["a"]))}</p></details>' for x in c["faq"])
        tight = ' class="sec-tight"' if kind != "bezirk" else ""
        after.append(f'''<section id="fragen"{tight}><div class="wrap">
  <div class="head reveal">
    <p class="label">Häufige Fragen</p>
    <h2>Fragen und Antworten</h2>
  </div>
  <div class="faq reveal">
    {qa}
  </div>
</div></section>''')
    after.append(contact_section(ctx, c, data_page))
    if kind == "leistung":
        others = [x for x in s.leistungen if x["slug"] != slug]
        cards = "\n    ".join(mini_card(ctx, x) for x in others)
        after.append(f'''<section><div class="wrap">
  <div class="head reveal">
    <p class="label">Alles aus einer Hand</p>
    <h2>Weitere Leistungen</h2>
  </div>
  <div class="minis n3">
    {cards}
  </div>
</div></section>''')
    if kind == "bezirk":
        others = [x for x in s.bezirke if x["slug"] != slug]
        after.append(f'''<section><div class="wrap">
  <div class="head reveal">
    <p class="label">Einsatzgebiet</p>
    <h2>Weitere Bezirke</h2>
  </div>
  <div class="chips">{chip_links(others)}</div>
</div></section>''')

    crumbs = f'''<nav class="crumbs wrap" aria-label="Brotkrumen"><ol>
  <li><a href="{esc(ctx.home)}">Startseite</a></li>
  <li><a href="{esc(ctx.home_link(mid[1], False))}">{esc(mid[0])}</a></li>
  <li><span aria-current="page">{esc(entry["name"])}</span></li>
</ol></nav>'''
    hero = f'''<div class="subhero">
  <img class="photo" src="img/{esc(c["image"])}.jpg" alt="" width="{img["w"]}" height="{img["h"]}" fetchpriority="high">
  <div class="wrap">
    <p class="label">{esc(c["label"])}</p>
    <h1>{esc(c["h1"])}</h1>
    <p class="lead">{esc(c["lead"])}</p>
    <div class="ctas">
      <a class="btn" href="#anfrage">Kostenlose Besichtigung {ARR}</a>
      <a class="btn line" href="tel:{esc(f["telefon_link"])}">{PHONE_SVG}{esc(f["telefon"])}</a>
    </div>
    <div class="facts">
      {facts_html(c["facts"])}
    </div>
  </div>
</div>'''
    body = "\n\n".join([
        render_header(ctx, slug, False, "#anfrage"),
        '<main id="start">\n' + crumbs + "\n" + hero + '\n\n<div class="wrap page">\n  <div class="prose">\n    '
        + "\n    ".join(secs) + "\n  </div>\n  " + side + "\n</div>\n\n" + "\n\n".join(after) + "\n</main>",
        render_footer(ctx, slug, False, "#anfrage"),
    ])
    return doc(head, body, f"{ctx.content_rel}/{slug}.json")


def render_legal(ctx, entry, fragment):
    s = ctx.site
    head = page_head(ctx, title=entry["title"], description=None, noindex=True)
    body = "\n\n".join([
        render_header(ctx, entry["slug"], False, ctx.home_link("anfrage", False)),
        f'<main id="start" class="wrap legal"><div>\n{ctx.fix_home_links(fragment.strip())}\n</div></main>',
        render_footer(ctx, entry["slug"], False, None),
    ])
    return doc(head, body, f"src/legal/{entry['slug']}.html")


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


def render_index(ctx):
    s, f = ctx.site, ctx.site.firma
    src = ctx.home_src
    business = {
        "@context": "https://schema.org", "@type": "HomeAndConstructionBusiness", "@id": s.base + "#firma",
        "name": f["name"], "description": f["beschreibung"], "url": s.base, "image": s.base + "img/abriss.jpg",
        "telephone": f["telefon_schema"], "email": f["email"],
        "address": {"@type": "PostalAddress", "streetAddress": f["strasse"], "postalCode": f["plz"],
                    "addressLocality": f["ort"], "addressCountry": "DE"},
        "areaServed": [{"@type": "AdministrativeArea", "name": b["gebiet"]} for b in s.bezirke],
    }
    head = head_assets(ctx, extra_noindex=True) + [jsonld(business), jsonld(faq_jsonld(s, home_faq_pairs(src)))]
    out = fill_marker(src, "head", "\n".join(head))
    out = fill_marker(out, "header", render_header(ctx, "index", True, "#anfrage"))
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
        warn(f"Kein Inhalt für {len(missing)} Seite(n) in {content_dir.name}/ – übersprungen, im Menü trotzdem verlinkt: "
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
    if linker.pending:
        warn("Links auf Seiten, die (noch) nicht gebaut werden: " + "; ".join(
            f"{k}.html ← {', '.join(sorted(set(v)))}" for k, v in linker.pending.items()))

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
    if not args.preview:
        files["sitemap.xml"] = sitemap(site, order, today)

    out_dir.mkdir(parents=True, exist_ok=True)
    if out_dir != ROOT:
        for d in ("assets", "img"):
            if (out_dir / d).exists():
                shutil.rmtree(out_dir / d)
            shutil.copytree(ROOT / d, out_dir / d)
        shutil.copy2(ROOT / "favicon.svg", out_dir / "favicon.svg")
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
