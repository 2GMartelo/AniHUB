from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor, QImage

from anihub.services import xyplot
from anihub.services.generation import GenParams, GenResult
from anihub.services.xyplot import MAX_CELLS, apply_axis, build_plan, compose_grid, parse_values, run_xy


def test_parse_values_lists_ranges_and_types():
    assert parse_values("steps", "20, 30;40") == [20, 30, 40]
    assert parse_values("steps", "10:30:10") == [10, 20, 30]
    assert parse_values("cfg_scale", "4:6:0.5") == [4.0, 4.5, 5.0, 5.5, 6.0]
    assert parse_values("sampler_name", "Euler a, DPM++ 2M") == ["Euler a", "DPM++ 2M"]
    assert parse_values("denoising_strength", "0.3, 0.6") == [0.3, 0.6]
    for bad in ("", "abc", "1:2", "5:1:1", "1:5:0"):
        with pytest.raises(ValueError):
            parse_values("steps", bad)
    with pytest.raises(ValueError):
        parse_values("steps", "20.5")                       # steps must be whole
    with pytest.raises(ValueError):
        parse_values("steps", "1:200:1")                    # more values than any grid may hold


def test_prompt_search_replace():
    base = GenParams(prompt="a cat on a sofa")
    assert apply_axis(base, "prompt_sr", "dog", first_value="cat").prompt == "a dog on a sofa"
    assert apply_axis(base, "prompt_sr", "cat", first_value="cat").prompt == "a cat on a sofa"     # first cell = original
    with pytest.raises(ValueError):
        apply_axis(base, "prompt_sr", "x", first_value="zebra")


def test_plan_shares_one_seed_and_covers_every_cell():
    base = GenParams(prompt="p", seed=-1, n_iter=3, batch_size=2, steps=20)
    plan = build_plan(base, "steps", [10, 20, 30], "cfg_scale", [5.0, 7.0])
    assert (plan.cols, plan.rows, len(plan.cells)) == (3, 2, 6)
    assert len({c.params.seed for c in plan.cells}) == 1 and plan.cells[0].params.seed != -1
    assert all(c.params.n_iter == 1 and c.params.batch_size == 1 for c in plan.cells)
    cell = next(c for c in plan.cells if (c.row, c.col) == (1, 2))
    assert (cell.params.steps, cell.params.cfg_scale) == (30, 7.0)
    fixed = build_plan(GenParams(seed=123), "steps", [10, 20])
    assert {c.params.seed for c in fixed.cells} == {123} and fixed.rows == 1


def test_plan_rejects_bad_input():
    base = GenParams(prompt="p")
    with pytest.raises(ValueError):
        build_plan(base, "steps", [1], "steps", [2])
    with pytest.raises(ValueError):
        build_plan(base, "steps", list(range(1, 10)), "cfg_scale", list(range(1, 10)))     # 81 > limit
    assert MAX_CELLS == 64


def fake_result(tmp_path, name, color):
    path = tmp_path / f"{name}.png"
    img = QImage(64, 48, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    img.save(str(path))
    return GenResult(path=path, seed=1)


def test_run_xy_generates_in_order_reports_progress_and_can_be_cancelled(tmp_path, monkeypatch):
    seen = []

    def fake(api, params, out_dir):
        seen.append(params.steps)
        return [fake_result(tmp_path, f"s{params.steps}", "#ff0000")]

    monkeypatch.setattr(xyplot, "run_generation", fake)
    plan = build_plan(GenParams(prompt="p", seed=1), "steps", [10, 20, 30])
    ticks = []
    made = run_xy(None, plan, tmp_path, progress=lambda i, n: ticks.append((i, n)))
    assert seen == [10, 20, 30] and sorted(made) == [(0, 0), (0, 1), (0, 2)] and ticks[-1] == (3, 3)
    seen.clear()
    stop = {"now": False}

    def stopping(api, params, out_dir):
        stop["now"] = True
        return fake(api, params, out_dir)

    monkeypatch.setattr(xyplot, "run_generation", stopping)
    made = run_xy(None, plan, tmp_path, cancelled=lambda: stop["now"])
    assert len(made) == 1                                        # stopped after the first picture


def test_a_failure_during_cancel_returns_partial_results_but_otherwise_raises(tmp_path, monkeypatch):
    calls = {"n": 0}

    def flaky(api, params, out_dir):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("Forge returned no images")
        return [fake_result(tmp_path, f"c{calls['n']}", "#00ff00")]

    monkeypatch.setattr(xyplot, "run_generation", flaky)
    plan = build_plan(GenParams(prompt="p", seed=1), "steps", [10, 20, 30])
    with pytest.raises(RuntimeError):
        run_xy(None, plan, tmp_path)
    calls["n"] = 0
    made = run_xy(None, plan, tmp_path, cancelled=lambda: calls["n"] >= 2)
    assert len(made) == 1


def test_compose_grid_lays_out_headers_and_cells(qapp, tmp_path):
    plan = build_plan(GenParams(prompt="p", seed=1), "steps", [10, 20], "cfg_scale", [5.0, 7.0])
    red = QImage(64, 48, QImage.Format.Format_RGB32)
    red.fill(QColor("#ff0000"))
    blue = QImage(64, 48, QImage.Format.Format_RGB32)
    blue.fill(QColor("#0000ff"))
    grid = compose_grid(plan, {(0, 0): red, (1, 1): blue}, cell=100)
    assert grid.width() > 2 * 100 and grid.height() > 2 * 75 + 40
    reds = [(x, y) for x in range(0, grid.width(), 4) for y in range(0, grid.height(), 4) if grid.pixelColor(x, y).red() > 200 and grid.pixelColor(x, y).blue() < 60]
    blues = [(x, y) for x in range(0, grid.width(), 4) for y in range(0, grid.height(), 4) if grid.pixelColor(x, y).blue() > 200 and grid.pixelColor(x, y).red() < 60]
    assert reds and blues
    assert min(x for x, _ in reds) < min(x for x, _ in blues) and min(y for _, y in reds) < min(y for _, y in blues)   # red top-left, blue bottom-right


def test_xy_dialog_builds_a_plan_from_the_form(qapp, tmp_path):
    from anihub.ui.xy_dialog import XYDialog

    ctx = SimpleNamespace(paths=SimpleNamespace(sd=tmp_path), db=None, library=None)
    dlg = XYDialog(ctx, None, lambda: GenParams(prompt="a cat", seed=5), lambda: True, lambda: None, lambda axis: ["Euler a", "DDIM"])
    assert "3 × 1 = 3" in dlg.count.text()
    dlg.y_axis.setCurrentIndex(dlg.y_axis.findData("sampler_name"))
    dlg.y_values.setText("Euler a, DDIM")
    assert "3 × 2 = 6" in dlg.count.text() and dlg.start_btn.isEnabled()
    plan = dlg.make_plan()
    assert len(plan.cells) == 6 and plan.cells[-1].params.sampler_name == "DDIM"
    dlg.x_values.setText("1:200:1")
    assert not dlg.start_btn.isEnabled()
    dlg.close()
