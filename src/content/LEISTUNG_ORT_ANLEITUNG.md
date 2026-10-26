# Anleitung: Seiten „Leistung in einem Bezirk“ (type `leistung_ort`)

Beispiel und Vorlage für den Aufbau (nicht für den Text!): `entruempelung-hamburg-altona.json`.

## 1. Datei und Slug

- Eine Datei je Seite: `src/content/<slug>.json`. **Kein Eintrag in `src/site.json`**, der Build findet die Seite selbst.
- Slug-Regel: `<leistung ohne "-hamburg">-<bezirk ohne "abriss-">`
  - `entruempelung-hamburg` + `abriss-hamburg-altona` → `entruempelung-hamburg-altona`
  - `gruenschnitt-hecke-hamburg` + `abriss-hamburg-mitte` → `gruenschnitt-hecke-hamburg-mitte`
- Leistungen: `entruempelung-hamburg`, `gartenraeumung-hamburg`, `pflaster-entfernen-hamburg`,
  `gruenschnitt-hecke-hamburg`, `baumfaellung-hamburg` (jede Leistung aus `site.json` geht).
- Bezirke (`site.json` → `bezirke`): `abriss-hamburg-altona`, `abriss-hamburg-eimsbuettel`, `abriss-hamburg-mitte`,
  `abriss-hamburg-nord`, `abriss-hamburg-wandsbek`, `abriss-hamburg-harburg`, `abriss-hamburg-bergedorf`.
- Passen Slug, Dateiname, `leistung` und `bezirk` nicht zusammen, bricht der Build mit FEHLER ab.

## 2. Felder

Pflicht wie bei jeder Inhaltsseite, dazu `leistung`, `bezirk` und `sources`:

| Feld | Inhalt |
|---|---|
| `slug` | nach der Regel oben, gleich dem Dateinamen |
| `type` | `"leistung_ort"` |
| `leistung` | Slug der Leistung, z. B. `"gartenraeumung-hamburg"` |
| `bezirk` | Slug des Bezirks, z. B. `"abriss-hamburg-wandsbek"` |
| `menu` | z. B. `"Gartenräumung Wandsbek"` (Name fürs Formular-Tracking) |
| `title` | max. 65 Zeichen, nennt Leistung und Bezirk |
| `description` | so kurz, dass mit Häkchen-Zeile max. 160 Zeichen (etwa 105 Zeichen eigener Text) |
| `label` | z. B. `"Gartenräumung · Bezirk Wandsbek"` |
| `h1`, `lead` | h1 nennt Leistung und Bezirk |
| `facts` | genau 3 kurze Punkte |
| `image` | Bild der Leistung aus `site.json` → `leistungen[].bild` (z. B. `garten`, `pflaster`, `hecke`, `baum`, `entruempelung`) |
| `form_leistung` | Formular-Option der Leistung (`Entrümpelung`, `Gartenräumung`, `Pflaster entfernen`, `Hecke und Grünschnitt`, `Baumfällung`) |
| `form_ort` | Bezirksname wie in `site.json`, z. B. `"Wandsbek"` |
| `sections` | 3–5 Abschnitte `{h2, html}`; erlaubt: `p ul ol li strong em h3 a` |
| `faq` | 3–4 Fragen `{q, a}` |
| `sources` | Belege für jede lokale Angabe `{title, url}`, mind. 4 von mind. 3 Websites (werden nicht angezeigt) |
| `notes_for_review` | optional: offene Fragen an Talal |

Nicht verwenden: `stadtteile` (wird nicht angezeigt). Kein eigener Abschnitt mit Links auf andere Bezirke oder
Leistungen – das baut der Build automatisch (Leistungsseite, Bezirksseite, andere Bezirke derselben Leistung,
weitere Leistungen im selben Bezirk, Sitemap, llms.txt). Menü und Footer bekommen diese Seiten bewusst nicht.

## 3. Was lokal einzigartig sein muss

Jede Seite braucht echten, belegten Bezug zum Bezirk – kein Text, der mit anderem Ortsnamen überall passt:

- Stadtteile des Bezirks (Liste auf der Bezirksseite `abriss-hamburg-<bezirk>.json`, Feld `stadtteile`).
- Lokale Anlaufstellen mit Name und Adresse, z. B. Recyclinghöfe der Stadtreinigung im Bezirk
  (Liste: hamburg.de → Recyclinghöfe), zuständiges Bezirksamt, bei Bäumen die Baumschutz-Regeln.
- Typische Bau- und Wohnsituationen im Bezirk (Altbau, Großsiedlung, Einzelhäuser mit Garten, Kleingärten …),
  nur mit Beleg, **ohne erfundene Statistik**.
- Regeln, die wirklich gelten (Sperrmüll, Halteverbot, Baumschutz, Grünabfall), mit Stand-Datum, wenn es Zahlen sind.

Nicht erfinden: Preise, Jahreszahlen der Firma, Mitarbeiterzahlen, Bewertungen, Kundenbeispiele, Zertifikate,
Fahrzeiten. Belegte Arbeitsweise (darf genannt werden): kostenlose Besichtigung vor Ort oder per Video,
Rückmeldung in einem Werktag, Festpreis nach Besichtigung inkl. Abtransport und Entsorgung, auch abends und
samstags (Besichtigung werktags ab 16:30, Sa ab 9:00), besenreine Übergabe, Asbest nur durch zugelassenen
Fachbetrieb. Sitz: Dosestraße 11, 22767 Hamburg (Altona). Entrümpelung: HafenRäumer bleibt Partner für größere
Haushaltsauflösungen (`<a href="https://hafenraeumer.de" rel="nofollow">HafenRäumer</a>`).

## 4. Verbot von Textkopien

- **Keine Sätze aus anderen Bezirks-Varianten übernehmen, auch nicht mit ausgetauschtem Ortsnamen.**
  Jede Seite wird neu geschrieben, mit eigener Gliederung, eigenen Überschriften und eigenen FAQ.
- Auch keine Sätze von der Leistungsseite (`<leistung>.json`) oder der Bezirksseite abschreiben.
- Der Build warnt, wenn ein Satz ab 10 Wörtern (Ortsnamen und Zahlen ausgeblendet) gleich auf einer anderen
  leistung_ort-Seite oder auf der Leistungsseite steht. Gründlicher prüft:
  `python3 src/tools/check_ortsseite.py <slug>` (muss „ok“ melden).
- Auf Seiten für andere Bezirke nicht „im Bezirk Altona“ schreiben (der Build hält das für einen Kopierfehler);
  den Sitz lieber so nennen: „aus der Dosestraße in Altona“.

## 5. Prüfen

```
python3 src/build.py --out /tmp/vorschau --preview   # muss mit „0 Warnungen“ enden
python3 src/tools/check_ortsseite.py <slug>          # muss „ok“ melden
```

Der Build prüft u. a.: Slug-Regel, Pflichtfelder, `sources`, Länge von title/description, dass h1/title/menu/
form_ort den Bezirk nennen und h1/title die Leistung, dass h1/title/menu/label/form_ort keinen fremden Bezirk
nennen, erlaubte HTML-Tags, interne Links, Platzhalter, doppelte Wörter und Textkopien.
Links auf noch nicht vorhandene Seiten werden als reiner Text ausgegeben (mit Warnung) – also nur auf
Seiten verlinken, die es gibt.
