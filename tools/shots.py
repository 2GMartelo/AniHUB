r"""Dev tool: renders the main screens to PNG files (real fonts, no window shown) for visual review.

    .venv\Scripts\python tools\shots.py <output dir> [dark|light]
"""
import sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtWidgets import QApplication
from anihub.context import AppContext
from anihub.core.config import Config
from anihub.core.i18n import set_language
from anihub.ui.main_window import MainWindow
from anihub.ui.theme import apply_theme

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
mode = sys.argv[2] if len(sys.argv) > 2 else "dark"
app = QApplication([])
tmp = Path(tempfile.mkdtemp()); cfg = Config.load(tmp / "config.json")
real = Config.load()
cfg.set("library_path", str(tmp / "lib"), save=False); cfg.set("first_run_done", True, save=False)
cfg.set("theme", mode, save=False); cfg.set("ratings.allowed", ["general", "sensitive"], save=False)
cfg.set("sources.danbooru.api_key", real.get("sources.danbooru.api_key"), save=False)
cfg.set("forge.path", real.get("forge.path"), save=False)
set_language("ru"); apply_theme(app, mode)
ctx = AppContext.build(cfg)

def pump(seconds=0.0, cond=None, limit=60):
    end = time.time() + (limit if cond else seconds)
    while time.time() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.03)
    return False

# realistic content: save some general-rated posts from Danbooru, plus categories/collections/tags
posts = ctx.sources["danbooru"].search(["landscape", "rating:g"], 1, 30) + ctx.sources["danbooru"].search(["1girl", "rating:g"], 1, 30)
ctx.library.save_posts(posts[:40])
db = ctx.db
c1, c2 = db.create_category("Избранные"), db.create_category("Обои")
db.set_default_category(c1)
col = db.create_collection("Пейзажи")
ids = [r["id"] for r in db.search_items(limit=100)]
db.add_to_collection(ids[:8], col); db.set_field(ids[:6], "favorite", 1); db.set_field(ids[:10], "stars", 4)
db.save_smart_tag("девушки", ["1girl"])

win = MainWindow(ctx); win.resize(1440, 900)
def shot(name):
    pump(0.6)
    win.grab().save(str(out / f"{mode}_{name}.png"))
    print("saved", name, flush=True)

win.nav.setCurrentRow(0); win.arts_tabs.setCurrentIndex(0) if hasattr(win, "arts_tabs") else None
win.browse.query.setText("landscape"); win.browse.start_search()
pump(cond=lambda: win.browse.grid.count() >= 12, limit=40); pump(4)
shot("arts_browse")
for t in win.findChildren(type(win.pages.widget(0).findChild(type(win.browse.parent().parent())) if False else object)):
    pass
tabs = win.pages.widget(0)
tabs.setCurrentIndex(1); win.library.reload(); pump(cond=lambda: win.library.grid.count() >= 10, limit=30); pump(3)
shot("arts_library")
win.library.grid.setCurrentRow(0) if hasattr(win.library.grid, "setCurrentRow") else None
viewer_item = win.library.grid.item(2)
win.library._open_viewer(viewer_item)
viewer = win.library._viewers[-1]; viewer.resize(1100, 720); pump(3)
viewer.grab().save(str(out / f"{mode}_viewer.png")); print("saved viewer", flush=True)
viewer.close(); pump(0.3)
from anihub.ui.manga_views import MangaBrowseTab
from anihub.services.suwayomi import _normalize_filter
win.nav.setCurrentRow(1)
tab = win.findChild(MangaBrowseTab)
raw = [{"__typename": "SelectFilter", "name": "Сортировка", "values": ["Популярное", "Новинки"], "selDef": 0},
       {"__typename": "GroupFilter", "name": "Жанры", "filters": [{"__typename": "TriStateFilter", "name": n, "triDef": "IGNORE"} for n in
        ["Боевик", "Комедия", "Драма", "Фэнтези", "Романтика", "Школа", "Спорт", "Ужасы", "Меха", "Исекай", "Психология"]]},
       {"__typename": "GroupFilter", "name": "Статус", "filters": [{"__typename": "CheckBoxFilter", "name": n, "boolDef": False} for n in ["Выходит", "Завершено"]]}]
tab.panel.set_filters([_normalize_filter(f, i) for i, f in enumerate(raw)])
tab.filters_btn.setEnabled(True); tab.filters_btn.setChecked(True); tab.settings_btn.show()
chip = tab.panel._chips[1]; chip.click(); tab.panel._chips[3].click(); tab.panel._chips[3].click()
from PySide6.QtWidgets import QTabWidget
mt = tab.parent()
while mt is not None and not isinstance(mt, QTabWidget): mt = mt.parent()
mt.setCurrentWidget(tab) if mt else None
shot("manga")
win.nav.setCurrentRow(2); shot("sd_generate")
win.sd_page.tabs.setCurrentIndex(1); shot("sd_queue")
win.sd_page.tabs.setCurrentIndex(3); shot("sd_civitai")
win.nav.setCurrentRow(3); shot("anime")
win.nav.setCurrentRow(4); shot("settings")
ctx.db.close()
