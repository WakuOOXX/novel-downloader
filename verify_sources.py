# -*- coding: utf-8 -*-
"""用 VerifyBookSource 的校验逻辑检查 Legado 书源文件,输出 good/error。

用法: python verify_sources.py [书源.json] (缺省为 bookSource.json)
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\book\_ref\xin-verify-book-source")
from book.book import book  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\book\bookdl\shuyuan\bookSource.json")
OUT = SRC.parent
STEM = "shuyuan" if SRC.stem == "shuyuan" else "bookSource"

bk = book(str(SRC))
books = bk.json_to_books()
print("总书源数: %d" % len(books), flush=True)

start = time.time()
res = bk.checkbooks(workers=64)
good, error = res["good"], res["error"]
good = bk.dedup(good)

(OUT / f"{STEM}.good.json").write_text(
    json.dumps(good, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / f"{STEM}.error.json").write_text(
    json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n有效: %d | 无效: %d | 去重移除: %d | 耗时: %.1fs" % (
    len(good), len(error), len(books) - len(good) - len(error), time.time() - start),
    flush=True)
