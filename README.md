# T&A Abriss & Rückbau – Webseite

Webseite von T&A Abriss & Rückbau, Inh. Talal Alsaadoun, Hamburg.
Live unter https://ta-abriss-hamburg.de (GitHub Pages).

## Aufbau
- `index.html` – Startseite (von Hand gepflegt). Kopfzeile, Menü, Footer, der Umland-Satz im Einsatzgebiet, die Ankreuzliste der Leistungen im Anfrageformular und die Einbindung von CSS/JS/JSON-LD stehen zwischen den Markern `<!-- @head -->`, `<!-- @header -->`, `<!-- @umland -->`, `<!-- @leistungswahl -->`, `<!-- @footer -->` und werden vom Build ersetzt – dort nichts von Hand ändern. Der Kontaktbereich `id="anfrage"` ist die Vorlage für das Formular auf allen Seiten.
- `<slug>.html` – Unterseiten (Leistungen, Bezirke, Stadtteile, Umland, Ratgeber), erzeugt aus `src/content/<slug>.json`
- `einsatzgebiet.html` – Übersicht aller Bezirke, Stadtteile und Umland-Orte, erzeugt aus `src/site.json`
- `impressum.html`, `datenschutz.html` – erzeugt aus `src/legal/*.html`
- `assets/site.css`, `assets/site.js` – gemeinsames Design und Skript aller Seiten
- `assets/fonts*` – Schriften (lokal, SIL Open Font License)
- `img/` – Fotos
- `src/site.json` – feste Seitenliste (Menü, Footer, Firmendaten); `kernleistungen` = Leistungskarten der Ortsseiten und Leistungen in der Fußzeile, `fusszeile_ratgeber` = Ratgeber in der Fußzeile (das Menü zeigt immer alle); `leistungen[].zusammen` = „Oft zusammen gebucht“ auf der Leistungsseite (2–4 andere Leistungen mit kurzer Frage); `formular_leistungen` (Gruppen) und `formular_unklar` = Ankreuzliste im Anfrageformular
- `kombi-pakete.html` – „Alles aus einer Hand: Kombi-Pakete“, erzeugt aus `src/content/kombi-pakete.json` (läuft als Ratgeber ohne Quellen-Pflicht, steht im Menü unter Leistungen). Jede Kombination ist ein Abschnitt mit einer nummerierten Liste der Schritte; der Build ergänzt Sprungliste und Knopf „Diese Kombination anfragen“, der die Leistungen im Formular ankreuzt
- `src/tools/rahmen_anteil.py` – misst, wie viel Text einer gebauten Seite seitenspezifisch ist; `src/tools/eingehende_links.py` – zählt, von wie vielen Seiten eine Seite verlinkt wird
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
