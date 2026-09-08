# -*- coding: utf-8 -*-
"""normalize 字段清洗与同书合并的单元测试。运行:python -m unittest discover tests"""
import unittest

from legado.normalize import (clean_author, clean_kind, clean_last_chapter,
                              clean_name, dedupe_sources, merge_hits,
                              norm_key, source_identity)


def _hit(name, author="", kind="", last="", src="源A", url="http://a/1"):
    return {"source": {"bookSourceName": src}, "name": name, "author": author,
            "kind": kind, "book_url": url, "last_chapter": last, "intro": ""}


def _src(name="源A", url="http://a.com", **kw):
    s = {"bookSourceName": name, "bookSourceUrl": url}
    s.update(kw)
    return s


class TestClean(unittest.TestCase):
    def test_name_seo_tails(self):
        self.assertEqual(clean_name("斗破苍穹TXT下载"), "斗破苍穹")
        self.assertEqual(clean_name("凡人修仙传(完结)"), "凡人修仙传")
        self.assertEqual(clean_name("斗破苍穹最新章节无弹窗"), "斗破苍穹")

    def test_name_mixed_fields(self):
        self.assertEqual(clean_name("斗破苍穹 作者:天蚕土豆 最新章节:第100章"),
                         "斗破苍穹")
        self.assertEqual(clean_name("凡人修仙传  忘语 著"), "凡人修仙传")

    def test_name_plain(self):
        self.assertEqual(clean_name("  大主宰  "), "大主宰")
        self.assertEqual(clean_name(""), "")

    def test_author(self):
        self.assertEqual(clean_author("斗破苍穹", "作者:天蚕土豆"), "天蚕土豆")
        self.assertEqual(clean_author("斗破苍穹", "天蚕土豆著"), "天蚕土豆")
        self.assertEqual(clean_author("斗破苍穹", "斗破苍穹"), "")      # 与书名同
        self.assertEqual(clean_author("斗破苍穹", "《斗破苍穹》"), "")  # 误抽书名
        self.assertEqual(clean_author("", "最新章节:第3章 xx"), "")    # 错列整行

    def test_kind(self):
        self.assertEqual(clean_kind("斗破苍穹", "分类:玄幻"), "玄幻")
        self.assertEqual(clean_kind("斗破苍穹", "玄幻"), "玄幻")
        self.assertEqual(clean_kind("斗破苍穹", "斗破苍穹"), "")
        self.assertEqual(clean_kind("斗破苍穹", "作者:天蚕土豆 最新章节:xx"), "")

    def test_last(self):
        self.assertEqual(clean_last_chapter("斗破苍穹", "第100章 大结局"),
                         "第100章 大结局")
        self.assertEqual(clean_last_chapter("斗破苍穹", "斗破苍穹第100章"),
                         "第100章")
        self.assertEqual(clean_last_chapter("斗破苍穹", "作者:天蚕土豆"), "")
        self.assertEqual(clean_last_chapter("斗破苍穹", "第1章 " + "长" * 70), "")


class TestMerge(unittest.TestCase):
    def test_norm_key(self):
        self.assertEqual(norm_key("斗破苍穹（精校版）", "天蚕土豆"),
                         norm_key("斗 破 苍 穹", "天 蚕 土 豆"))
        self.assertNotEqual(norm_key("斗破苍穹", "天蚕土豆"),
                            norm_key("斗破苍穹", "唐家三少"))

    def test_merge_same_book(self):
        hits = merge_hits([
            _hit("斗破苍穹", "天蚕土豆", kind="", last="", src="源A",
                 url="http://a/1"),
            _hit("斗 破 苍 穹（精校）", "天蚕土豆", kind="玄幻",
                 last="第100章", src="源B", url="http://b/9"),
        ])
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["_src_count"], 2)
        self.assertTrue(hits[0]["_group_first"])
        self.assertFalse(hits[1]["_group_first"])
        self.assertTrue(all(h["_group_key"] == hits[0]["_group_key"]
                            for h in hits))
        # 组内主字段回填:缺分类/章节的行获得组内非空值
        self.assertEqual(hits[0]["kind"], "玄幻")
        self.assertEqual(hits[0]["last_chapter"], "第100章")

    def test_different_author_not_merged(self):
        hits = merge_hits([
            _hit("斗破苍穹", "天蚕土豆", src="源A"),
            _hit("斗破苍穹", "唐家三少", src="源B", url="http://b/1"),
        ])
        self.assertEqual(len({h["_group_key"] for h in hits}), 2)

    def test_missing_author_wildcard(self):
        hits = merge_hits([
            _hit("斗破苍穹", "", src="源A"),
            _hit("斗破苍穹", "天蚕土豆", src="源B", url="http://b/1"),
        ])
        self.assertEqual(len({h["_group_key"] for h in hits}), 1)

    def test_group_adjacent_order(self):
        hits = merge_hits([
            _hit("书一", "甲", src="源A", url="u1"),
            _hit("书二", "乙", src="源A", url="u2"),
            _hit("书 一", "甲", src="源B", url="u3"),
        ])
        keys = [h["_group_key"] for h in hits]
        self.assertEqual(keys[0], keys[1])          # 同书相邻(合并后紧跟组首)
        self.assertNotEqual(keys[1], keys[2])


class TestDedupeSources(unittest.TestCase):
    """跨文件书源去重(dedupe_sources):同名同站去重 / 同名异站保留 / good 优先。"""

    def test_same_name_same_url_deduped(self):
        out, n = dedupe_sources([
            _src("源A", "http://a.com", _file="f1.json"),
            _src("源A", "http://a.com", _file="f2.json"),
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(n, 1)
        self.assertEqual(out[0]["_file"], "f1.json")   # 首个保留

    def test_same_name_diff_url_kept(self):
        out, n = dedupe_sources([
            _src("源A", "http://a.com"),
            _src("源A", "http://b.com"),                # 同名不同站 → 不同源
        ])
        self.assertEqual(len(out), 2)
        self.assertEqual(n, 0)

    def test_good_table_wins(self):
        out, n = dedupe_sources([
            _src("源A", "http://a.com", _file="f1.json", _from_good=False),
            _src("源A", "http://a.com", _file="f2.json", _from_good=True),
        ])
        self.assertEqual(n, 1)
        self.assertTrue(out[0]["_from_good"])           # 有效表来源顶替
        self.assertEqual(out[0]["_file"], "f2.json")


if __name__ == "__main__":
    unittest.main()
