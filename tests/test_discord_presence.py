"""services/discord_presence.py (pure unit tests, no real Discord/IPC) and its MainWindow wiring."""
from anihub.context import AppContext
from anihub.core.config import Config
from anihub.services import discord_presence as dp
from anihub.services.discord_presence import DiscordPresence


class FakePresence:
    """Stands in for pypresence.Presence: no real IPC socket, just records calls."""

    instances: list = []

    def __init__(self, client_id):
        self.client_id = client_id
        self.calls: list = []
        self.fail_connect = False
        FakePresence.instances.append(self)

    def connect(self):
        self.calls.append("connect")
        if self.fail_connect:
            raise ConnectionRefusedError("no local Discord client")

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))

    def close(self):
        self.calls.append("close")


def test_available_is_false_without_a_client_id():
    presence = DiscordPresence("")
    assert not presence.available


def test_available_is_false_when_pypresence_is_not_installed(monkeypatch):
    monkeypatch.setattr(dp, "Presence", None)
    presence = DiscordPresence("123")
    assert not presence.available


def test_update_connects_once_and_reuses_the_connection(monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(dp, "Presence", FakePresence)
    presence = DiscordPresence("123")
    presence.update("Browsing: Arts")
    presence.update("Reading: Manga")
    assert len(FakePresence.instances) == 1
    calls = FakePresence.instances[0].calls
    assert calls[0] == "connect"
    assert calls[1][0] == "update" and calls[1][1]["state"] == "Browsing: Arts"
    assert calls[2][1]["state"] == "Reading: Manga"


def test_update_never_raises_when_discord_is_not_running(monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(dp, "Presence", FakePresence)
    presence = DiscordPresence("123")

    def make_failing(client_id):
        inst = FakePresence(client_id)
        inst.fail_connect = True
        return inst

    monkeypatch.setattr(dp, "Presence", make_failing)
    presence.update("state")  # must not raise


def test_close_is_safe_even_when_never_connected():
    DiscordPresence("123").close()  # must not raise


def test_close_calls_the_underlying_close(monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(dp, "Presence", FakePresence)
    presence = DiscordPresence("123")
    presence.update("state")
    presence.close()
    assert FakePresence.instances[0].calls[-1] == "close"


# --- MainWindow wiring -----------------------------------------------------------------------------------------

def make_window(qapp, tmp_path, **cfg_values):
    from anihub.ui.main_window import MainWindow

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    for k, v in cfg_values.items():
        cfg.set(k, v, save=False)
    ctx = AppContext.build(cfg)
    win = MainWindow(ctx)
    return win, ctx


def test_main_window_has_no_discord_presence_when_disabled(qapp, tmp_path):
    win, ctx = make_window(qapp, tmp_path)
    assert win.discord is None
    win._quitting = True
    win.close()


def test_main_window_has_no_discord_presence_when_enabled_without_a_client_id(qapp, tmp_path):
    win, ctx = make_window(qapp, tmp_path, **{"discord.enabled": True})
    assert win.discord is None
    win._quitting = True
    win.close()


def test_main_window_creates_discord_presence_when_configured(qapp, tmp_path, monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(dp, "Presence", FakePresence)
    win, ctx = make_window(qapp, tmp_path, **{"discord.enabled": True, "discord.client_id": "42"})
    assert win.discord is not None and win.discord.available
    win._quitting = True
    win.close()


def test_settings_page_saves_the_discord_box(qapp, tmp_path, monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(dp, "Presence", FakePresence)
    win, ctx = make_window(qapp, tmp_path)
    assert win.discord is None
    win.settings.discord_enabled.setChecked(True)
    win.settings.discord_client_id.setText("99")
    win.settings._save()
    assert ctx.cfg.get("discord.enabled") is True
    assert ctx.cfg.get("discord.client_id") == "99"
    assert win.discord is not None and win.discord.available   # settings.saved -> MainWindow._reload_discord()
    win._quitting = True
    win.close()


def test_switching_sections_updates_the_presence(qapp, tmp_path, monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(dp, "Presence", FakePresence)
    win, ctx = make_window(qapp, tmp_path, **{"discord.enabled": True, "discord.client_id": "42"})
    win.go("manga")
    updates = [c for c in FakePresence.instances[0].calls if isinstance(c, tuple)]
    assert len(updates) >= 2  # once on construction (_reload_discord), once more on the section switch
    win._quitting = True
    win.close()
