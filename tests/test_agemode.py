from anihub.core import agemode
from anihub.core.config import Config


def cfg_in(tmp_path) -> Config:
    return Config.load(tmp_path / "c.json")


def test_modes_lock_tags_cumulatively():
    t12, t16, t18 = (set(agemode.locked_tags(m)) for m in ("12", "16", "18"))
    assert not t18 and t16 and t12 > t16                       # 12+ hides everything 16+ hides, and more
    assert "breasts" in t12 and "breasts" not in t16            # 16+ gives access to breasts...
    assert "nipples" in t16 and "penis" in t16 and "loli" in t16   # ...but the rest of 18+ stays hidden
    assert t16 <= t12


def test_ratings_follow_the_mode(tmp_path):
    cfg = cfg_in(tmp_path)
    assert agemode.mode_of(cfg) == "12"                         # the safe default
    for mode, expected in (("16", {"general", "sensitive", "questionable"}), ("18", {"explicit"}), ("12", {"general"})):
        agemode.apply_mode(cfg, mode, save=False)
        assert agemode.mode_of(cfg) == mode
        assert expected <= set(cfg.get("ratings.allowed"))
    assert "explicit" not in cfg.get("ratings.allowed")


def test_old_configs_are_translated(tmp_path):
    cfg = cfg_in(tmp_path)
    cfg.set("ratings.allowed", ["general", "explicit"], save=False)
    assert agemode.mode_of(cfg) == "18"
    cfg.set("ratings.allowed", ["general", "questionable"], save=False)
    assert agemode.mode_of(cfg) == "16"


def test_parse_tags_and_prefixes(tmp_path):
    assert agemode.parse_tags("Guro*, big  breasts;foo,,FOO") == ["guro*", "big", "breasts", "foo"]
    blocker = agemode.Blocker.from_tags(["cat", "guro*"])
    assert blocker.blocks("Cat") and blocker.blocks("guro_hentai") and not blocker.blocks("category")
    assert blocker.blocked_in(["x", "guro"]) and not blocker.blocked_in(["x"]) and not agemode.Blocker.from_tags([])


def test_blocker_combines_mode_and_custom_tags(tmp_path):
    cfg = cfg_in(tmp_path)
    agemode.apply_mode(cfg, "16", save=False)
    cfg.set("filter.custom_tags", ["spiders", "gore*"], save=False)
    blocker = agemode.blocker_for(cfg)
    assert blocker.blocks("nipples") and blocker.blocks("spiders") and blocker.blocks("gore_extreme")
    assert not blocker.blocks("breasts") and not blocker.blocks("landscape")


def test_library_hides_blocked_tags_but_not_in_the_trash(tmp_path):
    from anihub.context import AppContext

    cfg = cfg_in(tmp_path)
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    ctx = AppContext.build(cfg)
    ok = ctx.db.add_item(kind="art", path="a.png", tags=[("landscape", "general")])
    boobs = ctx.db.add_item(kind="art", path="b.png", tags=[("landscape", "general"), ("breasts", "general")])
    lewd = ctx.db.add_item(kind="art", path="c.png", tags=[("nipples", "general")])
    plain = lambda **kw: {r["id"] for r in ctx.db.search_items(**kw)}
    assert plain() == {ok}                                       # 12+ (default)
    assert ctx.db.count_search() == 1
    agemode.apply_mode(cfg, "16", save=False)
    ctx.refresh_filter()
    assert plain() == {ok, boobs}
    cfg.set("filter.custom_tags", ["landscape"], save=False)
    ctx.refresh_filter()
    assert plain() == set()
    agemode.apply_mode(cfg, "18", save=False)
    cfg.set("filter.custom_tags", [], save=False)
    ctx.refresh_filter()
    assert plain() == {ok, boobs, lewd}
    agemode.apply_mode(cfg, "12", save=False)
    ctx.refresh_filter()
    ctx.db.conn.execute("UPDATE items SET trashed_at=1 WHERE id=?", (lewd,))
    assert {r["id"] for r in ctx.db.search_items(trashed=True)} == {lewd}     # the trash is not filtered


def test_settings_show_locked_tags_and_they_follow_the_mode(qapp, tmp_path, monkeypatch):
    from anihub.context import AppContext
    from anihub.ui.settings import SettingsPage

    cfg = cfg_in(tmp_path)
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    ctx = AppContext.build(cfg)
    page = SettingsPage(ctx)
    assert page.locked_tags.isReadOnly()
    assert "breasts" in page.locked_tags.toPlainText()          # 12+
    page.age_mode.setCurrentIndex(page.age_mode.findData("16"))
    text = page.locked_tags.toPlainText()
    assert "breasts" not in text.split(", ") and "nipples" in text
    page.age_mode.setCurrentIndex(page.age_mode.findData("18"))
    assert "nipples" not in page.locked_tags.toPlainText()

    page.custom_tags.setPlainText("Spiders, gore*")
    monkeypatch.setattr(page, "_confirm_adult", lambda: False)   # declined: stays where it was
    page._save()
    assert agemode.mode_of(cfg) == "12" and cfg.get("filter.custom_tags") == ["spiders", "gore*"]
    assert ctx.blocker.blocks("spiders") and ctx.allowed_ratings() == ["general"]
    monkeypatch.setattr(page, "_confirm_adult", lambda: True)
    page.age_mode.setCurrentIndex(page.age_mode.findData("18"))
    page._save()
    assert agemode.mode_of(cfg) == "18" and "explicit" in ctx.allowed_ratings()


def test_wizard_offers_three_modes(qapp, tmp_path):
    from anihub.ui.wizard import RatingPage

    cfg = cfg_in(tmp_path)
    page = RatingPage(cfg)
    page.initializePage()
    assert list(page.boxes) == ["12", "16", "18"] and page.chosen() == "12"
    page.boxes["16"].setChecked(True)
    assert page.validatePage() and agemode.mode_of(cfg) == "16"
