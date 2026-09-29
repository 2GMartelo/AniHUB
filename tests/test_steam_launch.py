from anihub.services import steam_launch


def test_open_steam_install_calls_startfile_with_the_right_uri(monkeypatch):
    seen = {}
    monkeypatch.setattr(steam_launch.os, "startfile", lambda uri: seen.setdefault("uri", uri))
    steam_launch.open_steam_install(1325860)
    assert seen["uri"] == "steam://install/1325860"


def test_open_steam_install_propagates_a_missing_steam(monkeypatch):
    def boom(uri):
        raise FileNotFoundError("no association")

    monkeypatch.setattr(steam_launch.os, "startfile", boom)
    try:
        steam_launch.open_steam_install(1325860)
        assert False, "should have raised"
    except FileNotFoundError:
        pass


def test_steam_installed_checks_the_common_install_locations(monkeypatch, tmp_path):
    monkeypatch.setattr(steam_launch.os.path, "isdir", lambda p: p == r"C:\Program Files (x86)\Steam")
    assert steam_launch.steam_installed() is True
    monkeypatch.setattr(steam_launch.os.path, "isdir", lambda p: False)
    assert steam_launch.steam_installed() is False
