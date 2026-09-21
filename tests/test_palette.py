from types import SimpleNamespace

from PySide6.QtCore import Qt

from anihub.ui.command_palette import CommandPalette, Entry, rank, score


def test_score_requires_every_word_and_prefers_early_or_exact_matches():
    assert score("", "anything") == 1 and score("zzz", "Settings") == 0
    assert score("set", "Settings") > score("set", "Reset the world") > 0            # a prefix beats a mid-word hit
    assert score("back up", "Back up the library now") > 0 and score("back zzz", "Back up") == 0
    assert score("theme dark", "Switch dark / light theme") > 0                       # word order does not matter
    assert score("anime", "anime") > score("anime", "anime list")                    # exact wins
    assert score("list", "Anime · My list") > score("list", "Playlist of things")     # start of a word beats the middle of one


def test_rank_orders_by_score_then_provider_order_and_limits():
    entries = [Entry("Reset", lambda: None), Entry("Settings", lambda: None), Entry("Sets of tags", lambda: None, keywords="tags")]
    assert [e.title for e in rank("set", entries)] == ["Settings", "Sets of tags", "Reset"]
    assert [e.title for e in rank("tags", entries)] == ["Sets of tags"]              # keywords are searched too
    assert [e.title for e in rank("", entries)] == ["Reset", "Settings", "Sets of tags"]
    assert len(rank("", [Entry(str(i), lambda: None) for i in range(100)], limit=5)) == 5


def test_palette_filters_navigates_and_runs(qapp):
    ran = []
    entries = [Entry("Alpha section", lambda: ran.append("a"), "section"), Entry("Beta action", lambda: ran.append("b"), "action")]
    dyn = lambda q: [Entry(f"Tag {q}", lambda: ran.append("tag:" + q), "library")] if q == "be" else []      # noqa: E731
    broken = lambda q: 1 / 0                                                                                    # noqa: E731
    dlg = CommandPalette([lambda q: entries, dyn, broken])
    assert dlg.list.count() == 2 and dlg.current_entry().title == "Alpha section"
    dlg.edit.setText("be")
    assert dlg.current_entry().title == "Beta action"                              # the broken provider did not break anything
    assert any(dlg.list.item(i).data(Qt.ItemDataRole.UserRole).title == "Tag be" for i in range(dlg.list.count()))
    dlg.edit.setText("")
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    dlg.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
    assert dlg.current_entry().title == "Beta action"
    dlg.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
    assert dlg.current_entry().title == "Beta action"                              # stops at the end
    dlg.run_current()
    assert ran == ["b"]
    dlg.edit.setText("nothing matches this")
    assert dlg.current_entry() is None
    dlg.run_current()                                                              # no entry: nothing happens
    assert ran == ["b"]


def test_providers_work_on_a_real_main_window(qapp, tmp_path):
    from anihub.context import AppContext
    from anihub.core.config import Config
    from anihub.ui.main_window import MainWindow
    from anihub.ui.palette_providers import build_providers

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    ctx = AppContext.build(cfg)
    ctx.db.add_item(kind="art", path="arts/a.png", tags=[("landscape", "general"), ("lantern", "general")])
    ctx.db.novel_add(title="Дорога в никуда", author="Автор", path="novels/x.txt", ext="txt", sha256="abc", chapters=3)
    win = MainWindow(ctx)
    providers = build_providers(win)
    everything = {e.title: e for p in providers for e in p("lan")}
    assert any(t.startswith("landscape") for t in everything) and any(t.startswith("lantern") for t in everything)
    assert any("Search the library" in t or "Искать в библиотеке" in t for t in everything)
    assert [e.title for e in providers[3]("дорога")] == ["Дорога в никуда — Автор"]
    names = [e.title for e in providers[0]("")] + [e.title for e in providers[1]("")]
    assert len(names) >= 20
    section = next(e for e in providers[0]("") if e.title.endswith(win.ctx and "Ranobe") or "Ранобэ" in e.title or "Novels" in e.title)
    section.action()
    assert win.nav.currentRow() == 4
    tag = next(e for e in providers[2]("lan") if e.title.startswith("landscape"))
    tag.action()
    assert win.nav.currentRow() == 0 and win.library.query.text() == "landscape"
    dlg = CommandPalette(providers, win)
    dlg.edit.setText("тем")
    assert any("тём" in dlg.list.item(i).text().lower() or "theme" in dlg.list.item(i).text().lower() for i in range(dlg.list.count()))
    win.quit_app = lambda: None
    ctx.downloads.shutdown()
