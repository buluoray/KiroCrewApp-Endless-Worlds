import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
//#region src/api.ts
/** The app's HTTP surface, and the shapes it answers with.
*
* The types are written from what the routes actually send. That makes drift a
* compile error instead of a blank panel — the failure mode this app has already
* shipped twice, once when a renamed field blanked the whole page.
*/
var API = "/api/apps/endless-worlds";
/**
* Fold a `/api/models` payload into the picker's `{ id, name }` rows.
*
* Tolerates both a bare array and a `{ models: [...] }` wrapper, and both the
* `model_id` / `model_name` keys kiro-cli's `--list-models` emits and a plain
* `id` / `name` — reading the kiro-cli keys FIRST. A row filtering out on a
* missing `id` is what once left the picker showing only "Default (auto)".
*
* Exported so it can fold the response whether it arrives via the App SDK client
* (`useAppApi().get`) or the bare-fetch fallback below.
*/
function normalizeModels(raw) {
	return (Array.isArray(raw) ? raw : Array.isArray(raw?.models) ? raw.models : []).map((m) => {
		if (typeof m === "string") return { id: m };
		const o = m;
		const id = o.model_id || o.model_name || o.id || "";
		return {
			id,
			name: o.model_name || o.name || id
		};
	}).filter((m) => m && typeof m.id === "string" && m.id);
}
var ApiError = class extends Error {
	status;
	body;
	constructor(status, body) {
		super(`HTTP ${status}`);
		this.status = status;
		this.body = body;
		this.name = "ApiError";
	}
	/** The server's machine-readable reason, or '' when it sent none. */
	get code() {
		return typeof this.body.code === "string" ? this.body.code : "";
	}
};
async function json(path, init) {
	const res = await fetch(`${API}${path}`, init);
	if (!res.ok) {
		let body = {};
		try {
			body = await res.json();
		} catch {}
		throw new ApiError(res.status, body);
	}
	return await res.json();
}
function post(path, body) {
	return json(path, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body ?? {})
	});
}
function send(method, path, body) {
	return json(path, {
		method,
		headers: { "Content-Type": "application/json" },
		body: body === void 0 ? void 0 : JSON.stringify(body)
	});
}
var api = {
	worlds: (language) => json(`/worlds${language ? `?language=${encodeURIComponent(language)}` : ""}`),
	settings: () => json("/settings"),
	saveSettings: (body) => json("/settings", {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body)
	}),
	/** The gateway's advertised model list, proxied through the app's OWN backend
	*  (`GET /api/apps/endless-worlds/models`). The core `/api/models` route needs
	*  the dashboard token, which the app's path-scoped session cookie cannot carry;
	*  the app route can, and reuses the core handler server-side. Returns [] rather
	*  than throwing when the list is unavailable, so the picker degrades to "keep
	*  default". */
	models: async () => {
		try {
			const res = await fetch(`${API}/models`);
			if (!res.ok) return [];
			return normalizeModels(await res.json());
		} catch {
			return [];
		}
	},
	world: (id, prose = false, language) => {
		const q = new URLSearchParams();
		if (prose) q.set("prose", "1");
		if (language) q.set("language", language);
		const qs = q.toString();
		return json(`/worlds/${encodeURIComponent(id)}${qs ? `?${qs}` : ""}`);
	},
	worldDeletion: (id) => json(`/worlds/${encodeURIComponent(id)}/deletion`),
	/** `lives` is a precondition, not a parameter: it must match what the dialog
	*  showed, or the server refuses with 409 rather than ending a life the player
	*  was never told about. */
	deleteWorld: (id, lives) => post(`/worlds/${encodeURIComponent(id)}/delete`, {
		confirm: id,
		lives
	}),
	lifeDeletion: (runId) => json(`/runs/${encodeURIComponent(runId)}/deletion`),
	/** `turn` is a precondition, not a parameter: it must match the month the dialog
	*  showed, or the server refuses rather than erasing more story than the player
	*  was told about. */
	deleteLife: (runId, turn) => post(`/runs/${encodeURIComponent(runId)}/delete`, {
		confirm: runId,
		turn
	}),
	/** A player's own name and shelf state for a life — metadata only, never the
	*  story. Pass `label: ""` to clear a custom name. */
	setLifeMeta: (runId, body) => post(`/runs/${encodeURIComponent(runId)}/meta`, body),
	/** A fresh storyteller for the same story: discards the narrator's accumulated
	*  conversation while keeping every fact of the life. `confirm` echoes the run
	*  id, same retried-fetch guard as deleteLife. */
	resetConversation: (runId) => post(`/runs/${encodeURIComponent(runId)}/reset-conversation`, { confirm: runId }),
	restoreWorld: (id) => post(`/worlds/${encodeURIComponent(id)}/restore`, {}),
	worldDrafts: () => json("/world-drafts"),
	worldDraft: (id) => json(`/world-drafts/${encodeURIComponent(id)}`),
	createWorldDraft: (text, title = "") => post("/world-drafts", {
		text,
		title
	}),
	compileWorldDraft: (id) => post(`/world-drafts/${encodeURIComponent(id)}/compile`, {}),
	/** Optional `title` renames the world's display title before installing it. */
	installWorldDraft: (id, title = "") => post(`/world-drafts/${encodeURIComponent(id)}/install`, title ? { title } : {}),
	discardWorldDraft: (id) => send("DELETE", `/world-drafts/${encodeURIComponent(id)}`),
	runs: () => json("/runs"),
	run: (id) => json(`/runs/${encodeURIComponent(id)}`),
	/** The months already lived. `before` is a turn NUMBER, not an offset: an offset
	*  would shift under a turn committed between two pages and silently skip or
	*  repeat a month. `q` filters the whole life by substring before paging. */
	chronicle: (id, before = 0, q = "", limit = 0) => {
		const p = new URLSearchParams();
		if (before > 0) p.set("before", String(before));
		if (q) p.set("q", q);
		if (limit > 0) p.set("limit", String(limit));
		const qs = p.toString();
		return json(`/runs/${encodeURIComponent(id)}/chronicle${qs ? `?${qs}` : ""}`);
	},
	createRun: (body) => post("/runs", body),
	/** What a finished life may pass on, grouped by category (§9 step 1). */
	legacyCandidates: (runId) => json(`/runs/${encodeURIComponent(runId)}/legacy/candidates`),
	openRun: (id) => post(`/runs/${encodeURIComponent(id)}/open`, {}),
	takeTurn: (id, body) => post(`/runs/${encodeURIComponent(id)}/turn`, body),
	scene: async (runId, sceneId) => {
		const res = await fetch(`${API}/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}`);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		return res.text();
	},
	/** The compiled background HTML for a life, as text for a sandbox frame's
	*  srcdoc. Throws on any non-2xx (incl. 404 = no backdrop) so the caller
	*  simply shows no background. */
	backdrop: async (runId) => {
		const res = await fetch(`${API}/runs/${encodeURIComponent(runId)}/backdrop`);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		return res.text();
	},
	answerScene: (runId, sceneId, body) => post(`/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}/answer`, body),
	/** The sparse graph all three star-map lenses share — one request per open. */
	star: (runId) => json(`/runs/${encodeURIComponent(runId)}/memory/star`),
	/** Remember this life's last-used lens. Fire-and-forget metadata. */
	setMemoryView: (runId, view) => send("PATCH", `/runs/${encodeURIComponent(runId)}/preferences/memory-view`, { view }),
	createKeepsake: (runId, body) => post(`/runs/${encodeURIComponent(runId)}/keepsakes`, body),
	updateKeepsake: (runId, keepsakeId, body) => send("PATCH", `/runs/${encodeURIComponent(runId)}/keepsakes/${encodeURIComponent(keepsakeId)}`, body),
	deleteKeepsake: (runId, keepsakeId) => send("DELETE", `/runs/${encodeURIComponent(runId)}/keepsakes/${encodeURIComponent(keepsakeId)}`),
	/** Turn a keepsake into an editable story-card draft (allowlist fixed here). */
	previewStoryCard: (runId, keepsakeId) => post(`/runs/${encodeURIComponent(runId)}/story-cards/preview`, { keepsakeId }),
	/** Narrow, relabel, reorder — the server refuses anything additive. */
	editStoryCard: (runId, cardId, body) => send("PATCH", `/runs/${encodeURIComponent(runId)}/story-cards/${encodeURIComponent(cardId)}`, body),
	/** The browser downloads this URL directly; auth rides on the cookie. */
	storyCardExportUrl: (runId, cardId, format) => `${API}/runs/${encodeURIComponent(runId)}/story-cards/${encodeURIComponent(cardId)}/export?format=${format}`
};
//#endregion
//#region src/strings.ts
var TABLES$1 = {
	zh: {
		"app.title": "无限世界",
		"app.tagline": "走进 AI 创造的世界，经历独一无二的一生。",
		"app.version": "v{version}",
		"app.language": "界面语言",
		"create.title": "创建一个世界",
		"create.subtitle": "粘贴设定 / 规则书，或只写一个点子（一本小说、一句 premise），它会研究并整理成可玩的世界",
		"create.heading": "粘贴设定，或只写一个点子",
		"create.placeholder": "粘贴任何文字，或只写一个点子：\n· 一份世界观设定 / 规则书\n· 一本小说、电影、游戏的名字\n· 一句脑洞或 premise\n它会（必要时上网研究）把它变成一个可以开始人生的世界，去掉不适合游玩的部分，再给你过目。",
		"create.hint": "不用担心格式或长短。哪怕只有一句话或一个作品名，它也会研究并扩写成完整世界；要自己画的界面、纯数值计算等本框架玩不了的内容会被丢掉。",
		"create.submit": "开始整理 →",
		"create.submitting": "整理中…",
		"create.cancel": "取消",
		"create.count": "{n} 字",
		"create.failed": "没能开始整理，请重试",
		"worldDraft.generating": "正在整理你的世界…",
		"worldDraft.reading": "读取设定",
		"worldDraft.writing": "整理结构",
		"worldDraft.steps": "已处理 {n} 步",
		"worldDraft.ready": "整理好了 · 点按过目",
		"worldDraft.readyChip": "待过目",
		"worldDraft.failed": "没能整理成世界",
		"worldDraft.untitled": "未命名的世界",
		"worldDraft.discard": "放弃",
		"worldDraft.discardAria": "放弃草稿 {title}",
		"review.heading": "整理好了 · 过目",
		"review.titleLabel": "世界名（可改）",
		"review.promise": "承诺",
		"review.clock": "时钟",
		"review.styles": "风格",
		"review.opening": "开场",
		"review.endings": "结局",
		"review.endingsN": "{n} 种结局",
		"review.dropped": "已整理 / 丢弃",
		"review.warnings": "提示",
		"review.jump": "想改设定？在对话里继续调整 →",
		"review.jumpHint": "在 KiroCrew 对话侧栏找到「世界工匠」会话，直接告诉它要改什么；改完回到这里刷新即可。",
		"review.jumpMessage": "我想继续调整世界草稿「{title}」（草稿号 {id}）。请先读取它，我想改的是：",
		"review.accept": "接受并加入书架",
		"review.installing": "正在加入…",
		"review.discard": "放弃",
		"review.retry": "再试一次",
		"review.back": "返回",
		"review.leave": "先离开（稍后回来看）",
		"review.stillWorking": "还在整理这个世界，可以先离开，稍后回来。",
		"review.gone": "这个草稿不见了。",
		"review.installFailed": "没能加入书架，请重试或调整后再试。",
		"review.discardFailed": "没能放弃，请重试。",
		"review.failedGeneric": "这段文字没能整理成一个可玩的世界。",
		"review.failedHint": "可以去对话里告诉「世界工匠」怎么改，或放弃重来。",
		"settings.open": "设置",
		"settings.title": "叙事者设置",
		"settings.close": "关闭",
		"settings.model": "模型",
		"settings.modelDefault": "默认（auto）",
		"settings.painterModel": "背景绘制模型",
		"settings.effort": "推理强度",
		"settings.effortDefault": "默认",
		"settings.save": "保存",
		"settings.saved": "已保存",
		"settings.note": "从每条人生的下一回合起生效，包括正在进行的那一条。",
		"delete.cancel": "不删了",
		"delete.changed": "这次没有删掉：这个世界里的人生条数变了。请再确认一遍。",
		"delete.counting": "正在数这个世界里有几条人生…",
		"delete.done": "世界已删除。",
		"delete.doneRestorable": "以后还能把它装回书架。",
		"delete.doneWithLives": "世界已删除，连同 {n} 条人生。",
		"delete.doneWithLivesOne": "世界已删除，连同 {n} 条人生。",
		"delete.forever": "这个世界不是应用自带的，删掉就找不回来了。",
		"delete.go": "删除世界，连同 {n} 条人生",
		"delete.goOne": "删除世界，连同 {n} 条人生",
		"delete.goNoLives": "删除这个世界",
		"delete.inFlight": "这次没有删掉：这个世界还有一个回合没写完。等写完再试一次。",
		"delete.noLives": "这个世界里还没有人活过。删掉它，书架上就没有它了。",
		"delete.restorable": "这个世界是应用自带的，删掉之后还能装回来——但装回来的是最初的样子：你改过的地方和被删掉的人生都不会回来。",
		"delete.title": "删除「{world}」？",
		"delete.withLives": "这个世界里有 {n} 条人生。删掉它，这些人生连同它们已经写下的一切一起消失。",
		"delete.withLivesOne": "这个世界里有 {n} 条人生。删掉它，这些人生连同它们已经写下的一切一起消失。",
		"delete.working": "正在删除…",
		"history.beginning": "已经到这条人生的开头了。",
		"history.chose": "当时你选了：{action}",
		"history.close": "收起前面的回合",
		"history.earlier": "再往前",
		"history.eventsOnly": "只看大事",
		"history.jump": "跳转",
		"history.jumpPlaceholder": "跳到第几回合",
		"history.noEvents": "这条人生还没有留下大事。",
		"history.noMatches": "没有找到包含「{q}」的回合。",
		"history.none": "还没有什么可回顾的——这才是第一个回合。",
		"history.open": "往回读这条人生",
		"history.reading": "正在往回翻…",
		"history.search": "搜索",
		"history.searchClear": "清除",
		"history.searchPlaceholder": "搜索这一生",
		"history.showAll": "看全部回合",
		"history.summaryTitle": "这一生的大事",
		"history.unreadable": "这条人生的过往读不出来。",
		"history.via": "（来自 {source}）",
		"library.backendHint": "书架暂时打不开：{error}。如果错误码是 404，请停用后重新启用这个应用。请求地址：{path}",
		"library.backendSilent": "后端还没有响应。",
		"library.empty": "书架还是空的。第一个世界，正等你推门。",
		"library.lives": "你正在过的人生",
		"library.newerSeed": "「{world}」有了新版本（{installed} → {available}）。你手上的版本不会改变。",
		"library.otherWorlds": "世界列表",
		"library.preparing": "书架正在打开…",
		"library.removed": "「{world}」已从书架移除。",
		"library.restore": "装回书架",
		"library.retry": "重试",
		"life.archive": "归档",
		"life.delete.aria": "删除人生：{name}",
		"life.delete.changed": "这条人生的回合数刚刚变了。请再确认一遍。",
		"life.delete.done": "人生已删除（活了 {n} 个回合）。",
		"life.delete.doneOne": "人生已删除（活了 {n} 个回合）。",
		"life.delete.doneUnborn": "那条还没出生的人生已删除。",
		"life.delete.forever": "它的世界会留下，别的人生也不受影响。但这条人生再也找不回来——它的编年史只有这一份，没有别的副本。",
		"life.delete.go": "删除这条人生",
		"life.delete.inFlight": "这次没有删掉：这条人生还有一个回合没写完。等写完再试一次。",
		"life.delete.months": "「{name}」已经活了 {n} 个回合。删掉它，这些回合里写下的一切都会消失。",
		"life.delete.monthsOne": "「{name}」已经活了 {n} 个回合。删掉它，这些回合里写下的一切都会消失。",
		"life.delete.reading": "正在看这条人生走到了哪一页…",
		"life.delete.short": "删除",
		"life.actions": "{name} 的操作",
		"life.delete.title": "删除这条人生？",
		"life.delete.unborn": "「{name}」还没有出生。删掉它，你留下的开局设定也会一起消失。",
		"life.delete.unreadable": "这条人生已经读不出来了。它打不开，所以只能从这里删掉。",
		"life.ended": "已落幕",
		"life.generating": "这一页正在写…",
		"life.resetChat.short": "清理缓存",
		"life.resetChat.cancel": "先不清理",
		"life.resetChat.working": "正在清理…",
		"life.resetChat.ok": "好",
		"life.resetChat.aria": "清理「{name}」的叙事缓存",
		"life.resetChat.confirm": "清理叙事缓存？故事、状态和历史都会保留——只清掉叙事者积累的对话缓存，下一回合会重新阅读世界规则。",
		"life.resetChat.done": "已清理——下一回合将以干净的缓存继续。",
		"life.resetChat.busy": "这个月正在书写中，落笔后再试。",
		"life.rename.aria": "重命名人生：{name}",
		"life.rename.cancel": "取消",
		"life.rename.placeholder": "给这条人生起个名字",
		"life.rename.save": "保存",
		"life.rename.short": "重命名",
		"life.turn": "第 {turn} 回合",
		"life.unarchive": "取消归档",
		"life.unborn": "序章还没开始",
		"life.unreadable": "这条人生读不出来了",
		"life.waiting": "等你继续",
		"note.dismiss": "知道了",
		"opening.arranging": "这一世的序章正在展开。",
		"opening.backToShelf": "回到书架",
		"opening.begin": "开始这一世",
		"opening.beginning": "正在翻开序章…",
		"opening.continueBirth": "继续序章",
		"opening.custom": "自定义…",
		"opening.customPlaceholder": "写下你自己的答案",
		"opening.hintPick": "挑一个，或者留空让世界替你决定。",
		"opening.hintText": "留空则由世界决定。",
		"opening.keptSafe": "你选的一切都还在。",
		"opening.next": "下一页",
		"opening.notStarted": "序章还没有开始。你留下的选择都替你收好了。",
		"opening.page": "第 {page} / {pages} 页",
		"opening.prev": "上一页",
		"opening.reset": "全部重置",
		"opening.restored": "已恢复你上次的选择。",
		"opening.retry": "再试一次",
		"opening.rollAll": "全部随机",
		"opening.roleHint": "选一个开局原型(可选);它会预填一部分开局,你仍可修改。",
		"opening.roleLabel": "开局原型",
		"opening.rollPage": "本页随机",
		"opening.rollOne": "随机 {label}",
		"opening.sealed": "这一项由世界定下，不由你选。等你出生时才会知道。",
		"opening.silent": "这一世没能开始。",
		"opening.styleHint": "会影响这个世界怎样对待你。",
		"opening.styleLabel": "这一世怎么讲给你听",
		"opening.summaryTitle": "这一世的样子",
		"opening.summaryWorld": "交给世界决定",
		"opening.waiting.0": "来处渐渐有了轮廓…",
		"opening.waiting.1": "身世与际遇正在交汇…",
		"opening.waiting.2": "开端正在故事之外成形…",
		"opening.waiting.3": "命纸已经摊开，第一笔将落未落…",
		"opening.waiting.4": "山河、街巷与星海，正为你让出一个位置…",
		"opening.waiting.5": "线索正从远处系过来…",
		"opening.waiting.6": "故事屏住呼吸，只等这一笔落下…",
		"opening.waiting.7": "时间空出一格，故事正往那里汇拢…",
		"opening.waiting.8": "一条人生的轮廓，正在世界里慢慢落定…",
		"opening.waiting.9": "远近诸事各归其位，你的来路渐渐清晰…",
		"opening.waiting.10": "无数可能散开，又向同一个开端收拢…",
		"opening.waiting.11": "世界翻动旧日历，寻找你到来的那一刻…",
		"opening.waiting.12": "天光未至，故事的边缘已经泛白…",
		"opening.waiting.13": "你还没有出现，属于你的痕迹却已先一步抵达…",
		"opening.waiting.14": "门尚未开，门后的世界已经开始运转…",
		"opening.waiting.15": "一切都在成为过去，而你即将从此刻开始…",
		"play.act": "去做",
		"play.acting": "…",
		"play.actionPlaceholder": "或者，写下别的做法…",
		"play.back": "← 回到书架",
		"play.birthRevealHint": "这不是你的选择，却会成为这条人生的一部分。",
		"play.birthRevealTitle": "出生时，世界替你决定了",
		"play.confirmAct": "按你写的去做？",
		"play.confirmAsk": "确定要这么做吗？",
		"play.confirmNo": "再想想",
		"play.confirmYes": "确定",
		"play.drawerClose": "收起",
		"play.drawerOpen": "看看这一刻的自己",
		"play.endedBadge": "这一生落幕了。",
		"play.endedMeta": "这一生走过了 {turn} 个回合。",
		"play.endedReplay": "在这个世界再活一次",
		"play.endedReplaySame": "以同样的开局再活一次",
		"play.endedShelf": "回到书架",
		"play.echoLine": "往事回响 · 回应的是第 {turn} 页发生的事",
		"play.echoThen": "当时",
		"play.echoYouDid": "你当时的选择",
		"play.echoNow": "此刻",
		"play.echoJump": "回到那一页",
		"play.echoClose": "收起回响",
		"play.generating": "下一页正在落笔。放心离开，归来时故事还在这里。",
		"play.nothingToShow": "这一刻还没有什么可看的——有些面板要等条件满足了才会出现。",
		"play.opening": "正在翻到你留下的那一页…",
		"play.pollHiccup": "连接不稳，正在重试……",
		"play.writingAction": "正在书写你的选择：「{action}」",
		"play.retry": "再试一次",
		"play.rumour": "传闻",
		"play.rumourSuffix": "——只是听说",
		"play.sceneFailed": "这一幕没能画出来。",
		"play.sceneLoading": "这一幕正在画…",
		"play.sceneSending": "正在回应你的选择…",
		"play.sceneTitle": "景象",
		"play.silent": "（这一页还没有内容。）",
		"play.stalled": "这一页没写出来。你写的内容还留着，可以再试一次。",
		"play.turn": "第 {turn} 回合",
		"play.page": "第 {n} 页",
		"play.prevTurn": "上一回合",
		"play.recapDismiss": "先收起",
		"play.recapLastChoice": "你上次的选择：",
		"play.recapRecent": "最近留下的痕迹",
		"play.recapTitle": "回来时，这条人生正停在这里",
		"play.nextTurn": "下一回合",
		"play.unlocked": "新篇已启：{heading}",
		"play.milestone": "达成里程碑 · {label}",
		"play.unlockedMeaning": "从现在起，与这一篇有关的人物、规则和后果，都可以进入这条人生。",
		"play.waiting.0": "选择已定，后续正在推演…",
		"play.waiting.1": "下一步正在暗处成形…",
		"play.waiting.2": "后果正一层层铺开…",
		"play.waiting.3": "旧因追上此刻，新果正在分岔处结下…",
		"play.waiting.4": "这一页还没写完…",
		"play.waiting.5": "世界不会停在原地…",
		"play.waiting.6": "故事越过眼前这一刻，下一幕正在显形…",
		"play.waiting.7": "你看不见的地方，许多细节正在归位…",
		"play.waiting.8": "时间继续向前，变化正在悄然累积…",
		"play.waiting.9": "世界接住了你的选择，正在酝酿回应…",
		"play.waiting.10": "旧的局面正在松动，新的局面尚未定形…",
		"play.waiting.11": "眼前这一刻，正在成为往事…",
		"play.waiting.12": "远处与近处，正沿着各自的方向变化…",
		"play.waiting.13": "笔没有停，下一行却还藏在纸背…",
		"play.waiting.14": "答案尚未显露，变化已经开始…",
		"play.waiting.15": "故事正在收拢这一回的余音…",
		"play.zoomIn": "全屏查看",
		"play.zoomOut": "退出全屏",
		"rail.broken": "另有 {n} 个世界读不出来",
		"rail.close": "关闭",
		"rail.label": "世界与人生",
		"rail.open": "书架",
		"rail.shelf": "← 书架",
		"rail.styles": "{n} 种叙事风格",
		"rail.width": "正文宽度",
		"rail.width.fixed": "固定宽度",
		"rail.width.fluid": "跟随窗口",
		"rail.worlds": "世界",
		"shelf.archived": "已归档（{n}）",
		"shelf.continue": "接着过下去",
		"shelf.ended": "已落幕的人生",
		"shelf.pick": "点左上角的「书架」挑一条人生，或者选一个世界开始新人生。",
		"unit.day": "日",
		"unit.month": "月",
		"unit.season": "季",
		"tab.label": "页面导航",
		"tab.more": "更多",
		"tab.pack": "背包",
		"tab.reading": "书页",
		"tab.starmap": "星图",
		"tab.status": "状态",
		"tab.system": "系统",
		"tab.tasks": "任务",
		"tab.world": "世界",
		"unit.week": "周",
		"unit.year": "年",
		"world.back": "← 返回世界列表",
		"world.cardEnter": "看看这一生可能走向哪里",
		"world.cardFallback": "一段尚未活过的人生，正等着你决定它的方向。",
		"world.cardPossibilities": "在这里，你可能会",
		"world.cardUntold": "这段人生还没有开始",
		"world.delete": "删除这个世界",
		"world.detailLineage": " · 可传承数代",
		"world.detailMeta": "{turn} · {styles} 种叙事风格{lineage}",
		"world.digest": "世界每回合都在变化",
		"world.endings": "{endings} 种结局条件 · 会记住 {save} 类经历",
		"world.laws": "世界法则",
		"world.lineage": "可传承数代",
		"world.languagePick": "这个世界用哪种语言讲述",
		"world.needsNewerCore": "这个世界需要更高版本的应用（最低 {needed}，当前 {local}）。",
		"world.opening": "开局会问你的事",
		"world.worldDecidesHint": "带标记的选项由世界决定，无法手动选择。",
		"world.panelAlways": "始终显示",
		"world.panelConditional": "满足条件才显示",
		"world.panelFields": "{count} 项",
		"world.panels": "你会看到的面板",
		"world.play": "在这个世界活一次",
		"world.roles": "开局原型",
		"world.setting": "世界设定",
		"world.settingOther": "其它",
		"world.plays": "你在这里活过 {n} 次",
		"world.summary": "{groups} 项开局设定 · {panels} 组面板 · {turn}",
		"world.turnUnit": "以{unit}为一回合",
		"world.unopenable": "这个世界打不开：{problem}",
		"world.unreadableDetail": "这次没能读取：{error}",
		"shelf.orderRecent": "最近更新",
		"shelf.orderStarted": "开始时间"
	},
	en: {
		"app.title": "Endless Worlds",
		"app.tagline": "Live a whole life — in a world written by AI, different every time.",
		"app.version": "v{version}",
		"app.language": "Interface language",
		"create.title": "Create a world",
		"create.subtitle": "Paste a setting or rulebook — or just an idea (a novel's name, a premise) — and it researches and shapes it into a playable world",
		"create.heading": "Paste a setting, or just an idea",
		"create.placeholder": "Paste anything, or just an idea:\n· a worldbuilding doc / rulebook\n· the name of a novel, film, or game\n· a one-line premise or prompt\nIt turns that into a world you can start a life in (researching it online when needed), dropping whatever can't be played, then shows you the result.",
		"create.hint": "Don't worry about format or length. Even a single line or a title is enough — it researches and expands it into a full world; things this framework can't play (drawn interfaces, dice math) are dropped.",
		"create.submit": "Shape it →",
		"create.submitting": "Working…",
		"create.cancel": "Cancel",
		"create.count": "{n} chars",
		"create.failed": "Couldn't start — try again",
		"worldDraft.generating": "Shaping your world…",
		"worldDraft.reading": "Reading the text",
		"worldDraft.writing": "Working out the structure",
		"worldDraft.steps": "{n} steps so far",
		"worldDraft.ready": "Ready · tap to review",
		"worldDraft.readyChip": "To review",
		"worldDraft.failed": "Couldn't make a world",
		"worldDraft.untitled": "Untitled world",
		"worldDraft.discard": "Discard",
		"worldDraft.discardAria": "Discard draft {title}",
		"review.heading": "Ready to review",
		"review.titleLabel": "World name (editable)",
		"review.promise": "Promise",
		"review.clock": "Clock",
		"review.styles": "Styles",
		"review.opening": "Opening",
		"review.endings": "Endings",
		"review.endingsN": "{n} endings",
		"review.dropped": "Cleaned up / dropped",
		"review.warnings": "Notes",
		"review.jump": "Want changes? Keep adjusting in chat →",
		"review.jumpHint": "Find the \"worldsmith\" session in the KiroCrew chat sidebar and tell it what to change; refresh here when it's done.",
		"review.jumpMessage": "I'd like to keep adjusting the world draft \"{title}\" (draft {id}). Please read it first — here's what I want to change:",
		"review.accept": "Accept & add to shelf",
		"review.installing": "Adding…",
		"review.discard": "Discard",
		"review.retry": "Try again",
		"review.back": "Back",
		"review.leave": "Leave for now",
		"review.stillWorking": "Still shaping this world — you can leave and come back.",
		"review.gone": "This draft is gone.",
		"review.installFailed": "Couldn't add it to the shelf — try again.",
		"review.discardFailed": "Couldn't discard — try again.",
		"review.failedGeneric": "This text couldn't be shaped into a playable world.",
		"review.failedHint": "Tell the worldsmith how to change it in chat, or discard and start over.",
		"settings.open": "Settings",
		"settings.title": "Narrator settings",
		"settings.close": "Close",
		"settings.model": "Model",
		"settings.modelDefault": "Default (auto)",
		"settings.painterModel": "Backdrop painter model",
		"settings.effort": "Reasoning effort",
		"settings.effortDefault": "Default",
		"settings.save": "Save",
		"settings.saved": "Saved",
		"settings.note": "Applies to the narrator on the next turn of every life, including one already in progress.",
		"delete.cancel": "Keep it",
		"delete.changed": "The delete did not go through: the number of lives in this world changed. Look again before deciding.",
		"delete.counting": "Checking how many lives remain in this world…",
		"delete.done": "The world was deleted.",
		"delete.doneRestorable": "You can restore it to the shelf later.",
		"delete.doneWithLives": "The world was deleted, along with {n} lives.",
		"delete.doneWithLivesOne": "The world was deleted, along with 1 life.",
		"delete.forever": "This world did not come with the app. Deleting it is final.",
		"delete.go": "Delete the world and {n} lives",
		"delete.goOne": "Delete the world and 1 life",
		"delete.goNoLives": "Delete this world",
		"delete.inFlight": "The delete did not go through: a turn is still being written in this world. Try again when it is finished.",
		"delete.noLives": "Nobody has lived in this world yet. Delete it and it leaves the shelf.",
		"delete.restorable": "This world came with the app, so it can be put back — but it returns as it shipped. Your edits do not come back, and neither do the lives.",
		"delete.title": "Delete “{world}”?",
		"delete.withLives": "There are {n} lives in this world. Deleting it ends them, and everything already written in them goes with it.",
		"delete.withLivesOne": "There is 1 life in this world. Deleting it ends that life, and everything already written in it goes with it.",
		"delete.working": "Deleting…",
		"history.beginning": "This is where the life began.",
		"history.chose": "You chose: {action}",
		"history.close": "Hide earlier turns",
		"history.earlier": "Further back",
		"history.eventsOnly": "Big moments only",
		"history.jump": "Jump",
		"history.jumpPlaceholder": "Jump to turn",
		"history.noEvents": "No big moments marked in this life yet.",
		"history.noMatches": "No turns mention “{q}”.",
		"history.none": "No past to read yet — this is the first turn.",
		"history.open": "Read earlier turns",
		"history.reading": "Turning back through the pages…",
		"history.search": "Search",
		"history.searchClear": "Clear",
		"history.searchPlaceholder": "Search this life",
		"history.showAll": "All turns",
		"history.summaryTitle": "The big moments of this life",
		"history.unreadable": "This life's past could not be read.",
		"history.via": " (from {source})",
		"library.backendHint": "{path} → {error}. A 404 means the backend module did not load; a disable→enable cycle reloads it.",
		"library.backendSilent": "The backend has not answered.",
		"library.empty": "The shelf is empty. Your first world is waiting to be opened.",
		"library.lives": "Lives in progress",
		"library.newerSeed": "A newer version of {world} exists ({installed} → {available}). Your copy is left unchanged.",
		"library.otherWorlds": "All worlds",
		"library.preparing": "Opening the shelf…",
		"library.removed": "You removed “{world}”.",
		"library.restore": "Put it back",
		"library.retry": "Retry",
		"life.archive": "Archive",
		"life.delete.aria": "Delete the life: {name}",
		"life.delete.changed": "This life advanced elsewhere, so its turn count changed. Look again before deciding.",
		"life.delete.done": "The life was deleted ({n} turns lived).",
		"life.delete.doneOne": "The life was deleted (1 turn lived).",
		"life.delete.doneUnborn": "The unborn life was deleted.",
		"life.delete.forever": "Its world stays, and so does every other life. But this life cannot be recovered — its chronicle existed only in this one copy.",
		"life.delete.go": "End this life",
		"life.delete.inFlight": "The delete did not go through: a turn is still being written for this life. Try again when it is finished.",
		"life.delete.months": "“{name}” has lived {n} turns. Deleting it erases everything written in them.",
		"life.delete.monthsOne": "“{name}” has lived 1 turn. Deleting it erases everything written in it.",
		"life.delete.reading": "Checking which page this life has reached…",
		"life.delete.short": "Delete",
		"life.actions": "Actions for {name}",
		"life.delete.title": "End this life?",
		"life.delete.unborn": "“{name}” has not been born yet. Deleting it also takes the opening you chose.",
		"life.delete.unreadable": "This life can no longer be read. Since it cannot be opened, this is the only place you can delete it.",
		"life.ended": "Ended",
		"life.generating": "This page is being written…",
		"life.resetChat.short": "Clear cache",
		"life.resetChat.cancel": "Not now",
		"life.resetChat.working": "Clearing…",
		"life.resetChat.ok": "OK",
		"life.resetChat.aria": "Clear the narrator cache for: {name}",
		"life.resetChat.confirm": "Clear the narrator cache? The story, its state and history all stay — only the narrator's accumulated conversation is discarded, and the next turn re-reads the world's rules.",
		"life.resetChat.done": "Cleared — the next turn continues on a clean cache.",
		"life.resetChat.busy": "A month is being written right now; try again when it lands.",
		"life.rename.aria": "Rename the life: {name}",
		"life.rename.cancel": "Cancel",
		"life.rename.placeholder": "Give this life a name",
		"life.rename.save": "Save",
		"life.rename.short": "Rename",
		"life.turn": "Turn {turn}",
		"life.unarchive": "Unarchive",
		"life.unborn": "The prologue has not begun",
		"life.unreadable": "This life can no longer be read",
		"life.waiting": "Waiting for you",
		"note.dismiss": "Dismiss",
		"opening.arranging": "The prologue to this life is unfolding.",
		"opening.backToShelf": "Back to the shelf",
		"opening.begin": "Begin this life",
		"opening.beginning": "Opening the prologue…",
		"opening.continueBirth": "Enter the world",
		"opening.custom": "Something else…",
		"opening.customPlaceholder": "Write your own",
		"opening.hintPick": "Pick one, or leave it for the world to decide.",
		"opening.hintText": "Leave it blank and the world decides.",
		"opening.keptSafe": "Everything you chose is still here.",
		"opening.next": "Next",
		"opening.notStarted": "The prologue has not begun. Everything you chose is still here.",
		"opening.page": "Page {page} of {pages}",
		"opening.prev": "Back",
		"opening.reset": "Reset all",
		"opening.restored": "Your last choices are back.",
		"opening.retry": "Try again",
		"opening.rollAll": "Roll everything",
		"opening.roleHint": "Pick a starting archetype (optional) — it presets part of the opening, which you can still change.",
		"opening.roleLabel": "Starting archetype",
		"opening.rollPage": "Roll this page",
		"opening.rollOne": "Roll {label}",
		"opening.sealed": "The world decides this one, not you. You will find out when this life begins.",
		"opening.silent": "This life could not begin.",
		"opening.styleHint": "This shapes how the world treats you.",
		"opening.styleLabel": "How this life is told",
		"opening.summaryTitle": "This life, before it begins",
		"opening.summaryWorld": "left to the world",
		"opening.waiting.0": "where you came from is taking shape…",
		"opening.waiting.1": "circumstance and chance are converging…",
		"opening.waiting.2": "the beginning is taking shape just beyond the story…",
		"opening.waiting.3": "the page lies open, the first line not yet written…",
		"opening.waiting.4": "mountains, streets, and stars are making room for you…",
		"opening.waiting.5": "threads are drawing in from afar…",
		"opening.waiting.6": "the story holds its breath as the first line forms…",
		"opening.waiting.7": "time makes room, and the story gathers there…",
		"opening.waiting.8": "the shape of a life is settling into the world…",
		"opening.waiting.9": "things near and far find their place; your path grows clearer…",
		"opening.waiting.10": "countless possibilities spread, then gather toward one beginning…",
		"opening.waiting.11": "the world turns through its calendar, searching for your first moment…",
		"opening.waiting.12": "before the light arrives, the edge of the story begins to show…",
		"opening.waiting.13": "you have not appeared, but your traces are already arriving…",
		"opening.waiting.14": "the door is still closed; the world beyond it is already moving…",
		"opening.waiting.15": "everything is becoming the past, and you are about to begin…",
		"play.act": "Do it",
		"play.acting": "…",
		"play.actionPlaceholder": "Or write something else…",
		"play.back": "← Back to the shelf",
		"play.birthRevealHint": "You did not choose this, but it is now part of this life.",
		"play.birthRevealTitle": "At birth, the world decided",
		"play.confirmAct": "Act on what you wrote?",
		"play.confirmAsk": "Do this?",
		"play.confirmNo": "Think again",
		"play.confirmYes": "Do it",
		"play.drawerClose": "Hide",
		"play.drawerOpen": "Look at yourself",
		"play.endedBadge": "This life has come to a close.",
		"play.endedMeta": "This life lasted {turn} turns.",
		"play.endedReplay": "Live again in this world",
		"play.endedReplaySame": "Live again with the same opening",
		"play.endedShelf": "Back to the shelf",
		"play.echoLine": "An echo · this answers what happened on page {turn}",
		"play.echoThen": "Then",
		"play.echoYouDid": "What you chose then",
		"play.echoNow": "Now",
		"play.echoJump": "Back to that page",
		"play.echoClose": "Fold away",
		"play.generating": "The next page is being written. You can leave; the story will be here when you return.",
		"play.nothingToShow": "Nothing to show yet — this life's panels appear once their conditions are met.",
		"play.opening": "Turning to the page where you left off…",
		"play.pollHiccup": "Connection hiccup — retrying…",
		"play.writingAction": "Writing your choice: “{action}”",
		"play.retry": "Try again",
		"play.rumour": "Rumor",
		"play.rumourSuffix": " — only hearsay",
		"play.sceneFailed": "This scene could not be drawn.",
		"play.sceneLoading": "This scene is being drawn…",
		"play.sceneSending": "Responding to your choice…",
		"play.sceneTitle": "Scene",
		"play.silent": "(There is nothing on this page yet.)",
		"play.stalled": "This page did not come through. Your words are still here — try again.",
		"play.turn": "Turn {turn}",
		"play.page": "Page {n}",
		"play.prevTurn": "Previous turn",
		"play.recapDismiss": "Hide for now",
		"play.recapLastChoice": "Last time, you chose:",
		"play.recapRecent": "What the last turns left behind",
		"play.recapTitle": "Where this life left off",
		"play.nextTurn": "Next turn",
		"play.unlocked": "A new chapter opens: {heading}",
		"play.milestone": "Milestone reached · {label}",
		"play.unlockedMeaning": "From now on, the people, rules, and consequences behind this chapter can enter this life.",
		"play.waiting.0": "your choice is set; what follows is being worked out…",
		"play.waiting.1": "the next step is taking shape out of sight…",
		"play.waiting.2": "the consequences are unfolding, layer by layer…",
		"play.waiting.3": "old causes catch up; new outcomes branch away…",
		"play.waiting.4": "this page is not finished yet…",
		"play.waiting.5": "the world will not stand still…",
		"play.waiting.6": "the story moves beyond this moment; the next scene takes shape…",
		"play.waiting.7": "out of sight, the details are falling into place…",
		"play.waiting.8": "time moves on; change gathers quietly…",
		"play.waiting.9": "the world has received your choice and is shaping its answer…",
		"play.waiting.10": "the old shape of things is loosening; the new one is not yet set…",
		"play.waiting.11": "this moment is already becoming the past…",
		"play.waiting.12": "near and far, the world is changing in its own directions…",
		"play.waiting.13": "the pen has not stopped, but the next line is still hidden…",
		"play.waiting.14": "the answer has not appeared, but change has begun…",
		"play.waiting.15": "the story is gathering the echoes of this turn…",
		"play.zoomIn": "Expand",
		"play.zoomOut": "Collapse",
		"rail.broken": "{n} more worlds could not be read",
		"rail.close": "Close",
		"rail.label": "Worlds and lives",
		"rail.open": "Shelf",
		"rail.shelf": "← Home",
		"rail.styles": "{n} styles",
		"rail.width": "Text width",
		"rail.width.fixed": "Fixed measure",
		"rail.width.fluid": "Follow the window",
		"rail.worlds": "Worlds",
		"shelf.archived": "Archived ({n})",
		"shelf.continue": "Carry on",
		"shelf.ended": "Lives that have ended",
		"shelf.pick": "Open the shelf, top left, to pick a life — or open a world.",
		"unit.day": "day",
		"unit.month": "month",
		"unit.season": "season",
		"tab.label": "Sections",
		"tab.more": "More",
		"tab.pack": "Pack",
		"tab.reading": "Story",
		"tab.starmap": "Star map",
		"tab.status": "Status",
		"tab.system": "Systems",
		"tab.tasks": "Tasks",
		"tab.world": "World",
		"unit.week": "week",
		"unit.year": "year",
		"world.back": "← Back to the worlds",
		"world.cardEnter": "See where this life could lead",
		"world.cardFallback": "An unlived life is waiting for you to give it a direction.",
		"world.cardPossibilities": "Here, you might",
		"world.cardUntold": "This life has not begun",
		"world.delete": "Delete this world",
		"world.detailLineage": " · can continue across generations",
		"world.detailMeta": "{turn} · {styles} styles{lineage}",
		"world.digest": "What the world reports each turn",
		"world.endings": "{endings} ending conditions · saves record {save} kinds of content",
		"world.laws": "World laws",
		"world.lineage": "Can continue across generations",
		"world.languagePick": "Language for this world",
		"world.needsNewerCore": "This world needs a newer version of the app (it asks for {needed}, this is {local}).",
		"world.opening": "What the world will ask you",
		"world.worldDecidesHint": "Highlighted choices are decided by the world — you cannot choose them.",
		"world.panelAlways": "always shown",
		"world.panelConditional": "shown when conditions are met",
		"world.panelFields": "{count} entries",
		"world.panels": "What you will see",
		"world.play": "Live a life here",
		"world.roles": "Starting archetypes",
		"world.setting": "The world",
		"world.settingOther": "Other",
		"world.plays": "You have lived here {n} times",
		"world.summary": "{groups} opening settings · {panels} panels · {turn}",
		"world.turnUnit": "one {unit} per turn",
		"world.unopenable": "This world cannot be opened: {problem}",
		"world.unreadableDetail": "This could not be loaded: {error}",
		"shelf.orderRecent": "Recently played",
		"shelf.orderStarted": "When it began"
	}
};
/**
* The language `t()` and `pick()` render in.
*
* Read from module scope so that every call site stays a plain `t('key')` with no
* hook, but it is DRIVEN by React state at the app root (see `LanguageProvider`):
* the root sets this synchronously during its own render, so a change to the world
* being played re-renders the whole tree and this value is already correct on that
* same commit rather than one render late.
*/
var current = "zh";
/** Normalise a world's declared code; unknown codes are not a language we have. */
function asLang(lang) {
	return lang === "zh" || lang === "en" ? lang : null;
}
/** Set the render language synchronously. Called by the root during render, never
*  from an effect — an effect runs after the frame it should have governed. */
function setCurrentLanguage(lang) {
	current = lang;
}
/** Delivers the language setter down the tree so a page that learns its world's
*  language (after a fetch) can apply it without prop-drilling. The re-render is
*  driven by the root's own state, not by this context. */
var LanguageContext = createContext(() => {});
/** The function a page calls to make the app follow its world's language. */
function useSetLanguage() {
	return useContext(LanguageContext);
}
/**
* One string, with `{name}` placeholders filled in.
*
* A missing key returns the key itself rather than an empty string: a screen
* reading `play.turn` is obviously a bug, while a screen with a gap where a
* sentence should be looks like a design choice.
*/
function t(key, vars = {}) {
	const table = TABLES$1[current];
	const fallback = TABLES$1.en;
	return (table[key] ?? fallback[key] ?? key).replace(/\{(\w+)\}/g, (whole, name) => name in vars ? String(vars[name]) : whole);
}
/**
* One of several interchangeable phrasings, picked at random.
*
* How many variants exist is a property of the TABLE, not of this code: the count
* is discovered by walking `<prefix>.0`, `<prefix>.1`, … until a key is missing, so
* adding a seventh way to say "the years slip by" is a one-line edit to a JSON file
* and nothing here changes.
*
* The caller must pick ONCE and hold the result. Calling this during render would
* re-roll on every re-paint, and the page polls every few seconds while a month is
* being written — the phrase would flicker through the whole set.
*/
function pick(prefix, vars = {}) {
	const table = TABLES$1[current];
	const fallback = TABLES$1.en;
	const variants = [];
	for (let i = 0;; i += 1) {
		const key = `${prefix}.${i}`;
		if (!(key in table) && !(key in fallback)) break;
		variants.push(key);
	}
	if (!variants.length) return t(prefix, vars);
	const chosen = variants[Math.floor(Math.random() * variants.length)];
	return t(chosen, vars);
}
//#endregion
//#region src/confirm.tsx
/** Deleting a world — the second ask.
*
* One press, and what it costs stated plainly. A world with no lives in it can be
* reinstalled from its seed; a world holding lives is hours of narrated story no
* seed brings back, so the ask NAMES that — the count, and every life by name and
* month — instead of demanding the title be typed. Retyping a name on screen is a
* ritual a reflex satisfies too, and it taxes every honest deletion to do it.
*
* What the dialog must never do is guess. The life count comes from the server when
* the dialog opens and is sent back as a precondition, so a confirmation always
* names the number the delete will act on. If a life began in another tab in
* between, the server refuses and this dialog re-asks with the new number rather
* than proceeding on the old one.
*/
function DeleteWorldDialog({ worldId, onCancel, onDeleted }) {
	const [facts, setFacts] = useState(null);
	const [phase, setPhase] = useState("loading");
	const [problem, setProblem] = useState("");
	const panel = useRef(null);
	const look = () => {
		api.worldDeletion(worldId).then((f) => {
			setFacts(f);
			setPhase("asking");
		}).catch((e) => {
			setProblem(e.message);
			setPhase("failed");
		});
	};
	useEffect(() => {
		setPhase("loading");
		look();
	}, [worldId]);
	useEffect(() => {
		const onKey = (e) => {
			if (e.key === "Escape") onCancel();
		};
		window.addEventListener("keydown", onKey);
		panel.current?.focus();
		return () => window.removeEventListener("keydown", onKey);
	}, [onCancel]);
	const lives = facts?.liveCount ?? 0;
	const armed = phase === "asking" && !!facts;
	const confirm = () => {
		if (!facts || !armed) return;
		setPhase("working");
		setProblem("");
		api.deleteWorld(worldId, facts.liveCount).then((out) => onDeleted({
			restorable: out.restorable,
			lives: out.livesRemoved.length
		})).catch((e) => {
			const code = e instanceof ApiError ? e.code : "";
			if (code === "lives_changed") {
				setProblem(t("delete.changed"));
				look();
				return;
			}
			if (code === "turn_in_flight") {
				setProblem(t("delete.inFlight"));
				look();
				return;
			}
			setProblem(e.message);
			setPhase("failed");
		});
	};
	return createPortal(/* @__PURE__ */ jsx("div", {
		className: "ew-modal-wrap",
		role: "presentation",
		onClick: onCancel,
		children: /* @__PURE__ */ jsxs("div", {
			className: "ew-modal",
			role: "dialog",
			"aria-modal": "true",
			"aria-label": t("delete.title", { world: facts?.title ?? worldId }),
			tabIndex: -1,
			ref: panel,
			onClick: (e) => e.stopPropagation(),
			children: [
				/* @__PURE__ */ jsx("div", {
					className: "ew-modal-title",
					children: t("delete.title", { world: facts?.title ?? worldId })
				}),
				phase === "loading" ? /* @__PURE__ */ jsx("div", {
					className: "ew-meta",
					children: t("delete.counting")
				}) : null,
				facts ? /* @__PURE__ */ jsxs(Fragment, { children: [
					/* @__PURE__ */ jsx("div", {
						className: "ew-modal-body",
						children: lives === 0 ? t("delete.noLives") : t(lives === 1 ? "delete.withLivesOne" : "delete.withLives", { n: lives })
					}),
					lives ? /* @__PURE__ */ jsx("ul", {
						className: "ew-doomed",
						children: facts.lives.map((l) => /* @__PURE__ */ jsxs("li", { children: [/* @__PURE__ */ jsx("span", {
							className: "ew-doomed-name",
							children: l.subtitle || l.title || l.runId
						}), /* @__PURE__ */ jsx("span", {
							className: "ew-doomed-where",
							children: l.unreadable ? t("life.unreadable") : l.generating ? t("life.generating") : l.ended ? t("life.ended") : t("life.turn", { turn: l.turn })
						})] }, l.runId))
					}) : null,
					/* @__PURE__ */ jsx("div", {
						className: "ew-meta ew-modal-note",
						children: facts.restorable ? t("delete.restorable") : t("delete.forever")
					})
				] }) : null,
				problem ? /* @__PURE__ */ jsx("div", {
					className: "ew-modal-problem",
					children: problem
				}) : null,
				/* @__PURE__ */ jsxs("div", {
					className: "ew-bar ew-modal-bar",
					children: [/* @__PURE__ */ jsx("button", {
						className: "ew-btn",
						type: "button",
						onClick: onCancel,
						children: t("delete.cancel")
					}), /* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-danger",
						type: "button",
						disabled: !armed,
						onClick: confirm,
						children: phase === "working" ? t("delete.working") : lives === 0 ? t("delete.goNoLives") : t(lives === 1 ? "delete.goOne" : "delete.go", { n: lives })
					})]
				})
			]
		})
	}), document.body);
}
//#endregion
//#region src/ui.tsx
function hostUi() {
	try {
		return window.__kirocrew_modules?.["@kirocrew/ui"] ?? null;
	} catch {
		return null;
	}
}
function Chip({ children, accent }) {
	return /* @__PURE__ */ jsx("span", {
		className: `ew-chip${accent ? " ew-chip-accent" : ""}`,
		children
	});
}
/**
* Narration, rendered as the markdown the narrator writes.
*
* Uses the HOST's renderer, and the reason is not convenience: narration is model
* output, and a renderer of my own would be a new, unaudited path from model bytes
* to the DOM. The dashboard already renders model markdown in chat through this
* component, so it is the audited one.
*/
/** A line made only of box-drawing / block-element characters (U+2500–U+259F)
*  and whitespace — a decorative frame the narrator sometimes draws around a
*  title or a status block. Proportional fonts wrap these into broken rectangles,
*  so they are dropped before rendering. Legitimate prose (em dashes, markdown
*  `---` dividers) uses ASCII and is never matched. */
var FRAME_LINE = /^[\s\u2500-\u259F]+$/;
function stripFrames(text) {
	return text.split("\n").filter((line) => !FRAME_LINE.test(line)).join("\n");
}
function Prose({ text }) {
	const Md = hostUi()?.MarkdownRenderer;
	const cleaned = text ? stripFrames(text) : text;
	if (!cleaned) return /* @__PURE__ */ jsx("p", {
		className: "ew-prose ew-prose-plain",
		children: t("play.silent")
	});
	if (!Md) return /* @__PURE__ */ jsx("p", {
		className: "ew-prose ew-prose-plain",
		children: cleaned
	});
	return /* @__PURE__ */ jsx("div", {
		className: "ew-prose",
		children: /* @__PURE__ */ jsx(Md, {
			content: cleaned,
			softBreaks: true
		})
	});
}
var Bar = ({ pct }) => /* @__PURE__ */ jsx("div", {
	className: "ew-bar-track",
	children: /* @__PURE__ */ jsx("div", {
		className: "ew-bar-fill",
		style: { width: `${Math.round(pct * 100)}%` }
	})
});
var Lines = ({ entries, primary, secondary }) => /* @__PURE__ */ jsx("ul", {
	className: "ew-list",
	children: entries.map((e, i) => /* @__PURE__ */ jsxs("li", { children: [String(e[primary] ?? ""), e[secondary] ? /* @__PURE__ */ jsx("span", {
		className: "ew-sub",
		children: ` — ${String(e[secondary])}`
	}) : null] }, `${String(e[primary] ?? "")}-${i}`))
});
/**
* One field, drawn by its PRIMITIVE alone.
*
* There is deliberately no branch on a field's id anywhere below: a world gets its
* panels by declaring them, and the first `if (f.id === 'age')` here would be the
* first world-specific line in the app. The backend shapes the values; this draws.
*/
function Value({ f }) {
	switch (f.kind) {
		case "gap": return /* @__PURE__ */ jsx("span", {
			className: "ew-gap",
			children: "—"
		});
		case "stat":
		case "resource": return /* @__PURE__ */ jsxs("div", { children: [
			/* @__PURE__ */ jsxs("span", { children: [String(f.value), f.max != null ? /* @__PURE__ */ jsx("span", {
				className: "ew-sub",
				children: ` / ${f.max}`
			}) : null] }),
			f.note ? /* @__PURE__ */ jsx("div", {
				className: "ew-sub",
				children: f.note
			}) : null,
			f.pct != null ? /* @__PURE__ */ jsx(Bar, { pct: f.pct }) : null
		] });
		case "trend": return /* @__PURE__ */ jsxs("span", { children: [
			String(f.value ?? ""),
			f.direction ? /* @__PURE__ */ jsx("span", {
				className: "ew-sub",
				children: ` ${f.direction}`
			}) : null,
			f.note ? /* @__PURE__ */ jsx("span", {
				className: "ew-sub",
				children: ` ${f.note}`
			}) : null
		] });
		case "rank": return /* @__PURE__ */ jsxs("span", { children: [f.tier ? String(f.tier) : /* @__PURE__ */ jsx("span", {
			className: "ew-gap",
			children: "—"
		}), f.note ? /* @__PURE__ */ jsx("span", {
			className: "ew-sub",
			children: ` ${f.note}`
		}) : null] });
		case "people": return /* @__PURE__ */ jsx("ul", {
			className: "ew-list",
			children: (f.entries ?? []).map((e, i) => /* @__PURE__ */ jsxs("li", { children: [
				e.name,
				(f.columns ?? []).map((c) => e.cols?.[c] ? /* @__PURE__ */ jsx("span", {
					className: "ew-sub",
					children: ` · ${c}：${e.cols[c]}`
				}, c) : null),
				e.note ? /* @__PURE__ */ jsx("span", {
					className: "ew-sub",
					children: ` — ${e.note}`
				}) : null
			] }, `${e.name}-${i}`))
		});
		case "threads": return /* @__PURE__ */ jsx(Lines, {
			entries: f.entries ?? [],
			primary: "text",
			secondary: "status"
		});
		case "inventory": return /* @__PURE__ */ jsx("div", {
			className: "ew-chips",
			children: (f.items ?? []).map((it, n) => /* @__PURE__ */ jsxs(Chip, { children: [it.name, it.count ? /* @__PURE__ */ jsx("span", {
				className: "ew-sub",
				children: ` ×${it.count}`
			}) : null] }, `${it.name}-${n}`))
		});
		case "field": return /* @__PURE__ */ jsx("span", { children: String(f.value ?? "") });
		case "lines": return /* @__PURE__ */ jsx("div", {
			className: "ew-lines",
			children: (f.lines ?? []).map((ln, i) => /* @__PURE__ */ jsx("div", { children: ln }, `${ln}-${i}`))
		});
		default: return /* @__PURE__ */ jsx("span", {
			className: "ew-sub",
			children: String(f.value ?? "")
		});
	}
}
function PanelBox({ panel }) {
	return /* @__PURE__ */ jsxs("div", {
		className: `ew-panel-box${panel.empty ? " ew-panel-quiet" : ""}`,
		children: [/* @__PURE__ */ jsx("div", {
			className: "ew-panel-box-name",
			children: panel.label || panel.id
		}), (panel.fields ?? []).map((f) => /* @__PURE__ */ jsxs("div", {
			className: `ew-prow${f.label.length > LABEL_COLUMN_CHARS ? " ew-prow-stack" : ""}`,
			children: [/* @__PURE__ */ jsx("div", {
				className: "ew-plabel",
				children: f.label
			}), /* @__PURE__ */ jsx("div", {
				className: "ew-pval",
				children: /* @__PURE__ */ jsx(Value, { f })
			})]
		}, f.id))]
	});
}
/** Labels longer than this stop being column headings and become prose, so the row
*  stacks. Sized to the 5.5em label column: about the point where a CJK label needs
*  a third line beside a one-line value. */
var LABEL_COLUMN_CHARS = 10;
function Glyph({ size = 20 }) {
	return /* @__PURE__ */ jsxs("svg", {
		xmlns: "http://www.w3.org/2000/svg",
		width: size,
		height: size,
		viewBox: "0 0 24 24",
		fill: "none",
		stroke: "var(--accent, #7c3aed)",
		strokeWidth: 1.8,
		strokeLinecap: "round",
		strokeLinejoin: "round",
		"aria-hidden": "true",
		style: { flexShrink: 0 },
		children: [
			/* @__PURE__ */ jsx("path", { d: "M4 4.5A1.5 1.5 0 0 1 5.5 3H19v18H5.5A1.5 1.5 0 0 1 4 19.5z" }),
			/* @__PURE__ */ jsx("path", { d: "M8 3v18" }),
			/* @__PURE__ */ jsx("path", { d: "M12.5 8.5 14 11l2.5.4-1.8 1.8.4 2.5-2.6-1.2-2.6 1.2.4-2.5L8.5 11l2.5-.4z" })
		]
	});
}
/**
* The narrator is working.
*
* Why this exists rather than only disabling the button: a greyed-out row of
* choices says "you cannot act" but not "your choice was taken", and it throws away
* the one thing the player most wants confirmed — WHICH one they picked. So this
* renders next to the chosen option's own label, leaving that label on screen,
* instead of replacing the row with a page-level spinner.
*
* `role="status"` with `aria-live="polite"` because the visual change is the only
* feedback: a screen reader that is never told the turn was accepted has the same
* problem the grey button had, one layer down. The label is the announcement; the
* dots are decoration and are hidden from the accessibility tree.
*/
function Waiting({ label }) {
	return /* @__PURE__ */ jsxs("span", {
		className: "ew-wait",
		role: "status",
		"aria-live": "polite",
		children: [/* @__PURE__ */ jsxs("span", {
			className: "ew-wait-dots",
			"aria-hidden": "true",
			children: [
				/* @__PURE__ */ jsx("i", { className: "ew-dot" }),
				/* @__PURE__ */ jsx("i", { className: "ew-dot" }),
				/* @__PURE__ */ jsx("i", { className: "ew-dot" })
			]
		}), label ? /* @__PURE__ */ jsx("span", {
			className: "ew-wait-label",
			children: label
		}) : null]
	});
}
//#endregion
//#region src/create-world.tsx
/** Creating a world from pasted text.
*
* The player pastes any text; a background "worldsmith" agent cleans out whatever
* this framework cannot play and compiles the rest into a world. The job mirrors
* life-creation: it runs on the server, so the player can leave and come back to a
* draft still being worked, then review and install it. This file holds the four
* surfaces — the shelf entry, the in-progress/ready card, the paste screen, and the
* review — while main.tsx owns the view switching and the shelf poll.
*/
/** Where the half-typed paste is kept, so closing the screen does not lose it.
*  Prefixed because this app shares the dashboard's localStorage. */
var CREATE_DRAFT_KEY = "endless-worlds:create-draft";
/** How often a generating draft is re-checked while the player watches. Matches
*  the play page's GENERATING_POLL_MS. */
var DRAFT_POLL_MS = 3e3;
/** The always-present entry at the top of the worlds shelf. */
function CreateWorldCard({ onClick }) {
	return /* @__PURE__ */ jsxs("button", {
		className: "ew-card ew-card-create",
		type: "button",
		onClick,
		children: [/* @__PURE__ */ jsx("span", {
			className: "ew-create-plus",
			"aria-hidden": "true",
			children: "+"
		}), /* @__PURE__ */ jsxs("span", {
			className: "ew-create-text",
			children: [/* @__PURE__ */ jsx("span", {
				className: "ew-create-title",
				children: t("create.title")
			}), /* @__PURE__ */ jsx("span", {
				className: "ew-create-sub",
				children: t("create.subtitle")
			})]
		})]
	});
}
function draftWhere(d) {
	if (d.status === "ready") return t("worldDraft.ready");
	if (d.status === "failed") return d.problem || t("worldDraft.failed");
	const stage = d.stage === "writing" ? t("worldDraft.writing") : t("worldDraft.reading");
	return d.steps > 0 ? `${stage} · ${t("worldDraft.steps", { n: d.steps })}` : stage;
}
/** A world being built (or one that finished and is waiting to be reviewed). */
function WorldDraftCard({ draft, onOpen, onDiscard }) {
	const generating = draft.status === "generating";
	const pct = Math.min(12 + draft.steps * 16, 92);
	return /* @__PURE__ */ jsxs("div", {
		className: `ew-card ew-card-draft ew-card-draft-${draft.status}`,
		children: [/* @__PURE__ */ jsxs("button", {
			className: "ew-card-open",
			type: "button",
			disabled: generating,
			onClick: () => onOpen(draft.draftId),
			children: [
				/* @__PURE__ */ jsxs("div", {
					className: "ew-titlerow",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-title",
						children: draft.title || t("worldDraft.untitled")
					}), draft.status === "ready" ? /* @__PURE__ */ jsx(Chip, {
						accent: true,
						children: t("worldDraft.readyChip")
					}) : null]
				}),
				/* @__PURE__ */ jsx("div", {
					className: "ew-meta",
					children: draftWhere(draft)
				}),
				generating ? /* @__PURE__ */ jsx("div", {
					className: "ew-progress",
					role: "status",
					"aria-live": "polite",
					children: /* @__PURE__ */ jsx("div", {
						className: "ew-progress-track",
						children: /* @__PURE__ */ jsx("div", {
							className: "ew-progress-fill",
							style: { width: `${pct}%` }
						})
					})
				}) : null
			]
		}), /* @__PURE__ */ jsx("div", {
			className: "ew-life-actions",
			children: /* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-quiet ew-card-drop",
				type: "button",
				"aria-label": t("worldDraft.discardAria", { title: draft.title || "" }),
				onClick: () => onDiscard(draft.draftId),
				children: t("worldDraft.discard")
			})
		})]
	});
}
/** The paste screen (view === 'create'). */
function CreateWorldScreen({ onCancel, onCreated }) {
	const [text, setText] = useState(() => {
		try {
			return window.localStorage.getItem(CREATE_DRAFT_KEY) ?? "";
		} catch {
			return "";
		}
	});
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	useEffect(() => {
		try {
			if (text) window.localStorage.setItem(CREATE_DRAFT_KEY, text);
			else window.localStorage.removeItem(CREATE_DRAFT_KEY);
		} catch {}
	}, [text]);
	const submit = async () => {
		const body = text.trim();
		if (!body || busy) return;
		setBusy(true);
		setError("");
		try {
			const { draftId } = await api.createWorldDraft(body);
			api.compileWorldDraft(draftId);
			try {
				window.localStorage.removeItem(CREATE_DRAFT_KEY);
			} catch {}
			onCreated(draftId);
		} catch (e) {
			setBusy(false);
			setError(e?.body?.error || t("create.failed"));
		}
	};
	const count = [...text.trim()].length;
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-create",
		children: [
			/* @__PURE__ */ jsx("div", {
				className: "ew-section",
				children: t("create.heading")
			}),
			/* @__PURE__ */ jsx("textarea", {
				className: "ew-create-ta",
				value: text,
				onChange: (e) => setText(e.target.value),
				placeholder: t("create.placeholder"),
				autoFocus: true,
				spellCheck: false
			}),
			/* @__PURE__ */ jsx("div", {
				className: "ew-create-hint",
				children: t("create.hint")
			}),
			error ? /* @__PURE__ */ jsx("div", {
				className: "ew-note ew-note-row",
				children: error
			}) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ew-bar",
				children: [
					/* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-quiet",
						type: "button",
						onClick: onCancel,
						disabled: busy,
						children: t("create.cancel")
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-go",
						type: "button",
						onClick: () => void submit(),
						disabled: busy || count === 0,
						children: busy ? t("create.submitting") : t("create.submit")
					}),
					/* @__PURE__ */ jsx("span", {
						className: "ew-create-count",
						children: t("create.count", { n: count })
					})
				]
			})
		]
	});
}
/** The worldsmith agent, as registered by app.json — the agent a jump-to-chat
*  launches so the player keeps adjusting the SAME draft (its tools act by
*  draftId, so a fresh chat carrying the id can read and re-submit it). */
var WORLDSMITH_AGENT = "endless-worldsmith";
/** The host App SDK, reached defensively through the window module map (an older
*  host may not expose the chat launcher — the UI degrades to an inline hint). */
var appSdk = window.__kirocrew_modules?.["@kirocrew/app-sdk"];
/** The review screen (view === 'draft'). Polls until the worldsmith is done, then
*  shows what the world will contain and offers accept / discard / jump-to-chat. */
function WorldDraftReview({ draftId, onInstalled, onDiscarded, onBack }) {
	const [draft, setDraft] = useState(null);
	const [error, setError] = useState("");
	const [title, setTitle] = useState("");
	const [busy, setBusy] = useState("");
	const [chatHint, setChatHint] = useState(false);
	const titleTouched = useRef(false);
	const kicked = useRef(false);
	const launcher = appSdk?.useChatLauncher?.() ?? null;
	const kickCompile = async () => {
		try {
			await api.compileWorldDraft(draftId);
		} catch {
			setDraft((d) => d ? {
				...d,
				status: "failed",
				problem: d.problem || ""
			} : d);
		}
	};
	const retry = async () => {
		kicked.current = true;
		setDraft((d) => d ? {
			...d,
			status: "generating"
		} : d);
		await kickCompile();
		load();
	};
	const load = async () => {
		try {
			const d = await api.worldDraft(draftId);
			setDraft(d);
			if (d.status === "new" && !kicked.current) {
				kicked.current = true;
				kickCompile();
			}
			if (!titleTouched.current) setTitle(d.preview?.title || d.title || "");
		} catch {
			setError(t("review.gone"));
		}
	};
	useEffect(() => {
		load();
	}, [draftId]);
	const generating = draft?.status === "generating" || draft?.status === "new";
	useEffect(() => {
		if (!generating) return void 0;
		const timer = window.setInterval(() => {
			load();
		}, DRAFT_POLL_MS);
		return () => window.clearInterval(timer);
	}, [generating, draftId]);
	const install = async () => {
		if (busy) return;
		setBusy("installing");
		try {
			const { worldId } = await api.installWorldDraft(draftId, title.trim());
			onInstalled(worldId);
		} catch (e) {
			setBusy("");
			setError(e?.body?.error || t("review.installFailed"));
		}
	};
	const discard = async () => {
		if (busy) return;
		setBusy("discarding");
		try {
			await api.discardWorldDraft(draftId);
			onDiscarded();
		} catch {
			setBusy("");
			setError(t("review.discardFailed"));
		}
	};
	/** Keep adjusting in the dashboard chat: launch the worldsmith with a message
	*  naming this draft, so it can re-read and re-submit it. Falls back to an inline
	*  hint on a host without the launcher. */
	const jumpToChat = () => {
		if (!draft) return;
		if (launcher) {
			launcher.openChat({
				agent: WORLDSMITH_AGENT,
				message: t("review.jumpMessage", {
					title: draft.title || draft.preview?.title || "",
					id: draft.draftId
				})
			});
			return;
		}
		setChatHint(true);
	};
	if (error) return /* @__PURE__ */ jsxs("div", {
		className: "ew-create",
		children: [/* @__PURE__ */ jsx("div", {
			className: "ew-note ew-note-row",
			children: error
		}), /* @__PURE__ */ jsx("div", {
			className: "ew-bar",
			children: /* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-quiet",
				type: "button",
				onClick: onBack,
				children: t("review.back")
			})
		})]
	});
	if (!draft || generating) {
		const steps = draft?.steps ?? 0;
		const pct = Math.min(12 + steps * 16, 92);
		return /* @__PURE__ */ jsxs("div", {
			className: "ew-create",
			children: [
				/* @__PURE__ */ jsx("div", {
					className: "ew-section",
					children: t("worldDraft.generating")
				}),
				/* @__PURE__ */ jsx("div", {
					className: "ew-meta",
					children: t("review.stillWorking")
				}),
				/* @__PURE__ */ jsx("div", {
					className: "ew-progress",
					role: "status",
					"aria-live": "polite",
					children: /* @__PURE__ */ jsx("div", {
						className: "ew-progress-track",
						children: /* @__PURE__ */ jsx("div", {
							className: "ew-progress-fill",
							style: { width: `${pct}%` }
						})
					})
				}),
				/* @__PURE__ */ jsx("div", {
					className: "ew-bar",
					children: /* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-quiet",
						type: "button",
						onClick: onBack,
						children: t("review.leave")
					})
				})
			]
		});
	}
	if (draft.status === "failed") return /* @__PURE__ */ jsxs("div", {
		className: "ew-create",
		children: [
			/* @__PURE__ */ jsx("div", {
				className: "ew-section",
				children: t("worldDraft.failed")
			}),
			/* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: draft.problem || t("review.failedGeneric")
			}),
			/* @__PURE__ */ jsx("div", {
				className: "ew-create-hint",
				children: t("review.failedHint")
			}),
			/* @__PURE__ */ jsx("button", {
				className: "ew-draft-jump",
				type: "button",
				onClick: jumpToChat,
				children: t("review.jump")
			}),
			chatHint ? /* @__PURE__ */ jsx("div", {
				className: "ew-create-hint",
				children: t("review.jumpHint")
			}) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ew-bar",
				children: [/* @__PURE__ */ jsx("button", {
					className: "ew-btn",
					type: "button",
					onClick: () => void retry(),
					disabled: !!busy,
					children: t("review.retry")
				}), /* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-quiet",
					type: "button",
					onClick: () => void discard(),
					disabled: !!busy,
					children: t("review.discard")
				})]
			})
		]
	});
	const p = draft.preview;
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-create",
		children: [
			/* @__PURE__ */ jsx("div", {
				className: "ew-section",
				children: t("review.heading")
			}),
			/* @__PURE__ */ jsx("label", {
				className: "ew-create-titlelabel",
				htmlFor: "ew-world-title",
				children: t("review.titleLabel")
			}),
			/* @__PURE__ */ jsx("input", {
				id: "ew-world-title",
				className: "ew-title-edit",
				value: title,
				maxLength: 80,
				onChange: (e) => {
					titleTouched.current = true;
					setTitle(e.target.value);
				}
			}),
			p ? /* @__PURE__ */ jsxs("div", {
				className: "ew-review",
				children: [
					p.promise ? /* @__PURE__ */ jsxs("div", {
						className: "ew-kv",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-k",
							children: t("review.promise")
						}), /* @__PURE__ */ jsx("span", { children: p.promise })]
					}) : null,
					/* @__PURE__ */ jsxs("div", {
						className: "ew-kv",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-k",
							children: t("review.clock")
						}), /* @__PURE__ */ jsx("span", { children: p.clock })]
					}),
					p.styles.length ? /* @__PURE__ */ jsxs("div", {
						className: "ew-kv",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-k",
							children: t("review.styles")
						}), /* @__PURE__ */ jsx("span", {
							className: "ew-chips",
							children: p.styles.map((s) => /* @__PURE__ */ jsx(Chip, { children: s }, s))
						})]
					}) : null,
					p.opening.length ? /* @__PURE__ */ jsxs("div", {
						className: "ew-kv",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-k",
							children: t("review.opening")
						}), /* @__PURE__ */ jsx("span", { children: p.opening.join(" · ") })]
					}) : null,
					/* @__PURE__ */ jsxs("div", {
						className: "ew-kv",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-k",
							children: t("review.endings")
						}), /* @__PURE__ */ jsx("span", { children: t("review.endingsN", { n: p.endings }) })]
					})
				]
			}) : null,
			draft.dropped.length ? /* @__PURE__ */ jsxs("div", {
				className: "ew-review-warn",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-review-warn-h",
					children: t("review.dropped")
				}), /* @__PURE__ */ jsx("ul", {
					className: "ew-list",
					children: draft.dropped.map((d, i) => /* @__PURE__ */ jsx("li", { children: d }, i))
				})]
			}) : null,
			draft.warnings.length ? /* @__PURE__ */ jsxs("div", {
				className: "ew-review-warn",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-review-warn-h",
					children: t("review.warnings")
				}), /* @__PURE__ */ jsx("ul", {
					className: "ew-list",
					children: draft.warnings.map((wn, i) => /* @__PURE__ */ jsx("li", { children: wn }, i))
				})]
			}) : null,
			/* @__PURE__ */ jsx("button", {
				className: "ew-draft-jump",
				type: "button",
				onClick: jumpToChat,
				children: t("review.jump")
			}),
			chatHint ? /* @__PURE__ */ jsx("div", {
				className: "ew-create-hint",
				children: t("review.jumpHint")
			}) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ew-bar",
				children: [/* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-quiet",
					type: "button",
					onClick: () => void discard(),
					disabled: !!busy,
					children: t("review.discard")
				}), /* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-go ew-review-accept",
					type: "button",
					onClick: () => void install(),
					disabled: !!busy,
					children: busy === "installing" ? t("review.installing") : t("review.accept")
				})]
			})
		]
	});
}
//#endregion
//#region src/library.tsx
var TURN_UNITS = {
	month: "unit.month",
	year: "unit.year",
	day: "unit.day",
	week: "unit.week",
	season: "unit.season"
};
/**
* How a language reads in its own tongue. Endonyms are conventionally not
* translated, so they carry no catalog key; an unknown tag shows its own code
* uppercased rather than nothing.
*/
var LANGUAGE_ENDONYM = {
	en: "English",
	zh: "中文",
	ja: "日本語",
	ko: "한국어",
	fr: "Français",
	de: "Deutsch",
	es: "Español",
	"pt-br": "Português",
	ru: "Русский"
};
function languageName(tag) {
	return LANGUAGE_ENDONYM[tag] ?? tag.toUpperCase();
}
/** A three-bar hamburger, drawn rather than imported: this app carries no icon
*  dependency, and an SVG keeps it crisp and theme-coloured (currentColor). */
function MenuGlyph() {
	return /* @__PURE__ */ jsxs("svg", {
		width: "18",
		height: "18",
		viewBox: "0 0 18 18",
		"aria-hidden": "true",
		children: [
			/* @__PURE__ */ jsx("line", {
				x1: "3",
				y1: "5",
				x2: "15",
				y2: "5",
				stroke: "currentColor",
				strokeWidth: "2",
				strokeLinecap: "round"
			}),
			/* @__PURE__ */ jsx("line", {
				x1: "3",
				y1: "9",
				x2: "15",
				y2: "9",
				stroke: "currentColor",
				strokeWidth: "2",
				strokeLinecap: "round"
			}),
			/* @__PURE__ */ jsx("line", {
				x1: "3",
				y1: "13",
				x2: "15",
				y2: "13",
				stroke: "currentColor",
				strokeWidth: "2",
				strokeLinecap: "round"
			})
		]
	});
}
/**
* How a turn reads, in one place.
*
* The card and the detail view used to build this phrase separately, which is how
* the detail view came to print "undefined": it read a field name the card did not
* use.
*/
function turnPhrase(unit) {
	const key = unit ? TURN_UNITS[unit] : void 0;
	return t("world.turnUnit", { unit: key ? t(key) : String(unit ?? "") });
}
/** A world on the shelf. Its own words, never the app's vocabulary. */
function WorldCard({ world, onOpen, plays = 0 }) {
	if (!world.usable) return /* @__PURE__ */ jsxs("div", {
		className: "ew-card ew-card-broken",
		children: [/* @__PURE__ */ jsx("div", {
			className: "ew-title",
			style: { marginBottom: "4px" },
			children: world.title
		}), /* @__PURE__ */ jsx("div", {
			className: "ew-meta",
			children: world.needsCore ? t("world.needsNewerCore", {
				needed: world.needsCore,
				local: world.localCore ?? "?"
			}) : t("world.unopenable", { problem: world.problem ?? "" })
		})]
	});
	const possibilities = (world.cardPossibilities ?? []).filter(Boolean).slice(0, 3);
	const promise = world.cardPromise?.trim() || t("world.cardFallback");
	return /* @__PURE__ */ jsxs("button", {
		className: "ew-card ew-world-card",
		type: "button",
		onClick: () => onOpen(world.worldId),
		children: [/* @__PURE__ */ jsxs("div", {
			className: "ew-world-band",
			children: [/* @__PURE__ */ jsx("span", {
				className: "ew-world-band-title",
				children: world.title
			}), world.lineage ? /* @__PURE__ */ jsx(Chip, {
				accent: true,
				children: t("world.lineage")
			}) : null]
		}), /* @__PURE__ */ jsxs("div", {
			className: "ew-world-body",
			children: [
				/* @__PURE__ */ jsx("div", {
					className: "ew-world-promise",
					children: promise
				}),
				possibilities.length ? /* @__PURE__ */ jsx("div", {
					className: "ew-world-possibilities",
					children: possibilities.map((possibility) => /* @__PURE__ */ jsx("span", {
						className: "ew-world-possibility",
						children: possibility
					}, possibility))
				}) : null,
				/* @__PURE__ */ jsxs("div", {
					className: "ew-world-card-footer",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-meta",
						children: plays > 0 ? t("world.plays", { n: plays }) : t("world.cardUntold")
					}), /* @__PURE__ */ jsxs("span", {
						className: "ew-world-enter",
						children: [t("world.cardEnter"), " →"]
					})]
				})
			]
		})]
	});
}
/**
* A life in progress.
*
* This is the load-bearing half of not losing your place: even if the app forgets
* which screen you were on, the life itself is listed and one tap from where you
* left it.
*/
function LifeRow({ run, onOpen, onDeleted, onArchive, onRename }) {
	const name = run.label || run.subtitle || run.title || run.worldId;
	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState("");
	const commit = () => {
		onRename?.(run.runId, draft.trim());
		setEditing(false);
	};
	const [doom, setDoom] = useState(null);
	const [facts, setFacts] = useState(null);
	const [problem, setProblem] = useState("");
	useEffect(() => {
		if (doom !== "asking" || facts) return;
		let alive = true;
		api.lifeDeletion(run.runId).then((f) => {
			if (alive) setFacts(f);
		}).catch((e) => {
			if (alive) setProblem(e.message);
		});
		return () => {
			alive = false;
		};
	}, [
		doom,
		facts,
		run.runId
	]);
	const endThisLife = () => {
		if (!facts || doom === "working") return;
		setDoom("working");
		setProblem("");
		api.deleteLife(run.runId, facts.turn).then((out) => onDeleted?.(out.turn)).catch((e) => {
			const code = e instanceof ApiError ? e.code : "";
			if (code === "turn_changed" || code === "turn_in_flight") {
				setProblem(t(code === "turn_changed" ? "life.delete.changed" : "life.delete.inFlight"));
				setFacts(null);
				setDoom("asking");
				return;
			}
			setProblem(e.message);
			setDoom("asking");
		});
	};
	const [menuOpen, setMenuOpen] = useState(false);
	const [resetAsk, setResetAsk] = useState(null);
	const [resetProblem, setResetProblem] = useState("");
	const resetStoryteller = () => {
		if (resetAsk === "working") return;
		setResetAsk("working");
		setResetProblem("");
		api.resetConversation(run.runId).then(() => setResetAsk("done")).catch((e) => {
			const code = e instanceof ApiError ? e.code : "";
			setResetProblem(code === "turn_in_flight" ? t("life.resetChat.busy") : e.message);
			setResetAsk("asking");
		});
	};
	const panelRef = useRef(null);
	const kebabRef = useRef(null);
	const [menuAt, setMenuAt] = useState(null);
	useEffect(() => {
		if (!menuOpen) return void 0;
		const close = (e) => {
			const inMenu = panelRef.current?.contains(e.target);
			const onKebab = kebabRef.current?.contains(e.target);
			if (!inMenu && !onKebab) setMenuOpen(false);
		};
		const drop = () => setMenuOpen(false);
		document.addEventListener("mousedown", close);
		window.addEventListener("scroll", drop, true);
		window.addEventListener("resize", drop);
		return () => {
			document.removeEventListener("mousedown", close);
			window.removeEventListener("scroll", drop, true);
			window.removeEventListener("resize", drop);
		};
	}, [menuOpen]);
	const openMenu = () => {
		const r = kebabRef.current?.getBoundingClientRect();
		if (r) setMenuAt({
			top: r.bottom + 6,
			right: Math.max(8, window.innerWidth - r.right)
		});
		setMenuOpen((o) => !o);
	};
	const actions = [];
	if (onRename) actions.push({
		key: "rename",
		label: t("life.rename.short"),
		aria: t("life.rename.aria", { name }),
		onClick: () => {
			setDraft(run.label || "");
			setEditing(true);
		}
	});
	if (onArchive) actions.push({
		key: "archive",
		label: run.archived ? t("life.unarchive") : t("life.archive"),
		onClick: () => onArchive(run.runId, !run.archived)
	});
	if (onArchive && !run.unreadable) actions.push({
		key: "resetChat",
		label: t("life.resetChat.short"),
		aria: t("life.resetChat.aria", { name }),
		onClick: () => {
			setResetProblem("");
			setResetAsk("asking");
		}
	});
	if (onDeleted) actions.push({
		key: "delete",
		label: t("life.delete.short"),
		aria: t("life.delete.aria", { name }),
		onClick: () => {
			setProblem("");
			setFacts(null);
			setDoom("asking");
		}
	});
	const where = run.unreadable ? t("life.unreadable") : run.generating ? t("life.generating") : run.ended ? t("life.ended") : run.awaitingOpening ? t("life.unborn") : t("life.turn", { turn: run.turn });
	if (editing) return /* @__PURE__ */ jsxs("div", {
		className: "ew-card ew-card-row",
		children: [
			/* @__PURE__ */ jsx("input", {
				className: "ew-rename-input",
				value: draft,
				maxLength: 60,
				autoFocus: true,
				placeholder: t("life.rename.placeholder"),
				onChange: (e) => setDraft(e.target.value),
				onKeyDown: (e) => {
					if (e.key === "Enter") commit();
					if (e.key === "Escape") setEditing(false);
				}
			}),
			/* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-sm ew-btn-go",
				type: "button",
				onClick: commit,
				children: t("life.rename.save")
			}),
			/* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-sm",
				type: "button",
				onClick: () => setEditing(false),
				children: t("life.rename.cancel")
			})
		]
	});
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-card ew-card-row",
		children: [
			run.backdrop ? /* @__PURE__ */ jsxs("div", {
				className: "ew-card-bgclip",
				"aria-hidden": "true",
				children: [/* @__PURE__ */ jsx("img", {
					className: "ew-card-bg",
					src: `${API}/runs/${encodeURIComponent(run.runId)}/backdrop?v=${run.backdrop.version}`,
					alt: "",
					draggable: false
				}), /* @__PURE__ */ jsx("div", { className: "ew-card-bg-scrim" })]
			}) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ew-card-rowmain",
				children: [/* @__PURE__ */ jsxs("button", {
					className: "ew-card-open",
					type: "button",
					disabled: !!run.unreadable,
					onClick: () => onOpen(run.runId),
					children: [
						/* @__PURE__ */ jsxs("div", {
							className: "ew-titlerow",
							children: [/* @__PURE__ */ jsx("span", {
								className: "ew-title",
								children: name
							}), run.awaitingOpening ? /* @__PURE__ */ jsx(Chip, {
								accent: true,
								children: t("life.waiting")
							}) : null]
						}),
						name !== run.title ? /* @__PURE__ */ jsx("div", {
							className: "ew-sub",
							children: run.title
						}) : null,
						/* @__PURE__ */ jsx("div", {
							className: "ew-meta",
							children: where
						})
					]
				}), actions.length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("div", {
					className: "ew-life-actions",
					children: actions.map((a) => /* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-quiet ew-card-drop",
						type: "button",
						"aria-label": a.aria,
						onClick: a.onClick,
						children: a.label
					}, a.key))
				}), /* @__PURE__ */ jsxs("div", {
					className: "ew-life-menu",
					children: [/* @__PURE__ */ jsx("button", {
						ref: kebabRef,
						className: "ew-kebab",
						type: "button",
						"aria-haspopup": "menu",
						"aria-expanded": menuOpen,
						"aria-label": t("life.actions", { name }),
						onClick: openMenu,
						children: /* @__PURE__ */ jsx(MenuGlyph, {})
					}), menuOpen && menuAt ? createPortal(/* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("div", {
						className: "ew-menu-backdrop",
						"aria-hidden": "true",
						onClick: () => setMenuOpen(false)
					}), /* @__PURE__ */ jsx("div", {
						className: "ew-menu",
						role: "menu",
						ref: panelRef,
						style: {
							top: `${menuAt.top}px`,
							right: `${menuAt.right}px`
						},
						children: actions.map((a) => /* @__PURE__ */ jsx("button", {
							className: "ew-menu-item",
							role: "menuitem",
							type: "button",
							"aria-label": a.aria,
							onClick: (e) => {
								e.stopPropagation();
								setMenuOpen(false);
								a.onClick();
							},
							onTouchEnd: (e) => {
								e.preventDefault();
								e.stopPropagation();
								setMenuOpen(false);
								a.onClick();
							},
							children: a.label
						}, a.key))
					})] }), document.body) : null]
				})] }) : null]
			}),
			doom ? /* @__PURE__ */ jsxs("div", {
				className: "ew-rowdoom",
				role: "group",
				"aria-label": t("life.delete.title"),
				children: [
					/* @__PURE__ */ jsx("div", {
						className: "ew-rowdoom-say",
						children: !facts ? t("life.delete.reading") : facts.unreadable ? t("life.delete.unreadable") : facts.turn > 0 ? t(facts.turn === 1 ? "life.delete.monthsOne" : "life.delete.months", {
							name,
							n: facts.turn
						}) : t("life.delete.unborn", { name })
					}),
					/* @__PURE__ */ jsx("div", {
						className: "ew-meta ew-rowdoom-note",
						children: t("life.delete.forever")
					}),
					problem ? /* @__PURE__ */ jsx("div", {
						className: "ew-modal-problem",
						children: problem
					}) : null,
					/* @__PURE__ */ jsxs("div", {
						className: "ew-rowdoom-bar",
						children: [/* @__PURE__ */ jsx("button", {
							className: "ew-btn ew-btn-sm",
							type: "button",
							onClick: () => {
								setDoom(null);
								setProblem("");
							},
							children: t("delete.cancel")
						}), /* @__PURE__ */ jsx("button", {
							className: "ew-btn ew-btn-sm ew-btn-danger",
							type: "button",
							disabled: !facts || doom === "working",
							onClick: endThisLife,
							children: doom === "working" ? t("delete.working") : t("life.delete.go")
						})]
					})
				]
			}) : null,
			resetAsk ? /* @__PURE__ */ jsxs("div", {
				className: "ew-rowdoom",
				role: "group",
				"aria-label": t("life.resetChat.short"),
				children: [
					/* @__PURE__ */ jsx("div", {
						className: "ew-rowdoom-say",
						children: resetAsk === "done" ? t("life.resetChat.done") : t("life.resetChat.confirm")
					}),
					resetProblem ? /* @__PURE__ */ jsx("div", {
						className: "ew-modal-problem",
						children: resetProblem
					}) : null,
					/* @__PURE__ */ jsx("div", {
						className: "ew-rowdoom-bar",
						children: resetAsk === "done" ? /* @__PURE__ */ jsx("button", {
							className: "ew-btn ew-btn-sm",
							type: "button",
							onClick: () => setResetAsk(null),
							children: t("life.resetChat.ok")
						}) : /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("button", {
							className: "ew-btn ew-btn-sm",
							type: "button",
							onClick: () => {
								setResetAsk(null);
								setResetProblem("");
							},
							children: t("life.resetChat.cancel")
						}), /* @__PURE__ */ jsx("button", {
							className: "ew-btn ew-btn-sm",
							type: "button",
							disabled: resetAsk === "working",
							onClick: resetStoryteller,
							children: resetAsk === "working" ? t("life.resetChat.working") : t("life.resetChat.short")
						})] })
					})
				]
			}) : null
		]
	});
}
/** The world's setting as a browsable, grouped structure — the reader-facing face
*  of the world's `lore`. Grouped by category; each entry expands to its body, and
*  its relations to other entries are shown as a small edge list. */
function WorldSetting({ lore }) {
	const [open, setOpen] = useState({});
	const names = new Map(lore.map((e) => [e.id, e.name]));
	const order = [];
	const groups = /* @__PURE__ */ new Map();
	for (const e of lore) {
		const cat = e.category || t("world.settingOther");
		if (!groups.has(cat)) {
			groups.set(cat, []);
			order.push(cat);
		}
		groups.get(cat).push(e);
	}
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-setting",
		style: { marginTop: "18px" },
		children: [/* @__PURE__ */ jsx("div", {
			className: "ew-section",
			children: t("world.setting")
		}), order.map((cat) => /* @__PURE__ */ jsxs("div", {
			className: "ew-setting-group",
			children: [/* @__PURE__ */ jsx("div", {
				className: "ew-glabel",
				children: cat
			}), (groups.get(cat) ?? []).map((e) => /* @__PURE__ */ jsxs("div", {
				className: "ew-setting-entry",
				children: [/* @__PURE__ */ jsxs("button", {
					className: "ew-setting-head",
					type: "button",
					"aria-expanded": !!open[e.id],
					onClick: () => setOpen((o) => ({
						...o,
						[e.id]: !o[e.id]
					})),
					children: [
						/* @__PURE__ */ jsx("span", {
							className: "ew-setting-name",
							children: e.name
						}),
						e.summary ? /* @__PURE__ */ jsx("span", {
							className: "ew-setting-sum",
							children: e.summary
						}) : null,
						/* @__PURE__ */ jsx("span", {
							className: "ew-setting-caret",
							"aria-hidden": "true"
						})
					]
				}), open[e.id] ? /* @__PURE__ */ jsxs("div", {
					className: "ew-setting-body",
					children: [/* @__PURE__ */ jsx(Prose, { text: e.text }), e.relations.length ? /* @__PURE__ */ jsx("div", {
						className: "ew-setting-rel",
						children: e.relations.map((r, i) => /* @__PURE__ */ jsxs("span", {
							className: "ew-chip",
							children: [r.label ? `${r.label} · ` : "", names.get(r.to) ?? r.to]
						}, `${r.to}-${i}`))
					}) : null]
				}) : null]
			}, e.id))]
		}, cat))]
	});
}
function WorldDetailView({ worldId, onBack, onPlay, onDelete, onLanguage, initialLanguage }) {
	const [world, setWorld] = useState(null);
	const [error, setError] = useState(null);
	const [nonce, setNonce] = useState(0);
	const [laws, setLaws] = useState(false);
	const [language, setLanguage] = useState(initialLanguage);
	useEffect(() => {
		let alive = true;
		setWorld(null);
		setError(null);
		api.world(worldId, true, language).then((w) => {
			if (alive) {
				setWorld(w);
				if (w.language) onLanguage?.(w.language);
			}
		}).catch((e) => {
			if (alive) setError(e.message);
		});
		return () => {
			alive = false;
		};
	}, [
		worldId,
		nonce,
		language
	]);
	const back = /* @__PURE__ */ jsx("button", {
		className: "ew-back",
		type: "button",
		onClick: onBack,
		children: t("world.back")
	});
	if (error) return /* @__PURE__ */ jsxs("div", { children: [
		back,
		/* @__PURE__ */ jsx("div", {
			className: "ew-meta",
			children: t("world.unreadableDetail", { error })
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-bar",
			children: /* @__PURE__ */ jsx("button", {
				className: "ew-btn",
				type: "button",
				onClick: () => setNonce((n) => n + 1),
				children: t("library.retry")
			})
		})
	] });
	if (!world) return /* @__PURE__ */ jsxs("div", { children: [back, /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("library.preparing")
	})] });
	const styleRows = world.styleRows ?? [];
	const groups = world.opening ?? [];
	return /* @__PURE__ */ jsxs("div", { children: [
		back,
		/* @__PURE__ */ jsx("h3", {
			className: "ew-detail-title",
			children: world.title
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-meta",
			style: { marginBottom: "18px" },
			children: t("world.detailMeta", {
				turn: turnPhrase(world.clockUnit),
				styles: styleRows.length,
				lineage: world.lineage ? t("world.detailLineage") : ""
			})
		}),
		(world.languages ?? []).length > 1 ? /* @__PURE__ */ jsxs("div", {
			className: "ew-block",
			children: [/* @__PURE__ */ jsx("div", {
				className: "ew-section",
				children: t("world.languagePick")
			}), /* @__PURE__ */ jsx("div", {
				className: "ew-chips",
				role: "group",
				"aria-label": t("world.languagePick"),
				children: (world.languages ?? []).map((lg) => /* @__PURE__ */ jsx("button", {
					type: "button",
					className: "ew-lang",
					"aria-pressed": world.language === lg,
					onClick: () => setLanguage(lg),
					children: languageName(lg)
				}, lg))
			})]
		}) : null,
		/* @__PURE__ */ jsx("div", {
			className: "ew-section",
			children: t("world.opening")
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-chips ew-block",
			children: groups.map((g) => /* @__PURE__ */ jsx(Chip, {
				accent: g.worldDecides,
				children: g.label
			}, g.id))
		}),
		groups.some((g) => g.worldDecides) ? /* @__PURE__ */ jsx("div", {
			className: "ew-hint ew-block",
			children: t("world.worldDecidesHint")
		}) : null,
		/* @__PURE__ */ jsx("div", {
			className: "ew-section",
			children: t("world.panels")
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-block",
			children: (world.panels ?? []).map((p) => /* @__PURE__ */ jsxs("div", {
				className: "ew-panel",
				children: [/* @__PURE__ */ jsxs("div", {
					className: "ew-panel-head",
					children: [
						/* @__PURE__ */ jsx("span", {
							className: "ew-panel-name",
							children: p.label || p.id
						}),
						/* @__PURE__ */ jsx(Chip, {
							accent: p.always,
							children: p.always ? t("world.panelAlways") : t("world.panelConditional")
						}),
						/* @__PURE__ */ jsx("span", {
							style: {
								fontSize: "11px",
								color: "var(--muted, #6b7280)"
							},
							children: t("world.panelFields", { count: p.fields.length })
						})
					]
				}), /* @__PURE__ */ jsx("div", {
					className: "ew-chips",
					children: p.fields.map((f) => /* @__PURE__ */ jsx(Chip, { children: f.label }, f.id))
				})]
			}, p.id))
		}),
		(world.digest ?? []).length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("div", {
			className: "ew-section",
			children: t("world.digest")
		}), /* @__PURE__ */ jsx("div", {
			className: "ew-chips ew-block",
			children: (world.digest ?? []).map((c) => /* @__PURE__ */ jsx(Chip, { children: c }, c))
		})] }) : null,
		/* @__PURE__ */ jsx("div", {
			className: "ew-meta",
			children: t("world.endings", {
				endings: (world.endings ?? []).length,
				save: (world.save ?? []).length
			})
		}),
		world.lore?.length ? /* @__PURE__ */ jsx(WorldSetting, { lore: world.lore }) : null,
		world.roles?.length ? /* @__PURE__ */ jsxs("div", {
			className: "ew-roles",
			style: { marginTop: "18px" },
			children: [/* @__PURE__ */ jsx("div", {
				className: "ew-section",
				children: t("world.roles")
			}), /* @__PURE__ */ jsx("div", {
				className: "ew-block",
				children: (world.roles ?? []).map((r) => /* @__PURE__ */ jsxs("div", {
					className: "ew-role",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-role-name",
						children: r.name
					}), r.summary ? /* @__PURE__ */ jsx("span", {
						className: "ew-role-sum",
						children: r.summary
					}) : null]
				}, r.id))
			})]
		}) : null,
		world.prose ? /* @__PURE__ */ jsx("div", {
			className: "ew-setting",
			style: { marginTop: "18px" },
			children: /* @__PURE__ */ jsxs("div", {
				className: "ew-setting-entry",
				children: [/* @__PURE__ */ jsxs("button", {
					className: "ew-setting-head",
					type: "button",
					"aria-expanded": laws,
					onClick: () => setLaws((v) => !v),
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-setting-name",
						children: t("world.laws")
					}), /* @__PURE__ */ jsx("span", {
						className: "ew-setting-caret",
						"aria-hidden": "true"
					})]
				}), laws ? /* @__PURE__ */ jsx("div", {
					className: "ew-setting-body",
					children: /* @__PURE__ */ jsx(Prose, { text: world.prose })
				}) : null]
			})
		}) : null,
		/* @__PURE__ */ jsxs("div", {
			className: "ew-bar",
			children: [/* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-go",
				type: "button",
				onClick: () => onPlay(world),
				children: t("world.play")
			}), /* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-quiet",
				type: "button",
				onClick: () => onDelete(world.worldId),
				children: t("world.delete")
			})]
		})
	] });
}
//#endregion
//#region src/opening.tsx
var PER_PAGE = 4;
/** Sentinel for "I want to type my own", never a real option value. */
var CUSTOM = "\0custom";
/** Where a half-finished opening is kept. Prefixed: this app shares the
*  dashboard's localStorage. */
var DRAFT_PREFIX = "endless-worlds:where:draft:";
/** How long an abandoned opening draft is honoured. A draft is a convenience for
*  coming back in a day or two, not a permanent resident of shared localStorage —
*  after this it is ignored on read (and overwritten on the next real edit). */
var DRAFT_TTL_MS = 2592e6;
function readDraft(key) {
	try {
		const d = JSON.parse(localStorage.getItem(key) ?? "null") ?? {};
		if (typeof d.savedAt === "number" && Date.now() - d.savedAt > DRAFT_TTL_MS) return {};
		return d;
	} catch {
		return {};
	}
}
/**
* One opening group.
*
* A group the world reserves for itself renders as a sealed note, not a picker:
* offering a choice the world already made would be a lie about who decided.
*/
function Group({ group, value, custom, onPick, onCustom }) {
	if (group.worldDecides) return /* @__PURE__ */ jsxs("div", {
		className: "ew-group",
		children: [/* @__PURE__ */ jsx("div", {
			className: "ew-glabel",
			children: group.label
		}), /* @__PURE__ */ jsx("div", {
			className: "ew-sealed",
			children: t("opening.sealed")
		})]
	});
	const picking = group.kind === "pick" && group.options.length > 0;
	const isCustom = value === CUSTOM;
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-group",
		children: [
			/* @__PURE__ */ jsx("div", {
				className: "ew-glabel",
				children: group.label
			}),
			/* @__PURE__ */ jsx("div", {
				className: "ew-ghint",
				children: picking ? t("opening.hintPick") : t("opening.hintText")
			}),
			picking ? /* @__PURE__ */ jsxs("div", { children: [/* @__PURE__ */ jsxs("div", {
				className: "ew-chips",
				children: [group.options.map((o) => /* @__PURE__ */ jsx("button", {
					type: "button",
					className: `ew-opt${value === o ? " ew-opt-on" : ""}`,
					"aria-pressed": value === o,
					onClick: () => onPick(value === o ? "" : o),
					children: o
				}, o)), group.custom ? /* @__PURE__ */ jsx("button", {
					type: "button",
					className: `ew-opt${isCustom ? " ew-opt-on" : ""}`,
					"aria-pressed": isCustom,
					onClick: () => onPick(isCustom ? "" : CUSTOM),
					children: t("opening.custom")
				}) : null]
			}), isCustom ? /* @__PURE__ */ jsx("input", {
				className: "ew-input",
				style: { marginTop: "8px" },
				value: custom ?? "",
				maxLength: 200,
				"aria-label": group.label,
				placeholder: t("opening.customPlaceholder"),
				onChange: (e) => onCustom(e.target.value)
			}) : null] }) : /* @__PURE__ */ jsx("input", {
				className: "ew-input",
				type: "text",
				inputMode: group.kind === "number" ? "numeric" : "text",
				value: value === CUSTOM ? "" : value ?? "",
				maxLength: 200,
				"aria-label": group.label,
				onChange: (e) => onPick(e.target.value)
			})
		]
	});
}
function OpeningScreen({ world, onBack, onLive }) {
	const draftKey = `${DRAFT_PREFIX}${world.worldId}`;
	const [draft] = useState(() => readDraft(draftKey));
	const styleRows = world.styleRows ?? [];
	const [answers, setAnswers] = useState(draft.answers ?? {});
	const [customs, setCustoms] = useState(draft.customs ?? {});
	const [style, setStyle] = useState(draft.style ?? (styleRows.find((s) => s.default) ?? styleRows[0])?.id ?? "");
	const [role, setRole] = useState(draft.role ?? "");
	const [page, setPage] = useState(draft.page ?? 0);
	const [busy, setBusy] = useState("");
	const [failed, setFailed] = useState(null);
	const run = draft.run ?? null;
	const [restored, setRestored] = useState(() => Object.keys(draft.answers ?? {}).length > 0 || Object.keys(draft.customs ?? {}).length > 0 || !!draft.run || (draft.page ?? 0) > 0);
	useEffect(() => {
		try {
			localStorage.setItem(draftKey, JSON.stringify({
				answers,
				customs,
				style,
				role,
				page,
				run,
				savedAt: Date.now()
			}));
		} catch {}
	}, [
		draftKey,
		answers,
		customs,
		style,
		role,
		page,
		run
	]);
	const clearDraft = () => {
		try {
			localStorage.removeItem(draftKey);
		} catch {}
	};
	const defaultStyle = (styleRows.find((s) => s.default) ?? styleRows[0])?.id ?? "";
	const dirty = Object.keys(answers).length > 0 || Object.keys(customs).length > 0;
	const resetAll = () => {
		setAnswers({});
		setCustoms({});
		setStyle(defaultStyle);
		setRole("");
		setPage(0);
		setRestored(false);
	};
	const groups = world.opening ?? [];
	const pages = Math.max(1, Math.ceil(groups.length / PER_PAGE));
	const slice = groups.slice(page * PER_PAGE, page * PER_PAGE + PER_PAGE);
	const last = page >= pages - 1;
	const rollableHere = slice.filter((g) => !g.worldDecides && g.options.length > 0);
	const rollOne = (g) => {
		const pick = g.options[Math.floor(Math.random() * g.options.length)];
		if (pick) setAnswers((a) => ({
			...a,
			[g.id]: pick
		}));
	};
	const rollPage = () => {
		const next = {};
		rollableHere.forEach((g) => {
			const pick = g.options[Math.floor(Math.random() * g.options.length)];
			if (pick) next[g.id] = pick;
		});
		setAnswers((a) => ({
			...a,
			...next
		}));
	};
	/** Blanks are omitted entirely — an omitted group means "the world decides" —
	*  and a group the world reserves is never sent, because the backend refuses it. */
	const payload = () => {
		const out = {};
		groups.forEach((g) => {
			if (g.worldDecides) return;
			const v = answers[g.id];
			if (v === CUSTOM) {
				const text = (customs[g.id] ?? "").trim();
				if (text) out[g.id] = text;
				return;
			}
			if (typeof v === "string" && v.trim()) out[g.id] = v.trim();
		});
		return out;
	};
	const openRun = async (runId) => {
		setBusy("opening");
		setFailed(null);
		try {
			const out = await api.openRun(runId);
			if (out.advanced || out.reason === "already") {
				clearDraft();
				onLive(runId);
				return;
			}
			setFailed(t("opening.silent"));
		} catch {
			setFailed(t("opening.silent"));
		}
		setBusy("");
	};
	const begin = async () => {
		setBusy("creating");
		setFailed(null);
		try {
			const created = await api.createRun({
				worldId: world.worldId,
				style,
				answers: payload(),
				language: world.language,
				role: role || void 0
			});
			api.openRun(created.runId);
			clearDraft();
			onLive(created.runId);
		} catch (e) {
			setFailed(e.message);
			setBusy("");
		}
	};
	if (busy === "opening" && !failed) return /* @__PURE__ */ jsxs("div", { children: [/* @__PURE__ */ jsx("div", {
		className: "ew-detail-title",
		children: world.title
	}), /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("opening.arranging")
	})] });
	if (failed && run) return /* @__PURE__ */ jsxs("div", { children: [
		/* @__PURE__ */ jsx("div", {
			className: "ew-detail-title",
			children: world.title
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-note",
			children: `${failed}${t("opening.keptSafe")}`
		}),
		/* @__PURE__ */ jsxs("div", {
			className: "ew-bar",
			children: [/* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-go",
				type: "button",
				onClick: () => openRun(run),
				children: t("opening.retry")
			}), /* @__PURE__ */ jsx("button", {
				className: "ew-btn",
				type: "button",
				onClick: onBack,
				children: t("opening.backToShelf")
			})]
		})
	] });
	return /* @__PURE__ */ jsxs("div", { children: [
		/* @__PURE__ */ jsx("button", {
			className: "ew-back",
			type: "button",
			onClick: onBack,
			children: t("world.back")
		}),
		/* @__PURE__ */ jsx("h3", {
			className: "ew-detail-title",
			children: world.title
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-meta",
			style: { marginBottom: "18px" },
			children: t("opening.page", {
				page: page + 1,
				pages
			})
		}),
		restored ? /* @__PURE__ */ jsxs("div", {
			className: "ew-note ew-note-row",
			children: [/* @__PURE__ */ jsx("span", { children: t("opening.restored") }), /* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-quiet",
				type: "button",
				onClick: () => setRestored(false),
				children: t("note.dismiss")
			})]
		}) : null,
		page === 0 && (world.roles?.length ?? 0) > 0 ? /* @__PURE__ */ jsxs("div", {
			className: "ew-group",
			children: [
				/* @__PURE__ */ jsx("div", {
					className: "ew-glabel",
					children: t("opening.roleLabel")
				}),
				/* @__PURE__ */ jsx("div", {
					className: "ew-ghint",
					children: t("opening.roleHint")
				}),
				/* @__PURE__ */ jsx("div", {
					className: "ew-chips",
					children: (world.roles ?? []).map((r) => /* @__PURE__ */ jsx("button", {
						type: "button",
						className: `ew-opt${role === r.id ? " ew-opt-on" : ""}`,
						"aria-pressed": role === r.id,
						onClick: () => setRole(role === r.id ? "" : r.id),
						children: r.name
					}, r.id))
				}),
				role ? /* @__PURE__ */ jsx("div", {
					className: "ew-role-sum",
					style: { marginTop: "8px" },
					children: (world.roles ?? []).find((r) => r.id === role)?.summary
				}) : null
			]
		}) : null,
		slice.map((g) => /* @__PURE__ */ jsx(Group, {
			group: g,
			value: answers[g.id],
			custom: customs[g.id],
			onPick: (v) => setAnswers((a) => ({
				...a,
				[g.id]: v
			})),
			onCustom: (v) => setCustoms((c) => ({
				...c,
				[g.id]: v
			}))
		}, g.id)),
		last ? /* @__PURE__ */ jsxs("div", {
			className: "ew-group",
			children: [
				/* @__PURE__ */ jsx("div", {
					className: "ew-glabel",
					children: t("opening.styleLabel")
				}),
				/* @__PURE__ */ jsx("div", {
					className: "ew-ghint",
					children: t("opening.styleHint")
				}),
				/* @__PURE__ */ jsx("div", {
					className: "ew-chips",
					children: styleRows.map((s) => /* @__PURE__ */ jsx("button", {
						type: "button",
						className: `ew-opt${style === s.id ? " ew-opt-on" : ""}`,
						"aria-pressed": style === s.id,
						onClick: () => setStyle(s.id),
						children: s.label
					}, s.id))
				})
			]
		}) : null,
		failed && !run ? /* @__PURE__ */ jsx("div", {
			className: "ew-note",
			children: failed
		}) : null,
		last ? /* @__PURE__ */ jsxs("div", {
			className: "ew-summary",
			children: [
				/* @__PURE__ */ jsx("div", {
					className: "ew-glabel",
					children: t("opening.summaryTitle")
				}),
				groups.map((g) => {
					const v = answers[g.id];
					const text = g.worldDecides ? "" : v === CUSTOM ? (customs[g.id] ?? "").trim() : (v ?? "").trim();
					return /* @__PURE__ */ jsxs("div", {
						className: "ew-summary-row",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-summary-label",
							children: g.label
						}), /* @__PURE__ */ jsx("span", {
							className: text ? "ew-summary-value" : "ew-summary-world",
							children: text || t("opening.summaryWorld")
						})]
					}, g.id);
				}),
				/* @__PURE__ */ jsxs("div", {
					className: "ew-summary-row",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-summary-label",
						children: t("opening.styleLabel")
					}), /* @__PURE__ */ jsx("span", {
						className: "ew-summary-value",
						children: styleRows.find((s) => s.id === style)?.label ?? style
					})]
				})
			]
		}) : null,
		/* @__PURE__ */ jsxs("div", {
			className: "ew-bar",
			children: [
				page > 0 ? /* @__PURE__ */ jsx("button", {
					className: "ew-btn",
					type: "button",
					onClick: () => setPage((p) => p - 1),
					children: t("opening.prev")
				}) : null,
				rollableHere.length ? /* @__PURE__ */ jsx("button", {
					className: "ew-btn",
					type: "button",
					onClick: rollPage,
					children: t("opening.rollPage")
				}) : null,
				dirty ? /* @__PURE__ */ jsx("button", {
					className: "ew-btn",
					type: "button",
					onClick: resetAll,
					children: t("opening.reset")
				}) : null,
				/* @__PURE__ */ jsx("div", { className: "ew-spacer" }),
				last ? /* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-go",
					type: "button",
					disabled: !!busy,
					onClick: begin,
					children: busy ? t("opening.beginning") : t("opening.begin")
				}) : /* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-go",
					type: "button",
					onClick: () => setPage((p) => p + 1),
					children: t("opening.next")
				})
			]
		}),
		slice.some((g) => !g.worldDecides && g.options.length) ? /* @__PURE__ */ jsx("div", {
			className: "ew-chips",
			style: { marginTop: "12px" },
			children: slice.filter((g) => !g.worldDecides && g.options.length).map((g) => /* @__PURE__ */ jsx("button", {
				type: "button",
				className: "ew-opt",
				onClick: () => rollOne(g),
				children: t("opening.rollOne", { label: g.label })
			}, g.id))
		}) : null
	] });
}
//#endregion
//#region src/tabbar.tsx
/** Canonical system regions, in the order they take on the bar. Anything a world
*  tags with its own word follows these, and untagged scenes fall into one bucket. */
var REGION_ORDER = [
	"status",
	"world",
	"pack",
	"tasks"
];
var SYSTEM = "system";
/** iOS-style ceiling: six tabs fit a phone bar; past this the tail folds into 更多. */
var MAX_VISIBLE = 6;
function regionLabel(region, labels) {
	if (region === SYSTEM) return t("tab.system");
	if (REGION_ORDER.includes(region)) return t(`tab.${region}`);
	return labels.find((l) => l.trim())?.trim() || region;
}
/** The full ordered tab list for a life: 书页, then the world's system regions
*  (canonical first, then custom, then the untagged bucket), then 星图. A region
*  is any region tagged on a PANEL (app-rendered from state) or a mounted SCENE;
*  both feed the same tab. */
function buildTabs(scenes, panels = []) {
	const byRegion = /* @__PURE__ */ new Map();
	const bucket = (key) => {
		const b = byRegion.get(key) ?? {
			scenes: [],
			labels: []
		};
		byRegion.set(key, b);
		return b;
	};
	for (const s of scenes) {
		const b = bucket((s.region ?? "").trim() || SYSTEM);
		b.scenes.push(s);
		if ((s.label ?? "").trim()) b.labels.push((s.label ?? "").trim());
	}
	for (const p of panels) {
		const region = (p.region ?? "").trim();
		if (!region) continue;
		bucket(region).labels.push(p.label ?? "");
	}
	const present = [...byRegion.keys()];
	const regionTabs = [
		...REGION_ORDER.filter((r) => present.includes(r)),
		...present.filter((r) => !REGION_ORDER.includes(r) && r !== SYSTEM),
		...present.includes(SYSTEM) ? [SYSTEM] : []
	].map((r) => ({
		id: r,
		kind: "region",
		label: regionLabel(r, byRegion.get(r)?.labels ?? []),
		sceneIds: (byRegion.get(r)?.scenes ?? []).map((s) => s.sceneId)
	}));
	return [
		{
			id: "reading",
			kind: "reading",
			label: t("tab.reading"),
			sceneIds: []
		},
		...regionTabs,
		{
			id: "starmap",
			kind: "starmap",
			label: t("tab.starmap"),
			sceneIds: []
		}
	];
}
function useScrollHide(enabled, pinUntil = 40) {
	const [hidden, setHidden] = useState(false);
	useEffect(() => {
		if (!enabled) {
			setHidden(false);
			return;
		}
		let last = -1;
		const onScroll = (e) => {
			const tgt = e.target;
			const el = tgt && tgt instanceof HTMLElement ? tgt : document.scrollingElement;
			const y = el ? el.scrollTop : window.scrollY || 0;
			if (last < 0) {
				last = y;
				return;
			}
			const dy = y - last;
			if (Math.abs(dy) < 8) return;
			const end = el instanceof HTMLElement ? el.scrollHeight - el.clientHeight - y : Number.POSITIVE_INFINITY;
			if (y < pinUntil || end < pinUntil) setHidden(false);
			else if (dy > 0) setHidden(true);
			else setHidden(false);
			last = y;
		};
		window.addEventListener("scroll", onScroll, true);
		return () => window.removeEventListener("scroll", onScroll, true);
	}, [enabled, pinUntil]);
	return hidden;
}
function icon(tab) {
	return tabIcon(tab.kind === "region" ? tab.id : tab.kind);
}
/** The glyph for a tab/region id — shared by the phone bottom bar and the desktop
*  right-aside tab strip so both surfaces read the same. */
function tabIcon(id) {
	switch (id) {
		case "reading": return /* @__PURE__ */ jsxs("svg", {
			viewBox: "0 0 24 24",
			children: [/* @__PURE__ */ jsx("path", { d: "M12 6.5C10.5 5 8 4.5 4 4.7v13c4-.2 6.5.3 8 1.8 1.5-1.5 4-2 8-1.8v-13c-4-.2-6.5.3-8 1.8Z" }), /* @__PURE__ */ jsx("path", { d: "M12 6.5V19" })]
		});
		case "starmap": return /* @__PURE__ */ jsx("svg", {
			viewBox: "0 0 24 24",
			children: /* @__PURE__ */ jsx("path", { d: "M12 3.2l1.9 4.4 4.8.4-3.6 3.1 1.1 4.7L12 13.8 7.8 15.8l1.1-4.7L5.3 8l4.8-.4Z" })
		});
		case "status": return /* @__PURE__ */ jsxs("svg", {
			viewBox: "0 0 24 24",
			children: [/* @__PURE__ */ jsx("circle", {
				cx: "12",
				cy: "8",
				r: "3.4"
			}), /* @__PURE__ */ jsx("path", { d: "M5.5 20c.6-3.6 3.2-5.5 6.5-5.5S18.4 16.4 19 20" })]
		});
		case "world": return /* @__PURE__ */ jsxs("svg", {
			viewBox: "0 0 24 24",
			children: [/* @__PURE__ */ jsx("circle", {
				cx: "12",
				cy: "12",
				r: "8.2"
			}), /* @__PURE__ */ jsx("path", { d: "M3.8 12h16.4M12 3.8c2.4 2.4 2.4 13.9 0 16.4M12 3.8c-2.4 2.4-2.4 13.9 0 16.4" })]
		});
		case "pack": return /* @__PURE__ */ jsxs("svg", {
			viewBox: "0 0 24 24",
			children: [
				/* @__PURE__ */ jsx("path", { d: "M7 9V7.5A5 5 0 0 1 17 7.5V9" }),
				/* @__PURE__ */ jsx("rect", {
					x: "4.5",
					y: "9",
					width: "15",
					height: "11",
					rx: "2.5"
				}),
				/* @__PURE__ */ jsx("path", { d: "M9.5 13h5" })
			]
		});
		case "tasks": return /* @__PURE__ */ jsxs("svg", {
			viewBox: "0 0 24 24",
			children: [/* @__PURE__ */ jsx("rect", {
				x: "4.5",
				y: "4.5",
				width: "15",
				height: "15",
				rx: "3"
			}), /* @__PURE__ */ jsx("path", { d: "M8.5 12.2l2.4 2.4 4.6-5" })]
		});
		default: return /* @__PURE__ */ jsxs("svg", {
			viewBox: "0 0 24 24",
			children: [
				/* @__PURE__ */ jsx("rect", {
					x: "4",
					y: "4",
					width: "7",
					height: "7",
					rx: "1.5"
				}),
				/* @__PURE__ */ jsx("rect", {
					x: "13",
					y: "4",
					width: "7",
					height: "7",
					rx: "1.5"
				}),
				/* @__PURE__ */ jsx("rect", {
					x: "4",
					y: "13",
					width: "7",
					height: "7",
					rx: "1.5"
				}),
				/* @__PURE__ */ jsx("rect", {
					x: "13",
					y: "13",
					width: "7",
					height: "7",
					rx: "1.5"
				})
			]
		});
	}
}
function moreIcon() {
	return /* @__PURE__ */ jsxs("svg", {
		viewBox: "0 0 24 24",
		children: [
			/* @__PURE__ */ jsx("circle", {
				cx: "6",
				cy: "12",
				r: "1.6"
			}),
			/* @__PURE__ */ jsx("circle", {
				cx: "12",
				cy: "12",
				r: "1.6"
			}),
			/* @__PURE__ */ jsx("circle", {
				cx: "18",
				cy: "12",
				r: "1.6"
			})
		]
	});
}
function WorldTabBar({ tabs, active, dots, hidden, onSelect }) {
	const [moreOpen, setMoreOpen] = useState(false);
	let visible = tabs;
	let overflow = [];
	if (tabs.length > MAX_VISIBLE) {
		visible = tabs.slice(0, 5);
		overflow = tabs.slice(5);
	}
	const overflowActive = overflow.some((o) => o.id === active);
	const overflowDot = overflow.some((o) => dots[o.id]);
	return createPortal(/* @__PURE__ */ jsxs(Fragment, { children: [moreOpen && overflow.length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("button", {
		className: "ew-tabmore-scrim",
		type: "button",
		"aria-label": t("play.back"),
		onClick: () => setMoreOpen(false)
	}), /* @__PURE__ */ jsx("div", {
		className: "ew-tabmore",
		role: "menu",
		children: overflow.map((o) => /* @__PURE__ */ jsxs("button", {
			className: "ew-tabmore-item" + (o.id === active ? " on" : ""),
			type: "button",
			role: "menuitem",
			onClick: () => {
				onSelect(o.id);
				setMoreOpen(false);
			},
			children: [
				icon(o),
				/* @__PURE__ */ jsx("span", { children: o.label }),
				dots[o.id] ? /* @__PURE__ */ jsx("i", { className: "ew-tabdot-inline" }) : null
			]
		}, o.id))
	})] }) : null, /* @__PURE__ */ jsxs("nav", {
		className: "ew-tabbar" + (hidden && !moreOpen ? " ew-tabbar-hidden" : ""),
		"aria-label": t("tab.label"),
		children: [visible.map((tb) => /* @__PURE__ */ jsxs("button", {
			className: "ew-tab" + (tb.id === active ? " on" : ""),
			type: "button",
			"aria-pressed": tb.id === active,
			onClick: () => {
				setMoreOpen(false);
				onSelect(tb.id);
			},
			children: [
				dots[tb.id] ? /* @__PURE__ */ jsx("span", { className: "ew-tabdot" }) : null,
				icon(tb),
				/* @__PURE__ */ jsx("span", {
					className: "ew-tablabel",
					children: tb.label
				})
			]
		}, tb.id)), overflow.length ? /* @__PURE__ */ jsxs("button", {
			className: "ew-tab" + (overflowActive ? " on" : ""),
			type: "button",
			"aria-expanded": moreOpen,
			onClick: () => setMoreOpen((o) => !o),
			children: [
				overflowDot ? /* @__PURE__ */ jsx("span", { className: "ew-tabdot" }) : null,
				moreIcon(),
				/* @__PURE__ */ jsx("span", {
					className: "ew-tablabel",
					children: t("tab.more")
				})
			]
		}) : null]
	})] }), document.body);
}
//#endregion
//#region src/effects.tsx
/**
* Runtime effects for choice buttons — the narrator declares a NAME from the
* server-validated vocabulary; this module owns the pixels.
*
* Why declared-not-drawn: the play page lives in the dashboard DOCUMENT, not a
* sandboxed iframe, so model-authored CSS/JS can never be mounted here. The
* split mirrors the backdrop pipeline: the model decides semantics (which
* effect, what tint), code owns rendering quality. `shimmer`/`aura`/`ripple`
* are pure CSS (see styles.css); `embers` is the one canvas effect, budgeted
* hard: ≤24 particles, rAF paused while the tab is hidden, and not mounted at
* all under prefers-reduced-motion.
*/
var CSS_EFFECTS = /* @__PURE__ */ new Set([
	"shimmer",
	"aura",
	"ripple"
]);
function reducedMotion() {
	return typeof window !== "undefined" && !!window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
/** The class list a button gains for a declared effect ('' when none). */
function effectClass(effect) {
	if (!effect) return "";
	if (CSS_EFFECTS.has(effect)) return ` ew-fx ew-fx-${effect}`;
	if (effect === "embers") return " ew-fx";
	return "";
}
var MAX_EMBERS = 24;
/** The canvas half of the effect layer. Renders nothing for CSS effects. */
function ChoiceEffect({ effect, tint }) {
	const ref = useRef(null);
	useEffect(() => {
		if (effect !== "embers" || reducedMotion()) return;
		const canvas = ref.current;
		const ctx = canvas?.getContext("2d");
		if (!canvas || !ctx) return;
		let raf = 0;
		let alive = true;
		const dpr = Math.min(window.devicePixelRatio || 1, 2);
		const color = /^#[0-9a-fA-F]{6}$/.test(tint || "") ? tint : "#e0b64a";
		const embers = [];
		const size = () => {
			const rect = canvas.getBoundingClientRect();
			canvas.width = Math.max(1, Math.round(rect.width * dpr));
			canvas.height = Math.max(1, Math.round(rect.height * dpr));
		};
		size();
		const spawn = () => ({
			x: Math.random() * canvas.width,
			y: canvas.height + 4 * dpr,
			r: (.8 + Math.random() * 1.6) * dpr,
			vy: (.12 + Math.random() * .25) * dpr,
			vx: (Math.random() - .5) * .08 * dpr,
			life: 0,
			ttl: 140 + Math.random() * 160
		});
		const step = () => {
			if (!alive) return;
			if (document.hidden) return;
			if (embers.length < MAX_EMBERS && Math.random() < .35) embers.push(spawn());
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			for (let i = embers.length - 1; i >= 0; i--) {
				const p = embers[i];
				if (!p) continue;
				p.life += 1;
				p.x += p.vx;
				p.y -= p.vy;
				const t = p.life / p.ttl;
				if (t >= 1 || p.y < -4) {
					embers.splice(i, 1);
					continue;
				}
				const alpha = t < .2 ? t / .2 : 1 - (t - .2) / .8;
				ctx.globalAlpha = Math.max(0, alpha * .85);
				ctx.fillStyle = color;
				ctx.beginPath();
				ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
				ctx.fill();
			}
			ctx.globalAlpha = 1;
			raf = requestAnimationFrame(step);
		};
		const onVisibility = () => {
			if (!document.hidden && alive) {
				cancelAnimationFrame(raf);
				raf = requestAnimationFrame(step);
			}
		};
		document.addEventListener("visibilitychange", onVisibility);
		raf = requestAnimationFrame(step);
		return () => {
			alive = false;
			cancelAnimationFrame(raf);
			document.removeEventListener("visibilitychange", onVisibility);
		};
	}, [effect, tint]);
	if (effect !== "embers" || reducedMotion()) return null;
	return /* @__PURE__ */ jsx("canvas", {
		ref,
		className: "ew-fx-embers-canvas",
		"aria-hidden": "true"
	});
}
//#endregion
//#region src/history.tsx
/** Looking back over the months already lived.
*
* A separate component and a separate fetch, because reading backwards and playing
* forwards want opposite things. The play page is re-read every few seconds while a
* month is being written and has to stay small; a life's history is a hundred turns
* of prose and is read only when the player deliberately asks for it. Folding one
* into the other would make every poll carry the whole life.
*
* Newest first, and paged from the newest end — that is the direction a life gets
* re-read in: what just happened, then further back.
*/
function History({ runId }) {
	const [turns, setTurns] = useState([]);
	const [more, setMore] = useState(false);
	const [busy, setBusy] = useState(false);
	const [failed, setFailed] = useState(false);
	const [eventsOnly, setEventsOnly] = useState(false);
	const [jump, setJump] = useState("");
	const [query, setQuery] = useState("");
	const [search, setSearch] = useState("");
	const latestRef = useRef(0);
	const load = useCallback(async (before, replace = false, q = "") => {
		setBusy(true);
		setFailed(false);
		try {
			const out = await api.chronicle(runId, before, q);
			const newest = out.turns[0];
			if (before === 0 && !q && newest) latestRef.current = Math.max(latestRef.current, newest.turn);
			setTurns((have) => before > 0 && !replace ? [...have, ...out.turns] : out.turns);
			setMore(out.more);
		} catch {
			setFailed(true);
		}
		setBusy(false);
	}, [runId]);
	useEffect(() => {
		load(0);
	}, [load]);
	const jumpTo = () => {
		const n = parseInt(jump, 10);
		if (!Number.isFinite(n) || n <= 0) return;
		const capped = latestRef.current ? Math.min(n, latestRef.current) : n;
		load(capped + 1, true, query);
	};
	const runSearch = () => {
		const q = search.trim();
		setQuery(q);
		load(0, true, q);
	};
	const clearSearch = () => {
		setSearch("");
		setQuery("");
		load(0, true, "");
	};
	if (failed && !turns.length) return /* @__PURE__ */ jsxs("div", {
		className: "ew-meta",
		children: [t("history.unreadable"), /* @__PURE__ */ jsx("button", {
			className: "ew-btn ew-btn-sm",
			type: "button",
			style: { marginInlineStart: "8px" },
			onClick: () => void load(0),
			children: t("library.retry")
		})]
	});
	if (!turns.length && !query) return /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: busy ? t("history.reading") : t("history.none")
	});
	const oldest = turns[turns.length - 1]?.turn ?? 0;
	const rows = eventsOnly ? turns.filter((p) => p.events.length) : turns;
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-history",
		children: [
			/* @__PURE__ */ jsxs("div", {
				className: "ew-history-bar",
				children: [
					/* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-sm",
						type: "button",
						"aria-pressed": eventsOnly,
						onClick: () => setEventsOnly((v) => !v),
						children: eventsOnly ? t("history.showAll") : t("history.eventsOnly")
					}),
					/* @__PURE__ */ jsx("input", {
						className: "ew-jump",
						inputMode: "numeric",
						value: jump,
						placeholder: t("history.jumpPlaceholder"),
						onChange: (e) => setJump(e.target.value.replace(/[^0-9]/g, "")),
						onKeyDown: (e) => {
							if (e.key === "Enter") jumpTo();
						}
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-sm",
						type: "button",
						onClick: jumpTo,
						children: t("history.jump")
					}),
					/* @__PURE__ */ jsx("input", {
						className: "ew-jump ew-search",
						value: search,
						placeholder: t("history.searchPlaceholder"),
						onChange: (e) => setSearch(e.target.value),
						onKeyDown: (e) => {
							if (e.key === "Enter") runSearch();
						}
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-sm",
						type: "button",
						onClick: runSearch,
						children: t("history.search")
					}),
					query ? /* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-sm",
						type: "button",
						onClick: clearSearch,
						children: t("history.searchClear")
					}) : null
				]
			}),
			query && !turns.length && !busy ? /* @__PURE__ */ jsx("div", {
				className: "ew-meta",
				children: t("history.noMatches", { q: query })
			}) : null,
			eventsOnly && !rows.length ? /* @__PURE__ */ jsx("div", {
				className: "ew-meta",
				children: t("history.noEvents")
			}) : null,
			rows.map((p) => /* @__PURE__ */ jsxs("div", {
				className: "ew-past",
				children: [
					p.backdrop && !eventsOnly ? /* @__PURE__ */ jsx("img", {
						className: "ew-past-bg",
						src: `${API}/runs/${encodeURIComponent(runId)}/backdrop?turn=${p.turn}&v=${p.backdrop.version}`,
						alt: "",
						"aria-hidden": "true",
						draggable: false,
						onError: (e) => {
							e.currentTarget.style.display = "none";
						}
					}) : null,
					/* @__PURE__ */ jsxs("div", {
						className: "ew-past-head",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-past-turn",
							children: t("play.turn", { turn: p.turn })
						}), p.action ? /* @__PURE__ */ jsx("span", {
							className: "ew-past-action",
							children: t("history.chose", { action: p.action })
						}) : null]
					}),
					eventsOnly ? null : /* @__PURE__ */ jsx(Prose, { text: p.prose }),
					p.events.length || p.gains.length ? /* @__PURE__ */ jsxs("div", {
						className: "ew-marks",
						children: [p.events.map((ev, i) => /* @__PURE__ */ jsx("div", {
							className: "ew-mark",
							children: ev
						}, `e${i}`)), p.gains.map((g, i) => /* @__PURE__ */ jsxs("div", {
							className: "ew-mark ew-mark-gain",
							children: [
								g.field,
								g.amount ? ` ${g.amount}` : "",
								g.source ? /* @__PURE__ */ jsx("span", {
									className: "ew-sub",
									children: t("history.via", { source: g.source })
								}) : null
							]
						}, `g${i}`))]
					}) : null
				]
			}, p.turn)),
			more ? /* @__PURE__ */ jsx("button", {
				className: "ew-btn",
				type: "button",
				disabled: busy,
				onClick: () => void load(oldest, false, query),
				children: busy ? t("history.reading") : t("history.earlier")
			}) : /* @__PURE__ */ jsx("div", {
				className: "ew-meta",
				children: t("history.beginning")
			})
		]
	});
}
/**
* A finished life in brief: its marked events, oldest first.
*
* Reuses the chronicle the play page already has — no new model call. Reads up to
* the most recent 100 months (the whole life for all but the very longest) and
* flattens their events into one list, so a terminal page can show "this is what
* happened" without the reader paging back through every turn of prose.
*/
function LifeSummary({ runId }) {
	const [events, setEvents] = useState([]);
	const [loaded, setLoaded] = useState(false);
	useEffect(() => {
		let alive = true;
		api.chronicle(runId, 0, "", 100).then((out) => {
			if (!alive) return;
			const flat = [];
			for (const turn of [...out.turns].reverse()) for (const ev of turn.events) flat.push({
				turn: turn.turn,
				text: ev
			});
			setEvents(flat);
			setLoaded(true);
		}).catch(() => {
			if (alive) setLoaded(true);
		});
		return () => {
			alive = false;
		};
	}, [runId]);
	if (!loaded || !events.length) return null;
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-summary",
		children: [/* @__PURE__ */ jsx("div", {
			className: "ew-glabel",
			children: t("history.summaryTitle")
		}), /* @__PURE__ */ jsx("ul", {
			className: "ew-list",
			children: events.map((e, i) => /* @__PURE__ */ jsxs("li", { children: [/* @__PURE__ */ jsx("span", {
				className: "ew-sub",
				children: `${t("play.turn", { turn: e.turn })} · `
			}), e.text] }, `${e.turn}-${i}`))
		})]
	});
}
//#endregion
//#region src/memory-state.ts
var ALL_FILTERS = {
	characters: true,
	places: true,
	groups: true,
	objects: true,
	threads: true
};
var KIND_TO_FILTER = {
	character: "characters",
	place: "places",
	group: "groups",
	object: "objects",
	thread: "threads"
};
function nodeVisible(node, filters) {
	if (node.kind === "event") return true;
	const key = KIND_TO_FILTER[node.kind];
	return key ? filters[key] : true;
}
/** The nodes adjacent to `id`, for the detail panel's one-hop expansion. */
function neighbours(payload, id) {
	const wanted = /* @__PURE__ */ new Set();
	for (const e of payload.edges) {
		if (e.from === id) wanted.add(e.to);
		if (e.to === id) wanted.add(e.from);
	}
	return payload.nodes.filter((n) => wanted.has(n.id));
}
function nodeById(payload, id) {
	return payload.nodes.find((n) => n.id === id);
}
/** A node's display name, whatever its kind. */
function nodeLabel(node) {
	return node.kind === "event" ? node.title ?? node.id : node.name ?? node.id;
}
var TABLES = {
	zh: {
		"star.title": "人生星图",
		"star.close": "返回故事",
		"star.lens.life": "人生",
		"star.lens.people": "人物",
		"star.lens.keepsakes": "纪念",
		"star.empty": "这段人生还没有留下可以画进星图的事。往前走，世界会记住的。",
		"star.hint": "星图不会改变故事——它只是世界记得你的方式。",
		"star.filter.characters": "人物",
		"star.filter.places": "地点",
		"star.filter.groups": "群体",
		"star.filter.objects": "物品",
		"star.filter.threads": "线索",
		"star.detail.turn": "第 {n} 页",
		"star.detail.jump": "回到那一页",
		"star.detail.action": "你当时的选择",
		"star.detail.related": "相关",
		"star.detail.echoed": "被回响于第 {n} 页",
		"star.detail.thread.open": "仍未了结",
		"star.detail.thread.done": "已了结",
		"star.keep.this": "收藏这一刻",
		"star.keep.kept": "已收藏",
		"star.keep.failed": "收藏失败，请再试一次。",
		"star.people.centre": "以谁为中心",
		"star.people.me": "我",
		"star.people.none": "这段人生还没有记下与人的往来。",
		"star.rel.evidence": "因为这些事",
		"star.rel.unrecorded": "尚无关系记录",
		"star.rel.closer": "更亲近",
		"star.rel.farther": "更疏远",
		"star.rel.type.trust": "信任",
		"star.rel.type.grudge": "积怨",
		"star.rel.type.debt": "人情",
		"star.rel.type.fealty": "效忠",
		"star.rel.type.love": "爱意",
		"star.rel.type.fear": "畏惧",
		"star.rel.type.respect": "敬重",
		"star.rel.type.hostility": "敌意",
		"star.rel.type.kinship": "亲缘",
		"star.rel.type.friendship": "友谊",
		"star.rel.type.rivalry": "竞争",
		"star.mode.canvas": "画布",
		"star.mode.list": "列表",
		"star.keeps.none": "还没有纪念。在回响或星图节点上点「收藏」，把重要的时刻留在这里。",
		"star.keeps.thought": "感想",
		"star.keeps.thoughtPlaceholder": "为什么这一刻重要…",
		"star.keeps.rename": "重命名",
		"star.keeps.save": "保存",
		"star.keeps.delete": "删除",
		"star.keeps.deleteAsk": "删除这份纪念？事实不会消失，只是不再被你标记。",
		"star.keeps.deleteYes": "删除",
		"star.keeps.deleteNo": "留着",
		"star.keeps.cites": "引用的时刻",
		"star.keeps.excerpt": "摘录",
		"star.keeps.newTitle": "未命名的纪念",
		"star.keeps.makeCard": "做成故事卡",
		"card.title": "回响故事卡",
		"card.close": "返回",
		"card.export.html": "导出网页",
		"card.export.md": "导出 Markdown",
		"card.export.svg": "导出图片 (SVG)",
		"card.field.title": "标题",
		"card.field.cover": "封面句",
		"card.field.coverHint": "一句话，说明这段往事为什么值得讲",
		"card.field.thought": "结尾感想",
		"card.sect.events": "要讲哪几件事",
		"card.sect.people": "出场的他们",
		"card.anonHint": "改掉名字即可匿名；取消勾选则完全不出现。",
		"card.moveUp": "上移",
		"card.moveDown": "下移",
		"card.renameOf": "{name} 在卡片上的名字",
		"card.spoilers": "显示结局内容（含剧透）",
		"card.wrap": "界面语言",
		"legacy.title": "传承",
		"legacy.close": "返回",
		"legacy.hint": "这一生结束了。有些东西可以留给下一代——人、物、未了的心愿。被带走的只是它们在你生命里的样子；这一生本身不会被改动。",
		"legacy.none": "这一生没有留下可以传承的东西。有些人生就是这样，干干净净。",
		"legacy.group.characters": "人与羁绊",
		"legacy.group.objects": "物品",
		"legacy.group.groups": "家族与群体",
		"legacy.group.threads": "未了之事",
		"legacy.group.places": "地方",
		"legacy.picked": "已选 {n} / {max}",
		"legacy.continue": "带着这些，开启下一代",
		"legacy.confirmAsk": "传承一旦开启就不能更改。确定吗？",
		"legacy.confirmYes": "确定",
		"legacy.confirmNo": "再想想",
		"legacy.entry": "开启传承"
	},
	en: {
		"star.title": "Life star map",
		"star.close": "Back to the story",
		"star.lens.life": "Life",
		"star.lens.people": "People",
		"star.lens.keepsakes": "Keepsakes",
		"star.empty": "Nothing has been drawn into this map yet. Keep going — the world will remember.",
		"star.hint": "The map never changes the story — it is only how the world remembers you.",
		"star.filter.characters": "People",
		"star.filter.places": "Places",
		"star.filter.groups": "Groups",
		"star.filter.objects": "Objects",
		"star.filter.threads": "Threads",
		"star.detail.turn": "Page {n}",
		"star.detail.jump": "Back to that page",
		"star.detail.action": "What you chose then",
		"star.detail.related": "Related",
		"star.detail.echoed": "Echoed on page {n}",
		"star.detail.thread.open": "Still open",
		"star.detail.thread.done": "Settled",
		"star.keep.this": "Keep this moment",
		"star.keep.kept": "Kept",
		"star.keep.failed": "Could not keep it — try again.",
		"star.people.centre": "Centred on",
		"star.people.me": "Me",
		"star.people.none": "No dealings with anyone have been recorded yet.",
		"star.rel.evidence": "Because of",
		"star.rel.unrecorded": "No relationship recorded yet",
		"star.rel.closer": "Closer",
		"star.rel.farther": "More distant",
		"star.rel.type.trust": "Trust",
		"star.rel.type.grudge": "Grudge",
		"star.rel.type.debt": "Debt",
		"star.rel.type.fealty": "Fealty",
		"star.rel.type.love": "Love",
		"star.rel.type.fear": "Fear",
		"star.rel.type.respect": "Respect",
		"star.rel.type.hostility": "Hostility",
		"star.rel.type.kinship": "Kinship",
		"star.rel.type.friendship": "Friendship",
		"star.rel.type.rivalry": "Rivalry",
		"star.mode.canvas": "Canvas",
		"star.mode.list": "List",
		"star.keeps.none": "No keepsakes yet. Tap \"keep\" on an echo or a map node to hold on to a moment.",
		"star.keeps.thought": "Thought",
		"star.keeps.thoughtPlaceholder": "Why this moment matters…",
		"star.keeps.rename": "Rename",
		"star.keeps.save": "Save",
		"star.keeps.delete": "Delete",
		"star.keeps.deleteAsk": "Delete this keepsake? The facts stay; only your mark on them goes.",
		"star.keeps.deleteYes": "Delete",
		"star.keeps.deleteNo": "Keep it",
		"star.keeps.cites": "Cited moments",
		"star.keeps.excerpt": "Excerpt",
		"star.keeps.newTitle": "Untitled keepsake",
		"star.keeps.makeCard": "Make a story card",
		"card.title": "Echo story card",
		"card.close": "Back",
		"card.export.html": "Export page",
		"card.export.md": "Export Markdown",
		"card.export.svg": "Export image (SVG)",
		"card.field.title": "Title",
		"card.field.cover": "Cover line",
		"card.field.coverHint": "One line on why this is worth telling",
		"card.field.thought": "Closing thought",
		"card.sect.events": "Which moments to tell",
		"card.sect.people": "Who appears",
		"card.anonHint": "Change a name to anonymise; untick to leave someone out entirely.",
		"card.moveUp": "Move up",
		"card.moveDown": "Move down",
		"card.renameOf": "{name}'s name on the card",
		"card.spoilers": "Show ending content (spoilers)",
		"card.wrap": "Card language",
		"legacy.title": "Inheritance",
		"legacy.close": "Back",
		"legacy.hint": "This life is over. Some things can be left to the next one — people, objects, unfinished business. What crosses is how they stood in your life; the life itself is never altered.",
		"legacy.none": "This life leaves nothing to pass on. Some lives are like that — clean.",
		"legacy.group.characters": "People and bonds",
		"legacy.group.objects": "Objects",
		"legacy.group.groups": "Family and groups",
		"legacy.group.threads": "Unfinished business",
		"legacy.group.places": "Places",
		"legacy.picked": "Chosen {n} / {max}",
		"legacy.continue": "Carry these into the next life",
		"legacy.confirmAsk": "An inheritance cannot be changed once made. Sure?",
		"legacy.confirmYes": "Yes",
		"legacy.confirmNo": "Let me think",
		"legacy.entry": "Begin an inheritance"
	}
};
function mt(lang, key, vars = {}) {
	return ((lang === "zh" ? TABLES.zh : TABLES.en)[key] ?? TABLES.en[key] ?? key).replace(/\{(\w+)\}/g, (whole, name) => name in vars ? String(vars[name]) : whole);
}
//#endregion
//#region src/legacy.tsx
/** The legacy picker — the ending page's bridge into a next life (design §9).
*
* Offered only when the world declares lineage and the life has ended; the
* player chooses what crosses, sees each character's current relation reading
* before deciding, and confirms deliberately — an inheritance is the one
* choice that outlives the life making it. The copy is performed server-side
* with provenance; nothing here can widen what the ending screen offered.
*/
var GROUP_ORDER = [
	"characters",
	"objects",
	"groups",
	"threads",
	"places"
];
var MAX_PICK = 12;
function LegacyPicker({ runId, lang, onClose, onContinue }) {
	const [groups, setGroups] = useState(null);
	const [picked, setPicked] = useState([]);
	const [confirming, setConfirming] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const sheet = useRef(null);
	useEffect(() => {
		let alive = true;
		api.legacyCandidates(runId).then((got) => {
			if (alive) setGroups(got.candidates);
		}).catch((e) => {
			if (alive) setError(e.message);
		});
		return () => {
			alive = false;
		};
	}, [runId]);
	const toggle = (id) => setPicked((p) => p.includes(id) ? p.filter((x) => x !== id) : p.length < MAX_PICK ? [...p, id] : p);
	useEffect(() => {
		sheet.current?.scrollIntoView({ block: "start" });
	}, []);
	const total = groups ? GROUP_ORDER.reduce((n, g) => n + (groups[g]?.length ?? 0), 0) : 0;
	return /* @__PURE__ */ jsxs("div", {
		className: "ewl-overlay",
		ref: sheet,
		role: "dialog",
		"aria-modal": "true",
		"aria-label": mt(lang, "legacy.title"),
		children: [
			/* @__PURE__ */ jsxs("div", {
				className: "ewl-head",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ewl-title",
					children: mt(lang, "legacy.title")
				}), /* @__PURE__ */ jsx("button", {
					className: "ews-btn",
					type: "button",
					onClick: onClose,
					children: mt(lang, "legacy.close")
				})]
			}),
			/* @__PURE__ */ jsx("div", {
				className: "ewl-hint",
				children: mt(lang, "legacy.hint")
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ewl-body",
				children: [
					error ? /* @__PURE__ */ jsx("div", {
						className: "ewl-empty",
						children: error
					}) : null,
					groups && !total ? /* @__PURE__ */ jsx("div", {
						className: "ewl-empty",
						children: mt(lang, "legacy.none")
					}) : null,
					groups ? GROUP_ORDER.map((g) => {
						const rows = groups[g] ?? [];
						if (!rows.length) return null;
						return /* @__PURE__ */ jsxs("div", { children: [/* @__PURE__ */ jsx("div", {
							className: "ewl-group",
							children: mt(lang, `legacy.group.${g}`)
						}), rows.map((c) => /* @__PURE__ */ jsxs("label", {
							className: "ewl-row",
							children: [
								/* @__PURE__ */ jsx("input", {
									type: "checkbox",
									checked: picked.includes(c.id),
									disabled: !picked.includes(c.id) && picked.length >= MAX_PICK,
									onChange: () => toggle(c.id)
								}),
								/* @__PURE__ */ jsx("span", {
									className: "ewl-name",
									children: c.name
								}),
								/* @__PURE__ */ jsx("span", {
									className: "ewl-meta",
									children: c.relations?.length ? c.relations.map((r) => `${r.type}${r.value ? ` ${r.value}` : r.level ? ` ${r.level > 0 ? "+" : ""}${r.level}` : ""}`).join(" · ") : c.kind === "thread" ? mt(lang, c.open ? "star.detail.thread.open" : "star.detail.thread.done") : c.summary
								})
							]
						}, c.id))] }, g);
					}) : null
				]
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ewl-foot",
				children: [/* @__PURE__ */ jsx("span", {
					className: "ewl-count",
					children: mt(lang, "legacy.picked", {
						n: picked.length,
						max: MAX_PICK
					})
				}), confirming ? /* @__PURE__ */ jsxs(Fragment, { children: [
					/* @__PURE__ */ jsx("span", {
						className: "ewl-ask",
						children: mt(lang, "legacy.confirmAsk")
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ews-btn",
						type: "button",
						disabled: busy,
						onClick: async () => {
							setBusy(true);
							setError("");
							try {
								await onContinue(picked);
							} catch (e) {
								setError(e.message);
								setBusy(false);
								setConfirming(false);
							}
						},
						children: mt(lang, "legacy.confirmYes")
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ews-btn",
						type: "button",
						onClick: () => setConfirming(false),
						children: mt(lang, "legacy.confirmNo")
					})
				] }) : /* @__PURE__ */ jsx("button", {
					className: "ews-btn",
					type: "button",
					disabled: !picked.length,
					onClick: () => setConfirming(true),
					children: mt(lang, "legacy.continue")
				})]
			}),
			/* @__PURE__ */ jsx("style", { children: CSS_TEXT$2 })
		]
	});
}
var CSS_TEXT$2 = `
.ewl-overlay {
  /* Absolute, NOT fixed. This app is mounted in the dashboard's own document, so a
     fixed sheet resolves against the WINDOW and paints over the crew's chrome —
     its left menu included. Anchored to .ew-root (the app's positioning box) it
     covers the app and nothing else. The open handler scrolls it to the top of the
     viewport, which is what a fixed sheet was standing in for. */
  position: absolute; inset: 0; min-height: 100%; z-index: 20;
  display: flex; flex-direction: column;
  background: var(--bg, #14151f); color: var(--text, #e5e7eb);
}
.ewl-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; border-bottom: 1px solid var(--border, #2d2f3d);
}
.ewl-title { font-weight: 600; }
.ewl-hint {
  padding: 10px 16px 0; font-size: 13px; line-height: 1.7;
  color: var(--muted, #9ca3af);
}
.ewl-body { flex: 1; overflow: auto; padding: 10px 16px; max-width: 640px; }
.ewl-group { font-size: 12px; color: var(--muted, #9ca3af); margin: 14px 0 6px; }
.ewl-row {
  display: flex; gap: 9px; align-items: baseline; padding: 6px 0; cursor: pointer;
}
.ewl-name { font-weight: 500; flex: 0 0 auto; }
.ewl-meta { font-size: 12px; color: var(--muted, #9ca3af); }
.ewl-empty { padding: 30px 0; color: var(--muted, #9ca3af); }
.ewl-foot {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  padding: 10px 16px; border-top: 1px solid var(--border, #2d2f3d);
}
.ewl-count { font-size: 12px; color: var(--muted, #9ca3af); margin-inline-end: auto; }
.ewl-ask { font-size: 13px; }
.ews-btn {
  appearance: none; border: 1px solid var(--border, #2d2f3d); background: none;
  color: inherit; font: inherit; font-size: 13px; padding: 5px 12px;
  border-radius: 8px; cursor: pointer;
}
.ews-btn:disabled { opacity: 0.5; cursor: default; }
`;
//#endregion
//#region src/backdrop.tsx
/**
* The story's background layer: the narrator-authored SVG, shown as an inert
* `<img>` behind the story.
*
* Accepting the narrator's drawing (the app otherwise never accepts markup) is
* safe because it is rendered as an IMAGE, not a live document:
*
*  - an SVG in an `<img>` runs in a non-scripted context — `<script>` and `on*=`
*    handlers never execute and external loads are disabled — so the markup cannot
*    run code or exfiltrate, with or without a sandbox (the backend also strips
*    those as defense in depth);
*  - it sits BEHIND the prose with `pointer-events: none` (see `.ew-backdrop` in
*    styles.css), so a background that draws a fake control cannot be clicked or
*    cover the real one.
*
* This replaced a sandboxed `<iframe srcdoc>` that iOS Safari blank-rendered
* (showing a flat grey background on iPhone). An image renders and sizes reliably
* everywhere, and the image context is a stronger boundary than the sandbox was.
*
* `version` is the cache-buster: a replaced background loads the new image.
*/
function Backdrop({ runId, version, turn, mobile = false }) {
	const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(max-width: 1100px)").matches : false);
	useEffect(() => {
		if (typeof window === "undefined" || !window.matchMedia) return;
		const query = window.matchMedia("(max-width: 1100px)");
		const changed = () => setNarrow(query.matches);
		changed();
		query.addEventListener("change", changed);
		return () => query.removeEventListener("change", changed);
	}, []);
	const q = turn != null ? `?turn=${turn}&v=${version}` : `?v=${version}`;
	const src = `${API}/runs/${encodeURIComponent(runId)}/backdrop${q}${mobile && narrow ? "&variant=mobile" : ""}`;
	const [shownSrc, setShownSrc] = useState(null);
	const retried = useRef(null);
	useEffect(() => {
		if (src === shownSrc) return;
		let alive = true;
		let timer = 0;
		const img = new Image();
		img.onload = () => {
			if (alive) setShownSrc(src);
		};
		img.onerror = () => {
			if (!alive || retried.current === src) return;
			retried.current = src;
			timer = window.setTimeout(() => {
				if (!alive) return;
				const again = new Image();
				again.onload = () => {
					if (alive) setShownSrc(src);
				};
				again.src = src;
			}, 1500);
		};
		img.src = src;
		return () => {
			alive = false;
			if (timer) window.clearTimeout(timer);
		};
	}, [src, shownSrc]);
	if (shownSrc == null) return null;
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-backdrop",
		"aria-hidden": "true",
		children: [/* @__PURE__ */ jsx("img", {
			className: "ew-backdrop-frame",
			src: shownSrc,
			alt: "",
			draggable: false
		}), /* @__PURE__ */ jsx("div", { className: "ew-backdrop-scrim" })]
	});
}
//#endregion
//#region src/memory-layouts/timeline.tsx
function TimelineLens({ payload, lang, focus, setFocus, filters }) {
	const events = payload.nodes.filter((n) => n.kind === "event").sort((a, b) => (a.turn ?? 0) - (b.turn ?? 0) || a.id.localeCompare(b.id));
	if (!events.length) return /* @__PURE__ */ jsx("div", {
		className: "ews-empty",
		children: mt(lang, "star.empty")
	});
	const byId = new Map(payload.nodes.map((n) => [n.id, n]));
	const echoOf = /* @__PURE__ */ new Map();
	for (const e of payload.edges) if (e.type === "echoes") echoOf.set(e.from, [...echoOf.get(e.from) ?? [], e.to]);
	const attached = /* @__PURE__ */ new Map();
	for (const e of payload.edges) {
		if (e.type === "echoes") continue;
		const event = e.type === "participated_in" ? e.to : e.from;
		const entity = e.type === "participated_in" ? e.from : e.to;
		const node = byId.get(entity);
		if (!node || node.kind === "event" || !nodeVisible(node, filters)) continue;
		const list = attached.get(event) ?? [];
		if (!list.some((n) => n.id === node.id)) list.push(node);
		attached.set(event, list);
	}
	return /* @__PURE__ */ jsx("div", {
		className: "ews-timeline",
		role: "list",
		children: events.map((ev) => {
			const selected = ev.id === focus;
			const echoes = echoOf.get(ev.id) ?? [];
			return /* @__PURE__ */ jsxs("div", {
				className: "ews-tl-row",
				role: "listitem",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ews-tl-spine",
					"aria-hidden": "true",
					children: /* @__PURE__ */ jsx("span", { className: "ews-tl-dot" + (ev.importance === "major" ? " ews-tl-dot-major" : "") + (selected ? " ews-tl-dot-sel" : "") })
				}), /* @__PURE__ */ jsxs("div", {
					className: "ews-tl-body",
					children: [
						/* @__PURE__ */ jsxs("button", {
							className: "ews-node" + (selected ? " ews-node-sel" : ""),
							type: "button",
							"aria-pressed": selected,
							onClick: () => setFocus(ev.id),
							children: [/* @__PURE__ */ jsx("span", {
								className: "ews-tl-turn",
								children: mt(lang, "star.detail.turn", { n: ev.turn ?? 0 })
							}), /* @__PURE__ */ jsx("span", {
								className: "ews-tl-title",
								children: ev.title
							})]
						}),
						echoes.map((target) => {
							const src = byId.get(target);
							return src ? /* @__PURE__ */ jsxs("button", {
								className: "ews-echo-ref",
								type: "button",
								onClick: () => setFocus(target),
								children: [
									mt(lang, "star.detail.echoed", { n: src.turn ?? 0 }),
									" · ",
									nodeLabel(src)
								]
							}, target) : null;
						}),
						(attached.get(ev.id) ?? []).length ? /* @__PURE__ */ jsx("div", {
							className: "ews-tl-cluster",
							children: (attached.get(ev.id) ?? []).map((n) => /* @__PURE__ */ jsx("button", {
								className: "ews-chip ews-chip-" + n.kind + (n.id === focus ? " ews-chip-sel" : ""),
								type: "button",
								onClick: () => setFocus(n.id),
								children: nodeLabel(n)
							}, n.id))
						}) : null
					]
				})]
			}, ev.id);
		})
	});
}
//#endregion
//#region src/memory-layouts/relations.tsx
var SIZE = 620;
var CX = SIZE / 2;
var LOCALIZED_RELATION_TYPES = /* @__PURE__ */ new Set([
	"trust",
	"grudge",
	"debt",
	"fealty",
	"love",
	"fear",
	"respect",
	"hostility",
	"kinship",
	"friendship",
	"rivalry"
]);
function relationReading(lang, relation) {
	const normalized = relation.type.trim().toLowerCase().replace(/[\s-]+/g, "_");
	const type = LOCALIZED_RELATION_TYPES.has(normalized) ? mt(lang, `star.rel.type.${normalized}`) : relation.type.replace(/[_-]+/g, " ");
	if (relation.value) return `${type} · ${relation.value}`;
	if (!relation.level) return type;
	return `${type} · ${mt(lang, relation.level > 0 ? "star.rel.closer" : "star.rel.farther")} ×${Math.abs(relation.level)}`;
}
function ring(index, count, radius) {
	const angle = index / Math.max(count, 1) * Math.PI * 2 - Math.PI / 2;
	return {
		x: CX + radius * Math.cos(angle),
		y: CX + radius * Math.sin(angle)
	};
}
function RelationsLens({ payload, lang, focus, setFocus, filters, centre, setCentre, mode }) {
	const self = payload.centre;
	const selfLabel = self.name || mt(lang, "star.people.me");
	const centred = centre || self.id;
	const characters = payload.nodes.filter((n) => n.kind === "character" && nodeVisible(n, filters));
	const relations = payload.relations.filter((r) => r.from === centred || r.to === centred);
	if (!characters.length && !relations.length) return /* @__PURE__ */ jsx("div", {
		className: "ews-empty",
		children: mt(lang, "star.people.none")
	});
	const partners = /* @__PURE__ */ new Map();
	for (const r of relations) {
		const other = r.from === centred ? r.to : r.from;
		partners.set(other, [...partners.get(other) ?? [], r]);
	}
	const inner = [...partners.keys()].map((id) => nodeById(payload, id)).filter((n) => !!n && nodeVisible(n, filters)).sort((a, b) => a.id.localeCompare(b.id));
	const outer = payload.nodes.filter((n) => n.kind !== "event" && n.id !== centred && !partners.has(n.id) && nodeVisible(n, filters)).sort((a, b) => a.id.localeCompare(b.id));
	const unrelatedCharacters = characters.filter((character) => character.id !== centred && !partners.has(character.id)).sort((a, b) => a.id.localeCompare(b.id));
	const centreLabel = centred === self.id ? selfLabel : nodeLabel(nodeById(payload, centred) ?? {
		id: centred,
		kind: "character",
		name: centred
	});
	const picker = /* @__PURE__ */ jsxs("div", {
		className: "ews-centre-row",
		children: [
			/* @__PURE__ */ jsx("span", {
				className: "ews-centre-label",
				children: mt(lang, "star.people.centre")
			}),
			/* @__PURE__ */ jsx("button", {
				className: "ews-chip" + (centred === self.id ? " ews-chip-sel" : ""),
				type: "button",
				onClick: () => setCentre(self.id),
				children: selfLabel
			}),
			characters.filter((c) => c.id !== self.id).map((c) => /* @__PURE__ */ jsx("button", {
				className: "ews-chip ews-chip-character" + (centred === c.id ? " ews-chip-sel" : ""),
				type: "button",
				onClick: () => setCentre(c.id),
				children: nodeLabel(c)
			}, c.id))
		]
	});
	if (mode === "list") return /* @__PURE__ */ jsxs("div", { children: [picker, /* @__PURE__ */ jsxs("div", {
		className: "ews-rel-list",
		children: [
			relations.map((r, i) => {
				const other = r.from === centred ? r.to : r.from;
				const node = nodeById(payload, other);
				return /* @__PURE__ */ jsxs("div", {
					className: "ews-rel-row",
					children: [
						/* @__PURE__ */ jsx("button", {
							className: "ews-node" + (focus === other ? " ews-node-sel" : ""),
							type: "button",
							onClick: () => setFocus(other),
							children: node ? nodeLabel(node) : other
						}),
						/* @__PURE__ */ jsx("span", {
							className: "ews-rel-kind",
							children: relationReading(lang, r)
						}),
						r.sources.length ? /* @__PURE__ */ jsxs("span", {
							className: "ews-rel-srcs",
							children: [
								mt(lang, "star.rel.evidence"),
								":",
								" ",
								r.sources.map((s) => {
									const ev = nodeById(payload, s);
									return ev ? /* @__PURE__ */ jsx("button", {
										className: "ews-echo-ref",
										type: "button",
										onClick: () => setFocus(s),
										children: mt(lang, "star.detail.turn", { n: ev.turn ?? 0 })
									}, s) : null;
								})
							]
						}) : null
					]
				}, `${r.from}-${r.type}-${r.to}-${i}`);
			}),
			unrelatedCharacters.map((character) => /* @__PURE__ */ jsxs("div", {
				className: "ews-rel-row",
				children: [/* @__PURE__ */ jsx("button", {
					className: "ews-node" + (focus === character.id ? " ews-node-sel" : ""),
					type: "button",
					onClick: () => setFocus(character.id),
					children: nodeLabel(character)
				}), /* @__PURE__ */ jsx("span", {
					className: "ews-rel-kind",
					children: mt(lang, "star.rel.unrecorded")
				})]
			}, `unrecorded-${character.id}`)),
			!relations.length && !unrelatedCharacters.length ? /* @__PURE__ */ jsx("div", {
				className: "ews-empty",
				children: mt(lang, "star.people.none")
			}) : null
		]
	})] });
	return /* @__PURE__ */ jsxs("div", { children: [picker, /* @__PURE__ */ jsxs("svg", {
		className: "ews-canvas",
		viewBox: `0 0 ${SIZE} ${SIZE}`,
		role: "img",
		"aria-label": mt(lang, "star.lens.people"),
		children: [
			/* @__PURE__ */ jsx("circle", {
				cx: CX,
				cy: CX,
				r: 150,
				className: "ews-orbit"
			}),
			/* @__PURE__ */ jsx("circle", {
				cx: CX,
				cy: CX,
				r: 265,
				className: "ews-orbit"
			}),
			inner.map((n, i) => {
				const p = ring(i, inner.length, 150);
				return /* @__PURE__ */ jsx("line", {
					x1: CX,
					y1: CX,
					x2: p.x,
					y2: p.y,
					className: "ews-rel-line"
				}, `l-${n.id}`);
			}),
			/* @__PURE__ */ jsxs("g", {
				className: "ews-star ews-star-centre",
				onClick: () => setFocus(centred),
				role: "button",
				tabIndex: 0,
				children: [/* @__PURE__ */ jsx("circle", {
					cx: CX,
					cy: CX,
					r: 26
				}), /* @__PURE__ */ jsx("text", {
					x: CX,
					y: 314,
					textAnchor: "middle",
					children: centreLabel
				})]
			}),
			inner.map((n, i) => {
				const p = ring(i, inner.length, 150);
				return /* @__PURE__ */ jsxs("g", {
					className: "ews-star ews-star-" + n.kind + (focus === n.id ? " ews-star-sel" : ""),
					onClick: () => setFocus(n.id),
					role: "button",
					tabIndex: 0,
					children: [/* @__PURE__ */ jsx("circle", {
						cx: p.x,
						cy: p.y,
						r: 20
					}), /* @__PURE__ */ jsx("text", {
						x: p.x,
						y: p.y + 34,
						textAnchor: "middle",
						children: nodeLabel(n)
					})]
				}, n.id);
			}),
			outer.map((n, i) => {
				const p = ring(i, outer.length, 265);
				return /* @__PURE__ */ jsxs("g", {
					className: "ews-star ews-star-" + n.kind + (focus === n.id ? " ews-star-sel" : ""),
					onClick: () => setFocus(n.id),
					role: "button",
					tabIndex: 0,
					children: [/* @__PURE__ */ jsx("circle", {
						cx: p.x,
						cy: p.y,
						r: 14
					}), /* @__PURE__ */ jsx("text", {
						x: p.x,
						y: p.y + 28,
						textAnchor: "middle",
						children: nodeLabel(n)
					})]
				}, n.id);
			})
		]
	})] });
}
//#endregion
//#region src/story-card.tsx
/** The echo story card editor (design §8.4).
*
* One panel, two halves: the LEFT edits the draft (include/exclude events and
* people, rename for anonymity, title/cover/thought, spoilers, wrap language);
* the RIGHT shows the resolved preview the server returns with every edit.
* The preview is rendered by the SAME resolver the exporters use, so what the
* player reads here is byte-for-byte what the file will say — the §11 Phase 3
* completion bar, surfaced as UI.
*
* Nothing here can ADD to a card: the server refuses ids outside the
* allowlist, and this editor simply has no control that would try.
*/
function StoryCardEditor({ runId, keepsake, lang, onClose }) {
	const [card, setCard] = useState(null);
	const [preview, setPreview] = useState(null);
	const [error, setError] = useState("");
	const [title, setTitle] = useState("");
	const [cover, setCover] = useState("");
	const [thought, setThought] = useState("");
	const sheet = useRef(null);
	useEffect(() => {
		sheet.current?.scrollIntoView({ block: "start" });
	}, []);
	useEffect(() => {
		let alive = true;
		api.previewStoryCard(runId, keepsake.id).then(({ card: c, preview: p }) => {
			if (!alive) return;
			setCard(c);
			setPreview(p);
			setTitle(c.title);
			setCover(c.coverLine);
			setThought(c.thought);
		}).catch((e) => {
			if (alive) setError(e.message);
		});
		return () => {
			alive = false;
		};
	}, [runId, keepsake.id]);
	const patch = async (body) => {
		if (!card) return;
		try {
			const { card: c, preview: p } = await api.editStoryCard(runId, card.id, body);
			setCard(c);
			setPreview(p);
		} catch (e) {
			setError(e.message);
		}
	};
	const move = (id, dir) => {
		if (!card) return;
		const order = card.events.map((e) => e.id);
		const i = order.indexOf(id);
		const j = i + dir;
		if (i < 0 || j < 0 || j >= order.length) return;
		const next = [...order];
		const a = next[i];
		next[i] = next[j];
		next[j] = a;
		patch({ order: next });
	};
	if (error) return /* @__PURE__ */ jsxs("div", {
		className: "ewc-overlay",
		ref: sheet,
		role: "dialog",
		"aria-modal": "true",
		children: [/* @__PURE__ */ jsxs("div", {
			className: "ewc-head",
			children: [/* @__PURE__ */ jsx("div", {
				className: "ewc-title",
				children: mt(lang, "card.title")
			}), /* @__PURE__ */ jsx("button", {
				className: "ews-btn",
				type: "button",
				onClick: onClose,
				children: mt(lang, "card.close")
			})]
		}), /* @__PURE__ */ jsx("div", {
			className: "ews-empty",
			children: error
		})]
	});
	if (!card || !preview) return /* @__PURE__ */ jsx("div", {
		className: "ewc-overlay",
		ref: sheet,
		role: "dialog",
		"aria-modal": "true",
		children: /* @__PURE__ */ jsx("div", {
			className: "ews-empty",
			children: "…"
		})
	});
	return /* @__PURE__ */ jsxs("div", {
		className: "ewc-overlay",
		ref: sheet,
		role: "dialog",
		"aria-modal": "true",
		"aria-label": mt(lang, "card.title"),
		children: [
			/* @__PURE__ */ jsxs("div", {
				className: "ewc-head",
				children: [
					/* @__PURE__ */ jsx("div", {
						className: "ewc-title",
						children: mt(lang, "card.title")
					}),
					/* @__PURE__ */ jsx("div", {
						className: "ewc-exports",
						children: [
							"html",
							"md",
							"svg"
						].map((fmt) => /* @__PURE__ */ jsx("a", {
							className: "ews-btn",
							href: api.storyCardExportUrl(runId, card.id, fmt),
							download: true,
							children: mt(lang, `card.export.${fmt}`)
						}, fmt))
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ews-btn",
						type: "button",
						onClick: onClose,
						children: mt(lang, "card.close")
					})
				]
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ewc-body",
				children: [/* @__PURE__ */ jsxs("div", {
					className: "ewc-edit",
					children: [
						/* @__PURE__ */ jsxs("label", {
							className: "ewc-field",
							children: [/* @__PURE__ */ jsx("span", { children: mt(lang, "card.field.title") }), /* @__PURE__ */ jsx("input", {
								value: title,
								maxLength: 120,
								onChange: (e) => setTitle(e.target.value),
								onBlur: () => {
									if (title.trim() && title !== card.title) patch({ title });
								}
							})]
						}),
						/* @__PURE__ */ jsxs("label", {
							className: "ewc-field",
							children: [/* @__PURE__ */ jsx("span", { children: mt(lang, "card.field.cover") }), /* @__PURE__ */ jsx("input", {
								value: cover,
								maxLength: 200,
								placeholder: mt(lang, "card.field.coverHint"),
								onChange: (e) => setCover(e.target.value),
								onBlur: () => {
									if (cover !== card.coverLine) patch({ coverLine: cover });
								}
							})]
						}),
						/* @__PURE__ */ jsx("div", {
							className: "ewc-sect",
							children: mt(lang, "card.sect.events")
						}),
						card.events.map((ev, i) => /* @__PURE__ */ jsxs("div", {
							className: "ewc-row",
							children: [/* @__PURE__ */ jsxs("label", {
								className: "ewc-check",
								children: [
									/* @__PURE__ */ jsx("input", {
										type: "checkbox",
										checked: ev.included,
										onChange: () => void patch({ events: { [ev.id]: !ev.included } })
									}),
									/* @__PURE__ */ jsx("span", {
										className: "ewc-row-turn",
										children: mt(lang, "star.detail.turn", { n: ev.turn })
									}),
									/* @__PURE__ */ jsx("span", {
										className: "ewc-row-title",
										children: ev.title
									})
								]
							}), /* @__PURE__ */ jsxs("span", {
								className: "ewc-move",
								children: [/* @__PURE__ */ jsx("button", {
									className: "ews-btn",
									type: "button",
									disabled: i === 0,
									"aria-label": mt(lang, "card.moveUp"),
									onClick: () => move(ev.id, -1),
									children: "↑"
								}), /* @__PURE__ */ jsx("button", {
									className: "ews-btn",
									type: "button",
									disabled: i === card.events.length - 1,
									"aria-label": mt(lang, "card.moveDown"),
									onClick: () => move(ev.id, 1),
									children: "↓"
								})]
							})]
						}, ev.id)),
						/* @__PURE__ */ jsx("div", {
							className: "ewc-sect",
							children: mt(lang, "card.sect.people")
						}),
						/* @__PURE__ */ jsx("div", {
							className: "ewc-hint",
							children: mt(lang, "card.anonHint")
						}),
						card.entities.map((ent) => /* @__PURE__ */ jsxs("div", {
							className: "ewc-row",
							children: [/* @__PURE__ */ jsxs("label", {
								className: "ewc-check",
								children: [/* @__PURE__ */ jsx("input", {
									type: "checkbox",
									checked: ent.included,
									onChange: () => void patch({ entities: { [ent.id]: { included: !ent.included } } })
								}), /* @__PURE__ */ jsx("span", {
									className: "ewc-row-title",
									children: ent.name
								})]
							}), /* @__PURE__ */ jsx("input", {
								className: "ewc-rename",
								value: ent.display,
								maxLength: 120,
								"aria-label": mt(lang, "card.renameOf", { name: ent.name }),
								onChange: (e) => {
									const display = e.target.value;
									setCard({
										...card,
										entities: card.entities.map((x) => x.id === ent.id ? {
											...x,
											display
										} : x)
									});
								},
								onBlur: (e) => {
									const display = e.target.value.trim();
									if (display && display !== ent.name) patch({ entities: { [ent.id]: { display } } });
								}
							})]
						}, ent.id)),
						card.endedTurn ? /* @__PURE__ */ jsxs("label", {
							className: "ewc-check ewc-spoiler",
							children: [/* @__PURE__ */ jsx("input", {
								type: "checkbox",
								checked: card.showSpoilers,
								onChange: () => void patch({ showSpoilers: !card.showSpoilers })
							}), mt(lang, "card.spoilers")]
						}) : null,
						/* @__PURE__ */ jsxs("label", {
							className: "ewc-field",
							children: [/* @__PURE__ */ jsx("span", { children: mt(lang, "card.field.thought") }), /* @__PURE__ */ jsx("textarea", {
								rows: 2,
								value: thought,
								maxLength: 1e3,
								onChange: (e) => setThought(e.target.value),
								onBlur: () => {
									if (thought !== card.thought) patch({ thought });
								}
							})]
						}),
						/* @__PURE__ */ jsxs("div", {
							className: "ewc-langrow",
							children: [/* @__PURE__ */ jsx("span", { children: mt(lang, "card.wrap") }), ["zh", "en"].map((l) => /* @__PURE__ */ jsx("button", {
								className: "ews-lens" + (card.language === l ? " ews-lens-on" : ""),
								type: "button",
								onClick: () => void patch({ language: l }),
								children: l === "zh" ? "中文" : "English"
							}, l))]
						})
					]
				}), /* @__PURE__ */ jsxs("div", {
					className: "ewc-preview",
					children: [
						/* @__PURE__ */ jsx("h2", {
							className: "ewc-p-title",
							children: preview.title
						}),
						preview.coverLine ? /* @__PURE__ */ jsx("p", {
							className: "ewc-p-cover",
							children: preview.coverLine
						}) : null,
						preview.events.map((ev) => /* @__PURE__ */ jsxs("section", {
							className: "ewc-p-event",
							children: [
								/* @__PURE__ */ jsxs("div", {
									className: "ewc-p-head",
									children: [/* @__PURE__ */ jsx("span", {
										className: "ewc-row-turn",
										children: mt(lang, "star.detail.turn", { n: ev.turn })
									}), /* @__PURE__ */ jsx("strong", { children: ev.title })]
								}),
								/* @__PURE__ */ jsx("p", { children: ev.excerpt || ev.summary }),
								ev.action ? /* @__PURE__ */ jsx("div", {
									className: "ewc-p-act",
									children: ev.action
								}) : null
							]
						}, ev.id)),
						preview.entities.length ? /* @__PURE__ */ jsx("div", {
							className: "ewc-p-cast",
							children: preview.entities.map((e) => /* @__PURE__ */ jsx("span", {
								className: "ews-chip",
								children: e.display
							}, e.id))
						}) : null,
						preview.thought ? /* @__PURE__ */ jsx("p", {
							className: "ewc-p-thought",
							children: preview.thought
						}) : null
					]
				})]
			}),
			/* @__PURE__ */ jsx("style", { children: CSS_TEXT$1 })
		]
	});
}
var CSS_TEXT$1 = `
.ewc-overlay {
  /* Absolute, NOT fixed — same reason as the legacy sheet: a fixed sheet resolves
     against the window and covers the dashboard's own chrome. This one anchors to
     the star map page it opens from, and scrolls itself into view on open. */
  position: absolute; inset: 0; min-height: 100%; z-index: 20;
  display: flex; flex-direction: column;
  background: var(--bg, #14151f); color: var(--text, #e5e7eb);
}
.ewc-head {
  display: flex; align-items: center; gap: 10px; padding: 10px 16px;
  border-bottom: 1px solid var(--border, #2d2f3d);
}
.ewc-title { font-weight: 600; }
.ewc-exports { display: flex; gap: 6px; margin-inline: auto; }
.ewc-exports a { text-decoration: none; }
.ewc-body { flex: 1; display: flex; min-height: 0; }
.ewc-edit {
  flex: 0 0 380px; overflow: auto; padding: 14px 16px;
  border-inline-end: 1px solid var(--border, #2d2f3d);
  display: flex; flex-direction: column; gap: 8px;
}
.ewc-preview { flex: 1; overflow: auto; padding: 20px 24px; max-width: 660px; }
.ewc-field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.ewc-field input, .ewc-field textarea, .ewc-rename {
  font: inherit; color: inherit; background: none;
  border: 1px solid var(--border, #2d2f3d); border-radius: 8px; padding: 6px 8px;
}
.ewc-sect { font-size: 12px; color: var(--muted, #9ca3af); margin-top: 10px; }
.ewc-hint { font-size: 12px; color: var(--muted, #6b7280); }
.ewc-row { display: flex; gap: 8px; align-items: center; }
.ewc-check { display: flex; gap: 7px; align-items: center; flex: 1; min-width: 0;
             cursor: pointer; font-size: 14px; }
.ewc-row-turn { font-size: 12px; color: var(--muted, #9ca3af); flex: 0 0 auto; }
.ewc-row-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ewc-move { display: flex; gap: 4px; }
.ewc-rename { flex: 0 0 130px; font-size: 13px; }
.ewc-spoiler { margin-top: 10px; }
.ewc-langrow { display: flex; gap: 6px; align-items: center; font-size: 13px;
               margin-top: 8px; }
.ewc-p-title { font-size: 22px; margin: 0 0 8px; }
.ewc-p-cover { font-style: italic; color: var(--muted, #a5a8b6);
  border-inline-start: 3px solid var(--accent, #7c3aed); padding-inline-start: 12px; }
.ewc-p-event { margin: 18px 0; }
.ewc-p-head { margin-bottom: 4px; }
.ewc-p-act { font-size: 13px; font-style: italic; color: var(--accent, #a78bfa); }
.ewc-p-cast { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 16px; }
.ewc-p-thought { font-style: italic; margin-top: 16px; }
@media (max-width: 860px) {
  .ewc-body { flex-direction: column; }
  .ewc-edit { flex: 0 0 auto; max-height: 52dvh;
    border-inline-end: 0; border-bottom: 1px solid var(--border, #2d2f3d); }
}
`;
//#endregion
//#region src/memory-layouts/keepsakes.tsx
/** 纪念地图 — the "keepsakes" lens (design §8.3.1).
*
* The question: "哪些时刻对我最重要？" Keepsakes are the anchors; each opens
* into the exact events it cites. Editing here touches the MEANING layer only
* — a rename, a thought, a deletion — and can never move a fact (§8.2: the
* cited path is immutable, deletion of a keepsake deletes nothing the world
* remembers).
*/
function KeepsakeCard({ runId, kp, lang, payload, focus, setFocus, onChanged, onMakeCard }) {
	const [editing, setEditing] = useState(false);
	const [title, setTitle] = useState(kp.title);
	const [thought, setThought] = useState(kp.thought);
	const [confirming, setConfirming] = useState(false);
	const [busy, setBusy] = useState(false);
	const save = async () => {
		setBusy(true);
		try {
			await api.updateKeepsake(runId, kp.id, {
				title: title.trim(),
				thought
			});
			setEditing(false);
			onChanged();
		} finally {
			setBusy(false);
		}
	};
	const remove = async () => {
		setBusy(true);
		try {
			await api.deleteKeepsake(runId, kp.id);
			onChanged();
		} finally {
			setBusy(false);
		}
	};
	return /* @__PURE__ */ jsxs("div", {
		className: "ews-kp" + (kp.cites.includes(focus) ? " ews-kp-hot" : ""),
		children: [
			editing ? /* @__PURE__ */ jsx("input", {
				className: "ews-kp-title-edit",
				value: title,
				maxLength: 120,
				onChange: (e) => setTitle(e.target.value)
			}) : /* @__PURE__ */ jsx("div", {
				className: "ews-kp-title",
				children: kp.title
			}),
			kp.kind === "excerpt" && kp.excerpt ? /* @__PURE__ */ jsxs("blockquote", {
				className: "ews-kp-excerpt",
				children: [kp.excerpt, /* @__PURE__ */ jsxs("div", {
					className: "ews-kp-excerpt-src",
					children: [
						mt(lang, "star.keeps.excerpt"),
						" · ",
						mt(lang, "star.detail.turn", { n: kp.turn })
					]
				})]
			}) : null,
			editing ? /* @__PURE__ */ jsx("textarea", {
				className: "ews-kp-thought-edit",
				rows: 2,
				value: thought,
				maxLength: 1e3,
				placeholder: mt(lang, "star.keeps.thoughtPlaceholder"),
				onChange: (e) => setThought(e.target.value)
			}) : kp.thought ? /* @__PURE__ */ jsx("div", {
				className: "ews-kp-thought",
				children: kp.thought
			}) : null,
			kp.cites.length ? /* @__PURE__ */ jsxs("div", {
				className: "ews-kp-cites",
				children: [/* @__PURE__ */ jsx("span", {
					className: "ews-kp-cites-label",
					children: mt(lang, "star.keeps.cites")
				}), kp.cites.map((cid) => {
					const ev = nodeById(payload, cid);
					return ev ? /* @__PURE__ */ jsxs("button", {
						className: "ews-chip" + (focus === cid ? " ews-chip-sel" : ""),
						type: "button",
						onClick: () => setFocus(cid),
						children: [
							mt(lang, "star.detail.turn", { n: ev.turn ?? 0 }),
							" · ",
							ev.title
						]
					}, cid) : null;
				})]
			}) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ews-kp-actions",
				children: [
					kp.cites.length ? /* @__PURE__ */ jsx("button", {
						className: "ews-btn",
						type: "button",
						onClick: () => onMakeCard(kp),
						children: mt(lang, "star.keeps.makeCard")
					}) : null,
					editing ? /* @__PURE__ */ jsx("button", {
						className: "ews-btn",
						type: "button",
						disabled: busy,
						onClick: () => void save(),
						children: mt(lang, "star.keeps.save")
					}) : /* @__PURE__ */ jsx("button", {
						className: "ews-btn",
						type: "button",
						onClick: () => setEditing(true),
						children: mt(lang, "star.keeps.rename")
					}),
					confirming ? /* @__PURE__ */ jsxs(Fragment, { children: [
						/* @__PURE__ */ jsx("span", {
							className: "ews-kp-ask",
							children: mt(lang, "star.keeps.deleteAsk")
						}),
						/* @__PURE__ */ jsx("button", {
							className: "ews-btn ews-btn-danger",
							type: "button",
							disabled: busy,
							onClick: () => void remove(),
							children: mt(lang, "star.keeps.deleteYes")
						}),
						/* @__PURE__ */ jsx("button", {
							className: "ews-btn",
							type: "button",
							onClick: () => setConfirming(false),
							children: mt(lang, "star.keeps.deleteNo")
						})
					] }) : /* @__PURE__ */ jsx("button", {
						className: "ews-btn",
						type: "button",
						onClick: () => setConfirming(true),
						children: mt(lang, "star.keeps.delete")
					})
				]
			})
		]
	});
}
function KeepsakesLens({ runId, payload, lang, focus, setFocus, onChanged }) {
	const [cardFor, setCardFor] = useState(null);
	if (!payload.keepsakes.length) return /* @__PURE__ */ jsx("div", {
		className: "ews-empty",
		children: mt(lang, "star.keeps.none")
	});
	const rows = [...payload.keepsakes].sort((a, b) => b.createdAt - a.createdAt);
	return /* @__PURE__ */ jsxs("div", {
		className: "ews-kp-map",
		children: [cardFor ? /* @__PURE__ */ jsx(StoryCardEditor, {
			runId,
			keepsake: cardFor,
			lang,
			onClose: () => setCardFor(null)
		}) : null, rows.map((kp) => /* @__PURE__ */ jsx(KeepsakeCard, {
			runId,
			kp,
			lang,
			payload,
			focus,
			setFocus,
			onChanged,
			onMakeCard: setCardFor
		}, kp.id))]
	});
}
//#endregion
//#region src/memory.tsx
/** The life star map container (design §8.3).
*
* Three lenses over ONE payload: switching a lens swaps the layout adapter and
* nothing else — the fetched graph, the selected node, the filters and the
* detail panel all survive the switch (§12.4). The last-used lens is saved per
* life on the server; the entry point only chooses the INITIAL lens (§8.3.2).
*
* Rendered as a full-screen overlay from the play page rather than a route of
* its own, and styled by a module-scoped <style> tag: both choices keep this
* feature's file footprint disjoint from concurrently-edited app files
* (main.tsx, styles.css) — the container is self-contained by construction.
*/
var FILTER_KEYS = [
	"characters",
	"places",
	"groups",
	"objects",
	"threads"
];
function StarMap({ runId, lang, onClose, onJumpTurn, initialFocus, backdrop }) {
	const [payload, setPayload] = useState(null);
	const [lens, setLens] = useState(null);
	const [focus, setFocus] = useState(initialFocus ?? "");
	const [filters, setFilters] = useState(ALL_FILTERS);
	const [centre, setCentre] = useState("");
	const [mode, setMode] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 860px)").matches ? "list" : "canvas");
	const [kept, setKept] = useState([]);
	const [keepFailed, setKeepFailed] = useState(false);
	const sheet = useRef(null);
	useEffect(() => {
		sheet.current?.scrollIntoView({ block: "start" });
	}, []);
	const load = useCallback(async () => {
		const got = await api.star(runId);
		setPayload(got);
		setLens((cur) => cur ?? got.view);
	}, [runId]);
	useEffect(() => {
		load();
	}, [load]);
	const pick = (next) => {
		setLens(next);
		api.setMemoryView(runId, next).catch(() => {});
	};
	if (!payload || !lens) return /* @__PURE__ */ jsxs("div", {
		className: "ews-overlay",
		ref: sheet,
		role: "dialog",
		"aria-modal": "true",
		children: [
			/* @__PURE__ */ jsx(StarStyles, {}),
			backdrop ? /* @__PURE__ */ jsx(Backdrop, {
				runId,
				version: backdrop.version,
				mobile: backdrop.mobile
			}) : null,
			/* @__PURE__ */ jsx("div", {
				className: "ews-head",
				children: /* @__PURE__ */ jsx("button", {
					className: "ews-btn",
					type: "button",
					onClick: onClose,
					children: mt(lang, "star.close")
				})
			})
		]
	});
	const focused = focus ? nodeById(payload, focus) : void 0;
	const isKept = focused ? kept.includes(focused.id) || payload.keepsakes.some((kp) => kp.cites.includes(focused.id)) : false;
	const keep = async () => {
		if (!focused || focused.kind !== "event") return;
		setKeepFailed(false);
		try {
			await api.createKeepsake(runId, {
				kind: "event",
				title: focused.title ?? mt(lang, "star.keeps.newTitle"),
				cites: [focused.id]
			});
			setKept((k) => [...k, focused.id]);
			await load();
		} catch {
			setKeepFailed(true);
		}
	};
	return /* @__PURE__ */ jsxs("div", {
		className: "ews-overlay",
		ref: sheet,
		role: "dialog",
		"aria-modal": "true",
		"aria-label": mt(lang, "star.title"),
		children: [
			/* @__PURE__ */ jsx(StarStyles, {}),
			backdrop ? /* @__PURE__ */ jsx(Backdrop, {
				runId,
				version: backdrop.version,
				mobile: backdrop.mobile
			}) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ews-head",
				children: [
					/* @__PURE__ */ jsx("div", {
						className: "ews-title",
						children: mt(lang, "star.title")
					}),
					/* @__PURE__ */ jsx("div", {
						className: "ews-lenses",
						role: "tablist",
						children: [
							"life",
							"people",
							"keepsakes"
						].map((v) => /* @__PURE__ */ jsx("button", {
							className: "ews-lens" + (lens === v ? " ews-lens-on" : ""),
							type: "button",
							role: "tab",
							"aria-selected": lens === v,
							onClick: () => pick(v),
							children: mt(lang, `star.lens.${v}`)
						}, v))
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ews-btn",
						type: "button",
						onClick: onClose,
						children: mt(lang, "star.close")
					})
				]
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ews-toolbar",
				children: [FILTER_KEYS.map((key) => /* @__PURE__ */ jsxs("label", {
					className: "ews-filter",
					children: [/* @__PURE__ */ jsx("input", {
						type: "checkbox",
						checked: filters[key],
						onChange: () => setFilters((f) => ({
							...f,
							[key]: !f[key]
						}))
					}), mt(lang, `star.filter.${key}`)]
				}, key)), lens === "people" ? /* @__PURE__ */ jsx("button", {
					className: "ews-btn ews-mode",
					type: "button",
					onClick: () => setMode((m) => m === "canvas" ? "list" : "canvas"),
					children: mt(lang, mode === "canvas" ? "star.mode.list" : "star.mode.canvas")
				}) : null]
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ews-body",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ews-lens-pane",
					children: lens === "life" ? /* @__PURE__ */ jsx(TimelineLens, {
						payload,
						lang,
						focus,
						setFocus,
						filters
					}) : lens === "people" ? /* @__PURE__ */ jsx(RelationsLens, {
						payload,
						lang,
						focus,
						setFocus,
						filters,
						centre,
						setCentre,
						mode
					}) : /* @__PURE__ */ jsx(KeepsakesLens, {
						runId,
						payload,
						lang,
						focus,
						setFocus,
						onChanged: () => void load()
					})
				}), focused ? /* @__PURE__ */ jsxs("div", {
					className: "ews-detail",
					role: "complementary",
					"aria-live": "polite",
					children: [
						/* @__PURE__ */ jsx("div", {
							className: "ews-detail-name",
							children: nodeLabel(focused)
						}),
						focused.kind === "event" ? /* @__PURE__ */ jsxs(Fragment, { children: [
							/* @__PURE__ */ jsxs("div", {
								className: "ews-detail-meta",
								children: [mt(lang, "star.detail.turn", { n: focused.turn ?? 0 }), focused.summary ? ` · ${focused.summary}` : ""]
							}),
							focused.action ? /* @__PURE__ */ jsxs("div", {
								className: "ews-detail-meta",
								children: [
									mt(lang, "star.detail.action"),
									": ",
									focused.action
								]
							}) : null,
							/* @__PURE__ */ jsxs("div", {
								className: "ews-detail-actions",
								children: [
									/* @__PURE__ */ jsx("button", {
										className: "ews-btn",
										type: "button",
										onClick: () => onJumpTurn(focused.turn ?? 1),
										children: mt(lang, "star.detail.jump")
									}),
									/* @__PURE__ */ jsx("button", {
										className: "ews-btn",
										type: "button",
										disabled: isKept,
										onClick: () => void keep(),
										children: mt(lang, isKept ? "star.keep.kept" : "star.keep.this")
									}),
									keepFailed ? /* @__PURE__ */ jsx("span", {
										className: "ews-detail-meta",
										role: "alert",
										children: mt(lang, "star.keep.failed")
									}) : null
								]
							})
						] }) : /* @__PURE__ */ jsxs("div", {
							className: "ews-detail-meta",
							children: [focused.summary || (focused.aliases ?? []).join(" · "), focused.kind === "thread" ? ` · ${mt(lang, focused.open ? "star.detail.thread.open" : "star.detail.thread.done")}` : ""]
						}),
						/* @__PURE__ */ jsxs("div", {
							className: "ews-detail-related",
							children: [/* @__PURE__ */ jsx("span", {
								className: "ews-kp-cites-label",
								children: mt(lang, "star.detail.related")
							}), neighbours(payload, focused.id).filter((n) => nodeVisible(n, filters)).map((n) => /* @__PURE__ */ jsx("button", {
								className: "ews-chip ews-chip-" + n.kind,
								type: "button",
								onClick: () => setFocus(n.id),
								children: nodeLabel(n)
							}, n.id))]
						})
					]
				}) : null]
			}),
			/* @__PURE__ */ jsx("div", {
				className: "ews-foot",
				children: mt(lang, "star.hint")
			})
		]
	});
}
/** Module-scoped styles, injected with the overlay and gone with it. */
function StarStyles() {
	return /* @__PURE__ */ jsx("style", { children: CSS_TEXT });
}
var CSS_TEXT = `
.ews-overlay {
  /* Absolute, NOT fixed. It is still the same overlay over the same play page —
     only its BOX changes: fixed resolved against the WINDOW, so it painted over the
     dashboard's own chrome, its left menu included. Anchored to .ew-root (the app's
     positioning box) it covers the app and nothing outside it. The open handler
     scrolls it to the top of the viewport, which is what fixed was doing for free
     and why absolute alone once let the story show past it. */
  position: absolute; inset: 0; min-height: 100%; z-index: 60;
  display: flex; flex-direction: column;
  background: var(--bg, #14151f); color: var(--text, #e2e8f0); overflow: hidden;
}
/* When a life backdrop is mounted it sits at z-index 0 inside the overlay (same
 * as .ew-backdrop at the root); lift every other child above it so the map reads
 * over the backdrop instead of under it. */
.ews-overlay > *:not(.ew-backdrop) { position: relative; z-index: 1; }
.ews-head {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px;
  border-bottom: 1px solid var(--border, #2d2f3d);
}
.ews-title { font-weight: 600; }
.ews-lenses { display: flex; gap: 4px; margin-inline: auto; }
.ews-lens {
  appearance: none; border: 1px solid var(--border, #2d2f3d); background: none;
  color: inherit; font: inherit; padding: 5px 14px; border-radius: 999px; cursor: pointer;
}
.ews-lens-on {
  border-color: var(--accent, #7c3aed);
  background: color-mix(in oklab, var(--accent, #7c3aed) 18%, transparent);
}
.ews-btn {
  appearance: none; border: 1px solid var(--border, #2d2f3d); background: none;
  color: inherit; font: inherit; font-size: 13px; padding: 5px 12px;
  border-radius: 8px; cursor: pointer;
}
.ews-btn:disabled { opacity: 0.5; cursor: default; }
.ews-btn-danger { border-color: #b91c1c; color: #f87171; }
.ews-toolbar {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  padding: 8px 16px; border-bottom: 1px solid var(--border, #2d2f3d); font-size: 13px;
}
.ews-filter { display: inline-flex; gap: 5px; align-items: center; cursor: pointer; }
/* Native checkboxes render the browser's blue check; paint them with the app's
 * accent (the same colour the lens tabs and chips use) so they match the rest of
 * the crew UI instead of clashing with a stray blue. */
.ews-filter input[type="checkbox"] { accent-color: var(--accent, #7c3aed); }
.ews-mode { margin-inline-start: auto; }
.ews-body { flex: 1; display: flex; min-height: 0; }
.ews-lens-pane { flex: 1; overflow: auto; padding: 16px; }
.ews-detail {
  flex: 0 0 300px; overflow: auto; padding: 14px 16px;
  border-inline-start: 1px solid var(--border, #2d2f3d);
}
.ews-detail-name { font-weight: 600; margin-bottom: 6px; }
.ews-detail-meta { font-size: 13px; line-height: 1.6; color: var(--muted, #9ca3af); margin-bottom: 6px; }
.ews-detail-actions { display: flex; gap: 8px; margin: 8px 0; }
.ews-detail-related { display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; }
.ews-foot {
  padding: 6px 16px 10px; font-size: 12px; color: var(--muted, #6b7280);
  border-top: 1px solid var(--border, #2d2f3d);
}
.ews-empty { padding: 40px 20px; text-align: center; color: var(--muted, #9ca3af); line-height: 1.8; }
.ews-node {
  appearance: none; border: 0; background: none; color: inherit; font: inherit;
  text-align: start; cursor: pointer; padding: 2px 4px; border-radius: 6px;
}
.ews-node-sel { background: color-mix(in oklab, var(--accent, #7c3aed) 22%, transparent); }
.ews-chip {
  appearance: none; border: 1px solid var(--border, #2d2f3d); background: none;
  color: inherit; font: inherit; font-size: 12px; padding: 2px 10px;
  border-radius: 999px; cursor: pointer;
}
.ews-chip-sel, .ews-chip:hover { border-color: var(--accent, #7c3aed); }
.ews-chip-thread { border-style: dashed; }
.ews-echo-ref {
  appearance: none; border: 0; background: none; cursor: pointer; display: block;
  font: inherit; font-size: 12px; font-style: italic; color: var(--accent, #7c3aed);
  padding: 1px 4px; text-align: start;
}
/* 时间星座 */
.ews-timeline { max-width: 640px; }
.ews-tl-row { display: flex; gap: 12px; }
.ews-tl-spine {
  flex: 0 0 14px; display: flex; justify-content: center; position: relative;
}
.ews-tl-spine::before {
  content: ""; position: absolute; top: 0; bottom: 0; width: 2px;
  background: var(--border, #2d2f3d);
}
.ews-tl-dot {
  position: relative; z-index: 1; width: 10px; height: 10px; border-radius: 50%;
  margin-top: 8px; background: var(--muted, #6b7280);
}
.ews-tl-dot-major { width: 14px; height: 14px; background: var(--accent, #7c3aed); }
.ews-tl-dot-sel { outline: 3px solid color-mix(in oklab, var(--accent, #7c3aed) 40%, transparent); }
.ews-tl-body { flex: 1; padding-bottom: 18px; min-width: 0; }
.ews-tl-turn { font-size: 12px; color: var(--muted, #9ca3af); margin-inline-end: 8px; }
.ews-tl-title { font-weight: 500; }
.ews-tl-cluster { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
/* 关系轨道 */
.ews-centre-row {
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 10px;
  font-size: 13px;
}
.ews-centre-label { color: var(--muted, #9ca3af); }
.ews-canvas { width: 100%; max-width: 640px; height: auto; display: block; margin: 0 auto; }
.ews-orbit { fill: none; stroke: var(--border, #2d2f3d); stroke-dasharray: 3 5; }
.ews-rel-line { stroke: color-mix(in oklab, var(--accent, #7c3aed) 45%, transparent); }
.ews-star { cursor: pointer; }
.ews-star circle { fill: var(--card, #1f2030); stroke: var(--border, #2d2f3d); stroke-width: 1.5; }
.ews-star-centre circle, .ews-star-sel circle { stroke: var(--accent, #7c3aed); stroke-width: 2.5; }
.ews-star text { fill: var(--text, #e5e7eb); font-size: 12px; }
.ews-rel-list { display: flex; flex-direction: column; gap: 10px; max-width: 640px; }
.ews-rel-row {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline;
  padding: 8px 10px; border: 1px solid var(--border, #2d2f3d); border-radius: 10px;
}
.ews-rel-kind { font-size: 13px; color: var(--muted, #9ca3af); }
.ews-rel-srcs { font-size: 12px; display: inline-flex; gap: 4px; align-items: baseline; }
/* 纪念地图 */
.ews-kp-map { display: flex; flex-direction: column; gap: 14px; max-width: 640px; }
.ews-kp {
  padding: 12px 14px; border: 1px solid var(--border, #2d2f3d); border-radius: 12px;
}
.ews-kp-hot { border-color: var(--accent, #7c3aed); }
.ews-kp-title { font-weight: 600; margin-bottom: 4px; }
.ews-kp-title-edit, .ews-kp-thought-edit {
  width: 100%; font: inherit; color: inherit; background: none;
  border: 1px solid var(--border, #2d2f3d); border-radius: 8px; padding: 6px 8px;
  margin-bottom: 6px;
}
.ews-kp-excerpt {
  margin: 6px 0; padding: 6px 10px; font-size: 13px; line-height: 1.7;
  border-inline-start: 3px solid var(--accent, #7c3aed);
  color: var(--muted, #c4c7d0);
}
.ews-kp-excerpt-src { font-size: 11px; margin-top: 4px; color: var(--muted, #6b7280); }
.ews-kp-thought { font-size: 13px; line-height: 1.6; margin-bottom: 6px; }
.ews-kp-cites { display: flex; flex-wrap: wrap; gap: 5px; align-items: baseline; margin: 6px 0; }
.ews-kp-cites-label { font-size: 12px; color: var(--muted, #9ca3af); }
.ews-kp-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 6px; }
.ews-kp-ask { font-size: 12px; color: var(--muted, #9ca3af); }
/* Observatory composition: the narrator's art remains the room, while controls
 * become local frosted instruments instead of an opaque application shell. The
 * horizontal shade protects labels from either a bright or dark backdrop without
 * flattening the whole image to one grey value. */
.ews-overlay:has(> .ew-backdrop) { background: transparent; }
.ews-overlay:has(> .ew-backdrop)::after {
  content: ""; position: absolute; inset: 0; z-index: 1; pointer-events: none;
  background:
    linear-gradient(90deg,
      color-mix(in srgb, var(--bg, #14151f) 68%, transparent),
      color-mix(in srgb, var(--bg, #14151f) 16%, transparent) 58%,
      color-mix(in srgb, var(--bg, #14151f) 42%, transparent)),
    linear-gradient(to bottom,
      color-mix(in srgb, var(--bg, #14151f) 12%, transparent),
      color-mix(in srgb, var(--bg, #14151f) 30%, transparent));
}
.ews-overlay > *:not(.ew-backdrop) { z-index: 2; }
.ews-head,
.ews-toolbar,
.ews-lens-pane,
.ews-detail,
.ews-foot {
  border: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 82%, transparent);
  background: color-mix(in srgb, var(--card, #1f2030) 72%, transparent);
  -webkit-backdrop-filter: blur(18px) saturate(1.08);
  backdrop-filter: blur(18px) saturate(1.08);
  box-shadow: 0 18px 48px color-mix(in srgb, var(--bg, #14151f) 28%, transparent);
}
.ews-head {
  margin: 12px 16px 0; padding: 10px 12px; border-radius: 14px;
}
.ews-title { letter-spacing: .01em; }
.ews-lenses {
  padding: 3px; border: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 76%, transparent);
  border-radius: 999px; background: color-mix(in srgb, var(--bg, #14151f) 28%, transparent);
}
.ews-lens {
  border-color: transparent; padding: 6px 16px;
  transition: color .16s ease, background .16s ease, border-color .16s ease;
}
.ews-lens-on {
  color: var(--text, #e5e7eb); border-color: color-mix(in srgb, var(--accent, #7c3aed) 46%, transparent);
  background: color-mix(in srgb, var(--accent, #7c3aed) 20%, transparent);
}
.ews-btn,
.ews-chip {
  background: color-mix(in srgb, var(--card, #1f2030) 50%, transparent);
  -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
}
.ews-btn:hover:not(:disabled),
.ews-chip:hover {
  border-color: color-mix(in srgb, var(--accent, #7c3aed) 72%, var(--border, #2d2f3d));
  background: color-mix(in srgb, var(--accent, #7c3aed) 12%, transparent);
}
.ews-toolbar {
  margin: 8px 16px 0; padding: 7px 10px; gap: 7px; border-radius: 12px;
  box-shadow: none;
}
.ews-filter {
  padding: 5px 9px; border: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 74%, transparent);
  border-radius: 999px; background: color-mix(in srgb, var(--card, #1f2030) 46%, transparent);
}
.ews-filter:has(input:checked) {
  border-color: color-mix(in srgb, var(--accent, #7c3aed) 50%, var(--border, #2d2f3d));
  background: color-mix(in srgb, var(--accent, #7c3aed) 10%, transparent);
}
.ews-body { gap: 14px; padding: 14px 16px 16px; }
.ews-lens-pane {
  padding: 16px; border-radius: 16px;
  background: color-mix(in srgb, var(--card, #1f2030) 28%, transparent);
  -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px);
  box-shadow: none;
}
.ews-detail {
  flex-basis: 300px; margin: 0; padding: 17px;
  border-inline-start: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 82%, transparent);
  border-radius: 16px;
}
.ews-detail-name { font-size: 15px; margin-bottom: 8px; }
.ews-detail-meta { color: color-mix(in srgb, var(--text, #e5e7eb) 68%, var(--muted, #9ca3af)); }
.ews-detail-actions { margin: 14px 0; }
.ews-foot {
  margin: 0 16px 10px; padding: 7px 10px; border-radius: 10px;
  color: color-mix(in srgb, var(--text, #e5e7eb) 62%, var(--muted, #6b7280));
  box-shadow: none;
}
.ews-orbit {
  stroke: color-mix(in srgb, var(--accent, #7c3aed) 42%, var(--border, #2d2f3d));
}
.ews-rel-line { stroke: color-mix(in srgb, var(--accent, #7c3aed) 62%, transparent); }
.ews-star circle {
  fill: color-mix(in srgb, var(--card, #1f2030) 78%, transparent);
  stroke: color-mix(in srgb, var(--border, #2d2f3d) 88%, transparent);
}
.ews-star-centre circle,
.ews-star-sel circle {
  filter: drop-shadow(0 0 8px color-mix(in srgb, var(--accent, #7c3aed) 65%, transparent));
}
.ews-kp,
.ews-rel-row {
  background: color-mix(in srgb, var(--card, #1f2030) 58%, transparent);
  -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px);
}
.ews-tl-dot-major {
  box-shadow: 0 0 14px color-mix(in srgb, var(--accent, #7c3aed) 65%, transparent);
}

/* The phone detail is a sheet, not the last row of a long column. Its entrance is
 * the feedback that a star tap did something; anchoring it above the portalled tab
 * bar keeps that feedback in the player's current field of view. */
@keyframes ews-detail-rise {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

/* The portalled bottom bar is rendered through 1100px, including large phones in
 * landscape. In that whole range, raise detail as a sheet and reserve the bar plus
 * the device safe area rather than letting either cover selected-star feedback. */
@media (max-width: 1100px) {
  .ews-body {
    --ews-tab-clearance: calc(74px + env(safe-area-inset-bottom, 0px));
    padding-bottom: var(--ews-tab-clearance);
  }
  .ews-detail {
    position: absolute; inset-inline: 10px; bottom: var(--ews-tab-clearance); z-index: 4;
    box-sizing: border-box; flex: 0 0 auto; max-height: 38dvh; padding: 14px;
    border-inline-start: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 82%, transparent);
    border-top: 2px solid color-mix(in srgb, var(--accent, #7c3aed) 72%, var(--border, #2d2f3d));
    box-shadow: 0 -12px 40px color-mix(in srgb, var(--bg, #14151f) 55%, transparent);
    animation: ews-detail-rise .18s ease-out;
  }
  .ews-foot { display: none; }
}

/* Below 860px the controls also take their compact, single-column form. */
@media (max-width: 860px) {
  .ews-head { margin: 8px 10px 0; padding: 9px 10px; flex-wrap: wrap; gap: 8px; }
  .ews-title { flex: 1; }
  .ews-lenses { order: 3; width: 100%; margin-inline: 0; justify-content: center; }
  .ews-lens { flex: 1; padding-inline: 8px; }
  .ews-toolbar {
    margin: 7px 10px 0; padding: 6px 8px; flex-wrap: nowrap; overflow-x: auto;
    scrollbar-width: none;
  }
  .ews-toolbar::-webkit-scrollbar { display: none; }
  .ews-filter { flex: 0 0 auto; }
  .ews-body {
    flex-direction: column; gap: 8px; padding: 8px 10px var(--ews-tab-clearance);
  }
  .ews-lens-pane { padding: 12px; min-height: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .ews-detail { animation: none; }
}
`;
//#endregion
//#region src/play.tsx
/** How often a life mid-generation is re-read. A month takes tens of seconds, so
*  this is about the page converging on its own rather than about latency. */
var GENERATING_POLL_MS = 3e3;
/** How many awaiting-only polls to allow before going quiet. Polling while a
*  life merely AWAITS its opening catches the `generating` mark that begin()
*  fires in the background — but that turn runs against the backend's 300s
*  OPENING_DEADLINE_SECS, so the mark can land well after begin() (agent spin-up,
*  a queued slot, a slow model). Capped just past that deadline (110 × 3s ≈ 330s)
*  so the arranging screen keeps refreshing for the whole opening; only a life
*  whose opening genuinely never landed falls through to the "continue birth"
*  button. A shorter cap stranded the arranging screen at 60s on slow openings. */
var AWAITING_POLL_CAP = 110;
/**
* What the player has armed or committed.
*
* A world's choice ids come from the narrator, so no sentinel string is safe from
* colliding with one. The prefix therefore goes on the NARRATOR's side: the two
* fixed targets keep plain names, and anything world-supplied is namespaced. A
* narrator that emits a choice literally called "act" cannot then hijack the
* free-text button's state.
*/
var ACT = "act";
var OPEN = "open";
var choiceTarget = (id) => `c:${id}`;
function Chevron({ dir }) {
	return /* @__PURE__ */ jsx("svg", {
		width: "18",
		height: "18",
		viewBox: "0 0 18 18",
		"aria-hidden": "true",
		children: /* @__PURE__ */ jsx("path", {
			d: dir === "l" ? "M11 4 L6 9 L11 14" : "M7 4 L12 9 L7 14",
			fill: "none",
			stroke: "currentColor",
			strokeWidth: "2",
			strokeLinecap: "round",
			strokeLinejoin: "round"
		})
	});
}
/**
* Live feedback while a month is written. The bar advances a notch per narrator
* tool call (`generating.steps`, ~16% each, capped at 92% until commit); the
* label reuses the app's existing, already-tuned waiting copy rather than a
* generic stage name, so the wording stays consistent with the rest of the wait.
*/
function TurnProgress({ g, label }) {
	const steps = g?.steps ?? 0;
	const pct = Math.min(12 + steps * 16, 92);
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-progress",
		role: "status",
		"aria-live": "polite",
		children: [/* @__PURE__ */ jsx("div", {
			className: "ew-progress-track",
			children: /* @__PURE__ */ jsx("div", {
				className: "ew-progress-fill",
				style: { width: `${pct}%` }
			})
		}), /* @__PURE__ */ jsx("div", {
			className: "ew-progress-steps",
			children: /* @__PURE__ */ jsx("span", {
				className: "ew-progress-label",
				children: label
			})
		})]
	});
}
/**
* One "an old thing came back" marker (design §8.1). Deliberately quiet: a single
* folded line after the prose, expanding to the source moment, the player's own
* choice back then, how this turn answers it, and a jump to the source page. No
* celebration, no sound, no modal — the prose stays the protagonist.
*/
function EchoMark({ e, lang, runId, onJump }) {
	const [open, setOpen] = useState(false);
	const [kept, setKept] = useState(false);
	const [keepFailed, setKeepFailed] = useState(false);
	const keep = async () => {
		setKeepFailed(false);
		try {
			await api.createKeepsake(runId, {
				kind: "echo",
				title: e.title || e.sourceTitle,
				cites: [e.sourceId, e.currentId].filter(Boolean)
			});
			setKept(true);
		} catch {
			setKeepFailed(true);
		}
	};
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-echo",
		children: [/* @__PURE__ */ jsx("button", {
			className: "ew-echo-line",
			type: "button",
			"aria-expanded": open,
			onClick: () => setOpen((o) => !o),
			children: t("play.echoLine", { turn: e.sourceTurn })
		}), open ? /* @__PURE__ */ jsxs("div", {
			className: "ew-echo-body",
			children: [
				/* @__PURE__ */ jsxs("div", {
					className: "ew-echo-row",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-echo-label",
						children: t("play.echoThen")
					}), /* @__PURE__ */ jsxs("span", { children: [/* @__PURE__ */ jsx("strong", { children: e.sourceTitle }), e.sourceSummary ? ` — ${e.sourceSummary}` : ""] })]
				}),
				e.sourceAction ? /* @__PURE__ */ jsxs("div", {
					className: "ew-echo-row",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-echo-label",
						children: t("play.echoYouDid")
					}), /* @__PURE__ */ jsx("span", { children: e.sourceAction })]
				}) : null,
				/* @__PURE__ */ jsxs("div", {
					className: "ew-echo-row",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-echo-label",
						children: t("play.echoNow")
					}), /* @__PURE__ */ jsxs("span", { children: [/* @__PURE__ */ jsx("strong", { children: e.title }), e.summary ? ` — ${e.summary}` : ""] })]
				}),
				/* @__PURE__ */ jsxs("div", {
					className: "ew-echo-actions",
					children: [
						/* @__PURE__ */ jsx("button", {
							className: "ew-btn ew-btn-sm",
							type: "button",
							onClick: () => onJump(e.sourceTurn),
							children: t("play.echoJump")
						}),
						/* @__PURE__ */ jsx("button", {
							className: "ew-btn ew-btn-sm",
							type: "button",
							disabled: kept,
							onClick: () => void keep(),
							children: mt(lang, kept ? "star.keep.kept" : "star.keep.this")
						}),
						keepFailed ? /* @__PURE__ */ jsx("span", {
							className: "ew-meta",
							role: "alert",
							children: mt(lang, "star.keep.failed")
						}) : null,
						/* @__PURE__ */ jsx("button", {
							className: "ew-btn ew-btn-sm",
							type: "button",
							onClick: () => setOpen(false),
							children: t("play.echoClose")
						})
					]
				})
			]
		}) : null]
	});
}
function PlayPage({ runId, onBack, onScenes, onBackdrop, onReplay, onReplaySame, onEnterLife, refresh, readerBar = false, openStar, onStarClose, onSheetOpen, onLiveTurn, narrow, onPanels, turnPending = false }) {
	const [v, setV] = useState(null);
	const [error, setError] = useState(null);
	const [action, setAction] = useState("");
	const [tapped, setTapped] = useState("");
	const [arm, setArm] = useState("");
	const [phrase, setPhrase] = useState("");
	const [arrange, setArrange] = useState("");
	const [stalled, setStalled] = useState(false);
	const [retry, setRetry] = useState(null);
	const [drawer, setDrawer] = useState(false);
	const [starOpen, setStarOpen] = useState(false);
	const [asideTab, setAsideTab] = useState("");
	/** Per-region content signature last seen on the aside, so a region tab dots on
	*  an unseen change — the same notification affordance the phone bottom bar has. */
	const asideSeenRef = useRef({});
	const [legacyOpen, setLegacyOpen] = useState(false);
	const sheetOpen = starOpen || legacyOpen;
	useEffect(() => {
		onSheetOpen?.(sheetOpen);
	}, [sheetOpen, onSheetOpen]);
	const [back, setBack] = useState(false);
	const loadedRun = useRef(null);
	const [recapOpen, setRecapOpen] = useState(false);
	const barHidden = useScrollHide(readerBar, 70);
	const [viewTurn, setViewTurn] = useState(null);
	const [chron, setChron] = useState([]);
	useEffect(() => {
		if (!v || v.turn < 1) return void 0;
		let alive = true;
		setViewTurn(null);
		api.chronicle(runId).then((c) => {
			if (alive) setChron(c.turns);
		}).catch(() => {});
		return () => {
			alive = false;
		};
	}, [runId, v?.turn]);
	const pageFetchRef = useRef(0);
	useEffect(() => {
		if (!v || viewTurn === null || viewTurn >= v.turn) return void 0;
		if (chron.some((c) => c.turn === viewTurn)) return void 0;
		if (pageFetchRef.current === viewTurn) return void 0;
		pageFetchRef.current = viewTurn;
		let alive = true;
		api.chronicle(runId, viewTurn + 1).then((c) => {
			if (!alive) return;
			setChron((have) => {
				const seen = new Set(have.map((p) => p.turn));
				return [...have, ...c.turns.filter((p) => !seen.has(p.turn))];
			});
		}).catch(() => {}).finally(() => {
			pageFetchRef.current = 0;
		});
		return () => {
			alive = false;
		};
	}, [
		runId,
		v,
		viewTurn,
		chron
	]);
	const prevTurnRef = useRef(0);
	useEffect(() => {
		document.querySelector(".ew-root")?.scrollIntoView({ block: "start" });
		prevTurnRef.current = viewTurn ?? v?.turn ?? 0;
	}, [viewTurn, v?.turn]);
	const load = useCallback(async () => {
		try {
			const next = await api.run(runId);
			setV(next);
			setError(null);
			if (loadedRun.current !== runId) {
				loadedRun.current = runId;
				const recap = next.recap;
				setRecapOpen(next.turn > 1 && !!(recap.lastAction || recap.events.length));
			}
		} catch (e) {
			setError(e.message);
		}
	}, [runId]);
	useEffect(() => {
		load();
	}, [load, refresh]);
	/**
	* A month being written is a fact on the server, not a fact about this page.
	*
	* The bug this closes: waiting was `busy`, a React boolean, so leaving the page
	* while the world was being made and coming back showed a life that looked like
	* nobody had ever asked for it — the request's poll loop had died with the page.
	* The backend now records the asking before it speaks to the narrator, so the
	* server can be believed over local memory, and coming back converges on its own
	* instead of needing the player to guess whether to tap again.
	*/
	const generating = !!v?.generating;
	const awaiting = !!v?.awaitingOpening;
	useEffect(() => {
		if (!generating && !awaiting) return void 0;
		if (generating) setPhrase((p) => p || pick("play.waiting"));
		let ticks = 0;
		const timer = window.setInterval(() => {
			ticks += 1;
			if (!generating && ticks > AWAITING_POLL_CAP) {
				window.clearInterval(timer);
				return;
			}
			load();
		}, GENERATING_POLL_MS);
		return () => window.clearInterval(timer);
	}, [
		generating,
		awaiting,
		load
	]);
	const busy = !!tapped || generating || turnPending;
	const gAction = v?.generating?.action ?? "";
	const genChoice = generating && gAction ? (v?.choices ?? []).find((c) => c.label === gAction) : void 0;
	useEffect(() => {
		if (!(v?.awaitingOpening && generating)) return void 0;
		setArrange(pick("opening.waiting"));
		const timer = window.setInterval(() => setArrange(pick("opening.waiting")), 4e3);
		return () => window.clearInterval(timer);
	}, [v?.awaitingOpening, generating]);
	useEffect(() => {
		if (!(generating && !awaiting)) return void 0;
		setPhrase(pick("play.waiting"));
		const timer = window.setInterval(() => setPhrase(pick("play.waiting")), 4e3);
		return () => window.clearInterval(timer);
	}, [generating, awaiting]);
	const setLanguage = useSetLanguage();
	useEffect(() => {
		setLanguage(v?.language);
	}, [v, setLanguage]);
	const scenesSig = JSON.stringify(v?.scenes ?? []);
	useEffect(() => {
		onScenes(v?.scenes ?? []);
	}, [scenesSig, onScenes]);
	useEffect(() => {
		if (openStar !== void 0) setStarOpen(openStar);
	}, [openStar]);
	useEffect(() => {
		if (v && v.turn) onLiveTurn?.(v.turn);
	}, [v?.turn, onLiveTurn]);
	const panelsSig = JSON.stringify(v?.panels ?? []);
	useEffect(() => {
		onPanels?.(v?.panels ?? []);
	}, [panelsSig, onPanels]);
	const backdropSig = JSON.stringify([
		v?.backdrop,
		v?.turn,
		viewTurn
	]);
	useEffect(() => {
		if (!v) {
			onBackdrop(null);
			return;
		}
		const latest = v.turn;
		const shown = viewTurn ?? latest;
		if (shown >= latest) onBackdrop(v.backdrop ? {
			version: v.backdrop.version,
			turn: latest,
			mobile: v.backdrop.mobile
		} : null);
		else {
			const past = chron.find((c) => c.turn === shown)?.backdrop;
			onBackdrop(past ? {
				version: past.version,
				turn: shown,
				mobile: past.mobile
			} : v.backdrop ?? null);
		}
	}, [
		backdropSig,
		chron,
		onBackdrop
	]);
	const take = async (payload, what) => {
		setTapped(what);
		setPhrase(pick("play.waiting"));
		setStalled(false);
		try {
			const out = await api.takeTurn(runId, payload);
			if (out.advanced || out.reason === "already" || out.reason === "ended") {
				setAction("");
				setRetry(null);
			} else {
				setStalled(true);
				setRetry({
					payload,
					what
				});
			}
			await load();
		} catch {
			setStalled(true);
			setRetry({
				payload,
				what
			});
		}
		setTapped("");
	};
	if (error && !v) return /* @__PURE__ */ jsxs("div", { children: [
		/* @__PURE__ */ jsx("button", {
			className: "ew-back",
			type: "button",
			onClick: onBack,
			children: t("play.back")
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-meta",
			children: t("world.unreadableDetail", { error })
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-bar",
			children: /* @__PURE__ */ jsx("button", {
				className: "ew-btn",
				type: "button",
				onClick: () => {
					setError(null);
					load();
				},
				children: t("play.retry")
			})
		})
	] });
	if (!v) return /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("play.opening")
	});
	const recap = v.recap ?? {
		lastAction: "",
		events: [],
		choices: []
	};
	const reveals = v.reveals ?? [];
	if (v.awaitingOpening) return /* @__PURE__ */ jsxs("div", { children: [
		/* @__PURE__ */ jsx("button", {
			className: "ew-back",
			type: "button",
			onClick: onBack,
			children: t("play.back")
		}),
		/* @__PURE__ */ jsx("h3", {
			className: "ew-detail-title",
			children: v.title
		}),
		generating ? /* @__PURE__ */ jsxs("div", {
			className: "ew-arrange",
			children: [/* @__PURE__ */ jsx("div", {
				className: "ew-arrange-title",
				children: t("opening.arranging")
			}), /* @__PURE__ */ jsx(TurnProgress, {
				g: v.generating,
				label: arrange || t("opening.arranging")
			})]
		}) : /* @__PURE__ */ jsxs(Fragment, { children: [
			/* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: busy ? t("opening.arranging") : t("opening.notStarted")
			}),
			stalled && !busy ? /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: t("opening.silent")
			}) : null,
			/* @__PURE__ */ jsx("div", {
				className: "ew-bar",
				children: /* @__PURE__ */ jsxs("button", {
					className: "ew-btn ew-btn-go",
					type: "button",
					disabled: busy,
					onClick: async () => {
						setTapped(OPEN);
						setPhrase(pick("opening.waiting"));
						setStalled(false);
						try {
							const out = await api.openRun(runId);
							if (!out.advanced && out.reason !== "already") setStalled(true);
							await load();
						} catch {
							setStalled(true);
						}
						setTapped("");
					},
					children: [t("opening.continueBirth"), tapped === OPEN ? /* @__PURE__ */ jsx(Waiting, { label: phrase }) : null]
				})
			})
		] })
	] });
	const past = viewTurn !== null && viewTurn < v.turn ? chron.find((c) => c.turn === viewTurn) : void 0;
	const shownDigest = past ? past.digest ?? v.digest ?? [] : v.digest ?? [];
	const shownPanels = past ? past.panels ?? v.panels ?? [] : v.panels ?? [];
	const panels = /* @__PURE__ */ jsx(Fragment, { children: shownPanels.map((p) => /* @__PURE__ */ jsx(PanelBox, { panel: p }, p.id)) });
	if (v.ended) return /* @__PURE__ */ jsxs("div", { children: [
		legacyOpen ? /* @__PURE__ */ jsx(LegacyPicker, {
			runId,
			lang: v.language,
			onClose: () => setLegacyOpen(false),
			onContinue: async (selected) => {
				const created = await api.createRun({
					worldId: v.worldId,
					language: v.language,
					legacy: {
						fromRunId: runId,
						selected
					}
				});
				api.openRun(created.runId);
				onEnterLife(created.runId);
			}
		}) : null,
		/* @__PURE__ */ jsx("button", {
			className: "ew-back",
			type: "button",
			onClick: onBack,
			children: t("play.back")
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-clock",
			children: v.clock || t("play.turn", { turn: v.turn })
		}),
		/* @__PURE__ */ jsx("h3", {
			className: "ew-detail-title",
			children: v.title
		}),
		/* @__PURE__ */ jsx("div", {
			className: "ew-note ew-note-live",
			children: t("play.endedBadge")
		}),
		/* @__PURE__ */ jsx(Prose, { text: v.prose }),
		/* @__PURE__ */ jsx("div", {
			className: "ew-meta",
			children: t("play.endedMeta", { turn: v.turn })
		}),
		/* @__PURE__ */ jsx(LifeSummary, { runId }),
		/* @__PURE__ */ jsxs("div", {
			className: "ew-bar",
			children: [
				v.lineage ? /* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-go",
					type: "button",
					onClick: () => setLegacyOpen(true),
					children: mt(v.language, "legacy.entry")
				}) : null,
				/* @__PURE__ */ jsx("button", {
					className: "ew-btn" + (v.lineage ? "" : " ew-btn-go"),
					type: "button",
					onClick: () => onReplaySame(runId),
					children: t("play.endedReplaySame")
				}),
				/* @__PURE__ */ jsx("button", {
					className: "ew-btn",
					type: "button",
					onClick: () => onReplay(v.worldId),
					children: t("play.endedReplay")
				}),
				/* @__PURE__ */ jsx("button", {
					className: "ew-btn",
					type: "button",
					onClick: onBack,
					children: t("play.endedShelf")
				})
			]
		}),
		/* @__PURE__ */ jsx("button", {
			className: "ew-drawer",
			type: "button",
			"aria-expanded": back,
			"aria-controls": "ew-history-panel-ended",
			onClick: () => setBack((b) => !b),
			children: back ? t("history.close") : t("history.open")
		}),
		back ? /* @__PURE__ */ jsx("div", {
			id: "ew-history-panel-ended",
			children: /* @__PURE__ */ jsx(History, { runId })
		}) : null
	] });
	const latest = v.turn;
	const shownTurn = viewTurn ?? latest;
	const isLive = shownTurn >= latest;
	const shownEntry = isLive ? void 0 : chron.find((c) => c.turn === shownTurn);
	const pageLoading = !isLive && !shownEntry;
	const shownProse = isLive ? v.prose : shownEntry?.prose ?? "";
	const pastAction = isLive ? "" : shownEntry?.action ?? "";
	const pageDir = shownTurn >= prevTurnRef.current ? "fwd" : "back";
	const pager = latest >= 1 ? /* @__PURE__ */ jsxs("div", {
		className: "ew-pager",
		children: [
			/* @__PURE__ */ jsx("button", {
				className: "ew-pager-arw",
				type: "button",
				disabled: shownTurn <= 1,
				"aria-label": t("play.prevTurn"),
				onClick: () => setViewTurn(Math.max(1, shownTurn - 1)),
				children: /* @__PURE__ */ jsx(Chevron, { dir: "l" })
			}),
			/* @__PURE__ */ jsx("span", {
				className: "ew-pager-turn",
				children: t("play.page", { n: shownTurn })
			}),
			/* @__PURE__ */ jsx("button", {
				className: "ew-pager-arw",
				type: "button",
				disabled: shownTurn >= latest,
				"aria-label": t("play.nextTurn"),
				onClick: () => setViewTurn(shownTurn + 1 >= latest ? null : shownTurn + 1),
				children: /* @__PURE__ */ jsx(Chevron, { dir: "r" })
			})
		]
	}) : null;
	const main = /* @__PURE__ */ jsxs("div", { children: [
		isLive && recapOpen ? /* @__PURE__ */ jsxs("section", {
			className: "ew-story-moment",
			"aria-label": t("play.recapTitle"),
			children: [
				/* @__PURE__ */ jsxs("div", {
					className: "ew-story-moment-head",
					children: [/* @__PURE__ */ jsx("div", {
						className: "ew-story-moment-title",
						children: t("play.recapTitle")
					}), /* @__PURE__ */ jsx("button", {
						className: "ew-story-moment-close",
						type: "button",
						onClick: () => setRecapOpen(false),
						children: t("play.recapDismiss")
					})]
				}),
				recap.lastAction ? /* @__PURE__ */ jsxs("div", {
					className: "ew-recap-line",
					children: [/* @__PURE__ */ jsxs("span", {
						className: "ew-recap-label",
						children: [t("play.recapLastChoice"), " "]
					}), recap.lastAction]
				}) : null,
				recap.events.length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("div", {
					className: "ew-recap-label",
					children: t("play.recapRecent")
				}), /* @__PURE__ */ jsx("ul", {
					className: "ew-recap-list",
					children: recap.events.map((event, i) => /* @__PURE__ */ jsx("li", { children: event }, `${i}-${event}`))
				})] }) : null
			]
		}) : null,
		isLive && v.turn === 1 && reveals.length ? /* @__PURE__ */ jsxs("section", {
			className: "ew-story-moment",
			"aria-label": t("play.birthRevealTitle"),
			children: [
				/* @__PURE__ */ jsx("div", {
					className: "ew-story-moment-title",
					children: t("play.birthRevealTitle")
				}),
				reveals.map((reveal, i) => /* @__PURE__ */ jsxs("div", {
					className: "ew-reveal-row",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-reveal-label",
						children: reveal.label
					}), /* @__PURE__ */ jsx("span", {
						className: "ew-reveal-value",
						children: reveal.value
					})]
				}, `${i}-${reveal.label}`)),
				/* @__PURE__ */ jsx("div", {
					className: "ew-story-moment-hint",
					children: t("play.birthRevealHint")
				})
			]
		}) : null,
		(v.unlocked ?? []).length ? /* @__PURE__ */ jsx("div", {
			className: "ew-unlocked",
			role: "status",
			"aria-live": "polite",
			children: (v.unlocked ?? []).map((h, i) => /* @__PURE__ */ jsxs("div", {
				className: "ew-unlocked-row",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-unlocked-heading",
					children: t("play.unlocked", { heading: h })
				}), /* @__PURE__ */ jsx("div", {
					className: "ew-unlocked-meaning",
					children: t("play.unlockedMeaning", { heading: h })
				})]
			}, `${h}-${i}`))
		}) : null,
		(v.milestonesReached ?? []).length ? /* @__PURE__ */ jsx("div", {
			className: "ew-milestone",
			role: "status",
			"aria-live": "polite",
			children: (v.milestonesReached ?? []).map((m, i) => /* @__PURE__ */ jsx("div", {
				className: "ew-milestone-row",
				children: t("play.milestone", { label: m })
			}, `${m}-${i}`))
		}) : null,
		shownDigest.length ? /* @__PURE__ */ jsx("div", {
			className: "ew-digest",
			children: shownDigest.map((dg, i) => /* @__PURE__ */ jsxs("div", {
				className: `ew-drow${dg.rumour ? " ew-drow-rumour" : ""}`,
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-dcat",
					children: dg.category === "rumour" ? t("play.rumour") : dg.category
				}), /* @__PURE__ */ jsxs("div", { children: [dg.text, dg.rumour && dg.category !== "rumour" ? /* @__PURE__ */ jsx("span", {
					className: "ew-sub",
					children: t("play.rumourSuffix")
				}) : null] })]
			}, `${dg.category}-${i}`))
		}) : null,
		!isLive && pastAction ? /* @__PURE__ */ jsx("div", {
			className: "ew-hint",
			children: t("history.chose", { action: pastAction })
		}) : null,
		/* @__PURE__ */ jsx("div", {
			className: `ew-turnpage ew-turnpage-${pageDir}`,
			children: pageLoading ? /* @__PURE__ */ jsx("div", {
				className: "ew-meta",
				children: t("history.reading")
			}) : /* @__PURE__ */ jsx(Prose, { text: shownProse })
		}, shownTurn),
		isLive && (v.echoes ?? []).length ? /* @__PURE__ */ jsx("div", {
			className: "ew-echoes",
			children: (v.echoes ?? []).map((e, i) => /* @__PURE__ */ jsx(EchoMark, {
				e,
				lang: v.language,
				runId,
				onJump: (turn) => setViewTurn(turn >= latest ? null : turn)
			}, `${e.sourceId}-${i}`))
		}) : null,
		generating && !genChoice ? /* @__PURE__ */ jsxs("div", {
			className: "ew-note ew-note-live",
			role: "status",
			"aria-live": "polite",
			children: [gAction ? /* @__PURE__ */ jsx("div", {
				className: "ew-writing-action",
				children: t("play.writingAction", { action: gAction })
			}) : null, /* @__PURE__ */ jsx(TurnProgress, {
				g: v.generating,
				label: phrase || t("play.generating")
			})]
		}) : null,
		stalled && !generating ? /* @__PURE__ */ jsxs("div", {
			className: "ew-note",
			role: "status",
			"aria-live": "polite",
			children: [t("play.stalled"), retry ? /* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-sm",
				type: "button",
				disabled: busy,
				style: { marginInlineStart: "8px" },
				onClick: () => void take(retry.payload, retry.what),
				children: t("play.retry")
			}) : null]
		}) : null,
		isLive && (v.choices ?? []).length ? /* @__PURE__ */ jsx("div", {
			className: "ew-choices",
			children: (v.choices ?? []).map((c) => {
				const target = choiceTarget(c.id);
				const armed = arm === target;
				const sending = tapped === target;
				const writing = sending || generating && !!gAction && c.label === gAction;
				const dimmed = generating && !!genChoice && !writing;
				return /* @__PURE__ */ jsxs("div", {
					className: "ew-choicewrap",
					children: [/* @__PURE__ */ jsxs("button", {
						className: "ew-choice" + (c.fateful || c.art ? " ew-choice-fateful" : "") + (c.art ? " ew-choice-arted" : "") + effectClass(c.effect) + (armed ? " ew-choice-armed" : "") + (writing ? " ew-choice-waiting" : "") + (dimmed ? " ew-choice-dimmed" : ""),
						style: c.tint ? { "--fx-tint": c.tint } : void 0,
						type: "button",
						disabled: busy,
						"aria-pressed": armed,
						"aria-busy": writing,
						onClick: () => setArm(armed ? "" : target),
						children: [
							c.art ? /* @__PURE__ */ jsx("img", {
								className: "ew-choice-art",
								src: `data:image/svg+xml;utf8,${encodeURIComponent(c.art)}`,
								alt: "",
								"aria-hidden": "true",
								draggable: false,
								onError: (e) => {
									e.currentTarget.style.display = "none";
								}
							}) : v.backdrop?.buttons ? /* @__PURE__ */ jsx("img", {
								className: "ew-choice-art ew-choice-art-common",
								src: `${API}/runs/${encodeURIComponent(runId)}/backdrop?part=buttons&turn=${v.turn}&v=${v.backdrop.version}`,
								alt: "",
								"aria-hidden": "true",
								draggable: false,
								onError: (e) => {
									e.currentTarget.style.display = "none";
								}
							}) : null,
							/* @__PURE__ */ jsx("span", {
								className: "ew-choice-label",
								children: c.label
							}),
							/* @__PURE__ */ jsx(ChoiceEffect, {
								effect: c.effect,
								tint: c.tint
							}),
							writing && generating ? /* @__PURE__ */ jsx(TurnProgress, {
								g: v.generating,
								label: phrase || t("play.generating")
							}) : sending ? /* @__PURE__ */ jsx(Waiting, { label: phrase }) : null
						]
					}), armed && !busy ? /* @__PURE__ */ jsxs("div", {
						className: "ew-confirm",
						children: [
							/* @__PURE__ */ jsx("span", {
								className: "ew-confirm-ask",
								children: t("play.confirmAsk")
							}),
							/* @__PURE__ */ jsx("button", {
								className: "ew-btn ew-btn-go ew-btn-sm",
								type: "button",
								onClick: () => {
									setArm("");
									take({
										turn: v.turn + 1,
										action: c.label
									}, target);
								},
								children: t("play.confirmYes")
							}),
							/* @__PURE__ */ jsx("button", {
								className: "ew-btn ew-btn-sm",
								type: "button",
								onClick: () => setArm(""),
								children: t("play.confirmNo")
							})
						]
					}) : null]
				}, c.id);
			})
		}) : null,
		isLive ? /* @__PURE__ */ jsxs("div", { children: [
			/* @__PURE__ */ jsxs("div", {
				className: "ew-act",
				children: [/* @__PURE__ */ jsx("textarea", {
					value: action,
					maxLength: 500,
					rows: 2,
					placeholder: t("play.actionPlaceholder"),
					disabled: busy,
					onChange: (e) => {
						setAction(e.target.value);
						setArm("");
					},
					onKeyDown: (e) => {
						if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && action.trim() && !busy) {
							e.preventDefault();
							setArm("");
							take({
								turn: v.turn + 1,
								action: action.trim()
							}, ACT);
						}
					}
				}), /* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-go",
					type: "button",
					style: {
						flex: "0 0 auto",
						minWidth: 0,
						padding: "0 16px"
					},
					disabled: busy || !action.trim(),
					onClick: () => setArm(arm === ACT ? "" : ACT),
					"aria-pressed": arm === ACT,
					children: t("play.act")
				})]
			}),
			arm === ACT && !busy ? /* @__PURE__ */ jsxs("div", {
				className: "ew-confirm ew-confirm-act",
				children: [
					/* @__PURE__ */ jsx("span", {
						className: "ew-confirm-ask",
						children: t("play.confirmAct")
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-go ew-btn-sm",
						type: "button",
						onClick: () => {
							setArm("");
							take({
								turn: v.turn + 1,
								action: action.trim()
							}, ACT);
						},
						children: t("play.confirmYes")
					}),
					/* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-sm",
						type: "button",
						onClick: () => setArm(""),
						children: t("play.confirmNo")
					})
				]
			}) : null,
			tapped === ACT ? /* @__PURE__ */ jsx("div", {
				className: "ew-confirm ew-confirm-act",
				children: /* @__PURE__ */ jsx(Waiting, { label: phrase })
			}) : null,
			action.length > 400 ? /* @__PURE__ */ jsx("div", {
				className: "ew-count",
				children: `${action.length} / 500`
			}) : null
		] }) : null,
		!narrow ? /* @__PURE__ */ jsx("button", {
			className: "ew-drawer",
			type: "button",
			"aria-expanded": drawer,
			"aria-controls": "ew-panels-drawer",
			onClick: () => setDrawer((d) => !d),
			children: drawer ? t("play.drawerClose") : t("play.drawerOpen")
		}) : null,
		drawer && !narrow ? /* @__PURE__ */ jsx("div", {
			id: "ew-panels-drawer",
			style: { marginTop: "10px" },
			children: shownPanels.length ? panels : /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: t("play.nothingToShow")
			})
		}) : null
	] });
	const asideRegionTabs = buildTabs(v.scenes ?? [], v.panels ?? []).filter((tb) => tb.kind === "region");
	const asideUntagged = (v.panels ?? []).filter((p) => !(p.region ?? "").trim());
	const asideStripTabs = [...asideRegionTabs, ...asideUntagged.length ? [{
		id: "__untagged",
		kind: "region",
		label: t("tab.system"),
		sceneIds: []
	}] : []];
	const activeAside = asideStripTabs.some((tb) => tb.id === asideTab) ? asideTab : asideStripTabs[0]?.id ?? "";
	const asidePanels = activeAside === "__untagged" ? asideUntagged : (v.panels ?? []).filter((p) => (p.region ?? "").trim() === activeAside);
	const asideSig = (regionId) => {
		const group = regionId === "__untagged" ? asideUntagged : (v.panels ?? []).filter((p) => (p.region ?? "").trim() === regionId);
		return JSON.stringify(group.map((p) => [p.id, JSON.stringify(p.fields)]));
	};
	const asideDots = {};
	for (const tb of asideStripTabs) {
		const sig = asideSig(tb.id);
		if (tb.id === activeAside) {
			asideSeenRef.current[tb.id] = sig;
			asideDots[tb.id] = false;
			continue;
		}
		if (asideSeenRef.current[tb.id] === void 0) asideSeenRef.current[tb.id] = sig;
		asideDots[tb.id] = asideSeenRef.current[tb.id] !== sig;
	}
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-play-root",
		children: [
			starOpen ? /* @__PURE__ */ jsx(StarMap, {
				runId,
				lang: v.language,
				backdrop: v.backdrop ?? null,
				onClose: () => {
					setStarOpen(false);
					onStarClose?.();
				},
				onJumpTurn: (turn) => {
					setStarOpen(false);
					setViewTurn(turn >= latest ? null : turn);
				}
			}) : null,
			readerBar ? /* @__PURE__ */ jsx("div", { className: "ew-topbar-slot" }) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ew-topbar" + (readerBar ? " ew-topbar-fixed" : "") + (readerBar && barHidden ? " ew-topbar-hidden" : ""),
				children: [/* @__PURE__ */ jsx("button", {
					className: "ew-back",
					type: "button",
					onClick: onBack,
					children: t("play.back")
				}), pager]
			}),
			error ? /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				role: "status",
				children: t("play.pollHiccup")
			}) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ew-titleline",
				children: [/* @__PURE__ */ jsx("h3", {
					className: "ew-detail-title",
					children: v.title
				}), v.clock ? /* @__PURE__ */ jsx("span", {
					className: "ew-clock",
					children: v.clock
				}) : null]
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ew-play",
				children: [main, !narrow ? /* @__PURE__ */ jsxs("div", {
					className: "ew-aside",
					children: [/* @__PURE__ */ jsxs("div", {
						className: "ew-aside-tabs",
						children: [asideStripTabs.map((tb) => /* @__PURE__ */ jsxs("button", {
							type: "button",
							className: "ew-aside-tab" + (tb.id === activeAside ? " on" : ""),
							"aria-pressed": tb.id === activeAside,
							onClick: () => setAsideTab(tb.id),
							children: [
								tabIcon(tb.id === "__untagged" ? "system" : tb.id),
								/* @__PURE__ */ jsx("span", { children: tb.label }),
								asideDots[tb.id] ? /* @__PURE__ */ jsx("i", { className: "ew-aside-dot" }) : null
							]
						}, tb.id)), /* @__PURE__ */ jsxs("button", {
							type: "button",
							className: "ew-aside-tab",
							onClick: () => setStarOpen(true),
							children: [tabIcon("starmap"), /* @__PURE__ */ jsx("span", { children: mt(v.language, "star.title") })]
						})]
					}), asidePanels.length ? /* @__PURE__ */ jsx(Fragment, { children: asidePanels.map((p) => /* @__PURE__ */ jsx(PanelBox, { panel: p }, p.id)) }) : /* @__PURE__ */ jsx("div", {
						className: "ew-note",
						children: t("play.nothingToShow")
					})]
				}) : null]
			})
		]
	});
}
//#endregion
//#region src/rail.tsx
/** The desktop navigator: worlds and lives, one click away.
*
* Why a rail and not a wider column. The shelf, a world's detail, the opening
* screen and the live turn were all one centred column, which is right on a phone
* and wasteful on a desktop — not because 900px is too narrow to read (it is about
* right for prose), but because *navigation* was sharing the reading axis. Opening
* a world replaced the shelf, so switching between two lives meant going back to
* a list, and the list itself was the same width as the story.
*
* Why it is now a drawer rather than a permanent column. A permanent 248px of names
* beside a story is navigation charging rent on every page: it is read once when you
* switch lives and ignored for the hours in between. So it opens from the same
* top-left slot the phone puts "back to the shelf" in, closes on the first thing you
* pick, and the reading column keeps the whole width the rest of the time.
*
* It opens IN FLOW, pushing the story right, and is never a viewport-fixed overlay.
* That is not a style preference: this app is mounted inside the dashboard's own
* content region, which is itself offset right by the dashboard's sidebar, so a
* panel positioned at `left: 0` of the VIEWPORT lands outside the area the app can
* be seen in — drawn, but somewhere the reader cannot look.
*
* It never shows prose and never grows.
*
* Below the desktop breakpoint this component renders NOTHING and the shelf works
* exactly as it did: a phone has no room for a rail of any kind, and the existing
* narrow layout was not a compromise to be undone but the baseline to build on.
*/
/** The same fact as the shelf's row, in the same words.
*
* Reusing `life.*` rather than adding `rail.*` twins is deliberate: the rail and
* the shelf describe the same life, and two phrasings of one state is how a UI
* starts reading as two different apps. */
function lifeWhere(run) {
	if (run.unreadable) return t("life.unreadable");
	if (run.generating) return t("life.generating");
	if (run.ended) return t("life.ended");
	if (run.awaitingOpening) return t("life.unborn");
	return t("life.turn", { turn: run.turn });
}
function WorldRail({ worlds, runs, activeRunId, activeWorldId, onWorld, onLife, onHome, atShelf, open, onClose, width, onWidth }) {
	useEffect(() => {
		if (!open) return;
		const onKey = (e) => {
			if (e.key === "Escape") onClose();
		};
		window.addEventListener("keydown", onKey);
		return () => {
			window.removeEventListener("keydown", onKey);
		};
	}, [open, onClose]);
	if (!open) return null;
	const playable = (worlds ?? []).filter((w) => w.usable);
	const broken = (worlds ?? []).length - playable.length;
	const shown = runs.filter((r) => !r.archived);
	return /* @__PURE__ */ jsxs("nav", {
		className: "ew-rail",
		"aria-label": t("rail.label"),
		children: [
			/* @__PURE__ */ jsxs("div", {
				className: "ew-rail-top",
				children: [atShelf ? /* @__PURE__ */ jsx("span", {}) : /* @__PURE__ */ jsx("button", {
					className: "ew-rail-home",
					type: "button",
					onClick: onHome,
					children: t("rail.shelf")
				}), /* @__PURE__ */ jsx("button", {
					className: "ew-rail-x",
					type: "button",
					onClick: onClose,
					children: t("rail.close")
				})]
			}),
			shown.length ? /* @__PURE__ */ jsxs("div", {
				className: "ew-rail-group",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-rail-head",
					children: t("library.lives")
				}), shown.map((r) => /* @__PURE__ */ jsxs("button", {
					type: "button",
					disabled: !!r.unreadable,
					className: "ew-rail-row" + (r.runId === activeRunId ? " ew-rail-row-on" : ""),
					onClick: () => onLife(r.runId),
					"aria-current": r.runId === activeRunId ? "page" : void 0,
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-rail-name",
						children: r.label || r.subtitle || r.title || r.worldId
					}), /* @__PURE__ */ jsx("span", {
						className: "ew-rail-sub",
						children: lifeWhere(r)
					})]
				}, r.runId))]
			}) : null,
			/* @__PURE__ */ jsxs("div", {
				className: "ew-rail-group",
				children: [
					/* @__PURE__ */ jsx("div", {
						className: "ew-rail-head",
						children: t("rail.worlds")
					}),
					playable.map((w) => /* @__PURE__ */ jsxs("button", {
						type: "button",
						className: "ew-rail-row" + (w.worldId === activeWorldId && !activeRunId ? " ew-rail-row-on" : ""),
						onClick: () => onWorld(w.worldId),
						"aria-current": w.worldId === activeWorldId ? "page" : void 0,
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-rail-name",
							children: w.title
						}), /* @__PURE__ */ jsx("span", {
							className: "ew-rail-sub",
							children: t("rail.styles", { n: w.styles?.length ?? 0 })
						})]
					}, w.worldId)),
					broken > 0 ? /* @__PURE__ */ jsx("div", {
						className: "ew-rail-note",
						children: t("rail.broken", { n: broken })
					}) : null
				]
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ew-rail-group",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-rail-head",
					children: t("rail.width")
				}), /* @__PURE__ */ jsxs("select", {
					className: "ew-uilang ew-rail-width",
					"aria-label": t("rail.width"),
					value: width,
					onChange: (e) => onWidth(e.target.value === "fixed" ? "fixed" : "fluid"),
					children: [/* @__PURE__ */ jsx("option", {
						value: "fluid",
						children: t("rail.width.fluid")
					}), /* @__PURE__ */ jsx("option", {
						value: "fixed",
						children: t("rail.width.fixed")
					})]
				})]
			})
		]
	});
}
//#endregion
//#region src/scene.tsx
/** The band the frame is allowed to occupy, in px. Below the floor a one-line
*  ledger reads as a rendering failure; above the ceiling a runaway spec would
*  push the rest of the page out of reach. Between them the frame is exactly as
*  tall as its picture — no dead band under a short scene, and no map with its
*  last row clipped off by a frame that was one fixed height for every spec. */
var MIN_SCENE_H = 96;
var MAX_SCENE_H = 1400;
/** How long a frame may take to report its height before the slot calls it failed.
*  Generous on purpose: the document is a local request and reports on load, so
*  seconds of headroom cover a cold instance without ever making a working scene
*  flash an error. Too short shows a false failure; too long restores the silent
*  blank frame this exists to prevent. */
var SCENE_RENDER_DEADLINE_MS = 6e3;
/** A short, stable token that changes only when the scene's compiled HTML does, so
*  the iframe `src` reloads on a real content change but NOT on a tab switch or
*  re-render (which would otherwise reload and lose what the player was looking at). */
function sceneVersion(html) {
	let h = 5381;
	for (let i = 0; i < html.length; i++) h = (h << 5) + h + html.charCodeAt(i) | 0;
	return (h >>> 0).toString(36);
}
/**
* The frame a scene is drawn in.
*
* Created on FIRST need and kept for the rest of the session. "Never moved once it
* exists" is the invariant that protects a mounted scene from reloading — moving an
* iframe in the DOM reloads it, and a React portal does not help because the
* browser's rule is about position in the document, not about who rendered it.
*
* It never required the element to exist before any scene had been asked for, and
* mounting it unconditionally put a live browsing context with allow-scripts into
* the dashboard's own document for every player, including the majority who never
* see a scene at all.
*/
function SceneSlot({ runId, sceneId, asks, visible = true, onChoice, resetSignal = 0, locked = false }) {
	const [everNeeded, setEverNeeded] = useState(false);
	const [html, setHtml] = useState("");
	const [failed, setFailed] = useState(false);
	/** Set the instant the player acts, cleared when the scene changes — so a scene
	*  tap has immediate feedback instead of looking dead for the seconds a turn
	*  takes. (M0.4) */
	const [sending, setSending] = useState(false);
	/** The frame's own reported content height, clamped. 0 until the first report,
	*  where the stylesheet's fallback height stands in. A later scene keeps the
	*  previous height until its own report lands, so a page turn resizes once
	*  instead of collapsing to the fallback and growing back. */
	const [fitH, setFitH] = useState(0);
	const wrapRef = useRef(null);
	useEffect(() => {
		if (sceneId) setEverNeeded(true);
	}, [sceneId]);
	useEffect(() => {
		if (!runId || !sceneId) {
			setHtml("");
			setFailed(false);
			return;
		}
		let alive = true;
		api.scene(runId, sceneId).then((text) => {
			if (alive) {
				setHtml(text);
				setFailed(false);
			}
		}).catch(() => {
			if (alive) {
				setHtml("");
				setFailed(true);
			}
		});
		return () => {
			alive = false;
		};
	}, [runId, sceneId]);
	const answered = useRef(false);
	useEffect(() => {
		answered.current = false;
		setSending(false);
	}, [
		sceneId,
		html,
		resetSignal
	]);
	const lockedRef = useRef(locked);
	lockedRef.current = locked;
	useEffect(() => {
		if (html && sceneId && asks) wrapRef.current?.scrollIntoView({
			block: "nearest",
			behavior: "smooth"
		});
	}, [
		html,
		sceneId,
		asks
	]);
	useEffect(() => {
		if (!everNeeded) return void 0;
		const onMessage = (e) => {
			if (e.origin !== "null") return;
			const d = e.data;
			if (!d || d.source !== "endless-scene") return;
			if (d.sceneId !== sceneId) return;
			if (typeof d.nonce !== "string" || !d.nonce) return;
			if (typeof d.height === "number" && Number.isFinite(d.height)) {
				setFitH(Math.min(MAX_SCENE_H, Math.max(MIN_SCENE_H, Math.round(d.height))));
				return;
			}
			if (typeof d.choice !== "string" || !d.choice) return;
			if (answered.current) return;
			if (lockedRef.current) return;
			answered.current = true;
			setSending(true);
			onChoice(sceneId, d.choice, d.nonce);
		};
		window.addEventListener("message", onMessage);
		return () => window.removeEventListener("message", onMessage);
	}, [
		sceneId,
		onChoice,
		everNeeded
	]);
	const on = !!(html && sceneId);
	const loading = !!sceneId && !html && !failed;
	const src = on && runId ? `${API}/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}?v=${sceneVersion(html)}` : void 0;
	useEffect(() => {
		if (!src || fitH) return void 0;
		const timer = setTimeout(() => setFailed(true), SCENE_RENDER_DEADLINE_MS);
		return () => clearTimeout(timer);
	}, [src, fitH]);
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-slot-wrap",
		ref: wrapRef,
		style: !visible ? { display: "none" } : on ? void 0 : { margin: 0 },
		children: [
			failed && sceneId ? /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: t("play.sceneFailed")
			}) : null,
			loading ? /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				role: "status",
				"aria-live": "polite",
				children: t("play.sceneLoading")
			}) : null,
			sending ? /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				role: "status",
				"aria-live": "polite",
				children: t("play.sceneSending")
			}) : null,
			everNeeded ? /* @__PURE__ */ jsx("iframe", {
				title: t("play.sceneTitle"),
				className: `ew-slot${on && !failed ? " ew-slot-on" : ""}`,
				style: failed ? { display: "none" } : on && fitH ? { height: `${fitH}px` } : void 0,
				sandbox: "allow-scripts allow-forms",
				src,
				allow: "",
				referrerPolicy: "no-referrer"
			}) : null
		]
	});
}
//#endregion
//#region src/settings.tsx
/**
* Narrator + painter settings, opened from the home page: which model writes the
* story, at what reasoning effort, and which model paints the backdrops. All apply
* to every life at its next turn.
*
* The model list comes from the gateway's advertised set (never a hardcoded id);
* an empty pick means "keep the app's default", so the app still runs on auto
* when the list is unavailable or the player has chosen nothing.
*/
function SettingsPanel({ onClose }) {
	const [model, setModel] = useState("");
	const [effort, setEffort] = useState("");
	const [painterModel, setPainterModel] = useState("");
	const [efforts, setEfforts] = useState([""]);
	const [models, setModels] = useState([]);
	const [saved, setSaved] = useState(false);
	const [busy, setBusy] = useState(false);
	useEffect(() => {
		let alive = true;
		api.settings().then((s) => {
			if (!alive) return;
			setModel(s.model && s.model !== "auto" ? s.model : "");
			setEffort(s.reasoningEffort || "");
			setPainterModel(s.painterModel && s.painterModel !== "auto" ? s.painterModel : "");
			if (Array.isArray(s.efforts) && s.efforts.length) setEfforts(s.efforts);
		}).catch(() => {});
		api.models().then((m) => {
			if (alive) setModels(m);
		}).catch(() => {});
		return () => {
			alive = false;
		};
	}, []);
	const save = async () => {
		setBusy(true);
		try {
			const out = await api.saveSettings({
				model,
				reasoningEffort: effort,
				painterModel
			});
			setModel(out.model || "");
			setEffort(out.reasoningEffort || "");
			setPainterModel(out.painterModel || "");
			setSaved(true);
		} finally {
			setBusy(false);
		}
	};
	const modelIds = models.map((m) => m.id).filter((id) => id && id !== "auto");
	const label = (id) => models.find((m) => m.id === id)?.name || id;
	const optionsFor = (current) => (current && current !== "auto" && !modelIds.includes(current) ? [current] : []).concat(modelIds);
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-settings ew-block",
		children: [
			/* @__PURE__ */ jsxs("div", {
				className: "ew-settings-head",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-section",
					children: t("settings.title")
				}), /* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-quiet",
					type: "button",
					onClick: onClose,
					children: t("settings.close")
				})]
			}),
			/* @__PURE__ */ jsxs("label", {
				className: "ew-settings-row",
				children: [/* @__PURE__ */ jsx("span", {
					className: "ew-settings-label",
					children: t("settings.model")
				}), /* @__PURE__ */ jsxs("select", {
					className: "ew-uilang ew-settings-select",
					value: model,
					onChange: (e) => {
						setModel(e.target.value);
						setSaved(false);
					},
					children: [/* @__PURE__ */ jsx("option", {
						value: "",
						children: t("settings.modelDefault")
					}), optionsFor(model).map((id) => /* @__PURE__ */ jsx("option", {
						value: id,
						children: label(id)
					}, id))]
				})]
			}),
			/* @__PURE__ */ jsxs("label", {
				className: "ew-settings-row",
				children: [/* @__PURE__ */ jsx("span", {
					className: "ew-settings-label",
					children: t("settings.painterModel")
				}), /* @__PURE__ */ jsxs("select", {
					className: "ew-uilang ew-settings-select",
					value: painterModel,
					onChange: (e) => {
						setPainterModel(e.target.value);
						setSaved(false);
					},
					children: [/* @__PURE__ */ jsx("option", {
						value: "",
						children: t("settings.modelDefault")
					}), optionsFor(painterModel).map((id) => /* @__PURE__ */ jsx("option", {
						value: id,
						children: label(id)
					}, id))]
				})]
			}),
			/* @__PURE__ */ jsxs("label", {
				className: "ew-settings-row",
				children: [/* @__PURE__ */ jsx("span", {
					className: "ew-settings-label",
					children: t("settings.effort")
				}), /* @__PURE__ */ jsx("select", {
					className: "ew-uilang ew-settings-select",
					value: effort,
					onChange: (e) => {
						setEffort(e.target.value);
						setSaved(false);
					},
					children: efforts.map((lvl) => /* @__PURE__ */ jsx("option", {
						value: lvl,
						children: lvl ? lvl : t("settings.effortDefault")
					}, lvl || "default"))
				})]
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ew-settings-foot",
				children: [/* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-go",
					type: "button",
					disabled: busy,
					onClick: () => void save(),
					children: t("settings.save")
				}), saved ? /* @__PURE__ */ jsx("span", {
					className: "ew-settings-saved",
					children: t("settings.saved")
				}) : null]
			}),
			/* @__PURE__ */ jsx("div", {
				className: "ew-hint",
				children: t("settings.note")
			})
		]
	});
}
//#endregion
//#region src/styles.css?raw
var styles_default = "/* This app mounts into the DASHBOARD's own document, not an iframe, so every rule\n   here is global. Hence the ew- prefix on every class and zero bare element\n   selectors — an unprefixed .card would repaint the whole dashboard.\n\n   Narrow-first: bare rules are the phone baseline, min-width adds the desktop. */\n\n.ew-root {\n  --ew-gutter: 16px;\n  width: 100%; box-sizing: border-box;\n  color: var(--text, #e2e8f0);\n  padding: var(--ew-gutter);\n  /* Scopes any future overlay to this panel instead of the whole dashboard. */\n  position: relative;\n}\n@media (min-width: 768px) {\n  /* Every app page owns the available canvas. A short workflow is not centred or\n     narrowed merely because it has less content; it begins at the top-left like\n     every other page. Reading measure is scoped separately to the live view. */\n  .ew-root { max-width: none; margin: 0; --ew-gutter: 24px; }\n}\n\n/* ── the desktop shelf drawer ──────────────────────────────────────────────\n   Above this width the shelf is reachable from every page without occupying one.\n   Below it neither the drawer nor its opener is rendered and the shelf behaves\n   exactly as it always has — the narrow layout is the baseline, not a compromise\n   being undone.\n\n   1100px, not 768: below it the centred column is already the best use of the\n   space, and a drawer that leaves a readable measure needs the room.\n\n   It opens IN FLOW and pushes the story right. NOT `position: fixed`: this app is\n   mounted inside the dashboard's own content region, which is offset right by the\n   dashboard's sidebar, so a panel pinned to `left: 0` of the VIEWPORT is painted\n   outside the area the app is visible in — it renders and the reader cannot see it.\n   A grid column has no such problem because it is positioned by the app's own box. */\n.ew-rail { display: none; }\n.ew-rail-top {\n  display: flex; align-items: center; justify-content: space-between; gap: 10px;\n  margin-bottom: 10px;\n}\n.ew-rail-x {\n  background: transparent; border: none; cursor: pointer;\n  color: var(--muted, #6b7280); font: inherit; font-size: 13px;\n  min-height: 36px; padding: 0 2px;\n}\n.ew-rail-width { width: 100%; }\n/* The opener. Hidden at phone widths, where the inline \"back to the shelf\" is the\n   corner's one control; sized like that button so the corner does not shift as the\n   window crosses the breakpoint. */\n.ew-shelfbtn {\n  display: none;\n  align-items: center; min-height: 44px; padding: 0 12px 0 0;\n  background: transparent; border: none; cursor: pointer;\n  color: var(--accent, #7c3aed); font: inherit; font-size: 14px;\n}\n\n@media (min-width: 1100px) {\n  /* Fill the whole available space for immersion: the app spans the dashboard's\n     content region edge to edge, so the backdrop reaches the edges instead of\n     leaving black gutters beside a centred 1320px column. The reading measure is\n     NOT lifted here — it lives on `.ew-main` (74ch) below, so prose stays readable\n     while the background fills the room around it. This is the same full-width the\n     `.ew-w-fluid` reader preference already uses. */\n  .ew-root { max-width: none; }\n\n  /* One way back, not two. The drawer's own \"back to the shelf\" is the desktop's\n     route home, so the view's inline back button is a second control doing the same\n     thing. Scoped to `.ew-root .ew-back` (0,2,0) on purpose: the base `.ew-back`\n     rule is declared LATER in this file, so an equal-specificity\n     `.ew-back { display: none }` here would lose the cascade and the button would\n     stay visible — which is exactly the \"two back buttons\" bug this had. The inline\n     one is the mobile affordance and stays the only one below this width. */\n  .ew-root .ew-back { display: none; }\n\n  /* The lives, once. The rail lists every life by name, so repeating the life\n     rows in the reading column is the same information twice — hide them when the\n     rail is open. The WORLD covers stay: a name in the rail is not the cover tile,\n     and the landing's job is to invite you into a world, not just link to it. */\n  .ew-shell-open .ew-shelf-lives { display: none; }\n\n  /* Closed: one column, the story owns the width. Open: two, the story moves right\n     by exactly the drawer's own width and nothing is covered. */\n  .ew-shell-open {\n    display: grid;\n    grid-template-columns: 248px minmax(0, 1fr);\n    gap: 32px;\n    align-items: start;\n  }\n  .ew-shell-open .ew-rail {\n    display: block;\n    position: sticky;\n    /* Sticks under the app's own header rather than the viewport top, so the title\n       does not scroll away from the shelf it labels. */\n    top: var(--ew-gutter);\n    /* Its own scroll: a shelf with thirty lives must not push the story down. */\n    max-height: calc(100vh - 120px);\n    overflow-y: auto;\n    padding-right: 4px;\n  }\n  /* The opener is only for OPENING: when the shelf is already open the rail's own\n     close is the single closer, so hiding the opener removes the \"two buttons that\n     both close\" confusion. */\n  .ew-shelfbtn { display: inline-flex; }\n  .ew-shell-open .ew-shelfbtn { display: none; }\n\n  /* The measure. Prose is the reason this number exists — a life is read, not\n     scanned — so it is set in ch and does not grow with the window. It is the\n     DEFAULT, not the law: `.ew-w-fluid` below is the reader's own explicit\n     override and the only thing that lifts it. */\n  .ew-view-live .ew-main { max-width: 74ch; }\n  /* Only live prose honours the reader's measure preference. Workflow, detail and\n     shelf pages always fill their main track and begin at its top-left. */\n  .ew-view-live .ew-shell:not(.ew-shell-open) .ew-main { margin-inline: auto; }\n}\n\n/* ── the reading measure, as the reader set it ─────────────────────────────\n   `fixed` is the cap above. `fluid` gives the story the window, and is a stored\n   preference rather than a width the layout guessed at: the guard is against the\n   measure growing on its own, not against being told to. On the play page the\n   status aside keeps its 300px either way, so fluid widens the prose, not the\n   panels. Declared after the desktop block and one class more specific, so it wins\n   on specificity rather than on source order. */\n.ew-root.ew-w-fluid { max-width: none; }\n@media (min-width: 1100px) {\n  .ew-root.ew-view-live.ew-w-fluid .ew-main { max-width: none; }\n}\n\n.ew-rail-home {\n  display: block; width: 100%; text-align: left;\n  min-height: 36px; margin-bottom: 14px; padding: 0;\n  background: transparent; border: none; cursor: pointer;\n  color: var(--accent, #7c3aed); font: inherit; font-size: 13px;\n}\n/* In the drawer's top row it shares the line with the close control, so it gives up\n   the full-width block box it needs when it is the only thing there. */\n.ew-rail-top .ew-rail-home { width: auto; margin-bottom: 0; }\n\n.ew-rail-group { margin-bottom: 18px; }\n.ew-rail-head {\n  font-size: 11px; font-weight: 600; letter-spacing: 0.04em;\n  text-transform: uppercase;\n  color: var(--muted, #6b7280);\n  margin-bottom: 6px;\n}\n\n.ew-rail-row {\n  display: block; width: 100%; text-align: left; cursor: pointer;\n  background: transparent;\n  border: none; border-left: 2px solid transparent;\n  border-radius: 0 6px 6px 0;\n  padding: 7px 8px; margin-bottom: 1px;\n  color: inherit; font: inherit;\n}\n@media (hover: hover) { .ew-rail-row:hover { background: var(--card, #1f2030); } }\n.ew-rail-row:disabled { cursor: default; opacity: 0.45; }\n.ew-rail-row-on {\n  border-left-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 10%, transparent);\n}\n\n.ew-rail-name {\n  display: block; font-size: 13px; line-height: 1.35;\n  /* A world title is user content: one long unbroken run must not widen the\n     grid column, which would push the reading measure sideways. */\n  overflow-wrap: anywhere;\n}\n.ew-rail-sub {\n  display: block; font-size: 11px; color: var(--muted, #6b7280); margin-top: 2px;\n}\n/* Only where the rail is: below it, the shelf list IS the page and this landing\n   would be a second copy of what the list already says. */\n.ew-onlywide { display: none; }\n@media (min-width: 1100px) { .ew-onlywide { display: block; } }\n\n/* ── reading back ── */\n.ew-history { margin-top: 14px; }\n.ew-past { position: relative; overflow: hidden; padding: 6px 10px; margin-bottom: 18px; border-bottom: 1px solid var(--border, #2d2f3d); border-radius: 8px; }\n/* Each re-read page keeps the scene it had: its backdrop sits faint behind the\n   prose, and the content is lifted above it so it stays readable. */\n.ew-past-bg {\n  position: absolute; inset: 0; width: 100%; height: 100%;\n  object-fit: cover; opacity: .16; pointer-events: none; z-index: 0;\n}\n.ew-past-head, .ew-past .ew-prose, .ew-past .ew-marks { position: relative; z-index: 1; }\n.ew-past-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }\n.ew-past-turn { font-size: 12px; color: var(--muted, #6b7280); letter-spacing: .04em; }\n.ew-past-action { font-size: 12px; color: var(--accent, #7c3aed); overflow-wrap: anywhere; }\n\n.ew-rail-note {\n  font-size: 11px; color: var(--muted, #6b7280); padding: 6px 8px; line-height: 1.6;\n}\n\n.ew-head { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }\n.ew-head h2 { margin: 0; font-size: 17px; font-weight: 600; }\n@media (min-width: 768px) { .ew-head h2 { font-size: 19px; } }\n/* Interface-language dropdown: pushed to the far right of the title bar. */\n.ew-uilang {\n  margin-left: 0; min-height: 30px; padding: 0 8px; font-size: 13px;\n  color: var(--text, #e2e8f0); background: transparent;\n  border: 1px solid var(--border, #334155); border-radius: 8px; cursor: pointer;\n}\n/* The header's right-hand controls (language, settings), grouped and pushed right. */\n.ew-headtools { margin-left: auto; display: flex; gap: 8px; align-items: center; }\n/* Narrator settings panel on the home page. */\n.ew-settings {\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  background: var(--card, #1f2030); padding: 14px; margin-bottom: 16px;\n}\n.ew-settings-head { display: flex; align-items: center; justify-content: space-between; }\n.ew-settings-row { display: flex; align-items: center; gap: 12px; margin: 10px 0; }\n.ew-settings-label { flex: 0 0 8em; color: var(--muted, #6b7280); font-size: 13px; }\n.ew-settings-select { flex: 1; min-width: 0; }\n.ew-settings-foot { display: flex; align-items: center; gap: 12px; margin-top: 6px; }\n.ew-settings-saved { font-size: 12px; color: var(--accent, #7c3aed); }\n/* The shared .ew-hint carries a negative top margin tuned for its other call\n * sites; inside the settings panel it directly follows the 44px Save button row,\n * where that negative margin pulls the note up ONTO the button. Reset it here. */\n.ew-settings .ew-hint { margin-top: 8px; }\n\n/* A world name is user content and can be one long unbroken run; without this a\n   phone gets a horizontal scrollbar on the whole page. */\n.ew-title, .ew-detail-title { overflow-wrap: anywhere; }\n\n.ew-card {\n  display: block; width: 100%; text-align: left; cursor: pointer;\n  background: var(--card, #1f2030);\n  border: 1px solid var(--border, #2d2f3d);\n  border-radius: 10px;\n  padding: 12px; margin-bottom: 10px;\n  color: inherit; font: inherit;\n  -webkit-tap-highlight-color: transparent;\n  /* Scope the life backdrop to the card. The CLIP is not here: `overflow: hidden`\n     rounded the backdrop but also cut off the row's action menu, which opens below\n     the kebab and is taller than the card. `.ew-card-bgclip` clips the backdrop\n     instead, so the menu is free to leave the card. */\n  position: relative;\n}\n/* The life's narrator backdrop behind the card, framed to the card (unlike the\n * full-page .ew-backdrop). A scrim over it keeps the title/meta readable; inert\n * image so it runs no script and needs no sandbox. */\n/* The backdrop's own clipping box: inset to the card's padding box and rounded a\n   hair tighter than the card's 10px, which is what the 1px border leaves inside. */\n.ew-card-bgclip {\n  position: absolute; inset: 0; z-index: 0;\n  border-radius: 9px; overflow: hidden; pointer-events: none;\n}\n.ew-card-bg {\n  position: absolute; inset: 0;\n  width: 100%; height: 100%; object-fit: cover;\n  opacity: .5; pointer-events: none;\n}\n.ew-card-bg-scrim {\n  position: absolute; inset: 0; pointer-events: none;\n  background: linear-gradient(\n    180deg,\n    color-mix(in srgb, var(--card, #1f2030) 45%, transparent),\n    color-mix(in srgb, var(--card, #1f2030) 72%, transparent)\n  );\n}\n/* Lift the card's real content above the backdrop box. Deliberately NOT a z-index\n   here: `z-index: 1` on these wrappers created a stacking context, and the row's\n   action menu (z-index 30) was trapped inside it — no value could raise it above the\n   phone's bottom bars, which is why it appeared UNDER other UI. `position: relative`\n   alone paints them after the backdrop box, which is all the lift they needed. */\n.ew-card > .ew-card-bgclip ~ * { position: relative; }\n@media (min-width: 768px) { .ew-card { padding: 14px; } }\n/* Press feedback belongs to the control that was pressed, not to its ancestors.\n   `:active` matches every ancestor of the pressed element, so a card-level rule made\n   a tap on the kebab flash the whole row as though it had been opened. These two are\n   the only things whose press means \"open this\": a world card IS the button, and a\n   life row carries its own open button (a button inside a button is invalid HTML).\n   Neither can be triggered by the kebab, and neither depends on `:has()`. */\nbutton.ew-card:active { border-color: var(--accent, #7c3aed); }\n.ew-card-open:active {\n  background: color-mix(in oklab, var(--accent, #7c3aed) 14%, transparent);\n  border-radius: 8px;\n}\n.ew-card-broken { cursor: default; border-left: 3px solid var(--danger, #b91c1c); }\n\n.ew-title { font-size: 15px; font-weight: 600; line-height: 1.35; }\n@media (min-width: 768px) { .ew-title { font-size: 16px; } }\n\n.ew-titlerow {\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;\n}\n.ew-chips { display: flex; gap: 6px; flex-wrap: wrap; }\n\n.ew-chip {\n  border-radius: 9999px; padding: 2px 9px; font-size: 11px;\n  border: 1px solid var(--border, #2d2f3d);\n  color: var(--muted, #6b7280);\n  /* A chip's text can come from the world or the narrator, so it is not safe to\n     assume it is short. Wrap/break a long one instead of letting `nowrap` force a\n     page-wide horizontal scroll on a phone. */\n  white-space: normal; overflow-wrap: anywhere; max-width: 100%;\n}\n.ew-chip-accent {\n  border-color: transparent;\n  background: color-mix(in oklab, var(--accent, #7c3aed) 16%, transparent);\n  color: var(--accent, #7c3aed);\n}\n\n.ew-meta { font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7; }\n\n/* A world card is an invitation to imagine a life, not a package manifest. The\n   promise leads; concrete possibilities make it credible; implementation counts\n   stay one tap away on the detail page. */\n.ew-world-card { overflow: hidden; }\n.ew-world-promise {\n  margin: 2px 0 12px;\n  font-size: 14px; line-height: 1.65;\n  color: var(--text, #e2e8f0);\n}\n.ew-world-possibilities {\n  margin: 0 0 14px; padding: 10px 12px;\n  border-left: 2px solid color-mix(in oklab, var(--accent, #7c3aed) 48%, transparent);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 7%, transparent);\n}\n.ew-world-possibilities-label {\n  margin-bottom: 5px; font-size: 11px; font-weight: 600;\n  letter-spacing: .04em; color: var(--accent, #7c3aed);\n}\n.ew-world-possibility {\n  position: relative; padding-left: 12px;\n  font-size: 12px; line-height: 1.65;\n  color: var(--muted, #94a3b8);\n}\n.ew-world-possibility::before { content: '·'; position: absolute; left: 1px; }\n.ew-world-card-footer {\n  display: flex; align-items: baseline; justify-content: space-between;\n  gap: 12px; margin-top: 12px; padding-top: 10px;\n  border-top: 1px solid var(--border, #2d2f3d);\n}\n.ew-world-enter {\n  flex: none; font-size: 12px; font-weight: 600;\n  color: var(--accent, #7c3aed);\n}\n\n/* ── the landing: a living bookshelf ─────────────────────────────────────\n   The play page became rich (full backdrop, translucent cards); the shelf was a\n   flat list by comparison. These give the landing its own ambient night sky, a\n   tagline, a prominent \"continue\" hero, life rows with a gilt spine, and worlds\n   as book covers — so the shelf reads as part of the same world. */\n/* The ambient fills the whole screen, not the content box. It was painted on\n   `.ew-root`, which is width-capped and only as tall as its content, so on desktop\n   the night sky covered a centred column and left the rest black. A fixed\n   full-viewport layer behind the content (z-index 0; content is z-index 1) fills\n   the screen at any column width or content height. */\n.ew-home::before {\n  content: ''; position: fixed; inset: 0; z-index: 0; pointer-events: none;\n  background:\n    radial-gradient(circle at 8px 8px, rgba(230, 217, 168, .16) 1px, transparent 1.7px) 0 0 / 48px 48px,\n    radial-gradient(55% 40% at 50% 4%, color-mix(in srgb, var(--accent, #d9b45a) 12%, transparent), transparent 62%),\n    radial-gradient(130% 95% at 50% 0%, #1b1832 0%, #131120 48%, #0a0912 100%);\n}\n.ew-tagline {\n  color: var(--muted, #9c96a8); font-size: 13px; line-height: 1.6; margin: 4px 2px 18px;\n}\n\n/* The version footer at the bottom of the shelf: quiet, centered, out of the way. */\n.ew-version {\n  color: var(--muted, #9c96a8); opacity: .55; font-size: 11px;\n  text-align: center; letter-spacing: .04em; padding: 20px 0 10px;\n}\n\n/* Continue: the most recent life, made a gold hero rather than one row among many.\n   Styles the LifeRow card inside the wrapper, so LifeRow itself stays generic. */\n.ew-cont-wrap .ew-card {\n  border-color: color-mix(in oklab, var(--accent, #d9b45a) 36%, var(--border, #2d2f3d));\n  background:\n    linear-gradient(180deg,\n      color-mix(in srgb, var(--accent, #d9b45a) 16%, transparent),\n      color-mix(in srgb, var(--accent, #d9b45a) 4%, transparent)),\n    var(--card, #1f2030);\n  box-shadow: 0 6px 22px rgba(0, 0, 0, .28);\n}\n\n/* Life rows read as books on a shelf: a thin gilt spine down the left edge. */\n.ew-card-row {\n  box-shadow: inset 3px 0 0 color-mix(in oklab, var(--accent, #d9b45a) 55%, transparent);\n}\n\n/* World card = a book cover: a decorative band carries the title; the body holds\n   the promise, style chips, and the play-count + enter. */\n.ew-world-card { padding: 0; }\n.ew-world-band {\n  display: flex; align-items: flex-end; flex-wrap: wrap; gap: 8px;\n  min-height: 96px; padding: 14px 16px;\n  background:\n    repeating-linear-gradient(135deg,\n      color-mix(in srgb, var(--accent, #d9b45a) 9%, transparent) 0 2px, transparent 2px 12px),\n    radial-gradient(120% 160% at 18% 0%, #3a2d63, #1a1430);\n  border-bottom: 1px solid var(--border, #2d2f3d);\n}\n.ew-world-band-title {\n  font-size: 19px; font-weight: 700; color: #f1ecdf; text-shadow: 0 2px 8px rgba(0, 0, 0, .5);\n}\n.ew-world-body { padding: 14px 16px; }\n/* The possibilities become style chips (was an accent-bordered bullet list). */\n.ew-world-possibilities {\n  display: flex; flex-wrap: wrap; gap: 6px;\n  margin: 12px 0 0; padding: 0; border: 0; background: none;\n}\n.ew-world-possibility {\n  position: static; padding: 3px 9px; font-size: 11px; color: var(--muted, #9c96a8);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 999px;\n  background: color-mix(in srgb, var(--card, #1f2030) 50%, transparent);\n}\n.ew-world-possibility::before { content: none; }\n\n/* ── creating a world from pasted text ─────────────────────────────────────\n   The entry sits atop the worlds shelf; a draft being compiled reads as a book\n   being written (the same gilt spine as a life); the paste and review screens are\n   transient forms, like the opening. */\n.ew-card-create {\n  display: flex; align-items: center; gap: 12px;\n  border: 1px dashed color-mix(in srgb, var(--accent, #d9b45a) 45%, var(--border, #2d2f3d));\n  background: linear-gradient(\n    180deg, color-mix(in srgb, var(--accent, #d9b45a) 6%, transparent), transparent\n  );\n  text-align: left; -webkit-tap-highlight-color: transparent;\n}\n.ew-create-plus {\n  width: 38px; height: 38px; flex: none; border-radius: 9px;\n  display: inline-flex; align-items: center; justify-content: center;\n  font-size: 22px; line-height: 1; color: var(--accent, #d9b45a);\n  border: 1px solid color-mix(in srgb, var(--accent, #d9b45a) 55%, var(--border, #2d2f3d));\n}\n.ew-create-text { display: flex; flex-direction: column; gap: 2px; }\n.ew-create-title { font-size: 15px; font-weight: 600; color: var(--text, #e2e8f0); }\n.ew-create-sub { font-size: 12.5px; color: var(--muted, #9c96a8); }\n\n.ew-card-draft {\n  box-shadow: inset 3px 0 0 color-mix(in oklab, var(--accent, #d9b45a) 55%, transparent);\n}\n.ew-card-draft-ready { box-shadow: inset 3px 0 0 var(--accent, #d9b45a); }\n.ew-card-draft-failed { box-shadow: inset 3px 0 0 color-mix(in oklab, #d9534f 60%, transparent); }\n\n.ew-progress { margin-top: 10px; }\n.ew-progress-track {\n  height: 5px; border-radius: 3px; overflow: hidden;\n  background: color-mix(in srgb, var(--border, #2d2f3d) 80%, transparent);\n}\n.ew-progress-fill {\n  height: 100%; border-radius: 3px; transition: width .4s ease;\n  background: linear-gradient(\n    90deg, var(--accent, #d9b45a), color-mix(in srgb, var(--accent, #d9b45a) 55%, #000)\n  );\n}\n\n.ew-create { max-width: none; }\n.ew-create-ta {\n  width: 100%; min-height: 320px; resize: vertical; box-sizing: border-box;\n  background: color-mix(in srgb, var(--card, #1f2030) 85%, #000);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  color: var(--text, #e2e8f0); font: inherit; font-size: 14px; line-height: 1.7;\n  padding: 14px; -webkit-tap-highlight-color: transparent;\n}\n.ew-create-hint {\n  font-size: 12.5px; color: var(--muted, #9c96a8); line-height: 1.6; margin: 8px 2px 0;\n}\n.ew-create-count { margin-left: auto; align-self: center; font-size: 12px; color: var(--muted, #9c96a8); }\n.ew-create-titlelabel { display: block; font-size: 12px; color: var(--muted, #9c96a8); margin: 2px 0 6px; }\n.ew-title-edit {\n  width: 100%; box-sizing: border-box;\n  background: color-mix(in srgb, var(--card, #1f2030) 85%, #000);\n  border: 1px solid color-mix(in srgb, var(--accent, #d9b45a) 40%, var(--border, #2d2f3d));\n  border-radius: 8px; color: #f1ecdf; font-size: 17px; font-weight: 700; padding: 9px 11px;\n}\n.ew-review { margin-top: 14px; }\n.ew-kv {\n  display: flex; gap: 10px; font-size: 13.5px; padding: 8px 0; line-height: 1.6;\n  border-bottom: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 60%, transparent);\n}\n.ew-kv:last-child { border-bottom: 0; }\n.ew-kv .ew-k { color: var(--muted, #9c96a8); width: 56px; flex: none; }\n.ew-review-warn {\n  margin-top: 14px; padding: 10px 12px; border-radius: 8px;\n  background: color-mix(in srgb, var(--accent, #d9b45a) 8%, transparent);\n  border: 1px solid color-mix(in srgb, var(--accent, #d9b45a) 28%, var(--border, #2d2f3d));\n}\n.ew-review-warn-h {\n  font-size: 12px; font-weight: 600; margin-bottom: 6px;\n  color: color-mix(in srgb, var(--accent, #d9b45a) 80%, var(--text, #e2e8f0));\n}\n.ew-draft-jump {\n  display: block; width: 100%; margin-top: 14px; padding: 11px;\n  border: 1px solid color-mix(in srgb, var(--accent, #d9b45a) 40%, var(--border, #2d2f3d));\n  border-radius: 9px; background: color-mix(in srgb, var(--accent, #d9b45a) 5%, transparent);\n  color: var(--accent, #d9b45a); font: inherit; font-size: 13.5px; font-weight: 600;\n  cursor: pointer; -webkit-tap-highlight-color: transparent;\n}\n.ew-review-accept { flex: 1; }\n\n/* 44px is the smallest reliably tappable target; a 13px text link with 4px of\n   padding is about 21px, which is a miss on a phone even when it looks fine on a\n   desktop mock. */\n.ew-back {\n  display: inline-flex; align-items: center;\n  min-height: 44px; padding: 0 12px 0 0;\n  background: transparent; border: none; cursor: pointer;\n  color: var(--accent, #7c3aed); font: inherit; font-size: 14px;\n  -webkit-tap-highlight-color: transparent;\n}\n\n.ew-detail-title { margin: 0 0 4px; font-size: 19px; line-height: 1.3; }\n@media (min-width: 768px) { .ew-detail-title { font-size: 22px; } }\n\n.ew-section { font-size: 13px; font-weight: 600; margin: 0 0 7px; }\n/* A heading with one control on its right. The heading keeps its own margin, so\n   the row does not add another and shift every list below it. */\n.ew-section-row {\n  display: flex; align-items: baseline; justify-content: space-between; gap: 12px;\n}\n/* Names the order it would switch TO, so it needs no separate label. Quiet by\n   default because it is a preference, not an action the page is asking for. */\n.ew-order-toggle {\n  margin: 0 0 7px; padding: 0; background: transparent; border: 0; cursor: pointer;\n  font: inherit; font-size: 12px; color: var(--muted, #6b7280);\n  letter-spacing: .02em; white-space: nowrap;\n}\n.ew-order-toggle:hover { color: var(--text, #e2e8f0); }\n.ew-order-toggle:focus-visible {\n  outline: 2px solid var(--accent, #7c3aed); outline-offset: 2px; border-radius: 4px;\n}\n.ew-block { margin-bottom: 18px; }\n/* A small explanatory caption under a block, e.g. what the accented chips mean. */\n.ew-hint { font-size: 12px; color: var(--muted, #6b7280); line-height: 1.6; margin-top: -10px; }\n\n.ew-panel {\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px; margin-bottom: 8px;\n}\n@media (min-width: 768px) { .ew-panel { padding: 10px 12px; } }\n.ew-panel-head {\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 7px;\n}\n.ew-panel-name { font-size: 13px; font-weight: 600; }\n\n.ew-note {\n  font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; margin-top: 10px;\n}\n/* A note that carries an action. The button keeps its own size, so a long sentence\n   wraps instead of squeezing the thing the player is meant to press. */\n.ew-note-row {\n  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;\n  justify-content: space-between;\n}\n\n/* ── the second ask ──\n   Absolute inside the app's own box, NOT fixed — the same rule the scene slot\n   follows and for a sharper reason here: a fixed overlay would cover the\n   dashboard's own navigation, so a modal that failed to close would trap the\n   player in this app. Scoped to .ew-root, the worst case is an app they can\n   still navigate away from. */\n.ew-modal-wrap {\n  position: fixed; inset: 0; z-index: 40;\n  display: flex; align-items: flex-start; justify-content: center;\n  padding: 24px var(--ew-gutter, 8px);\n  background: color-mix(in oklab, var(--bg, #1a1b26) 72%, transparent);\n  /* Fixed to the viewport, not sized to the app box: on a scrolled phone an\n     absolute wrap put the panel at the top of a tall page — off-screen and unseen\n     while its scrim still dimmed the view. Fixed keeps the panel in view and its\n     scrim catches every click regardless of scroll. */\n  overflow-y: auto;\n}\n.ew-modal {\n  width: 100%; max-width: 460px; box-sizing: border-box;\n  background: var(--bg-elevated, #21222e); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 12px;\n  padding: 18px; margin-top: 4vh;\n}\n.ew-modal:focus { outline: none; }\n.ew-modal-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; }\n.ew-modal-body { font-size: 14px; line-height: 1.75; margin-bottom: 12px; }\n.ew-modal-note { margin-bottom: 14px; }\n.ew-modal-gate { display: block; margin-bottom: 14px; }\n.ew-modal-gate .ew-meta { display: block; margin-bottom: 6px; }\n.ew-modal-problem {\n  font-size: 13px; line-height: 1.7; margin-bottom: 12px;\n  color: var(--danger, #f87171);\n}\n.ew-modal-bar { margin-top: 0; }\n\n/* What is about to be lost, named. A count alone does not tell the player which\n   life they are ending. */\n.ew-doomed {\n  list-style: none; margin: 0 0 14px; padding: 0;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  max-height: 34vh; overflow-y: auto;\n}\n.ew-doomed li {\n  display: flex; justify-content: space-between; gap: 10px;\n  padding: 8px 12px; font-size: 13px;\n  border-bottom: 1px solid var(--border, #2d2f3d);\n}\n.ew-doomed li:last-child { border-bottom: none; }\n.ew-doomed-name { min-width: 0; overflow-wrap: anywhere; }\n.ew-doomed-where { color: var(--muted, #6b7280); flex: 0 0 auto; font-size: 12px; }\n\n/* ── opening screen ── */\n\n.ew-group { margin-bottom: 20px; }\n.ew-glabel {\n  font-size: 14px; font-weight: 600; margin-bottom: 2px;\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;\n}\n.ew-ghint { font-size: 12px; color: var(--muted, #6b7280); margin-bottom: 8px; }\n\n/* Options are buttons, not a select: on a phone a native select opens a modal\n   wheel for six words, and the words are the whole point of this screen. */\n.ew-opt {\n  border-radius: 9999px; padding: 7px 13px; font-size: 13px;\n  border: 1px solid var(--border, #2d2f3d); background: transparent;\n  color: var(--text, #e2e8f0); cursor: pointer; font: inherit;\n  min-height: 36px; -webkit-tap-highlight-color: transparent;\n}\n.ew-opt-on {\n  border-color: transparent; color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 18%, transparent);\n}\n\n.ew-input {\n  width: 100%; box-sizing: border-box;\n  background: var(--bg, #1a1b26); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; font: inherit; font-size: 15px;\n  min-height: 44px;\n}\n.ew-input:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n\n/* A visible keyboard focus ring on every custom control, so tabbing through the\n   app can be followed. :focus-visible keeps it off pointer clicks. */\n.ew-btn:focus-visible, .ew-opt:focus-visible, .ew-choice:focus-visible,\n.ew-drawer:focus-visible, .ew-card-open:focus-visible, .ew-slot-btn:focus-visible,\n.ew-starbtn:focus-visible,\n.ew-rail-row:focus-visible, .ew-rail-home:focus-visible, .ew-back:focus-visible,\n.ew-shelfbtn:focus-visible, .ew-rail-x:focus-visible,\n.ew-section-toggle:focus-visible {\n  outline: 2px solid var(--accent, #7c3aed); outline-offset: 2px;\n}\n\n/* Inline rename inside a life row: flexes to fill the row beside its save/cancel\n   buttons rather than forcing them onto a second line. */\n.ew-rename-input {\n  flex: 1 1 auto; min-width: 0; box-sizing: border-box;\n  background: var(--bg, #1a1b26); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 8px 10px; font: inherit; min-height: 40px;\n}\n.ew-rename-input:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n\n/* The archived group's heading is a toggle: it keeps the section typography but\n   reads as pressable. */\n.ew-section-toggle {\n  background: none; border: none; padding: 0; cursor: pointer;\n  color: inherit; text-align: start; -webkit-tap-highlight-color: transparent;\n}\n\n/* History toolbar: the events-only toggle and the jump-to-turn control. */\n.ew-history-bar {\n  display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px;\n}\n.ew-jump {\n  width: 7em; min-width: 0; box-sizing: border-box; font: inherit; min-height: 36px;\n  padding: 6px 10px; border-radius: 8px;\n  color: var(--text, #e2e8f0); background: var(--bg, #1a1b26);\n  border: 1px solid var(--border, #2d2f3d);\n}\n.ew-jump:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n.ew-search { width: 12em; }\n\n/* The \"world is being arranged\" state on the play page while a life is born. */\n.ew-arrange {\n  display: flex; flex-direction: column; gap: 12px; align-items: flex-start;\n  padding: 20px 0;\n}\n.ew-arrange-title {\n  font-size: 18px; font-weight: 600; color: var(--text, #e2e8f0);\n}\n\n/* A quiet marker when the world opens a new chapter of this life. */\n.ew-unlocked { margin: 0 0 14px; display: flex; flex-direction: column; gap: 7px; }\n\n/* \"An old thing came back\" — the echo marker (design §8.1). A single folded line\n   in the unlocked-marker voice; expanding it is the player's act, never a popup. */\n.ew-echoes { margin: 12px 0 14px; display: flex; flex-direction: column; gap: 7px; }\n.ew-echo {\n  padding-inline-start: 10px;\n  border-inline-start: 2px solid color-mix(in oklab, var(--accent, #7c3aed) 55%, transparent);\n}\n.ew-echo-line {\n  appearance: none; background: none; border: 0; padding: 2px 0; cursor: pointer;\n  font: inherit; font-size: 13px; font-style: italic; text-align: start;\n  color: var(--accent, #7c3aed);\n}\n@media (hover: hover) { .ew-echo-line:hover { text-decoration: underline; } }\n.ew-echo-body {\n  margin-top: 6px; display: flex; flex-direction: column; gap: 6px;\n  font-size: 13px; line-height: 1.6; color: var(--text, #e5e7eb);\n}\n.ew-echo-row { display: flex; gap: 8px; align-items: baseline; }\n.ew-echo-label {\n  flex: 0 0 auto; font-size: 12px; color: var(--muted, #6b7280);\n}\n.ew-echo-actions { display: flex; gap: 8px; margin-top: 2px; }\n\n.ew-unlocked-row {\n  font-size: 13px; color: var(--accent, #7c3aed);\n  padding-inline-start: 10px;\n  border-inline-start: 2px solid var(--accent, #7c3aed);\n}\n.ew-unlocked-heading { font-style: italic; font-weight: 600; }\n.ew-unlocked-meaning {\n  margin-top: 2px; font-size: 12px; line-height: 1.6;\n  color: var(--muted, #6b7280);\n}\n/* A milestone reached this month — a small gilt banner, warmer than the chapter\n   marker so an achievement reads as a reward, not just a progress note. */\n.ew-milestone { margin: 0 0 14px; display: flex; flex-direction: column; gap: 6px; }\n.ew-milestone-row {\n  font-size: 13px; font-weight: 600;\n  color: color-mix(in oklab, var(--accent, #d9b45a) 82%, var(--text, #e2e8f0));\n  padding: 8px 12px; border-radius: 8px;\n  background: color-mix(in srgb, var(--accent, #d9b45a) 12%, transparent);\n  border: 1px solid color-mix(in srgb, var(--accent, #d9b45a) 34%, var(--border, #2d2f3d));\n}\n\n/* Small ceremonies around the prose: one reveals what the world settled at birth;\n   the other restores a returning player's place without generating a new summary. */\n.ew-story-moment {\n  margin: 16px 0; padding: 12px 14px; border-radius: 10px;\n  border: 1px solid color-mix(in oklab, var(--accent, #7c3aed) 32%, var(--border, #2d2f3d));\n  /* Translucent so the story's backdrop shows through, rather than an opaque card\n     sitting on top of it. A faint accent tint over transparency keeps it reading as\n     a card; the accent border still defines its edge. */\n  background: linear-gradient(\n    180deg,\n    color-mix(in srgb, var(--accent, #7c3aed) 15%, transparent),\n    color-mix(in srgb, var(--accent, #7c3aed) 5%, transparent)\n  );\n}\n.ew-story-moment-head {\n  display: flex; align-items: baseline; justify-content: space-between;\n  gap: 12px; margin-bottom: 7px;\n}\n.ew-story-moment-title { font-size: 13px; font-weight: 600; color: var(--accent, #7c3aed); }\n.ew-story-moment-close {\n  flex: none; border: none; padding: 3px 0; background: transparent;\n  color: var(--muted, #6b7280); font: inherit; font-size: 11px; cursor: pointer;\n}\n.ew-story-moment-close:focus-visible {\n  outline: 2px solid var(--accent, #7c3aed); outline-offset: 2px;\n}\n.ew-reveal-row {\n  display: flex; justify-content: space-between; gap: 12px;\n  padding: 4px 0; font-size: 13px; line-height: 1.5;\n}\n.ew-reveal-label, .ew-recap-label { color: var(--muted, #6b7280); }\n.ew-reveal-value { text-align: end; font-weight: 600; }\n.ew-story-moment-hint { margin-top: 6px; font-size: 11px; color: var(--muted, #6b7280); }\n/* On the now-translucent story-moment cards, the cold --muted grey is hard to read\n   over the backdrop. Warm it toward the accent and lighten it — the mock's scheme —\n   scoped to these cards so ordinary muted text elsewhere is untouched. */\n.ew-story-moment .ew-reveal-label,\n.ew-story-moment .ew-recap-label,\n.ew-story-moment .ew-story-moment-hint {\n  color: color-mix(in srgb, var(--text, #e2e8f0) 70%, var(--accent, #7c3aed));\n}\n.ew-recap-line { margin: 5px 0; font-size: 12px; line-height: 1.65; }\n.ew-recap-list { margin: 4px 0 8px; padding-inline-start: 18px; font-size: 12px; line-height: 1.65; }\n\n/* A turn's marked events and gains — the material the events-only timeline shows. */\n.ew-marks { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; }\n.ew-mark {\n  font-size: 13px; line-height: 1.6; padding-inline-start: 12px; position: relative;\n}\n.ew-mark::before {\n  content: \"·\"; position: absolute; inset-inline-start: 2px; color: var(--muted, #6b7280);\n}\n.ew-mark-gain { color: var(--muted, #6b7280); }\n\n/* A scalar field the narrator handed a structured value: its text, one line each. */\n.ew-lines { display: flex; flex-direction: column; gap: 3px; }\n\n/* The pre-birth summary: every opening choice on one line, with world-decided\n   items plainly marked so a look-before-you-leap is honest about what was chosen. */\n.ew-summary {\n  margin: 18px 0 6px; padding: 12px 14px; border-radius: 10px;\n  border: 1px solid var(--border, #2d2f3d); background: var(--card, #1f2030);\n}\n.ew-summary-row {\n  display: flex; gap: 12px; justify-content: space-between; align-items: baseline;\n  padding: 4px 0; font-size: 14px; line-height: 1.6;\n}\n.ew-summary-label { color: var(--muted, #6b7280); flex: 0 0 auto; }\n.ew-summary-value { text-align: end; }\n.ew-summary-world { text-align: end; color: var(--muted, #6b7280); font-style: italic; }\n\n.ew-sealed {\n  border: 1px dashed var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7;\n}\n\n.ew-bar {\n  display: flex; gap: 8px; flex-wrap: wrap; align-items: center;\n  margin-top: 20px; padding-top: 16px;\n  border-top: 1px solid var(--border, #2d2f3d);\n}\n.ew-btn {\n  border-radius: 8px; padding: 0 16px; min-height: 44px;\n  border: 1px solid var(--border, #2d2f3d); background: transparent;\n  color: var(--text, #e2e8f0); font: inherit; font-size: 14px; cursor: pointer;\n  -webkit-tap-highlight-color: transparent;\n}\n.ew-btn-go {\n  border-color: transparent; background: var(--accent, #7c3aed); color: #fff;\n  font-weight: 600; flex: 1; min-width: 140px;\n}\n.ew-btn:disabled, .ew-btn-go:disabled { opacity: .5; cursor: default; }\n\n/* Destructive, and it must read that way BEFORE it is pressed. Colour is not the\n   safeguard (the dialog is), but a delete that looks like every other button is a\n   delete the player presses while reading something else. */\n.ew-btn-danger {\n  border-color: var(--danger, #f87171);\n  color: var(--danger, #f87171);\n  background: color-mix(in oklab, var(--danger, #f87171) 12%, transparent);\n  flex: 0 0 auto;\n}\n/* The way OUT of a destructive path, and the way INTO one from a page whose\n   subject is something else. Quiet on purpose. */\n.ew-btn-quiet {\n  color: var(--muted, #6b7280); border-color: transparent;\n  flex: 0 0 auto; min-height: 36px; padding: 0 12px; font-size: 13px;\n}\n@media (hover: hover) { .ew-btn-quiet:hover { color: var(--text, #e2e8f0); } }\n.ew-spacer { flex: 1; }\n/* Language chooser on the world card: a small toggle set, the chosen one filled. */\n.ew-lang {\n  border: 1px solid var(--border, #334155); border-radius: 999px;\n  background: transparent; color: var(--muted, #6b7280);\n  min-height: 32px; padding: 0 14px; font-size: 13px; cursor: pointer;\n}\n@media (hover: hover) { .ew-lang:hover { color: var(--text, #e2e8f0); } }\n.ew-lang[aria-pressed=\"true\"] {\n  background: var(--accent, #6366f1); color: #fff; border-color: transparent;\n}\n@media (min-width: 768px) { .ew-btn-go { flex: 0 0 auto; } }\n\n/* ── prose ── */\n\n/* Reading typography, not UI typography — this is the only place the player reads\n   for minutes at a time. */\n.ew-prose {\n  font-size: 16px; line-height: 1.85; max-width: 66ch; margin: 12px 0 0;\n  /* CJK and ordinary prose wrap fine on their own; this only catches a long\n     unbreakable token (a URL, an id) so it breaks instead of overflowing the page\n     on a narrow screen. Not `break-all`, which would break ordinary words too. */\n  overflow-wrap: anywhere;\n}\n.ew-prose pre { overflow-x: auto; }\n/* Only the fallback path needs pre-wrap. With the host's markdown renderer,\n   paragraphs are real elements and pre-wrap would double every blank line. */\n.ew-prose-plain { white-space: pre-wrap; }\n.ew-prose p { margin: 0 0 1.1em; }\n.ew-prose p:last-child { margin-bottom: 0; }\n.ew-prose em { font-style: italic; }\n.ew-prose h1, .ew-prose h2, .ew-prose h3 {\n  font-size: 1.05em; font-weight: 600; margin: 1.4em 0 .5em;\n}\n.ew-prose blockquote {\n  margin: 1em 0; padding-left: 12px;\n  border-left: 2px solid var(--border, #2d2f3d); color: var(--muted, #6b7280);\n}\n.ew-prose ul, .ew-prose ol { margin: .8em 0; padding-left: 1.4em; }\n.ew-prose li { margin: .25em 0; }\n\n/* ── play page ── */\n\n/* Narrow-first single column; panels move to a sidebar from 900px. Below that the\n   sidebar is absent entirely and the drawer is how panels stay reachable —\n   rendering both would put every panel on screen twice. */\n/* The story's background layer, spanning the WHOLE app on the live view. The app\n   root is the positioning context (.ew-root is position:relative); the backdrop is\n   placed behind everything (z-index 0) and cannot be interacted with. Every real\n   child of the root is lifted above it, so the background never covers or\n   intercepts a control — the anti-phishing guarantee for a scriptless frame. */\n.ew-root > *:not(.ew-backdrop) { position: relative; z-index: 1; }\n.ew-backdrop {\n  position: fixed; inset: 0; z-index: 0;\n  pointer-events: none; overflow: hidden;\n  /* Pinned to the viewport, NOT sized to content. Expanding the drawer or the\n     panels used to grow this layer (it was `absolute; inset:0` inside .ew-root,\n     so its height tracked the content), and `object-fit: cover` then re-cropped\n     the SVG — the art behind a translucent button visibly shifted colour on open.\n     Fixed fills the viewport regardless of content height, so it never re-crops,\n     and a short screen (opening / \"arranging\") is still fully covered. */\n}\n.ew-backdrop-frame {\n  position: absolute; inset: 0;\n  width: 100%; height: 100%;\n  border: 0; pointer-events: none;\n  object-fit: cover; display: block;\n  background: transparent;\n}\n/* A contrast floor between the background and the prose, kept light so a PATTERN\n   reads through instead of being flattened into grey. The narrator supplies real\n   imagery; a heavy scrim would waste it. Legibility past this is the reading\n   surfaces' own semi-opaque backing, not more dimming here. */\n.ew-backdrop-scrim {\n  position: absolute; inset: 0;\n  pointer-events: none;\n  background: linear-gradient(\n    to bottom,\n    color-mix(in srgb, var(--ew-bg, #0b0c10) 22%, transparent),\n    color-mix(in srgb, var(--ew-bg, #0b0c10) 40%, transparent)\n  );\n}\n\n.ew-play { display: block; }.ew-aside { display: none; }\n@media (min-width: 900px) {\n  .ew-play {\n    display: grid; grid-template-columns: minmax(0,1fr) 300px; gap: 28px; align-items: start;\n  }\n  .ew-aside { display: block; position: sticky; top: 12px; }\n}\n\n/* A sheet over the column takes the story off screen with it, the way a phone's\n   region tab replaces the story rather than floating above it.\n\n   Needed because the star map is deliberately TRANSPARENT when a life backdrop is\n   mounted (.ews-overlay:has(> .ew-backdrop)) so the world's art becomes the room —\n   and that same transparency let the prose read through the sheet's negative space,\n   between and below its frosted instruments. Dimming it further was the wrong lever:\n   the text was legible enough to be noise at any scrim alpha that still let the art\n   through.\n\n   `visibility`, not `display`. The sheet is absolute with `inset: 0` against .ew-root,\n   so its box is the app panel's — a box .ew-root only has because this content is in\n   the layout. Removing the content collapses .ew-root and the sheet collapses with it\n   (measured: panel 873px tall, sheet 841px). Hiding it keeps the height and drops the\n   ink, and takes the story out of hit-testing and the a11y tree while a modal is up.\n   The backdrop is untouched: the app's own .ew-backdrop is a child of .ew-root, not of\n   this column, and the sheet mounts its own copy inside itself. */\n.ew-play-root:has(> .ews-overlay) > *:not(.ews-overlay) { visibility: hidden; }\n\n/* Title with the in-world date beside it (shown only when the world has one). */\n.ew-titleline { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }\n.ew-titleline .ew-clock { margin-bottom: 0; }\n.ew-clock {\n  font-size: 12px; color: var(--muted, #6b7280); letter-spacing: .04em; margin-bottom: 4px;\n}\n\n/* Back button and turn pager share one row, the pager pushed to the far right. */\n.ew-topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }\n/* Turn pager: ‹ current turn › */\n.ew-pager {\n  display: flex; align-items: center; justify-content: center; gap: 14px;\n  margin: 0;\n}\n.ew-pager-turn {\n  font-size: 13px; color: var(--muted, #6b7280); letter-spacing: .04em;\n  min-width: 6em; text-align: center;\n}\n.ew-pager-arw {\n  display: inline-flex; align-items: center; justify-content: center;\n  width: 36px; height: 36px; border-radius: 8px; cursor: pointer;\n  background: transparent; border: 1px solid var(--border, #2d2f3d);\n  color: var(--text, #e2e8f0);\n}\n@media (hover: hover) { .ew-pager-arw:hover:not(:disabled) { border-color: var(--accent, #7c3aed); } }\n.ew-pager-arw:disabled { opacity: .35; cursor: default; }\n\n/* The standing summary above the prose. It had no surface at all — 13px muted rows\n   sitting directly on the page's backdrop art, which is where it became hard to\n   read: a photograph or a motif behind small grey type takes the contrast with it.\n   A faint tint plus a border gives it a surface without turning it into a card that\n   competes with the story: deliberately quieter than `.ew-story-moment` (no accent\n   in the border, less tint), because the recap is a one-time notice and this is\n   permanent furniture the eye should pass over on its way to the prose. */\n.ew-digest {\n  margin: 0 0 20px; padding: 10px 12px 4px; border-radius: 10px;\n  /* Fixed dark values, NOT var(--card)/var(--border): those come from the DASHBOARD's\n     theme, and under a light dashboard `--card` is white — measured, a 42% mix of it\n     laid a white wash over this app's own dark canvas. The same rgba(6,7,14) family\n     the tab bar uses is correct on that canvas whatever theme surrounds it. */\n  border: 1px solid rgba(255, 255, 255, .09);\n  background: rgba(6, 7, 14, .42);\n}\n/* The last row's rule would otherwise sit a hair above the new bottom padding and\n   read as an unfinished edge. */\n.ew-digest .ew-drow:last-child { border-bottom: 0; }\n/* Page-turn: the story slides+fades in — from the right going forward, from the\n   left going back. Keyed remount per turn runs it once; motion-reduce opts out. */\n@keyframes ew-page-fwd { from { opacity: 0; transform: translateX(26px); } to { opacity: 1; transform: none; } }\n@keyframes ew-page-back { from { opacity: 0; transform: translateX(-26px); } to { opacity: 1; transform: none; } }\n.ew-turnpage-fwd { animation: ew-page-fwd .3s ease-out both; }\n.ew-turnpage-back { animation: ew-page-back .3s ease-out both; }\n@media (prefers-reduced-motion: reduce) {\n  .ew-turnpage-fwd, .ew-turnpage-back { animation: none; }\n}\n.ew-drow {\n  display: flex; gap: 8px; padding: 6px 0; font-size: 13px; line-height: 1.7;\n  border-bottom: 1px solid var(--border, #2d2f3d);\n}\n.ew-drow-rumour { color: var(--muted, #6b7280); font-style: italic; }\n.ew-dcat { color: var(--muted, #6b7280); flex: 0 0 auto; min-width: 4.5em; }\n\n/* Panels keep UI type while the prose gets reading type — a stat block read at\n   16/1.85 is harder to scan, not easier. */\n.ew-panel-box {\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  padding: 12px; margin-bottom: 10px; font-size: 13px;\n}\n.ew-panel-box-name {\n  margin-bottom: 5px; font-size: 13px; font-weight: 600;\n  color: var(--text, #e2e8f0);\n}\n.ew-panel-quiet { opacity: .55; }\n.ew-prow { display: flex; gap: 10px; align-items: baseline; padding: 5px 0; line-height: 1.6; }\n.ew-plabel { color: var(--muted, #6b7280); flex: 0 0 5.5em; }\n.ew-pval { flex: 1; min-width: 0; overflow-wrap: anywhere; }\n/* A rank/tier value renders as an accent chip, but the narrator can write a whole\n   clause into it (measured on the flagship). Chips are nowrap by default so tag\n   rows stay tidy — but a value chip must wrap instead of overflowing the panel. */\n.ew-pval .ew-chip { white-space: normal; overflow-wrap: anywhere; }\n.ew-gap { color: var(--border, #2d2f3d); }\n\n/* A label that is really a sentence. Measured on the live flagship: the narrator\n   wrote a whole clause into a label slot, and the fixed 5.5em column wrapped it to\n   ten lines beside a single dot. Stacking costs one line of height and makes the row\n   readable; keeping the column costs ten and does not. */\n.ew-prow-stack { display: block; }\n.ew-prow-stack .ew-plabel { flex: none; margin-bottom: 2px; line-height: 1.55; }\n.ew-prow-stack .ew-pval { margin-left: 0; }\n\n.ew-bar-track {\n  height: 4px; border-radius: 2px; margin-top: 5px;\n  background: var(--border, #2d2f3d); overflow: hidden;\n}\n.ew-bar-fill { height: 100%; background: var(--accent, #7c3aed); }\n\n.ew-list { margin: 0; padding: 0; list-style: none; }\n.ew-list li { padding: 2px 0; }\n.ew-sub { color: var(--muted, #6b7280); }\n/* The world's name, demoted to a second line now that the life's own identity holds\n   the first. Small: it is the same string on every row, so it is context, not news. */\n.ew-card .ew-sub { display: block; font-size: 12px; margin-bottom: 2px; }\n\n.ew-choices { display: flex; flex-direction: column; gap: 8px; margin: 20px 0 0; }\n.ew-choice {\n  text-align: left; width: 100%; box-sizing: border-box;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  /* Translucent so the scene's backdrop shows through every choice — the shared,\n     theme-matching texture for the whole row, at no narrator cost. */\n  background: color-mix(in srgb, var(--card, #1f2030) 66%, transparent);\n  color: var(--text, #e2e8f0);\n  padding: 12px 14px; font: inherit; font-size: 14px; line-height: 1.5;\n  min-height: 48px; cursor: pointer; -webkit-tap-highlight-color: transparent;\n  transition: border-color .14s ease, background .14s ease, transform .14s ease;\n}\n/* Match the armed look on press so the touch highlight flows straight into the\n * armed state. Without this, `:active` only moved the border, so on release the\n * button dropped to its dim base style for a frame before React applied `armed`\n * — reading as a grey dip between two highlights on a single tap. */\n.ew-choice:active {\n  border-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 8%, var(--card, #1f2030));\n}\n.ew-choice:disabled { opacity: .5; cursor: default; }\n\n/* The one that was chosen. Kept at full opacity while its siblings dim, because\n   the point of the waiting state is to confirm WHICH choice was taken — a row where\n   every option is equally grey has answered a different question. */\n.ew-choicewrap { margin-bottom: 8px; }\n.ew-choice { position: relative; overflow: hidden; }\n.ew-choice-label { position: relative; z-index: 1; }\n\n/* A fateful choice — one the narrator marked as able to lead to a major event or\n   turning point. A distinctive, ornate look so it reads as weightier than the\n   rest: an accent border, a faint diagonal gilt hatch, and a glow blooming from\n   the top corner. Theme-aware (all tints derive from --accent), and still\n   translucent so the backdrop shows through like its siblings. Kept as background\n   layers, not a pseudo-element, so it never collides with the waiting sweep. */\n.ew-choice-fateful {\n  border-color: color-mix(in oklab, var(--accent, #7c3aed) 55%, var(--border, #2d2f3d));\n  background:\n    repeating-linear-gradient(\n      135deg,\n      color-mix(in srgb, var(--accent, #7c3aed) 10%, transparent) 0 2px,\n      transparent 2px 11px\n    ),\n    radial-gradient(\n      130% 170% at 100% 0%,\n      color-mix(in srgb, var(--accent, #7c3aed) 26%, transparent),\n      transparent 55%\n    ),\n    color-mix(in srgb, var(--card, #1f2030) 64%, transparent);\n  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent, #7c3aed) 20%, transparent);\n  /* A slow accent glow that breathes, so a fateful choice quietly signals weight\n     before it is even touched. On the border only (the narrator's art sits inside),\n     slow enough to read as ambience not alarm; disabled under reduced-motion. */\n  animation: ew-fateful-glow 4.5s ease-in-out infinite;\n}\n\n/* The narrator's own SVG for a fateful choice, as an inert image behind the label.\n   Kept low-opacity so the label stays readable; the accent border still frames it. */\n.ew-choice-art {\n  position: absolute; inset: 0; z-index: 0;\n  width: 100%; height: 100%;\n  /* A fateful choice's own art is ONE centred emblem, so contain it — the button\n     is far wider than the art's viewBox, and `cover` would crop the symbol to a\n     horizontal band (its top and bottom sliced off). The shared tiled motif below\n     overrides back to `cover`, because a texture is meant to fill edge to edge. */\n  object-fit: contain;\n  pointer-events: none; opacity: .55;\n}\n/* The shared scene motif on ordinary buttons sits fainter than a fateful choice's\n   own art, so a fateful choice still stands out from the row. It is a full-bleed\n   texture, so it fills the button (cover) rather than being contained. */\n.ew-choice-art-common { opacity: .4; object-fit: cover; }\n/* When the narrator supplied art, it IS the pattern — drop the app's fallback\n   hatch/glow so the two do not fight, but keep the accent border/frame. Declared\n   after .ew-choice-fateful so it wins the cascade. */\n.ew-choice-arted {\n  background: color-mix(in srgb, var(--card, #1f2030) 60%, transparent);\n}\n\n/* Armed: chosen, not yet done. Reads as a held breath — brighter and slightly\n   raised, but explicitly NOT the accent fill the committing state uses, so the two\n   are never confused at a glance. */\n.ew-choice-armed {\n  border-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 8%, var(--card, #1f2030));\n  transform: translateY(-1px);\n  transition: transform .14s ease, background .14s ease, border-color .14s ease;\n}\n\n.ew-choice-waiting {\n  opacity: 1 !important;\n  border-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 12%, var(--card, #1f2030));\n}\n/* Siblings of the choice being written: still present (the fork stays readable)\n   but clearly not the one happening. */\n.ew-choice-dimmed { opacity: .45; }\n/* The turn progress living INSIDE the chosen option: full-width under the label,\n   above the sweep light. */\n.ew-choice .ew-progress { position: relative; z-index: 1; width: 100%; margin-top: 6px; }\n.ew-writing-action { margin-bottom: 6px; font-style: italic; opacity: .9; }\n/* A light sweeping across the chosen line, once every couple of seconds. Chosen\n   over a spinner because it belongs to the SENTENCE the player picked rather than\n   to the page: what is being waited on is that line becoming a month. */\n.ew-choice-waiting::after {\n  content: ''; position: absolute; inset: 0; z-index: 0;\n  background: linear-gradient(\n    100deg,\n    transparent 20%,\n    color-mix(in oklab, var(--accent, #7c3aed) 22%, transparent) 50%,\n    transparent 80%\n  );\n  transform: translateX(-100%);\n  animation: ew-sweep 2.1s ease-in-out infinite;\n}\n\n/* ── the second step ──────────────────────────────────────────────────────\n   A turn is a month of a life and cannot be undone, so committing one is its own\n   deliberate act. The row appears under the armed choice rather than in a modal:\n   a dialog would take the sentence being decided off the screen. */\n.ew-confirm {\n  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;\n  padding: 8px 4px 2px 14px;\n  animation: ew-rise .16s ease-out;\n}\n.ew-confirm-act { padding-left: 0; }\n.ew-confirm-ask { font-size: 13px; color: var(--muted, #6b7280); margin-right: 2px; }\n.ew-btn-sm { min-height: 36px; padding: 0 14px; font-size: 13px; flex: 0 0 auto; }\n.ew-note-live { display: flex; align-items: center; margin-top: 10px; min-width: 0; }\n/* Turn progress: a staged bar the narrator's tool calls drive — a fill that jumps\n   to ~90% once it has read the life, plus a moving shimmer so the long writing\n   phase never looks stalled. */\n.ew-progress { width: 100%; min-width: 0; }\n.ew-progress-track {\n  position: relative; height: 6px; border-radius: 999px; overflow: hidden;\n  background: var(--border, #2d2f3d);\n}\n.ew-progress-fill {\n  position: absolute; inset: 0 auto 0 0; width: 0; border-radius: 999px;\n  background: var(--accent, #7c3aed); transition: width .4s ease;\n}\n.ew-progress-track::after {\n  content: ''; position: absolute; inset: 0; z-index: 1;\n  background: linear-gradient(\n    100deg, transparent 20%,\n    color-mix(in oklab, #fff 28%, transparent) 50%, transparent 80%\n  );\n  transform: translateX(-100%); animation: ew-sweep 1.6s ease-in-out infinite;\n}\n.ew-progress-steps {\n  display: flex; justify-content: space-between; gap: 8px; margin-top: 6px;\n}\n.ew-progress-label { font-size: 12px; color: var(--muted, #6b7280); }\n.ew-progress-count { font-size: 11px; color: var(--muted, #6b7280); flex: 0 0 auto; }\n@media (prefers-reduced-motion: reduce) {\n  .ew-progress-track::after { animation: none; opacity: 0; }\n}\n\n/* ── waiting ──────────────────────────────────────────────────────────────\n   The app's only animation, introduced with its reduced-motion answer in the same\n   edit rather than after: idle motion like this reads as pleasant to most people\n   and as a symptom to someone with a vestibular disorder, and retrofitting the\n   media query means shipping the version without it. */\n\n.ew-wait {\n  display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap;\n  vertical-align: middle; margin-left: 8px; position: relative; z-index: 1;\n  min-width: 0; max-width: 100%;\n}\n.ew-wait-dots { display: inline-flex; gap: 4px; flex: 0 0 auto; }\n.ew-wait-label { font-size: 12px; color: var(--muted, #6b7280); min-width: 0; overflow-wrap: anywhere; }\n\n.ew-dot {\n  width: 5px; height: 5px; border-radius: 50%;\n  background: currentColor; opacity: .35;\n  animation: ew-pulse 1.1s ease-in-out infinite;\n}\n/* Staggered, so the group reads as one moving thing rather than three blinking\n   ones. */\n.ew-dot:nth-child(2) { animation-delay: .18s; }\n.ew-dot:nth-child(3) { animation-delay: .36s; }\n\n@keyframes ew-pulse {\n  0%, 80%, 100% { opacity: .25; transform: scale(.8); }\n  40%           { opacity: 1;   transform: scale(1); }\n}\n@keyframes ew-sweep {\n  0%        { transform: translateX(-100%); }\n  60%, 100% { transform: translateX(100%); }\n}\n@keyframes ew-rise {\n  from { opacity: 0; transform: translateY(-3px); }\n  to   { opacity: 1; transform: none; }\n}\n\n@media (prefers-reduced-motion: reduce) {\n  /* Not \"animation: none\" alone — that would leave three barely-visible dots and\n     no signal at all. Every indicator stays; they simply stop moving. */\n  .ew-dot { animation: none; opacity: .75; }\n  .ew-choice-waiting::after { animation: none; transform: none; opacity: .35; }\n  .ew-confirm { animation: none; }\n  .ew-choice-armed { transition: none; transform: none; }\n  .ew-choice { transition: none; }\n  .ew-choice-fateful { animation: none; }\n}\n\n.ew-act { display: flex; gap: 8px; margin-top: 12px; align-items: stretch; }\n.ew-act textarea {\n  flex: 1; min-width: 0; box-sizing: border-box; resize: vertical;\n  min-height: 44px; max-height: 40vh;\n  background: var(--bg, #1a1b26); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  padding: 11px 12px; font: inherit; font-size: 15px; line-height: 1.5;\n}\n.ew-act textarea:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n\n.ew-count { font-size: 11px; color: var(--muted, #6b7280); margin-top: 4px; }\n\n/* The drawer is how panels stay reachable on a phone without pushing the prose\n   off the first screen. */\n.ew-drawer {\n  width: 100%; margin: 20px 0 0;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  background: transparent; color: var(--text, #e2e8f0);\n  font: inherit; font-size: 13px; min-height: 44px; cursor: pointer;\n}\n@media (min-width: 900px) { .ew-drawer { display: none; } }\n\n/* The way into the life star map. It looks like the panels drawer because it sits\n   in the same place and is the same kind of move, but it is NOT that class: the\n   drawer disappears above 900px (its panels move into the aside) and the star map\n   has no aside twin, so sharing the class hid the only entrance on a desktop. */\n.ew-starbtn {\n  display: block; width: 100%; margin: 20px 0 0;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  background: transparent; color: var(--text, #e2e8f0);\n  font: inherit; font-size: 13px; min-height: 44px; cursor: pointer;\n}\n\n/* ── the scene slot ── */\n\n/* ONE element, created on first need and never moved. Moving an iframe in the DOM\n   reloads it, so re-parenting a mounted scene would throw away whatever the player\n   was looking at — and a React portal does not help, because the browser's rule is\n   about the element's position in the document, not about who rendered it. */\n.ew-slot {\n  display: none;\n  width: 100%;\n  /* FROSTED, not a slab. The scene's own document is transparent, so what fills this\n     box is the world's backdrop art seen through a low-alpha dark scrim and a blur —\n     each world tints its own widgets, and no colour decision is ever handed to the\n     narrator (it sends structure; style is the app's).\n\n     The scrim is a fixed dark rgba and NOT var(--card): resolving a host theme\n     variable here is what once painted a pale slab under a light dashboard. The alpha\n     is what keeps the frame legible over whatever the illustrator drew — the same\n     treatment the phone reader bar uses over the same art. The alpha is SOLVED, not\n     picked: at .58 a scene's body text measured 4.20:1 against this scrim over a white\n     illustration and its labels 2.50:1, both under WCAG AA —\n     backend/tests/test_widget_contrast.py computes it and fails below the floor.\n\n     `backdrop-filter` belongs HERE rather than inside the frame: an iframe's backdrop\n     root is its own document, so it cannot blur the page behind itself. */\n  border: 1px solid rgba(255, 255, 255, .12);\n  border-radius: 10px;\n  background: rgba(9, 10, 14, .66);\n  -webkit-backdrop-filter: blur(16px) saturate(1.08);\n  backdrop-filter: blur(16px) saturate(1.08);\n  /* A scene is a picture, not a page: it never becomes the scrolling thing. The\n     frame is sized to the document's reported height instead, so there is nothing\n     left below the fold to scroll to. */\n  overflow: hidden;\n}\n/* The height before the frame has reported its own: a scene mid-load, or one whose\n   report never arrives. Live scenes are sized in `scene.tsx` from the report. */\n.ew-slot-on { display: block; height: 320px; }\n\n.ew-slot-wrap { position: relative; margin: 16px 0 0; }\n\n/* The scene frames render after the app shell, outside it — so the shell's own\n   bottom clearance does not reach them, and the last scene on a phone ended up\n   under the fixed tab bar. This is that clearance for the frames. */\n.ew-scenes-clear { padding-bottom: 72px; }\n\n/* A shelf row that carries its own destructive control. The row is a div and the\n   open action is a button INSIDE it, because a button cannot contain a button --\n   and the delete has to be a sibling, not a nested child. */\n/* A column, so the card can carry the delete ask as a second row beneath its\n   content; `.ew-card-rowmain` is the horizontal part that used to be this rule. */\n.ew-card-row { display: flex; flex-direction: column; gap: 0; padding: 0; overflow: visible; }\n.ew-card-rowmain { display: flex; align-items: stretch; gap: 0; }\n\n/* The delete ask, attached UNDER the life it will end.\n   Inside the card on purpose: a page-level dialog for a per-row action has to be\n   told which row it means, and this one cannot be looked at without also seeing the\n   life's own title directly above it. */\n.ew-rowdoom {\n  border-top: 1px solid rgba(255, 255, 255, .09);\n  background: color-mix(in oklab, var(--danger, #e5484d) 12%, transparent);\n  padding: 12px;\n}\n.ew-rowdoom-say { font-size: 14px; line-height: 1.45; }\n.ew-rowdoom-note { margin-top: 4px; }\n.ew-rowdoom-bar {\n  display: flex; gap: 8px; justify-content: flex-end; margin-top: 10px;\n}\n/* 44px, the smallest target a finger hits reliably — the same floor the row's own\n   menu uses, and this is the one row where a miss is expensive. */\n.ew-rowdoom-bar .ew-btn { min-height: 44px; }\n.ew-card-open {\n  flex: 1 1 auto; min-width: 0; text-align: left; font: inherit;\n  background: transparent; border: none; color: inherit; cursor: pointer;\n  /* 12px, matching .ew-card, so a life row is inset exactly like a world card. */\n  padding: 12px; -webkit-tap-highlight-color: transparent;\n}\n.ew-card-open:disabled { opacity: .55; cursor: default; }\n/* Aligned to the top of the row rather than centred: a row is two or three lines\n   tall, and a vertically centred control drifts as the row's text grows. */\n.ew-card-drop {\n  align-self: flex-start; margin: 10px 10px 0 0; border-radius: 8px;\n}\n/* Row actions: inline on desktop, collapsed into a kebab menu on a phone where\n   three stacked buttons wrapped badly. */\n.ew-life-actions { display: flex; align-items: flex-start; }\n.ew-life-menu { display: none; position: relative; align-self: flex-start; margin: 10px 10px 0 0; }\n@media (max-width: 767px) {\n  .ew-life-actions { display: none; }\n  .ew-life-menu { display: block; }\n  /* iOS Safari zooms the page when a focused control's font-size is under 16px.\n     Floor every control at 16px on a phone so focusing an input never zooms in. */\n  .ew-root input, .ew-root textarea, .ew-root select { font-size: 16px; }\n}\n.ew-kebab {\n  display: inline-flex; align-items: center; justify-content: center;\n  /* 44px, the smallest target a finger hits reliably — it was 40 and \"often\n     missed\" was one of the two complaints about this control. */\n  width: 44px; height: 44px; border-radius: 8px; cursor: pointer;\n  -webkit-tap-highlight-color: transparent;\n  background: transparent; border: 1px solid var(--border, #2d2f3d);\n  color: var(--muted, #6b7280); -webkit-tap-highlight-color: transparent;\n}\n@media (hover: hover) { .ew-kebab:hover { color: var(--text, #e2e8f0); } }\n.ew-kebab:active { background: color-mix(in oklab, var(--accent, #7c3aed) 18%, transparent); }\n/* Sits above every life row (rows are z-index auto) and just below the menu, so\n   a tap anywhere but the menu is absorbed here and closes it — never reaching the\n   row beneath. Transparent, but it MUST catch clicks, so no pointer-events:none. */\n/* Both live at body level now (see LifeRow), so these z-indexes finally mean what\n   they say. Above the phone's tab bar (30) and reading bar (29), because a menu the\n   player opened is the thing they are interacting with. */\n.ew-menu-backdrop { position: fixed; inset: 0; z-index: 40; background: transparent; }\n.ew-menu {\n  position: fixed; z-index: 41; min-width: 176px;\n  display: flex; flex-direction: column; gap: 2px; padding: 6px;\n  background: var(--card, #1f2030); border: 1px solid var(--border, #2d2f3d);\n  border-radius: 10px; box-shadow: 0 10px 28px rgba(0, 0, 0, .45);\n}\n.ew-menu-item {\n  text-align: left; font: inherit; cursor: pointer; min-height: 44px;\n  padding: 11px 14px; border: none; border-radius: 6px;\n  background: transparent; color: var(--text, #e2e8f0);\n  -webkit-tap-highlight-color: transparent;\n  transition: background .12s ease;\n}\n/* Touch had NO feedback at all: the only state was a hover rule behind\n   `@media (hover: hover)`, so a finger got nothing back and a tap that did land felt\n   like one that had missed. `:active` covers touch and mouse alike. */\n.ew-menu-item:active { background: color-mix(in oklab, var(--accent, #7c3aed) 22%, var(--card, #1f2030)); }\n.ew-menu-item:focus-visible {\n  outline: 2px solid var(--accent, #7c3aed); outline-offset: -2px;\n}\n@media (hover: hover) { .ew-menu-item:hover { background: color-mix(in oklab, var(--accent, #7c3aed) 12%, var(--card, #1f2030)); } }\n\n/* ── phone bottom tab bar ──────────────────────────────────────────────────\n   Sticky at the foot of the app's own scroll container (never position:fixed,\n   which in the dashboard DOM escapes the panel). Colour IS the background: a soft\n   dark fade lifts it off the story text scrolling under it, with no panel block.\n   Hides on scroll-down, returns on scroll-up. */\n.ew-tabbar {\n  position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;\n  max-width: 900px; margin-inline: auto;  /* match the centred .ew-root column */\n  display: flex; height: 60px;\n  padding-bottom: env(safe-area-inset-bottom, 0);  /* clear the iOS home indicator */\n  background: linear-gradient(180deg,\n    rgba(6, 7, 14, 0) 0%, rgba(6, 7, 14, .82) 46%, rgba(6, 7, 14, .96) 100%);\n  transition: transform .28s ease;\n  pointer-events: auto;\n}\n.ew-tabbar-hidden { transform: translateY(96px); }\n\n/* The phone's reading controls, held below the dashboard's own chrome.\n\n   FIXED, so a pane rubber-banding past its own top slides its content UNDER a row\n   that does not move — sticky pins inside the scrollport and travels with it, leaving\n   the row below a band of bare canvas.\n\n   The offset is DECLARED, and that is the whole point. It was measured before, and a\n   reading taken before the host's chrome has laid out returns 0 — which put the row on\n   top of that chrome and stayed there until a bottom-tab switch happened to remount\n   the effect. A constant cannot be 0 at the wrong moment. 42px is the pane's top edge\n   as measured at 390px width; `.topbar` declares no height of its own (content-driven,\n   padding varying by platform) so there is no host variable to read instead. If the\n   row ever overlaps that menu or leaves a gap above itself, this is the only value to\n   change, and it is checkable in one line from the dashboard's console:\n     document.querySelector('main').getBoundingClientRect().top\n\n   z-index 2 is the whole requirement: the row only has to clear the story it floats\n   over, whose own lift is 1. Higher was copied from the phone's bottom bar and had no\n   reason behind it — at body level it outranked the dashboard's own surfaces, and this\n   row is the first one the app puts where the host's furniture lives. It stays BELOW\n   the app's own overlays too (bottom bar 30, its sheet 31/32, row menus 40/41), since\n   a menu opening over the reading row is right and the reverse is not. */\n.ew-root { --ew-chrome-h: 42px; }\n\n.ew-topbar-fixed {\n  position: fixed; left: 0; right: 0; top: var(--ew-chrome-h); z-index: 2;\n  padding: 8px var(--ew-gutter, 16px);\n  background: rgba(8, 9, 18, .52);\n  backdrop-filter: blur(16px) saturate(1.15);\n  border-bottom: 1px solid rgba(255, 255, 255, .06);\n  transition: transform .28s ease, opacity .28s ease;\n}\n/* Holds the row's place now that it is out of the flow: its own footprint, stated —\n   44px of controls, 8px of padding twice, and the 10px it holds above the title. */\n.ew-topbar-slot { flex: none; height: 70px; }\n/* Slides UP out of the pane, far enough to take its hairline with it. */\n.ew-topbar-hidden { transform: translateY(-115%); opacity: 0; pointer-events: none; }\n@media (prefers-reduced-motion: reduce) {\n  .ew-topbar-fixed { transition: none; }\n}\n.ew-tab {\n  flex: 1; display: flex; flex-direction: column; align-items: center;\n  justify-content: flex-end; gap: 3px; padding: 0 0 9px;\n  background: transparent; border: 0; cursor: pointer;\n  color: var(--muted, #8b8ea6); font: inherit; font-size: 10px; position: relative;\n}\n.ew-tab svg {\n  width: 21px; height: 21px; stroke: currentColor; fill: none;\n  stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round;\n}\n.ew-tab.on { color: var(--gold, #e5c07b); }\n.ew-tab.on::before {\n  content: \"\"; position: absolute; top: 8px; width: 26px; height: 2.5px;\n  border-radius: 2px; background: var(--gold, #e5c07b);\n}\n.ew-tablabel { line-height: 1; }\n.ew-tabdot {\n  position: absolute; top: 6px; right: calc(50% - 15px);\n  width: 7px; height: 7px; border-radius: 50%;\n  background: var(--gold, #e5c07b); box-shadow: 0 0 6px var(--gold, #e5c07b);\n}\n/* Overflow sheet for the 更多 tab. The bar is portalled to document.body, so the\n   scrim is fixed to the viewport (it must not extend the page or cover chrome\n   beyond the tap-to-close area). */\n.ew-tabmore-scrim {\n  position: fixed; inset: 0; z-index: 31; background: transparent; border: 0;\n}\n.ew-tabmore {\n  position: fixed; bottom: 66px; left: 0; right: 0; z-index: 32;\n  max-width: 900px; margin: 0 auto; width: calc(100% - 16px); padding: 6px;\n  /* Fixed dark, NOT theme vars: this sheet floats directly above the fixed-dark\n     tab bar, and following --panel/--border rendered it as a light box over a\n     dark bar under a light dashboard theme (same trap .ew-digest documents). */\n  background: rgba(6, 7, 14, .96); border: 1px solid rgba(255, 255, 255, .09);\n  border-radius: 14px; box-shadow: 0 14px 34px rgba(0, 0, 0, .55);\n  display: flex; flex-direction: column;\n}\n.ew-tabmore-item {\n  display: flex; align-items: center; gap: 10px; padding: 10px 12px;\n  /* Fixed light-on-dark: the sheet above is pinned dark, so a light theme's\n     --text (near-black) would vanish on it. */\n  background: transparent; border: 0; color: #e9e6df;\n  font: inherit; font-size: 13.5px; border-radius: 10px; cursor: pointer;\n  text-align: start;\n}\n.ew-tabmore-item svg {\n  width: 18px; height: 18px; stroke: currentColor; fill: none; stroke-width: 1.7;\n  stroke-linecap: round; stroke-linejoin: round;\n}\n.ew-tabmore-item.on { color: var(--gold, #e5c07b); }\n.ew-tabdot-inline {\n  width: 7px; height: 7px; border-radius: 50%; margin-inline-start: auto;\n  background: var(--gold, #e5c07b);\n}\n.ew-region-pane { display: flex; flex-direction: column; gap: 12px; margin-top: 8px; }\n/* World setting view (structured lore browser) on the world detail page. */\n.ew-setting-group { margin: 8px 0 2px; }\n.ew-setting-entry { border-bottom: 1px solid var(--border, #2d2f3d); }\n.ew-setting-head {\n  display: flex; gap: 8px; align-items: center; width: 100%; text-align: start;\n  background: transparent; border: 0; padding: 11px 8px; cursor: pointer;\n  color: var(--text, #e2e8f0); font: inherit; border-radius: 8px;\n  transition: background 0.12s ease; -webkit-tap-highlight-color: transparent;\n}\n/* hover only on real pointers — on touch, :hover is emulated on tap-down and would\n   light the row up before the finger lifts. */\n@media (hover: hover) {\n  .ew-setting-head:hover { background: var(--surface-2, rgba(255, 255, 255, 0.05)); }\n  .ew-setting-head:hover .ew-setting-name { color: var(--accent, #7c3aed); }\n}\n.ew-setting-head:focus-visible { outline: 2px solid var(--accent, #7c3aed); outline-offset: 2px; }\n.ew-setting-name { font-weight: 600; flex: 0 0 auto; }\n.ew-setting-sum {\n  color: var(--muted, #8b8ea6); font-size: 12.5px;\n  flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;\n}\n/* A chevron the reader can see is clickable: points right when closed, down when\n   open. Drawn from borders so it needs no icon font or emoji. */\n.ew-setting-caret {\n  margin-left: auto; flex: 0 0 auto; width: 7px; height: 7px; margin-inline-end: 2px;\n  border-right: 2px solid var(--muted, #8b8ea6); border-bottom: 2px solid var(--muted, #8b8ea6);\n  transform: rotate(-45deg); transition: transform 0.15s ease, border-color 0.12s ease;\n}\n.ew-setting-head[aria-expanded=\"true\"] .ew-setting-caret { transform: rotate(45deg); }\n@media (hover: hover) {\n  .ew-setting-head:hover .ew-setting-caret { border-color: var(--accent, #7c3aed); }\n}\n.ew-setting-body { padding: 0 8px 12px; }\n.ew-setting-rel { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }\n/* Starting-archetype (role) list on the world detail page. */\n.ew-role { display: flex; gap: 8px; align-items: baseline; padding: 8px 0; border-bottom: 1px solid var(--border, #2d2f3d); }\n.ew-role-name { font-weight: 600; flex: 0 0 auto; }\n.ew-role-sum { color: var(--muted, #8b8ea6); font-size: 12.5px; overflow-wrap: anywhere; }\n/* Desktop right-aside tab strip: switch which system region's panels show. */\n.ew-aside-tabs {\n  display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 10px;\n  border-bottom: 1px solid var(--border, #262a3e); padding-bottom: 8px;\n}\n.ew-aside-tab {\n  display: inline-flex; align-items: center; gap: 6px; position: relative;\n  background: transparent; border: 0; color: var(--muted, #8b8ea6);\n  font: inherit; font-size: 12.5px; padding: 5px 10px; border-radius: 8px; cursor: pointer;\n}\n.ew-aside-tab svg {\n  width: 15px; height: 15px; stroke: currentColor; fill: none;\n  stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round;\n}\n.ew-aside-tab.on {\n  color: var(--gold, #e5c07b);\n  background: color-mix(in oklab, var(--gold, #e5c07b) 14%, transparent);\n}\n.ew-aside-dot {\n  width: 6px; height: 6px; border-radius: 50%;\n  background: var(--gold, #e5c07b); box-shadow: 0 0 6px var(--gold, #e5c07b);\n}\n\n/* Kept at the end of the file: a @keyframes block's nested braces confuse the\n   naive CSS parser in the frontend contract tests, shifting the rule pairing for\n   everything after it. At EOF there is nothing after it to shift. */\n@keyframes ew-fateful-glow {\n  0%, 100% {\n    box-shadow:\n      inset 0 0 0 1px color-mix(in srgb, var(--accent, #7c3aed) 20%, transparent),\n      0 0 0 0 transparent;\n  }\n  50% {\n    box-shadow:\n      inset 0 0 0 1px color-mix(in srgb, var(--accent, #7c3aed) 34%, transparent),\n      0 0 12px 1px color-mix(in srgb, var(--accent, #7c3aed) 18%, transparent);\n  }\n}\n\n\n/* ── Choice-button runtime effects (narrator-declared, code-rendered) ──────\n   The narrator names one of shimmer|aura|embers|ripple on a choice; the tint\n   arrives as --fx-tint on the button (falls back to the theme accent). These\n   live HERE, not in narrator SVG, because the play page is dashboard DOM —\n   model bytes never carry style or script into it. Embers' canvas is mounted\n   by ChoiceEffect (effects.tsx); the rest are pure CSS. */\n\n.ew-fx { position: relative; overflow: hidden; isolation: isolate; }\n\n/* shimmer 流光: one specular band sweeping the button on a long period.\n   ::after so it never fights the ::before some themes use. */\n.ew-fx-shimmer::after {\n  content: '';\n  position: absolute;\n  inset: -40% -60%;\n  pointer-events: none;\n  background: linear-gradient(\n    105deg,\n    transparent 42%,\n    color-mix(in srgb, var(--fx-tint, var(--accent, #c9a227)) 34%, transparent) 50%,\n    transparent 58%\n  );\n  transform: translateX(-70%);\n  animation: ew-fx-shimmer 4.2s cubic-bezier(0.4, 0, 0.2, 1) infinite;\n}\n@keyframes ew-fx-shimmer {\n  0%   { transform: translateX(-70%); }\n  55%  { transform: translateX(70%); }\n  100% { transform: translateX(70%); }\n}\n\n/* aura 弥散: a breathing diffuse glow hugging the border, never the label. */\n.ew-fx-aura {\n  animation: ew-fx-aura 3.6s ease-in-out infinite;\n}\n@keyframes ew-fx-aura {\n  0%, 100% {\n    box-shadow:\n      0 0 6px 0 color-mix(in srgb, var(--fx-tint, var(--accent, #c9a227)) 24%, transparent),\n      inset 0 0 10px 0 color-mix(in srgb, var(--fx-tint, var(--accent, #c9a227)) 10%, transparent);\n  }\n  50% {\n    box-shadow:\n      0 0 18px 2px color-mix(in srgb, var(--fx-tint, var(--accent, #c9a227)) 42%, transparent),\n      inset 0 0 16px 0 color-mix(in srgb, var(--fx-tint, var(--accent, #c9a227)) 18%, transparent);\n  }\n}\n\n/* ripple 涟漪: two expanding rings born at the center, staggered half a period. */\n.ew-fx-ripple::before,\n.ew-fx-ripple::after {\n  content: '';\n  position: absolute;\n  left: 50%;\n  top: 50%;\n  width: 12px;\n  height: 12px;\n  margin: -6px 0 0 -6px;\n  border-radius: 999px;\n  border: 1px solid color-mix(in srgb, var(--fx-tint, var(--accent, #c9a227)) 55%, transparent);\n  pointer-events: none;\n  animation: ew-fx-ripple 3.8s ease-out infinite;\n}\n.ew-fx-ripple::after { animation-delay: 1.9s; }\n@keyframes ew-fx-ripple {\n  0%   { transform: scale(1); opacity: 0.7; }\n  85%  { transform: scale(16); opacity: 0; }\n  100% { transform: scale(16); opacity: 0; }\n}\n\n/* embers 粒子: the canvas ChoiceEffect mounts; drawing happens in JS. */\n.ew-fx-embers-canvas {\n  position: absolute;\n  inset: 0;\n  width: 100%;\n  height: 100%;\n  pointer-events: none;\n}\n\n@media (prefers-reduced-motion: reduce) {\n  .ew-fx-shimmer::after { animation: none; opacity: 0; }\n  .ew-fx-aura { animation: none; }\n  .ew-fx-ripple::before, .ew-fx-ripple::after { animation: none; opacity: 0; }\n  /* embers: ChoiceEffect checks the same query and mounts no canvas at all. */\n}\n\n/* Touch targets: several controls sit at 36px, under the 44px minimum. Raised\n   only for coarse pointers so desktop density is untouched; the visual glyph\n   size is unchanged (the extra room is hit area, not chrome). The pager arrows\n   matter most — they are the primary re-reading control. */\n@media (pointer: coarse) {\n  .ew-opt, .ew-rail-x, .ew-jump { min-height: 44px; }\n  .ew-pager-arw { width: 44px; height: 44px; }\n}\n";
//#endregion
//#region src/main.tsx
/** Where the player was, so leaving the page does not throw them back to the
*  shelf. Prefixed because this app mounts inside the dashboard's own document
*  and shares its localStorage. */
var WHERE = "endless-worlds:where";
/** The player's standing UI-language pick from the header dropdown. Prefixed and
*  shared with the dashboard document like every other key this app keeps. */
var LANG_KEY = "endless-worlds:lang";
/** The reader's standing choice of reading measure. A preference, not a per-world
*  fact, so it is kept here rather than asked of the backend. */
var WIDTH_KEY = "endless-worlds:width";
var RAIL_KEY = "endless-worlds:rail";
/** The FIRST-RUN default UI language: follow the Crew, fall back to English.
*
*  KiroCrew's LanguageProvider sets `<html lang>` to the resolved dashboard
*  language, and this app mounts into that same document, so `documentElement.lang`
*  is the Crew's OWN UI language rather than the raw browser locale;
*  `navigator.language` is only a standalone/dev fallback. This app ships zh + en,
*  so any Crew language it has no table for falls to English. A remembered explicit
*  pick and world-follow both still override this default. */
function crewLanguageDefault() {
	return asLang((document.documentElement.lang || navigator.language || "").slice(0, 2).toLowerCase()) ?? "en";
}
var ORDER_KEY = "ew-shelf-order";
var rememberOrder = (order) => {
	try {
		localStorage.setItem(ORDER_KEY, order);
	} catch {}
};
var recallOrder = () => {
	try {
		return localStorage.getItem(ORDER_KEY) === "started" ? "started" : "recent";
	} catch {
		return "recent";
	}
};
/** Order a shelf group. `createdAt` is absent on rows written before it existed,
*  so `lastPlayed` stands in — that orders such a row no worse than it was
*  ordered before, and never drops it. */
var byOrder = (rows, order) => [...rows].sort((a, b) => order === "started" ? (a.createdAt ?? a.lastPlayed ?? 0) - (b.createdAt ?? b.lastPlayed ?? 0) : (b.lastPlayed ?? 0) - (a.lastPlayed ?? 0));
var remember = (where) => {
	try {
		localStorage.setItem(WHERE, JSON.stringify(where));
	} catch {}
};
var recall = () => {
	try {
		return JSON.parse(localStorage.getItem(WHERE) ?? "null");
	} catch {
		return null;
	}
};
var forget = () => {
	try {
		localStorage.removeItem(WHERE);
	} catch {}
};
function EndlessWorlds() {
	const [worlds, setWorlds] = useState(null);
	const [seeds, setSeeds] = useState(null);
	const [runs, setRuns] = useState([]);
	const [error, setError] = useState(null);
	/** World drafts being built from pasted text — shown as cards in the worlds
	*  section, polled to completion, then reviewed and installed. */
	const [drafts, setDrafts] = useState([]);
	/** The draft open in the review screen (view === 'draft'). */
	const [reviewDraft, setReviewDraft] = useState(null);
	const [view, setView] = useState("library");
	const [showSettings, setShowSettings] = useState(false);
	/** The shelf. Remembered across loads and OPEN by default so the landing shows
	*  the lives in it; the reader can close it for more reading room (the story
	*  then owns the full width) and reopen it, and the choice sticks. */
	const [railOpen, setRailOpen] = useState(() => {
		try {
			return localStorage.getItem(RAIL_KEY) !== "closed";
		} catch {
			return true;
		}
	});
	const toggleRail = useCallback(() => {
		setRailOpen((o) => {
			const next = !o;
			try {
				localStorage.setItem(RAIL_KEY, next ? "open" : "closed");
			} catch {}
			return next;
		});
	}, []);
	const [readWidth, setReadWidth] = useState(() => localStorage.getItem(WIDTH_KEY) === "fixed" ? "fixed" : "fluid");
	const chooseWidth = useCallback((next) => {
		try {
			localStorage.setItem(WIDTH_KEY, next);
		} catch {}
		setReadWidth(next);
	}, []);
	const rootRef = useRef(null);
	useEffect(() => {
		rootRef.current?.scrollIntoView({ block: "start" });
	}, [view]);
	const [selected, setSelected] = useState(null);
	const [world, setWorld] = useState(null);
	const [live, setLive] = useState(null);
	const [scenes, setScenes] = useState([]);
	const [panels, setPanels] = useState([]);
	const [backdrop, setBackdrop] = useState(null);
	const [isNarrow, setIsNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(max-width: 1100px)").matches : false);
	const [tab, setTab] = useState("reading");
	/** Whether a sheet in the play column (star map, legacy picker) is open.
	*
	*  The mounted scene frames render HERE, outside that column, because
	*  re-parenting an iframe reloads it — so a sheet anchored to the column cannot
	*  cover them and they would otherwise stay on the page underneath it. Held as
	*  state rather than derived, since only the play column knows its own sheets. */
	const [sheetOpen, setSheetOpen] = useState(false);
	const [liveTurn, setLiveTurn] = useState(0);
	/** tabId → the content signature last seen, so a tab dots only on an UNSEEN
	*  change. A ref (not state) because it is bookkeeping, not render input. */
	const seenRef = useRef({});
	const [refresh, setRefresh] = useState(0);
	/** ONE turn in flight at a time, across every surface that can start one — a
	*  scene answer, a choice tap, the act box. Scene answers dispatch from here
	*  (not PlayPage), so without a hoisted lock the play page's own `busy` never
	*  learns a scene already fired and a player can start two concurrent turns. */
	const [turnPending, setTurnPending] = useState(false);
	const turnPendingRef = useRef(false);
	/** Bumped whenever a scene answer resolves without changing scene html, so
	*  every SceneSlot clears its local answered/sending state (a refused answer
	*  otherwise locks its slot on "sending…" forever). */
	const [sceneEpoch, setSceneEpoch] = useState(0);
	/** Which world's deletion is being confirmed, or null. Held here rather than in
	*  the detail view because the reload that follows a deletion unmounts that
	*  view — a dialog owned by it would vanish mid-request. */
	const [doomed, setDoomed] = useState(null);
	/** Which life's deletion is being confirmed, or null. */
	const [note, setNote] = useState("");
	const [lang, setLangState] = useState(() => asLang(localStorage.getItem(LANG_KEY) ?? void 0) ?? crewLanguageDefault());
	const [langLocked, setLangLocked] = useState(() => localStorage.getItem(LANG_KEY) != null);
	setCurrentLanguage(lang);
	const applyLanguage = useCallback((code) => {
		if (langLocked) return;
		const next = asLang(code);
		if (next) setLangState(next);
	}, [langLocked]);
	const chooseLanguage = useCallback((code) => {
		const next = asLang(code);
		if (!next) return;
		localStorage.setItem(LANG_KEY, next);
		setLangLocked(true);
		setLangState(next);
	}, []);
	const load = useCallback(async () => {
		setError(null);
		try {
			const d = await api.worlds(lang);
			setWorlds(d.worlds);
			setSeeds(d.seeds);
		} catch (e) {
			setError(e.message);
		}
		try {
			setRuns((await api.runs()).runs);
		} catch {
			setRuns([]);
		}
		try {
			setDrafts((await api.worldDrafts()).drafts);
		} catch {
			setDrafts([]);
		}
	}, [lang]);
	useEffect(() => {
		load();
	}, [load]);
	useEffect(() => {
		if (!drafts.some((d) => d.status === "generating" || d.status === "new")) return;
		const timer = window.setInterval(() => {
			load();
		}, DRAFT_POLL_MS);
		return () => window.clearInterval(timer);
	}, [drafts, load]);
	useEffect(() => {
		if (!worlds) return;
		const live = new Set(worlds.map((w) => w.worldId));
		try {
			for (let i = localStorage.length - 1; i >= 0; i -= 1) {
				const key = localStorage.key(i);
				if (key && key.startsWith("endless-worlds:where:draft:") && !live.has(key.slice(27))) localStorage.removeItem(key);
			}
		} catch {}
	}, [worlds]);
	useEffect(() => {
		const where = recall();
		if (!where) return;
		if (where.view === "live" && where.runId) {
			const rid = where.runId;
			api.run(rid).then((v) => {
				applyLanguage(v.language);
				setLive(rid);
				setView("live");
			}).catch(() => {
				forget();
			});
			return;
		}
		if (where.view === "detail" && where.worldId) {
			const wid = where.worldId;
			api.world(wid).then((w) => {
				applyLanguage(w.language);
				setSelected(wid);
				setView("detail");
			}).catch(() => {
				forget();
			});
			return;
		}
		if (where.view === "opening" && where.worldId) {
			api.world(where.worldId).then((w) => {
				applyLanguage(w.language);
				setWorld(w);
				setView("opening");
			}).catch(() => {
				forget();
			});
			return;
		}
		if (where.view === "create") {
			setView("create");
			return;
		}
		if (where.view === "draft" && where.draftId) {
			const did = where.draftId;
			api.worldDraft(did).then(() => {
				setReviewDraft(did);
				setView("draft");
			}).catch(() => {
				forget();
			});
		}
	}, [applyLanguage]);
	const prevViewRef = useRef("library");
	const homeRef = useRef(() => {});
	useEffect(() => {
		const prev = prevViewRef.current;
		prevViewRef.current = view;
		if (prev === "library" && view !== "library") try {
			window.history.pushState({ ew: "subview" }, "");
		} catch {}
	}, [view]);
	useEffect(() => {
		const onPop = () => {
			homeRef.current();
		};
		window.addEventListener("popstate", onPop);
		return () => window.removeEventListener("popstate", onPop);
	}, []);
	const home = () => {
		forget();
		setView("library");
		setSelected(null);
		setWorld(null);
		setLive(null);
		setScenes([]);
		setReviewDraft(null);
		load();
	};
	homeRef.current = home;
	const startCreate = () => {
		remember({ view: "create" });
		setView("create");
	};
	const openDraft = (draftId) => {
		remember({
			view: "draft",
			draftId
		});
		setReviewDraft(draftId);
		setView("draft");
	};
	/** After submitting the paste, go straight to the review screen — it shows the
	*  worldsmith's progress and then the result; leaving it drops back to the shelf
	*  where the draft card keeps polling. */
	const draftCreated = (draftId) => {
		load();
		openDraft(draftId);
	};
	const backToShelf = () => {
		remember({ view: "library" });
		setView("library");
		setReviewDraft(null);
		load();
	};
	const draftInstalled = () => {
		home();
	};
	const discardDraftInline = (draftId) => {
		api.discardWorldDraft(draftId).then(() => void load()).catch(() => void load());
	};
	const enterLife = (runId) => {
		remember({
			view: "live",
			runId
		});
		setLive(runId);
		setView("live");
	};
	const restartSameOpening = async (fromRunId) => {
		try {
			const created = await api.createRun({ fromRunId });
			api.openRun(created.runId);
			setScenes([]);
			enterLife(created.runId);
		} catch {}
	};
	/**
	* After a world is gone.
	*
	* Landing back on the shelf is not decoration: the detail view the player was
	* standing in now describes a world that would answer 404, and the remembered
	* screen would send them straight back to it on the next visit. `home()` clears
	* both.
	*/
	const afterDelete = (out) => {
		setDoomed(null);
		setNote((out.lives ? t(out.lives === 1 ? "delete.doneWithLivesOne" : "delete.doneWithLives", { n: out.lives }) : t("delete.done")) + (out.restorable ? " " + t("delete.doneRestorable") : ""));
		home();
	};
	/**
	* After a life is gone.
	*
	* If the player was standing in it, staying would leave the play page polling a
	* life that answers 404. The shelf is the only honest landing.
	*/
	const afterLifeDelete = (turn) => {
		setNote(turn > 0 ? t(turn === 1 ? "life.delete.doneOne" : "life.delete.done", { n: turn }) : t("life.delete.doneUnborn"));
		home();
	};
	const restore = async (worldId) => {
		setNote("");
		try {
			await api.restoreWorld(worldId);
		} catch (e) {
			setNote(e.message);
			return;
		}
		await load();
	};
	/**
	* Opening a world from the rail.
	*
	* This is the reason the single-value `view` had to give a little ground. The
	* rail and the main column are two axes now, so "which world is selected" and
	* "what is being read" are separate facts: clicking a world while a life is open
	* must leave the rail's highlight somewhere honest, which means clearing `live`
	* rather than letting two rows read as current at once.
	*/
	const openWorld = (worldId) => {
		setLive(null);
		setScenes([]);
		setWorld(null);
		setSelected(worldId);
		setView("detail");
		remember({
			view: "detail",
			worldId
		});
	};
	/**
	* What the player did in a scene becomes the turn's action — the same road a
	* tapped choice or a typed sentence takes, so a scene is a way of asking rather
	* than a second kind of move.
	*/
	const onSceneChoice = useCallback(async (sceneId, choice, nonce) => {
		if (!live) return;
		if (turnPendingRef.current) return;
		turnPendingRef.current = true;
		setTurnPending(true);
		try {
			const out = await api.answerScene(live, sceneId, {
				choice,
				nonce
			});
			if (out.accepted) await api.takeTurn(live, { action: out.action });
		} catch {} finally {
			turnPendingRef.current = false;
			setTurnPending(false);
			setSceneEpoch((n) => n + 1);
			setRefresh((n) => n + 1);
		}
	}, [live]);
	const changeLifeMeta = useCallback(async (runId, changes) => {
		try {
			await api.setLifeMeta(runId, changes);
		} catch {}
		load();
	}, [load]);
	const renameLife = useCallback((runId, label) => {
		changeLifeMeta(runId, { label });
	}, [changeLifeMeta]);
	const archiveLife = useCallback((runId, archived) => {
		changeLifeMeta(runId, { archived });
	}, [changeLifeMeta]);
	const [showArchived, setShowArchived] = useState(false);
	const [order, setOrder] = useState(recallOrder);
	useEffect(() => {
		if (typeof window === "undefined" || !window.matchMedia) return void 0;
		const mq = window.matchMedia("(max-width: 1100px)");
		const on = () => setIsNarrow(mq.matches);
		on();
		mq.addEventListener?.("change", on);
		return () => mq.removeEventListener?.("change", on);
	}, []);
	useEffect(() => {
		setTab("reading");
		setSheetOpen(false);
	}, [live]);
	const tabs = useMemo(() => buildTabs(scenes, panels), [scenes, panels]);
	const narrowLive = isNarrow && view === "live" && !!live;
	const barHidden = useScrollHide(narrowLive, 70);
	useEffect(() => {
		if (narrowLive && !tabs.some((tb) => tb.id === tab)) setTab("reading");
	}, [
		tabs,
		tab,
		narrowLive
	]);
	const sigOf = useCallback((id, sceneIds) => {
		if (id === "reading") return `r${liveTurn}`;
		if (id === "starmap") return "s";
		const sc = sceneIds.map((sid) => {
			const s = scenes.find((x) => x.sceneId === sid);
			return [
				sid,
				s?.asks ?? false,
				s?.answered ?? false
			];
		});
		const pn = panels.filter((p) => (p.region ?? "") === id).map((p) => [p.id, JSON.stringify(p.fields)]);
		return JSON.stringify([sc, pn]);
	}, [
		scenes,
		panels,
		liveTurn
	]);
	const dots = {};
	for (const tb of tabs) {
		const sig = sigOf(tb.id, tb.sceneIds);
		if (seenRef.current[tb.id] === void 0) seenRef.current[tb.id] = sig;
		dots[tb.id] = tb.id !== tab && tb.id !== "starmap" && seenRef.current[tb.id] !== sig;
	}
	useEffect(() => {
		const tb = tabs.find((x) => x.id === tab);
		if (tb) seenRef.current[tab] = sigOf(tab, tb.sceneIds);
	}, [
		tab,
		tabs,
		sigOf
	]);
	const activeSceneIds = tabs.find((tb) => tb.id === tab)?.sceneIds ?? [];
	const hideBody = narrowLive && tab !== "reading" && tab !== "starmap";
	/** Whether a scene frame is actually on screen below the shell. The phone's
	*  tab-bar clearance belongs to whatever the page ENDS with: when frames follow
	*  the region pane, padding the pane only opens a gap between the panels and the
	*  map, and leaves the last frame under the bar. */
	const scenesShown = narrowLive && activeSceneIds.length > 0;
	let body;
	if (view === "live" && live) body = /* @__PURE__ */ jsx(PlayPage, {
		runId: live,
		onBack: home,
		onScenes: setScenes,
		onBackdrop: setBackdrop,
		onReplay: openWorld,
		onReplaySame: restartSameOpening,
		onEnterLife: enterLife,
		refresh,
		openStar: narrowLive ? tab === "starmap" : void 0,
		onStarClose: () => setTab("reading"),
		onSheetOpen: setSheetOpen,
		onLiveTurn: setLiveTurn,
		narrow: narrowLive,
		readerBar: narrowLive && !hideBody,
		onPanels: setPanels,
		turnPending
	});
	else if (view === "opening" && world) body = /* @__PURE__ */ jsx(OpeningScreen, {
		world,
		onBack: home,
		onLive: enterLife
	});
	else if (view === "create") body = /* @__PURE__ */ jsx(CreateWorldScreen, {
		onCancel: backToShelf,
		onCreated: draftCreated
	});
	else if (view === "draft" && reviewDraft) body = /* @__PURE__ */ jsx(WorldDraftReview, {
		draftId: reviewDraft,
		onInstalled: draftInstalled,
		onDiscarded: backToShelf,
		onBack: backToShelf
	});
	else if (selected) body = /* @__PURE__ */ jsx(WorldDetailView, {
		worldId: selected,
		onBack: home,
		onDelete: setDoomed,
		initialLanguage: lang,
		onLanguage: applyLanguage,
		onPlay: (w) => {
			remember({
				view: "opening",
				worldId: w.worldId
			});
			applyLanguage(w.language);
			setWorld(w);
			setView("opening");
		}
	});
	else if (error) body = /* @__PURE__ */ jsxs("div", {
		className: "ew-meta",
		children: [
			/* @__PURE__ */ jsx("div", {
				style: { marginBottom: "6px" },
				children: t("library.backendSilent")
			}),
			/* @__PURE__ */ jsx("div", { children: t("library.backendHint", {
				path: "/worlds",
				error
			}) }),
			/* @__PURE__ */ jsx("div", {
				className: "ew-bar",
				children: /* @__PURE__ */ jsx("button", {
					className: "ew-btn",
					type: "button",
					onClick: () => void load(),
					children: t("library.retry")
				})
			})
		]
	});
	else if (!worlds) body = /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("library.preparing")
	});
	else {
		const active = byOrder(runs.filter((r) => !r.archived && !r.ended), order);
		const endedRuns = byOrder(runs.filter((r) => !r.archived && r.ended), order);
		const archivedRuns = byOrder(runs.filter((r) => r.archived), order);
		const newest = active.find((r) => !r.unreadable);
		const rowProps = {
			onOpen: enterLife,
			onDeleted: afterLifeDelete,
			onRename: renameLife,
			onArchive: archiveLife
		};
		body = /* @__PURE__ */ jsxs(Fragment, { children: [
			newest ? /* @__PURE__ */ jsxs("div", {
				className: "ew-onlywide ew-cont-wrap",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-section",
					children: t("shelf.continue")
				}), /* @__PURE__ */ jsx(LifeRow, {
					run: newest,
					onOpen: enterLife
				})]
			}) : /* @__PURE__ */ jsx("div", {
				className: "ew-onlywide ew-meta",
				children: t("shelf.pick")
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ew-shelflist ew-shelf-lives",
				children: [
					active.length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsxs("div", {
						className: "ew-section-row",
						children: [/* @__PURE__ */ jsx("div", {
							className: "ew-section",
							children: t("library.lives")
						}), /* @__PURE__ */ jsx("button", {
							className: "ew-order-toggle",
							type: "button",
							onClick: () => {
								const next = order === "recent" ? "started" : "recent";
								setOrder(next);
								rememberOrder(next);
							},
							children: t(order === "recent" ? "shelf.orderRecent" : "shelf.orderStarted")
						})]
					}), active.map((r) => /* @__PURE__ */ jsx(LifeRow, {
						run: r,
						...rowProps
					}, r.runId))] }) : null,
					endedRuns.length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("div", {
						className: "ew-section",
						style: { marginTop: "22px" },
						children: t("shelf.ended")
					}), endedRuns.map((r) => /* @__PURE__ */ jsx(LifeRow, {
						run: r,
						...rowProps
					}, r.runId))] }) : null,
					archivedRuns.length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("button", {
						className: "ew-section ew-section-toggle",
						type: "button",
						style: { marginTop: "22px" },
						onClick: () => setShowArchived((s) => !s),
						"aria-expanded": showArchived,
						children: t("shelf.archived", { n: archivedRuns.length })
					}), showArchived ? archivedRuns.map((r) => /* @__PURE__ */ jsx(LifeRow, {
						run: r,
						...rowProps
					}, r.runId)) : null] }) : null
				]
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ew-shelflist ew-shelf-worlds",
				children: [
					runs.length ? /* @__PURE__ */ jsx("div", {
						className: "ew-section",
						children: t("library.otherWorlds")
					}) : null,
					/* @__PURE__ */ jsx(CreateWorldCard, { onClick: startCreate }),
					drafts.map((d) => /* @__PURE__ */ jsx(WorldDraftCard, {
						draft: d,
						onOpen: openDraft,
						onDiscard: discardDraftInline
					}, d.draftId)),
					worlds.length === 0 ? /* @__PURE__ */ jsx("div", {
						className: "ew-meta",
						children: t("library.empty")
					}) : worlds.map((w) => /* @__PURE__ */ jsx(WorldCard, {
						world: w,
						onOpen: openWorld,
						plays: runs.filter((r) => r.worldId === w.worldId).length
					}, w.worldId))
				]
			}),
			(seeds?.newerAvailable ?? []).map((n) => /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: t("library.newerSeed", {
					world: n.worldId,
					installed: n.installed,
					available: n.available
				})
			}, n.worldId)),
			(seeds?.removed ?? []).map((id) => /* @__PURE__ */ jsxs("div", {
				className: "ew-note ew-note-row",
				children: [/* @__PURE__ */ jsx("span", { children: t("library.removed", { world: id }) }), /* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-quiet",
					type: "button",
					onClick: () => void restore(id),
					children: t("library.restore")
				})]
			}, "removed-" + id))
		] });
	}
	const viewClass = "ew-root ew-view-" + view;
	const widthClass = " ew-w-" + readWidth;
	const rootClass = viewClass + (narrowLive ? " ew-root-flushtop" : "") + widthClass + (view === "library" ? " ew-home" : "");
	return /* @__PURE__ */ jsx(LanguageContext.Provider, {
		value: applyLanguage,
		children: /* @__PURE__ */ jsxs("div", {
			className: rootClass,
			lang,
			ref: rootRef,
			children: [
				/* @__PURE__ */ jsx("style", { children: styles_default }),
				view === "live" && live && backdrop ? /* @__PURE__ */ jsx(Backdrop, {
					runId: live,
					version: backdrop.version,
					turn: backdrop.turn,
					mobile: backdrop.mobile
				}) : null,
				narrowLive ? null : /* @__PURE__ */ jsxs("div", {
					className: "ew-head",
					children: [
						/* @__PURE__ */ jsx(Glyph, {}),
						/* @__PURE__ */ jsx("h2", { children: t("app.title") }),
						view === "library" ? /* @__PURE__ */ jsxs("div", {
							className: "ew-headtools",
							children: [/* @__PURE__ */ jsxs("select", {
								className: "ew-uilang",
								"aria-label": t("app.language"),
								value: lang,
								onChange: (e) => chooseLanguage(e.target.value),
								children: [/* @__PURE__ */ jsx("option", {
									value: "zh",
									children: "中文"
								}), /* @__PURE__ */ jsx("option", {
									value: "en",
									children: "English"
								})]
							}), /* @__PURE__ */ jsx("button", {
								className: "ew-uilang",
								type: "button",
								onClick: () => setShowSettings((s) => !s),
								"aria-expanded": showSettings,
								children: t("settings.open")
							})]
						}) : null
					]
				}),
				view === "library" ? /* @__PURE__ */ jsx("div", {
					className: "ew-tagline",
					children: t("app.tagline")
				}) : null,
				view === "library" && showSettings ? /* @__PURE__ */ jsx(SettingsPanel, { onClose: () => setShowSettings(false) }) : null,
				note ? /* @__PURE__ */ jsxs("div", {
					className: "ew-note ew-note-row",
					children: [/* @__PURE__ */ jsx("span", { children: note }), /* @__PURE__ */ jsx("button", {
						className: "ew-btn ew-btn-quiet",
						type: "button",
						onClick: () => setNote(""),
						children: t("note.dismiss")
					})]
				}) : null,
				/* @__PURE__ */ jsxs("div", {
					className: "ew-shell" + (railOpen ? " ew-shell-open" : ""),
					children: [/* @__PURE__ */ jsx(WorldRail, {
						worlds,
						runs,
						activeRunId: live,
						activeWorldId: world?.worldId ?? selected,
						onWorld: openWorld,
						onLife: enterLife,
						onHome: home,
						atShelf: view === "library",
						open: railOpen,
						onClose: toggleRail,
						width: readWidth,
						onWidth: chooseWidth
					}), /* @__PURE__ */ jsxs("div", {
						className: "ew-main",
						children: [
							/* @__PURE__ */ jsx("button", {
								className: "ew-shelfbtn",
								type: "button",
								"aria-expanded": railOpen,
								onClick: toggleRail,
								children: t("rail.open")
							}),
							/* @__PURE__ */ jsx("div", {
								className: "ew-bodywrap",
								style: {
									display: hideBody ? "none" : void 0,
									paddingBottom: narrowLive ? "72px" : void 0
								},
								children: body
							}),
							view === "library" && !hideBody ? /* @__PURE__ */ jsx("div", {
								className: "ew-version",
								children: t("app.version", { version: "0.7.0" })
							}) : null,
							hideBody ? /* @__PURE__ */ jsx("div", {
								className: "ew-region-pane",
								style: { paddingBottom: scenesShown ? void 0 : "72px" },
								children: panels.filter((p) => (p.region ?? "") === tab).map((p) => /* @__PURE__ */ jsx(PanelBox, { panel: p }, p.id))
							}) : null
						]
					})]
				}),
				live ? /* @__PURE__ */ jsx("div", {
					className: scenesShown ? "ew-scenes-clear" : void 0,
					children: scenes.map((s) => /* @__PURE__ */ jsx(SceneSlot, {
						runId: live,
						sceneId: s.sceneId,
						asks: s.asks,
						visible: !sheetOpen && (!narrowLive || activeSceneIds.includes(s.sceneId)),
						onChoice: onSceneChoice,
						resetSignal: sceneEpoch,
						locked: turnPending
					}, s.sceneId))
				}) : null,
				doomed ? /* @__PURE__ */ jsx(DeleteWorldDialog, {
					worldId: doomed,
					onCancel: () => setDoomed(null),
					onDeleted: afterDelete
				}) : null,
				narrowLive ? /* @__PURE__ */ jsx(WorldTabBar, {
					tabs,
					active: tab,
					dots,
					hidden: barHidden,
					onSelect: setTab
				}) : null
			]
		})
	});
}
//#endregion
export { EndlessWorlds as default };
