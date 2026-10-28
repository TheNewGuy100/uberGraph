"""Rasterize SVG icons to transparent PNGs with headless Chrome (no other SVG tool is installed here).

    python tools/ue-editor/svg_to_png.py <svg_dir> <out_dir> [size=128]

Every <name>.svg becomes <out_dir>/<name>.png (size x size, transparent background). Icons are authored white so the
UMG Image tints them. Needs Chrome at the default Windows path (override with the CHROME environment variable).
"""
import os
import subprocess
import sys
import tempfile

CHROME = os.environ.get("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def rasterize(svg_path, png_path, size):
    page = ('<html><body style="margin:0;background:transparent"><img src="%s" width="%d" height="%d" '
            'style="display:block"></body></html>') % (svg_path.replace("\\", "/").join(("file:///", "")), size, size)
    with tempfile.TemporaryDirectory() as tmp:
        html = os.path.join(tmp, "icon.html")
        open(html, "w", encoding="utf-8").write(page)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--default-background-color=00000000", "--window-size=%d,%d" % (size, size),
                        "--screenshot=" + png_path, "file:///" + html.replace("\\", "/")],
                       check=True, capture_output=True, timeout=60)


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(src)):
        if name.lower().endswith(".svg"):
            target = os.path.join(out, name[:-4] + ".png")
            rasterize(os.path.abspath(os.path.join(src, name)), os.path.abspath(target), size)
            print(name, "->", target, os.path.getsize(target), "bytes")
