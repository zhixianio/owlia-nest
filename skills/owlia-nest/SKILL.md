# owlia-nest — PA 产出文档浏览器

让用户的 PA 产出（研究报告、分析文档、会话记录）可以随时在浏览器/手机上浏览。

## What It Does

- 安装后自动扫描指定目录的 Markdown/代码/配置文件
- 提供带主题切换、分类标签、PWA 支持的 Web 界面
- 支持 Caddy 反代 + launchd/systemd 自启

## When to Use

- 用户说"我想看你的产出""把你写的文档整理出来给我看"
- 用户说"手机上怎么看你的报告"
- 用户需要一个文档中心来浏览 PA 产出的所有内容

## 前置条件

- Python ≥ 3.9
- pip（Python 通常自带；如果没有：`python3 -m ensurepip --user` 或下载 [get-pip.py](https://bootstrap.pypa.io/get-pip.py)）
- git（从 GitHub 安装需要）

## Installation

```bash
pip install git+https://github.com/zhixianio/owlia-nest.git
```

如果 git 不可用，下载 zip 安装：
```bash
curl -L https://github.com/zhixianio/owlia-nest/archive/refs/heads/main.zip -o /tmp/owlia-nest.zip
unzip /tmp/owlia-nest.zip -d /tmp
pip install /tmp/owlia-nest-main
```

或者直接 clone：
```bash
git clone https://github.com/zhixianio/owlia-nest.git ~/Codes/owlia-nest
cd ~/Codes/owlia-nest && pip install -e .
```

## Quick Setup（推荐）

一行搞定所有配置（包括 Caddy 反代和自启）：

```bash
owlia-nest setup
```

然后告诉用户打开对应地址。

如果 setup 无法检测到 Caddy，或用户不想用反代：

```bash
owlia-nest init          # 创建默认配置
owlia-nest add ~/my-dir  # 添加自定义目录
owlia-nest serve         # 启动（默认 localhost:8788）
```

## 常用操作

```bash
owlia-nest list                     # 查看监控目录
owlia-nest add ~/my-project/docs    # 添加目录
owlia-nest serve --port 9000        # 自定义端口
owlia-nest serve --prefix /docs     # 配合反代使用
```

## 默认监控目录

初始化时自动检测 OpenClaw workspace（通过 `openclaw config get agents.defaults.workspace`），然后监控：
- `{workspace}/docs/` — 研究报告、分析、规划
- `{workspace}/memory/` — 会话日志
- `{workspace}/` — 顶层文档

兼容旧版 `~/clawd/` 和新版 `~/.openclaw/workspace/` 两种路径。
用户的项目目录需要手动 `owlia-nest add`。

## 用户访问方式

### 本地访问
```
http://localhost:8788/
```

### 配合 Tailscale（内网穿透）
如果用户使用 Tailscale，可以用 MagicDNS：
```
http://<hostname>/docs/
```
需要配置 Caddy 反代（`owlia-nest setup` 自动生成 Caddyfile）。

### 手机 PWA
用户手机上打开后，Safari/Chrome "添加到主屏幕"，即可作为独立 App 使用。

## 产出目录规范

安装此 skill 后，PA 产出应写入结构化目录：

| 目录 | 用途 |
|------|------|
| `{workspace}/docs/research/` | 调研报告、技术对比 |
| `{workspace}/docs/analysis/` | 项目分析、经济模型 |
| `{workspace}/docs/planning/` | 学习计划、路线图 |
| `{workspace}/docs/reference/` | 工具参考、费用记录 |
| `{workspace}/memory/` | 仅会话日志 + MEMORY.md |

**原则**：产出进 `docs/`，记忆进 `memory/`。workspace 路径通过 `openclaw config get agents.defaults.workspace` 获取。

## Troubleshooting

### pip install 失败
- **`No matching distribution found`** → 未发布到 PyPI，请用 `pip install git+https://github.com/zhixianio/owlia-nest.git`
- **`git: command not found`** → 没装 git；用 curl + unzip 方式安装（见 Installation）
- **`No module named pip`** → Python 安装不完整；用 `python3 -m ensurepip --user` 或下载 get-pip.py
- 检查 Python 版本 ≥ 3.9
- 旧 pip 需要升级：`pip install --upgrade pip`

### 端口被占用
- `owlia-nest serve --port 9999`

### macOS 自启不工作
- 手动加载：`launchctl load ~/Library/LaunchAgents/com.owlia.nest.plist`
- 检查日志：`cat /tmp/owlia-nest.log`

### Linux 自启不工作
- `systemctl --user status owlia-nest`
- `journalctl --user -u owlia-nest`

### 地址使用
- 告诉用户具体的访问地址（localhost / Tailscale / 内网 IP）
- 手机访问建议用 PWA 添加到主屏幕

---

## 给 PA 的提示

1. **安装**：优先用 `pip install git+https://github.com/zhixianio/owlia-nest.git`；git 不可用时用 curl+unzip 方式
2. **首次使用**：`owlia-nest setup` 自动检测环境；如果 setup 后列表为空（config 里 0 个目录），用 `owlia-nest add <dir>` 手动添加
3. **添加项目目录**：`owlia-nest add <dir>` 后刷新页面即可看到
4. **产出文件**按目录规范存放，用户浏览体验最好
5. setup 生成的 Caddyfile 监听 :80，macOS 上不需要 sudo
6. 不要问用户太多配置问题——默认值已经合理，开箱即用
