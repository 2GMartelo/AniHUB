import random

from anihub.services import wildcards


def test_resolve_picks_one_entry_from_the_named_list():
    text = wildcards.resolve("1girl, __outfits__, smile", {"outfits": ["kimono", "swimsuit"]},
                             rng=random.Random(1))
    assert text in ("1girl, kimono, smile", "1girl, swimsuit, smile")


def test_resolve_is_case_insensitive_on_the_list_name():
    text = wildcards.resolve("__Outfits__", {"outfits": ["kimono"]})
    assert text == "kimono"


def test_resolve_leaves_an_unknown_or_empty_placeholder_untouched():
    assert wildcards.resolve("__missing__ tag", {"outfits": ["kimono"]}) == "__missing__ tag"
    assert wildcards.resolve("__outfits__", {"outfits": []}) == "__outfits__"


def test_resolve_handles_multi_word_list_names():
    assert wildcards.resolve("__hair color__", {"hair color": ["red"]}) == "red"


def test_resolve_replaces_each_placeholder_independently():
    text = wildcards.resolve("__a__ and __a__", {"a": ["x", "y"]}, rng=random.Random(2))
    assert all(w in ("x", "y") for w in text.split(" and "))


def test_resolve_is_a_no_op_without_placeholders_or_lists():
    assert wildcards.resolve("plain prompt", {}) == "plain prompt"
    assert wildcards.resolve("", {"a": ["x"]}) == ""
