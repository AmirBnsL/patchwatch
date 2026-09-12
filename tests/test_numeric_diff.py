"""Numeric diff engine tests — direction table, ranks, magnitudes."""

from __future__ import annotations

from patchwatch.diff.numeric import changed_scopes, numeric_diff, parse_ranks, similarity_hint


def test_parse_ranks() -> None:
    assert parse_ranks("70/105/140") == [70.0, 105.0, 140.0]
    assert parse_ranks(75) == [75.0]
    assert parse_ranks(75.5) == [75.5]
    assert parse_ranks("nope") is None
    assert parse_ranks(None) is None
    assert parse_ranks(True) is None


def test_damage_increase_is_buff() -> None:
    changes = numeric_diff(
        {"spells.0.effect.1": "70/105/140"}, {"spells.0.effect.1": "90/125/160"}, "champion/Ahri"
    )
    assert len(changes) == 1
    assert changes[0].direction == "buff"


def test_cooldown_increase_is_nerf() -> None:
    changes = numeric_diff(
        {"spells.0.cooldown": "12/11/10"}, {"spells.0.cooldown": "14/13/12"}, "champion/Ahri"
    )
    assert changes[0].direction == "nerf"


def test_stat_decrease_is_nerf() -> None:
    changes = numeric_diff({"stats.armor": 21.0}, {"stats.armor": 18.0}, "champion/Ahri")
    assert changes[0].direction == "nerf"
    assert changes[0].magnitude == 3.0 / 21.0


def test_item_cost_increase_is_nerf() -> None:
    changes = numeric_diff({"gold.total": 3500}, {"gold.total": 3600}, "item/3031")
    assert changes[0].direction == "nerf"


def test_mixed_rank_shift_is_uncertain() -> None:
    changes = numeric_diff(
        {"spells.0.effect.1": "70/140/210"}, {"spells.0.effect.1": "90/130/210"}, "champion/Ahri"
    )
    assert changes[0].direction == "uncertain"


def test_rank_count_change_is_uncertain() -> None:
    changes = numeric_diff(
        {"spells.0.cost": "55/65/75"}, {"spells.0.cost": "55/65/75/85"}, "champion/Ahri"
    )
    assert changes[0].direction == "uncertain"


def test_added_and_removed_fields() -> None:
    changes = numeric_diff(
        {"stats.hp": 590}, {"stats.hp": 590, "stats.newstat": 10}, "champion/Ahri"
    )
    assert len(changes) == 1
    assert changes[0].old is None and changes[0].new == 10
    assert changes[0].direction == "uncertain"


def test_text_change_is_uncertain_without_magnitude() -> None:
    changes = numeric_diff({"name": "Ahri"}, {"name": "Ahra"}, "champion/Ahri")
    assert changes[0].direction == "uncertain"
    assert changes[0].magnitude is None


def test_unchanged_fields_skipped() -> None:
    assert numeric_diff({"stats.hp": 590}, {"stats.hp": 590}, "champion/Ahri") == []


def test_changed_scopes() -> None:
    old = {"champion/Ahri": {"hp": 590}, "champion/Zed": {"hp": 630}}
    new = {"champion/Ahri": {"hp": 600}, "champion/Zed": {"hp": 630}}
    assert changed_scopes(old, new) == ["champion/Ahri"]


def test_similarity_hint() -> None:
    assert similarity_hint("same", "same") == 1.0
    assert similarity_hint("one two three", "one two three four") > 0.8
