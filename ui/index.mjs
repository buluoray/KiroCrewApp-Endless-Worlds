import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
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
* A failed request, with the server's own answer kept.
*
* The previous helper threw `new Error('HTTP 409')` and dropped the body, which is
* fine while every failure is just "it did not work". Deletion is not: its 409s
* carry the reason (the lives changed under you / a month is being written) and the
* refreshed facts the dialog has to re-render. A code the UI cannot read is a
* message the player never gets.
*/
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
	/** The gateway's advertised model list (same-origin dashboard endpoint, not the
	*  app base). Returns [] rather than throwing when the list is unavailable
	*  (signed out / gateway restart), so the picker degrades to "keep default". */
	models: async () => {
		try {
			const res = await fetch("/api/models");
			if (!res.ok) return [];
			const raw = await res.json();
			return (Array.isArray(raw) ? raw : []).map((m) => typeof m === "string" ? { id: m } : m).filter((m) => m && typeof m.id === "string" && m.id);
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
	restoreWorld: (id) => post(`/worlds/${encodeURIComponent(id)}/restore`, {}),
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
	openRun: (id) => post(`/runs/${encodeURIComponent(id)}/open`, {}),
	takeTurn: (id, body) => post(`/runs/${encodeURIComponent(id)}/turn`, body),
	scene: async (runId, sceneId) => {
		const res = await fetch(`${API}/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}`);
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
		"app.language": "界面语言",
		"settings.open": "设置",
		"settings.title": "叙事者设置",
		"settings.close": "关闭",
		"settings.model": "模型",
		"settings.modelDefault": "默认（auto）",
		"settings.effort": "推理强度",
		"settings.effortDefault": "默认",
		"settings.save": "保存",
		"settings.saved": "已保存",
		"settings.note": "在每条人生的下一回合生效（包括进行中的那条）。",
		"delete.cancel": "不删了",
		"delete.changed": "这次没有删掉：这个世界里的人生数目变了。请重新看一遍再决定。",
		"delete.counting": "正在数这个世界里有几条人生…",
		"delete.done": "世界已删除。",
		"delete.doneRestorable": "以后还能把它装回书架。",
		"delete.doneWithLives": "世界已删除，连同 {n} 条人生。",
		"delete.forever": "这个世界不是应用自带的，删掉就找不回来了。",
		"delete.go": "删除世界，连同 {n} 条人生",
		"delete.goNoLives": "删除这个世界",
		"delete.inFlight": "这次没有删掉：这个世界还有一个回合没写完。等写完再试一次。",
		"delete.noLives": "这个世界里还没有人活过。删掉它，书架上就没有它了。",
		"delete.restorable": "这个世界是应用自带的，删掉之后还能装回来——但装回来的是出厂的样子，你改过的地方回不来，已经消失的人生也不会回来。",
		"delete.title": "删除「{world}」？",
		"delete.typeToConfirm": "继续之前，请把世界的名字打一遍：{world}",
		"delete.withLives": "这个世界里有 {n} 条人生。删掉它，这些人生连同它们已经写下的一切一起消失。",
		"delete.working": "正在删除…",
		"history.beginning": "已经到这条人生的开头了。",
		"history.chose": "当时你选了：{action}",
		"history.close": "收起前面的回合",
		"history.earlier": "再往前",
		"history.eventsOnly": "只看大事",
		"history.jump": "跳转",
		"history.jumpPlaceholder": "跳到第几回合",
		"history.noEvents": "这条人生还没有标记出大事。",
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
		"library.backendHint": "{path} → {error}。404 说明后端模块没有加载，需要把模块停用再启用一次。",
		"library.backendSilent": "后端还没有响应。",
		"library.empty": "书架还是空的。第一个世界，正等你推门。",
		"library.lives": "你正在过的人生",
		"library.newerSeed": "「{world}」有更新的版本（{installed} → {available}）。你手上这份不变。",
		"library.otherWorlds": "别的世界",
		"library.preparing": "书架正在打开…",
		"library.removed": "「{world}」已被你移除。",
		"library.restore": "装回书架",
		"library.retry": "重试",
		"life.archive": "归档",
		"life.delete.aria": "删除人生：{name}",
		"life.delete.changed": "这条人生在别处又往前走了一个回合，回合数变了。请重新看一遍再决定。",
		"life.delete.done": "人生已删除（活了 {n} 个回合）。",
		"life.delete.doneUnborn": "那条还没出生的人生已删除。",
		"life.delete.forever": "它的世界会留下，别的人生也不受影响。但这条人生再也找不回来——它的编年史只有这一份，没有别的副本。",
		"life.delete.go": "结束这条人生",
		"life.delete.inFlight": "这次没有删掉：这条人生还有一个回合没写完。等写完再试一次。",
		"life.delete.months": "「{name}」已经活了 {n} 个回合。删掉它，这些回合写下的一切都会消失。",
		"life.delete.reading": "正在看这条人生走到了哪一页…",
		"life.delete.short": "删除",
		"life.actions": "{name} 的操作",
		"life.delete.title": "结束这条人生？",
		"life.delete.typeToConfirm": "继续之前，请把这条人生的名字打一遍：{name}",
		"life.delete.unborn": "「{name}」还没有出生。删掉它，你留下的开局设定也一起没有。",
		"life.delete.unreadable": "这条人生已经读不出来了。它打不开，所以只能从这里删掉。",
		"life.ended": "已落幕",
		"life.generating": "这一页正在写…",
		"life.rename.aria": "重命名人生：{name}",
		"life.rename.cancel": "取消",
		"life.rename.placeholder": "给这条人生起个名字",
		"life.rename.save": "保存",
		"life.rename.short": "重命名",
		"life.turn": "第 {turn} 回合",
		"life.unarchive": "取消归档",
		"life.unborn": "序章还没开始",
		"life.unreadable": "这一世读不出来了",
		"life.waiting": "等你继续",
		"note.dismiss": "知道了",
		"opening.arranging": "这一世的序章正在展开。",
		"opening.backToShelf": "回到书架",
		"opening.begin": "开始这一世",
		"opening.beginning": "正在翻开序章…",
		"opening.continueBirth": "接着出生",
		"opening.custom": "自定义…",
		"opening.customPlaceholder": "写下你自己的",
		"opening.hintPick": "挑一个，或者留空让世界替你决定。",
		"opening.hintText": "留空则由世界决定。",
		"opening.keptSafe": "你选的一切都还在。",
		"opening.next": "下一页",
		"opening.notStarted": "序章还没有开始。你留下的选择都好好收着。",
		"opening.page": "第 {page} / {pages} 页",
		"opening.prev": "上一页",
		"opening.reset": "全部重置",
		"opening.restored": "已恢复你上次的选择。",
		"opening.retry": "再试一次",
		"opening.rollAll": "全部随机",
		"opening.rollOne": "随机 {label}",
		"opening.sealed": "这一项由世界定下，不由你选。等你出生时才会知道。",
		"opening.silent": "这一世没能开始。",
		"opening.styleHint": "决定这个世界会怎样对待你。",
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
		"play.actionPlaceholder": "或者，做点别的。",
		"play.back": "← 回到书架",
		"play.birthRevealHint": "这不是你的选择，却会成为这条人生的一部分。",
		"play.birthRevealTitle": "出生时，世界替你决定了",
		"play.confirmAct": "按你写的去做？",
		"play.confirmAsk": "就这么做？",
		"play.confirmNo": "再想想",
		"play.confirmYes": "就这么做",
		"play.drawerClose": "收起",
		"play.drawerOpen": "看看这一刻的自己",
		"play.endedBadge": "这一生落幕了。",
		"play.endedMeta": "这一生走过了 {turn} 个回合。",
		"play.endedReplay": "在这个世界再活一次",
		"play.endedReplaySame": "以同样的开局再活一次",
		"play.endedShelf": "回到书架",
		"play.echoLine": "往事回响 · 这回应了第 {turn} 页发生的事",
		"play.echoThen": "当时",
		"play.echoYouDid": "你当时的选择",
		"play.echoNow": "此刻",
		"play.echoJump": "回到那一页",
		"play.echoClose": "收起",
		"play.generating": "下一页正在落笔。放心离开，归来时故事还在这里。",
		"play.nothingToShow": "这一刻还没有什么可看的——有些面板要等条件满足了才会出现。",
		"play.opening": "正在翻到你留下的那一页…",
		"play.retry": "再试一次",
		"play.rumour": "传闻",
		"play.rumourSuffix": " —— 只是听说",
		"play.sceneFailed": "这一幕没能画出来。",
		"play.sceneLoading": "这一幕正在画…",
		"play.sceneTitle": "景象",
		"play.silent": "（这一页还没有内容。）",
		"play.stalled": "这一页没有写出来。你写的内容还留着，再试一次。",
		"play.turn": "第 {turn} 回合",
		"play.page": "第 {n} 页",
		"play.prevTurn": "上一回合",
		"play.recapDismiss": "先收起",
		"play.recapLastChoice": "你上次选择：",
		"play.recapNow": "眼前仍可走的方向",
		"play.recapRecent": "最近留下的痕迹",
		"play.recapTitle": "回来时，这条人生正停在这里",
		"play.nextTurn": "下一回合",
		"play.unlocked": "新篇已启：{heading}",
		"play.unlockedMeaning": "从现在起，与这一篇有关的人物、规则和后果，真正进入了这条人生。",
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
		"play.zoomIn": "展开",
		"play.zoomOut": "收起",
		"rail.broken": "另有 {n} 个世界读不出来",
		"rail.label": "世界与人生",
		"rail.shelf": "← 回到书架",
		"rail.styles": "{n} 种风格",
		"rail.worlds": "世界",
		"shelf.archived": "已归档（{n}）",
		"shelf.continue": "接着过下去",
		"shelf.ended": "已落幕的人生",
		"shelf.pick": "从左边挑一条人生，或者开一个世界。",
		"unit.day": "日",
		"unit.month": "月",
		"unit.season": "季",
		"unit.week": "周",
		"unit.year": "年",
		"world.back": "← 返回世界列表",
		"world.cardEnter": "看看这一生会走向哪里",
		"world.cardFallback": "一段尚未活过的人生，正等着你决定它的方向。",
		"world.cardPossibilities": "在这里，你可能会",
		"world.cardUntold": "这段人生还没有开始",
		"world.delete": "删除这个世界",
		"world.detailLineage": " · 可传承数代",
		"world.detailMeta": "{turn} · {styles} 种模拟风格{lineage}",
		"world.digest": "每回合的世界简报",
		"world.endings": "{endings} 种结局条件 · 存档会记下 {save} 类内容",
		"world.lineage": "可传承数代",
		"world.loreHide": "收起世界设定",
		"world.loreShow": "读读这个世界的设定",
		"world.languagePick": "用哪种语言游玩",
		"world.needsNewerCore": "这个世界需要更新版本的应用（需要 {needed}，当前 {local}）。",
		"world.opening": "开局会问你的事",
		"world.worldDecidesHint": "标出来的项由世界决定，你选不了。",
		"world.panelAlways": "始终显示",
		"world.panelConditional": "满足条件才显示",
		"world.panelFields": "{count} 项",
		"world.panels": "你会看到的面板",
		"world.play": "在这个世界活一次",
		"world.plays": "你在这里活过 {n} 次",
		"world.stale": "设定有改动",
		"world.summary": "{groups} 项开局设定 · {panels} 组面板 · {turn}",
		"world.turnUnit": "以{unit}为一回合",
		"world.unopenable": "这个世界打不开：{problem}",
		"world.unreadableDetail": "这次没能读取：{error}"
	},
	en: {
		"app.title": "Endless Worlds",
		"app.language": "Interface language",
		"settings.open": "Settings",
		"settings.title": "Narrator settings",
		"settings.close": "Close",
		"settings.model": "Model",
		"settings.modelDefault": "Default (auto)",
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
		"delete.forever": "This world did not come with the app. Deleting it is final.",
		"delete.go": "Delete the world and {n} lives",
		"delete.goNoLives": "Delete this world",
		"delete.inFlight": "The delete did not go through: a turn is still being written in this world. Try again when it is finished.",
		"delete.noLives": "Nobody has lived in this world yet. Delete it and it leaves the shelf.",
		"delete.restorable": "This world came with the app, so it can be put back — but it returns as it shipped. Your edits do not come back, and neither do the lives.",
		"delete.title": "Delete “{world}”?",
		"delete.typeToConfirm": "To continue, type the world's name: {world}",
		"delete.withLives": "There are {n} lives in this world. Deleting it ends them, and everything already written in them goes with it.",
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
		"library.otherWorlds": "Other worlds",
		"library.preparing": "Opening the shelf…",
		"library.removed": "You removed “{world}”.",
		"library.restore": "Put it back",
		"library.retry": "Retry",
		"life.archive": "Archive",
		"life.delete.aria": "Delete the life: {name}",
		"life.delete.changed": "This life advanced elsewhere, so its turn count changed. Look again before deciding.",
		"life.delete.done": "The life was deleted ({n} turns lived).",
		"life.delete.doneUnborn": "The unborn life was deleted.",
		"life.delete.forever": "Its world stays, and so does every other life. But this life cannot be recovered — its chronicle existed only in this one copy.",
		"life.delete.go": "End this life",
		"life.delete.inFlight": "The delete did not go through: a turn is still being written for this life. Try again when it is finished.",
		"life.delete.months": "“{name}” has lived {n} turns. Deleting it erases everything written in them.",
		"life.delete.reading": "Checking which page this life has reached…",
		"life.delete.short": "Delete",
		"life.actions": "Actions for {name}",
		"life.delete.title": "End this life?",
		"life.delete.typeToConfirm": "To continue, type this life's name: {name}",
		"life.delete.unborn": "“{name}” has not been born yet. Deleting it also takes the opening you chose.",
		"life.delete.unreadable": "This life can no longer be read. Since it cannot be opened, this is the only place you can delete it.",
		"life.ended": "Ended",
		"life.generating": "This page is being written…",
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
		"play.retry": "Try again",
		"play.rumour": "Rumor",
		"play.rumourSuffix": " — only hearsay",
		"play.sceneFailed": "This scene could not be drawn.",
		"play.sceneLoading": "This scene is being drawn…",
		"play.sceneTitle": "Scene",
		"play.silent": "(There is nothing on this page yet.)",
		"play.stalled": "This page did not come through. Your words are still here — try again.",
		"play.turn": "Turn {turn}",
		"play.page": "Page {n}",
		"play.prevTurn": "Previous turn",
		"play.recapDismiss": "Hide for now",
		"play.recapLastChoice": "Last time, you chose:",
		"play.recapNow": "Paths still open",
		"play.recapRecent": "What the last turns left behind",
		"play.recapTitle": "Where this life left off",
		"play.nextTurn": "Next turn",
		"play.unlocked": "A new chapter opens: {heading}",
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
		"rail.label": "Worlds and lives",
		"rail.shelf": "← Back to the shelf",
		"rail.styles": "{n} styles",
		"rail.worlds": "Worlds",
		"shelf.archived": "Archived ({n})",
		"shelf.continue": "Carry on",
		"shelf.ended": "Lives that have ended",
		"shelf.pick": "Pick a life on the left, or open a world.",
		"unit.day": "day",
		"unit.month": "month",
		"unit.season": "season",
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
		"world.lineage": "Can continue across generations",
		"world.loreHide": "Hide this world's lore",
		"world.loreShow": "Read this world's lore",
		"world.languagePick": "Language for this world",
		"world.needsNewerCore": "This world needs a newer version of the app (it asks for {needed}, this is {local}).",
		"world.opening": "What the world will ask you",
		"world.worldDecidesHint": "Highlighted choices are decided by the world — you cannot choose them.",
		"world.panelAlways": "always shown",
		"world.panelConditional": "shown when conditions are met",
		"world.panelFields": "{count} entries",
		"world.panels": "What you will see",
		"world.play": "Live a life here",
		"world.plays": "You have lived here {n} times",
		"world.stale": "The rulebook has changed",
		"world.summary": "{groups} opening settings · {panels} panels · {turn}",
		"world.turnUnit": "one {unit} per turn",
		"world.unopenable": "This world cannot be opened: {problem}",
		"world.unreadableDetail": "This could not be loaded: {error}"
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
* The confirmation is GRADUATED, because the stakes are not uniform. A world with
* no lives in it, backed by a seed, can be reinstalled from the install tree: the
* honest ask there is one button, and dressing it up as irreversible teaches the
* player to click through warnings. A world holding lives is hours of narrated
* story that no seed can bring back, so that ask requires typing the world's name —
* the one ritual that cannot be satisfied by a reflex.
*
* What the dialog must never do is guess. The life count comes from the server when
* the dialog opens and is sent back as a precondition, so a confirmation always
* names the number the delete will act on. If a life began in another tab in
* between, the server refuses and this dialog re-asks with the new number rather
* than proceeding on the old one.
*/
/**
* Ending ONE life.
*
* Always requires typing, unlike a world with no lives in it. A world can be
* reinstalled from its seed; a life cannot be reconstructed from anything — the
* months behind it exist only in its own chronicle. So there is no cheap tier here,
* and the ask names the month it is ending.
*/
function DeleteLifeDialog({ runId, onCancel, onDeleted }) {
	const [facts, setFacts] = useState(null);
	const [phase, setPhase] = useState("loading");
	const [problem, setProblem] = useState("");
	const [typed, setTyped] = useState("");
	const panel = useRef(null);
	const look = (fresh = false) => {
		api.lifeDeletion(runId).then((f) => {
			setFacts(f);
			setPhase("asking");
			if (fresh) setTyped("");
		}).catch((e) => {
			setProblem(e.message);
			setPhase("failed");
		});
	};
	useEffect(() => {
		setPhase("loading");
		look();
	}, [runId]);
	useEffect(() => {
		const onKey = (e) => {
			if (e.key === "Escape") onCancel();
		};
		window.addEventListener("keydown", onKey);
		panel.current?.focus();
		return () => window.removeEventListener("keydown", onKey);
	}, [onCancel]);
	const name = (facts?.subtitle || facts?.title || facts?.runId || "").trim();
	const armed = phase === "asking" && !!facts && typed.trim() === name && !!name;
	const confirm = () => {
		if (!facts || !armed) return;
		setPhase("working");
		setProblem("");
		api.deleteLife(runId, facts.turn).then((out) => onDeleted(out.turn)).catch((e) => {
			const code = e instanceof ApiError ? e.code : "";
			if (code === "turn_changed") {
				setProblem(t("life.delete.changed"));
				look(true);
				return;
			}
			if (code === "turn_in_flight") {
				setProblem(t("life.delete.inFlight"));
				look(true);
				return;
			}
			setProblem(e.message);
			setPhase("failed");
		});
	};
	return /* @__PURE__ */ jsx("div", {
		className: "ew-modal-wrap",
		role: "presentation",
		onClick: onCancel,
		children: /* @__PURE__ */ jsxs("div", {
			className: "ew-modal",
			role: "dialog",
			"aria-modal": "true",
			"aria-label": t("life.delete.title"),
			tabIndex: -1,
			ref: panel,
			onClick: (e) => e.stopPropagation(),
			children: [
				/* @__PURE__ */ jsx("div", {
					className: "ew-modal-title",
					children: t("life.delete.title")
				}),
				phase === "loading" ? /* @__PURE__ */ jsx("div", {
					className: "ew-meta",
					children: t("life.delete.reading")
				}) : null,
				facts ? /* @__PURE__ */ jsxs(Fragment, { children: [
					/* @__PURE__ */ jsx("div", {
						className: "ew-modal-body",
						children: facts.unreadable ? t("life.delete.unreadable") : facts.turn > 0 ? t("life.delete.months", {
							name,
							n: facts.turn
						}) : t("life.delete.unborn", { name })
					}),
					/* @__PURE__ */ jsx("div", {
						className: "ew-meta ew-modal-note",
						children: t("life.delete.forever")
					}),
					/* @__PURE__ */ jsxs("label", {
						className: "ew-modal-gate",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-meta",
							children: t("life.delete.typeToConfirm", { name })
						}), /* @__PURE__ */ jsx("input", {
							className: "ew-input",
							value: typed,
							autoFocus: true,
							spellCheck: false,
							onChange: (e) => setTyped(e.target.value),
							"aria-label": t("life.delete.typeToConfirm", { name })
						})]
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
						children: phase === "working" ? t("delete.working") : t("life.delete.go")
					})]
				})
			]
		})
	});
}
function DeleteWorldDialog({ worldId, onCancel, onDeleted }) {
	const [facts, setFacts] = useState(null);
	const [phase, setPhase] = useState("loading");
	const [problem, setProblem] = useState("");
	const [typed, setTyped] = useState("");
	const panel = useRef(null);
	const look = (fresh = false) => {
		api.worldDeletion(worldId).then((f) => {
			setFacts(f);
			setPhase("asking");
			if (fresh) setTyped("");
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
	const mustType = lives > 0;
	const named = typed.trim() === (facts?.title ?? "").trim();
	const armed = phase === "asking" && !!facts && (!mustType || named);
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
				look(true);
				return;
			}
			if (code === "turn_in_flight") {
				setProblem(t("delete.inFlight"));
				look(true);
				return;
			}
			setProblem(e.message);
			setPhase("failed");
		});
	};
	return /* @__PURE__ */ jsx("div", {
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
						children: lives === 0 ? t("delete.noLives") : t("delete.withLives", { n: lives })
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
					}),
					mustType ? /* @__PURE__ */ jsxs("label", {
						className: "ew-modal-gate",
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-meta",
							children: t("delete.typeToConfirm", { world: facts.title })
						}), /* @__PURE__ */ jsx("input", {
							className: "ew-input",
							value: typed,
							autoFocus: true,
							spellCheck: false,
							onChange: (e) => setTyped(e.target.value),
							"aria-label": t("delete.typeToConfirm", { world: facts.title })
						})]
					}) : null
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
						children: phase === "working" ? t("delete.working") : lives === 0 ? t("delete.goNoLives") : t("delete.go", { n: lives })
					})]
				})
			]
		})
	});
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
	return /* @__PURE__ */ jsx("div", {
		className: `ew-panel-box${panel.empty ? " ew-panel-quiet" : ""}`,
		children: (panel.fields ?? []).map((f) => /* @__PURE__ */ jsxs("div", {
			className: `ew-prow${f.label.length > LABEL_COLUMN_CHARS ? " ew-prow-stack" : ""}`,
			children: [/* @__PURE__ */ jsx("div", {
				className: "ew-plabel",
				children: f.label
			}), /* @__PURE__ */ jsx("div", {
				className: "ew-pval",
				children: /* @__PURE__ */ jsx(Value, { f })
			})]
		}, f.id))
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
		children: [
			/* @__PURE__ */ jsxs("div", {
				className: "ew-titlerow",
				children: [
					/* @__PURE__ */ jsx("span", {
						className: "ew-title",
						children: world.title
					}),
					world.lineage ? /* @__PURE__ */ jsx(Chip, {
						accent: true,
						children: t("world.lineage")
					}) : null,
					world.stale ? /* @__PURE__ */ jsx(Chip, { children: t("world.stale") }) : null
				]
			}),
			/* @__PURE__ */ jsx("div", {
				className: "ew-world-promise",
				children: promise
			}),
			possibilities.length ? /* @__PURE__ */ jsxs("div", {
				className: "ew-world-possibilities",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-world-possibilities-label",
					children: t("world.cardPossibilities")
				}), possibilities.map((possibility) => /* @__PURE__ */ jsx("div", {
					className: "ew-world-possibility",
					children: possibility
				}, possibility))]
			}) : null,
			world.stalenessNote ? /* @__PURE__ */ jsx("div", {
				className: "ew-meta",
				children: world.stalenessNote
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
	});
}
/**
* A life in progress.
*
* This is the load-bearing half of not losing your place: even if the app forgets
* which screen you were on, the life itself is listed and one tap from where you
* left it.
*/
function LifeRow({ run, onOpen, onDelete, onArchive, onRename }) {
	const name = run.label || run.subtitle || run.title || run.worldId;
	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState("");
	const commit = () => {
		onRename?.(run.runId, draft.trim());
		setEditing(false);
	};
	const [menuOpen, setMenuOpen] = useState(false);
	const menuRef = useRef(null);
	useEffect(() => {
		if (!menuOpen) return void 0;
		const close = (e) => {
			if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
		};
		document.addEventListener("mousedown", close);
		return () => document.removeEventListener("mousedown", close);
	}, [menuOpen]);
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
	if (onDelete) actions.push({
		key: "delete",
		label: t("life.delete.short"),
		aria: t("life.delete.aria", { name }),
		onClick: () => onDelete(run.runId)
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
			ref: menuRef,
			children: [/* @__PURE__ */ jsx("button", {
				className: "ew-kebab",
				type: "button",
				"aria-haspopup": "menu",
				"aria-expanded": menuOpen,
				"aria-label": t("life.actions", { name }),
				onClick: () => setMenuOpen((o) => !o),
				children: /* @__PURE__ */ jsx(MenuGlyph, {})
			}), menuOpen ? /* @__PURE__ */ jsx("div", {
				className: "ew-menu",
				role: "menu",
				children: actions.map((a) => /* @__PURE__ */ jsx("button", {
					className: "ew-menu-item",
					role: "menuitem",
					type: "button",
					"aria-label": a.aria,
					onClick: () => {
						setMenuOpen(false);
						a.onClick();
					},
					children: a.label
				}, a.key))
			}) : null]
		})] }) : null]
	});
}
function WorldDetailView({ worldId, onBack, onPlay, onDelete, onLanguage, initialLanguage }) {
	const [world, setWorld] = useState(null);
	const [error, setError] = useState(null);
	const [nonce, setNonce] = useState(0);
	const [lore, setLore] = useState(false);
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
							children: p.id
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
		world.prose ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("button", {
			className: "ew-section ew-section-toggle",
			type: "button",
			style: { marginTop: "18px" },
			"aria-expanded": lore,
			onClick: () => setLore((v) => !v),
			children: lore ? t("world.loreHide") : t("world.loreShow")
		}), lore ? /* @__PURE__ */ jsx("div", {
			className: "ew-block",
			children: /* @__PURE__ */ jsx(Prose, { text: world.prose })
		}) : null] }) : null,
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
		setPage(0);
		setRestored(false);
	};
	const groups = world.opening ?? [];
	const pages = Math.max(1, Math.ceil(groups.length / PER_PAGE));
	const slice = groups.slice(page * PER_PAGE, page * PER_PAGE + PER_PAGE);
	const last = page >= pages - 1;
	const rollable = groups.filter((g) => !g.worldDecides && g.options.length > 0);
	const rollOne = (g) => {
		const pick = g.options[Math.floor(Math.random() * g.options.length)];
		if (pick) setAnswers((a) => ({
			...a,
			[g.id]: pick
		}));
	};
	const rollAll = () => {
		const next = {};
		rollable.forEach((g) => {
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
				language: world.language
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
				rollable.length ? /* @__PURE__ */ jsx("button", {
					className: "ew-btn",
					type: "button",
					onClick: rollAll,
					children: t("opening.rollAll")
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
	const load = useCallback(async (before, replace = false, q = "") => {
		setBusy(true);
		setFailed(false);
		try {
			const out = await api.chronicle(runId, before, q);
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
		if (Number.isFinite(n) && n > 0) load(n + 1, true, query);
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
		"star.people.centre": "以谁为中心",
		"star.people.none": "这段人生还没有记下与人的往来。",
		"star.rel.evidence": "因为这些事",
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
		"card.wrap": "界面语言"
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
		"star.people.centre": "Centred on",
		"star.people.none": "No dealings with anyone have been recorded yet.",
		"star.rel.evidence": "Because of",
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
		"card.wrap": "Card language"
	}
};
function mt(lang, key, vars = {}) {
	return ((lang === "zh" ? TABLES.zh : TABLES.en)[key] ?? TABLES.en[key] ?? key).replace(/\{(\w+)\}/g, (whole, name) => name in vars ? String(vars[name]) : whole);
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
function ring(index, count, radius) {
	const angle = index / Math.max(count, 1) * Math.PI * 2 - Math.PI / 2;
	return {
		x: CX + radius * Math.cos(angle),
		y: CX + radius * Math.sin(angle)
	};
}
function RelationsLens({ payload, lang, focus, setFocus, filters, centre, setCentre, mode }) {
	const characters = payload.nodes.filter((n) => n.kind === "character" && nodeVisible(n, filters));
	const relations = payload.relations.filter((r) => r.from === centre || r.to === centre);
	if (!characters.length && !relations.length) return /* @__PURE__ */ jsx("div", {
		className: "ews-empty",
		children: mt(lang, "star.people.none")
	});
	const partners = /* @__PURE__ */ new Map();
	for (const r of relations) {
		const other = r.from === centre ? r.to : r.from;
		partners.set(other, [...partners.get(other) ?? [], r]);
	}
	const inner = [...partners.keys()].map((id) => nodeById(payload, id)).filter((n) => !!n && nodeVisible(n, filters)).sort((a, b) => a.id.localeCompare(b.id));
	const outer = payload.nodes.filter((n) => n.kind !== "event" && n.id !== centre && !partners.has(n.id) && nodeVisible(n, filters)).sort((a, b) => a.id.localeCompare(b.id));
	const centreLabel = centre === "player" ? mt(lang, "star.lens.life") : nodeLabel(nodeById(payload, centre) ?? {
		id: centre,
		kind: "character",
		name: centre
	});
	const picker = /* @__PURE__ */ jsxs("div", {
		className: "ews-centre-row",
		children: [
			/* @__PURE__ */ jsx("span", {
				className: "ews-centre-label",
				children: mt(lang, "star.people.centre")
			}),
			/* @__PURE__ */ jsx("button", {
				className: "ews-chip" + (centre === "player" ? " ews-chip-sel" : ""),
				type: "button",
				onClick: () => setCentre("player"),
				children: lang === "zh" ? "我" : "Me"
			}),
			characters.map((c) => /* @__PURE__ */ jsx("button", {
				className: "ews-chip ews-chip-character" + (centre === c.id ? " ews-chip-sel" : ""),
				type: "button",
				onClick: () => setCentre(c.id),
				children: nodeLabel(c)
			}, c.id))
		]
	});
	if (mode === "list") return /* @__PURE__ */ jsxs("div", { children: [picker, /* @__PURE__ */ jsx("div", {
		className: "ews-rel-list",
		children: relations.map((r, i) => {
			const other = r.from === centre ? r.to : r.from;
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
					/* @__PURE__ */ jsxs("span", {
						className: "ews-rel-kind",
						children: [r.type, r.value ? ` · ${r.value}` : r.level ? ` · ${r.level > 0 ? "+" : ""}${r.level}` : ""]
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
		})
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
				onClick: () => setFocus(centre),
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
		role: "dialog",
		"aria-modal": "true",
		children: /* @__PURE__ */ jsx("div", {
			className: "ews-empty",
			children: "…"
		})
	});
	return /* @__PURE__ */ jsxs("div", {
		className: "ewc-overlay",
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
  position: fixed; inset: 0; z-index: 70; display: flex; flex-direction: column;
  background: var(--bg, #14151f); color: var(--fg, #e5e7eb);
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
function StarMap({ runId, lang, onClose, onJumpTurn, initialFocus }) {
	const [payload, setPayload] = useState(null);
	const [lens, setLens] = useState(null);
	const [focus, setFocus] = useState(initialFocus ?? "");
	const [filters, setFilters] = useState(ALL_FILTERS);
	const [centre, setCentre] = useState("player");
	const [mode, setMode] = useState("canvas");
	const [kept, setKept] = useState([]);
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
		role: "dialog",
		"aria-modal": "true",
		children: [/* @__PURE__ */ jsx(StarStyles, {}), /* @__PURE__ */ jsx("div", {
			className: "ews-head",
			children: /* @__PURE__ */ jsx("button", {
				className: "ews-btn",
				type: "button",
				onClick: onClose,
				children: mt(lang, "star.close")
			})
		})]
	});
	const focused = focus ? nodeById(payload, focus) : void 0;
	const isKept = focused ? kept.includes(focused.id) || payload.keepsakes.some((kp) => kp.cites.includes(focused.id)) : false;
	const keep = async () => {
		if (!focused || focused.kind !== "event") return;
		await api.createKeepsake(runId, {
			kind: "event",
			title: focused.title ?? mt(lang, "star.keeps.newTitle"),
			cites: [focused.id]
		});
		setKept((k) => [...k, focused.id]);
		await load();
	};
	return /* @__PURE__ */ jsxs("div", {
		className: "ews-overlay",
		role: "dialog",
		"aria-modal": "true",
		"aria-label": mt(lang, "star.title"),
		children: [
			/* @__PURE__ */ jsx(StarStyles, {}),
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
								children: [/* @__PURE__ */ jsx("button", {
									className: "ews-btn",
									type: "button",
									onClick: () => onJumpTurn(focused.turn ?? 1),
									children: mt(lang, "star.detail.jump")
								}), /* @__PURE__ */ jsx("button", {
									className: "ews-btn",
									type: "button",
									disabled: isKept,
									onClick: () => void keep(),
									children: mt(lang, isKept ? "star.keep.kept" : "star.keep.this")
								})]
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
  position: fixed; inset: 0; z-index: 60; display: flex; flex-direction: column;
  background: var(--bg, #14151f); color: var(--fg, #e5e7eb); overflow: hidden;
}
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
.ews-star text { fill: var(--fg, #e5e7eb); font-size: 12px; }
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
/* Narrow screens: the detail panel becomes a bottom drawer (§8.3.4). */
@media (max-width: 860px) {
  .ews-body { flex-direction: column; }
  .ews-detail {
    flex: 0 0 auto; max-height: 42dvh;
    border-inline-start: 0; border-top: 1px solid var(--border, #2d2f3d);
  }
  .ews-lenses { margin-inline: 0; }
  .ews-head { flex-wrap: wrap; }
}
`;
//#endregion
//#region src/play.tsx
/** How often a life mid-generation is re-read. A month takes tens of seconds, so
*  this is about the page converging on its own rather than about latency. */
var GENERATING_POLL_MS = 3e3;
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
	const keep = async () => {
		await api.createKeepsake(runId, {
			kind: "echo",
			title: e.title || e.sourceTitle,
			cites: [e.sourceId, e.currentId].filter(Boolean)
		});
		setKept(true);
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
							onClick: () => void keep().catch(() => {}),
							children: mt(lang, kept ? "star.keep.kept" : "star.keep.this")
						}),
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
function PlayPage({ runId, onBack, onScenes, onReplay, onReplaySame, refresh }) {
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
	const [back, setBack] = useState(false);
	const loadedRun = useRef(null);
	const [recapOpen, setRecapOpen] = useState(false);
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
	const prevTurnRef = useRef(0);
	useEffect(() => {
		document.querySelector(".ew-root")?.scrollIntoView({ block: "start" });
		prevTurnRef.current = viewTurn ?? v?.turn ?? 0;
	}, [viewTurn, v?.turn]);
	const load = useCallback(async () => {
		try {
			const next = await api.run(runId);
			setV(next);
			if (loadedRun.current !== runId) {
				loadedRun.current = runId;
				const recap = next.recap;
				setRecapOpen(next.turn > 1 && !!(recap.lastAction || recap.events.length || recap.choices.length));
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
		const timer = window.setInterval(() => {
			load();
		}, GENERATING_POLL_MS);
		return () => window.clearInterval(timer);
	}, [
		generating,
		awaiting,
		load
	]);
	const busy = !!tapped || generating;
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
	useEffect(() => {
		onScenes(v?.scenes ?? []);
	}, [v, onScenes]);
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
	if (error) return /* @__PURE__ */ jsxs("div", { children: [
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
	const panels = /* @__PURE__ */ jsx(Fragment, { children: (v.panels ?? []).map((p) => /* @__PURE__ */ jsx(PanelBox, { panel: p }, p.id)) });
	if (v.ended) return /* @__PURE__ */ jsxs("div", { children: [
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
				/* @__PURE__ */ jsx("button", {
					className: "ew-btn ew-btn-go",
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
	const shownProse = isLive ? v.prose : chron.find((c) => c.turn === shownTurn)?.prose ?? v.prose;
	const pastAction = isLive ? "" : chron.find((c) => c.turn === shownTurn)?.action ?? "";
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
					children: recap.events.map((event) => /* @__PURE__ */ jsx("li", { children: event }, event))
				})] }) : null,
				recap.choices.length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("div", {
					className: "ew-recap-label",
					children: t("play.recapNow")
				}), /* @__PURE__ */ jsx("div", {
					className: "ew-recap-choices",
					children: recap.choices.map((choice) => /* @__PURE__ */ jsx("span", {
						className: "ew-recap-choice",
						children: choice
					}, choice))
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
				reveals.map((reveal) => /* @__PURE__ */ jsxs("div", {
					className: "ew-reveal-row",
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-reveal-label",
						children: reveal.label
					}), /* @__PURE__ */ jsx("span", {
						className: "ew-reveal-value",
						children: reveal.value
					})]
				}, reveal.label)),
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
		(v.digest ?? []).length ? /* @__PURE__ */ jsx("div", {
			className: "ew-digest",
			children: (v.digest ?? []).map((dg, i) => /* @__PURE__ */ jsxs("div", {
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
			children: /* @__PURE__ */ jsx(Prose, { text: shownProse })
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
		stalled ? /* @__PURE__ */ jsxs("div", {
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
				return /* @__PURE__ */ jsxs("div", {
					className: "ew-choicewrap",
					children: [/* @__PURE__ */ jsxs("button", {
						className: "ew-choice" + (armed ? " ew-choice-armed" : "") + (sending ? " ew-choice-waiting" : ""),
						type: "button",
						disabled: busy,
						"aria-pressed": armed,
						"aria-busy": sending,
						onClick: () => setArm(armed ? "" : target),
						children: [/* @__PURE__ */ jsx("span", {
							className: "ew-choice-label",
							children: c.label
						}), sending ? /* @__PURE__ */ jsx(Waiting, { label: phrase }) : null]
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
			generating ? /* @__PURE__ */ jsx("div", {
				className: "ew-note ew-note-live",
				children: /* @__PURE__ */ jsx(TurnProgress, {
					g: v.generating,
					label: phrase || t("play.generating")
				})
			}) : null,
			action.length > 400 ? /* @__PURE__ */ jsx("div", {
				className: "ew-count",
				children: `${action.length} / 500`
			}) : null
		] }) : null,
		/* @__PURE__ */ jsx("button", {
			className: "ew-drawer",
			type: "button",
			"aria-expanded": drawer,
			"aria-controls": "ew-panels-drawer",
			onClick: () => setDrawer((d) => !d),
			children: drawer ? t("play.drawerClose") : t("play.drawerOpen")
		}),
		v.turn >= 1 ? /* @__PURE__ */ jsx("button", {
			className: "ew-drawer",
			type: "button",
			onClick: () => setStarOpen(true),
			children: mt(v.language, "star.title")
		}) : null,
		drawer ? /* @__PURE__ */ jsx("div", {
			id: "ew-panels-drawer",
			style: { marginTop: "10px" },
			children: (v.panels ?? []).length ? panels : /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: t("play.nothingToShow")
			})
		}) : null
	] });
	return /* @__PURE__ */ jsxs("div", { children: [
		starOpen ? /* @__PURE__ */ jsx(StarMap, {
			runId,
			lang: v.language,
			onClose: () => setStarOpen(false),
			onJumpTurn: (turn) => {
				setStarOpen(false);
				setViewTurn(turn >= latest ? null : turn);
			}
		}) : null,
		/* @__PURE__ */ jsxs("div", {
			className: "ew-topbar",
			children: [/* @__PURE__ */ jsx("button", {
				className: "ew-back",
				type: "button",
				onClick: onBack,
				children: t("play.back")
			}), pager]
		}),
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
			children: [main, /* @__PURE__ */ jsx("div", {
				className: "ew-aside",
				children: panels
			})]
		})
	] });
}
//#endregion
//#region src/rail.tsx
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
function WorldRail({ worlds, runs, activeRunId, activeWorldId, onWorld, onLife, onHome, atShelf }) {
	const playable = (worlds ?? []).filter((w) => w.usable);
	const broken = (worlds ?? []).length - playable.length;
	const shown = runs.filter((r) => !r.archived);
	return /* @__PURE__ */ jsxs("nav", {
		className: "ew-rail",
		"aria-label": t("rail.label"),
		children: [
			atShelf ? null : /* @__PURE__ */ jsx("button", {
				className: "ew-rail-home",
				type: "button",
				onClick: onHome,
				children: t("rail.shelf")
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
			})
		]
	});
}
//#endregion
//#region src/scene.tsx
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
function SceneSlot({ runId, sceneId, onChoice }) {
	const [everNeeded, setEverNeeded] = useState(false);
	const [html, setHtml] = useState("");
	const [full, setFull] = useState(false);
	const [failed, setFailed] = useState(false);
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
	}, [sceneId, html]);
	useEffect(() => {
		if (!everNeeded) return void 0;
		const onMessage = (e) => {
			if (e.origin !== "null") return;
			const d = e.data;
			if (!d || d.source !== "endless-scene") return;
			if (d.sceneId !== sceneId) return;
			if (typeof d.nonce !== "string" || !d.nonce) return;
			if (typeof d.choice !== "string" || !d.choice) return;
			if (answered.current) return;
			answered.current = true;
			onChoice(sceneId, d.choice, d.nonce);
		};
		window.addEventListener("message", onMessage);
		return () => window.removeEventListener("message", onMessage);
	}, [
		sceneId,
		onChoice,
		everNeeded
	]);
	useEffect(() => {
		if (!full) return void 0;
		const onKey = (e) => {
			if (e.key === "Escape") setFull(false);
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [full]);
	const on = !!(html && sceneId);
	const loading = !!sceneId && !html && !failed;
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-slot-wrap",
		style: on ? void 0 : { margin: 0 },
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
			everNeeded ? /* @__PURE__ */ jsx("iframe", {
				title: t("play.sceneTitle"),
				className: `ew-slot${full ? " ew-slot-full" : on ? " ew-slot-on" : ""}`,
				sandbox: "allow-scripts allow-forms",
				srcDoc: html,
				allow: "",
				referrerPolicy: "no-referrer"
			}) : null,
			on ? /* @__PURE__ */ jsx("div", {
				className: `ew-slot-bar${full ? " ew-slot-bar-full" : ""}`,
				children: /* @__PURE__ */ jsx("button", {
					className: "ew-slot-btn",
					type: "button",
					onClick: () => setFull((f) => !f),
					children: full ? t("play.zoomOut") : t("play.zoomIn")
				})
			}) : null
		]
	});
}
//#endregion
//#region src/settings.tsx
/**
* Narrator settings, opened from the home page: which model writes the story and
* at what reasoning effort. Both apply to every life's narrator at its next turn.
*
* The model list comes from the gateway's advertised set (never a hardcoded id);
* an empty pick means "keep the app's default", so the app still narrates on auto
* when the list is unavailable or the player has chosen nothing.
*/
function SettingsPanel({ onClose }) {
	const [model, setModel] = useState("");
	const [effort, setEffort] = useState("");
	const [efforts, setEfforts] = useState([""]);
	const [models, setModels] = useState([]);
	const [saved, setSaved] = useState(false);
	const [busy, setBusy] = useState(false);
	useEffect(() => {
		let alive = true;
		api.settings().then((s) => {
			if (!alive) return;
			setModel(s.model || "");
			setEffort(s.reasoningEffort || "");
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
				reasoningEffort: effort
			});
			setModel(out.model || "");
			setEffort(out.reasoningEffort || "");
			setSaved(true);
		} finally {
			setBusy(false);
		}
	};
	const modelIds = models.map((m) => m.id);
	const extra = model && !modelIds.includes(model) ? [model] : [];
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
					}), [...extra, ...modelIds].map((id) => /* @__PURE__ */ jsx("option", {
						value: id,
						children: models.find((m) => m.id === id)?.name || id
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
var styles_default = "/* This app mounts into the DASHBOARD's own document, not an iframe, so every rule\n   here is global. Hence the ew- prefix on every class and zero bare element\n   selectors — an unprefixed .card would repaint the whole dashboard.\n\n   Narrow-first: bare rules are the phone baseline, min-width adds the desktop. */\n\n.ew-root {\n  --ew-gutter: 16px;\n  color: var(--text, #e2e8f0);\n  padding: var(--ew-gutter);\n  /* Scopes any future overlay to this panel instead of the whole dashboard. */\n  position: relative;\n}\n@media (min-width: 768px) {\n  .ew-root { max-width: 900px; margin: 0 auto; --ew-gutter: 24px; }\n}\n\n/* ── the desktop rail ──────────────────────────────────────────────────────\n   Above this width the page splits into a navigation axis and a reading axis.\n   Below it the rail is not rendered at all and the shelf behaves exactly as it\n   always has — the narrow layout is the baseline, not a compromise being undone.\n\n   1100px, not 768: a rail plus a readable measure needs ~1060px, and squeezing\n   both into a tablet gives a cramped rail AND cramped prose. Between 768 and\n   1100 the centred column is still the best use of the space. */\n.ew-rail { display: none; }\n\n@media (min-width: 1100px) {\n  /* The cap moves off .ew-root and onto the reading column, so the rail can sit\n     outside the measure instead of eating into it. */\n  .ew-root { max-width: 1320px; }\n\n  /* One way back, not two. The rail's own \"back to the shelf\" is permanent and\n     always in the same place, so the view's inline back button is a second control\n     doing the same thing. Scoped to `.ew-root .ew-back` (0,2,0) on purpose: the\n     base `.ew-back` rule is declared LATER in this file, so an equal-specificity\n     `.ew-back { display: none }` here would lose the cascade and the button would\n     stay visible — which is exactly the \"two back buttons\" bug this had. The\n     inline one is the mobile affordance and stays the only one below this width. */\n  .ew-root .ew-back { display: none; }\n\n  /* The shelf, once. The rail already lists every life and every world, so the\n     same list in the reading column was the same information twice, side by side.\n     Hidden here rather than removed from the component, because whether the rail\n     exists is a width question and so is this. */\n  .ew-shelflist { display: none; }\n\n  .ew-shell {\n    display: grid;\n    grid-template-columns: 248px minmax(0, 1fr);\n    gap: 32px;\n    align-items: start;\n  }\n\n  .ew-rail {\n    display: block;\n    position: sticky;\n    /* Sticks under the app's own header rather than the viewport top, so the\n       title does not scroll away from the rail it labels. */\n    top: var(--ew-gutter);\n    /* Its own scroll: a shelf with thirty lives must not push the story down. */\n    max-height: calc(100vh - 120px);\n    overflow-y: auto;\n    padding-right: 4px;\n  }\n\n  /* The measure. Prose is the reason this number exists — a life is read, not\n     scanned — so it is set in ch and does not grow with the window. */\n  .ew-main { max-width: 74ch; }\n}\n\n.ew-rail-home {\n  display: block; width: 100%; text-align: left;\n  min-height: 36px; margin-bottom: 14px; padding: 0;\n  background: transparent; border: none; cursor: pointer;\n  color: var(--accent, #7c3aed); font: inherit; font-size: 13px;\n}\n\n.ew-rail-group { margin-bottom: 18px; }\n.ew-rail-head {\n  font-size: 11px; font-weight: 600; letter-spacing: 0.04em;\n  text-transform: uppercase;\n  color: var(--muted, #6b7280);\n  margin-bottom: 6px;\n}\n\n.ew-rail-row {\n  display: block; width: 100%; text-align: left; cursor: pointer;\n  background: transparent;\n  border: none; border-left: 2px solid transparent;\n  border-radius: 0 6px 6px 0;\n  padding: 7px 8px; margin-bottom: 1px;\n  color: inherit; font: inherit;\n}\n.ew-rail-row:hover { background: var(--card, #1f2030); }\n.ew-rail-row:disabled { cursor: default; opacity: 0.45; }\n.ew-rail-row-on {\n  border-left-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 10%, transparent);\n}\n\n.ew-rail-name {\n  display: block; font-size: 13px; line-height: 1.35;\n  /* A world title is user content: one long unbroken run must not widen the\n     grid column, which would push the reading measure sideways. */\n  overflow-wrap: anywhere;\n}\n.ew-rail-sub {\n  display: block; font-size: 11px; color: var(--muted, #6b7280); margin-top: 2px;\n}\n/* Only where the rail is: below it, the shelf list IS the page and this landing\n   would be a second copy of what the list already says. */\n.ew-onlywide { display: none; }\n@media (min-width: 1100px) { .ew-onlywide { display: block; } }\n\n/* ── reading back ── */\n.ew-history { margin-top: 14px; }\n.ew-past { padding-bottom: 6px; margin-bottom: 18px; border-bottom: 1px solid var(--border, #2d2f3d); }\n.ew-past-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }\n.ew-past-turn { font-size: 12px; color: var(--muted, #6b7280); letter-spacing: .04em; }\n.ew-past-action { font-size: 12px; color: var(--accent, #7c3aed); overflow-wrap: anywhere; }\n\n.ew-rail-note {\n  font-size: 11px; color: var(--muted, #6b7280); padding: 6px 8px; line-height: 1.6;\n}\n\n.ew-head { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }\n.ew-head h2 { margin: 0; font-size: 17px; font-weight: 600; }\n@media (min-width: 768px) { .ew-head h2 { font-size: 19px; } }\n/* Interface-language dropdown: pushed to the far right of the title bar. */\n.ew-uilang {\n  margin-left: 0; min-height: 30px; padding: 0 8px; font-size: 13px;\n  color: var(--text, #e2e8f0); background: transparent;\n  border: 1px solid var(--border, #334155); border-radius: 8px; cursor: pointer;\n}\n/* The header's right-hand controls (language, settings), grouped and pushed right. */\n.ew-headtools { margin-left: auto; display: flex; gap: 8px; align-items: center; }\n/* Narrator settings panel on the home page. */\n.ew-settings {\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  background: var(--card, #1f2030); padding: 14px; margin-bottom: 16px;\n}\n.ew-settings-head { display: flex; align-items: center; justify-content: space-between; }\n.ew-settings-row { display: flex; align-items: center; gap: 12px; margin: 10px 0; }\n.ew-settings-label { flex: 0 0 8em; color: var(--muted, #6b7280); font-size: 13px; }\n.ew-settings-select { flex: 1; min-width: 0; }\n.ew-settings-foot { display: flex; align-items: center; gap: 12px; margin-top: 6px; }\n.ew-settings-saved { font-size: 12px; color: var(--accent, #7c3aed); }\n\n/* A world name is user content and can be one long unbroken run; without this a\n   phone gets a horizontal scrollbar on the whole page. */\n.ew-title, .ew-detail-title { overflow-wrap: anywhere; }\n\n.ew-card {\n  display: block; width: 100%; text-align: left; cursor: pointer;\n  background: var(--card, #1f2030);\n  border: 1px solid var(--border, #2d2f3d);\n  border-radius: 10px;\n  padding: 12px; margin-bottom: 10px;\n  color: inherit; font: inherit;\n  -webkit-tap-highlight-color: transparent;\n}\n@media (min-width: 768px) { .ew-card { padding: 14px; } }\n.ew-card:active { border-color: var(--accent, #7c3aed); }\n.ew-card-broken { cursor: default; border-left: 3px solid var(--danger, #b91c1c); }\n\n.ew-title { font-size: 15px; font-weight: 600; line-height: 1.35; }\n@media (min-width: 768px) { .ew-title { font-size: 16px; } }\n\n.ew-titlerow {\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;\n}\n.ew-chips { display: flex; gap: 6px; flex-wrap: wrap; }\n\n.ew-chip {\n  border-radius: 9999px; padding: 2px 9px; font-size: 11px;\n  border: 1px solid var(--border, #2d2f3d);\n  color: var(--muted, #6b7280);\n  white-space: nowrap;\n}\n.ew-chip-accent {\n  border-color: transparent;\n  background: color-mix(in oklab, var(--accent, #7c3aed) 16%, transparent);\n  color: var(--accent, #7c3aed);\n}\n\n.ew-meta { font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7; }\n\n/* A world card is an invitation to imagine a life, not a package manifest. The\n   promise leads; concrete possibilities make it credible; implementation counts\n   stay one tap away on the detail page. */\n.ew-world-card { overflow: hidden; }\n.ew-world-promise {\n  margin: 2px 0 12px;\n  font-size: 14px; line-height: 1.65;\n  color: var(--text, #e2e8f0);\n}\n.ew-world-possibilities {\n  margin: 0 0 14px; padding: 10px 12px;\n  border-left: 2px solid color-mix(in oklab, var(--accent, #7c3aed) 48%, transparent);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 7%, transparent);\n}\n.ew-world-possibilities-label {\n  margin-bottom: 5px; font-size: 11px; font-weight: 600;\n  letter-spacing: .04em; color: var(--accent, #7c3aed);\n}\n.ew-world-possibility {\n  position: relative; padding-left: 12px;\n  font-size: 12px; line-height: 1.65;\n  color: var(--muted, #94a3b8);\n}\n.ew-world-possibility::before { content: '·'; position: absolute; left: 1px; }\n.ew-world-card-footer {\n  display: flex; align-items: baseline; justify-content: space-between;\n  gap: 12px; margin-top: 12px; padding-top: 10px;\n  border-top: 1px solid var(--border, #2d2f3d);\n}\n.ew-world-enter {\n  flex: none; font-size: 12px; font-weight: 600;\n  color: var(--accent, #7c3aed);\n}\n\n/* 44px is the smallest reliably tappable target; a 13px text link with 4px of\n   padding is about 21px, which is a miss on a phone even when it looks fine on a\n   desktop mock. */\n.ew-back {\n  display: inline-flex; align-items: center;\n  min-height: 44px; padding: 0 12px 0 0;\n  background: transparent; border: none; cursor: pointer;\n  color: var(--accent, #7c3aed); font: inherit; font-size: 14px;\n  -webkit-tap-highlight-color: transparent;\n}\n\n.ew-detail-title { margin: 0 0 4px; font-size: 19px; line-height: 1.3; }\n@media (min-width: 768px) { .ew-detail-title { font-size: 22px; } }\n\n.ew-section { font-size: 13px; font-weight: 600; margin: 0 0 7px; }\n.ew-block { margin-bottom: 18px; }\n/* A small explanatory caption under a block, e.g. what the accented chips mean. */\n.ew-hint { font-size: 12px; color: var(--muted, #6b7280); line-height: 1.6; margin-top: -10px; }\n\n.ew-panel {\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px; margin-bottom: 8px;\n}\n@media (min-width: 768px) { .ew-panel { padding: 10px 12px; } }\n.ew-panel-head {\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 7px;\n}\n.ew-panel-name { font-size: 13px; font-weight: 600; }\n\n.ew-note {\n  font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; margin-top: 10px;\n}\n/* A note that carries an action. The button keeps its own size, so a long sentence\n   wraps instead of squeezing the thing the player is meant to press. */\n.ew-note-row {\n  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;\n  justify-content: space-between;\n}\n\n/* ── the second ask ──\n   Absolute inside the app's own box, NOT fixed — the same rule the scene slot\n   follows and for a sharper reason here: a fixed overlay would cover the\n   dashboard's own navigation, so a modal that failed to close would trap the\n   player in this app. Scoped to .ew-root, the worst case is an app they can\n   still navigate away from. */\n.ew-modal-wrap {\n  position: absolute; inset: 0; z-index: 40;\n  display: flex; align-items: flex-start; justify-content: center;\n  padding: 24px var(--ew-gutter, 8px);\n  background: color-mix(in oklab, var(--bg, #1a1b26) 72%, transparent);\n  /* The app's box can be taller than the viewport; keeping the panel near the top\n     of it means a scrolled page still shows the panel rather than empty scrim. */\n  overflow-y: auto;\n}\n.ew-modal {\n  width: 100%; max-width: 460px; box-sizing: border-box;\n  background: var(--bg-elevated, #21222e); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 12px;\n  padding: 18px; margin-top: 4vh;\n}\n.ew-modal:focus { outline: none; }\n.ew-modal-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; }\n.ew-modal-body { font-size: 14px; line-height: 1.75; margin-bottom: 12px; }\n.ew-modal-note { margin-bottom: 14px; }\n.ew-modal-gate { display: block; margin-bottom: 14px; }\n.ew-modal-gate .ew-meta { display: block; margin-bottom: 6px; }\n.ew-modal-problem {\n  font-size: 13px; line-height: 1.7; margin-bottom: 12px;\n  color: var(--danger, #f87171);\n}\n.ew-modal-bar { margin-top: 0; }\n\n/* What is about to be lost, named. A count alone does not tell the player which\n   life they are ending. */\n.ew-doomed {\n  list-style: none; margin: 0 0 14px; padding: 0;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  max-height: 34vh; overflow-y: auto;\n}\n.ew-doomed li {\n  display: flex; justify-content: space-between; gap: 10px;\n  padding: 8px 12px; font-size: 13px;\n  border-bottom: 1px solid var(--border, #2d2f3d);\n}\n.ew-doomed li:last-child { border-bottom: none; }\n.ew-doomed-name { min-width: 0; overflow-wrap: anywhere; }\n.ew-doomed-where { color: var(--muted, #6b7280); flex: 0 0 auto; font-size: 12px; }\n\n/* ── opening screen ── */\n\n.ew-group { margin-bottom: 20px; }\n.ew-glabel {\n  font-size: 14px; font-weight: 600; margin-bottom: 2px;\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;\n}\n.ew-ghint { font-size: 12px; color: var(--muted, #6b7280); margin-bottom: 8px; }\n\n/* Options are buttons, not a select: on a phone a native select opens a modal\n   wheel for six words, and the words are the whole point of this screen. */\n.ew-opt {\n  border-radius: 9999px; padding: 7px 13px; font-size: 13px;\n  border: 1px solid var(--border, #2d2f3d); background: transparent;\n  color: var(--text, #e2e8f0); cursor: pointer; font: inherit;\n  min-height: 36px; -webkit-tap-highlight-color: transparent;\n}\n.ew-opt-on {\n  border-color: transparent; color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 18%, transparent);\n}\n\n.ew-input {\n  width: 100%; box-sizing: border-box;\n  background: var(--bg, #1a1b26); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; font: inherit; font-size: 15px;\n  min-height: 44px;\n}\n.ew-input:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n\n/* A visible keyboard focus ring on every custom control, so tabbing through the\n   app can be followed. :focus-visible keeps it off pointer clicks. */\n.ew-btn:focus-visible, .ew-opt:focus-visible, .ew-choice:focus-visible,\n.ew-drawer:focus-visible, .ew-card-open:focus-visible, .ew-slot-btn:focus-visible,\n.ew-rail-row:focus-visible, .ew-rail-home:focus-visible, .ew-back:focus-visible,\n.ew-section-toggle:focus-visible {\n  outline: 2px solid var(--accent, #7c3aed); outline-offset: 2px;\n}\n\n/* Inline rename inside a life row: flexes to fill the row beside its save/cancel\n   buttons rather than forcing them onto a second line. */\n.ew-rename-input {\n  flex: 1 1 auto; min-width: 0; box-sizing: border-box;\n  background: var(--bg, #1a1b26); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 8px 10px; font: inherit; min-height: 40px;\n}\n.ew-rename-input:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n\n/* The archived group's heading is a toggle: it keeps the section typography but\n   reads as pressable. */\n.ew-section-toggle {\n  background: none; border: none; padding: 0; cursor: pointer;\n  color: inherit; text-align: start; -webkit-tap-highlight-color: transparent;\n}\n\n/* History toolbar: the events-only toggle and the jump-to-turn control. */\n.ew-history-bar {\n  display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px;\n}\n.ew-jump {\n  width: 7em; min-width: 0; box-sizing: border-box; font: inherit; min-height: 36px;\n  padding: 6px 10px; border-radius: 8px;\n  color: var(--text, #e2e8f0); background: var(--bg, #1a1b26);\n  border: 1px solid var(--border, #2d2f3d);\n}\n.ew-jump:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n.ew-search { width: 12em; }\n\n/* The \"world is being arranged\" state on the play page while a life is born. */\n.ew-arrange {\n  display: flex; flex-direction: column; gap: 12px; align-items: flex-start;\n  padding: 20px 0;\n}\n.ew-arrange-title {\n  font-size: 18px; font-weight: 600; color: var(--text, #e2e8f0);\n}\n\n/* A quiet marker when the world opens a new chapter of this life. */\n.ew-unlocked { margin: 0 0 14px; display: flex; flex-direction: column; gap: 7px; }\n\n/* \"An old thing came back\" — the echo marker (design §8.1). A single folded line\n   in the unlocked-marker voice; expanding it is the player's act, never a popup. */\n.ew-echoes { margin: 12px 0 14px; display: flex; flex-direction: column; gap: 7px; }\n.ew-echo {\n  padding-inline-start: 10px;\n  border-inline-start: 2px solid color-mix(in oklab, var(--accent, #7c3aed) 55%, transparent);\n}\n.ew-echo-line {\n  appearance: none; background: none; border: 0; padding: 2px 0; cursor: pointer;\n  font: inherit; font-size: 13px; font-style: italic; text-align: start;\n  color: var(--accent, #7c3aed);\n}\n.ew-echo-line:hover { text-decoration: underline; }\n.ew-echo-body {\n  margin-top: 6px; display: flex; flex-direction: column; gap: 6px;\n  font-size: 13px; line-height: 1.6; color: var(--fg, #e5e7eb);\n}\n.ew-echo-row { display: flex; gap: 8px; align-items: baseline; }\n.ew-echo-label {\n  flex: 0 0 auto; font-size: 12px; color: var(--muted, #6b7280);\n}\n.ew-echo-actions { display: flex; gap: 8px; margin-top: 2px; }\n\n.ew-unlocked-row {\n  font-size: 13px; color: var(--accent, #7c3aed);\n  padding-inline-start: 10px;\n  border-inline-start: 2px solid var(--accent, #7c3aed);\n}\n.ew-unlocked-heading { font-style: italic; font-weight: 600; }\n.ew-unlocked-meaning {\n  margin-top: 2px; font-size: 12px; line-height: 1.6;\n  color: var(--muted, #6b7280);\n}\n\n/* Small ceremonies around the prose: one reveals what the world settled at birth;\n   the other restores a returning player's place without generating a new summary. */\n.ew-story-moment {\n  margin: 0 0 16px; padding: 12px 14px; border-radius: 10px;\n  border: 1px solid color-mix(in oklab, var(--accent, #7c3aed) 32%, var(--border, #2d2f3d));\n  background: color-mix(in oklab, var(--accent, #7c3aed) 7%, var(--card, #1f2030));\n}\n.ew-story-moment-head {\n  display: flex; align-items: baseline; justify-content: space-between;\n  gap: 12px; margin-bottom: 7px;\n}\n.ew-story-moment-title { font-size: 13px; font-weight: 600; color: var(--accent, #7c3aed); }\n.ew-story-moment-close {\n  flex: none; border: none; padding: 3px 0; background: transparent;\n  color: var(--muted, #6b7280); font: inherit; font-size: 11px; cursor: pointer;\n}\n.ew-story-moment-close:focus-visible {\n  outline: 2px solid var(--accent, #7c3aed); outline-offset: 2px;\n}\n.ew-reveal-row {\n  display: flex; justify-content: space-between; gap: 12px;\n  padding: 4px 0; font-size: 13px; line-height: 1.5;\n}\n.ew-reveal-label, .ew-recap-label { color: var(--muted, #6b7280); }\n.ew-reveal-value { text-align: end; font-weight: 600; }\n.ew-story-moment-hint { margin-top: 6px; font-size: 11px; color: var(--muted, #6b7280); }\n.ew-recap-line { margin: 5px 0; font-size: 12px; line-height: 1.65; }\n.ew-recap-list { margin: 4px 0 8px; padding-inline-start: 18px; font-size: 12px; line-height: 1.65; }\n.ew-recap-choices { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }\n.ew-recap-choice {\n  border-radius: 9999px; padding: 3px 9px; font-size: 11px;\n  border: 1px solid var(--border, #2d2f3d); color: var(--muted, #94a3b8);\n}\n\n/* A turn's marked events and gains — the material the events-only timeline shows. */\n.ew-marks { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; }\n.ew-mark {\n  font-size: 13px; line-height: 1.6; padding-inline-start: 12px; position: relative;\n}\n.ew-mark::before {\n  content: \"·\"; position: absolute; inset-inline-start: 2px; color: var(--muted, #6b7280);\n}\n.ew-mark-gain { color: var(--muted, #6b7280); }\n\n/* A scalar field the narrator handed a structured value: its text, one line each. */\n.ew-lines { display: flex; flex-direction: column; gap: 3px; }\n\n/* The pre-birth summary: every opening choice on one line, with world-decided\n   items plainly marked so a look-before-you-leap is honest about what was chosen. */\n.ew-summary {\n  margin: 18px 0 6px; padding: 12px 14px; border-radius: 10px;\n  border: 1px solid var(--border, #2d2f3d); background: var(--card, #1f2030);\n}\n.ew-summary-row {\n  display: flex; gap: 12px; justify-content: space-between; align-items: baseline;\n  padding: 4px 0; font-size: 14px; line-height: 1.6;\n}\n.ew-summary-label { color: var(--muted, #6b7280); flex: 0 0 auto; }\n.ew-summary-value { text-align: end; }\n.ew-summary-world { text-align: end; color: var(--muted, #6b7280); font-style: italic; }\n\n.ew-sealed {\n  border: 1px dashed var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7;\n}\n\n.ew-bar {\n  display: flex; gap: 8px; flex-wrap: wrap; align-items: center;\n  margin-top: 20px; padding-top: 16px;\n  border-top: 1px solid var(--border, #2d2f3d);\n}\n.ew-btn {\n  border-radius: 8px; padding: 0 16px; min-height: 44px;\n  border: 1px solid var(--border, #2d2f3d); background: transparent;\n  color: var(--text, #e2e8f0); font: inherit; font-size: 14px; cursor: pointer;\n  -webkit-tap-highlight-color: transparent;\n}\n.ew-btn-go {\n  border-color: transparent; background: var(--accent, #7c3aed); color: #fff;\n  font-weight: 600; flex: 1; min-width: 140px;\n}\n.ew-btn:disabled, .ew-btn-go:disabled { opacity: .5; cursor: default; }\n\n/* Destructive, and it must read that way BEFORE it is pressed. Colour is not the\n   safeguard (the dialog is), but a delete that looks like every other button is a\n   delete the player presses while reading something else. */\n.ew-btn-danger {\n  border-color: var(--danger, #f87171);\n  color: var(--danger, #f87171);\n  background: color-mix(in oklab, var(--danger, #f87171) 12%, transparent);\n  flex: 0 0 auto;\n}\n/* The way OUT of a destructive path, and the way INTO one from a page whose\n   subject is something else. Quiet on purpose. */\n.ew-btn-quiet {\n  color: var(--muted, #6b7280); border-color: transparent;\n  flex: 0 0 auto; min-height: 36px; padding: 0 12px; font-size: 13px;\n}\n.ew-btn-quiet:hover { color: var(--text, #e2e8f0); }\n.ew-spacer { flex: 1; }\n/* Language chooser on the world card: a small toggle set, the chosen one filled. */\n.ew-lang {\n  border: 1px solid var(--border, #334155); border-radius: 999px;\n  background: transparent; color: var(--muted, #6b7280);\n  min-height: 32px; padding: 0 14px; font-size: 13px; cursor: pointer;\n}\n.ew-lang:hover { color: var(--text, #e2e8f0); }\n.ew-lang[aria-pressed=\"true\"] {\n  background: var(--accent, #6366f1); color: #fff; border-color: transparent;\n}\n@media (min-width: 768px) { .ew-btn-go { flex: 0 0 auto; } }\n\n/* ── prose ── */\n\n/* Reading typography, not UI typography — this is the only place the player reads\n   for minutes at a time. */\n.ew-prose {\n  font-size: 16px; line-height: 1.85; max-width: 66ch; margin: 12px 0 0;\n}\n/* Only the fallback path needs pre-wrap. With the host's markdown renderer,\n   paragraphs are real elements and pre-wrap would double every blank line. */\n.ew-prose-plain { white-space: pre-wrap; }\n.ew-prose p { margin: 0 0 1.1em; }\n.ew-prose p:last-child { margin-bottom: 0; }\n.ew-prose em { font-style: italic; }\n.ew-prose h1, .ew-prose h2, .ew-prose h3 {\n  font-size: 1.05em; font-weight: 600; margin: 1.4em 0 .5em;\n}\n.ew-prose blockquote {\n  margin: 1em 0; padding-left: 12px;\n  border-left: 2px solid var(--border, #2d2f3d); color: var(--muted, #6b7280);\n}\n.ew-prose ul, .ew-prose ol { margin: .8em 0; padding-left: 1.4em; }\n.ew-prose li { margin: .25em 0; }\n\n/* ── play page ── */\n\n/* Narrow-first single column; panels move to a sidebar from 900px. Below that the\n   sidebar is absent entirely and the drawer is how panels stay reachable —\n   rendering both would put every panel on screen twice. */\n.ew-play { display: block; }\n.ew-aside { display: none; }\n@media (min-width: 900px) {\n  .ew-play {\n    display: grid; grid-template-columns: minmax(0,1fr) 300px; gap: 28px; align-items: start;\n  }\n  .ew-aside { display: block; position: sticky; top: 12px; }\n}\n\n/* Title with the in-world date beside it (shown only when the world has one). */\n.ew-titleline { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }\n.ew-titleline .ew-clock { margin-bottom: 0; }\n.ew-clock {\n  font-size: 12px; color: var(--muted, #6b7280); letter-spacing: .04em; margin-bottom: 4px;\n}\n\n/* Back button and turn pager share one row, the pager pushed to the far right. */\n.ew-topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }\n/* Turn pager: ‹ current turn › */\n.ew-pager {\n  display: flex; align-items: center; justify-content: center; gap: 14px;\n  margin: 0;\n}\n.ew-pager-turn {\n  font-size: 13px; color: var(--muted, #6b7280); letter-spacing: .04em;\n  min-width: 6em; text-align: center;\n}\n.ew-pager-arw {\n  display: inline-flex; align-items: center; justify-content: center;\n  width: 36px; height: 36px; border-radius: 8px; cursor: pointer;\n  background: transparent; border: 1px solid var(--border, #2d2f3d);\n  color: var(--text, #e2e8f0);\n}\n.ew-pager-arw:hover:not(:disabled) { border-color: var(--accent, #7c3aed); }\n.ew-pager-arw:disabled { opacity: .35; cursor: default; }\n\n.ew-digest { margin: 0 0 20px; }\n/* Page-turn: the story slides+fades in — from the right going forward, from the\n   left going back. Keyed remount per turn runs it once; motion-reduce opts out. */\n@keyframes ew-page-fwd { from { opacity: 0; transform: translateX(26px); } to { opacity: 1; transform: none; } }\n@keyframes ew-page-back { from { opacity: 0; transform: translateX(-26px); } to { opacity: 1; transform: none; } }\n.ew-turnpage-fwd { animation: ew-page-fwd .3s ease-out both; }\n.ew-turnpage-back { animation: ew-page-back .3s ease-out both; }\n@media (prefers-reduced-motion: reduce) {\n  .ew-turnpage-fwd, .ew-turnpage-back { animation: none; }\n}\n.ew-drow {\n  display: flex; gap: 8px; padding: 6px 0; font-size: 13px; line-height: 1.7;\n  border-bottom: 1px solid var(--border, #2d2f3d);\n}\n.ew-drow-rumour { color: var(--muted, #6b7280); font-style: italic; }\n.ew-dcat { color: var(--muted, #6b7280); flex: 0 0 auto; min-width: 4.5em; }\n\n/* Panels keep UI type while the prose gets reading type — a stat block read at\n   16/1.85 is harder to scan, not easier. */\n.ew-panel-box {\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  padding: 12px; margin-bottom: 10px; font-size: 13px;\n}\n.ew-panel-quiet { opacity: .55; }\n.ew-prow { display: flex; gap: 10px; align-items: baseline; padding: 5px 0; line-height: 1.6; }\n.ew-plabel { color: var(--muted, #6b7280); flex: 0 0 5.5em; }\n.ew-pval { flex: 1; min-width: 0; overflow-wrap: anywhere; }\n/* A rank/tier value renders as an accent chip, but the narrator can write a whole\n   clause into it (measured on the flagship). Chips are nowrap by default so tag\n   rows stay tidy — but a value chip must wrap instead of overflowing the panel. */\n.ew-pval .ew-chip { white-space: normal; overflow-wrap: anywhere; }\n.ew-gap { color: var(--border, #2d2f3d); }\n\n/* A label that is really a sentence. Measured on the live flagship: the narrator\n   wrote a whole clause into a label slot, and the fixed 5.5em column wrapped it to\n   ten lines beside a single dot. Stacking costs one line of height and makes the row\n   readable; keeping the column costs ten and does not. */\n.ew-prow-stack { display: block; }\n.ew-prow-stack .ew-plabel { flex: none; margin-bottom: 2px; line-height: 1.55; }\n.ew-prow-stack .ew-pval { margin-left: 0; }\n\n.ew-bar-track {\n  height: 4px; border-radius: 2px; margin-top: 5px;\n  background: var(--border, #2d2f3d); overflow: hidden;\n}\n.ew-bar-fill { height: 100%; background: var(--accent, #7c3aed); }\n\n.ew-list { margin: 0; padding: 0; list-style: none; }\n.ew-list li { padding: 2px 0; }\n.ew-sub { color: var(--muted, #6b7280); }\n/* The world's name, demoted to a second line now that the life's own identity holds\n   the first. Small: it is the same string on every row, so it is context, not news. */\n.ew-card .ew-sub { display: block; font-size: 12px; margin-bottom: 2px; }\n\n.ew-choices { display: flex; flex-direction: column; gap: 8px; margin: 20px 0 0; }\n.ew-choice {\n  text-align: left; width: 100%; box-sizing: border-box;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  background: var(--card, #1f2030); color: var(--text, #e2e8f0);\n  padding: 12px 14px; font: inherit; font-size: 14px; line-height: 1.5;\n  min-height: 48px; cursor: pointer; -webkit-tap-highlight-color: transparent;\n}\n.ew-choice:active { border-color: var(--accent, #7c3aed); }\n.ew-choice:disabled { opacity: .5; cursor: default; }\n\n/* The one that was chosen. Kept at full opacity while its siblings dim, because\n   the point of the waiting state is to confirm WHICH choice was taken — a row where\n   every option is equally grey has answered a different question. */\n.ew-choicewrap { margin-bottom: 8px; }\n.ew-choice { position: relative; overflow: hidden; }\n.ew-choice-label { position: relative; z-index: 1; }\n\n/* Armed: chosen, not yet done. Reads as a held breath — brighter and slightly\n   raised, but explicitly NOT the accent fill the committing state uses, so the two\n   are never confused at a glance. */\n.ew-choice-armed {\n  border-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 8%, var(--card, #1f2030));\n  transform: translateY(-1px);\n  transition: transform .14s ease, background .14s ease, border-color .14s ease;\n}\n\n.ew-choice-waiting {\n  opacity: 1 !important;\n  border-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 12%, var(--card, #1f2030));\n}\n/* A light sweeping across the chosen line, once every couple of seconds. Chosen\n   over a spinner because it belongs to the SENTENCE the player picked rather than\n   to the page: what is being waited on is that line becoming a month. */\n.ew-choice-waiting::after {\n  content: ''; position: absolute; inset: 0; z-index: 0;\n  background: linear-gradient(\n    100deg,\n    transparent 20%,\n    color-mix(in oklab, var(--accent, #7c3aed) 22%, transparent) 50%,\n    transparent 80%\n  );\n  transform: translateX(-100%);\n  animation: ew-sweep 2.1s ease-in-out infinite;\n}\n\n/* ── the second step ──────────────────────────────────────────────────────\n   A turn is a month of a life and cannot be undone, so committing one is its own\n   deliberate act. The row appears under the armed choice rather than in a modal:\n   a dialog would take the sentence being decided off the screen. */\n.ew-confirm {\n  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;\n  padding: 8px 4px 2px 14px;\n  animation: ew-rise .16s ease-out;\n}\n.ew-confirm-act { padding-left: 0; }\n.ew-confirm-ask { font-size: 13px; color: var(--muted, #6b7280); margin-right: 2px; }\n.ew-btn-sm { min-height: 36px; padding: 0 14px; font-size: 13px; flex: 0 0 auto; }\n.ew-note-live { display: flex; align-items: center; margin-top: 10px; min-width: 0; }\n/* Turn progress: a staged bar the narrator's tool calls drive — a fill that jumps\n   to ~90% once it has read the life, plus a moving shimmer so the long writing\n   phase never looks stalled. */\n.ew-progress { width: 100%; min-width: 0; }\n.ew-progress-track {\n  position: relative; height: 6px; border-radius: 999px; overflow: hidden;\n  background: var(--border, #2d2f3d);\n}\n.ew-progress-fill {\n  position: absolute; inset: 0 auto 0 0; width: 0; border-radius: 999px;\n  background: var(--accent, #7c3aed); transition: width .4s ease;\n}\n.ew-progress-track::after {\n  content: ''; position: absolute; inset: 0; z-index: 1;\n  background: linear-gradient(\n    100deg, transparent 20%,\n    color-mix(in oklab, #fff 28%, transparent) 50%, transparent 80%\n  );\n  transform: translateX(-100%); animation: ew-sweep 1.6s ease-in-out infinite;\n}\n.ew-progress-steps {\n  display: flex; justify-content: space-between; gap: 8px; margin-top: 6px;\n}\n.ew-progress-label { font-size: 12px; color: var(--muted, #6b7280); }\n.ew-progress-count { font-size: 11px; color: var(--muted, #6b7280); flex: 0 0 auto; }\n@media (prefers-reduced-motion: reduce) {\n  .ew-progress-track::after { animation: none; opacity: 0; }\n}\n\n/* ── waiting ──────────────────────────────────────────────────────────────\n   The app's only animation, introduced with its reduced-motion answer in the same\n   edit rather than after: idle motion like this reads as pleasant to most people\n   and as a symptom to someone with a vestibular disorder, and retrofitting the\n   media query means shipping the version without it. */\n\n.ew-wait {\n  display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap;\n  vertical-align: middle; margin-left: 8px; position: relative; z-index: 1;\n  min-width: 0; max-width: 100%;\n}\n.ew-wait-dots { display: inline-flex; gap: 4px; flex: 0 0 auto; }\n.ew-wait-label { font-size: 12px; color: var(--muted, #6b7280); min-width: 0; overflow-wrap: anywhere; }\n\n.ew-dot {\n  width: 5px; height: 5px; border-radius: 50%;\n  background: currentColor; opacity: .35;\n  animation: ew-pulse 1.1s ease-in-out infinite;\n}\n/* Staggered, so the group reads as one moving thing rather than three blinking\n   ones. */\n.ew-dot:nth-child(2) { animation-delay: .18s; }\n.ew-dot:nth-child(3) { animation-delay: .36s; }\n\n@keyframes ew-pulse {\n  0%, 80%, 100% { opacity: .25; transform: scale(.8); }\n  40%           { opacity: 1;   transform: scale(1); }\n}\n@keyframes ew-sweep {\n  0%        { transform: translateX(-100%); }\n  60%, 100% { transform: translateX(100%); }\n}\n@keyframes ew-rise {\n  from { opacity: 0; transform: translateY(-3px); }\n  to   { opacity: 1; transform: none; }\n}\n\n@media (prefers-reduced-motion: reduce) {\n  /* Not \"animation: none\" alone — that would leave three barely-visible dots and\n     no signal at all. Every indicator stays; they simply stop moving. */\n  .ew-dot { animation: none; opacity: .75; }\n  .ew-choice-waiting::after { animation: none; transform: none; opacity: .35; }\n  .ew-confirm { animation: none; }\n  .ew-choice-armed { transition: none; transform: none; }\n}\n\n.ew-act { display: flex; gap: 8px; margin-top: 12px; align-items: stretch; }\n.ew-act textarea {\n  flex: 1; min-width: 0; box-sizing: border-box; resize: vertical;\n  min-height: 44px; max-height: 40vh;\n  background: var(--bg, #1a1b26); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  padding: 11px 12px; font: inherit; font-size: 15px; line-height: 1.5;\n}\n.ew-act textarea:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n\n.ew-count { font-size: 11px; color: var(--muted, #6b7280); margin-top: 4px; }\n\n/* The drawer is how panels stay reachable on a phone without pushing the prose\n   off the first screen. */\n.ew-drawer {\n  width: 100%; margin: 20px 0 0;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  background: transparent; color: var(--text, #e2e8f0);\n  font: inherit; font-size: 13px; min-height: 44px; cursor: pointer;\n}\n@media (min-width: 900px) { .ew-drawer { display: none; } }\n\n/* ── the scene slot ── */\n\n/* ONE element, created on first need and never moved. Moving an iframe in the DOM\n   reloads it, so re-parenting a mounted scene would throw away whatever the player\n   was looking at — and a React portal does not help, because the browser's rule is\n   about the element's position in the document, not about who rendered it. */\n.ew-slot {\n  display: none;\n  width: 100%;\n  border: 1px solid var(--border, #2d2f3d);\n  border-radius: 10px;\n  background: var(--card, #1f2030);\n  /* A scene is a picture, not a page: it never becomes the scrolling thing. */\n  overflow: hidden;\n}\n.ew-slot-on { display: block; height: 320px; }\n\n/* Fullscreen is the SAME element with different geometry. Absolute inside the\n   app's own box rather than fixed: position fixed escapes the panel entirely and\n   would put a scene over the dashboard's own chrome. */\n.ew-slot-full {\n  display: block;\n  position: absolute; inset: 0;\n  height: auto; z-index: 20;\n  border-radius: 0;\n}\n\n.ew-slot-wrap { position: relative; margin: 16px 0 0; }\n.ew-slot-bar {\n  display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 6px;\n}\n.ew-slot-bar-full { position: absolute; top: 8px; right: 8px; z-index: 21; margin: 0; }\n.ew-slot-btn {\n  min-height: 36px; padding: 0 12px; font: inherit; font-size: 12px;\n  color: var(--text, #e2e8f0); background: var(--card, #1f2030);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px; cursor: pointer;\n  -webkit-tap-highlight-color: transparent;\n}\n\n/* A shelf row that carries its own destructive control. The row is a div and the\n   open action is a button INSIDE it, because a button cannot contain a button --\n   and the delete has to be a sibling, not a nested child. */\n.ew-card-row { display: flex; align-items: stretch; gap: 0; padding: 0; overflow: visible; }\n.ew-card-open {\n  flex: 1 1 auto; min-width: 0; text-align: left; font: inherit;\n  background: transparent; border: none; color: inherit; cursor: pointer;\n  /* 12px, matching .ew-card, so a life row is inset exactly like a world card. */\n  padding: 12px; -webkit-tap-highlight-color: transparent;\n}\n.ew-card-open:disabled { opacity: .55; cursor: default; }\n/* Aligned to the top of the row rather than centred: a row is two or three lines\n   tall, and a vertically centred control drifts as the row's text grows. */\n.ew-card-drop {\n  align-self: flex-start; margin: 10px 10px 0 0; border-radius: 8px;\n}\n/* Row actions: inline on desktop, collapsed into a kebab menu on a phone where\n   three stacked buttons wrapped badly. */\n.ew-life-actions { display: flex; align-items: flex-start; }\n.ew-life-menu { display: none; position: relative; align-self: flex-start; margin: 10px 10px 0 0; }\n@media (max-width: 767px) {\n  .ew-life-actions { display: none; }\n  .ew-life-menu { display: block; }\n  /* iOS Safari zooms the page when a focused control's font-size is under 16px.\n     Floor every control at 16px on a phone so focusing an input never zooms in. */\n  .ew-root input, .ew-root textarea, .ew-root select { font-size: 16px; }\n}\n.ew-kebab {\n  display: inline-flex; align-items: center; justify-content: center;\n  width: 40px; height: 40px; border-radius: 8px; cursor: pointer;\n  background: transparent; border: 1px solid var(--border, #2d2f3d);\n  color: var(--muted, #6b7280); -webkit-tap-highlight-color: transparent;\n}\n.ew-kebab:hover { color: var(--text, #e2e8f0); }\n.ew-menu {\n  position: absolute; right: 0; top: 44px; z-index: 30; min-width: 160px;\n  display: flex; flex-direction: column; gap: 2px; padding: 6px;\n  background: var(--card, #1f2030); border: 1px solid var(--border, #2d2f3d);\n  border-radius: 10px; box-shadow: 0 10px 28px rgba(0, 0, 0, .45);\n}\n.ew-menu-item {\n  text-align: left; font: inherit; cursor: pointer; min-height: 42px;\n  padding: 10px 12px; border: none; border-radius: 6px;\n  background: transparent; color: var(--text, #e2e8f0);\n}\n.ew-menu-item:hover { background: color-mix(in oklab, var(--accent, #7c3aed) 12%, var(--card, #1f2030)); }\n";
//#endregion
//#region src/main.tsx
/** Where the player was, so leaving the page does not throw them back to the
*  shelf. Prefixed because this app mounts inside the dashboard's own document
*  and shares its localStorage. */
var WHERE = "endless-worlds:where";
/** The player's standing UI-language pick from the header dropdown. Prefixed and
*  shared with the dashboard document like every other key this app keeps. */
var LANG_KEY = "endless-worlds:lang";
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
	const [view, setView] = useState("library");
	const [showSettings, setShowSettings] = useState(false);
	const rootRef = useRef(null);
	useEffect(() => {
		rootRef.current?.scrollIntoView({ block: "start" });
	}, [view]);
	const [selected, setSelected] = useState(null);
	const [world, setWorld] = useState(null);
	const [live, setLive] = useState(null);
	const [scenes, setScenes] = useState([]);
	const [refresh, setRefresh] = useState(0);
	/** Which world's deletion is being confirmed, or null. Held here rather than in
	*  the detail view because the reload that follows a deletion unmounts that
	*  view — a dialog owned by it would vanish mid-request. */
	const [doomed, setDoomed] = useState(null);
	/** Which life's deletion is being confirmed, or null. */
	const [doomedLife, setDoomedLife] = useState(null);
	const [note, setNote] = useState("");
	const [lang, setLangState] = useState(() => asLang(localStorage.getItem(LANG_KEY) ?? void 0) ?? "zh");
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
	}, [lang]);
	useEffect(() => {
		load();
	}, [load]);
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
		if (where.view === "opening" && where.worldId) api.world(where.worldId).then((w) => {
			applyLanguage(w.language);
			setWorld(w);
			setView("opening");
		}).catch(() => {
			forget();
		});
	}, [applyLanguage]);
	const home = () => {
		forget();
		setView("library");
		setSelected(null);
		setWorld(null);
		setLive(null);
		setScenes([]);
		load();
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
		setNote((out.lives ? t("delete.doneWithLives", { n: out.lives }) : t("delete.done")) + (out.restorable ? " " + t("delete.doneRestorable") : ""));
		home();
	};
	/**
	* After a life is gone.
	*
	* If the player was standing in it, staying would leave the play page polling a
	* life that answers 404. The shelf is the only honest landing.
	*/
	const afterLifeDelete = (turn) => {
		setDoomedLife(null);
		setNote(turn > 0 ? t("life.delete.done", { n: turn }) : t("life.delete.doneUnborn"));
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
		try {
			const out = await api.answerScene(live, sceneId, {
				choice,
				nonce
			});
			if (!out.accepted) {
				setRefresh((n) => n + 1);
				return;
			}
			await api.takeTurn(live, { action: out.action });
		} catch {}
		setRefresh((n) => n + 1);
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
	let body;
	if (view === "live" && live) body = /* @__PURE__ */ jsx(PlayPage, {
		runId: live,
		onBack: home,
		onScenes: setScenes,
		onReplay: openWorld,
		onReplaySame: restartSameOpening,
		refresh
	});
	else if (view === "opening" && world) body = /* @__PURE__ */ jsx(OpeningScreen, {
		world,
		onBack: home,
		onLive: enterLife
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
		const active = runs.filter((r) => !r.archived && !r.ended);
		const endedRuns = runs.filter((r) => !r.archived && r.ended);
		const archivedRuns = runs.filter((r) => r.archived);
		const newest = active.find((r) => !r.unreadable);
		const rowProps = {
			onOpen: enterLife,
			onDelete: setDoomedLife,
			onRename: renameLife,
			onArchive: archiveLife
		};
		body = /* @__PURE__ */ jsxs(Fragment, { children: [
			newest ? /* @__PURE__ */ jsxs("div", {
				className: "ew-onlywide",
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
				className: "ew-shelflist",
				children: [
					active.length ? /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("div", {
						className: "ew-section",
						children: t("library.lives")
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
					}, r.runId)) : null] }) : null,
					runs.length ? /* @__PURE__ */ jsx("div", {
						className: "ew-section",
						style: { marginTop: "22px" },
						children: t("library.otherWorlds")
					}) : null,
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
	return /* @__PURE__ */ jsx(LanguageContext.Provider, {
		value: applyLanguage,
		children: /* @__PURE__ */ jsxs("div", {
			className: "ew-root",
			lang,
			ref: rootRef,
			children: [
				/* @__PURE__ */ jsx("style", { children: styles_default }),
				/* @__PURE__ */ jsxs("div", {
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
					className: "ew-shell",
					children: [/* @__PURE__ */ jsx(WorldRail, {
						worlds,
						runs,
						activeRunId: live,
						activeWorldId: world?.worldId ?? selected,
						onWorld: openWorld,
						onLife: enterLife,
						onHome: home,
						atShelf: view === "library"
					}), /* @__PURE__ */ jsx("div", {
						className: "ew-main",
						children: body
					})]
				}),
				live ? scenes.map((s) => /* @__PURE__ */ jsx(SceneSlot, {
					runId: live,
					sceneId: s.sceneId,
					onChoice: onSceneChoice
				}, s.sceneId)) : null,
				doomed ? /* @__PURE__ */ jsx(DeleteWorldDialog, {
					worldId: doomed,
					onCancel: () => setDoomed(null),
					onDeleted: afterDelete
				}) : null,
				doomedLife ? /* @__PURE__ */ jsx(DeleteLifeDialog, {
					runId: doomedLife,
					onCancel: () => setDoomedLife(null),
					onDeleted: afterLifeDelete
				}) : null
			]
		})
	});
}
//#endregion
export { EndlessWorlds as default };
