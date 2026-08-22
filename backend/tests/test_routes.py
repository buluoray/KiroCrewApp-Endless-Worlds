"""Route-module tests.

The one that earns its place is ``test_every_global_a_handler_uses_resolves``.
A route handler is never executed by the rest of the suite — the tests exercise
``view.world_detail`` and ``turn.advance_turn`` directly — so a name the handler
references but the module never imported is invisible to both pytest and
``py_compile``: a NameError is a RUNTIME error. That is exactly how
``world_detail`` shipped missing from ``routes.py``'s import line and turned the
world page into an HTTP 500.
"""

from __future__ import annotations

import builtins
import symtable
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

ROUTES = _BACKEND / "routes.py"


@pytest.fixture(scope="module")
def routes_mod():
    try:
        import routes
    except Exception as exc:  # pragma: no cover — environment-dependent
        pytest.skip(f"routes.py not importable here: {exc}")
    return routes


def _global_reads(src: str, filename: str) -> dict[str, set[str]]:
    """Per-function, the names that will be looked up in module globals.

    ``symtable`` is the compiler's own view, so this asks the same question the
    interpreter will ask at call time — rather than re-implementing scope rules
    over an AST, which is where a hand-rolled version gets it wrong.
    """
    top = symtable.symtable(src, filename, "exec")
    out: dict[str, set[str]] = {}

    def walk(table: symtable.SymbolTable, path: str) -> None:
        if table.get_type() == "function":
            names = {
                s.get_name() for s in table.get_symbols() if s.is_global() and not s.is_assigned()
            }
            if names:
                out[path] = names
        for child in table.get_children():
            walk(child, f"{path}.{child.get_name()}" if path else child.get_name())

    for child in top.get_children():
        walk(child, child.get_name())
    return out


def test_a_reload_actually_reloads_this_apps_own_modules(routes_mod):
    """A named regression, and a platform fact worth stating.

    An app disable→enable re-executes ``routes.py`` but does NOT unload the
    sibling modules it imported: they sit in ``sys.modules`` under bare names for
    the life of the gateway process. So after editing ``scenes.py``, the fresh
    ``routes`` imported the OLD ``scenes`` and failed with
    ``cannot import name 'AlreadyAnswered' from 'scenes'`` while the file on disk
    plainly had it — and no number of disable→enable cycles could fix it.
    """
    assert hasattr(routes_mod, "_drop_stale_siblings")


def _fake(name: str, path) -> object:
    import types

    module = types.ModuleType(name)
    module.__file__ = str(path)
    return module


def test_the_purge_is_skipped_on_the_live_mapping_under_the_test_suite(routes_mod):
    """Not tidiness. Purging swaps module identity underneath anything already
    holding a reference, and across many test files in one process that is
    order-dependent: a ``monkeypatch`` can land on one copy of a module while the
    code under test uses another. The gateway does exactly one load per enable, so
    the hazard exists only here."""
    import sys as _sys

    assert routes_mod._UNDER_TEST is True
    before = _sys.modules.get("view")
    assert before is not None
    routes_mod._drop_stale_siblings()
    assert _sys.modules.get("view") is before, "the purge ran against the live mapping"


def test_a_module_from_this_app_is_dropped(routes_mod, tmp_path):
    """The behaviour the whole function exists for, proven against a throwaway
    mapping — verifying it against the live one would perform the very identity
    swap the guard exists to avoid, which is how an earlier version of this test
    broke an unrelated one two files away."""
    mine = _fake("scenes", Path(routes_mod._HERE) / "scenes.py")
    modules = {"scenes": mine}
    routes_mod._drop_stale_siblings(modules)
    assert "scenes" not in modules


def test_a_foreign_module_squatting_on_a_name_this_app_owns_is_evicted(routes_mod, tmp_path):
    """The bug that shipped, as a test.

    After this app was renamed and reinstalled under a new id, the new install
    failed to load with ``cannot import name 'Chapter' from 'template'`` — and the
    path in that message was the OLD app's ``template.py``, still held by the live
    gateway after its app had been uninstalled. ``sys.modules`` is consulted before
    ``sys.path``, so a bare name this app imports can hand it another app's file.

    An earlier revision deliberately left this alone, reasoning that purging
    someone else's module would break them to fix us. Right about the risk, wrong
    about the conclusion: a foreign occupant of a name this app imports is not a
    module it can politely ignore, it is the module it is about to be handed
    instead of its own.

    Backed by a REAL file outside the app directory. An earlier version of this
    test pointed at a path that did not exist, so ``resolve()`` raised and the
    module was skipped for the wrong reason — it passed whether or not the path
    check was there, which a mutation run exposed.
    """
    assert "view" in routes_mod._MY_MODULES, "this test needs a name the app owns"
    elsewhere = tmp_path / "view.py"
    elsewhere.write_text("# another app's module\n", encoding="utf-8")
    intruder = _fake("view", elsewhere)
    modules = {"view": intruder}
    routes_mod._drop_stale_siblings(modules)
    assert "view" not in modules, (
        "a foreign module kept a name this app imports, so the next import gets it"
    )


def test_a_module_under_a_name_this_app_does_not_own_is_left_alone(routes_mod, tmp_path):
    """The half of the old rule that is still right, and load-bearing.

    Eviction is scoped to the names this app has files for. Without that scope the
    purge would reach the gateway's own modules and every other app's — breaking
    them to fix us, which is the objection the earlier revision was built around
    and which this scope answers properly.
    """
    name = "not_a_module_this_app_has"
    assert name not in routes_mod._MY_MODULES
    elsewhere = tmp_path / f"{name}.py"
    elsewhere.write_text("# the gateway's own module\n", encoding="utf-8")
    stranger = _fake(name, elsewhere)
    modules = {name: stranger}
    routes_mod._drop_stale_siblings(modules)
    assert modules.get(name) is stranger, "a module this app does not own was purged"


def test_a_squatter_with_no_file_is_evicted_too(routes_mod):
    """A namespace package or C extension under one of this app's names is not this
    app's module either, and offers no path to compare. Keeping it would fail the
    import for a reason no message explains."""
    import types as _types

    ghost = _types.ModuleType("template")  # no __file__
    modules = {"template": ghost}
    routes_mod._drop_stale_siblings(modules)
    assert "template" not in modules


def test_the_purge_never_drops_the_route_module_itself(routes_mod):
    """Dropping itself mid-execution would leave a half-initialised module in the
    importer's hands."""
    name = routes_mod.__name__
    modules = {name: routes_mod}
    routes_mod._drop_stale_siblings(modules)
    assert modules.get(name) is routes_mod, "the route module purged itself"


def test_every_global_a_handler_uses_resolves(routes_mod):
    src = ROUTES.read_text(encoding="utf-8")
    available = set(vars(routes_mod)) | set(dir(builtins))

    missing: dict[str, list[str]] = {}
    for func, names in _global_reads(src, str(ROUTES)).items():
        gaps = sorted(n for n in names if n not in available)
        if gaps:
            missing[func] = gaps

    assert not missing, f"names used but never imported: {missing}"


def test_the_missing_import_that_caused_the_500_is_present(routes_mod):
    """A named regression."""
    assert hasattr(routes_mod, "world_detail")
    assert hasattr(routes_mod, "build_play_view")


def test_every_declared_route_points_at_a_real_handler(routes_mod):
    """A route naming a handler that does not exist would 500 on first request."""

    class _Ctx:
        name = "endless-worlds"
        data_dir = Path("/tmp/does-not-matter")
        storage = None

    for route in routes_mod.register_routes(_Ctx()):
        assert callable(route.handler), route.path
        assert route.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert route.path.startswith("/")


def test_the_world_page_handler_cannot_500_on_a_readable_world(routes_mod):
    """``world_detail`` used to sit OUTSIDE the handler's try, so anything it
    raised became a 500 instead of a message the page could show. It is inside
    now — asserted structurally, since a route handler is never called by the
    rest of the suite."""
    import inspect

    src = inspect.getsource(routes_mod.get_world)
    body_after_try = src.split("try:", 1)[-1]
    assert "world_detail(" in body_after_try
    assert "except" in src


def test_no_handler_leaks_a_stack_trace_to_the_player(routes_mod):
    """R25 — an error body may name what went wrong, never how it is built.

    Scoped to traces specifically. ``Path(__file__)`` is how this module locates
    its own siblings and never reaches a response, so banning it would be
    checking for the wrong thing.
    """
    import inspect

    src = inspect.getsource(routes_mod)
    for leak in ("traceback", "format_exc", "exc_info"):
        assert leak not in src


# -- telling one life from another ---------------------------------------


def test_a_lifes_subtitle_comes_from_the_players_own_answers():
    """The shelf and the rail were listing four lives under one name — the WORLD's
    title, repeated, three of them also reading "turn 1". Nothing said which was
    which.

    The answers are used because they exist for every world and are chosen per life.
    Reading a "name" field out of the narrated state instead would have the app
    decide which of a world's own fields counts as identity.
    """
    from routes import SUBTITLE_JOIN, SUBTITLE_PARTS, life_subtitle

    out = life_subtitle({"opening": {"race": "faerie", "birth": "commoner"}})
    assert out == f"faerie{SUBTITLE_JOIN}commoner"

    # Bounded: a subtitle has to fit one line of a 248px rail.
    many = {f"g{i}": f"v{i}" for i in range(10)}
    assert life_subtitle({"opening": many}).count(SUBTITLE_JOIN) == SUBTITLE_PARTS - 1


def test_a_life_with_nothing_distinguishing_it_gets_no_subtitle():
    """Empty, not a placeholder: the caller falls back to the world's title rather
    than rendering a blank line that looks like a missing value."""
    from routes import life_subtitle

    assert life_subtitle({}) == ""
    assert life_subtitle({"opening": {}}) == ""
    assert life_subtitle({"opening": {"race": "   "}}) == ""
    # A world that stored something odd under `opening` must not crash the shelf.
    assert life_subtitle({"opening": ["not", "a", "dict"]}) == ""
    assert life_subtitle({"opening": {"a": {"nested": 1}}}) == ""
