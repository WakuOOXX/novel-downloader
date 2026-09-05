# -*- coding: utf-8 -*-
"""端到端:真实活书源 → 目录 → 3章正文 → 导出 TXT/EPUB 并校验结构"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from legado import engine, export
from pathlib import Path

KEY = sys.argv[1] if len(sys.argv) > 1 else "斗破苍穹"
URLFRAG = sys.argv[2] if len(sys.argv) > 2 else "biquge7"
srcs = engine.load_sources("bookSource.json")
cand = [s for s in srcs if URLFRAG in (s.get("bookSourceUrl") or "")
        and (s.get("searchUrl") or "").lstrip().startswith(("http://", "https://"))]
print("源:", [s["bookSourceName"] for s in cand])
s = cand[0]
print("JS关键规则:", engine.critical_js(s) or "纯规则")
hits = engine.search_sources([s], KEY)
want = [h for h in hits if h["name"] == KEY]
h = (want or hits)[0]
print("选中:", h["name"], "|", h["author"], "|", h["book_url"][:70])

toc = engine.fetch_toc(h["source"], h["book_url"])
print("目录:", len(toc), "章; 首:", toc[0][0][:40], "; 尾:", toc[-1][0][:40])

import threading
n = 3
chapters = []
for i in range(min(n, len(toc))):
    nm, cu = toc[i]
    body = engine._fetch_chapter(h["source"], cu, h["book_url"], {})
    chapters.append({"name": nm, "text": body, "error": "" if body else "empty"})
    print("  #%d %s ...(%d字)" % (i + 1, nm[:24], len(body)))

out = Path("downloads"); out.mkdir(exist_ok=True)
book = {"title": h["name"], "author": h["author"], "kind": "", "source": s["bookSourceName"],
        "book_url": h["book_url"], "chapters": chapters, "total": len(toc), "ok": sum(1 for c in chapters if c["text"])}
tp = export.export_txt(book, str(out))
ep = export.export_epub(book, str(out))
print("\nTXT:", tp, Path(tp).stat().st_size, "bytes")
print("EPUB:", ep, Path(ep).stat().st_size, "bytes")

# 校验 EPUB 结构
import zipfile, xml.dom.minidom
z = zipfile.ZipFile(ep)
names = z.namelist()
assert names[0] == "mimetype" and z.read("mimetype") == b"application/epub+zip", "mimetype 异常"
xml.dom.minidom.parseString(z.read("META-INF/container.xml"))
xml.dom.minidom.parseString(z.read("OEBPS/content.opf"))
xml.dom.minidom.parseString(z.read("OEBPS/nav.xhtml"))
for f in names:
    if f.endswith(".xhtml") and f != "OEBPS/nav.xhtml":
        xml.dom.minidom.parseString(z.read(f))
print("EPUB 结构校验通过; 文件数:", len(names))
print("\nTXT 开头预览:\n", Path(tp).read_text(encoding="utf-8-sig")[:300])
