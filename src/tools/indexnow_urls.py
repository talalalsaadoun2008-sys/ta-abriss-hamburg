"""IndexNow: neue Seiten sofort an Bing (und Yandex, Seznam, Naver) melden.

Aufruf:  python3 src/tools/indexnow_urls.py [--seit JJJJ-MM-TT] [--alle]
  --seit  Ortsseiten, die ab diesem Tag live gegangen sind (Standard: heute)
  --alle  alle URLs aus sitemap.xml

Ausgabe: JSON {"key", "keyLocation", "urls": [...], "js": "..."}
"js" ist ein fertiges Stück JavaScript für den Browser auf dem MacBook
(Claude-Browser, Seite https://ta-abriss-hamburg.de/ offen): Es meldet jede URL
einzeln per GET an https://api.indexnow.org/indexnow (mode "no-cors", Antwort
nicht lesbar). Kontrolle danach in den Bing Webmaster Tools unter „IndexNow“.

Aus dem Cloud-Container und der Mac-Shell ist api.indexnow.org gesperrt (Proxy 403),
deshalb läuft das Melden über den Browser.
Die Schlüsseldatei liegt im Website-Hauptordner: <KEY>.txt (Inhalt = KEY).
"""
import json, re, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://ta-abriss-hamburg.de/"


def key():
    for p in ROOT.glob("*.txt"):
        if re.fullmatch(r"[0-9a-f]{32}", p.stem) and p.read_text().strip() == p.stem:
            return p.stem
    sys.exit("IndexNow-Schlüsseldatei fehlt im Hauptordner")


def main(argv):
    k = key()
    if "--alle" in argv:
        urls = re.findall(r"<loc>([^<]+)</loc>", (ROOT / "sitemap.xml").read_text(encoding="utf-8"))
    else:
        seit = argv[argv.index("--seit") + 1] if "--seit" in argv else datetime.date.today().isoformat()
        q = json.loads((ROOT / "src" / "orte-warteschlange.json").read_text(encoding="utf-8"))["orte"]
        urls = [f"{BASE}{o['slug']}.html" for o in q
                if o.get("status") == "live" and o.get("slug") and o.get("datum", "") >= seit]
        if urls:
            urls.append(f"{BASE}einsatzgebiet.html")
    loc = f"{BASE}{k}.txt"
    js = ("(async()=>{const u=%s;let n=0;for(const x of u){try{await fetch('https://api.indexnow.org/indexnow?url='"
          "+encodeURIComponent(x)+'&key=%s&keyLocation='+encodeURIComponent('%s'),{mode:'no-cors'});n++}catch(e){}"
          "await new Promise(r=>setTimeout(r,300))}return n+' von '+u.length+' gemeldet'})()") % (json.dumps(urls), k, loc)
    print(json.dumps({"key": k, "keyLocation": loc, "urls": urls, "js": js}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
