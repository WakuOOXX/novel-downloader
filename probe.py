# -*- coding: utf-8 -*-
"""探活:在候选纯规则源上搜索一本书,把真实命中写到 probe_hits.json"""
import sys, io, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from legado import engine

KEY = sys.argv[1] if len(sys.argv) > 1 else "斗破苍穹"
srcs = engine.load_sources("bookSource.json")

def pure_ok(s):
    rs = s.get("ruleSearch") or {}
    if not (s.get("enabled", True) and s.get("searchUrl") and isinstance(rs, dict) and rs.get("bookList")):
        return False
    return not engine.critical_js(s)

tags = ("0905", "校验可用", "水幽临渊", "笔趣阁0905")
cand = [s for s in srcs if pure_ok(s) and any(t in (s.get("bookSourceGroup") or "") for t in tags)]
print("候选:", len(cand), flush=True)
t0 = time.time()
state = {"done": 0, "total": len(cand)}

def prog(done, total, msg):
    state["done"] = done
    if done % 50 == 0 or done == total:
        print("[%d/%d] %s (%.0fs)" % (done, total, msg, time.time() - t0), flush=True)

hits = engine.search_sources(cand, KEY, on_progress=prog, workers=24)
print("总命中:", len(hits), "耗时 %.0fs" % (time.time() - t0), flush=True)
seen = set()
out = []
for h in hits:
    key = (h["source"]["bookSourceName"], h["book_url"])
    if key in seen:
        continue
    seen.add(key)
    out.append({"源": h["source"]["bookSourceName"], "分组": h["source"].get("bookSourceGroup", ""),
                "书名": h["name"], "作者": h["author"], "url": h["book_url"]})
with open("probe_hits.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("去重后写入 probe_hits.json:", len(out), flush=True)
for h in out[:15]:
    print("  -", h["源"], "|", h["书名"], "|", h["作者"], "|", h["url"][:60])
