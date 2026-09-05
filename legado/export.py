# -*- coding: utf-8 -*-
"""导出 TXT 与 EPUB3。"""
import html
import re
import uuid
import zipfile
from pathlib import Path

SAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_name(name: str) -> str:
    n = SAFE.sub("_", name or "未命名").strip(" .")
    return n[:80] or "未命名"


def export_txt(book, out_dir):
    title = safe_name(book["title"])
    path = Path(out_dir) / ("%s.txt" % title)
    parts = ["%s\n作者:%s\n来源书源:%s\n共 %d 章,成功 %d 章\n" %
             (book["title"], book.get("author", ""), book.get("source", ""),
              book.get("total", len(book["chapters"])), book.get("ok", 0))]
    parts.append("=" * 40)
    for ch in book["chapters"]:
        parts.append("\n%s\n\n" % ch["name"])
        parts.append(ch["text"] if ch.get("text") else ("[抓取失败%s]\n" % ch.get("error", "")))
    data = "\n".join(parts)
    path.write_text(data, encoding="utf-8-sig")
    return str(path)


def _paras(text):
    text = re.sub(r"\r\n?", "\n", text or "")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if p]


def export_epub(book, out_dir):
    title = book["title"]
    author = book.get("author", "")
    fname = safe_name(title)
    path = Path(out_dir) / ("%s.epub" % fname)
    uid = uuid.uuid4()
    chap_xhtml = []
    for i, ch in enumerate(book["chapters"]):
        fn = "chap%04d.xhtml" % (i + 1)
        t = html.escape(ch["name"] or "")
        body = "".join("<p>%s</p>" % html.escape(p) for p in _paras(ch.get("text") or ""))
        if not body:
            body = "<p>[抓取失败]</p>"
        x = ('<?xml version="1.0" encoding="utf-8"?>\n'
             '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh">\n<head>'
             '<meta charset="utf-8"/><title>%s</title>'
             '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
             '<body><h2>%s</h2>%s</body></html>' % (t, t, body))
        chap_xhtml.append((fn, x))
    manifest_items = []
    spine = []
    manifest_items.append(('nav', 'nav.xhtml', 'application/xhtml+xml', 'nav'))
    for fn, _ in chap_xhtml:
        manifest_items.append(('chapter-' + fn[:-6], fn, 'application/xhtml+xml', None))
        spine.append(fn[:-6])
    manifest_items.append(('css', 'style.css', 'text/css', None))

    mi = "".join(
        '<item id="%s" href="%s" media-type="%s"%s/>\n' % (i, h, m, ' properties="nav"' if p == "nav" else "")
        for i, h, m, p in manifest_items)
    sp = "".join('<itemref idref="%s"/>\n' % x for x in spine)
    navlis = "".join('<li><a href="%s">%s</a></li>\n' %
                     (fn, html.escape(ch["name"] or "")) for fn, _ in chap_xhtml)
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">\n'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
           '<dc:identifier id="uid">urn:uuid:%s</dc:identifier>\n'
           '<dc:title>%s</dc:title>\n'
           '<dc:language>zh-CN</dc:language>\n'
           '<dc:creator>%s</dc:creator>\n'
           '<meta property="dcterms:modified">%s</meta>\n'
           '</metadata>\n<manifest>\n%s</manifest>\n<spine>\n%s</spine>\n</package>\n'
           % (uid, html.escape(title), html.escape(author), "2026-01-01T00:00:00Z", mi, sp))
    nav = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
           '<head><meta charset="utf-8"/><title>目录</title></head><body>\n'
           '<nav epub:type="toc"><h1>%s</h1><ol>\n%s</ol></nav></body></html>\n'
           % (html.escape(title), navlis))
    css = ("body{font-family:serif;line-height:1.7;margin:5%% 6%%;}\n"
           "h2{text-align:center;}\np{text-indent:2em;margin:0.4em 0;}\n")

    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0" encoding="utf-8"?>\n'
                   '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/style.css", css)
        for fn, x in chap_xhtml:
            z.writestr("OEBPS/" + fn, x)
    return str(path)
