# Narrator, content, and settings (`narrator.py`, `content.py`, `settings.py`)

The narrator is a packaged agent driven in an app-owned chat slot, one slot per
life. Three concerns meet here: how the agent is sealed and wired so it can reach
this app's tools and nothing else (`narrator.py` + `agents/narrator.json`); how
every line the narrator is spoken to is looked up by the *world's* language rather
than a user setting (`content.py`); and how the player's model and reasoning-effort
choice is stored and applied to the slot at dispatch (`settings.py`). None of the
three trusts the narrator: not with the player's memory, not with a language the
world did not declare, and not with an effort string that becomes a subprocess
argument.

## Layout

| Path | What it is |
|---|---|
| `agents/narrator.json` | the packaged agent: `name` `endless-narrator`, `model` `auto`, `tools` == `allowedTools` == the single ref `@endless-worlds:endless-mcp`, and no `mcpServers` of its own |
| `backend/narrator.py` | slot lifecycle + the seal: `ensure_narrator_slot_ex()` (ownership + memory-mode guards), `_apply_choice()`, and the constants `NARRATOR_AGENT`, `OWN_SERVER_REF`, `MEMORY_MODE` |
| `backend/content.py` | `Content(language)` — one language's text with English behind it: `resolve()`, `__call__()`, `_table()` |
| `content/{en,zh}.json` | the text tables themselves (prompt lines, shape descriptions, separators) |
| `backend/settings.py` | `read_settings()` / `write_settings()` over `<data>/settings.json`, and `REASONING_EFFORTS` |

## Load-bearing contracts

- **The agent can reach this app's own tools and nothing else.** `narrator.json`
  declares no filesystem, shell, network, or other MCP server — only the one ref.
  This is the R26 control: the narrator must not read or write the player's memory,
  and while `memory_mode="temporary"` blocks memory context injection and the
  consolidator, a direct memory *tool* call is a third path only the `tools`
  allowlist closes (the temporary-mode prompt prefix telling the model not to call
  memory tools is advice a model can ignore). Pinned by
  `test_the_narrator_can_reach_nothing_but_this_apps_own_tools`.

- **The tool ref is the namespaced key, and the bare key resolves to zero tools.**
  The ref must be `@endless-worlds:endless-mcp` (`OWN_SERVER_REF`), not the bare
  `@endless-mcp`. Registration writes every app server under
  `f"{app_name}:{server_name}"` and merges those entries, unrenamed, into the
  materialized agent's `mcpServers`; kiro-cli resolves `@x` against those keys, so
  the bare form matches nothing and is dropped silently at mount time — no error,
  no log, just an agent with no tools. Pinned by
  `test_the_tool_ref_uses_the_namespaced_key_registration_actually_writes`; the
  agent declares no `mcpServers` of its own, since a hand-written entry would
  shadow the framework-injected one
  (`test_the_agent_declares_no_mcp_servers_of_its_own`).

- **`allowedTools` equals `tools` because the slot is unattended.** An app-owned
  narrator slot has no human at the approval prompt, so a server that is granted
  but not auto-approved would have every call resolve to *rejected*. The app never
  grants itself trust at runtime — no `_trust`, no `_trusted_patterns`; approval-free
  play comes only from the packaged agent's declared allowlist, which the
  governance ceiling can still veto. Pinned by
  `test_auto_approve_is_declared_because_an_unattended_prompt_means_rejected` and
  `test_this_app_never_grants_itself_tool_approval`; the packaged server must also
  be launchable as an external app
  (`test_the_apps_own_server_is_launchable_as_an_external_app`) and carry no
  unresolved placeholder token, which would make the agent silently fail to
  register (`test_no_unresolvable_placeholder_token_in_the_agent_file`).

- **A slot is used only if it is owned by this app and sealed from memory.**
  `ensure_narrator_slot_ex()` creates the slot scoped to this app and refuses one
  another app owns rather than adopting it; `MEMORY_MODE` is `temporary` and
  nothing else, and a slot whose mode is anything else — including `incognito`,
  which still *reads* memory — is refused, never narrated into and never fallen
  back from. Pinned by `test_an_unsealed_slot_is_refused_rather_than_narrated_into`,
  `test_there_is_no_fallback_to_an_unsealed_slot`, and
  `test_only_temporary_blocks_memory_reads`; a malformed run id never becomes a slot
  key or a filename (`test_a_malformed_run_id_never_becomes_a_slot_key`).

- **The model is `auto`; the concrete choice is applied per slot at dispatch.**
  `narrator.json` carries `model: auto` and no reasoning field — the player's
  choice is a per-slot setting, not baked into the agent. `_apply_choice()` sets
  the model and reasoning effort on the slot, treating empty string as "leave the
  agent's own default" so an unset preference never forces a concrete id, and it is
  re-applied to an *existing* slot too, so a change made on the home page takes
  effect on the very next turn of a life already in progress. The narrator's prompt
  leaks no implementation vocabulary to the player — words like "panels" or
  "schemas" appear only inside the sentence prohibiting them
  (`test_the_narrators_prompt_leaks_no_implementation_vocabulary_to_the_player`).

- **The world selects the language, not the caller.** `Content(language)` takes its
  language from the world pack's `language` value: a world whose header says
  `language: zh` is a Chinese world with a Chinese rulebook, and narrating it in
  English would mismatch its own source material. `resolve()` maps an unknown
  language to the `en` fallback — the table guaranteed complete — rather than
  refusing the world. Pinned by
  `test_the_opening_prompt_takes_its_language_from_the_world_not_the_caller` and
  `test_an_unknown_language_falls_back_instead_of_failing`.

- **`key` is positional-only, and a missing key returns the key.** `Content.__call__`
  takes `key` positionally so a placeholder literally named `key`
  (`text("turn.state.group", key=...)`) cannot collide with the parameter — the
  placeholder names come from the tables and cannot be constrained. A missing key
  returns the key string itself, and an unknown `{placeholder}` is left as-is,
  because a visibly broken prompt is safer than a silent gap that reads as a
  complete prompt which simply never asked for anything. Pinned by
  `test_a_missing_key_returns_the_key`.

- **No prompt module carries user-facing language in a string literal — punctuation
  included.** An AST scan of the prompt-building modules rejects CJK in string
  literals, and the scanned set covers punctuation (fullwidth forms such as the
  ideographic comma, full stop, and corner-bracket quotes), not
  only ideographs, because a hardcoded ideographic comma once joined an English world's field
  list with a Chinese comma no ideograph-only scan would catch. Separators are
  themselves content. Pinned by
  `test_no_prompt_module_carries_language_in_a_string_literal`,
  `test_the_scan_would_catch_a_bare_separator`, and
  `test_the_separators_are_content_too`. The tables carry identical keys and
  matching placeholder slots, every key the prompt modules ask for exists, and all
  three prompt builders actually consult the table — pinned by
  `test_both_tables_carry_the_same_keys`,
  `test_a_placeholder_missing_from_one_table_is_a_failure`,
  `test_every_key_the_prompt_modules_ask_for_exists`, and
  `test_the_three_prompt_builders_all_read_the_table`.

- **Route call-site keyword arguments are checked against the callee's signature.**
  No test executes a route handler, so a keyword argument added at a call site — a
  `language=` passed to a `compose_opening_prompt()` that has no such parameter —
  would pass every unit test and ship as a live `TypeError`. An AST guard inspects
  the call sites in `routes.py` against the real callee signatures instead. Pinned
  by `test_every_keyword_at_a_route_call_site_exists_in_the_callee`.

- **An unknown reasoning effort is coerced before it can become a subprocess
  argument.** `write_settings()` validates `reasoningEffort` against
  `REASONING_EFFORTS` and stores an unknown value as `""` (the default) rather than
  passing it onward, because it becomes an argument to the model subprocess
  downstream; `model` is an explicit pick from the advertised list and stored
  verbatim. A damaged or non-object settings file reads as the default rather than
  raising — a preference is never worth failing a page over — and the write is
  atomic (tmp + rename). Pinned by `test_an_unknown_effort_is_coerced_to_default`,
  `test_a_damaged_file_reads_as_default`, `test_round_trip`, and
  `test_defaults_when_nothing_saved`.
