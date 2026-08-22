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

需要一个正在运行的 [Kiro Crew](https://github.com/kirodotdev/KiroCrew) gateway
（Python 3.10+；构建 UI 需要 Node.js 22+）。

安装本地检出（本仓库目前未声明公开的远程地址）：

```bash
kirocrew app install /absolute/path/to/endless-worlds
kirocrew app enable endless-worlds
```

打开 dashboard，在侧栏选择 **无限世界 / Endless Worlds**。应用会把自己的 MCP server
路径自愈到实际安装位置，无需手动编辑 `app.json`。

发布背景画还需要 gateway 主机上有**一个本地 SVG 光栅化器**——插画师会先审阅服务端
渲染出的 PNG 预览再发布。以下任一即可满足，按此顺序检查：

- `cairosvg` Python 包（`pip install cairosvg`）；
- `rsvg-convert` 可执行文件（Debian/Ubuntu 上的 `librsvg2-bin`）；
- librsvg 共享库本身（Debian/Ubuntu 上的 `librsvg2-2`、Fedora/AL2023 上的
  `dnf install librsvg2`、macOS 上的 `brew install librsvg`），通过 `ctypes` 直接调用，
  无需 Python 包。

SCENE 车道还需要 `vtracer` 与 `pillow` 两个 Python 包
（`pip install vtracer pillow`）把参考照片描摹成底图；motif 车道没有它们也能工作。
照片解码与描摹按每个变体在一个可被杀死的子进程里运行，带墙钟超时、输入/输出字节上限，
以及格式/尺寸/像素守卫。参考图仅从 Wikimedia Commons 主机经 HTTPS 拉取，重定向不能离开
该允许列表，且只接受 CC0 或公有领域的照片。若搜索、拉取、校验或描摹失败，该场景会退化为
一张安静的程序生成色调底图，而不是暴露一个损坏或部分不可信的描摹。

没有光栅化器时，插画师的草稿提交会失败、页面美术回退到叙事者的应急路径；故事本身不受影响。

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
