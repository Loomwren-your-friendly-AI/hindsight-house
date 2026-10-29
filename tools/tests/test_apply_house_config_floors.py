"""apply_house_config floor copy: a zero legacy floor writes none, and the kept-value note."""
import apply_house_config as ac


def test_legacy_zero_writes_no_floor():
    for zero in (0, 0.0, -0.0):
        new, changes, notes = ac.plan({ac.LEGACY_NAME: zero}, drop_legacy=False)
        assert ac.FLOORS_NAME not in new
        assert all(key != ac.FLOORS_NAME for key, _old, _new in changes)
        assert any("is 0 (no floor in 1.2.1)" in n for n in notes)
        assert new[ac.LEGACY_NAME] == zero


def test_legacy_zero_with_drop_removes_legacy_only():
    new, changes, _notes = ac.plan({ac.LEGACY_NAME: 0}, drop_legacy=True)
    assert ac.LEGACY_NAME not in new and ac.FLOORS_NAME not in new
    assert (ac.LEGACY_NAME, 0, ac.ABSENT) in changes


def test_small_nonzero_legacy_is_still_copied():
    new, _changes, _notes = ac.plan({ac.LEGACY_NAME: 1e-9}, drop_legacy=False)
    assert new[ac.FLOORS_NAME] == {ac.SCORE_NAME: 1e-9}


def test_negative_legacy_is_copied_as_is():
    new, _changes, _notes = ac.plan({ac.LEGACY_NAME: -0.5}, drop_legacy=False)
    assert new[ac.FLOORS_NAME] == {ac.SCORE_NAME: -0.5}


def test_kept_note_shows_both_values():
    cfg = {ac.FLOORS_NAME: {"final": 0.5}, ac.LEGACY_NAME: 0.92}
    new, changes, notes = ac.plan(cfg, drop_legacy=False)
    assert new[ac.FLOORS_NAME] == {"final": 0.5}
    assert all(key != ac.FLOORS_NAME for key, _old, _new in changes)
    note = [n for n in notes if "kept the existing value" in n][0]
    assert '{"final": 0.5}' in note and "0.92" in note


def test_kept_note_with_legacy_absent():
    _new, _changes, notes = ac.plan({ac.FLOORS_NAME: {"final": 0.5}}, drop_legacy=False)
    assert any("<absent>" in n for n in notes if "kept" in n)


def test_kept_floor_is_not_overwritten_by_zero_legacy():
    cfg = {ac.FLOORS_NAME: {"final": 0.7}, ac.LEGACY_NAME: 0}
    new, _changes, _notes = ac.plan(cfg, drop_legacy=False)
    assert new[ac.FLOORS_NAME] == {"final": 0.7}
