"""Punkte für das Radar „Einsatzgebiet“ im T&A-Leitstand.

Aufruf:  python3 src/tools/radar_punkte.py > radar.json
Danach mit ArtifactData (url des Leitstands) als Dokument leitstand/radar speichern (set, file_path=radar.json).

Liest src/site.json (Seiten, die es gibt) und src/orte-warteschlange.json (geplante Orte mit Koordinaten).
Ausgabe: {"stand": "...", "b": [[name, lat, lon], ...], "s": [...], "u": [...], "geplant": [...]}
b = Bezirke, s = Hamburger Stadtteile, u = Umland-Orte mit eigener Seite, geplant = noch offene Orte der Warteschlange.
"""
import json, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = json.loads((ROOT / "src" / "site.json").read_text(encoding="utf-8"))
QUEUE = json.loads((ROOT / "src" / "orte-warteschlange.json").read_text(encoding="utf-8"))["orte"]

# Ungefähre Mittelpunkte (nur für die Radar-Anzeige, nicht für die Website)
KOORD = {
    "Altona": (53.5511, 9.9350), "Eimsbüttel": (53.5752, 9.9536), "Hamburg-Mitte": (53.5503, 10.0006),
    "Hamburg-Nord": (53.5900, 10.0300), "Wandsbek": (53.5720, 10.0830), "Harburg": (53.4600, 9.9830),
    "Bergedorf": (53.4880, 10.2120),
    "Ottensen": (53.5530, 9.9200), "Blankenese": (53.5650, 9.8100), "Rissen": (53.5820, 9.7600),
    "Niendorf": (53.6200, 9.9500), "Schnelsen": (53.6330, 9.9200), "Eppendorf": (53.5900, 9.9850),
    "Winterhude": (53.5950, 10.0050), "Barmbek": (53.5850, 10.0450), "Wilhelmsburg": (53.5000, 10.0080),
    "Neugraben-Fischbek": (53.4750, 9.8500), "Lohbrügge": (53.5000, 10.2000), "Rahlstedt": (53.6000, 10.1550),
    "Bramfeld": (53.6150, 10.0750), "Volksdorf": (53.6500, 10.1650), "Poppenbüttel": (53.6600, 10.0850),
    "Sasel": (53.6550, 10.1100), "Billstedt": (53.5400, 10.1100), "Hamm": (53.5550, 10.0600),
    "Langenhorn": (53.6650, 10.0100), "Lokstedt": (53.6000, 9.9500), "Stellingen": (53.5900, 9.9300),
    "Bahrenfeld": (53.5650, 9.9050), "Lurup": (53.5900, 9.8750), "Osdorf": (53.5700, 9.8600),
    "Farmsen-Berne": (53.6100, 10.1200), "Jenfeld": (53.5750, 10.1350),
    "Norderstedt": (53.7050, 9.9950), "Pinneberg": (53.6560, 9.7990), "Wedel": (53.5830, 9.6980),
    "Schenefeld": (53.6030, 9.8230), "Halstenbek": (53.6330, 9.8400), "Quickborn": (53.7300, 9.9050),
    "Ahrensburg": (53.6740, 10.2390), "Bargteheide": (53.7290, 10.2650), "Reinbek": (53.5090, 10.2480),
    "Glinde": (53.5410, 10.2110), "Geesthacht": (53.4370, 10.3690), "Seevetal": (53.3880, 9.9900),
    "Buchholz in der Nordheide": (53.3270, 9.8770), "Winsen (Luhe)": (53.3570, 10.2120),
    "Buxtehude": (53.4770, 9.7000), "Stade": (53.6000, 9.4760),
}


def main():
    by_slug = {o["slug"]: o for o in QUEUE if o.get("slug")}
    out = {"stand": datetime.date.today().isoformat(), "b": [], "s": [], "u": [], "geplant": []}
    for key, grp in (("b", "bezirke"), ("s", "stadtteile"), ("u", "umland")):
        for it in SITE.get(grp, []):
            if not (ROOT / "src" / "content" / f"{it['slug']}.json").exists():
                continue
            name = it["name"]
            if name in KOORD:
                la, lo = KOORD[name]
            elif it["slug"] in by_slug and "lat" in by_slug[it["slug"]]:
                la, lo = by_slug[it["slug"]]["lat"], by_slug[it["slug"]]["lon"]
            else:
                continue
            out[key].append([name, la, lo])
    for o in QUEUE:
        if o.get("status") == "offen" and "lat" in o:
            out["geplant"].append([o["name"], o["lat"], o["lon"]])
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
