<div align="center">

# 📚⬇️ 小说下载器

**输入书名 → 聚合搜索 3000+ 书源 → 下载整本 → 导出 TXT 与 EPUB**

Windows 桌面应用 · Python + tkinter · 自研 Legado 规则引擎

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.13%2B-blue)](#)
[![platform](https://img.shields.io/badge/platform-Windows-lightgrey)](#)

[🌐 项目官网](https://WakuOOXX.github.io/novel-downloader/) · [⬇️ 下载 Windows 版](https://github.com/WakuOOXX/novel-downloader/releases/latest)

</div>

---

## ✨ 特性

- **3000+ 书源聚合搜索**:读入开源阅读(Legado)书源包,一次搜索并发打向所有可用源,结果**边搜边上屏**(不用等全部跑完),随时可停止。
- **模糊搜索兜底**:直搜无果时自动生成关键词变体(取首段 / 去尾字 / 截前 4 字),仅对本轮存活源重试;结果按相关度排序。
- **TXT + EPUB3 双格式导出**:UTF-8(BOM)TXT 与标准 EPUB3(zip/mimetype/opf/nav 全结构),适配手机阅读器与电纸书。
- **自研 Legado 规则引擎**(纯 Python):支持 `class./id./tag./text.` 链式选择器、简化 XPath / JSONPath、`##正则##替换##`、正文多页拼接、GBK/UTF-8 自动识别;含 JS 的书源自动跳过,永不报错中断。
- **书源分组过滤**:可选「校验可用 / 笔趣阁0905 / 0905校验」等当天校验分组,快速定位有效源。

## 🖥️ 界面

<table><tr>
<td>🔎 输入书名 → 搜索</td><td>📋 双击结果 → 下载</td><td>📄 自动导出 TXT + EPUB</td>
</tr></table>

> 真实演示:搜索「斗破苍穹」命中 18 条(含同名《斗破苍穹》天蚕土豆),目录 1625 章完整抓取。
> 交互预览见 [项目官网](https://WakuOOXX.github.io/novel-downloader/)。

## 🚀 快速开始

### 方式一:Windows 免安装版(推荐)
1. 下载 [novel-downloader-v1.0.0-windows-x64.zip](https://github.com/WakuOOXX/novel-downloader/releases/latest/download/novel-downloader-v1.0.0-windows-x64.zip) 并解压;
2. 保持 `小说下载器.exe` 与 `bookSource.json` 在同一文件夹;
3. 双击 exe → 输入书名 → 搜索 → 双击结果下载。

> exe 免安装、免 Python 环境,已实测 Windows 11。`bookSource.json`(18MB 书源包)可随时替换更新,无需重新下载程序。

### 方式二:源码运行
```bash
pip install requests beautifulsoup4 lxml     # Python 3.13+(需 tkinter)
python app.py
```

## 🔨 打包单文件 EXE
```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name 小说下载器 app.py
# exe 需与 bookSource.json 同目录使用(app 在打包态自动从 exe 目录读取)
```

## 📁 目录结构
```
bookdl/
├─ app.py            # tkinter GUI(搜索/下载/进度)
├─ legado/           # 引擎包(可脱离 GUI 使用)
│  ├─ rules.py       #   Legado 规则 DSL:选择器/XPath/JSONPath/正则链
│  ├─ fetcher.py     #   HTTP:独立会话、编码识别、超时
│  ├─ engine.py      #   编排:并发搜索(增量+模糊)/目录/正文
│  └─ export.py      #   TXT(UTF-8 BOM)与 EPUB3 导出
├─ bookSource.json   # 书源包(开源阅读格式,3393 源)
├─ docs/             # GitHub Pages 官网源码
├─ dev_check.py      # 单源调试脚本
├─ probe.py          # 批量探活脚本(输出 probe_hits.json)
├─ e2e2.py           # 全链路自检(含 EPUB 结构校验)
└─ 技术文档.md        # 13 章技术文档:架构/引擎/导出/扩展
```

## ⚠️ 免责声明
本项目**仅用于学习与研究**网络请求与规则解析技术。内置书源清单来自网络公开共享,不保证可用性,亦不对任何源的内容负责。请尊重作品版权:仅供个人试读,下载内容请于 24 小时内删除;长期阅读请支持正版(起点、晋江等官方平台)。

## 📄 License
[MIT](LICENSE) © 2026 WakuOOXX
