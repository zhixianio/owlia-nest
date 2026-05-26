# 🦉 Owlia Nest

Self-hosted Markdown document browser for OpenClaw PA outputs.

把你的 PA 产出的研究报告、分析文档、会话记录，随时在浏览器/手机上浏览。

## Features

- 📂 自动扫描指定目录的 Markdown/代码/配置文件
- 🎨 主题切换 + 分类标签 + 代码高亮
- 📱 PWA 支持，手机添加到主屏幕即用
- 🔗 Caddy 反代 + launchd/systemd 自启

## Quick Start

```bash
pip install owlia-nest
owlia-nest setup
```

然后打开 http://localhost/docs/

## Manual Setup

```bash
owlia-nest init                  # 创建默认配置
owlia-nest add ~/my-project/docs # 添加自定义目录
owlia-nest serve                 # 启动（默认 :8788）
```

## Development

```bash
git clone https://github.com/zhixianio/owlia-nest.git
cd owlia-nest
pip install -e .
owlia-nest serve
```

### Architecture

```
owlia-nest/              # Python 包
├── cli.py               # CLI 入口（init/add/list/serve/setup）
├── server.py            # HTTP 服务器 + Markdown 渲染 + PWA manifest
└── icons/               # favicon / PWA icons / logo
```

- **Server**: Python `http.server` + `markdown` + `pygments` 代码高亮
- **Reverse proxy**: Caddy（可选，`setup` 自动检测）
- **Auto-start**: macOS launchd / Linux systemd（`setup` 自动生成）
- **PWA**: manifest + service worker，支持离线浏览

### Publishing to PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```

## License

MIT
