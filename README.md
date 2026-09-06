<div align="center">

# 📚⬇️ 小说下载器

**输入书名 → 聚合搜索 3000+ 书源 → 下载整本 → 导出 TXT 与 EPUB**

Windows 桌面应用 · Python + tkinter · 自研 Legado 规则引擎

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.14%2B-blue)](#)
[![platform](https://img.shields.io/badge/platform-Windows-lightgrey)](#)

[🌐 项目官网](https://WakuOOXX.github.io/novel-downloader/) · [⬇️ 下载 Windows 版](https://github.com/WakuOOXX/novel-downloader/releases/latest)

</div>

---

## ✨ 特性

- **3393 书源聚合搜索**:读入开源阅读(Legado)书源包,一次搜索并发打向所有可用源,结果**边搜边上屏**(不用等全部跑完),随时可停止。
- **模糊搜索兜底**:直搜无果时自动生成关键词变体,仅对本轮存活源重试,结果按相关度排序。
- **多选 + 智能下载模式**:`Ctrl/Shift` 多选结果 → 弹窗选「下载单一」(自动跳过被封书源,只下第一本可用的)或「合并下载」(每本各导出一个文件);失败的源在结果表里自动标红,下次一眼避开。
- **交互式多选引擎(资源管理器式,常开)**:无需任何开关、不改鼠标样式。**单击=单选该项**,`Ctrl+单击`=逐个加/减,`Shift+单击`=从上次点到的行连续选,按住左键拖动=蓝色半透明**框选**(与框相交的行全中;普通拖松开=只留框内,`Shift`/`Ctrl`+拖=追加进已选),`Esc` 取消框选,双击=下载该行。拖拽做了行区间缓存+节流,上千行结果也流畅。选中项自动记忆(存 `sel_state.json`),重开后按上次结果自动恢复,条目已失效的自动跳过,可一键「清除记忆」。
- **TXT / EPUB 二选一导出**:每本书只导出一种格式,避免重复占空间;批量模式自动给重名书加「_源名」后缀防覆盖。
- **自研 Legado 规则引擎**(纯 Python):实现书源规则 DSL 的常用子集,自动识别站点编码;依赖 JS 的书源自动跳过,永不报错中断。
- **书源分组过滤**:可选「校验可用」等已校验分组(共 252 个取值),快速定位有效源。

> 各特性的实现细节(并发与超时策略、规则语法兼容矩阵、EPUB 内部结构)见 [技术文档.md](技术文档.md),本文仅保留使用者视角的概述。

## 🖥️ 界面

<table><tr>
<td>🔎 输入书名 → 搜索</td><td>📋 Ctrl/Shift 多选 → 下载</td><td>📄 TXT / EPUB 二选一导出</td>
</tr></table>

> 真实演示:搜索「斗破苍穹」命中 18 条(含同名《斗破苍穹》天蚕土豆),目录 1625 章完整抓取。
> 多选后弹出下载方式选项:**下载单一**自动跳过被封书源、**合并下载**逐个独立下载,失败行标红。
> 交互预览见 [项目官网](https://WakuOOXX.github.io/novel-downloader/)。
> 注:本组数据的权威记录见 [技术文档 §1](技术文档.md),**实测数据更新时两处需同步**。

## 🚀 快速开始

### 方式一:Windows 免安装版(推荐)
1. 下载 [novel-downloader-v1.0.0-windows-x64.zip](https://github.com/WakuOOXX/novel-downloader/releases/latest/download/novel-downloader-v1.0.0-windows-x64.zip) 并解压;
2. 保持 `小说下载器.exe` 与 `bookSource.json` 在同一文件夹;
3. 双击 exe → 输入书名 → 搜索 → 双击结果下载。

> exe 免安装、免 Python 环境,已实测 Windows 11。`bookSource.json`(18MB 书源包)可随时替换更新,无需重新下载程序。

### 方式二:源码运行
```bash
pip install requests beautifulsoup4 lxml     # 需含 tkinter 的解释器(实测 Python 3.14.7 可用)
python app.py              # 命令行启动
启动下载器.bat              # 或双击此脚本(pythonw 启动, 无控制台窗口)
```

> ⚠️ 部分精简版 Python **不含 tkinter**(本机管理版 3.13.12 即如此),用它启动会直接报 `ModuleNotFoundError`。运行环境要求与排错见 [技术文档 §2 / §11](技术文档.md)。

## 🔨 打包单文件 EXE
```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name 小说下载器 app.py
# exe 需与 bookSource.json 同目录使用(app 在打包态自动从 exe 目录读取)
```
> 完整发布流程与产物清单见 [技术文档 §14](技术文档.md)。

## 📁 目录结构(精简)
```
bookdl/
├─ app.py                              # tkinter GUI(入口)
├─ selpolicy.py                        # 多选/框选纯策略
├─ 启动下载器.bat                       # 双击启动脚本(pythonw)
├─ legado/                             # 引擎包(可脱离 GUI 独立使用)
├─ bookSource.json                     # 书源包(开源阅读格式, 3393 源)
├─ downloads/                          # 下载输出目录
└─ 技术文档.md                          # 技术文档:架构/引擎/导出/交互/扩展/发布
```
> 开发/自检脚本(dev_check、probe、e2e2、test_*)已随发布清理,如需二次开发可在开发工作区副本获取;完整文件树见 [技术文档 §3](技术文档.md)。

## ⚠️ 免责声明
本项目**仅用于学习与研究**网络请求与规则解析技术。内置书源清单来自网络公开共享,不保证可用性,亦不对任何源的内容负责。请尊重作品版权:仅供个人试读,下载内容请于 24 小时内删除;长期阅读请支持正版(起点、晋江等官方平台)。

## 📄 License
[MIT](LICENSE) © 2026 WakuOOXX
