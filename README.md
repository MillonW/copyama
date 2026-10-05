<div align="center">

# Copyama

**极简、流畅、开源的 Windows 剪贴板管理器**

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-green?logo=qt&logoColor=white)](https://wiki.qt.io/Qt_for_Python)
[![License](https://img.shields.io/github/license/MillonW/copyama?color=orange)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.5.0-blueviolet)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey?logo=windows&logoColor=white)]()

**轻量 · 快速 · 无广告 · 开源免费**

</div>

---

## ✨ 特性

- ⌨️ **全局热键唤起** — 任意位置按快捷键呼出剪贴板历史，双击直接填入当前输入框
- 🎯 **智能气泡分类** — 自动识别文本/代码/链接/图片/文件/音视频/压缩包等类型，流式布局
- 🖼 **右侧实时预览** — 文本、代码、图片、文件列表一键预览
- 🔤 **中文分词搜索** — 基于 jieba 的智能分词，输入关键词秒级过滤
- 🌓 **明暗主题切换** — 内置浅色 / 深色两套主题，自动适配系统
- 📌 **置顶收藏 + 分组** — 常用内容钉住，按时间/类型自动分组
- 🧹 **自动清理策略** — 按容量/时间自动过期，隐私保护
- 🔍 **热键冲突检测** — 设置时实时检测占用，一键推荐可用快捷键
- 🎨 **丝滑动画** — 弹出/收起/按压反馈，流畅不生硬
- 🪟 **托盘常驻** — 关闭主窗口不退出，后台静默运行

---

## 📦 下载

从 [Releases](https://github.com/MillonW/copyama/releases) 页面下载最新版 `Copyama.zip`，解压后双击 `Copyama.exe` 即可使用，无需安装。

> 单目录绿色版，所有数据保存在 `%APPDATA%/Copyama` 下。

---

## 🚀 快速上手

### 基本操作

| 操作 | 说明 |
|------|------|
| `Ctrl + Alt + V` | 呼出 / 收起剪贴板历史（可在设置中修改） |
| 双击条目 / 点气泡 | 复制并直接粘贴到当前输入框 |
| `↑` `↓` | 上下选择条目 |
| `Enter` | 复制选中条目 |
| `Esc` | 收起窗口 |
| 直接输入文字 | 搜索过滤 |
| 右键托盘图标 | 打开设置 / 暂停捕获 / 清空历史 / 退出 |

### 支持的内容类型

| 类型 | 说明 |
|------|------|
| 📝 文本 | 普通文字、富文本自动转纯文本 |
| 💻 代码 | 自动识别代码片段，气泡高亮 |
| 🔗 链接 | URL / 邮箱 / 手机号 |
| 🖼 图片 | 截图、复制的图片，支持预览 |
| 📁 文件 | 多文件列表，单张图片支持预览 |
| 🔢 数字 | 手机号、身份证、金额等 |
| 🎵 音视频 | mp4 / mp3 / wav 等文件 |
| 📦 压缩包 | zip / rar / 7z 等 |

---

## 🛠 开发环境

### 环境要求

- Python **3.9 ~ 3.12**（推荐 3.11）
- Windows 10 / 11

### 从零开始

```bash
# 1. 克隆项目
git clone https://github.com/MillonW/copyama.git
cd copyama

# 2. 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate

# 3. 安装依赖（国内建议加镜像源）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 运行
python -m copyama
```

> 💡 **多 Python 版本**：如果你装了多个 Python，请用完整路径或 `py -3.11` 指定版本，
> 例如 `py -3.11 -m venv .venv`。

### 运行测试

```bash
pytest
```

### 打包发布

项目使用 **PyInstaller** 打包为绿色单目录版：

```bash
# 安装打包工具
pip install pyinstaller

# 执行打包（配置在 copyama.spec）
pyinstaller copyama.spec --clean -y

# 产物在 dist/Copyama/ 目录下
```

打包参数：
- `--windowed` — 无控制台黑框
- `--icon assets/app.ico` — 应用图标
- 目录模式（非单文件），启动更快

---

## 📂 项目结构

```
copyama/
├── src/copyama/
│   ├── core/              # 核心业务逻辑
│   │   ├── clipboard.py   # 剪贴板监听（Qt QClipboard）
│   │   ├── tokenizer.py   # 中文分词
│   │   ├── grouping.py    # 分组策略
│   │   ├── retention.py   # 清理策略
│   │   ├── blacklist.py   # 黑名单
│   │   └── ...
│   ├── data/              # 数据层
│   │   ├── storage.py     # SQLite 存储
│   │   └── thumbnails.py  # 缩略图
│   ├── platform/          # 平台相关（Win32 API 封装）
│   ├── ui/                # PySide6 界面
│   │   ├── main_window.py     # 主窗口
│   │   ├── settings_window.py # 设置窗口
│   │   ├── hotkey.py          # 热键设置页
│   │   ├── tray.py            # 托盘图标
│   │   ├── theme.py           # 主题系统
│   │   └── flow_layout.py     # 流式布局
│   ├── app.py            # 应用入口（组装各模块）
│   ├── config.py         # 配置管理
│   └── __main__.py       # 命令行入口
├── assets/               # 静态资源（图标等）
├── tools/                # 工具脚本
├── tests/                # 测试
├── copyama.spec          # PyInstaller 打包配置
├── pyproject.toml        # 项目元信息
├── requirements.txt      # 依赖清单
└── README.md
```

---

## 🧠 技术选型

| 模块 | 技术 | 说明 |
|------|------|------|
| GUI | **PySide6** (Qt 6) | LGPL 协议，商用友好，原生体验 |
| 剪贴板 | **Qt QClipboard** | 跨平台稳定，替代易出错的 Win32 hook |
| 全局热键 | **Win32 RegisterHotKey** | 系统级热键，不注入进程 |
| 存储 | **SQLite** | 零依赖，本地数据库，备份方便 |
| 分词 | **jieba** | 中文搜索体验好 |
| 图片 | **Pillow** | 缩略图生成、格式转换 |
| 打包 | **PyInstaller** | 生态成熟，PySide6 兼容性最佳 |

---

## 🗺 路线图

- [x] **M1** 基础 MVP — 文本剪贴历史、搜索、托盘
- [x] **M1.5** 多类型支持 — 图片、文件、气泡分类、预览
- [x] **M2** 完整体验 — 分词搜索、置顶分组、动画、热键检测、双击粘贴
- [ ] **M3** 发布 — 安装包、自动更新、官网、多语言

---

## 🤝 贡献

欢迎贡献代码！无论是 Bug 修复、新功能还是文档改进都很感激。

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的改动 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

### 代码规范

- 代码风格遵循 [PEP 8](https://peps.python.org/pep-0008/)
- 提交信息使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式
- 新增功能请附带测试

---

## 📄 许可证

MIT License © Copyama — 详见 [LICENSE](LICENSE)

---

<div align="center">

如果觉得好用，点个 ⭐ Star 支持一下吧！

</div>
