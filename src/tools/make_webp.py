#!/usr/bin/env python3
"""WebP-Kopien der Fotos erzeugen (nur lokal ausführen, gehört nicht zum Build).

Aufruf (im Repo-Hauptordner):
  python3 src/tools/make_webp.py               alle img/*.jpg -> img/*.webp (Qualität 75)
  python3 src/tools/make_webp.py --quality 80  andere Qualität (1–100)

Braucht Pillow (pip install Pillow). build.py selbst braucht nur die Standardbibliothek: Liegt neben
img/x.jpg eine gleich große img/x.webp, gibt es das Foto als <picture> aus (WebP, JPG als Rückfall).
Nach jedem neuen oder ersetzten Foto dieses Skript erneut ausführen und die .webp mit dem JPG committen.
Metadaten (EXIF, z. B. Kamera oder GPS) werden nicht übernommen, ein Farbprofil schon.
Qualität 75 ist auch der Standard von Googles cwebp; bei den Fotos hier ist selbst in doppelter
Vergrößerung kein Unterschied zum JPG zu sehen. Spart die WebP weniger als 5 %, bleibt es beim JPG.
"""
import argparse
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow fehlt: pip install Pillow")

ROOT = Path(__file__).resolve().parents[2]


def convert(jpg, quality):
    webp = jpg.with_suffix(".webp")
    with Image.open(jpg) as im:
        if im.getexif().get(0x0112, 1) != 1:
            return "übersprungen: JPG ist per EXIF gedreht – bitte gerade gedreht neu speichern"
        icc = im.info.get("icc_profile")
        rgb = im.convert("RGB") if im.mode != "RGB" else im
        tmp = webp.with_name(webp.name + ".tmp")
        opts = {"quality": quality, "method": 6}
        if icc:
            opts["icc_profile"] = icc
        rgb.save(tmp, "WEBP", **opts)
    old, new = jpg.stat().st_size, tmp.stat().st_size
    if new > old * 0.95:
        tmp.unlink()
        if webp.exists():
            webp.unlink()
            return f"WebP spart unter 5 % ({new:,} B) – alte {webp.name} entfernt, es bleibt beim JPG"
        return f"WebP spart unter 5 % ({new:,} B) – es bleibt beim JPG"
    os.replace(tmp, webp)
    return f"{old:>9,} B -> {new:>9,} B  (-{100 - 100 * new / old:.0f} %)  {webp.name}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Erzeugt img/*.webp aus img/*.jpg")
    ap.add_argument("--quality", type=int, default=75, help="WebP-Qualität 1–100 (Standard 75)")
    args = ap.parse_args(argv)
    if not 1 <= args.quality <= 100:
        ap.error("--quality muss zwischen 1 und 100 liegen")
    jpgs = sorted(p for p in (ROOT / "img").iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
    if not jpgs:
        print("Keine JPG-Dateien in img/")
        return 0
    for jpg in jpgs:
        print(f"{jpg.name:<45} {convert(jpg, args.quality)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
