"""services/psd_writer.py: building a layered PSD with pytoshop, round-tripped through pytoshop's own reader to
verify byte-level correctness (no real Photoshop/Krita available here -- see the module docstring for the two
pytoshop quirks this locks in: the `size=` parameter order, and top-to-bottom layer ordering)."""
import numpy as np
import pytest

from anihub.services.psd_writer import PsdLayer, write_psd


def solid(h: int, w: int, rgba: tuple[int, int, int, int]) -> np.ndarray:
    img = np.empty((h, w, 4), dtype=np.uint8)
    img[..., 0], img[..., 1], img[..., 2], img[..., 3] = rgba
    return img


def read_back(path):
    """pytoshop reads channel pixel data lazily, from the file object it was given, on first access to `.image` --
    so that file must stay open for as long as the caller still wants to read layer pixels (an explicit `with` that
    closes it right after `PsdFile.read()` breaks any later `.image` access)."""
    import io

    import pytoshop
    from pytoshop.user import nested_layers

    buf = io.BytesIO(path.read_bytes())
    psd = pytoshop.PsdFile.read(buf)
    return psd, nested_layers.psd_to_nested_layers(psd)


def test_write_psd_round_trips_canvas_size_layer_order_and_pixels(tmp_path):
    """size=(width, height): confirmed against pytoshop's own reader, not its (misleading) docstring."""
    back = PsdLayer("back", solid(40, 60, (10, 20, 30, 255)), x=0, y=0)
    front = PsdLayer("front hair", solid(20, 25, (200, 0, 0, 128)), x=5, y=8)
    out = tmp_path / "a.psd"

    write_psd(out, [front, back], width=90, height=70)

    psd, layers = read_back(out)
    assert psd.width == 90 and psd.height == 70
    assert [l.name for l in layers] == ["front hair", "back"]      # index 0 (front) stays topmost

    got_front, got_back = layers
    assert (got_front.top, got_front.left, got_front.bottom, got_front.right) == (8, 5, 28, 30)
    assert (got_back.top, got_back.left, got_back.bottom, got_back.right) == (0, 0, 40, 60)
    for channel_id, expected in ((0, 200), (1, 0), (2, 0), (-1, 128)):
        assert int(got_front.channels[channel_id].image[0, 0]) == expected
    for channel_id, expected in ((0, 10), (1, 20), (2, 30), (-1, 255)):
        assert int(got_back.channels[channel_id].image[0, 0]) == expected


def test_write_psd_many_layers_keep_their_relative_order(tmp_path):
    names = ["front hair", "face", "eyes", "back hair", "body"]
    layers = [PsdLayer(n, solid(8, 8, (i * 10, 0, 0, 255)), x=i, y=i) for i, n in enumerate(names)]
    out = tmp_path / "many.psd"

    write_psd(out, layers, width=50, height=50)

    _psd, got = read_back(out)
    assert [l.name for l in got] == names


def test_write_psd_rejects_empty_layer_list(tmp_path):
    with pytest.raises(ValueError, match="at least one layer"):
        write_psd(tmp_path / "empty.psd", [], width=10, height=10)


def test_write_psd_rejects_a_layer_that_is_not_rgba(tmp_path):
    bad = PsdLayer("rgb_only", np.zeros((10, 10, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="RGBA"):
        write_psd(tmp_path / "bad.psd", [bad], width=10, height=10)


def test_write_psd_creates_parent_directories(tmp_path):
    out = tmp_path / "nested" / "dir" / "a.psd"
    write_psd(out, [PsdLayer("x", solid(4, 4, (1, 2, 3, 4)))], width=4, height=4)
    assert out.exists()


def test_write_psd_survives_a_non_contiguous_array(tmp_path):
    """A layer sliced out of a bigger array (e.g. a crop) is not C-contiguous -- must not crash or scramble pixels."""
    big = solid(20, 20, (0, 0, 0, 0))
    big[5:15, 5:15] = (9, 8, 7, 255)
    sliced = big[5:15, 5:15]                                     # a view, not a copy
    assert not sliced.flags["C_CONTIGUOUS"]
    out = tmp_path / "sliced.psd"

    write_psd(out, [PsdLayer("crop", sliced)], width=10, height=10)

    _psd, got = read_back(out)
    assert int(got[0].channels[0].image[0, 0]) == 9
