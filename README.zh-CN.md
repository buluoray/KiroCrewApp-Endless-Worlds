# 无限世界 / Endless Worlds

[English](README.md) | **简体中文**

在一个由 AI 模拟的世界里过完一生。无限世界是一个
[Kiro Crew](https://github.com/kirodotdev/KiroCrew) 应用：一个文字人生模拟游戏——
你出生于某个世界，一回合一回合地把它活过来，由一个大语言模型**叙事者**书写每一回合：
它会回应你的选择、记得你五十回合前做过的事，并让世界按自己的节奏推进，无论你是否行动。
它内置了旗舰世界 **剑火纪元**（西幻沙盒）与 **末世残响**（丧尸末日生存），
还能用内置的**世界铸造师**把你粘贴的一段设定变成一个全新的可玩世界。

- 一次只过一段人生，用世界自己的语言（中文 / English）呈现。
- 一个永不出戏、也从不把你当成天选之子的叙事者。
- 每回合生成的背景画、命运抉择的插画、人生星图、纪念物、
  会把过往事实回响进故事的世界记忆，以及多代传承。
- 自带世界：粘贴一段设定或一句点子，世界铸造师会把它清洗、编译成可玩的世界包。

## 工作原理

无限世界完全运行在你自己的 Kiro Crew gateway 上。它由一个 Python 包提供两个后端界面：

- 一个 **HTTP 界面**（`backend/routes.py`），供网页 UI 调用；
- 一个面向 agent 的 **MCP server**（`backend/mcp_server.py`），供叙事者与世界铸造师
  读取运行时状态并提交回合。

前端（`web/`，React + TypeScript + Vite）构建为单个 `ui/index.mjs` bundle，
直接挂载到 dashboard 上。世界是 Markdown 包（`seeds/*.md`）：一段应用会渲染并强制校验的
机器可读头部，加上作为叙事者规则书、原样透传的正文。

完整架构见 [`docs/architecture.md`](docs/architecture.md)；
各模块的契约在 [`docs/modules/`](docs/modules/README.md) 下。

## 安装

需要一个正在运行的 [Kiro Crew](https://github.com/kirodotdev/KiroCrew) gateway，
主机上有 Python 3.10+ 与 Node.js 22+（registry 安装时用来构建 UI）。

**从 registry 安装（推荐）。** registry 安装会克隆并构建应用、并运行它的 `setup.sh`
——尽力安装下面说的可选美术依赖。把本仓库加为一个 app registry，然后在 dashboard 的
**App Store** 里安装无限世界：

- Registry 地址：`https://github.com/buluoray/KiroCrewApp-Endless-Worlds`
  （其 `app-registry.json` 列出了本应用）。
- 在 dashboard 打开 **App Store**，添加该 registry，然后安装
  **无限世界 / Endless Worlds** 并启用。

在侧栏选择它即可。应用会把自己的 MCP server 路径自愈到实际安装位置，无需手动编辑
`app.json`。

这种 registry 安装（以及每次更新）都会运行 `setup.sh`——对**可选**美术依赖做一次
**尽力而为、绝不阻拦**的安装：一个 SVG 光栅化器（供插画师预览草稿背景）和
`vtracer` + `pillow`（供 SCENE 页面描摹参考照片）。安装不会因此失败——即使这些都缺，
应用照常运行：发布背景画回退到叙事者的手绘路径，照片场景降级为安静的程序生成色调底图。
参考照片仅从固定的 CC0/公有领域白名单经 HTTPS 拉取。

**本地安装——仅供开发。** 本地路径安装只是拷贝应用，**不会**运行 `setup.sh`；
用于改代码时的迭代，而不是日常使用：

```bash
kirocrew app install /absolute/path/to/endless-worlds
kirocrew app enable endless-worlds
bash setup.sh   # 本地安装不会跑它，想要可选依赖就自己跑一下
```

## 构建与开发

发布用的 `ui/index.mjs` 是构建产物；改动 `web/` 下任何内容后都要重建它：

```bash
cd web
npm ci
npm run build        # tsc --noEmit && vite build -> ../ui/index.mjs
```

运行后端测试套件：

```bash
cd backend
python3 -m pytest
```

贡献流程（环境准备、质量门禁、PR 流程、linter）见
[`CONTRIBUTING.md`](CONTRIBUTING.md)；“改代码前先读规格”的路由表与工程规则见
[`AGENTS.md`](AGENTS.md)。遇到运行时问题（例如叙事者拿不到工具——重启 gateway）？
见 [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)。

## 创建一个世界

世界是自包含的 Markdown 文件。可以从 [`seeds/`](seeds/) 里已有的一个开始，
或用应用内的**创建世界**流程把一段设定交给世界铸造师。世界包的格式——头部 schema、
字段原语、`when` 表达式语言，以及系统引擎——规定在
[`docs/modules/world-schema.md`](docs/modules/world-schema.md) 与
[`docs/modules/world-creation.md`](docs/modules/world-creation.md)。

## 许可证

依 [Apache License 2.0](LICENSE) 授权。
