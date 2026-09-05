# -*- coding: utf-8 -*-
"""开发自检:用真实书源验证 搜索→目录→正文。用法:
python dev_check.py "关键词" [书源URL片段]
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from legado import engine, rules

key = sys.argv[1] if len(sys.argv) > 1 else "凡人修仙传"
urlfrag = sys.argv[2] if len(sys.argv) > 2 else "pi12345"

sources = engine.load_sources("bookSource.json")
print("加载书源:", len(sources))
filt = [s for s in sources if urlfrag in (s.get("bookSourceUrl") or "")]
print("候选源:", [s["bookSourceName"] for s in filt][:5])
if not filt:
    raise SystemExit("无匹配源")

s = filt[0]
print("测试源:", s["bookSourceName"], "|", s.get("bookSourceUrl"))
print("含JS关键规则:", engine.critical_js(s) or "无(纯规则)")

hits = engine.search_sources(filt, key)
print("搜索结果:", len(hits))
for h in hits[:8]:
    print("  -", h["name"], "|", h["author"], "|", h["book_url"][:70])

if not hits:
    raise SystemExit("搜索无结果,换关键词或源再试")

hit = hits[0]
print("\n下载测试:", hit["name"])
toc = engine.fetch_toc(hit["source"], hit["book_url"])
print("目录章节数:", len(toc))
for nm, u in toc[:5]:
    print("   *", nm, u[:70])

import threading
body = engine._fetch_chapter(hit["source"], toc[0][1], hit["book_url"], {})
print("\n首章正文前 400 字:\n", body[:400])
