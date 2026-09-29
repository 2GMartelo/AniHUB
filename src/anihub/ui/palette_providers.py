"""What the command palette knows about: sections, actions, library tags, books, the anime list."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from anihub.core.i18n import tr
from anihub.ui.command_palette import Entry
from anihub.ui.theme import apply_theme


def media_from_row(row) -> dict:
    """A watch-list row as the media dict the anime detail window expects."""
    return {"id": row["media_id"], "title": row["title"], "native": row["title_native"] or "", "cover": row["cover_url"] or "",
            "format": row["format"] or "", "episodes": row["episodes"], "status": row["airing_status"] or "",
            "next_episode": row["next_episode"], "next_airing": row["next_airing"], "genres": [], "description": "", "studio": "",
            "season": "", "year": None, "score": None, "url": f"https://anilist.co/anime/{row['media_id']}"}


def sections(win) -> list[Entry]:
    """Every section and its tabs."""
    s = tr("palette.section")
    out: list[Entry] = []

    def go(section: str, tabs=None, widget=None):
        def action() -> None:
            win.go(section)
            if tabs is not None and widget is not None:
                tabs.setCurrentWidget(widget)
        return action

    out += [Entry(f"{tr('nav.arts')} · {tr('tab.browse')}", go("arts", win.arts, win.browse), s, "sites booru"),
            Entry(f"{tr('nav.arts')} · {tr('tab.library')}", go("arts", win.arts, win.library), s, "library"),
            Entry(tr("nav.manga"), go("manga"), s, "manga"),
            Entry(f"{tr('nav.manga')} · {tr('manga.tab.browse')}", go("manga", win.manga_page.tabs, win.manga_page.browse), s, "catalog"),
            Entry(f"{tr('nav.manga')} · {tr('manga.tab.library')}", go("manga", win.manga_page.tabs, win.manga_page.library), s),
            Entry(tr("nav.anime"), go("anime"), s, "anime"),
            Entry(f"{tr('nav.anime')} · {tr('anime.tab.season')}", go("anime", win.anime_page.tabs, win.anime_page.season), s, "season calendar"),
            Entry(f"{tr('nav.anime')} · {tr('anime.tab.list')}", go("anime", win.anime_page.tabs, win.anime_page.mylist), s, "list tracker"),
            Entry(f"{tr('nav.anime')} · {tr('anime.tab.watch')}", go("anime", win.anime_page.tabs, win.anime_page.watch), s, "watch player"),
            Entry(f"{tr('nav.anime')} · {tr('anime.tab.music')}", go("anime", win.anime_page.tabs, win.anime_page.music_hub), s, "music ost soundtrack"),
            Entry(tr("nav.novels"), go("novels"), s, "novels books ranobe"),
            Entry(tr("nav.settings"), go("settings"), s, "settings")]
    if win.sd_enabled:
        out += [Entry(tr("nav.sd"), go("sd"), s, "stable diffusion forge generate"),
                Entry(f"{tr('nav.sd')} · CivitAI", go("sd", win.sd_page.tabs, win.sd_page.civitai), s)]
    if win.lora_train_enabled:
        out.append(Entry(tr("nav.lora_train"), go("lora_train"), s, "lora training kohya sd-scripts"))
    return out


def actions(win) -> list[Entry]:
    a = tr("palette.action")
    ctx = win.ctx

    def toggle_theme() -> None:
        dark = ctx.cfg.get("theme") == "dark"
        ctx.cfg.set("theme", "light" if dark else "dark")
        apply_theme(QApplication.instance(), ctx.cfg.get("theme"))

    def library_tool(method: str):
        def run() -> None:
            win.go("arts")
            win.arts.setCurrentWidget(win.library)
            getattr(win.library, method)()
        return run

    return [
        Entry(tr("palette.check_updates"), lambda: (win.go("settings"), win.settings.about.check_now()), a, "update version"),
        Entry(tr("palette.backup_now"), lambda: (win.go("settings"), win.settings.backup.backup_now()), a, "backup copy"),
        Entry(tr("palette.downloads"), lambda: (win.downloads_btn.show(), win.downloads_btn.open_window()), a, "downloads queue"),
        Entry(tr("palette.offline"), win.offline_btn.toggle, a, "offline online network"),
        Entry(tr("palette.theme"), toggle_theme, a, "theme dark light"),
        Entry(tr("tutorial.replay"), win.start_tutorial, a, "tutorial tour help guide"),
        Entry(tr("rules.title"), library_tool("_rules"), a, "rules auto"),
        Entry(tr("integrity.title"), library_tool("_integrity"), a, "integrity check"),
        Entry(tr("tags.manager"), library_tool("_tag_manager"), a, "tags"),
        Entry(tr("stats.title"), library_tool("_stats"), a, "statistics dashboard numbers"),
        Entry(tr("bug.button"), lambda: win.settings.about.report_btn.click(), a, "bug report error"),
        Entry(tr("about.logs"), lambda: win.settings.about.logs_btn.click(), a, "logs"),
        Entry(tr("tray.quit"), win.quit_app, a, "exit quit"),
    ]


def library_search(win, query: str) -> list[Entry]:
    """Tags of the library (and a free-text search) for the typed words."""
    q = query.strip()
    if len(q) < 2:
        return []
    out: list[Entry] = []
    tag = tr("palette.tag")

    def search(text: str):
        def run() -> None:
            win.go("arts")
            win.arts.setCurrentWidget(win.library)
            win.library.query.setText(text)
            win.library.reload()
        return run

    last = q.split()[-1].lstrip("-")
    for name, _category, count in win.ctx.db.suggest_tags(last, 6):
        out.append(Entry(f"{name}  ({count})", search(name), tag, ""))
    out.append(Entry(tr("palette.search_library", q=q), search(q), tr("palette.tag"), q))
    return out


def novels(win, query: str) -> list[Entry]:
    q = query.strip()
    if len(q) < 2:
        return []
    return [Entry(row["title"] + (f" — {row['author']}" if row["author"] else ""),
                  (lambda r=dict(row): (win.go("novels"), win.novels_hub.setCurrentWidget(win.novels_page), win.novels_page.open_book(r))), tr("palette.book"), "")
            for row in win.ctx.db.novels(q)[:8]]


def anime_list(win, query: str) -> list[Entry]:
    q = query.strip().lower()
    if len(q) < 2:
        return []
    out = []
    for row in win.ctx.db.anime_entries():
        if q in (row["title"] or "").lower() or q in (row["title_native"] or "").lower():
            out.append(Entry(row["title"], (lambda r=row: (win.go("anime"), win.anime_page.show_media(media_from_row(r)))),
                             tr("palette.anime"), ""))
        if len(out) >= 8:
            break
    return out


def sd_history_search(win, query: str) -> list[Entry]:
    """Past generations, searched by prompt -- Forge's own history is otherwise only reachable by opening
    Generation and typing into its own search box."""
    q = query.strip()
    if len(q) < 3 or not win.sd_enabled:
        return []

    def open_row(text: str):
        def run() -> None:
            win.go("sd")
            win.sd_page.tabs.setCurrentWidget(win.sd_page.history)
            win.sd_page.history.search.setText(text)
            win.sd_page.history.reload()
        return run

    rows = win.ctx.db.history(q, 6, 0)
    return [Entry((row["prompt"] or "").strip()[:90] or f"seed {row['seed']}", open_row(row["prompt"] or ""),
                  tr("palette.history"), "") for row in rows]


def build_providers(win) -> list:
    return [lambda q: sections(win), lambda q: actions(win), lambda q: library_search(win, q), lambda q: novels(win, q),
            lambda q: anime_list(win, q), lambda q: sd_history_search(win, q)]
