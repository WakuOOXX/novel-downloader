# -*- coding: utf-8 -*-
"""小说下载器 —— 桌面 GUI(输入书名 → 选书 → 导出 TXT/EPUB)。"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from legado import engine, export
from legado.normalize import merge_hits, dedupe_hits
from selpolicy import (MIN_DRAG, DOUBLE_MS, apply_click, apply_range,
                       apply_rubber, restore_filter)

try:                                       # 校验自签名站时不刷 InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings()
except Exception:
    pass

if getattr(sys, "frozen", False):          # PyInstaller 打包后:资源文件放 exe 同目录
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
SOURCE_DIR = APP_DIR / "shuyuan"           # 书源 JSON 统一放这里
DEFAULT_SOURCE = SOURCE_DIR / "bookSource.json"
DEFAULT_OUT = APP_DIR / "downloads"
STATE_FILE = APP_DIR / "sel_state.json"    # 多选/选中项记忆 + 校验原始表路径(见 _mem_*)

# 书源校验(照 VerifyBookSource 的判定:GET bookSourceUrl,200 即有效)
VERIFY_UA = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.58"}


def good_table_path(origin: Path) -> Path:
    """原始全量表对应的有效书源表:<原名>.good.json(与 verify_sources.py 输出一致)。"""
    name = origin.name
    if name.lower().endswith(".json"):
        return origin.with_name(name[:-5] + ".good.json")
    return origin.with_name(origin.stem + ".good.json")


class DownloadDialog:
    """下载方式选择弹窗:单一(自动跳过被封书源) / 合并(每本都下) + 导出格式单选。"""

    def __init__(self, parent, n, default_fmt="epub", default_mode="single"):
        self.result = None
        top = tk.Toplevel(parent)
        top.title("下载选项")
        top.transient(parent)
        top.resizable(False, False)
        top.protocol("WM_DELETE_WINDOW", self._cancel)
        self.top = top

        frm = ttk.Frame(top, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="已选中 %d 本书,请选择下载方式:" % n,
                  font=("Microsoft YaHei UI", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.mode = tk.StringVar(value=default_mode)
        ttk.Radiobutton(frm, text="下载单一",
                        variable=self.mode, value="single").grid(row=1, column=0, sticky="nw")
        ttk.Label(frm, text="按顺序探测选中的书源,自动跳过被封/需登录的,\n"
                           "只用第一本能成功下载的源,其余丢弃。",
                  foreground="#555", justify="left").grid(row=1, column=1, sticky="w")

        ttk.Radiobutton(frm, text="合并下载",
                        variable=self.mode, value="batch").grid(row=2, column=0, sticky="nw", pady=(8, 0))
        ttk.Label(frm, text="选中的每一本都下载,各自导出为独立文件。\n"
                            "被封的源会跳过并在日志中标红。",
                  foreground="#555", justify="left").grid(row=2, column=1, sticky="w", pady=(8, 0))

        ttk.Separator(frm, orient="horizontal").grid(row=3, column=0, columnspan=2,
                                                     sticky="ew", pady=12)

        ttk.Label(frm, text="导出格式(二选一):").grid(row=4, column=0, columnspan=2, sticky="w")
        self.fmt = tk.StringVar(value=default_fmt)
        ttk.Radiobutton(frm, text="EPUB", variable=self.fmt, value="epub").grid(
            row=5, column=0, sticky="w", padx=(12, 0))
        ttk.Radiobutton(frm, text="TXT", variable=self.fmt, value="txt").grid(
            row=5, column=1, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="取消", command=self._cancel, width=8).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="开始下载", command=self._ok, width=10).pack(side="right")

        top.update_idletasks()
        w, h = top.winfo_width(), top.winfo_height()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        top.geometry("+%d+%d" % (max(x, 0), max(y, 0)))
        top.grab_set()
        top.focus_force()
        parent.wait_window(top)

    def _ok(self):
        self.result = (self.mode.get(), self.fmt.get())
        self.top.destroy()

    def _cancel(self):
        self.result = None
        self.top.destroy()


class App:
    def __init__(self, root):
        self.root = root
        root.title("小说下载器 · Legado书源  →  TXT / EPUB")
        root.geometry("1040x720")
        root.minsize(900, 620)

        self.q = queue.Queue()
        self.hits = []
        self._gtag = {}                # 同书分组 → 底色交替序号(见 _insert_hit_row)
        self.sources = []              # 工作书源(搜索/下载用)= 勾选文件合并后的源列表
        self.checked_files = []        # 勾选的书源文件名(相对 shuyuan/,保序,重启不丢)
        self.verify_dones = {}         # {文件名: {"origin": 路径, "time": 完成时刻}}
                                       # ——每文件一条;只有本程序校验跑完生成的 good 表才采用
        self.verify_origin = ""        # 旧单文件字段:仅供一次性迁移读取,不再新增语义
        self.verify_done = {}
        self.stop_search = threading.Event()
        self.stop_dl = threading.Event()
        self.stop_verify = threading.Event()
        self.busy_search = False
        self.busy_dl = False
        self.busy_verify = False
        self._last_key = ""
        # —— 运行记忆:先读盘,勾选/取消/选项都持久,重启原样恢复(见 _mem_*)——
        mem = self._mem_load()
        self.verify_origin = mem.get("verify_origin") or ""
        self.verify_done = mem.get("verify_done") or {}
        # 勾选文件清单:记忆里有就用(含空 = 用户全不选);无字段(旧记忆/全新)→ 迁移或默认
        checked = mem.get("sources")
        self.checked_files = list(checked) if checked is not None else \
            ([Path(self.verify_origin).name] if self.verify_origin
             else [DEFAULT_SOURCE.name])
        self.verify_dones = dict(mem.get("verify_dones") or {})
        self._mem_last = mem       # 记忆缓存(含 selected key 列表)

        # 顶部勾选框 + 下载弹窗选项:默认值 = 上次记忆(取消过的保持取消);
        # 挂 trace 后任一勾选变化都立即写盘,不会再"回到默认勾上"。
        self.var_fuzzy = tk.BooleanVar(value=bool(mem.get("fuzzy", True)))
        self.var_rel = tk.BooleanVar(value=bool(mem.get("rel", True)))
        self.var_fmt = tk.StringVar(value=mem.get("fmt") or "epub")      # epub / txt
        self.var_mode = tk.StringVar(value=mem.get("mode") or "single")  # single / batch
        for _v in (self.var_fuzzy, self.var_rel, self.var_fmt, self.var_mode):
            _v.trace_add("write", self._mem_save_opts)

        # —— 多选交互状态(资源管理器式,常开;见 MultiSelect 相关方法)——
        self._drag = None          # 进行中的橡皮筋状态 dict 或 None
        self._press = None         # 左键按下信息
        self._last_click = None    # 上次单击信息,用于双击判定

        self._build_ui()
        self._anchor = None        # Shift 连续选锚点行(资源管理器语义)
        self.root.after(120, self._drain)
        self._reload_all()
        self._restore_pending = bool(mem.get("selected"))   # 搜索结果到达后尝试恢复

    # ------------------------------------------------------------- UI -------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="书源文件:").pack(side="left")
        self._src_menu_vars = {}     # 文件名 → tk.BooleanVar(菜单勾选用,每次重建菜单刷新)
        self.mb_src = ttk.Menubutton(top, text="选择…", width=26)
        self.mb_src.pack(side="left", **pad)
        self.src_menu = tk.Menu(self.mb_src, tearoff=0)
        self.mb_src["menu"] = self.src_menu
        self._src_menu_dirty = True  # 下次弹出前需重扫目录
        self.src_menu.bind("<Map>", lambda e: self._menu_populate())
        ttk.Button(top, text="打开目录", command=self._open_src_dir).pack(side="left")
        self.btn_verify = ttk.Button(top, text="✔ 校验书源", command=self.start_verify)
        self.btn_verify.pack(side="left")
        self.lbl_verify = ttk.Label(top, text="", foreground="#555")
        self.lbl_verify.pack(side="left", padx=(6, 0))

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
        cb = ttk.Checkbutton(row2, text="模糊搜索", variable=self.var_fuzzy)
        cb.pack(side="left", padx=(8, 0))
        ttk.Checkbutton(row2, text="只看相关结果", variable=self.var_rel).pack(side="left", padx=(8, 0))
        self.btn_stop = ttk.Button(row2, text="停止", command=self.stop_all, state="disabled")
        self.btn_stop.pack(side="left", **pad)
        self.lbl_progress = ttk.Label(row2, text="", foreground="#555")
        self.lbl_progress.pack(side="left", padx=10)

        # 结果表:普通 tree + 滚动条(tree 持鼠标捕获,橡皮筋选框为拖动时临时 Toplevel)
        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("name", "author", "kind", "last", "src")
        # 选择全部由 self._apply_selection 维护,selectmode 恒 extended
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        heads = {"name": ("书名", 300), "author": ("作者", 110), "kind": ("分类", 90),
                 "last": ("最新章节", 160), "src": ("书源", 160)}
        for c, (t, w) in heads.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda ev: self._sync_sel_label())  # 键盘增选时同步计数
        self.tree.tag_configure("blocked", foreground="#b00020")   # 被封/失败的源标红
        # 同书分组底色:相邻组交替,一眼看出哪些行是同一本书
        self.tree.tag_configure("grp1", background="#eef4fb")
        self.tree.tag_configure("grp2", background="#ffffff")
        # 移除 Treeview 类级绑定(其内置"单击替换选择/拖拽行选"会与自定义交互冲突),
        # 滚轮与方向键等必要行为由下方自行接管。
        try:
            self.tree.bindtags((str(self.tree), ".", "all"))
        except Exception:
            pass
        self.tree.bind("<MouseWheel>", self._ms_wheel)
        self.tree.bind("<Button-4>", lambda e: self._ms_wheel_scroll(e, 1))
        self.tree.bind("<Button-5>", lambda e: self._ms_wheel_scroll(e, -1))
        self.tree.bind("<KeyRelease>", self._on_key_nav)
        self.tree.bind("<ButtonPress-1>", self._ms_press)
        self.tree.bind("<B1-Motion>", self._ms_motion)
        self.tree.bind("<ButtonRelease-1>", self._ms_release)
        self.tree.bind("<Button-3>", self._ms_right)
        self.root.bind("<Escape>", lambda e: self._ms_escape())
        self.idx2iid = {}                                          # hits 下标 -> 行 id
        self._rubber_top = None                                    # 橡皮筋半透明层(临时)
        self.lbl_hits = ttk.Label(self.root, text="未搜索", foreground="#888")
        self.lbl_hits.pack(anchor="w", padx=10)

        # 选择辅助(多选模式下全部可用;单选模式下 全选/反选 置灰)
        selbar = ttk.Frame(self.root)
        selbar.pack(fill="x", padx=8, pady=(0, 2))
        self.btn_sel_all = ttk.Button(selbar, text="全选", command=self.sel_all, width=7)
        self.btn_sel_all.pack(side="left")
        self.btn_sel_inv = ttk.Button(selbar, text="反选", command=self.sel_invert, width=7)
        self.btn_sel_inv.pack(side="left", padx=4)
        self.btn_sel_none = ttk.Button(selbar, text="清空选择", command=self.sel_none, width=9)
        self.btn_sel_none.pack(side="left")
        ttk.Button(selbar, text="清除记忆", command=self._mem_clear, width=9).pack(side="left", padx=4)
        self.lbl_sel = ttk.Label(selbar, text="已选 0 本", foreground="#0066cc")
        self.lbl_sel.pack(side="left", padx=12)
        self.lbl_sel_hint = ttk.Label(
            selbar,
            text="单击=单选 · Ctrl+单击=增减 · Shift+单击=连续选 · 按住拖动=框选(Shift=追加) · Esc 取消",
            foreground="#888")
        self.lbl_sel_hint.pack(side="left")

        # 下载区
        dl = ttk.Frame(self.root)
        dl.pack(fill="x", padx=8, pady=4)
        self.btn_dl = ttk.Button(dl, text="⬇ 下载选中", command=self.start_download)
        self.btn_dl.pack(side="left")
        ttk.Label(dl, text="保存到:").pack(side="left", padx=(16, 2))
        self.var_out = tk.StringVar(value=str(DEFAULT_OUT))
        ttk.Entry(dl, textvariable=self.var_out, width=34).pack(side="left")
        ttk.Button(dl, text="浏览…", command=self.pick_out).pack(side="left", **pad)
        ttk.Button(dl, text="打开目录", command=self.open_out).pack(side="left", **pad)

        self.pbar = ttk.Progressbar(self.root, mode="determinate")
        self.pbar.pack(fill="x", padx=8, pady=2)
        self.lbl_dl = ttk.Label(self.root, text="", foreground="#444")
        self.lbl_dl.pack(anchor="w", padx=10)
        self.lbl_tick = ttk.Label(self.root, text="", foreground="#888")
        self.lbl_tick.pack(anchor="w", padx=10)

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

    def _menu_populate(self):
        """重扫 shuyuan/ 勾选文件菜单(只列原始表,过滤校验产物)。"""
        try:
            self.src_menu.delete(0, "end")
        except Exception:
            pass
        self._src_menu_vars.clear()
        try:
            src_dir = SOURCE_DIR
            all_json = sorted(f.name for f in src_dir.iterdir()
                              if f.suffix == ".json"
                              and not f.name.endswith((".good.json", ".error.json")))
        except Exception:
            all_json = []
        # 全选 / 全不选
        self.src_menu.add_command(label="全选", command=self._src_select_all)
        self.src_menu.add_command(label="全不选", command=self._src_select_none)
        self.src_menu.add_separator()
        for fn in all_json:
            var = tk.BooleanVar(value=(fn in self.checked_files))
            missing = not (SOURCE_DIR / fn).exists()
            label = ("⚠ %s(缺失)" % fn) if missing else fn
            self.src_menu.add_checkbutton(
                label=label, variable=var,
                command=lambda f=fn, v=var: self._toggle_file(f, v))
            self._src_menu_vars[fn] = var
        # 记忆里勾了但目录里已删的文件:显示并标红(不自动改勾选)
        for fn in list(self.checked_files):
            if fn not in self._src_menu_vars:
                var = tk.BooleanVar(value=True)
                self.src_menu.add_checkbutton(
                    label="⚠ %s(缺失)" % fn, variable=var,
                    command=lambda f=fn, v=var: self._toggle_file(f, v))
                self._src_menu_vars[fn] = var
        self.src_menu.add_separator()
        self.src_menu.add_command(label="选择其他文件…", command=self._pick_other_source)
        self._update_mb_text()

    def _update_mb_text(self):
        n = len(self.checked_files)
        self.mb_src.config(text="已勾选 %d" % n if n else "请选择")

    def _toggle_file(self, fn, var):
        if var.get():
            if fn not in self.checked_files:
                self.checked_files.append(fn)
        else:
            try:
                self.checked_files.remove(fn)
            except ValueError:
                pass
        self._reload_all()

    def _src_select_all(self):
        for fn, var in self._src_menu_vars.items():
            var.set(True)
            if fn not in self.checked_files:
                self.checked_files.append(fn)
        self._reload_all()

    def _src_select_none(self):
        for var in self._src_menu_vars.values():
            var.set(False)
        self.checked_files.clear()
        self._reload_all()

    def _pick_other_source(self):
        """选择 JSON 文件 → 复制进 SOURCE_DIR/ → 自动勾选。"""
        p = filedialog.askopenfilename(title="选择书源 JSON 文件",
                                       filetypes=[("JSON", "*.json")],
                                       initialdir=str(SOURCE_DIR))
        if not p:
            return
        src = Path(p)
        dest = SOURCE_DIR / src.name
        if src.resolve() != dest.resolve():
            try:
                import shutil
                shutil.copy2(str(src), str(dest))
                self.log("已复制 %s → %s" % (src.name, dest))
            except Exception as e:
                messagebox.showerror("复制失败", str(e))
                return
        if src.name not in self.checked_files:
            self.checked_files.append(src.name)
        self._src_menu_dirty = True
        self._reload_all()

    def _open_src_dir(self):
        SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(SOURCE_DIR))
        except Exception:
            pass

    @staticmethod
    def _fmt_time(t):
        try:
            return time.strftime("%m-%d %H:%M", time.localtime(float(t)))
        except Exception:
            return "?"

    def _set_groups(self):
        groups = ["全部"] + [g for g, _ in engine.source_groups(self.sources)]
        self.cmb_group["values"] = groups
        if self.var_group.get() not in groups:
            self.var_group.set("全部")

    def _reload_all(self):
        """按勾选文件清单(shuyuan/ 下)逐文件加载并合并成工作源 self.sources。

        good 信任逐文件独立判定:verify_dones[文件名].origin 匹配该文件当前路径
        且其 .good.json 存在 → 搜索/下载用 good 表;否则该文件用全量表
        (外部/旧表不自动采用)。缺失/读取失败的文件保留勾选,跳过并日志提示。
        """
        merged, n_good = [], 0
        for fn in self.checked_files:
            p = SOURCE_DIR / fn
            if not p.exists():
                self.log("⚠ 书源文件缺失,已跳过(勾选保留): %s" % fn)
                continue
            try:
                srcs = engine.load_sources(str(p))
            except Exception as e:
                self.log("✘ 书源文件读取失败,已跳过: %s(%s)" % (fn, e))
                continue
            done = self.verify_dones.get(fn) or {}
            good = good_table_path(p)
            use = srcs
            if done.get("origin") == str(p) and good.exists():
                try:
                    use = engine.load_sources(str(good))
                    n_good += 1
                    self.log("已加载 %s:有效表 %s(%d 源 · 校验于 %s)"
                             % (fn, good.name, len(use),
                                self._fmt_time(done.get("time"))))
                except Exception:
                    use = srcs
                    self.log("有效表 %s 读取失败,%s 暂用全量 %d 源。"
                             % (good.name, fn, len(srcs)))
            else:
                hint = ("发现旧有效表 %s(非本程序校验生成),未采用" % good.name) \
                    if good.exists() else "尚无有效表,可点\"校验书源\"生成"
                self.log("已加载 %s:全量 %d 源(%s)" % (fn, len(srcs), hint))
            for s in use:
                s["_file"] = fn                     # 运行时归属标记,不写回书源 JSON
            merged.extend(use)
        self.sources = merged
        if self.checked_files and merged:
            self.log("合并工作源 %d 个(勾选 %d 文件 · %d 个用有效表)。"
                     % (len(merged), len(self.checked_files), n_good))
            if len(merged) > 5000:
                self.log("⚠ 合并源数较大(%d),建议先\"校验书源\"再搜索。" % len(merged))
        elif self.checked_files:
            self.log("⚠ 勾选的 %d 个文件都没有可用书源。" % len(self.checked_files))
        else:
            self.log("未勾选任何书源文件;在\"书源文件\"下拉中勾选后自动加载。")
        self._set_groups()
        self.lbl_verify.config(text="勾选 %d 文件 · 合并 %d 源"
                               % (len(self.checked_files), len(merged)))
        self._update_mb_text()
        self._mem_save_core()

    # --------------------------------------------------------- 书源校验 -----
    # 多文件按序校验:每个勾选的原始表独立 64 并发探测 → 各自写 .good.json;
    # 停止 = 当前文件中止 + 后续不再开始(已完成的 good 表保留)。
    # 照 xin-verify-book-source 的判定:并发 GET bookSourceUrl,200 即有效。
    def _check_one(self, s):
        if self.stop_verify.is_set():
            return None                                          # None = 中止未检测
        url = (s.get("bookSourceUrl") or "").strip()
        if not url:
            return False
        try:
            r = requests.get(url, headers=VERIFY_UA, timeout=5,
                             verify=False, allow_redirects=True)
            return r.status_code == 200
        except Exception:
            return False

    def start_verify(self):
        if self.busy_verify or self.busy_search or self.busy_dl:
            return
        # 收集勾选且存在的原始表
        files = []
        for fn in self.checked_files:
            p = SOURCE_DIR / fn
            if p.exists():
                files.append((fn, p))
            else:
                self.log("⚠ 校验跳过缺失文件: %s" % fn)
        if not files:
            messagebox.showwarning("提示", "没有可校验的书源文件。"
                                           "请先在\"书源文件\"下拉中勾选。")
            return
        self.stop_verify.clear()
        self.busy_verify = True
        self.btn_verify.config(state="disabled")
        self.btn_search.config(state="disabled")
        self.btn_dl.config(state="disabled")
        self.btn_stop.config(state="normal")
        n_files = len(files)
        self.log("开始校验 %d 个书源文件(并发 64 · 超时 5s · 只测连通性)…" % n_files)
        self.lbl_verify.config(text="校验中 · 文件 0/%d" % n_files)
        threading.Thread(target=self._do_verify, args=(files,), daemon=True).start()

    def _do_verify(self, files):
        """逐文件校验循环。files = [(filename, Path), ...]"""
        t_total = time.time()
        n_files = len(files)
        tot_ok, tot_bad = 0, 0
        aborted = False
        for fi, (fn, origin) in enumerate(files):
            if self.stop_verify.is_set():
                aborted = True
                break
            self.q.put(("vfile", (fi + 1, n_files, fn)))
            try:
                srcs = engine.load_sources(str(origin))
            except Exception as e:
                self.q.put(("log", "✘ 文件 %s 读取失败,跳过: %s" % (fn, e)))
                continue
            if not srcs:
                self.q.put(("log", "⚠ 文件 %s 无书源,跳过。" % fn))
                continue
            t0 = time.time()
            results, done = [], 0
            pool = ThreadPoolExecutor(max_workers=64)
            try:
                for ok in pool.map(self._check_one, srcs):
                    results.append(ok)
                    done += 1
                    if done % 25 == 0 or done == len(srcs):
                        n_ok = sum(1 for r in results if r)
                        n_bad = sum(1 for r in results if r is False)
                        self.q.put(("vprog", (fi + 1, n_files, fn,
                                              done, len(srcs), n_ok, n_bad)))
            except Exception as e:
                self.q.put(("log", "校验异常(%s): %s" % (fn, e)))
            finally:
                pool.shutdown(wait=False)
            n_bad = sum(1 for r in results if r is False)
            n_ok = sum(1 for r in results if r)
            n_untested = sum(1 for r in results if r is None)
            elapsed = time.time() - t0
            tot_ok += n_ok
            tot_bad += n_bad
            table = good_table_path(origin)
            if n_untested:
                self.q.put(("log", "文件 %s 校验中止(未检测 %d 个)" % (fn, n_untested)))
                aborted = True
                break
            if n_ok == 0:
                self.q.put(("log", "⚠ 文件 %s 全部 %d 个源失效(耗时 %.0fs),未生成表。"
                                    % (fn, n_bad, elapsed)))
                continue
            seen, good = set(), []
            for s, r in zip(srcs, results):
                if r is not False:
                    u = (s.get("bookSourceUrl") or "").strip()
                    if u not in seen:
                        seen.add(u)
                        good.append(s)
            try:
                tmp = table.with_name(table.name + ".tmp")
                tmp.write_text(json.dumps(good, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                os.replace(tmp, table)
            except Exception as e:
                self.q.put(("log", "✘ %s 有效表写入失败: %s" % (fn, e)))
                continue
            self.q.put(("vfile_done", (fn, str(origin), n_ok, n_bad, elapsed)))
        elapsed_total = time.time() - t_total
        self.q.put(("vdone", (n_files, tot_ok, tot_bad, elapsed_total, aborted)))


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
        if not key or self.busy_search or self.busy_verify:
            return
        if not self.sources:
            messagebox.showwarning("提示", "请先加载书源文件")
            return
        self.stop_search.clear()
        self._set_busy(True)
        self.hits = []
        self._gtag = {}              # 同书分组 → 底色交替序号(见 _insert_hit_row)
        for it in self.tree.get_children():
            self.tree.delete(it)
        self.idx2iid = {}
        self._drag = None            # 清掉可能的半途框选状态
        self._press = None
        self._last_click = None
        self._sync_sel_label()
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

    def _rel_terms(self):
        """相关性判定词:关键词 + 其模糊变体(变体重试产生的结果也算相关)。"""
        k = (self._last_key or self.var_key.get() or "").strip()
        if not k:
            return []
        terms = [k] + engine.make_key_variants(k)
        return [t.lower() for t in terms if len(t) >= 2]

    def _relevant(self, h):
        """只看相关结果:书名/作者/分类/简介至少一处包含关键词或其变体。

        很多小站无视搜索词、返回热门书充数,本地不过滤就会混进无关结果。
        """
        terms = self._rel_terms()
        if not terms:
            return True
        text = " ".join((h.get("name") or "", h.get("author") or "",
                         h.get("kind") or "", h.get("intro") or "")).lower()
        return any(t in text for t in terms)

    def _score_hit(self, h):
        """相关度:书名同名/含词 > 作者含词 > 分类含词 > 简介含词 > 字符相似度。"""
        import difflib
        k = (self._last_key or "").strip()
        if not k:
            return 0
        kl = k.lower()
        name = (h.get("name") or "").lower()
        s = 0
        if kl == name:
            s += 100
        elif kl in name:
            s += 80
        else:
            for v in self._rel_terms():          # 变体命中书名也给分
                if v != kl and v in name:
                    s += 60
                    break
        if kl in (h.get("author") or "").lower():
            s += 40
        if kl in (h.get("kind") or "").lower():
            s += 25
        if kl in (h.get("intro") or "").lower():
            s += 15
        if s == 0:
            s += difflib.SequenceMatcher(None, kl, name).ratio() * 30
        return s

    def stop_all(self):
        self.stop_search.set()
        self.stop_dl.set()
        self.stop_verify.set()

    def _set_busy(self, b):
        self.busy_search = b
        self.btn_search.config(state="disabled" if b else "normal")
        self.btn_stop.config(state="normal" if b or self.busy_dl else "disabled")
        self.btn_dl.config(state="disabled" if self.busy_dl else "normal")

    # --------------------------------------------- 统一选中提交/回调 ---------
    def _hit_key(self, h):
        """条目的稳定 ID:(书源名, 详情URL)。用于记忆恢复与去重。"""
        return (h["source"].get("bookSourceName", "?"), h["book_url"])

    # --------------------------------------------- 同书分组展示/排序 ---------
    def _row_name(self, h):
        """书名列文本:组首行且同书命中多源时加"【N源】"前缀。"""
        if h.get("_group_first") and h.get("_src_count", 1) > 1:
            return "【%d源】%s" % (h["_src_count"], h["name"])
        return h["name"]

    def _insert_hit_row(self):
        """把 self.hits 末行插入表格(增量上屏与整体重建共用):
        同组行交替底色,组首行加【N源】前缀;tags[0] 恒为 hits 下标。"""
        i = len(self.hits) - 1
        h = self.hits[i]
        k = h.get("_group_key") or ("?", self._hit_key(h))
        seq = self._gtag.setdefault(k, len(self._gtag))
        tag = "grp1" if seq % 2 == 0 else "grp2"
        iid = self.tree.insert("", "end",
                               values=(self._row_name(h), h.get("author", ""),
                                       h.get("kind", ""),
                                       h.get("last_chapter", ""),
                                       h["source"]["bookSourceName"]),
                               tags=(str(i), tag))
        self.idx2iid[i] = iid

    @staticmethod
    def _completeness(h):
        """字段完整度:作者齐(+2)>分类/最新章节(+1)。组内排序用,
        完整度高的源排前,默认下载选中的质量更高。"""
        return ((2 if h.get("author") else 0) + (1 if h.get("kind") else 0)
                + (1 if h.get("last_chapter") else 0))

    def _ordered_hits(self):
        """重排 self.hits:同书组相邻;组间按组内最高相关度(相关度并列时
        保持先到先排);组内按字段完整度+相关度排前。"""
        groups, order = {}, []
        for h in self.hits:
            k = h.get("_group_key") or ("?", self._hit_key(h))
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append(h)
        for g in groups.values():
            g.sort(key=lambda x: (self._completeness(x), self._score_hit(x)),
                   reverse=True)
        order.sort(key=lambda k: max(self._score_hit(x) for x in groups[k]),
                   reverse=True)
        return [x for k in order for x in groups[k]]

    def _current_keys(self):
        """当前选中行的稳定 ID 列表(按行序)。"""
        keys = []
        for iid in self.tree.selection():
            tags = self.tree.item(iid, "tags")
            try:
                idx = int(tags[0]) if tags else None
            except Exception:
                idx = None
            if idx is not None and 0 <= idx < len(self.hits):
                keys.append(self._hit_key(self.hits[idx]))
        return keys

    def _apply_selection(self, iids, notify=True):
        """唯一写选中入口:落 Treeview → 刷新标签 → 按需通知(持久化/外部回调)。

        notify=True 表示"用户操作导致的最终状态",触发统一选中结果回调;
        框选拖动过程与程序性恢复传 notify=False,避免中间态写记忆。
        """
        iids = [i for i in iids if i in self.tree.get_children()]
        self.tree.selection_set(iids)
        self.tree.selection_remove([i for i in self.tree.get_children() if i not in iids])
        self._sync_sel_label()
        if notify:
            self._on_selection_changed(self._current_keys())

    def _on_selection_changed(self, keys):
        """统一选中结果回调(选中状态变化 → 上层)。
        当前只做记忆持久化;未来接入外部消费者在此扩展。
        """
        self._mem_save(keys)

    def _mem_load(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            # JSON 数组读回来是 list,而 _hit_key 产出 tuple;统一成 tuple 才能进集合
            sel = [tuple(k) if isinstance(k, list) else k
                   for k in (d.get("selected") or [])]
            # 勾选文件清单:无 sources 字段(旧记忆)→ 从旧 verify_origin 一次性迁移
            sources = d.get("sources")
            if sources is None:
                sources = ([Path(d["verify_origin"]).name]
                           if d.get("verify_origin") else None)
            dones = d.get("verify_dones")
            if not isinstance(dones, dict):
                dones = {}
            if sources and not dones and isinstance(d.get("verify_done"), dict) \
                    and d["verify_done"].get("origin"):
                dones = {sources[0]: d["verify_done"]}   # 旧单条校验记录 → 按文件挂
            return {"multi": True, "selected": sel,
                    "verify_origin": d.get("verify_origin") or "",
                    "verify_done": d.get("verify_done") or {},
                    "sources": [str(x) for x in sources] if sources else sources,
                    "verify_dones": dones,
                    "fuzzy": bool(d.get("fuzzy", True)),
                    "rel": bool(d.get("rel", True)),
                    "fmt": d.get("fmt") or "epub",
                    "mode": d.get("mode") or "single"}
        except Exception:
            # 无记忆/文件损坏:空选中 + 出厂默认选项。多选交互常开(单击仍是单选,无害)。
            return {"multi": True, "selected": [], "verify_origin": "",
                    "verify_done": {}, "sources": None, "verify_dones": {},
                    "fuzzy": True, "rel": True,
                    "fmt": "epub", "mode": "single"}

    def _mem_save(self, keys=None):
        """选中变化后的落盘入口(keys=None 时取当前树选中)。"""
        self._mem_flush(keys)

    def _mem_save_core(self):
        """书源状态(勾选文件/校验记录)变化后的落盘入口;只用缓存选中,
        避免启动早期空树清空记忆。"""
        if self._mem_last:
            keys = list(self._mem_last.get("selected") or [])
        else:
            keys = self._current_keys()
        self._mem_flush(keys)

    def _mem_save_opts(self, *a):
        """选项勾选变化入口(顶部两勾选框 / 下载方式 / 导出格式):即改即存。"""
        if self._mem_last:
            keys = list(self._mem_last.get("selected") or [])
        else:
            keys = self._current_keys()
        self._mem_flush(keys)

    def _mem_flush(self, keys=None):
        """统一全量写盘:选中 + 校验记录 + 选项勾选一次写齐,互不覆盖。

        keys=None 时读当前树选中;非 None(启动早期树未填充等)用给定 keys。
        """
        try:
            if keys is None:
                keys = self._current_keys()
            data = {"multi": True,
                    "selected": [[s, u] for s, u in keys],
                    "sources": list(self.checked_files),
                    "verify_dones": dict(self.verify_dones),
                    # 旧单文件字段:过渡期继续读写(commit 3 校验多文件化后停止写入)
                    "verify_origin": getattr(self, "verify_origin", ""),
                    "verify_done": getattr(self, "verify_done", {}),
                    "fuzzy": bool(self.var_fuzzy.get()),
                    "rel": bool(self.var_rel.get()),
                    "fmt": self.var_fmt.get() or "epub",
                    "mode": self.var_mode.get() or "single"}
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            self._mem_last = {"multi": True,
                              "selected": list(keys),
                              "sources": data["sources"],
                              "verify_dones": data["verify_dones"],
                              "verify_origin": data["verify_origin"],
                              "verify_done": data["verify_done"],
                              "fuzzy": data["fuzzy"],
                              "rel": data["rel"],
                              "fmt": data["fmt"],
                              "mode": data["mode"]}
        except Exception:
            pass

    def _mem_clear(self):
        """清除记忆入口:选中与勾选项(顶部/下载弹窗)一起恢复出厂并落盘。

        书源勾选回到默认单文件(bookSource.json),校验记录一并清除;
        verify_origin/verify_done 为旧字段,只保留缓存不再写入新语义。
        """
        try:
            STATE_FILE.unlink()
        except Exception:
            pass
        self.checked_files = [DEFAULT_SOURCE.name]
        self.verify_dones = {}
        self._mem_last = {"multi": True, "selected": [],
                          "sources": list(self.checked_files),
                          "verify_dones": {},
                          "verify_origin": self.verify_origin,
                          "verify_done": self.verify_done,
                          "fuzzy": True, "rel": True,
                          "fmt": "epub", "mode": "single"}
        for _v, _d in ((self.var_fuzzy, True), (self.var_rel, True),
                       (self.var_fmt, "epub"), (self.var_mode, "single")):
            try:
                _v.set(_d)         # 触发 trace → _mem_save_opts → 落盘全新状态
            except Exception:
                pass
        self._apply_selection([], notify=False)
        self._reload_all()
        messagebox.showinfo("清除记忆", "已清除保存的选中与选项状态(恢复默认)。")

    def _try_restore_selection(self):
        """搜索结果就绪后,按记忆恢复选中(容错:已不存在的条目自动跳过)。"""
        mem = self._mem_last
        if not mem or not mem.get("selected"):
            return
        avail = {self._hit_key(h) for h in self.hits}
        keep = restore_filter(mem.get("selected"), avail)
        if not keep:
            return
        by_key = {}
        for idx, iid in self.idx2iid.items():
            if 0 <= idx < len(self.hits):
                by_key[self._hit_key(self.hits[idx])] = iid
        want = [by_key[k] for k in keep if k in by_key]
        if want:
            self._apply_selection(want, notify=False)
            self.log("已按上次记忆恢复 %d 条选中" % len(want))

    # -------------------------------------------------- 框选/单击控制器 -----
    def _row_at(self, y):
        iid = self.tree.identify_row(y)
        return iid or None

    # —— 半透明橡皮筋框:拖动开始时创建一次,期间只改 geometry(性能) ——
    def _rubber_create(self):
        self._rubber_clear()
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        try:
            top.attributes("-topmost", True)
            top.attributes("-alpha", 0.25)
        except Exception:
            pass
        top.withdraw()                                  # 先隐藏,有面积再显示
        c = tk.Canvas(top, highlightthickness=0, bg="#1e80ff", bd=0)
        c.pack(fill="both", expand=True)
        # 松开/移动若落在遮罩上,同样走这里;坐标统一按"框左上角+局部偏移"换算
        c.bind("<ButtonRelease-1>", self._ms_release)
        c.bind("<B1-Motion>", self._ms_motion)
        self._rubber_top = (top, c)

    def _rubber_move(self, l, t, r, b):
        """把遮罩挪到 tree 局部坐标 (l,t)-(r,b);零面积时隐藏。"""
        if not self._rubber_top:
            return
        top = self._rubber_top[0]
        w, h = r - l, b - t
        if w < 1 or h < 1:
            try:
                top.withdraw()
            except Exception:
                pass
            return
        try:
            top.deiconify()
            top.geometry("%dx%d+%d+%d" % (w, h,
                                          self.tree.winfo_rootx() + l,
                                          self.tree.winfo_rooty() + t))
        except Exception:
            pass

    def _rubber_clear(self):
        if self._rubber_top:
            try:
                self._rubber_top[0].destroy()
            except Exception:
                pass
            self._rubber_top = None

    def _mods(self, e):
        """修饰键标记(按位读 state)。"""
        return {"ctrl": bool(e.state & 0x0004), "shift": bool(e.state & 0x0001)}

    def _ev_xy(self, e):
        """事件坐标统一为 tree 局部坐标:遮罩层事件按当前框左上角换算。"""
        try:
            if self._rubber_top and e.widget is self._rubber_top[1] and self._drag:
                l, t = self._drag["cur"][0], self._drag["cur"][1]
                return (l + e.x, t + e.y)
        except Exception:
            pass
        return (e.x, e.y)

    def _cache_rects(self):
        """拖动开始时缓存全部可见行的纵向区间,拖动中命中检测零 Tcl 调用。"""
        out = []
        for iid in self.tree.get_children():
            b = self.tree.bbox(iid)
            if b and b[3] > 0:
                out.append((iid, b[1], b[1] + b[3]))
        return out

    def _hit_rows(self, rect):
        """rect=(l,t,r,b) 与缓存行区间求交(行全宽,忽略横向)。"""
        _, t, _, b = rect
        out = set()
        for iid, y1, y2 in self._drag["rects"]:
            if y2 >= t and y1 <= b:
                out.add(iid)
        return out

    def _ms_press(self, e):
        self.tree.focus_set()
        try:
            if self.tree.identify_region(e.x, e.y) == "heading":
                return                     # 点表头:不参与选择
        except Exception:
            pass
        if self._drag:                     # 上一把没收尾的框选,先清理
            self._rubber_clear()
            self._drag = None
        row = self._row_at(e.y)
        if row:
            self.tree.focus(row)
        m = self._mods(e)
        self._press = {"x": e.x, "y": e.y, "row": row, "t": time.time(),
                       "ctrl": m["ctrl"], "shift": m["shift"]}

    def _ms_motion(self, e):
        """按住左键拖动:超过阈值进入橡皮筋框选(资源管理器式)。

        - 普通拖动:松开=只留框内(替换当前选中)。
        - Shift/Ctrl+拖动:松开=追加进现有选中。
        性能:行区间走拖动开始时的缓存,预览 ~30ms 节流,集合未变不刷 Treeview。
        """
        if not self._press:
            return
        p = self._press
        x, y = self._ev_xy(e)
        dx, dy = abs(x - p["x"]), abs(y - p["y"])
        if self._drag is None:
            if max(dx, dy) < MIN_DRAG:          # 低于阈值 → 仍是"单击",不框选
                return
            self._drag = {"x1": p["x"], "y1": p["y"],
                          "sel_before": set(self.tree.selection()),
                          "append": bool(p["shift"] or p["ctrl"]),
                          "rects": self._cache_rects(),
                          "cur": (p["x"], p["y"], p["x"], p["y"]),
                          "last_ts": 0.0, "last_sel": None}
            self._rubber_create()
            self.log("框选开始(松开确认 · %s · Esc 取消)" %
                     ("Shift/Ctrl 追加" if self._drag["append"] else "替换"))
        now = time.time()
        if now - self._drag["last_ts"] < 0.03:  # 节流:预览最多 ~33fps
            return
        self._drag["last_ts"] = now
        wv = max(self.tree.winfo_width(), 1)
        hv = max(self.tree.winfo_height(), 1)
        x2 = min(max(x, 0), wv - 1)
        y2 = min(max(y, 0), hv - 1)
        x1, y1 = self._drag["x1"], self._drag["y1"]
        rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        self._drag["cur"] = rect
        self._rubber_move(*rect)
        sel = self._hit_rows(rect)
        if p["row"]:
            sel.add(p["row"])
        final = apply_rubber(self._drag["sel_before"], sel, self._drag["append"])
        if final != self._drag["last_sel"]:     # 集合没变就不刷 Treeview
            self._drag["last_sel"] = final
            self._apply_selection(final, notify=False)

    def _ms_release(self, e):
        p = self._press
        self._press = None
        if not p:
            return
        x, y = self._ev_xy(e)
        if self._drag is not None:
            # 松开 → 框选结束:命中 = 起点行 ∪ 框内/相交行
            d = self._drag
            x1, y1 = d["x1"], d["y1"]
            x2, y2 = (x if x is not None else x1), (y if y is not None else y1)
            rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            added = self._hit_rows(rect)
            if p["row"]:
                added.add(p["row"])
            final = apply_rubber(d["sel_before"], added, d["append"])
            self._rubber_clear()
            self._drag = None
            if p["row"]:
                self._anchor = p["row"]
            self._apply_selection(final, notify=True)
            self.log("框选结束:选中 %d 本%s" % (len(final), " (追加)" if d["append"] else ""))
            return
        # —— 单击(含双击)/修饰键点击 ——
        row = p.get("row") or self._row_at(y if y is not None else -1)   # 按下位置为准
        now = time.time()
        plain = not (p["ctrl"] or p["shift"])
        lc = self._last_click
        if (plain and lc and lc["row"] == row and row and
                (now - lc["t"]) * 1000 <= DOUBLE_MS and
                max(abs(x - lc["x"]), abs(y - lc["y"])) < 10):
            # 双击(无修饰键):维持原双击语义 = 下载该行
            self._last_click = None
            self._apply_selection({row}, notify=True)
            self._anchor = row
            self.start_download()
            return
        cur = set(self.tree.selection())
        if plain:
            new = {row} if row else set()
            if row:
                self._anchor = row
        elif p["ctrl"]:
            new = apply_click(cur, True, row)      # Ctrl:逐个增减,锚点不动
        else:                                      # Shift:从锚点连续选(替换)
            if row and self._anchor:
                new = apply_range(self.tree.get_children(), self._anchor, row)
            else:
                new = {row} if row else cur
        if new != cur:
            self._apply_selection(new, notify=True)
        if plain and row:
            self._last_click = {"row": row, "x": x, "y": y, "t": now}

    def _ms_escape(self):
        """框选过程中按 Esc:取消框选,恢复拖动前的选中状态。"""
        if self._drag is None:
            return
        d = self._drag
        self._rubber_clear()
        self._drag = None
        self._press = None
        self._apply_selection(d["sel_before"], notify=True)
        self.log("已取消框选(恢复拖动前选中 %d 本)" % len(d["sel_before"]))

    def _ms_right(self, e):
        """右键:保持 tree 默认语义(上层如需右键菜单,在此扩展,不与多选冲突)。"""

    def _ms_wheel(self, e):
        try:
            self.tree.yview_scroll(int(-e.delta / 120), "units")
        except Exception:
            pass

    def _ms_wheel_scroll(self, e, step):
        try:
            self.tree.yview_scroll(step, "units")
        except Exception:
            pass

    def _on_key_nav(self, e):
        """接管 ↑/↓/Home/End/空格:单/双选模式下与鼠标策略一致。"""
        ks = e.keysym
        if ks not in ("Up", "Down", "Home", "End", "space"):
            return
        rows = self.tree.get_children()
        if not rows:
            return
        try:
            i = rows.index(self.tree.focus())
        except Exception:
            i = -1
        if ks == "Down":
            j = min(len(rows) - 1, i + 1)
        elif ks == "Up":
            j = max(0, i - 1)
        elif ks == "Home":
            j = 0
        elif ks == "End":
            j = len(rows) - 1
        else:                            # space
            row = rows[i] if 0 <= i < len(rows) else rows[0]
            cur = set(self.tree.selection())
            new = apply_click(cur, True, row)      # 空格:切换焦点行
            self.tree.focus(row)
            self.tree.see(row)
            if new != cur:
                self._apply_selection(new, notify=True)
            return "break"
        self.tree.focus(rows[j])
        self.tree.see(rows[j])
        if e.state & 0x0001:              # Shift+方向键:从锚点扩展
            base = self._anchor if self._anchor in rows else rows[j]
            new = apply_range(rows, base, rows[j])
            self._apply_selection(new, notify=True)
        elif not (e.state & 0x0004):      # 普通方向键:单选该行;Ctrl 只移焦点
            self._apply_selection({rows[j]}, notify=True)
            self._anchor = rows[j]
        return "break"

    # -------------------------------------------------- 多选辅助 -------------
    def _sel_indices(self):
        """当前选中行的 hits 下标(按表格顺序)。"""
        out = []
        for iid in self.tree.selection():
            tags = self.tree.item(iid, "tags")
            if tags:
                try:
                    out.append(int(tags[0]))
                except Exception:
                    pass
        return sorted(set(out))

    def _sync_sel_label(self):
        n = len(self._sel_indices())
        self.lbl_sel.config(text="已选 %d 本" % n)
        self.btn_dl.config(text="⬇ 下载选中(%d)" % n if n else "⬇ 下载选中")

    def sel_all(self):
        self._apply_selection(self.tree.get_children(), notify=True)

    def sel_none(self):
        self._apply_selection([], notify=True)

    def sel_invert(self):
        cur = set(self.tree.selection())
        self._apply_selection([i for i in self.tree.get_children() if i not in cur],
                              notify=True)

    # ---------------------------------------------------- 下载 ---------------
    def start_download(self):
        if self.busy_dl or self.busy_verify:
            return
        idxs = self._sel_indices()
        if not idxs:
            messagebox.showinfo("提示", "先在结果里选中一本书(拖拽/Ctrl/Shift 可多选)")
            return
        self.sel_idx = idxs
        hits = [self.hits[i] for i in idxs]
        dlg = DownloadDialog(self.root, len(hits),
                             default_fmt=self.var_fmt.get(),
                             default_mode=self.var_mode.get())
        if not dlg.result:
            return
        mode, fmt = dlg.result
        self.var_mode.set(mode)
        self.var_fmt.set(fmt)

        out = self.var_out.get()
        try:
            Path(out).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("目录错误", str(e))
            return
        self.stop_dl.clear()
        self.busy_dl = True
        self._dl_t0 = time.time()
        self._tick_last = -1
        self.lbl_tick.config(text="已用时 0s")
        self.btn_dl.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.pbar.config(value=0)
        self.lbl_dl.config(text="准备下载… %d 本 · 格式 %s" % (len(hits), fmt.upper()))
        self.log("开始下载 %d 本 · 模式[%s] · 格式[%s]" %
                 (len(hits), "下载单一" if mode == "single" else "合并下载", fmt.upper()))
        threading.Thread(target=self._do_download,
                         args=(hits, out, mode, fmt, idxs), daemon=True).start()

    def _mark_blocked(self, fail_list):
        """把下载失败(被封/需登录/空目录)的行标红,书源列加 ✖ 前缀。"""
        for idx, _nm, srcname, _reason in fail_list:
            iid = self.idx2iid.get(idx)
            if not iid or iid not in self.tree.get_children():
                continue
            vals = list(self.tree.item(iid, "values"))
            if len(vals) == 5 and not vals[4].startswith("✖"):
                vals[4] = "✖ " + vals[4]
            self.tree.item(iid, values=vals, tags=(str(idx), "blocked"))

    def _export_one(self, book, out, fmt, batch):
        """按选定格式导出单一格式。batch=True 时同名不同源自动加书源后缀,避免覆盖。"""
        ext = "txt" if fmt == "txt" else "epub"
        suffix = ""
        if batch and (Path(out) / ("%s.%s" % (export.safe_name(book["title"]), ext))).exists():
            suffix = "_" + export.safe_name(book.get("source", ""))
        if fmt == "txt":
            return export.export_txt(book, out, suffix)
        return export.export_epub(book, out, suffix)

    def _try_one(self, h, prog, out, fmt, batch):
        """探测并下载一本书。返回 (book, path) 或抛异常。被封源直接抛 RuntimeError。

        探测(目录)阶段限时:单请求 6s、总 15s——半死源快速失败,
        "下载单一"模式能尽快换下一个候选,不会长时间停在探测上。
        """
        srcname = h["source"].get("bookSourceName", "?")
        # P1 元数据补全:详情页按语义标签抽取,比搜索列表干净;失败回退搜索值。
        # 只影响导出文件的书名/作者/分类/最新章节,不影响该行选中(键=源+URL)。
        try:
            info = engine.fetch_book_info(h["source"], h["book_url"], timeout=6)
        except Exception:
            info = {}
        if info:
            for k in ("name", "author", "kind", "last_chapter"):
                if info.get(k):
                    h[k] = info[k]
            self.log("↻ 元数据已按详情页修正: [%s]《%s》" % (srcname, h["name"]))
        toc = engine.fetch_toc(h["source"], h["book_url"], stop=self.stop_dl,
                               timeout=6, deadline=time.time() + 15)
        if not toc:
            raise RuntimeError("目录为空(书源被封或需登录)")
        book = engine.load_book(h, toc=toc, on_progress=prog, stop=self.stop_dl, workers=10)
        if self.stop_dl.is_set():
            raise RuntimeError("已取消")
        if book["ok"] == 0:
            raise RuntimeError("正文 0/%d 章成功(书源被封)" % book["total"])
        path = self._export_one(book, out, fmt, batch)
        self.log("✔ 《%s》 %d/%d 章 · 源[%s] → %s" %
                 (book["title"], book["ok"], book["total"], srcname, path))
        return book, path

    def _do_download(self, hits, out, mode, fmt, hit_idx=None):
        """hit_idx:hits 各元素在 self.hits 中的真实下标(用于标红失败行)。"""
        try:
            self._do_download_inner(hits, out, mode, fmt, hit_idx)
        except Exception:
            # 下载线程的任何异常都必须可见(pythonw 下 stderr 不可见,
            # 否则表现为"永远停在准备下载")
            import traceback
            self.q.put(("log", "✘ 下载线程异常: %s" % traceback.format_exc()[-500:]))
            self.q.put(("dlerr", "下载线程异常,已终止: %s" % traceback.format_exc()[-200:]))

    def _do_download_inner(self, hits, out, mode, fmt, hit_idx=None):
        """hit_idx:hits 各元素在 self.hits 中的真实下标(用于标红失败行)。"""
        n = len(hits)
        hit_idx = hit_idx or list(range(n))

        def prog(done, total, msg):
            self.q.put(("dlprog", (done, total, msg)))

        ok_list, fail_list = [], []
        for bi, h in enumerate(hits):
            if self.stop_dl.is_set():
                break
            srcname = h["source"].get("bookSourceName", "?")
            self.q.put(("dlbook", (bi, n, h["name"], srcname,
                                   "探测目录(超时 6s,失败自动换源)…")))
            try:
                book, path = self._try_one(h, prog, out, fmt, batch=(mode == "batch"))
            except Exception as e:
                self.q.put(("log", "✘ 跳过[%s]《%s》: %s" % (srcname, h["name"], e)))
                fail_list.append((hit_idx[bi], h["name"], srcname, str(e)))
                continue              # 被封/失败 → 单一模式换下一个,合并模式继续下一本
            ok_list.append((book, path))
            self.q.put(("dlone", (book, path, bi, n)))
            if mode == "single":
                break                 # 单一模式:只保留第一本成功的,其余丢弃
        if self.stop_dl.is_set():
            self.q.put(("dlcancel", (ok_list, fail_list)))
        else:
            self.q.put(("dldone", (mode, fmt, ok_list, fail_list)))

    # ------------------------------------------------------- 事件泵 ----------
    def _drain(self):
        """UI 事件泵:任何单条事件的处理异常都不允许杀死循环——
        一旦 after 链断了,所有状态标签会永久冻结(表现为"停在准备下载")。"""
        import traceback as _tb
        try:
            while True:
                kind, payload = self.q.get_nowait()
                try:
                    self._handle_event(kind, payload)
                except Exception:
                    self._append("✘ 事件处理异常[%s]: %s" %
                                 (kind, _tb.format_exc()[-400:]))
        except queue.Empty:
            pass
        # 下载进行中的用时跳动(让"探测/正文抓取中" visibly 活着)
        if self.busy_dl and getattr(self, "_dl_t0", None):
            s = int(time.time() - self._dl_t0)
            if s != getattr(self, "_tick_last", -1):
                self._tick_last = s
                self.lbl_tick.config(text="已用时 %ds" % s)
        self.root.after(120, self._drain)

    def _handle_event(self, kind, payload):
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
                return
            if self.var_rel.get() and not self._relevant(h):
                return                                    # 无关结果不上屏
            self.hits.append(h)
            self._insert_hit_row()
            self.lbl_hits.config(text="搜索中… 已返回 %d 条" % len(self.hits))
        elif kind == "sres":
            n, fuzzy = payload
            self.hits = merge_hits(dedupe_hits(self.hits))
            self.hits = self._ordered_hits()   # 同书组相邻,组内按完整度/相关度
            self._fill_results()
            self.lbl_progress.config(text="完成")
            self.lbl_hits.config(text="共找到 %d 条结果" % len(self.hits))
            self.log("搜索完成,共 %d 条(同书已分组相邻)%s" % (len(self.hits),
                    " · 组间按相关度排序" if fuzzy else ""))
            try:                     # 恢复选中即使出错,也必须解开搜索按钮
                self._try_restore_selection()
            finally:
                self._set_busy(False)
        elif kind == "vfile":
            fi, n_files, fn = payload
            self.lbl_verify.config(text="校验中 · 文件 %d/%d · %s" % (fi, n_files, fn))
            self.log("开始校验文件 %d/%d: %s" % (fi, n_files, fn))
        elif kind == "vprog":
            fi, n_files, fn, done, total, ng, nb = payload
            self.lbl_verify.config(text="校验中 文件 %d/%d · %s · %d/%d · 有效 %d · 失效 %d"
                                   % (fi, n_files, fn, done, total, ng, nb))
        elif kind == "vfile_done":
            fn, origin, n_ok, n_bad, elapsed = payload
            now = time.time()
            self.verify_dones[fn] = {"origin": origin, "time": now}
            self._mem_save_core()
            self.log("✔ 文件 %s 校验完成:有效 %d · 失效 %d · 耗时 %.0fs"
                     % (fn, n_ok, n_bad, elapsed))
        elif kind == "vdone":
            n_files, tot_ok, tot_bad, elapsed, aborted = payload
            self.busy_verify = False
            self._set_busy(False)
            self.btn_verify.config(state="normal")
            self._reload_all()                  # good 表更新后重载合并源
            if aborted:
                self.lbl_verify.config(text="校验已中止 · 有效 %d · 失效 %d" % (tot_ok, tot_bad))
                self.log("校验已中止 · 总有效 %d · 总失效 %d · 耗时 %.0fs"
                         % (tot_ok, tot_bad, elapsed))
            else:
                self.lbl_verify.config(text="已校验 %d 文件 · 有效 %d · 失效 %d · 耗时 %.0fs"
                                       % (n_files, tot_ok, tot_bad, elapsed))
                self.log("全部校验完成: %d 文件 · 有效 %d · 失效 %d · 耗时 %.0fs"
                         % (n_files, tot_ok, tot_bad, elapsed))
        elif kind == "dlprog":
            done, total, msg = payload
            self.pbar.config(maximum=max(total, 1), value=done)
            self.lbl_dl.config(text="正文 %d/%d · %s" % (done, total, msg))
        elif kind == "dlbook":
            bi, n, name, srcname, msg = payload
            self.pbar.config(value=0)
            self.lbl_dl.config(text="第 %d/%d 本《%s》 · 源[%s] · %s" %
                               (bi + 1, n, name, srcname, msg))
        elif kind == "dlone":
            book, path, bi, n = payload
            self.log("已保存: %s" % path)
        elif kind == "dldone":
            mode, fmt, ok_list, fail_list = payload
            self.busy_dl = False
            self._set_busy(False)
            self.btn_dl.config(state="normal")
            self._mark_blocked(fail_list)
            self.lbl_tick.config(text="")
            self.pbar.config(value=self.pbar["maximum"] if ok_list else 0)
            if ok_list:
                total_ok = sum(b["ok"] for b, _ in ok_list)
                total_ch = sum(b["total"] for b, _ in ok_list)
                self.lbl_dl.config(text="完成:%d 本 · %d/%d 章" %
                                   (len(ok_list), total_ok, total_ch))
                lines = ["《%s》 %d/%d 章" % (b["title"], b["ok"], b["total"])
                         for b, _ in ok_list]
                detail = "\n".join(lines)
                if fail_list:
                    detail += "\n\n已跳过被封/失败 %d 个:\n" % len(fail_list)
                    detail += "\n".join("· [%s] %s" % (s, r)
                                        for _, _, s, r in fail_list[:8])
                self.log("下载结束:成功 %d 本,跳过 %d 个" % (len(ok_list), len(fail_list)))
                messagebox.showinfo(
                    "下载完成",
                    "成功 %d 本 · 格式 %s\n\n%s\n\n保存目录:\n%s" %
                    (len(ok_list), fmt.upper(), detail, self.var_out.get()))
                self.open_out()
            else:
                self.lbl_dl.config(text="全部失败")
                detail = "\n".join("· [%s]《%s》: %s" % (s, nm, r)
                                   for _, nm, s, r in fail_list[:10])
                self.log("✘ 全部失败:%d 个候选" % len(fail_list))
                messagebox.showerror(
                    "下载失败",
                    "选中的 %d 个候选全部不可用(被封/需登录/无目录):\n\n%s" %
                    (len(fail_list) or 1, detail or "未知原因"))
        elif kind == "dlcancel":
            ok_list, fail_list = payload
            self.busy_dl = False
            self._set_busy(False)
            self.btn_dl.config(state="normal")
            self.pbar.config(value=0)
            self.lbl_tick.config(text="")
            self.lbl_dl.config(text="已取消")
            self.log("已取消(成功 %d / 跳过 %d)" % (len(ok_list), len(fail_list)))
        elif kind == "dlerr":
            self.busy_dl = False
            self._set_busy(False)
            self.btn_dl.config(state="normal")
            self.pbar.config(value=0)
            self.lbl_tick.config(text="")
            self.lbl_dl.config(text="失败")
            self.log("✘ %s" % payload)
            messagebox.showerror("下载失败", payload)
    def _fill_results(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
        self.idx2iid = {}
        self._gtag = {}
        for _h in self.hits:
            self._insert_hit_row()
        self._sync_sel_label()
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
