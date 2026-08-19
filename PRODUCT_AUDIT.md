# Endless Worlds 产品体验审计与路线图

> 审计日期：2026-08-18
> 审计基线：Endless Worlds v0.3.0
> 审计范围：玩家流程、叙事交互、存档与长期游玩、移动端与无障碍、产品完整度

## 目标

本次审计检查 Endless Worlds 已有源码与测试，寻找能够让玩家更顺畅、更容易长期游玩，但目前尚未提供的便利功能。重点不是继续堆叠新系统，而是补齐生命周期、失败恢复和已有底层能力的玩家入口。

## 已有基础

以下能力已经存在，不应重复建设：

- 多世界、多人生书架与桌面导航栏。
- 分页开局、自由输入、单项随机和全部随机。
- 开局草稿自动保存，离开后可恢复。
- 预设选择与自由行动走同一条回合提交链路，并有二次确认。
- 回合幂等、服务器端生成中标记、离开页面后继续生成并自动收敛。
- Narrator 隔离运行，只能调用本 App 的 MCP 工具，无法访问玩家记忆、文件系统或网络。
- 状态面板、世界摘要、传闻标记和动态场景基础设施。
- 分页人生历史，并保存玩家当时采取的行动。
- 世界删除预检、输入名称确认、并发人数校验和种子世界恢复。
- 窄屏布局、桌面 rail、reduced-motion 和中英文字符串表。

当前产品的主要缺口集中在三类：

1. 人生生命周期没有闭环。
2. 已有底层能力没有玩家入口。
3. 失败恢复和长线回顾体验不足。

## P0：正确性与核心闭环

### 1. 执行世界声明的结局条件

> **状态：已实现（2026-08-18）。** `backend/view.py` 新增 `resolve_ending(template, state)`，在唯一位置执行所有 `endings` 条件并返回命中的 ending id（世界声明的条件优先于叙事者写入的 `state["ended"]` 标记）；`build_play_view` 据此回传 `ended` 与 `endingId`。`advance_run_turn` 在派发前检查，已结束人生的新回合以稳定的 `reason:"ended"` + `endingId` 拒绝而不再叙事。前端 `play.tsx` 增加终章分支：显示落幕提示、最后一段叙事作为尾声、存活回合数，并提供“在这个世界再活一次”与“回到书架”入口，编年史仍可回看。测试见 `test_view.py`。**仍未做**：`lineage: true` 世界的下一代继承流程（见 P2 §14）。

**现状**

世界模板可以声明 `endings`，详情页也会展示结局条件数量，但运行时没有统一执行这些条件。`ended` 目前只能依赖 narrator 自己写入状态；即使人生已结束，游玩页和回合路由仍可能允许继续行动。

**代码入口**

- `backend/template.py`：`Ending` 和结局条件解析。
- `backend/view.py`：`build_play_view()` 只读取 `state.ended`。
- `backend/routes.py`：`advance_run_turn()` 尚无结束态拒绝。
- `web/src/play.tsx`：没有 `v.ended` 专用分支。

**建议行为**

- 在后端唯一位置执行所有 ending 条件，返回命中的 ending ID。
- 已结束人生拒绝新回合，且重复请求返回稳定的机器可读原因。
- 游玩页将行动区替换为终章页面。
- 终章显示存活时长、关键事件、最终状态，并提供重新开一世、导出和整理人生的入口。
- `lineage: true` 的世界在符合条件时进入继承下一代流程，而不是仅显示徽章。

### 2. 显示所有已挂载动态场景

> **状态：已实现（2026-08-18）。** 场景不再是单槽只显示“最新一个提问场景”：`PlayPage` 现在把全部 mounted 场景上报给 app 根，`main.tsx` 按**挂载顺序**为每个场景渲染一个持久 `SceneSlot`（keyed by sceneId，绝不重排——移动 iframe 会重载）。展示型场景（`asks:false` 的地图/账本）因此可见，已回答但未 dismiss 的场景也仍在。`scene: string` 状态改为 `scenes: SceneRow[]`。
> **仍未做（UX 细化，非阻塞）：** 场景条/标签页与“主动展开非提问场景”的折叠交互；以及 scene 驱动的回合仍未显式传下一回合编号（当前依赖服务端 `current+1` + nonce/已答守卫，安全但非幂等最优）。

**现状**

Narrator 可以挂载 `asks: false` 的地图、账本和其他展示型场景，但前端只选择最新的、尚未回答的提问场景。因此实时生成 UI 的展示型能力已经存在，却不会出现在玩家面前。

**代码入口**

- `backend/mcp_server.py`：`endless_mount_scene`。
- `backend/view.py`：play view 已返回 mounted scenes。
- `web/src/play.tsx`：只筛选 `asks && !answered`。
- `web/src/main.tsx`、`web/src/scene.tsx`：当前只有一个 SceneSlot。

**建议行为**

- 增加场景条或标签页，显示当前全部 mounted scenes。
- 提问场景仍可自动前置，但非提问场景允许玩家主动打开。
- 已回答但未 dismiss 的地图或账本仍可回看。
- scene-driven turn 也必须提交明确的下一回合编号，保持与普通行动相同的幂等语义。

### 3. 失败后保留玩家输入并支持重试

> **状态：已实现（2026-08-18）。** `web/src/play.tsx` 的 `take()` 只在真正推进（`advanced`）、已提交（`already`）或人生终结（`ended`）时清空输入；叙事者未响应时保留玩家写的文本，记住上次未落地的行动，并在 stalled 提示旁给出“再试一次”按钮直接重发同一行动。`ended` 不再被误判为 stalled（改由终章分支接管）。

**现状**

当回合请求正常返回但 `advanced == false` 时，前端仍会清空自由输入，然后提示玩家再说一次。网络异常路径反而会保留输入，行为不一致。

**代码入口**

- `web/src/play.tsx`：`take()`。

**建议行为**

- 只在成功推进或确认已提交时清空输入。
- 保留最后一次行动，并显示“一键重试上次行动”。
- 区分离线、超时、已有请求正在生成和 narrator 未响应。
- 瞬时读取失败后，成功加载必须清除旧错误。

### 4. 修复恢复、语言和错误状态

> **状态：已实现（2026-08-18）。**
> - **语言即时生效（context 重构）：** 渲染语言改为根组件的 React 状态，根在**渲染期同步**写入 `strings.ts` 的模块 `current`（不再放在 effect 里），世界语言一变整棵树立即以新语言重渲染，不再落后一帧。`t()`/`pick()` 仍读模块 `current`，调用点零改动；语言 setter 经 `LanguageContext` 下发（`useSetLanguage`），`play.tsx` 与根的世界加载处调用它。
> - **失效位置清理 + detail 恢复：** 恢复 `live`/`detail`/`opening` 前先 `api.run`/`api.world` 校验目标仍在，已删除则清掉 remembered location 回到书架（不再打开 404 页）；新增 `detail` 视图的恢复分支。
> - **各页重试按钮：** 书架、游玩页、世界详情、编年史读取失败都提供“重试/Retry”按钮；书架与游玩页的按钮在 `body` 内，窄屏（rail 隐藏）也可点。
> - **404：** `get_run` 对不存在的人生已返回 404、无世界返回 422（本次确认，未改）。

- 世界语言变化必须触发 React 重渲染，避免英文世界首次打开仍显示中文 UI。
- 书架、世界详情、人生页和历史读取失败都应提供重试按钮。
- 移动端不得依赖仅桌面可见的 rail 才能重新加载。
- 不存在的人生统一返回 404，而不是未捕获的 `StoreError`/500。
- 恢复到已删除的人生时，应清除失效的 remembered location 并回到书架。
- `detail` 视图若写入 remembered location，也必须能够恢复。

## P1：高价值便利功能

### 5. 单独管理人生

**目标能力**

- 玩家自定义人生名称。
- 单独删除一条人生，不影响世界或同世界的其他人生。
- 归档与取消归档。
- 将进行中、已结束、已归档分组。
- 人生行显示世界、模拟风格、当前回合和最后游玩时间。
- 支持置顶和按状态筛选；数量增长后再增加搜索。

**现有基础**

`RunStore.delete_run()` 已经负责清理 state、rollback、pending、brief、chronicle 和 index。

**当前状态**

单独删除人生已落地：`backend/routes.py` 已注册 `POST /runs/{run_id}/delete`（`delete_life`，`routes.py:548/1172`），复用 `RunStore.delete_run()`，前端有 `DeleteLifeDialog`，并有 `test_delete_life.py`。

> **重命名 / 归档 / 分组已实现（2026-08-18）。** 新增 `RunStore.patch_index()`（合并 `label`/`archived` 到索引行，不动 `lastPlayed` 与其它字段）+ `POST /runs/{run_id}/meta`（`set_life_meta`，`label` 空串清除，`archived` 布尔）。`list_runs` 原样透出这两个字段。前端：`LifeRow` 优先显示玩家自定义 `label`，带内联重命名（Enter 保存 / Esc 取消）、归档/取消归档、删除三个控制；书架按**进行中 / 已落幕 / 已归档（可折叠）** 分组；rail 折叠掉已归档人生并同样优先 `label`。测试 `test_store.py::test_patch_index_*`。**仍未做：** 置顶（starred）、按状态/世界筛选与搜索、`lastPlayed` 目前是创建时间（回合提交不刷新索引，属既有限制）。

### 6. 前情提要与人生大事记

> **状态：事件时间线已实现（2026-08-18）。** `get_chronicle` 现在把每回合早已存储的 `events`（字符串）与 `gains`（`{field,amount?,source?}`）一并返回；`history.tsx` 在每回合正文下渲染这些标记（gain 带来源），并新增“只看大事”开关——只列出有 events 的回合、隐藏正文，即事件时间线。**仍未做：** 回到一条人生时的“上次离开前”前情提要横幅、结局页复用同一数据生成的一生摘要。

**现状**

每回合已经保存 `events` 和 `gains`，但玩家历史 API 只返回回合、正文和行动。

**建议行为**

- 回到一条人生时显示无额外模型调用的“上次离开前”。
- 历史中显示本回合事件、得失及来源。
- 提供“只看大事”时间线。
- 结束页复用同一数据生成一生摘要。

**代码入口**

- `backend/mcp_server.py`：commit chronicle 时写入 `events`、`gains`。
- `backend/routes.py`：`get_chronicle()` 当前未返回两者。
- `web/src/history.tsx`：历史展示。

### 7. 改善长人生的回顾体验

> **状态：跳转与事件过滤已实现（2026-08-18）。** `history.tsx` 新增“跳到第 N 回合”输入（用现成的 `?before=N+1` 定位，替换而非追加当前页）与“只看大事”事件过滤；后端 `?limit=` 已支持一次取到 100 回合。**仍未做：** 正文/行动的全文搜索、单回合折叠展开。

当前历史固定每页 12 回合，只能连续点击“再往前”。建议增加：

- 跳到指定回合。
- 搜索正文与玩家行动。
- 按关键事件过滤。
- 单回合折叠与展开。
- 一次加载更多或按需请求最多 100 回合。
- 将整条人生导出为连续 Markdown 小说。

### 8. 开局汇总、重置与复用

> **状态：汇总/重置/草稿体验已实现（2026-08-18）。** `opening.tsx`：最后一页新增“这一世的样子”出生前汇总，逐项列出选择，世界自决项以斜体“交给世界决定”明确标出；新增“全部重置”（有输入时才出现）；带回草稿时显示一次性“已恢复你上次的选择”提示；草稿加 30 天 TTL（过期即忽略），`main.tsx` 在世界列表已知时清除已删除世界的遗留草稿。**仍未做：** 复制上一世开局 / 保存为开局预设（需要跨人生读取开局答案，与 §4「快速重开 fromRunId」同源，留待一起做）。

- 出生前汇总所有选择，并明确标出留给世界决定的项目。
- 增加“全部重置”。
- 可复制上一世开局，或保存为开局预设。
- 返回已有草稿时明确显示“已恢复上次选择”。
- 草稿需要过期或清理策略，避免长期遗留在共享 localStorage。

### 9. 提高行动表达能力

- 增加可选的 OOC/补充说明通道，让玩家纠正 narrator 对意图的理解，而不必浪费一个世界回合在剧情内解释。
- Choice schema 可选携带风险、代价、时间跨度或前置条件。
- 增加 pacing 控制，例如“细讲这一晚”或“快进三年”。
- 允许在一生中切换叙述风格；后端已经支持每回合传递 style。
- 人物、物品和 thread 面板条目可点击填入行动框。
- 首次游玩可展示自由行动示例，而不仅是“或者做点别的”。

## P2：长期游玩能力

### 10. 重来上一回合

`RunStore.rollback()` 已保存上一状态，但目前没有玩家入口，而且只回滚 state，不会同步 chronicle、场景和 pending。

**建议约束**

- 第一版只允许重来最新一个已提交回合。
- 清除 pending，并使原 chronicle 记录显式失效；不要悄悄删除审计历史。
- 重新建立 narrator session 的 runtime baseline。
- 明确区分“撤回行动”和“使用同一行动重新叙述”。

不要直接实现任意历史分支。当前 chronicle 不保存逐回合完整 state，无法从第 20 回合准确还原第 7 回合。若未来需要分支，应先开始写入逐回合 state snapshot。

### 11. 世界与人生导入导出

世界打包已经实现为 `endless_make_pack`，但仅由 narrator MCP 写到服务器目录，玩家无法直接下载，也没有导入能力。

建议顺序：

1. 玩家下载世界包。
2. 导入世界包并验证 contract、世界 ID 和内容。
3. 导出完整人生，包括当前状态、chronicle、世界引用和必要场景数据。
4. 导入人生时重新生成 run ID，绝不覆盖本地现有人生。
5. 导出前可作为删除人生的安全备份。

### 12. 后台完成提醒与安全放弃

- 显示当前已等待时间。
- 玩家离开页面后，生成完成时发送 Dashboard 通知。
- 请求 deadline 后允许安全清理 stale pending。
- 不允许过早取消，否则可能出现两个 narrator 同时写同一回合。
- 页面隐藏或离线时降低轮询频率，恢复联网或回到前台时立即 refetch。

### 13. 世界更新与创建

- “有更新版本”提示目前没有行动入口，应允许将新版本安装成独立世界，或明确解释为什么不能覆盖现有世界。
- 增加世界包导入。
- 后续可将已有 compiler brief 接到“粘贴规则书并创建世界”的产品流程。
- 不应直接覆盖承载现有人生的世界定义。

### 14. 跨人生与世界连续性

这是较大的产品方向，不属于近期快赢：

- 当前每条人生及 narrator session 都是隔离的，这是正确的隐私边界。
- 若要让第二条人生继承第一条人生造成的世界历史，应建立独立的、App 专属世界 chronicle，而不是读取玩家个人记忆。
- 跨人生继承必须由世界模板显式允许，不能成为所有世界的默认行为。

## 无障碍与操作快赢

建议在 P1 一并处理：

- 开局输入使用真实 `<label>` 或明确的 accessible name。
- 选项 pill 使用 `aria-pressed` 或 radiogroup 语义。
- 历史和状态抽屉增加 `aria-expanded`、`aria-controls`。
- 加载、失败和 stalled 状态使用适当的 live region。
- Modal 增加 focus trap、关闭后 focus restore，工作中禁止 Escape/scrim 关闭。
- 自定义按钮统一 focus ring。
- 主要触控目标达到 44px。
- Scene fullscreen 支持 Escape 退出。
- Scene 加载过程显示 pending 状态。
- `Cmd/Ctrl+Enter` 用于提交或确认自由行动。
- 增加字号、行距和阅读宽度偏好。
- 根节点根据世界语言设置正确的 `lang`。

## 第二轮并行审计补充（2026-08-18，去重后净新增）

> 第二轮用 4 个并行 agent 分别复审存档管理、回合机制、前端 UI、动态内容与世界系统。以下仅列出上文尚未覆盖的项；结局闭环、动态场景全显示、失败重试、单独管理人生、前情提要/事件时间线、长历史导航、开局汇总/复用、OOC 通道、回合重来、导入导出、无障碍等均已在前文覆盖，不再重复。

### N1（并入 P0）：面板 primitive 声明了却运行时丢弃

> **状态：people 与 inventory 已修（2026-08-18）。** `backend/view.py` 的 `_shape` 现接收字段 `options`：`people` 按声明的 `attributes` 列保留每个人的属性值（态度/亲密度/身份），无声明时仍为 name+note 原状；`inventory` 保留每件物品的 `count`/`note`（“三瓶药水”不再与“一瓶”同形）。前端 `ui.tsx` 渲染人物列与物品数量，`ShapedField` 类型相应更新。测试见 `test_view.py`（`test_people_carry_declared_attribute_columns`、`test_an_inventory_keeps_count_and_note`）。
> **仍未做（需存储/新路由，非“快且安全”）：** `resource` 的 `delayed` 后果账本、`trend` 的历史序列（sparkline）——两者都要在 store 侧记录逐回合数值或未结算项，留待专门一版。

模板与编译简报承诺的字段在 `backend/view.py` 的 `_shape()` 里被压扁，属于和 P0#1 同类的“世界声明未兑现”正确性问题——编译出的世界包带着这些声明，玩家侧什么都不会发生。

- `people`：`_shape` 只输出 `("name","note")` 两列（`view.py:126`），丢弃 `COMPILER_BRIEF` 承诺的 `attributes` 列（`compile.py:134-135`）。NPC 的态度/亲密度/身份无处展示。
- `inventory`：dict 物品被压成纯字符串（`view.py:131-135`），数量、描述、分类全丢。“三瓶药水”和“一瓶”在界面上无差别。
- `resource` 的 `delayed: true`：简报承诺“会被花掉、且变化有延迟后果”（`compile.py:137-138`），但 `_shape` 未读取 `delayed`，与 `stat` 无异，也没有任何“未结算后果”的记录结构。
- `trend`：只回 `value/direction/note` 字符串，无历史序列，尽管每回合完整 state 快照已在磁盘（chronicle）。

**建议**：`_shape` 的 people/inventory 分支保留声明的列与数量；`resource` 二选一——要么从简报删掉承诺，要么在 store 加 pending-consequences 账本并在 `advance_turn` 提示叙事者；`trend` 可新增 `GET /runs/{id}/series?path=` 从 chronicle 抽取历史值。

### N2（并入 P1）：已有能力仍缺玩家入口

- **章节解锁提示**：`backend/chapters.py` 的 `opened_since()` 已能算出本回合新解锁的章节，但 `view.py`/`routes.py` 都不回传，玩家错过“世界为你打开了魔法体系这一章”的进度感时刻。落点 `build_play_view` 加 `unlocked`，**必须用世界自己的 heading 措辞，不得泄漏 chapter/disclosure 等实现词汇**（R25.2）。难度：低。
- **世界设定原文入口**：详情页从不请求 `?prose=1`，玩家看不到世界 lore 全文（后端已支持）。落点 `web/src/library.tsx`。难度：低。
- **世界卡足迹计数**：世界卡只讲静态配置，不讲玩家自己的足迹。按 `worldId` 聚合已有 `runs` 传入 `WorldCard`，显示“我在这里活过 n 次”。落点 `web/src/main.tsx`。难度：低。

### N3（并入 P1/无障碍）：阅读与沉浸体验

- **当前回合与历史的连续阅读流**：游玩页只显示当前一回合正文，上一回合要开抽屉去 History；把最近 1–2 条 chronicle 接在当前正文之上，恢复叙事连续感（`api.chronicle` 已有）。落点 `web/src/play.tsx`。难度：中。
- **阅读/沉浸模式**：一个开关隐藏 rail 与右侧面板，专心读长叙事。落点 `web/src/main.tsx` + `styles.css`。难度：低。
- **正文段落摘录/收藏**：叙事是这个 App 唯一产出物，却无法标记喜欢的段落，翻页即失。难度：低～中。
- **骨架屏加载态**：所有加载态都是一行文字，数据到达瞬间整体跳变；改为骨架屏。难度：低。
- **移动端面板可粘附**：<900px 时面板只在抽屉里，打字与看状态互斥；改为可 sticky 的摘要条。落点 `web/src/play.tsx`。难度：中。

### N4（并入 P2）：世界表现层

- **scene widget 缺空间/关系类元素**：现有 `ELEMENT_KINDS` 10 种全是线性排版（`widget.py:52-54`：heading/text/note/stat/bar/keyvalue/list/table/choice/divider），工具描述里写着“a map”却没有任何元素能画地图或关系网。建议加受约束的封闭 kind：`grid`（固定行列的区域地图）、`links`（节点+边的关系图）、`tree`（父子层级的技能树/家族谱），**几何全部由后端在 `widget.py` 生成，叙事者只提供关系不提供坐标**，守住“模型字节不直接进 DOM”的信任边界。难度：中高。
- **成就/里程碑系统**：零实现。header 加 `milestones: [{id, label, when}]`，**直接复用现成的 `Condition` 解释器**（机制成本近乎为零），每轮 commit 后求值，达成项写入 `RESERVED_STATE_KEYS` 保留字段（已有 carry-forward），view 回传本轮新达成项。难度：中（“只触发一次”的持久化需小心）。

## 推荐实施路线

### 第一批：正确性闭环

1. 执行结局条件、禁止结束后继续行动、增加终章。
2. 显示全部动态场景。
3. 失败输入保留与重试。
4. 修复语言、移动端重试、失效位置和 404/500。

### 第二批：日常游玩便利

1. 完成并验证单独删除人生。
2. 增加人生重命名、归档、分组和元数据。
3. 增加前情提要、事件时间线和长历史导航。
4. 增加开局汇总、重置和复用。
5. 完成键盘与无障碍改善。

### 第三批：长期价值

1. 世界与人生导入导出。
2. 重来上一回合。
3. 后台完成通知与安全放弃。
4. 开始保存逐回合状态快照，为未来历史分支铺路。
5. 设计 lineage 下一代与可选的世界级连续性。

## 决策原则

- 先修产品承诺和数据正确性，再加新世界或新面板。
- 优先暴露已经存在的底层能力，而不是创建平行机制。
- 回合重来必须维护 state、chronicle、scene 和 narrator baseline 的一致性。
- 完整历史分支必须建立在逐回合状态快照之上。
- Narrator 隔离和玩家记忆隔离是产品边界，便利功能不得绕过它。

## Mobile frontend deep audit

> 深审日期：2026-08-19
> 基线：当前 `main`（`0b807f1`），手机设计下限 320px，按 320 / 360 / 390 / 430 / 768 / 900 / 1100px 检查。
> 方法：4 路独立源码审计后逐项回看当前 TSX/CSS。当前 host 未安装 Browser 驱动，且已安装 app bundle 与源码 bundle 不同，因此本节把确定性的 DOM/CSS 缺陷标为“源码确认”，把必须看真实像素的项目留在验证矩阵，不用旧安装包截图代替证据。

本轮确认现有布局有良好基础：CSS 是 narrow-first；320–767px 使用 16px gutter；rail 只在 1100px 以上出现；面板 sidebar 只在 900px 以上出现，手机有 drawer 替代；正文保持 16px / 1.85 / 66ch；关键 choice 是 48px，主按钮、返回、输入框和 drawer 是 44px；`prefers-reduced-motion` 已完整覆盖现有动画。以下问题是在这些基础上的具体断点，而不是建议推翻现有响应式结构。

### Critical mobile blockers

#### M0.1 Scene 放大后 iframe 高度为 0

**状态：源码确认；跨宽度必现。**

- `web/src/styles.css:559-566`：`.ew-slot-full` 使用 `position: absolute; inset: 0; height: auto`，但最近的 positioned ancestor 是 `.ew-slot-wrap { position: relative }`，不是注释所指的 `.ew-root`。
- `web/src/scene.tsx:100-126`：full 状态下 iframe 和按钮栏都脱离文档流；wrapper 没有 in-flow child，内容高度坍缩为 0，iframe 的 top/bottom 也只能解出 0 高。
- 手机上常规 scene 已固定为 320px，放大是查看复杂场景的唯一出口，因此不是装饰性问题。

**建议**：让 full scene 保持 in-flow（例如 wrapper 负责 overlay 几何），或把 full class 放到 wrapper 上；同时增加 Escape 退出、`aria-expanded`，并保留同一个 iframe DOM 节点不移动的现有正确约束。

#### M0.2 删除确认弹窗可能出现在当前视口之外

**状态：源码确认；长书架/长详情页滚动后触发。**

- `web/src/styles.css:213-227`：`.ew-modal-wrap` 是相对整个 `.ew-root` 的 absolute box；panel 固定在 root 顶部 `4vh`，不是当前 viewport 顶部。
- `web/src/confirm.tsx:87,219`：两种删除弹窗都使用同一结构，打开时只 focus panel，没有 `scrollIntoView`。
- 从长列表底部点删除时，当前视口可能只看到 scrim，dialog 在上方数屏之外。输入框又 `autoFocus`，15px 字号会触发 iOS focus zoom，键盘进一步缩小可用区域。

**建议**：保持 overlay 不遮住 host chrome 的边界，但在打开时把 panel 滚入可见区；用 `dvh` 约束 dialog body、sticky action bar、16px 输入字号；删除 working 时禁止 scrim/Escape 关闭。

#### M0.3 手机系统 Back/边缘返回不会回到 app 上一层

**状态：源码确认。**

`web/src/main.tsx` 的 shelf/detail/opening/live 全是 React state；源码没有 `pushState`、`popstate` 或 hash 路由。Android 系统 Back 与 iOS 返回手势会退出 dashboard 当前页面，而不是 detail → shelf、opening → detail 或 live → shelf。现有可见返回按钮仍应保留，但浏览器历史必须反映用户进入的层级。

#### M0.4 提问 scene 位于整页末尾，回答时没有等待反馈

**状态：源码确认；实际“离首屏几屏”需真实数据复测。**

- `web/src/main.tsx:347` 把唯一 `SceneSlot` 挂在 `.ew-shell` 之后；`web/src/play.tsx` 只把 scene id 上报，没有 notice、anchor 或 `scrollIntoView`。手机上 scene 会出现在正文、choice、输入区和两个 drawer 之后。
- `onSceneChoice` 直接等待 `answerScene` + `takeTurn`，没有接入 PlayPage 的 tapped/phrase/busy 状态；直到整轮完成才 refresh。一次可能耗时几十秒的 scene 点击看起来像没有响应。

**建议**：PlayPage 内显示 scene 到达通知/入口并把 scene 滚入可见区；scene 回答复用普通行动的 waiting 与幂等 turn 语义。

#### M0.5 一次轮询读取失败会永久盖住后来成功的数据

**状态：源码确认。**

`web/src/play.tsx:50-56` 的 `load()` 失败时设置 `error`，成功时只 `setV`，不清除旧 error；渲染又先判断 `error`。生成中每 3 秒的轮询即使后来成功，玩家仍停留在错误页。在移动网络切换、短暂离线和后台恢复时影响最高。

### Layout defects by viewport

#### 320–430px

- **长 chip 可制造整页横向滚动（源码确认）**：`.ew-chip` 使用 `white-space: nowrap` 且没有 max-width；库存、rank、world style、opening label 与 digest category 都可来自世界或 narrator，不能假设字符串短。应允许单个 chip 在必要时换行或截断后提供完整值。
- **digest flex row 不能可靠收缩（源码确认）**：`.ew-dcat` 是 `flex: 0 0 auto`，正文 sibling 无 `min-width: 0` / `overflow-wrap`；长 category 或无断点 token 会撑宽页面。
- **正文长 token 没有 containment（源码确认）**：`.ew-prose` 缺少 `overflow-wrap: anywhere`，code/pre 也没有局部横向滚动策略。普通 CJK 正文默认换行是正确的，不应全局使用 `break-all`。
- **history 打开后把 panels drawer 推到整段历史之后（源码确认）**：`play.tsx` 顺序是 history button → 全部 History → panels button。历史越长，查看当前状态的入口越难到达。两个辅助面板应并列成 tabs/disclosure，或固定入口而不是彼此推远。
- **choice 二次确认可能生成在 fold 以下（设计缺陷，需像素确认）**：点击最后一个 choice 后，confirm row 插在该 choice 下方，但无 `scrollIntoView`。选择会亮起，提交控制可能不在视口内。
- **输入区是不可换行的单行 flex（潜在 i18n 缺陷）**：当前中英文短标签尚能放下，但 textarea 可被更长 locale 的按钮压成很窄的 sliver。为输入设置可用最小宽度，并允许 row 在约束不足时换行。
- **scene 常规高度固定 320px（需真实场景确认）**：在 320×568 上约占 56% 屏高；目前唯一放大出口又被 M0.1 破坏。修 M0.1 后再决定 `min()`/`dvh` 策略，不应先武断缩短。

#### 768px transition

- gutter 从 16px 变为 24px，仍保持单列阅读；没有发现双栏提前挤压的问题。
- 需要在 768px 两侧复测 opening action bar：`.ew-spacer` 在 mobile wrap 时只是残留的桌面右对齐机制，可能产生不自然的孤立空位。

#### 900px transition

- **history 被错误隐藏（源码确认）**：`@media (min-width: 900px) { .ew-drawer { display: none } }` 同时隐藏 history 与 panel drawer；只有 panel 有 `.ew-aside` 替代，history 没有。900–1099px 连 rail 也没有，因此 history 完全不可达；1100px 以上同样没有替代入口。
- **结束人生没有 panels（源码确认）**：ended branch 只渲染 history，不渲染 `panels` 或 `.ew-aside`，所有宽度都无法查看最终状态。

#### 1100px transition

- rail 与阅读列的 grid 分工正确，inline back 被 rail 的永久 shelf 入口替代也合理。
- `.ew-rail` 使用 `max-height: calc(100vh - 120px)`，高度依赖 host chrome 的硬编码猜测；真实 dashboard 容器若不是 viewport scroller，sticky/高度可能不符合预期。该项必须在 host 内实测，不能仅凭源码判失败。

### Touch, keyboard and accessibility

本轮把 44px 平台惯例与 WCAG 2.2 AA 的 24px target-size floor 分开评级。当前没有确认到 `<24×24` 且间距也不满足的 SC 2.5.8 失败；以下是重要的 44px 惯例缺口：

- `.ew-opt`、`.ew-btn-sm`、`.ew-btn-quiet`、`.ew-slot-btn` 是 36px。优先提升 choice 二次确认、opening option、删除和 scene zoom。
- `.ew-input` 与行动 textarea 是 15px，iOS 聚焦会自动放大；改为至少 16px。
- 多个按钮移除了 `-webkit-tap-highlight-color`，却没有自有 `:active` 反馈，触摸时像没有点中。

明确的语义/键盘缺口：

- `web/src/opening.tsx` 的视觉 `.ew-glabel` 不是 `<label>`，文本/数字输入没有 accessible name。
- opening option 与 style pill 没有 `aria-pressed` 或 radio 语义；颜色是唯一 selected state。
- history/panel drawer 没有 `aria-expanded`、`aria-controls`，展开内容也没有命名 region。
- action textarea 只靠 placeholder 命名；输入后名称消失，字符上限也没有关联说明。
- loading、error、stalled、scene 到达与删除失败多数没有 status/alert live region；`Waiting` 已有正确 pattern，可复用。
- modal 主动删除 focus outline、无 focus trap、关闭后不 restore opener；世界删除的 `.ew-doomed` 是可滚动但不可键盘聚焦的区域。
- modal 的 Escape 与 scrim 在 working 阶段仍可关闭，使后端删除完成但 UI 不执行 `onDeleted`，留下陈旧书架。
- scene fullscreen 没有 Escape 退出，也没有 expanded 状态。
- 根节点没有随世界设置 `lang`；语言模块 mutation 也不保证立即触发 React rerender。

### Loading, error and recovery behavior

- shelf backend error 在手机上没有 retry；桌面 rail 也不是一个明确重试入口。
- PlayPage 初始 `!v` loading 只有一行文字，没有 Back；挂起请求没有 timeout/AbortController，手机可进入无法退出的等待页。
- history 首次失败会显示错误，但加载过部分 turns 后的下一页失败没有可见提示或 retry。
- scene fetch 没有 pending 状态；失败提示存在，但新 scene 到达不会被宣布。
- 没有 offline/online、visibility 或 reconnect 处理；后台仍按 3 秒轮询，回到前台也不立即 refetch。
- `view:'detail'` 会写入 localStorage，但 restore effect 只恢复 live/opening；细节页记忆是死写入。
- view 切换和删除后回书架没有 scroll reset；操作结果 note 在 root 顶部，用户可能停在长列表中段看不到反馈。

### Recommended mobile implementation order

1. **修不可用路径**：M0.1 scene full geometry；M0.2 modal 可见性/working 关闭保护；900px history；ended panels。
2. **修手机导航与反馈**：app 内 history integration；scene 到达/等待；PlayPage 成功读取清旧 error；所有关键 error 提供 retry/back。
3. **修触控与输入**：36→44px；输入 16px；active/focus-visible；confirm row 自动保持可见。
4. **修 modal a11y**：focus trap/restore、可聚焦 doomed region、live regions、键盘与视觉 viewport 行为。
5. **修内容 reflow**：chip、digest、prose/code 与长 locale；真实 CJK/Latin 长数据共同验证。
6. **补语义**：opening labels/selected state、drawers、textarea、root language。
7. **再做体验增强**：history/panels 的手机信息架构、离线/visibility、长历史性能与 scroll restoration。

### Verification matrix

| Width | Required checks | Current evidence |
|---:|---|---|
| 320×568 | shelf/detail/opening/live 无整页横向滚动；所有关键目标 ≥44px；keyboard 打开后 dialog input + action 可见；scene/confirm 不被 fold 吞掉 | 源码缺陷已确认；真实像素待 Browser 驱动 |
| 360×800 | CJK populated world；长 chip/digest；history 与 panels 互相可达 | 源码缺陷已确认；真实像素待 Browser 驱动 |
| 390×844 | iPhone 主检查：focus zoom、返回手势、删除弹窗、scene full、safe visible height | 源码缺陷已确认；真实设备待测 |
| 430×932 | 大屏手机：opening 4-group 页面与 action bar wrap；长标题/人生删除同行 | 源码缺陷已确认；真实像素待 Browser 驱动 |
| 768×900 | 16→24px gutter 边界；仍为单阅读列；action bar 无异常空位 | 静态结构正确；边界截图待测 |
| 900×900 | `.ew-aside` 出现；panel drawer 消失；history 仍必须存在 | **当前源码失败：history 一并消失** |
| 1100×900 | rail 出现；inline back 消失但 shelf 路径仍可达；rail sticky 高度；history 可达 | rail 结构静态正确；**history 当前失败**；host sticky 待测 |

视觉验证恢复后，最小自动化门槛应包括：320/390px 的 `documentElement.scrollWidth <= clientWidth + 1`；逐个列出越过 viewport 的非 fixed 元素；直接测量主内容列宽而不只测 overflow；打开 keyboard/dialog/scene/history 状态；以中文真实填充数据看截图。overflow 结果要先区分允许局部滚动的 table 与不允许溢出的 control/text，且 CJK 被挤成一字一行只能靠看图发现。
