"""Derived estimates and margins of error (src/hazbrief/census.py; HB-09 method step 3).

The rules: the MOE of a sum is the square root of the sum of the squared component MOEs
(ACS General Handbook 2020, chapter 8, formula 1, PDF p. 65), with covariance taken as
zero; where several components estimate zero, only the largest of their MOEs enters
(OnTheMap for Emergency Management statistical methodology, p. 1); a component scaled by
an area share scales its MOE by the same share (the handbook's product formula 9, PDF
p. 72, with the share carrying no error)."""

from __future__ import annotations

import math

import pytest

from hazbrief import census


def test_the_handbook_worked_example_reproduces():
    """Handbook Table 8.1 and its result (PDF pp. 65-66): never-married females in
    Fairfax, Arlington and Alexandria, 2015 ACS 1-year: 203,119, MOE 5,070."""
    est, moe = census.sum_with_moe(
        [census.Cell(135173, 3860), census.Cell(43104, 2642), census.Cell(24842, 1957)]
    )
    assert est == 203119
    assert round(moe) == 5070


def test_moe_of_sum_on_three_block_groups_matches_a_hand_computation():
    """Three block groups of tract 24-043-010300 (C16002_001E/M, ACS 2020-2024, probed
    2026-10-21): 352 (181), 1,227 (280), 552 (152), allocated whole, half and a quarter.

    By hand: estimate 352 + 613.5 + 138 = 1,103.5; MOE sqrt(181^2 + 140^2 + 38^2) =
    sqrt(32,761 + 19,600 + 1,444) = sqrt(53,805) = 231.96."""
    cells = [
        census.Cell(352, 181).scaled(1.0),
        census.Cell(1227, 280).scaled(0.5),
        census.Cell(552, 152).scaled(0.25),
    ]
    est, moe = census.sum_with_moe(cells)
    assert est == pytest.approx(1103.5)
    assert moe == pytest.approx(math.sqrt(53805))
    assert moe == pytest.approx(231.96, abs=0.01)


def test_only_the_largest_moe_of_several_zero_estimates_enters():
    """OnTheMap EM: zero-estimate cells contribute only their maximum MOE."""
    cells = [census.Cell(0, 10), census.Cell(0, 20), census.Cell(5, 30)]
    est, moe = census.sum_with_moe(cells)
    assert est == 5 and moe == pytest.approx(math.sqrt(20**2 + 30**2))


def test_a_single_zero_estimate_keeps_its_moe():
    est, moe = census.sum_with_moe([census.Cell(0, 12), census.Cell(4, 3)])
    assert est == 4 and moe == pytest.approx(math.sqrt(12**2 + 3**2))


def test_scaling_scales_estimate_and_moe_alike():
    c = census.Cell(100, 20).scaled(0.5)
    assert (c.estimate, c.moe) == (50, 10)


def test_published_sentinels_are_read_as_the_census_bureau_defines_them():
    """ACS API annotation values: -555555555 (MOE not appropriate: the estimate is
    controlled, so its error is zero), -666666666, -888888888, -999999999, -222222222
    (cannot be computed or not available). OnTheMap EM: a suppressed cell is treated
    as zero and flagged."""
    controlled = census.cell_from_api("4000", "-555555555")
    assert (controlled.estimate, controlled.moe, controlled.suppressed) == (
        4000,
        0.0,
        False,
    )
    gone = census.cell_from_api("-666666666", "-222222222")
    assert (gone.estimate, gone.moe, gone.suppressed) == (0.0, 0.0, True)
    blank = census.cell_from_api(None, None)
    assert blank.suppressed and blank.estimate == 0.0
    assert census.cell_from_api("17", "9") == census.Cell(17.0, 9.0)


def test_an_empty_sum_is_zero_with_zero_moe():
    assert census.sum_with_moe([]) == (0.0, 0.0)
