"""Build the Alice Tran Photography site.

Pages live in src/pages/ as HTML fragments. The first line of each is a JSON
comment with page metadata:

    <!-- {"title": "...", "description": "...", "canonical": "/pricing/weddings-elopements"} -->

Tokens the builder expands:
    [[header]] [[footer]] [[booknow]] [[portfolio-tiles]]
    [[img src="home_043" alt="..." sizes="50vw" class="x" eager]]
    [[bg src="home_044"]]   -> url() of the image, for inline styles

Images come from original-site/photos (the Google Sites backup, not committed)
and are written once, as resized WebP, into img/. Identical source files share
one output, so the paper texture used in 16 places is stored once.

Run:  python tools/build.py [page ...]
"""
import hashlib
import html
import json
import re
from pathlib import Path

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PHOTOS = ROOT / "original-site" / "photos"
IMG_OUT = ROOT / "img"
SITE = "https://www.alicetranphotography.com"

WIDTHS = [640, 1280, 1920]
QUALITY = 78

_hash_to_name = {}


def _source(name):
    hits = sorted(PHOTOS.glob(name + ".*"))
    if not hits:
        raise SystemExit(f"missing photo: {name}")
    return hits[0]


def _canonical_name(name):
    """Collapse byte-identical photos onto the first name that used them."""
    src = _source(name)
    digest = hashlib.md5(src.read_bytes()).hexdigest()
    return _hash_to_name.setdefault(digest, name)


def _write_webp(name, max_w=None):
    """Return [(url, width)] for every size written for this photo."""
    name = _canonical_name(name)
    src = _source(name)
    im = Image.open(src)
    animated = getattr(im, "n_frames", 1) > 1
    widths = [w for w in WIDTHS if w < im.width] + [min(im.width, WIDTHS[-1])]
    if max_w:
        widths = [w for w in widths if w <= max_w] or [min(im.width, max_w)]
    if animated:
        widths = [min(im.width, 960)]
    out = []
    for w in sorted(set(widths)):
        dest = IMG_OUT / f"{name}-{w}.webp"
        if not dest.exists():
            h = round(im.height * w / im.width)
            if animated:
                frames, durations = [], []
                for fr in ImageSequence.Iterator(im):
                    frames.append(fr.convert("RGB").resize((w, h), Image.LANCZOS))
                    durations.append(fr.info.get("duration", 200))
                frames[0].save(dest, "WEBP", save_all=True, append_images=frames[1:],
                               duration=durations, loop=0, quality=70, method=4)
            else:
                mode = "RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB"
                im.convert(mode).resize((w, h), Image.LANCZOS).save(
                    dest, "WEBP", quality=QUALITY, method=6)
        out.append((f"/img/{dest.name}", w))
    return out, im.width, im.height


def _attrs(s):
    return dict(re.findall(r'(\w[\w-]*)="([^"]*)"', s)), set(re.findall(r'\s(\w+)(?=\s|$)', " " + re.sub(r'\w[\w-]*="[^"]*"', "", s)))


def render_img(arg):
    a, flags = _attrs(arg)
    max_w = int(a["max"]) if "max" in a else None
    sizes_list, w0, h0 = _write_webp(a["src"], max_w)
    largest = sizes_list[-1]
    h = round(h0 * largest[1] / w0)
    srcset = ", ".join(f"{u} {w}w" for u, w in sizes_list)
    cls = f' class="{a["class"]}"' if a.get("class") else ""
    loading = 'fetchpriority="high"' if "eager" in flags else 'loading="lazy" decoding="async"'
    sizes = a.get("sizes", "100vw")
    return (f'<img src="{largest[0]}" srcset="{srcset}" sizes="{sizes}" '
            f'width="{largest[1]}" height="{h}" alt="{html.escape(a.get("alt", ""))}"{cls} {loading}>')


def render_grid(arg):
    """[[grid page="home" from="31" to="42" alt="..." class="masonry"]] -> a <ul> of photos."""
    a, _ = _attrs(arg)
    cls = a.get("class", "masonry")
    sizes = a.get("sizes", "(min-width: 960px) 32vw, (min-width: 600px) 48vw, 100vw")
    items = []
    for n in range(int(a["from"]), int(a["to"]) + 1):
        name = f'{a["page"]}_{n:03d}'
        img = render_img('src="%s" alt="%s" sizes="%s"' % (name, a.get("alt", ""), sizes))
        items.append(f"  <li>{img}</li>")
    return f'<ul class="{cls}">\n' + "\n".join(items) + "\n</ul>"


def render_bg(arg):
    a, _ = _attrs(arg)
    sizes_list, _, _ = _write_webp(a["src"], int(a.get("max", 1920)))
    return sizes_list[-1][0]


def build(only=None):
    IMG_OUT.mkdir(exist_ok=True)
    favicon = IMG_OUT / "favicon.png"
    if not favicon.exists():
        Image.open(_source("home_002")).convert("RGB").resize((96, 92), Image.LANCZOS).save(favicon)
    partials = {p.stem: p.read_text(encoding="utf-8") for p in (SRC / "partials").glob("*.html")}
    layout = (SRC / "layout.html").read_text(encoding="utf-8")
    built, canonicals = [], []
    for page in sorted((SRC / "pages").rglob("*.html")):
        rel = page.relative_to(SRC / "pages").with_suffix("").as_posix()
        if only and rel not in only:
            continue
        text = page.read_text(encoding="utf-8")
        first, body = text.split("\n", 1)
        meta = json.loads(first.strip()[4:-3])
        for _ in range(2):  # partials may contain tokens of their own
            for k, v in partials.items():
                body = body.replace(f"[[{k}]]", v)
        body = re.sub(r"\[\[grid (.*?)\]\]", lambda m: render_grid(m.group(1)), body)
        body = re.sub(r"\[\[img (.*?)\]\]", lambda m: render_img(m.group(1)), body, flags=re.S)
        body = re.sub(r"\[\[bg (.*?)\]\]", lambda m: render_bg(m.group(1)), body)
        canonical = SITE + meta["canonical"]
        og_image = SITE + render_bg(f'src="{meta["og_image"]}" max="1280"')
        doc = layout
        for k, v in {
            "title": html.escape(meta["title"]),
            "description": html.escape(meta["description"]),
            "canonical": canonical,
            "og_image": og_image,
            "head_extra": meta.get("head_extra", ""),
            "body": body,
            "paper": render_bg('src="home_044" max="1280"'),
        }.items():
            doc = doc.replace("{{" + k + "}}", v)
        rel = page.relative_to(SRC / "pages").with_suffix("")
        special = {"index": "index.html", "404": "404.html"}  # GitHub Pages serves 404.html for missing URLs
        dest = ROOT / special.get(rel.as_posix(), rel / "index.html")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(doc, encoding="utf-8")
        built.append(dest.relative_to(ROOT).as_posix())
        if rel.as_posix() != "404":
            canonicals.append(canonical)
    if not only:  # a partial build would write an incomplete sitemap
        urls = "".join(f"  <url><loc>{u}</loc></url>\n" for u in sorted(canonicals))
        (ROOT / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n",
            encoding="utf-8")
    if not built:
        raise SystemExit(f"no pages matched {only}")
    leftovers = [b for b in built if "[[" in (ROOT / b).read_text(encoding="utf-8")]
    if leftovers:
        raise SystemExit(f"unexpanded tokens in {leftovers}")
    print("built:", *built, sep="\n  ")


if __name__ == "__main__":
    import sys
    # python tools/build.py                      -> every page
    # python tools/build.py pricing/tea-ceremonies faq   -> just those (paths under src/pages, no .html)
    build(sys.argv[1:] or None)
