import { useCallback, useEffect, useRef, useState } from "react";
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
var api = {
	worlds: () => json("/worlds"),
	world: (id) => json(`/worlds/${encodeURIComponent(id)}`),
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
	restoreWorld: (id) => post(`/worlds/${encodeURIComponent(id)}/restore`, {}),
	runs: () => json("/runs"),
	run: (id) => json(`/runs/${encodeURIComponent(id)}`),
	/** The months already lived. `before` is a turn NUMBER, not an offset: an offset
	*  would shift under a turn committed between two pages and silently skip or
	*  repeat a month. */
	chronicle: (id, before = 0) => json(`/runs/${encodeURIComponent(id)}/chronicle` + (before > 0 ? `?before=${before}` : "")),
	createRun: (body) => post("/runs", body),
	openRun: (id) => post(`/runs/${encodeURIComponent(id)}/open`, {}),
	takeTurn: (id, body) => post(`/runs/${encodeURIComponent(id)}/turn`, body),
	scene: async (runId, sceneId) => {
		const res = await fetch(`${API}/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}`);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		return res.text();
	},
	answerScene: (runId, sceneId, body) => post(`/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}/answer`, body)
};
//#endregion
//#region src/strings.ts
var TABLES = {
	zh: {
		"app.title": "无限世界",
		"delete.cancel": "不删了",
		"delete.changed": "刚才你在别处开始了新的人生，数目变了。请重新看一遍再决定。",
		"delete.counting": "正在数一数这个世界里还有谁在活着…",
		"delete.done": "世界已删除。",
		"delete.doneRestorable": "它还能从书架上重新装回。",
		"delete.doneWithLives": "世界已删除，连同 {n} 条人生。",
		"delete.forever": "这个世界不是随应用来的，删掉就没有了。",
		"delete.go": "删除世界，连同 {n} 条人生",
		"delete.goNoLives": "删除这个世界",
		"delete.inFlight": "这个世界里正有一个月在被写。等它写完再删，否则那一个月会白写。",
		"delete.noLives": "这个世界里还没有人活过。删掉它，书架上就不再有它。",
		"delete.restorable": "这个世界是随应用一起来的，删掉之后还能重新装回 —— 但装回来的是它出厂的样子，你改过的地方回不来，已经消失的人生也不会回来。",
		"delete.title": "删除「{world}」？",
		"delete.typeToConfirm": "要继续，请把世界的名字打一遍：{world}",
		"delete.withLives": "这个世界里有 {n} 条人生。删掉它，这些人生连同它们已经写下的一切一起消失。",
		"delete.working": "正在删除…",
		"history.beginning": "已经到这条人生的开头了。",
		"history.chose": "当时你选了：{action}",
		"history.close": "收起前面的回合",
		"history.earlier": "再往前",
		"history.none": "还没有过去可回顾——这是第一个月。",
		"history.open": "往回读这条人生",
		"history.reading": "正在翻回去…",
		"history.unreadable": "这条人生的过往读不出来。",
		"library.backendHint": "{path} → {error}。404 表示后端模块没有加载，需要 disable→enable 一次。",
		"library.backendSilent": "后端还没有响应。",
		"library.empty": "还没有任何世界。",
		"library.lives": "你正在过的人生",
		"library.newerSeed": "《{world}》有更新的版本（{installed} → {available}）。你这份保持原样。",
		"library.otherWorlds": "别的世界",
		"library.preparing": "正在准备…",
		"library.removed": "「{world}」已被你移除。",
		"library.restore": "重新装回",
		"life.delete.aria": "删除人生：{name}",
		"life.delete.changed": "这条人生在别处又往前走了一个月，数目变了。请重新看一遍再决定。",
		"life.delete.done": "人生已删除（活了 {n} 个月）。",
		"life.delete.doneUnborn": "那条还没出生的人生已删除。",
		"life.delete.forever": "它的世界会留下，别的人生也不受影响。但这条人生本身没有任何办法找回来 —— 它的编年史只存在于它自己那一份里。",
		"life.delete.go": "结束这条人生",
		"life.delete.inFlight": "正有一个月在为它被写。等它写完再删，否则那一个月会白写。",
		"life.delete.months": "「{name}」已经活了 {n} 个月。删掉它，这些月份写下的一切都没有了。",
		"life.delete.reading": "正在读这条人生走到了哪里…",
		"life.delete.short": "删除",
		"life.delete.title": "结束这条人生？",
		"life.delete.typeToConfirm": "要继续，请把这条人生的名字打一遍：{name}",
		"life.delete.unborn": "「{name}」还没有出生。删掉它，你留下的开局设定也一起没有。",
		"life.delete.unreadable": "这条人生已经读不出来了。它打不开，所以只能从这里删掉。",
		"life.ended": "已经结束",
		"life.generating": "正在写这个月…",
		"life.turn": "第 {turn} 回合",
		"life.unborn": "还没出生",
		"life.unreadable": "这一世读不出来了",
		"life.waiting": "等你继续",
		"note.dismiss": "知道了",
		"opening.arranging": "世界正在为你安排出生的时刻…",
		"opening.backToShelf": "回到书架",
		"opening.begin": "开始这一世",
		"opening.beginning": "正在开始…",
		"opening.continueBirth": "接着出生",
		"opening.custom": "自定义…",
		"opening.customPlaceholder": "写下你自己的",
		"opening.hintPick": "挑一个，或者留空让世界替你决定。",
		"opening.hintText": "留空则由世界决定。",
		"opening.keptSafe": "你选的一切都还在。",
		"opening.next": "下一页",
		"opening.notStarted": "这一世还没有开始。你选的一切都还在。",
		"opening.page": "第 {page} / {pages} 页",
		"opening.prev": "上一页",
		"opening.retry": "再试一次",
		"opening.rollAll": "全部随机",
		"opening.rollOne": "随机 {label}",
		"opening.sealed": "这一项由世界定下，不由你选。等你出生时才会知道。",
		"opening.silent": "世界一时没有回应。",
		"opening.styleHint": "决定这个世界对你有多狠。",
		"opening.styleLabel": "这一世怎么讲给你听",
		"opening.waiting.0": "正在为这条命安排出身…",
		"opening.waiting.1": "这个世界正在给他一个位置…",
		"opening.waiting.2": "第一口气还没吸进去…",
		"opening.waiting.3": "命纸尚白…",
		"play.act": "去做",
		"play.acting": "…",
		"play.actionPlaceholder": "或者，做点别的。",
		"play.back": "← 回到书架",
		"play.confirmAct": "按你写的去做？",
		"play.confirmAsk": "就这么做？",
		"play.confirmNo": "再想想",
		"play.confirmYes": "就这么做",
		"play.drawerClose": "收起这一刻的自己",
		"play.drawerOpen": "看看这一刻的自己",
		"play.endedBadge": "这一生落幕了。",
		"play.endedMeta": "这一生走过了 {turn} 个回合。",
		"play.endedReplay": "在这个世界再活一次",
		"play.endedShelf": "回到书架",
		"play.generating": "这个月正在被写下来。可以离开这一页，回来时它会在这里。",
		"play.nothingToShow": "这一刻还没有什么可看的——这条人生的各栏要等它们各自的条件成立才会出现。",
		"play.opening": "正在翻开…",
		"play.retry": "再试一次",
		"play.rumour": "传闻",
		"play.rumourSuffix": " —— 只是听说",
		"play.sceneFailed": "这一处景象没能画出来。",
		"play.sceneTitle": "景象",
		"play.silent": "（世界还没有说话。）",
		"play.stalled": "世界一时没有回应。再说一次试试。",
		"play.turn": "第 {turn} 回合",
		"play.waiting.0": "岁月流逝…",
		"play.waiting.1": "光阴推移…",
		"play.waiting.2": "世事流转…",
		"play.waiting.3": "这个月正在过去…",
		"play.waiting.4": "命运正在落笔…",
		"play.waiting.5": "时序更替…",
		"play.waiting.6": "风声穿过村口…",
		"play.zoomIn": "放大",
		"play.zoomOut": "缩小",
		"rail.broken": "另有 {n} 个世界读不出来",
		"rail.label": "世界与人生",
		"rail.shelf": "← 回到书架",
		"rail.styles": "{n} 种风格",
		"rail.worlds": "世界",
		"shelf.continue": "接着过下去",
		"shelf.pick": "从左边挑一条人生，或者开一个世界。",
		"unit.day": "日",
		"unit.month": "月",
		"unit.season": "季",
		"unit.week": "周",
		"unit.year": "年",
		"world.back": "← 返回世界列表",
		"world.delete": "删除这个世界",
		"world.detailLineage": " · 可传承数代",
		"world.detailMeta": "{turn} · {styles} 种模拟风格{lineage}",
		"world.digest": "每回合世界会报告",
		"world.endings": "{endings} 种结局条件 · 存档保存 {save} 类内容",
		"world.lineage": "可传承数代",
		"world.needsNewerCore": "这个世界需要更新版本的应用（它要 {needed}，当前 {local}）。",
		"world.opening": "开局会问你",
		"world.panelAlways": "始终显示",
		"world.panelConditional": "条件显示",
		"world.panelFields": "{count} 项",
		"world.panels": "你会看到的面板",
		"world.play": "在这个世界活一次",
		"world.stale": "正文有改动",
		"world.summary": "{groups} 项开局设定 · {panels} 组面板 · {turn}",
		"world.turnUnit": "以{unit}为一回合",
		"world.unopenable": "这个世界暂时打不开：{problem}",
		"world.unreadableDetail": "这一世读不出来了：{error}"
	},
	en: {
		"app.title": "Endless Worlds",
		"delete.cancel": "Keep it",
		"delete.changed": "A life was begun elsewhere, so the number changed. Look again before deciding.",
		"delete.counting": "Counting who is still alive in this world…",
		"delete.done": "The world was deleted.",
		"delete.doneRestorable": "It can be put back from the shelf.",
		"delete.doneWithLives": "The world was deleted, along with {n} lives.",
		"delete.forever": "This world did not come with the app. Deleting it is final.",
		"delete.go": "Delete the world and {n} lives",
		"delete.goNoLives": "Delete this world",
		"delete.inFlight": "A month is being written in this world. Wait for it to finish, or that month is written for nothing.",
		"delete.noLives": "Nobody has lived in this world yet. Delete it and it leaves the shelf.",
		"delete.restorable": "This world came with the app, so it can be put back — but it returns as it shipped. Your edits do not come back, and neither do the lives.",
		"delete.title": "Delete “{world}”?",
		"delete.typeToConfirm": "To go on, type the world's name: {world}",
		"delete.withLives": "There are {n} lives in this world. Deleting it ends them, and everything already written in them goes with it.",
		"delete.working": "Deleting…",
		"history.beginning": "This is where the life began.",
		"history.chose": "you chose: {action}",
		"history.close": "close the earlier months",
		"history.earlier": "further back",
		"history.none": "No past to read yet — this is the first month.",
		"history.open": "read back through this life",
		"history.reading": "turning back…",
		"history.unreadable": "This life's past could not be read.",
		"library.backendHint": "{path} → {error}. A 404 means the backend module did not load; a disable→enable cycle reloads it.",
		"library.backendSilent": "The backend has not answered.",
		"library.empty": "No worlds yet.",
		"library.lives": "Lives you are living",
		"library.newerSeed": "A newer version of {world} exists ({installed} → {available}). Yours is left as it is.",
		"library.otherWorlds": "Other worlds",
		"library.preparing": "Getting ready…",
		"library.removed": "You removed “{world}”.",
		"library.restore": "Put it back",
		"life.delete.aria": "Delete the life: {name}",
		"life.delete.changed": "This life moved on by a month elsewhere, so the number changed. Look again before deciding.",
		"life.delete.done": "The life was deleted ({n} months lived).",
		"life.delete.doneUnborn": "The unborn life was deleted.",
		"life.delete.forever": "Its world stays, and so does every other life. But this life itself cannot be recovered by any means — its chronicle exists only in its own copy.",
		"life.delete.go": "End this life",
		"life.delete.inFlight": "A month is being written for it. Wait for that to finish, or it is written for nothing.",
		"life.delete.months": "“{name}” has lived {n} months. Deleting it takes everything written in them.",
		"life.delete.reading": "Reading how far this life got…",
		"life.delete.short": "Delete",
		"life.delete.title": "End this life?",
		"life.delete.typeToConfirm": "To go on, type this life's name: {name}",
		"life.delete.unborn": "“{name}” has not been born yet. Deleting it also takes the opening you chose.",
		"life.delete.unreadable": "This life can no longer be read. It cannot be opened, so here is the only place it can be deleted.",
		"life.ended": "Ended",
		"life.generating": "writing this month…",
		"life.turn": "Turn {turn}",
		"life.unborn": "Not yet born",
		"life.unreadable": "This life can no longer be read",
		"life.waiting": "Waiting for you",
		"note.dismiss": "Dismiss",
		"opening.arranging": "The world is arranging the moment of your birth…",
		"opening.backToShelf": "Back to the shelf",
		"opening.begin": "Begin this life",
		"opening.beginning": "Beginning…",
		"opening.continueBirth": "Be born",
		"opening.custom": "Something else…",
		"opening.customPlaceholder": "Write your own",
		"opening.hintPick": "Pick one, or leave it for the world to decide.",
		"opening.hintText": "Leave it blank and the world decides.",
		"opening.keptSafe": "Everything you chose is still here.",
		"opening.next": "Next",
		"opening.notStarted": "This life has not started. Everything you chose is still here.",
		"opening.page": "Page {page} of {pages}",
		"opening.prev": "Back",
		"opening.retry": "Try again",
		"opening.rollAll": "Roll everything",
		"opening.rollOne": "Roll {label}",
		"opening.sealed": "The world settles this one, not you. You will find out when you are born.",
		"opening.silent": "The world did not answer.",
		"opening.styleHint": "This decides how hard the world is on you.",
		"opening.styleLabel": "How this life gets told",
		"opening.waiting.0": "a place in the world is being found…",
		"opening.waiting.1": "the circumstances of a birth are settling…",
		"opening.waiting.2": "the first breath has not been drawn…",
		"opening.waiting.3": "the page is still blank…",
		"play.act": "Do it",
		"play.acting": "…",
		"play.actionPlaceholder": "Or do something else.",
		"play.back": "← Back to the shelf",
		"play.confirmAct": "Act on what you wrote?",
		"play.confirmAsk": "Do this?",
		"play.confirmNo": "Think again",
		"play.confirmYes": "Do it",
		"play.drawerClose": "Put it away",
		"play.drawerOpen": "Look at yourself right now",
		"play.endedBadge": "This life has come to a close.",
		"play.endedMeta": "This life ran for {turn} turns.",
		"play.endedReplay": "Live again in this world",
		"play.endedShelf": "Back to the shelf",
		"play.generating": "This month is being written. You can leave this page; it will be here when you come back.",
		"play.nothingToShow": "Nothing to show yet — this life's panels appear as their own conditions come true.",
		"play.opening": "Opening…",
		"play.retry": "Try again",
		"play.rumour": "Rumour",
		"play.rumourSuffix": " — only hearsay",
		"play.sceneFailed": "This scene could not be drawn.",
		"play.sceneTitle": "Scene",
		"play.silent": "(The world has not spoken yet.)",
		"play.stalled": "The world did not answer. Say it again.",
		"play.turn": "Turn {turn}",
		"play.waiting.0": "the years slip by…",
		"play.waiting.1": "time moves on…",
		"play.waiting.2": "the world turns…",
		"play.waiting.3": "this month is passing…",
		"play.waiting.4": "fate sets down its pen…",
		"play.waiting.5": "the season shifts…",
		"play.waiting.6": "wind crosses the village gate…",
		"play.zoomIn": "Enlarge",
		"play.zoomOut": "Shrink",
		"rail.broken": "{n} more worlds could not be read",
		"rail.label": "Worlds and lives",
		"rail.shelf": "← Back to the shelf",
		"rail.styles": "{n} styles",
		"rail.worlds": "Worlds",
		"shelf.continue": "carry on",
		"shelf.pick": "Pick a life on the left, or open a world.",
		"unit.day": "day",
		"unit.month": "month",
		"unit.season": "season",
		"unit.week": "week",
		"unit.year": "year",
		"world.back": "← Back to the worlds",
		"world.delete": "Delete this world",
		"world.detailLineage": " · can pass through generations",
		"world.detailMeta": "{turn} · {styles} styles{lineage}",
		"world.digest": "What the world reports each turn",
		"world.endings": "{endings} ending conditions · saves keep {save} kinds of thing",
		"world.lineage": "Can pass through generations",
		"world.needsNewerCore": "This world needs a newer version of the app (it asks for {needed}, this is {local}).",
		"world.opening": "What it will ask you",
		"world.panelAlways": "always shown",
		"world.panelConditional": "shown on condition",
		"world.panelFields": "{count} entries",
		"world.panels": "What you will see",
		"world.play": "Live a life here",
		"world.stale": "The rulebook has changed",
		"world.summary": "{groups} opening settings · {panels} panels · {turn}",
		"world.turnUnit": "one {unit} per turn",
		"world.unopenable": "This world cannot be opened: {problem}",
		"world.unreadableDetail": "This life cannot be read: {error}"
	}
};
var current = "zh";
/** Follow the world being played. Unknown codes keep the previous choice. */
function useLanguage(lang) {
	if (lang === "zh" || lang === "en") current = lang;
}
/**
* One string, with `{name}` placeholders filled in.
*
* A missing key returns the key itself rather than an empty string: a screen
* reading `play.turn` is obviously a bug, while a screen with a gap where a
* sentence should be looks like a design choice.
*/
function t(key, vars = {}) {
	const table = TABLES[current];
	const fallback = TABLES.en;
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
	const table = TABLES[current];
	const fallback = TABLES.en;
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
function Prose({ text }) {
	const Md = hostUi()?.MarkdownRenderer;
	if (!text) return /* @__PURE__ */ jsx("p", {
		className: "ew-prose ew-prose-plain",
		children: t("play.silent")
	});
	if (!Md) return /* @__PURE__ */ jsx("p", {
		className: "ew-prose ew-prose-plain",
		children: text
	});
	return /* @__PURE__ */ jsx("div", {
		className: "ew-prose",
		children: /* @__PURE__ */ jsx(Md, {
			content: text,
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
		case "rank": return /* @__PURE__ */ jsxs("span", { children: [f.tier ? /* @__PURE__ */ jsx(Chip, {
			accent: true,
			children: f.tier
		}) : /* @__PURE__ */ jsx("span", {
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
function WorldCard({ world, onOpen }) {
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
	return /* @__PURE__ */ jsxs("button", {
		className: "ew-card",
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
				className: "ew-chips",
				style: { marginBottom: "8px" },
				children: (world.styles ?? []).map((s) => /* @__PURE__ */ jsx(Chip, { children: s }, s))
			}),
			/* @__PURE__ */ jsxs("div", {
				className: "ew-meta",
				children: [t("world.summary", {
					groups: world.openingGroups ?? 0,
					panels: world.panelCount ?? 0,
					turn: turnPhrase(world.clockUnit)
				}), world.stalenessNote ? /* @__PURE__ */ jsx("div", {
					style: { marginTop: "4px" },
					children: world.stalenessNote
				}) : null]
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
function LifeRow({ run, onOpen, onDelete }) {
	const where = run.unreadable ? t("life.unreadable") : run.generating ? t("life.generating") : run.ended ? t("life.ended") : run.awaitingOpening ? t("life.unborn") : t("life.turn", { turn: run.turn });
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
						children: run.subtitle || run.title || run.worldId
					}), run.awaitingOpening ? /* @__PURE__ */ jsx(Chip, {
						accent: true,
						children: t("life.waiting")
					}) : null]
				}),
				run.subtitle ? /* @__PURE__ */ jsx("div", {
					className: "ew-sub",
					children: run.title
				}) : null,
				/* @__PURE__ */ jsx("div", {
					className: "ew-meta",
					children: where
				})
			]
		}), onDelete ? /* @__PURE__ */ jsx("button", {
			className: "ew-btn ew-btn-quiet ew-card-drop",
			type: "button",
			onClick: () => onDelete(run.runId),
			"aria-label": t("life.delete.aria", { name: run.subtitle || run.title || run.runId }),
			children: t("life.delete.short")
		}) : null]
	});
}
function WorldDetailView({ worldId, onBack, onPlay, onDelete }) {
	const [world, setWorld] = useState(null);
	const [error, setError] = useState(null);
	useEffect(() => {
		let alive = true;
		setWorld(null);
		setError(null);
		api.world(worldId).then((w) => {
			if (alive) setWorld(w);
		}).catch((e) => {
			if (alive) setError(e.message);
		});
		return () => {
			alive = false;
		};
	}, [worldId]);
	const back = /* @__PURE__ */ jsx("button", {
		className: "ew-back",
		type: "button",
		onClick: onBack,
		children: t("world.back")
	});
	if (error) return /* @__PURE__ */ jsxs("div", { children: [back, /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("world.unreadableDetail", { error })
	})] });
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
function readDraft(key) {
	try {
		return JSON.parse(localStorage.getItem(key) ?? "null") ?? {};
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
					onClick: () => onPick(value === o ? "" : o),
					children: o
				}, o)), group.custom ? /* @__PURE__ */ jsx("button", {
					type: "button",
					className: `ew-opt${isCustom ? " ew-opt-on" : ""}`,
					onClick: () => onPick(isCustom ? "" : CUSTOM),
					children: t("opening.custom")
				}) : null]
			}), isCustom ? /* @__PURE__ */ jsx("input", {
				className: "ew-input",
				style: { marginTop: "8px" },
				value: custom ?? "",
				maxLength: 200,
				placeholder: t("opening.customPlaceholder"),
				onChange: (e) => onCustom(e.target.value)
			}) : null] }) : /* @__PURE__ */ jsx("input", {
				className: "ew-input",
				type: "text",
				inputMode: group.kind === "number" ? "numeric" : "text",
				value: value === CUSTOM ? "" : value ?? "",
				maxLength: 200,
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
	const [run, setRun] = useState(draft.run ?? null);
	useEffect(() => {
		try {
			localStorage.setItem(draftKey, JSON.stringify({
				answers,
				customs,
				style,
				page,
				run
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
				answers: payload()
			});
			setRun(created.runId);
			await openRun(created.runId);
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
	const load = useCallback(async (before) => {
		setBusy(true);
		setFailed(false);
		try {
			const out = await api.chronicle(runId, before);
			setTurns((have) => before > 0 ? [...have, ...out.turns] : out.turns);
			setMore(out.more);
		} catch {
			setFailed(true);
		}
		setBusy(false);
	}, [runId]);
	useEffect(() => {
		load(0);
	}, [load]);
	if (failed && !turns.length) return /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("history.unreadable")
	});
	if (!turns.length) return /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: busy ? t("history.reading") : t("history.none")
	});
	const oldest = turns[turns.length - 1]?.turn ?? 0;
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-history",
		children: [turns.map((p) => /* @__PURE__ */ jsxs("div", {
			className: "ew-past",
			children: [/* @__PURE__ */ jsxs("div", {
				className: "ew-past-head",
				children: [/* @__PURE__ */ jsx("span", {
					className: "ew-past-turn",
					children: t("play.turn", { turn: p.turn })
				}), p.action ? /* @__PURE__ */ jsx("span", {
					className: "ew-past-action",
					children: t("history.chose", { action: p.action })
				}) : null]
			}), /* @__PURE__ */ jsx(Prose, { text: p.prose })]
		}, p.turn)), more ? /* @__PURE__ */ jsx("button", {
			className: "ew-btn",
			type: "button",
			disabled: busy,
			onClick: () => void load(oldest),
			children: busy ? t("history.reading") : t("history.earlier")
		}) : /* @__PURE__ */ jsx("div", {
			className: "ew-meta",
			children: t("history.beginning")
		})]
	});
}
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
function PlayPage({ runId, onBack, onScene, onReplay, refresh }) {
	const [v, setV] = useState(null);
	const [error, setError] = useState(null);
	const [action, setAction] = useState("");
	const [tapped, setTapped] = useState("");
	const [arm, setArm] = useState("");
	const [phrase, setPhrase] = useState("");
	const [stalled, setStalled] = useState(false);
	const [retry, setRetry] = useState(null);
	const [drawer, setDrawer] = useState(false);
	const [back, setBack] = useState(false);
	const load = useCallback(async () => {
		try {
			setV(await api.run(runId));
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
	useEffect(() => {
		if (!generating) return;
		setPhrase((p) => p || pick("play.waiting"));
		const timer = window.setInterval(() => {
			load();
		}, GENERATING_POLL_MS);
		return () => window.clearInterval(timer);
	}, [generating, load]);
	const busy = !!tapped || generating;
	useEffect(() => {
		useLanguage(v?.language);
	}, [v]);
	useEffect(() => {
		const asking = (v?.scenes ?? []).filter((s) => s.asks && !s.answered);
		onScene(asking.length ? asking[asking.length - 1]?.sceneId ?? "" : "");
	}, [v, onScene]);
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
	if (error) return /* @__PURE__ */ jsxs("div", { children: [/* @__PURE__ */ jsx("button", {
		className: "ew-back",
		type: "button",
		onClick: onBack,
		children: t("play.back")
	}), /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("world.unreadableDetail", { error })
	})] });
	if (!v) return /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("play.opening")
	});
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
		/* @__PURE__ */ jsx("div", {
			className: "ew-note",
			children: busy ? t("opening.arranging") : t("opening.notStarted")
		}),
		generating ? /* @__PURE__ */ jsx("div", {
			className: "ew-note",
			children: t("play.generating")
		}) : null,
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
		/* @__PURE__ */ jsxs("div", {
			className: "ew-bar",
			children: [/* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-go",
				type: "button",
				onClick: () => onReplay(v.worldId),
				children: t("play.endedReplay")
			}), /* @__PURE__ */ jsx("button", {
				className: "ew-btn",
				type: "button",
				onClick: onBack,
				children: t("play.endedShelf")
			})]
		}),
		/* @__PURE__ */ jsx("button", {
			className: "ew-drawer",
			type: "button",
			onClick: () => setBack((b) => !b),
			children: back ? t("history.close") : t("history.open")
		}),
		back ? /* @__PURE__ */ jsx(History, { runId }) : null
	] });
	const main = /* @__PURE__ */ jsxs("div", { children: [
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
		/* @__PURE__ */ jsx(Prose, { text: v.prose }),
		stalled ? /* @__PURE__ */ jsxs("div", {
			className: "ew-note",
			children: [t("play.stalled"), retry ? /* @__PURE__ */ jsx("button", {
				className: "ew-btn ew-btn-sm",
				type: "button",
				disabled: busy,
				style: { marginInlineStart: "8px" },
				onClick: () => void take(retry.payload, retry.what),
				children: t("play.retry")
			}) : null]
		}) : null,
		(v.choices ?? []).length ? /* @__PURE__ */ jsx("div", {
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
		/* @__PURE__ */ jsxs("div", { children: [
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
			generating && !tapped ? /* @__PURE__ */ jsx("div", {
				className: "ew-note ew-note-live",
				children: /* @__PURE__ */ jsx(Waiting, { label: phrase || t("play.generating") })
			}) : null,
			action.length > 400 ? /* @__PURE__ */ jsx("div", {
				className: "ew-count",
				children: `${action.length} / 500`
			}) : null
		] }),
		/* @__PURE__ */ jsx("button", {
			className: "ew-drawer",
			type: "button",
			onClick: () => setBack((b) => !b),
			children: back ? t("history.close") : t("history.open")
		}),
		back ? /* @__PURE__ */ jsx(History, { runId }) : null,
		/* @__PURE__ */ jsx("button", {
			className: "ew-drawer",
			type: "button",
			onClick: () => setDrawer((d) => !d),
			children: drawer ? t("play.drawerClose") : t("play.drawerOpen")
		}),
		drawer ? /* @__PURE__ */ jsx("div", {
			style: { marginTop: "10px" },
			children: (v.panels ?? []).length ? panels : /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: t("play.nothingToShow")
			})
		}) : null
	] });
	return /* @__PURE__ */ jsxs("div", { children: [
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
function WorldRail({ worlds, runs, activeRunId, activeWorldId, onWorld, onLife, onHome }) {
	const playable = (worlds ?? []).filter((w) => w.usable);
	const broken = (worlds ?? []).length - playable.length;
	return /* @__PURE__ */ jsxs("nav", {
		className: "ew-rail",
		"aria-label": t("rail.label"),
		children: [
			/* @__PURE__ */ jsx("button", {
				className: "ew-rail-home",
				type: "button",
				onClick: onHome,
				children: t("rail.shelf")
			}),
			runs.length ? /* @__PURE__ */ jsxs("div", {
				className: "ew-rail-group",
				children: [/* @__PURE__ */ jsx("div", {
					className: "ew-rail-head",
					children: t("library.lives")
				}), runs.map((r) => /* @__PURE__ */ jsxs("button", {
					type: "button",
					disabled: !!r.unreadable,
					className: "ew-rail-row" + (r.runId === activeRunId ? " ew-rail-row-on" : ""),
					onClick: () => onLife(r.runId),
					"aria-current": r.runId === activeRunId ? "page" : void 0,
					children: [/* @__PURE__ */ jsx("span", {
						className: "ew-rail-name",
						children: r.subtitle || r.title || r.worldId
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
	const on = !!(html && sceneId);
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-slot-wrap",
		style: on ? void 0 : { margin: 0 },
		children: [
			failed && sceneId ? /* @__PURE__ */ jsx("div", {
				className: "ew-note",
				children: t("play.sceneFailed")
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
//#region src/styles.css?raw
var styles_default = "/* This app mounts into the DASHBOARD's own document, not an iframe, so every rule\n   here is global. Hence the ew- prefix on every class and zero bare element\n   selectors — an unprefixed .card would repaint the whole dashboard.\n\n   Narrow-first: bare rules are the phone baseline, min-width adds the desktop. */\n\n.ew-root {\n  --ew-gutter: 16px;\n  color: var(--text, #e2e8f0);\n  padding: var(--ew-gutter);\n  /* Scopes any future overlay to this panel instead of the whole dashboard. */\n  position: relative;\n}\n@media (min-width: 768px) {\n  .ew-root { max-width: 900px; margin: 0 auto; --ew-gutter: 24px; }\n}\n\n/* ── the desktop rail ──────────────────────────────────────────────────────\n   Above this width the page splits into a navigation axis and a reading axis.\n   Below it the rail is not rendered at all and the shelf behaves exactly as it\n   always has — the narrow layout is the baseline, not a compromise being undone.\n\n   1100px, not 768: a rail plus a readable measure needs ~1060px, and squeezing\n   both into a tablet gives a cramped rail AND cramped prose. Between 768 and\n   1100 the centred column is still the best use of the space. */\n.ew-rail { display: none; }\n\n@media (min-width: 1100px) {\n  /* The cap moves off .ew-root and onto the reading column, so the rail can sit\n     outside the measure instead of eating into it. */\n  .ew-root { max-width: 1320px; }\n\n  /* One way back, not two. The rail's own \"back to the shelf\" is permanent and\n     always in the same place, so the view's inline back button is a second control\n     doing the same thing three lines below the first — which is exactly how it\n     looked: two identical links stacked in the top-left corner. The inline one is\n     the mobile affordance and stays the only one below this width. */\n  .ew-back { display: none; }\n\n  /* The shelf, once. The rail already lists every life and every world, so the\n     same list in the reading column was the same information twice, side by side.\n     Hidden here rather than removed from the component, because whether the rail\n     exists is a width question and so is this. */\n  .ew-shelflist { display: none; }\n\n  .ew-shell {\n    display: grid;\n    grid-template-columns: 248px minmax(0, 1fr);\n    gap: 32px;\n    align-items: start;\n  }\n\n  .ew-rail {\n    display: block;\n    position: sticky;\n    /* Sticks under the app's own header rather than the viewport top, so the\n       title does not scroll away from the rail it labels. */\n    top: var(--ew-gutter);\n    /* Its own scroll: a shelf with thirty lives must not push the story down. */\n    max-height: calc(100vh - 120px);\n    overflow-y: auto;\n    padding-right: 4px;\n  }\n\n  /* The measure. Prose is the reason this number exists — a life is read, not\n     scanned — so it is set in ch and does not grow with the window. */\n  .ew-main { max-width: 74ch; }\n}\n\n.ew-rail-home {\n  display: block; width: 100%; text-align: left;\n  min-height: 36px; margin-bottom: 14px; padding: 0;\n  background: transparent; border: none; cursor: pointer;\n  color: var(--accent, #7c3aed); font: inherit; font-size: 13px;\n}\n\n.ew-rail-group { margin-bottom: 18px; }\n.ew-rail-head {\n  font-size: 11px; font-weight: 600; letter-spacing: 0.04em;\n  text-transform: uppercase;\n  color: var(--muted, #6b7280);\n  margin-bottom: 6px;\n}\n\n.ew-rail-row {\n  display: block; width: 100%; text-align: left; cursor: pointer;\n  background: transparent;\n  border: none; border-left: 2px solid transparent;\n  border-radius: 0 6px 6px 0;\n  padding: 7px 8px; margin-bottom: 1px;\n  color: inherit; font: inherit;\n}\n.ew-rail-row:hover { background: var(--card, #1f2030); }\n.ew-rail-row:disabled { cursor: default; opacity: 0.45; }\n.ew-rail-row-on {\n  border-left-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 10%, transparent);\n}\n\n.ew-rail-name {\n  display: block; font-size: 13px; line-height: 1.35;\n  /* A world title is user content: one long unbroken run must not widen the\n     grid column, which would push the reading measure sideways. */\n  overflow-wrap: anywhere;\n}\n.ew-rail-sub {\n  display: block; font-size: 11px; color: var(--muted, #6b7280); margin-top: 2px;\n}\n/* Only where the rail is: below it, the shelf list IS the page and this landing\n   would be a second copy of what the list already says. */\n.ew-onlywide { display: none; }\n@media (min-width: 1100px) { .ew-onlywide { display: block; } }\n\n/* ── reading back ── */\n.ew-history { margin-top: 14px; }\n.ew-past { padding-bottom: 6px; margin-bottom: 18px; border-bottom: 1px solid var(--border, #2d2f3d); }\n.ew-past-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }\n.ew-past-turn { font-size: 12px; color: var(--muted, #6b7280); letter-spacing: .04em; }\n.ew-past-action { font-size: 12px; color: var(--accent, #7c3aed); overflow-wrap: anywhere; }\n\n.ew-rail-note {\n  font-size: 11px; color: var(--muted, #6b7280); padding: 6px 8px; line-height: 1.6;\n}\n\n.ew-head { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }\n.ew-head h2 { margin: 0; font-size: 17px; font-weight: 600; }\n@media (min-width: 768px) { .ew-head h2 { font-size: 19px; } }\n\n/* A world name is user content and can be one long unbroken run; without this a\n   phone gets a horizontal scrollbar on the whole page. */\n.ew-title, .ew-detail-title { overflow-wrap: anywhere; }\n\n.ew-card {\n  display: block; width: 100%; text-align: left; cursor: pointer;\n  background: var(--card, #1f2030);\n  border: 1px solid var(--border, #2d2f3d);\n  border-radius: 10px;\n  padding: 12px; margin-bottom: 10px;\n  color: inherit; font: inherit;\n  -webkit-tap-highlight-color: transparent;\n}\n@media (min-width: 768px) { .ew-card { padding: 14px; } }\n.ew-card:active { border-color: var(--accent, #7c3aed); }\n.ew-card-broken { cursor: default; border-left: 3px solid var(--danger, #b91c1c); }\n\n.ew-title { font-size: 15px; font-weight: 600; line-height: 1.35; }\n@media (min-width: 768px) { .ew-title { font-size: 16px; } }\n\n.ew-titlerow {\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;\n}\n.ew-chips { display: flex; gap: 6px; flex-wrap: wrap; }\n\n.ew-chip {\n  border-radius: 9999px; padding: 2px 9px; font-size: 11px;\n  border: 1px solid var(--border, #2d2f3d);\n  color: var(--muted, #6b7280);\n  white-space: nowrap;\n}\n.ew-chip-accent {\n  border-color: transparent;\n  background: color-mix(in oklab, var(--accent, #7c3aed) 16%, transparent);\n  color: var(--accent, #7c3aed);\n}\n\n.ew-meta { font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7; }\n\n/* 44px is the smallest reliably tappable target; a 13px text link with 4px of\n   padding is about 21px, which is a miss on a phone even when it looks fine on a\n   desktop mock. */\n.ew-back {\n  display: inline-flex; align-items: center;\n  min-height: 44px; padding: 0 12px 0 0;\n  background: transparent; border: none; cursor: pointer;\n  color: var(--accent, #7c3aed); font: inherit; font-size: 14px;\n  -webkit-tap-highlight-color: transparent;\n}\n\n.ew-detail-title { margin: 0 0 4px; font-size: 19px; line-height: 1.3; }\n@media (min-width: 768px) { .ew-detail-title { font-size: 22px; } }\n\n.ew-section { font-size: 13px; font-weight: 600; margin: 0 0 7px; }\n.ew-block { margin-bottom: 18px; }\n\n.ew-panel {\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px; margin-bottom: 8px;\n}\n@media (min-width: 768px) { .ew-panel { padding: 10px 12px; } }\n.ew-panel-head {\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 7px;\n}\n.ew-panel-name { font-size: 13px; font-weight: 600; }\n\n.ew-note {\n  font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; margin-top: 10px;\n}\n/* A note that carries an action. The button keeps its own size, so a long sentence\n   wraps instead of squeezing the thing the player is meant to press. */\n.ew-note-row {\n  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;\n  justify-content: space-between;\n}\n\n/* ── the second ask ──\n   Absolute inside the app's own box, NOT fixed — the same rule the scene slot\n   follows and for a sharper reason here: a fixed overlay would cover the\n   dashboard's own navigation, so a modal that failed to close would trap the\n   player in this app. Scoped to .ew-root, the worst case is an app they can\n   still navigate away from. */\n.ew-modal-wrap {\n  position: absolute; inset: 0; z-index: 40;\n  display: flex; align-items: flex-start; justify-content: center;\n  padding: 24px var(--ew-gutter, 8px);\n  background: color-mix(in oklab, var(--bg, #1a1b26) 72%, transparent);\n  /* The app's box can be taller than the viewport; keeping the panel near the top\n     of it means a scrolled page still shows the panel rather than empty scrim. */\n  overflow-y: auto;\n}\n.ew-modal {\n  width: 100%; max-width: 460px; box-sizing: border-box;\n  background: var(--bg-elevated, #21222e); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 12px;\n  padding: 18px; margin-top: 4vh;\n}\n.ew-modal:focus { outline: none; }\n.ew-modal-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; }\n.ew-modal-body { font-size: 14px; line-height: 1.75; margin-bottom: 12px; }\n.ew-modal-note { margin-bottom: 14px; }\n.ew-modal-gate { display: block; margin-bottom: 14px; }\n.ew-modal-gate .ew-meta { display: block; margin-bottom: 6px; }\n.ew-modal-problem {\n  font-size: 13px; line-height: 1.7; margin-bottom: 12px;\n  color: var(--danger, #f87171);\n}\n.ew-modal-bar { margin-top: 0; }\n\n/* What is about to be lost, named. A count alone does not tell the player which\n   life they are ending. */\n.ew-doomed {\n  list-style: none; margin: 0 0 14px; padding: 0;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  max-height: 34vh; overflow-y: auto;\n}\n.ew-doomed li {\n  display: flex; justify-content: space-between; gap: 10px;\n  padding: 8px 12px; font-size: 13px;\n  border-bottom: 1px solid var(--border, #2d2f3d);\n}\n.ew-doomed li:last-child { border-bottom: none; }\n.ew-doomed-name { min-width: 0; overflow-wrap: anywhere; }\n.ew-doomed-where { color: var(--muted, #6b7280); flex: 0 0 auto; font-size: 12px; }\n\n/* ── opening screen ── */\n\n.ew-group { margin-bottom: 20px; }\n.ew-glabel {\n  font-size: 14px; font-weight: 600; margin-bottom: 2px;\n  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;\n}\n.ew-ghint { font-size: 12px; color: var(--muted, #6b7280); margin-bottom: 8px; }\n\n/* Options are buttons, not a select: on a phone a native select opens a modal\n   wheel for six words, and the words are the whole point of this screen. */\n.ew-opt {\n  border-radius: 9999px; padding: 7px 13px; font-size: 13px;\n  border: 1px solid var(--border, #2d2f3d); background: transparent;\n  color: var(--text, #e2e8f0); cursor: pointer; font: inherit;\n  min-height: 36px; -webkit-tap-highlight-color: transparent;\n}\n.ew-opt-on {\n  border-color: transparent; color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 18%, transparent);\n}\n\n.ew-input {\n  width: 100%; box-sizing: border-box;\n  background: var(--bg, #1a1b26); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; font: inherit; font-size: 15px;\n  min-height: 44px;\n}\n.ew-input:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n\n.ew-sealed {\n  border: 1px dashed var(--border, #2d2f3d); border-radius: 8px;\n  padding: 10px 12px; font-size: 12px; color: var(--muted, #6b7280); line-height: 1.7;\n}\n\n.ew-bar {\n  display: flex; gap: 8px; flex-wrap: wrap; align-items: center;\n  margin-top: 20px; padding-top: 16px;\n  border-top: 1px solid var(--border, #2d2f3d);\n}\n.ew-btn {\n  border-radius: 8px; padding: 0 16px; min-height: 44px;\n  border: 1px solid var(--border, #2d2f3d); background: transparent;\n  color: var(--text, #e2e8f0); font: inherit; font-size: 14px; cursor: pointer;\n  -webkit-tap-highlight-color: transparent;\n}\n.ew-btn-go {\n  border-color: transparent; background: var(--accent, #7c3aed); color: #fff;\n  font-weight: 600; flex: 1; min-width: 140px;\n}\n.ew-btn:disabled, .ew-btn-go:disabled { opacity: .5; cursor: default; }\n\n/* Destructive, and it must read that way BEFORE it is pressed. Colour is not the\n   safeguard (the dialog is), but a delete that looks like every other button is a\n   delete the player presses while reading something else. */\n.ew-btn-danger {\n  border-color: var(--danger, #f87171);\n  color: var(--danger, #f87171);\n  background: color-mix(in oklab, var(--danger, #f87171) 12%, transparent);\n  flex: 0 0 auto;\n}\n/* The way OUT of a destructive path, and the way INTO one from a page whose\n   subject is something else. Quiet on purpose. */\n.ew-btn-quiet {\n  color: var(--muted, #6b7280); border-color: transparent;\n  flex: 0 0 auto; min-height: 36px; padding: 0 12px; font-size: 13px;\n}\n.ew-btn-quiet:hover { color: var(--text, #e2e8f0); }\n.ew-spacer { flex: 1; }\n@media (min-width: 768px) { .ew-btn-go { flex: 0 0 auto; } }\n\n/* ── prose ── */\n\n/* Reading typography, not UI typography — this is the only place the player reads\n   for minutes at a time. */\n.ew-prose {\n  font-size: 16px; line-height: 1.85; max-width: 66ch; margin: 12px 0 0;\n}\n/* Only the fallback path needs pre-wrap. With the host's markdown renderer,\n   paragraphs are real elements and pre-wrap would double every blank line. */\n.ew-prose-plain { white-space: pre-wrap; }\n.ew-prose p { margin: 0 0 1.1em; }\n.ew-prose p:last-child { margin-bottom: 0; }\n.ew-prose em { font-style: italic; }\n.ew-prose h1, .ew-prose h2, .ew-prose h3 {\n  font-size: 1.05em; font-weight: 600; margin: 1.4em 0 .5em;\n}\n.ew-prose blockquote {\n  margin: 1em 0; padding-left: 12px;\n  border-left: 2px solid var(--border, #2d2f3d); color: var(--muted, #6b7280);\n}\n.ew-prose ul, .ew-prose ol { margin: .8em 0; padding-left: 1.4em; }\n.ew-prose li { margin: .25em 0; }\n\n/* ── play page ── */\n\n/* Narrow-first single column; panels move to a sidebar from 900px. Below that the\n   sidebar is absent entirely and the drawer is how panels stay reachable —\n   rendering both would put every panel on screen twice. */\n.ew-play { display: block; }\n.ew-aside { display: none; }\n@media (min-width: 900px) {\n  .ew-play {\n    display: grid; grid-template-columns: minmax(0,1fr) 300px; gap: 28px; align-items: start;\n  }\n  .ew-aside { display: block; position: sticky; top: 12px; }\n}\n\n.ew-clock {\n  font-size: 12px; color: var(--muted, #6b7280); letter-spacing: .04em; margin-bottom: 4px;\n}\n\n.ew-digest { margin: 0 0 20px; }\n.ew-drow {\n  display: flex; gap: 8px; padding: 6px 0; font-size: 13px; line-height: 1.7;\n  border-bottom: 1px solid var(--border, #2d2f3d);\n}\n.ew-drow-rumour { color: var(--muted, #6b7280); font-style: italic; }\n.ew-dcat { color: var(--muted, #6b7280); flex: 0 0 auto; min-width: 4.5em; }\n\n/* Panels keep UI type while the prose gets reading type — a stat block read at\n   16/1.85 is harder to scan, not easier. */\n.ew-panel-box {\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  padding: 12px; margin-bottom: 10px; font-size: 13px;\n}\n.ew-panel-quiet { opacity: .55; }\n.ew-prow { display: flex; gap: 10px; align-items: baseline; padding: 5px 0; line-height: 1.6; }\n.ew-plabel { color: var(--muted, #6b7280); flex: 0 0 5.5em; }\n.ew-pval { flex: 1; min-width: 0; overflow-wrap: anywhere; }\n.ew-gap { color: var(--border, #2d2f3d); }\n\n/* A label that is really a sentence. Measured on the live flagship: the narrator\n   wrote a whole clause into a label slot, and the fixed 5.5em column wrapped it to\n   ten lines beside a single dot. Stacking costs one line of height and makes the row\n   readable; keeping the column costs ten and does not. */\n.ew-prow-stack { display: block; }\n.ew-prow-stack .ew-plabel { flex: none; margin-bottom: 2px; line-height: 1.55; }\n.ew-prow-stack .ew-pval { margin-left: 0; }\n\n.ew-bar-track {\n  height: 4px; border-radius: 2px; margin-top: 5px;\n  background: var(--border, #2d2f3d); overflow: hidden;\n}\n.ew-bar-fill { height: 100%; background: var(--accent, #7c3aed); }\n\n.ew-list { margin: 0; padding: 0; list-style: none; }\n.ew-list li { padding: 2px 0; }\n.ew-sub { color: var(--muted, #6b7280); }\n/* The world's name, demoted to a second line now that the life's own identity holds\n   the first. Small: it is the same string on every row, so it is context, not news. */\n.ew-card .ew-sub { display: block; font-size: 12px; margin-bottom: 2px; }\n\n.ew-choices { display: flex; flex-direction: column; gap: 8px; margin: 20px 0 0; }\n.ew-choice {\n  text-align: left; width: 100%; box-sizing: border-box;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  background: var(--card, #1f2030); color: var(--text, #e2e8f0);\n  padding: 12px 14px; font: inherit; font-size: 14px; line-height: 1.5;\n  min-height: 48px; cursor: pointer; -webkit-tap-highlight-color: transparent;\n}\n.ew-choice:active { border-color: var(--accent, #7c3aed); }\n.ew-choice:disabled { opacity: .5; cursor: default; }\n\n/* The one that was chosen. Kept at full opacity while its siblings dim, because\n   the point of the waiting state is to confirm WHICH choice was taken — a row where\n   every option is equally grey has answered a different question. */\n.ew-choicewrap { margin-bottom: 8px; }\n.ew-choice { position: relative; overflow: hidden; }\n.ew-choice-label { position: relative; z-index: 1; }\n\n/* Armed: chosen, not yet done. Reads as a held breath — brighter and slightly\n   raised, but explicitly NOT the accent fill the committing state uses, so the two\n   are never confused at a glance. */\n.ew-choice-armed {\n  border-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 8%, var(--card, #1f2030));\n  transform: translateY(-1px);\n  transition: transform .14s ease, background .14s ease, border-color .14s ease;\n}\n\n.ew-choice-waiting {\n  opacity: 1 !important;\n  border-color: var(--accent, #7c3aed);\n  background: color-mix(in oklab, var(--accent, #7c3aed) 12%, var(--card, #1f2030));\n}\n/* A light sweeping across the chosen line, once every couple of seconds. Chosen\n   over a spinner because it belongs to the SENTENCE the player picked rather than\n   to the page: what is being waited on is that line becoming a month. */\n.ew-choice-waiting::after {\n  content: ''; position: absolute; inset: 0; z-index: 0;\n  background: linear-gradient(\n    100deg,\n    transparent 20%,\n    color-mix(in oklab, var(--accent, #7c3aed) 22%, transparent) 50%,\n    transparent 80%\n  );\n  transform: translateX(-100%);\n  animation: ew-sweep 2.1s ease-in-out infinite;\n}\n\n/* ── the second step ──────────────────────────────────────────────────────\n   A turn is a month of a life and cannot be undone, so committing one is its own\n   deliberate act. The row appears under the armed choice rather than in a modal:\n   a dialog would take the sentence being decided off the screen. */\n.ew-confirm {\n  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;\n  padding: 8px 4px 2px 14px;\n  animation: ew-rise .16s ease-out;\n}\n.ew-confirm-act { padding-left: 0; }\n.ew-confirm-ask { font-size: 13px; color: var(--muted, #6b7280); margin-right: 2px; }\n.ew-btn-sm { min-height: 36px; padding: 0 14px; font-size: 13px; flex: 0 0 auto; }\n.ew-note-live { display: flex; align-items: center; margin-top: 10px; }\n\n/* ── waiting ──────────────────────────────────────────────────────────────\n   The app's only animation, introduced with its reduced-motion answer in the same\n   edit rather than after: idle motion like this reads as pleasant to most people\n   and as a symptom to someone with a vestibular disorder, and retrofitting the\n   media query means shipping the version without it. */\n\n.ew-wait {\n  display: inline-flex; align-items: center; gap: 8px;\n  vertical-align: middle; margin-left: 8px; position: relative; z-index: 1;\n}\n.ew-wait-dots { display: inline-flex; gap: 4px; }\n.ew-wait-label { font-size: 12px; color: var(--muted, #6b7280); }\n\n.ew-dot {\n  width: 5px; height: 5px; border-radius: 50%;\n  background: currentColor; opacity: .35;\n  animation: ew-pulse 1.1s ease-in-out infinite;\n}\n/* Staggered, so the group reads as one moving thing rather than three blinking\n   ones. */\n.ew-dot:nth-child(2) { animation-delay: .18s; }\n.ew-dot:nth-child(3) { animation-delay: .36s; }\n\n@keyframes ew-pulse {\n  0%, 80%, 100% { opacity: .25; transform: scale(.8); }\n  40%           { opacity: 1;   transform: scale(1); }\n}\n@keyframes ew-sweep {\n  0%        { transform: translateX(-100%); }\n  60%, 100% { transform: translateX(100%); }\n}\n@keyframes ew-rise {\n  from { opacity: 0; transform: translateY(-3px); }\n  to   { opacity: 1; transform: none; }\n}\n\n@media (prefers-reduced-motion: reduce) {\n  /* Not \"animation: none\" alone — that would leave three barely-visible dots and\n     no signal at all. Every indicator stays; they simply stop moving. */\n  .ew-dot { animation: none; opacity: .75; }\n  .ew-choice-waiting::after { animation: none; transform: none; opacity: .35; }\n  .ew-confirm { animation: none; }\n  .ew-choice-armed { transition: none; transform: none; }\n}\n\n.ew-act { display: flex; gap: 8px; margin-top: 12px; align-items: flex-end; }\n.ew-act textarea {\n  flex: 1; min-width: 0; box-sizing: border-box; resize: vertical;\n  min-height: 44px; max-height: 40vh;\n  background: var(--bg, #1a1b26); color: var(--text, #e2e8f0);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  padding: 11px 12px; font: inherit; font-size: 15px; line-height: 1.5;\n}\n.ew-act textarea:focus { outline: 2px solid var(--accent, #7c3aed); outline-offset: 1px; }\n\n.ew-count { font-size: 11px; color: var(--muted, #6b7280); margin-top: 4px; }\n\n/* The drawer is how panels stay reachable on a phone without pushing the prose\n   off the first screen. */\n.ew-drawer {\n  width: 100%; margin: 20px 0 0;\n  border: 1px solid var(--border, #2d2f3d); border-radius: 10px;\n  background: transparent; color: var(--text, #e2e8f0);\n  font: inherit; font-size: 13px; min-height: 44px; cursor: pointer;\n}\n@media (min-width: 900px) { .ew-drawer { display: none; } }\n\n/* ── the scene slot ── */\n\n/* ONE element, created on first need and never moved. Moving an iframe in the DOM\n   reloads it, so re-parenting a mounted scene would throw away whatever the player\n   was looking at — and a React portal does not help, because the browser's rule is\n   about the element's position in the document, not about who rendered it. */\n.ew-slot {\n  display: none;\n  width: 100%;\n  border: 1px solid var(--border, #2d2f3d);\n  border-radius: 10px;\n  background: var(--card, #1f2030);\n  /* A scene is a picture, not a page: it never becomes the scrolling thing. */\n  overflow: hidden;\n}\n.ew-slot-on { display: block; height: 320px; }\n\n/* Fullscreen is the SAME element with different geometry. Absolute inside the\n   app's own box rather than fixed: position fixed escapes the panel entirely and\n   would put a scene over the dashboard's own chrome. */\n.ew-slot-full {\n  display: block;\n  position: absolute; inset: 0;\n  height: auto; z-index: 20;\n  border-radius: 0;\n}\n\n.ew-slot-wrap { position: relative; margin: 16px 0 0; }\n.ew-slot-bar {\n  display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 6px;\n}\n.ew-slot-bar-full { position: absolute; top: 8px; right: 8px; z-index: 21; margin: 0; }\n.ew-slot-btn {\n  min-height: 36px; padding: 0 12px; font: inherit; font-size: 12px;\n  color: var(--text, #e2e8f0); background: var(--card, #1f2030);\n  border: 1px solid var(--border, #2d2f3d); border-radius: 8px; cursor: pointer;\n  -webkit-tap-highlight-color: transparent;\n}\n\n/* A shelf row that carries its own destructive control. The row is a div and the\n   open action is a button INSIDE it, because a button cannot contain a button --\n   and the delete has to be a sibling, not a nested child. */\n.ew-card-row { display: flex; align-items: stretch; gap: 0; padding: 0; overflow: hidden; }\n.ew-card-open {\n  flex: 1 1 auto; min-width: 0; text-align: left; font: inherit;\n  background: transparent; border: none; color: inherit; cursor: pointer;\n  /* 12px, matching .ew-card, so a life row is inset exactly like a world card. */\n  padding: 12px; -webkit-tap-highlight-color: transparent;\n}\n.ew-card-open:disabled { opacity: .55; cursor: default; }\n/* Aligned to the top of the row rather than centred: a row is two or three lines\n   tall, and a vertically centred control drifts as the row's text grows. */\n.ew-card-drop {\n  align-self: flex-start; margin: 10px 10px 0 0; border-radius: 8px;\n}\n";
//#endregion
//#region src/main.tsx
/** Where the player was, so leaving the page does not throw them back to the
*  shelf. Prefixed because this app mounts inside the dashboard's own document
*  and shares its localStorage. */
var WHERE = "endless-worlds:where";
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
	const [selected, setSelected] = useState(null);
	const [world, setWorld] = useState(null);
	const [live, setLive] = useState(null);
	const [scene, setScene] = useState("");
	const [refresh, setRefresh] = useState(0);
	/** Which world's deletion is being confirmed, or null. Held here rather than in
	*  the detail view because the reload that follows a deletion unmounts that
	*  view — a dialog owned by it would vanish mid-request. */
	const [doomed, setDoomed] = useState(null);
	/** Which life's deletion is being confirmed, or null. */
	const [doomedLife, setDoomedLife] = useState(null);
	const [note, setNote] = useState("");
	const load = useCallback(async () => {
		setError(null);
		try {
			const d = await api.worlds();
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
	}, []);
	useEffect(() => {
		load();
	}, [load]);
	useEffect(() => {
		const where = recall();
		if (!where) return;
		if (where.view === "live" && where.runId) {
			setLive(where.runId);
			setView("live");
			return;
		}
		if (where.view === "opening" && where.worldId) api.world(where.worldId).then((w) => {
			setWorld(w);
			setView("opening");
		}).catch(() => {});
	}, []);
	const home = () => {
		forget();
		setView("library");
		setSelected(null);
		setWorld(null);
		setLive(null);
		setScene("");
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
		setScene("");
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
	let body;
	if (view === "live" && live) body = /* @__PURE__ */ jsx(PlayPage, {
		runId: live,
		onBack: home,
		onScene: setScene,
		onReplay: openWorld,
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
		onPlay: (w) => {
			remember({
				view: "opening",
				worldId: w.worldId
			});
			useLanguage(w.language);
			setWorld(w);
			setView("opening");
		}
	});
	else if (error) body = /* @__PURE__ */ jsxs("div", {
		className: "ew-meta",
		children: [/* @__PURE__ */ jsx("div", {
			style: { marginBottom: "6px" },
			children: t("library.backendSilent")
		}), /* @__PURE__ */ jsx("div", { children: t("library.backendHint", {
			path: "/worlds",
			error
		}) })]
	});
	else if (!worlds) body = /* @__PURE__ */ jsx("div", {
		className: "ew-meta",
		children: t("library.preparing")
	});
	else {
		const newest = runs.find((r) => !r.unreadable && !r.ended);
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
				children: [runs.length ? /* @__PURE__ */ jsxs(Fragment, { children: [
					/* @__PURE__ */ jsx("div", {
						className: "ew-section",
						children: t("library.lives")
					}),
					runs.map((r) => /* @__PURE__ */ jsx(LifeRow, {
						run: r,
						onOpen: enterLife,
						onDelete: setDoomedLife
					}, r.runId)),
					/* @__PURE__ */ jsx("div", {
						className: "ew-section",
						style: { marginTop: "22px" },
						children: t("library.otherWorlds")
					})
				] }) : null, worlds.length === 0 ? /* @__PURE__ */ jsx("div", {
					className: "ew-meta",
					children: t("library.empty")
				}) : worlds.map((w) => /* @__PURE__ */ jsx(WorldCard, {
					world: w,
					onOpen: openWorld
				}, w.worldId))]
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
	return /* @__PURE__ */ jsxs("div", {
		className: "ew-root",
		children: [
			/* @__PURE__ */ jsx("style", { children: styles_default }),
			/* @__PURE__ */ jsxs("div", {
				className: "ew-head",
				children: [/* @__PURE__ */ jsx(Glyph, {}), /* @__PURE__ */ jsx("h2", { children: t("app.title") })]
			}),
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
					onHome: home
				}), /* @__PURE__ */ jsx("div", {
					className: "ew-main",
					children: body
				})]
			}),
			/* @__PURE__ */ jsx(SceneSlot, {
				runId: live,
				sceneId: scene,
				onChoice: onSceneChoice
			}),
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
	});
}
//#endregion
export { EndlessWorlds as default };
