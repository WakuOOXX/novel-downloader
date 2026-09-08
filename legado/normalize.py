# -*- coding: utf-8 -*-
"""字段规范化:书名/作者/分类/最新章节的统一清洗规则 + 跨源同书合并。

设计:每个字段 = 清洗链(按序) + 合法形态校验 + 错值置空——置空优于存脏,
脏值会让同书合并误拆组,GUI 上也应以"该源未提供"呈现而非乱码。

清洗模板参照 LegadoParser FormatUtils.Fmt(github.com/821938089/LegadoParser,
阅读3.0规则引擎的 Python 移植);同书合并范式参照 Legado 官方 SearchModel.kt
(github.com/gedoor/legado,按书名+作者归一化键分组)。
"""
import re

# ---------------------------------------------------------------- 书名 ----
# SEO 尾巴:循环剥离直到不再变化
_NAME_TAILS = ("TXT下载", "TXT全本", "全文阅读", "最新章节", "无弹窗",
               "免费下载", "(完结)", "（完结）", "TXT", "下载", "连载")
# 混入的后续字段标记:截断
_NAME_MARKERS = ("作者:", "作者：", "最新章节")
# Fmt.bookNameRegex 思路:"XX 著" 尾(站方把作者混进书名)
_NAME_AUTHOR_TAIL = re.compile(r"\s+\S{1,8}\s+著\s*$")


def clean_name(text):
    n = re.sub(r"&nbsp;|&ensp;|&emsp;", " ", text or "")
    n = re.sub(r"\s{2,}", " ", n).strip()
    for marker in _NAME_MARKERS:
        i = n.find(marker)
        if i > 0:
            n = n[:i].strip(" :：-—|/，,。")
    if len(n) > 4:
        n = _NAME_AUTHOR_TAIL.sub("", n).strip()
    changed = True
    while changed and len(n) > 4:
        changed = False
        for suf in _NAME_TAILS:
            if n.endswith(suf):
                n = n[:-len(suf)].strip(" :：-—|/，,。")
                changed = True
    return n


# --------------------------------------------------------------- 作者 ----
# 整行文本混入这些词,说明规则抽错列,不可救,置空
_AUTHOR_JUNK = ("分类", "作者", "最新", "章节", "字数", "点击", "更新",
                "状态", "简介", "目录")


def clean_author(name, text):
    a = re.sub(r"^\s*作\s*者\s*[:：>》\s]*", "", text or "").strip()
    a = re.sub(r"\s*[/｜|]?\s*著\s*$", "", a).strip()
    a = re.sub(r"&nbsp;|&ensp;|&emsp;", " ", a)
    a = re.sub(r"\s{2,}", " ", a).strip()
    if not a or a == name:
        return ""
    if a.startswith("《") or a.endswith("》"):     # 作者栏误抽成书名
        return ""
    if len(a) >= 6 and name and name.startswith(a):  # 作者栏误抽成书名前缀
        return ""
    if len(a) > 20 or any(m in a for m in _AUTHOR_JUNK):
        return ""
    return a


# --------------------------------------------------------------- 分类 ----
_KIND_JUNK = ("作者", "最新", "章节", "字数", "点击", "更新", "状态",
              "简介", "目录", "下载", "连载")


def clean_kind(name, text):
    k = re.sub(r"^\s*分\s*类\s*[:：>》\s]*", "", text or "").strip()
    k = re.sub(r"&nbsp;|&ensp;|&emsp;", " ", k)
    k = re.sub(r"\s{2,}", " ", k).strip()
    if not k or k == name:
        return ""
    if len(k) > 12 or any(m in k for m in _KIND_JUNK):
        return ""
    return k


# ----------------------------------------------------------- 最新章节 ----
def clean_last_chapter(name, text):
    t = re.sub(r"&nbsp;|&ensp;|&emsp;", " ", text or "")
    t = re.sub(r"\s{2,}", " ", t).strip()
    if not t:
        return ""
    if name and t.startswith(name):
        t = t[len(name):].strip(" :：-—|/，,。")
    if not t or "作者" in t or len(t) > 60:
        return ""
    return t


# ------------------------------------------------------- 同书归一化键 ----
# 括号内容(卷标/副标题/精校标记)不参与同名判定
_BRACKETS = re.compile(r"[（(【\[〔《].*?[）)】\]〕》]")
_PUNCT = re.compile(r"[\s:：\-—_|/\\·,，。、'\"“”‘’!！?？~～*★☆]+")


def _name_key(name):
    return _PUNCT.sub("", _BRACKETS.sub("", name or "")).lower()


def _author_key(author):
    return _PUNCT.sub("", author or "").lower()


def norm_key(name, author):
    """同书判定键:(归一化书名, 归一化作者)。作者缺失时作者位为空串,
    合并时视为通配(见 merge_hits)。"""
    return (_name_key(name), _author_key(author))


def merge_hits(hits):
    """跨源同书分组:同名(归一化)且作者相容 → 同组。

    - 作者通配规则:一方作者缺失视为与任何作者相容;双方都非空且不同 → 拆组。
    - 组内主字段择优:kind/last_chapter 缺失的行回填组内首个非空值
      (仅展示语义,下载仍按行自己的源取数据)。
    - 就地注记每个 hit:_group_key(组标识)/_src_count(组内源数)/
      _group_first(是否组首行);返回按组相邻排序的新列表。
    """
    groups = []                       # [{"name_key","authors","hits"}]
    by_name = {}                      # name_key -> [group, ...]
    for h in hits:
        nk = _name_key(h.get("name"))
        ak = _author_key(h.get("author"))
        target = None
        for g in by_name.get(nk, ()):
            if ak and g["authors"] and ak not in g["authors"]:
                continue              # 同名不同作者 → 不同书
            target = g
            break
        if target is None:
            target = {"name_key": nk, "authors": set(), "hits": []}
            groups.append(target)
            by_name.setdefault(nk, []).append(target)
        if ak:
            target["authors"].add(ak)
        target["hits"].append(h)

    out = []
    for gi, g in enumerate(groups):
        ghits = g["hits"]
        kind = next((x.get("kind") for x in ghits if x.get("kind")), "")
        last = next((x.get("last_chapter") for x in ghits
                     if x.get("last_chapter")), "")
        key = "g%d" % gi
        for j, x in enumerate(ghits):
            x["_group_key"] = key
            x["_src_count"] = len(ghits)
            x["_group_first"] = (j == 0)
            if kind and not x.get("kind"):
                x["kind"] = kind
                x["_filled_kind"] = True
            if last and not x.get("last_chapter"):
                x["last_chapter"] = last
                x["_filled_last"] = True
            out.append(x)
    return out


def dedupe_hits(hits):
    """同源同 URL 去重(搜索列表级)。"""
    uniq, seen = [], set()
    for h in hits:
        k = (h["source"].get("bookSourceName", "?"), h.get("book_url"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    return uniq


# ----------------------------------------------------- 跨文件书源去重 ----
def source_identity(s):
    """书源稳定身份:(书源名, 站点URL)。两字段皆空的源视为无法识别。"""
    name = (s.get("bookSourceName") or "").strip()
    url = (s.get("bookSourceUrl") or "").strip()
    return (name, url)


def dedupe_sources(sources):
    """跨文件合并重复书源(2026-09-09 拍板新增)。

    规则:按 source_identity 去重,首个保留;若后到者来自有效表
    (s["_from_good"]=True)而已保留者不是,则后者顶替(校验过的优先);
    两字段皆空的源不参与去重,原样保留。返回 (去重后列表, 去重个数)。
    """
    out, seen, n_dup = [], {}, 0
    for s in sources:
        k = source_identity(s)
        if k == ("", ""):
            out.append(s)
            continue
        prev_i = seen.get(k)
        if prev_i is None:
            seen[k] = len(out)
            out.append(s)
            continue
        n_dup += 1
        prev = out[prev_i]
        if s.get("_from_good") and not prev.get("_from_good"):
            out[prev_i] = s          # 有效表来源顶替全量表来源
            seen[k] = prev_i
    return out, n_dup
