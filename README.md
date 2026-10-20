# T&A Abriss & Rückbau – Webseite

Webseite von T&A Abriss & Rückbau, Inh. Talal Al Saadoun, Hamburg.
Live unter https://ta-abriss-hamburg.de (GitHub Pages).

## Aufbau
- `index.html` – Startseite (von Hand gepflegt). Kopfzeile, Menü, Footer, der Umland-Satz im Einsatzgebiet und die Einbindung von CSS/JS/JSON-LD stehen zwischen den Markern `<!-- @head -->`, `<!-- @header -->`, `<!-- @umland -->`, `<!-- @footer -->` und werden vom Build ersetzt – dort nichts von Hand ändern.
- `<slug>.html` – Unterseiten (Leistungen, Bezirke, Stadtteile, Umland, Ratgeber), erzeugt aus `src/content/<slug>.json`
- `einsatzgebiet.html` – Übersicht aller Bezirke, Stadtteile und Umland-Orte, erzeugt aus `src/site.json`
- `impressum.html`, `datenschutz.html` – erzeugt aus `src/legal/*.html`
- `assets/site.css`, `assets/site.js` – gemeinsames Design und Skript aller Seiten
- `assets/fonts*` – Schriften (lokal, SIL Open Font License)
- `img/` – Fotos
- `src/site.json` – feste Seitenliste (Menü, Footer, Firmendaten)
- `src/preise.json` – Richtpreise je Leistungsseite (Anleitung im Feld `hinweis`); ohne Zahlen erscheint kein Preis-Abschnitt
- `src/build.py` – Generator (Python 3, nur Standardbibliothek)
- `src/test/`, `src/test2/` – Testinhalte für die Vorlage (`test2` mit Stadtteil- und Umland-Seite)
- `robots.txt`, `sitemap.xml` – für Google (Sitemap erzeugt der Build)

## Bauen
```sh
python3 src/build.py                                   # Website im Repo bauen
python3 src/build.py --out /tmp/vorschau --preview     # komplette Vorschau mit Hinweisbalken
python3 src/build.py --content src/test --out /tmp/vorschau --preview   # Vorlage mit Testinhalten
```
Der Build prüft die Inhalte (Pflichtfelder, erlaubte HTML-Tags `p ul ol li strong em h3 a`, interne Links) und bricht bei Fehlern ab, ohne etwas zu schreiben. Fehlt für eine Seite aus `src/site.json` die JSON-Datei, wird sie übersprungen (Warnung) und nirgends verlinkt: nicht in Menü, Footer, Chips, Übersicht und Sitemap; Links im Text anderer Seiten werden zu reinem Text.

Änderungen an `main` gehen automatisch online – vorher bauen und die Vorschau ansehen.
