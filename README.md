<div align="center">

# 📚 小说下载器

输入书名，聚合搜索 3393 个书源，框选批量下载，导出 EPUB 或 TXT。

Windows 桌面应用 · Python + tkinter · 自研 Legado 规则引擎

[![release](https://img.shields.io/github/v/release/WakuOOXX/novel-downloader)](https://github.com/WakuOOXX/novel-downloader/releases/latest)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.14%2B-blue)](#)
[![platform](https://img.shields.io/badge/platform-Windows-lightgrey)](#)

[🌐 项目官网](https://WakuOOXX.github.io/novel-downloader/) ·
[⬇️ 下载 Windows 版](https://github.com/WakuOOXX/novel-downloader/releases/latest) ·
[📖 技术文档](docs/技术文档.md)

</div>

---

## 目录

- [功能特性](#-功能特性)
- [界面预览](#-界面预览)
- [快速开始](#-快速开始)
- [使用指南](#-使用指南)
- [配置与数据文件](#-配置与数据文件)
- [常见问题](#-常见问题)
- [二次开发](#-二次开发)
- [免责声明](#-免责声明)

## ✨ 功能特性

搜索阶段：

- 一次搜索并发打向 3393 个书源（分组可选，共 252 个取值），结果边搜边上屏，不用等全部跑完。
- 直搜无果时自动生成关键词变体重试，只打这一轮还活着的源，结果按相关度排序。
- 依赖 JS 或登录态的书源自动跳过，不会报错中断。

选书阶段（和资源管理器同一套操作习惯）：

- 单击选一本，Ctrl 加减单个，Shift 连续选。
- 按住左键拖出蓝框，框内的行全部选中；Shift/Ctrl 加拖动则追加进已选。
- Esc 取消框选，双击直接下载这本书。
- 重开程序后自动恢复上次的选中状态，失效条目自动跳过。

下载阶段：

- 「下载单一」按顺序探测候选源，单源 15 秒封顶，被封的自动标红跳过，只留下能下全的那本。
- 「合并下载」把选中的每本都下下来，各自独立成文件。
- 导出格式 EPUB / TXT 二选一，不重复占空间。
- 正文逐章抓取，支持目录分页拼接；重名书自动加书源后缀防覆盖。

> 实现细节（并发与超时策略、规则语法兼容矩阵、EPUB 内部结构）见[技术文档](docs/技术文档.md)。

## 🖼️ 界面预览

<!-- 截图就位后取消下面的注释。建议三张：搜索结果页、拖框多选、下载方式弹窗。
     存放到 docs/assets/ 下，文件名对应改好即可。

![搜索结果页](docs/assets/screenshot-search.png)
![拖框多选](docs/assets/screenshot-rubber-select.png)
![下载方式弹窗](docs/assets/screenshot-download-dialog.png)

-->

实测记录：搜索「斗破苍穹」命中 18 条（含天蚕土豆同名书），目录 1625 章完整抓取并导出成功。交互演示见[项目官网](https://WakuOOXX.github.io/novel-downloader/)。

## 🚀 快速开始

### 方式一：免安装版（推荐）

1. 下载 [novel-downloader-v1.1.0-windows-x64.zip](https://github.com/WakuOOXX/novel-downloader/releases/latest/download/novel-downloader-v1.1.0-windows-x64.zip) 并解压；
2. 保持 `小说下载器.exe` 与 `bookSource.json` 在同一文件夹；
3. 双击 exe，输入书名开始搜索。

exe 免 Python 环境，已在 Windows 11 实测。书源包可单独替换，不用重新下载程序。首次启动需要解压，慢一两秒属正常。

### 方式二：源码运行

```bash
git clone https://github.com/WakuOOXX/novel-downloader.git
cd novel-downloader
pip install requests beautifulsoup4 lxml
python app.py        # 用 pythonw app.py 启动可免控制台窗口
```

注意：解释器必须带 tkinter，python.org 官方安装包默认包含；部分精简版 Python 没有，启动会报 `ModuleNotFoundError`。排查细节见[技术文档 §2](docs/技术文档.md)。

## 📖 使用指南

### 搜索

顶部选书源分组（想省事就选带「校验可用」字样的分组），输入关键词回车。搜索框旁有域下拉（自动/书名/作者/分类），默认「自动」：书名/作者/分类/简介任一处命中关键词即保留；选「作者」或「分类」则只保留该域命中的结果（网络仍按书名发起，该域为本地过滤）。结果边搜边上屏，随时可以点「停止」。

「只看相关结果」默认开启：很多小站无视搜索词返回热门书充数，开启后只有书名/作者/分类/简介里含关键词的结果才会显示；想看全量就把它去掉。

### 书源校验

顶部「书源文件(N)」下拉可管理多个书源 JSON 文件：点开后是**已加入清单**面板，每行文件右侧 ✕ 把它移出清单（文件保留在磁盘，随时可加回）；底部「+ 新加入书源…」直接打开系统文件选择框（多选，定位在 `shuyuan/`，不在里面的会自动复制进去）。加入即参与搜索/下载，多个文件**自动合并并去重重复书源**（同名同站保留一份，校验过的优先），日志会报合并与去重数量。点「✔ 校验书源」会对清单内全部文件逐个做连通性体检（每文件 64 并发、HTTP 200 判有效），每个文件跑完后在同目录生成有效书源表 `<文件名>.good.json`，搜索/下载只扫有效源。下次再点校验，永远是重扫原始全量表、重新生成有效表覆盖旧的。校验中途点「停止」则当前文件作废、已完成文件的 good 表保留。

### 选书

| 操作 | 效果 |
|---|---|
| 单击 | 选中那一本（自动取消其它） |
| Ctrl + 单击 | 加入或移出已选 |
| Shift + 单击 | 从上次点到的行连续选到这里 |
| 按住左键拖动 | 框选：与蓝框相交的行全部选中 |
| Shift / Ctrl + 拖动 | 框选结果追加进已选 |
| Esc | 取消正在拖的框选 |
| 双击 | 直接下载这本书 |
| 点击空白处 | 清空选中 |

顶部还有「全选 / 反选 / 清空选择 / 清除记忆」按钮。上次关程序时选中的书，下次搜到会自动恢复勾选。

### 下载

点「⬇ 下载选中」后弹窗，两处选择：

| 选项 | 值 | 行为 |
|---|---|---|
| 下载方式 | 下载单一 | 按顺序探测候选源（单请求 6 秒、单源 15 秒封顶），被封的标红跳过，只下第一本能下全的 |
| 下载方式 | 合并下载 | 选中的每本都试一遍，各自独立成文件 |
| 导出格式 | EPUB / TXT | 二选一，只生成所选格式 |

下载过程中状态行显示当前候选和已用时；结束后弹出结果汇总，失败的源在表格里保持标红，下次一眼避开。

## ⚙️ 配置与数据文件

| 文件 / 目录 | 说明 |
|---|---|
| `shuyuan/bookSource.json` | 原始全量书源包（开源阅读格式，18.6MB / 3393 源），校验专用，可单独替换更新 |
| `shuyuan/bookSource.good.json` | 有效书源表（点「校验书源」跑完自动生成/覆盖），搜索/下载实际使用的表 |
| `shuyuan/*.json` | 放入多个书源 JSON，「书源文件」下拉里「+ 新加入书源…」加入清单后合并搜索（自动去重重复源） |
| `sel_state.json` | 记忆文件：选中的书 ID + 勾选文件列表 + 每文件校验记录 + 选项（模糊/域/格式等）。删掉即重置 |
| `downloads/` | 下载输出目录，可在界面里改 |
| `docs/` | 项目官网源码（GitHub Pages） |

书源勾选、分组、关键词、搜索域、输出目录都会在程序内记住，不用每次重设。

## ❓ 常见问题

**搜出来 0 条？**
优先换分组（带「校验可用」字样的分组存活率最高），再打开「模糊搜索」让它换词重试。书源本身死亡率就高，这是所有聚合下载器的共同处境。

**下载时大量 `[抓取失败]`？**
站点限流或章节页反爬。等几分钟重试，或者换一个源的同一本书。

**提示「目录为空」「该源正文规则依赖 JS」？**
这个源用不了，程序会自动换下一个候选，不用管。

**双击 exe 没反应或冷启动很慢？**
`--onefile` 打包的 exe 首次启动要解压到临时目录，慢一两秒正常。确认杀毒软件没有拦截。

**源码启动报 `ModuleNotFoundError: tkinter`？**
换官方安装的 Python（默认带 tkinter），再 `pip install requests beautifulsoup4 lxml`。

更多排查项见[技术文档 §11](docs/技术文档.md)。

## 🧩 二次开发

仓库里只有运行所需的代码。规则引擎、导出、交互层的实现说明都在[技术文档](docs/技术文档.md)：

- [§6 规则 DSL 引擎](docs/技术文档.md)：支持与不支持的语法清单
- [§12 扩展指引](docs/技术文档.md)：加选择器、加导出格式、加交互怎么下手
- 打包单文件 exe：

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name 小说下载器 app.py
```

## ⚠️ 免责声明

本项目仅用于学习与研究网络请求与规则解析技术。内置书源清单来自网络公开共享，不保证可用性，也不对任何源的内容负责。请尊重作品版权：仅供个人试读，下载内容请于 24 小时内删除；长期阅读请支持正版（起点、晋江等官方平台）。

## 📄 License

[MIT](LICENSE) © 2026 WakuOOXX
