# -*- coding: utf-8 -*-
"""小说下载器 —— 桌面 GUI(输入书名 → 选书 → 导出 TXT/EPUB)。"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from legado import engine, export

if getattr(sys, "frozen", False):          # PyInstaller 打包后:资源文件放 exe 同目录
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = APP_DIR / "bookSource.json"
DEFAULT_OUT = APP_DIR / "downloads"


class App:
    def __init__(self, root):
        self.root = root
        root.title("小说下载器 · Legado书源  →  TXT / EPUB")
        root.geometry("1040x720")
        root.minsize(900, 620)

        self.q = queue.Queue()
        self.hits = []
        self.sources = []
        self.stop_search = threading.Event()
        self.stop_dl = threading.Event()
        self.busy_search = False
        self.busy_dl = False
        self._last_key = ""

        self._build_ui()
        self.root.after(120, self._drain)
        self.reload_sources(DEFAULT_SOURCE)

    # ------------------------------------------------------------- UI -------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="书源文件:").pack(side="left")
        self.var_src = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.var_src, width=40)
        e.pack(side="left", **pad)
        ttk.Button(top, text="选择…", command=self.pick_source).pack(side="left")
        ttk.Button(top, text="重新加载", command=lambda: self.reload_sources(self.var_src.get())).pack(side="left")

        row2 = ttk.Frame(self.root)
        row2.pack(fill="x", padx=8, pady=2)
        ttk.Label(row2, text="书源分组:").pack(side="left")
        self.var_group = tk.StringVar(value="全部")
        self.cmb_group = ttk.Combobox(row2, textvariable=self.var_group, width=26, state="readonly")
        self.cmb_group.pack(side="left", **pad)
        ttk.Label(row2, text="书名:").pack(side="left", padx=(14, 2))
        self.var_key = tk.StringVar()
        self.ent_key = ttk.Entry(row2, textvariable=self.var_key, width=26)
        self.ent_key.pack(side="left", **pad)
        self.ent_key.bind("<Return>", lambda ev: self.start_search())
        self.btn_search = ttk.Button(row2, text="🔍 搜索", command=self.start_search)
        self.btn_search.pack(side="left")
        self.var_fuzzy = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(row2, text="模糊搜索", variable=self.var_fuzzy)
        cb.pack(side="left", padx=(8, 0))
        self.btn_stop = ttk.Button(row2, text="停止", command=self.stop_all, state="disabled")
        self.btn_stop.pack(side="left", **pad)
        self.lbl_progress = ttk.Label(row2, text="", foreground="#555")
        self.lbl_progress.pack(side="left", padx=10)

        # 结果表
        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("name", "author", "kind", "last", "src")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        heads = {"name": ("书名", 300), "author": ("作者", 110), "kind": ("分类", 90),
                 "last": ("最新章节", 160), "src": ("书源", 160)}
        for c, (t, w) in heads.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda ev: self.start_download())
        self.lbl_hits = ttk.Label(self.root, text="未搜索", foreground="#888")
        self.lbl_hits.pack(anchor="w", padx=10)

        # 下载区
        dl = ttk.Frame(self.root)
        dl.pack(fill="x", padx=8, pady=4)
        ttk.Button(dl, text="⬇ 下载选中(导出 TXT+EPUB)", command=self.start_download).pack(side="left")
        ttk.Label(dl, text="保存到:").pack(side="left", padx=(16, 2))
        self.var_out = tk.StringVar(value=str(DEFAULT_OUT))
        ttk.Entry(dl, textvariable=self.var_out, width=34).pack(side="left")
        ttk.Button(dl, text="浏览…", command=self.pick_out).pack(side="left", **pad)
        ttk.Button(dl, text="打开目录", command=self.open_out).pack(side="left", **pad)

        self.pbar = ttk.Progressbar(self.root, mode="determinate")
        self.pbar.pack(fill="x", padx=8, pady=2)
        self.lbl_dl = ttk.Label(self.root, text="", foreground="#444")
        self.lbl_dl.pack(anchor="w", padx=10)

        logf = ttk.LabelFrame(self.root, text="运行日志")
        logf.pack(fill="both", expand=False, padx=8, pady=(2, 6))
        self.txt_log = tk.Text(logf, height=7, state="disabled", font=("Microsoft YaHei UI", 9))
        sb = ttk.Scrollbar(logf, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ------------------------------------------------------------ 动作 -------
    def log(self, s):
        self.q.put(("log", s))

    def pick_source(self):
        p = filedialog.askopenfilename(title="选择书源文件", filetypes=[("JSON", "*.json")],
                                        initialdir=str(APP_DIR))
        if p:
            self.reload_sources(p)

    def reload_sources(self, path):
        if not path or not os.path.exists(path):
            self.log("书源文件不存在: %s" % path)
            return
        try:
            self.sources = engine.load_sources(path)
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            return
        self.var_src.set(path)
        groups = ["全部"] + [g for g, _ in engine.source_groups(self.sources)]
        self.cmb_group["values"] = groups
        self.var_group.set("全部")
        self.log("已加载 %d 个书源: %s" % (len(self.sources), path))

    def pick_out(self):
        p = filedialog.askdirectory(title="选择保存目录", initialdir=str(DEFAULT_OUT))
        if p:
            self.var_out.set(p)

    def open_out(self):
        d = self.var_out.get()
        Path(d).mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(d)  # noqa
        except Exception:
            pass

    def _chosen_sources(self):
        g = self.var_group.get()
        if g == "全部":
            return self.sources
        return [s for s in self.sources if (s.get("bookSourceGroup") or "(未分组)").strip() == g]

    def start_search(self):
        key = self.var_key.get().strip()
        if not key or self.busy_search:
            return
        if not self.sources:
            messagebox.showwarning("提示", "请先加载书源文件")
            return
        self.stop_search.clear()
        self._set_busy(True)
        self.hits = []
        for it in self.tree.get_children():
            self.tree.delete(it)
        self._last_key = key
        self.lbl_hits.config(text="搜索中…")
        srcs = self._chosen_sources()
        fuzzy = self.var_fuzzy.get()
        self.log("开始搜索《%s》,分组[%s],候选 %d 源,%s" %
                 (key, self.var_group.get(), len(srcs), "模糊开启" if fuzzy else "精确模式"))
        threading.Thread(target=self._do_search, args=(key, srcs, fuzzy), daemon=True).start()

    def _do_search(self, key, srcs, fuzzy):
        def prog(done, total, msg):
            self.q.put(("sprog", "%d/%d 源 · %s" % (done, total, msg)))

        def onhit(h):
            self.q.put(("hit", h))

        try:
            hits = engine.search_sources(srcs, key, on_progress=prog, stop=self.stop_search,
                                         workers=40, on_hit=onhit, fuzzy=fuzzy)
        except Exception as e:
            self.q.put(("log", "搜索异常: %s" % e))
            hits = []
        self.q.put(("sres", (len(hits), fuzzy)))

    def _score_hit(self, h):
        """相关度:精确同名 > 键含于书名 > 书名含于键 > 字符相似度。"""
        import difflib
        n, k = h["name"] or "", self._last_key or ""
        if not k:
            return 0
        if k == n:
            return 100
        if k in n:
            return 80
        if n in k:
            return 60
        return difflib.SequenceMatcher(None, k, n).ratio() * 40

    def stop_all(self):
        self.stop_search.set()
        self.stop_dl.set()

    def _set_busy(self, b):
        self.busy_search = b
        self.btn_search.config(state="disabled" if b else "normal")
        self.btn_stop.config(state="normal" if b or self.busy_dl else "disabled")

    # 下载
    def start_download(self):
        if self.busy_dl:
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "先在结果里双击/选中一本书")
            return
        idx = int(self.tree.item(sel[0], "tags")[0]) if self.tree.item(sel[0], "tags") else 0
        hit = self.hits[idx]
        out = self.var_out.get()
        try:
            Path(out).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("目录错误", str(e))
            return
        self.stop_dl.clear()
        self.busy_dl = True
        self.btn_stop.config(state="normal")
        self.pbar.config(value=0)
        self.lbl_dl.config(text="准备下载…")
        threading.Thread(target=self._do_download, args=(hit, out), daemon=True).start()

    def _do_download(self, hit, out):
        def prog(done, total, msg):
            self.q.put(("dlprog", (done, total, msg)))

        try:
            book = engine.load_book(hit, on_progress=prog, stop=self.stop_dl, workers=10)
            if self.stop_dl.is_set():
                raise RuntimeError("已取消")
            txt = export.export_txt(book, out)
            epub = export.export_epub(book, out)
            self.q.put(("dlok", (txt, epub, book)))
        except Exception as e:
            self.q.put(("dlerr", str(e)))

    # ------------------------------------------------------- 事件泵 ----------
    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append(payload)
                elif kind == "sprog":
                    self.lbl_progress.config(text=payload)
                elif kind == "hit":
                    h = payload
                    # 增量上屏(保持引擎去重语义:同一URL只入一次)
                    if any(x["book_url"] == h["book_url"] and
                           x["source"]["bookSourceName"] == h["source"]["bookSourceName"]
                           for x in self.hits):
                        continue
                    self.hits.append(h)
                    i = len(self.hits) - 1
                    self.tree.insert("", "end",
                                     values=(h["name"], h["author"], h["kind"],
                                             h.get("last_chapter", ""),
                                             h["source"]["bookSourceName"]),
                                     tags=(str(i),))
                    self.lbl_hits.config(text="搜索中… 已返回 %d 条" % len(self.hits))
                elif kind == "sres":
                    n, fuzzy = payload
                    if fuzzy:
                        self.hits.sort(key=self._score_hit, reverse=True)
                    self._fill_results()
                    self.lbl_progress.config(text="完成")
                    self.lbl_hits.config(text="共找到 %d 条结果" % len(self.hits))
                    self.log("搜索完成,共 %d 条%s" % (len(self.hits),
                            " · 按相关度排序" if fuzzy else ""))
                    self._set_busy(False)
                elif kind == "dlprog":
                    done, total, msg = payload
                    self.pbar.config(maximum=max(total, 1), value=done)
                    self.lbl_dl.config(text="正文 %d/%d · %s" % (done, total, msg))
                elif kind == "dlok":
                    txt, epub, book = payload
                    self.busy_dl = False
                    self._set_busy(False)
                    self.pbar.config(value=self.pbar["maximum"])
                    self.lbl_dl.config(text="完成:%d/%d 章" % (book["ok"], book["total"]))
                    self.log("✔ 导出完成: %s" % txt)
                    self.log("✔ 导出完成: %s" % epub)
                    messagebox.showinfo("下载完成",
                                        "《%s》 %d/%d 章成功\n\nTXT:%s\nEPUB:%s" %
                                        (book["title"], book["ok"], book["total"], txt, epub))
                    self.open_out()
                elif kind == "dlerr":
                    self.busy_dl = False
                    self._set_busy(False)
                    self.pbar.config(value=0)
                    self.lbl_dl.config(text="失败")
                    self.log("✘ %s" % payload)
                    messagebox.showerror("下载失败", payload)
        except queue.Empty:
            pass
        self.root.after(120, self._drain)

    def _fill_results(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
        for i, h in enumerate(self.hits):
            self.tree.insert("", "end", values=(h["name"], h["author"], h["kind"],
                                                h.get("last_chapter", ""),
                                                h["source"]["bookSourceName"]),
                             tags=(str(i),))
        self.lbl_hits.config(text="共找到 %d 条结果" % len(self.hits))

    def _append(self, s):
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", s + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
