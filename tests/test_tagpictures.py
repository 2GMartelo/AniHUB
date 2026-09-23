from anihub.services.tagpictures import SEED_MAX, PictureMaker

ROW_A = {"id": 1, "slot": "clothing", "text": "red dress"}
ROW_B = {"id": 2, "slot": "clothing", "text": "blue dress"}
ROW_QUALITY = {"id": 3, "slot": "quality", "text": "masterpiece"}


def test_a_new_batch_uses_a_different_seed_than_the_last_one():
    """Drawing the same tag again later (a fresh PictureMaker, as every "draw this picture" click makes one) must not
    reproduce the exact same picture as before."""
    seeds = {PictureMaker(api=None).params_for(ROW_A).seed for _ in range(20)}
    assert len(seeds) > 1          # 20 independent batches essentially never collide on one fixed seed


def test_seeds_stay_within_the_valid_a1111_range():
    for _ in range(50):
        seed = PictureMaker(api=None).params_for(ROW_A).seed
        assert 0 <= seed < SEED_MAX


def test_within_one_batch_ordinary_tags_share_the_base_seed():
    """Tags outside VARIED_SEED_SLOTS (e.g. "clothing") intentionally reuse the same seed within one batch, so
    different options are visually comparable side by side (the existing design, unchanged by the fix)."""
    maker = PictureMaker(api=None)
    assert maker.params_for(ROW_A).seed == maker.params_for(ROW_B).seed


def test_within_one_batch_varied_slots_still_get_their_own_seed_per_tag():
    """"quality"/"extra"/negative tags are in VARIED_SEED_SLOTS: nothing in their own prompt text tells them apart
    visually, so each one keeps its own distinct seed even within a single batch (also unchanged by the fix)."""
    maker = PictureMaker(api=None)
    a = maker.params_for(ROW_QUALITY).seed
    b = maker.params_for({**ROW_QUALITY, "id": 4}).seed
    assert a != b
