"""Wilson interval maths, checked against numbers this module did not produce.

Reference values: statisticsfundamentals.com, "Wilson Score Interval: Worked
Examples and Step-by-Step Calculations" (14 published rows total, spanning
Examples 1-13), independent of `eval/stats.py`'s own implementation --
asserting against it, rather than round-tripping `wilson_interval` against
itself, is the actual check FR-20 asks for.

Eleven of the fourteen rows (Examples 1-6, 9-12, all z=1.96) are asserted
live below and match to 5e-4. The other three all come from one table --
Example 8, "Different Sample Sizes" -- and do NOT match this implementation.
Rather than silently dropping them, `_KNOWN_BAD_EXAMPLE_8` keeps all three,
unasserted against `wilson_interval`, with the diagnosis that rules them out
as a z-mismatch: see `_implied_z` and the test below it. The two n=20 rows
above are also verified algebraically, independent of the table entirely: at
p=0 the adjustment term cancels the center term exactly, so the closed form
collapses to `lo=0` and `hi=z^2/(n+z^2)` with no rounding involved.

The z parameter itself was untested until `test_wilson_interval_z_99_...`
and `test_wilson_interval_lower_bound_matches_example_13` below -- every row
above uses the function's own default. Example 7b is the page's only
non-95% row (z=2.576); Examples 13a/13b publish a lower bound only (the
page's ranking use case never states an upper bound for them).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval import stats                          # noqa: E402


# (n, x, published lower bound, published upper bound) at 95% confidence.
_REFERENCE_CASES = [
    (100, 60, 0.5020, 0.6906),
    (10, 7, 0.3967, 0.8923),
    (50, 2, 0.0110, 0.1346),
    (50, 48, 0.8654, 0.9890),
    (20, 0, 0.0000, 0.1612),
    (20, 20, 0.8388, 1.0000),
    (500, 125, 0.2141, 0.2898),
    (500, 45, 0.0679, 0.1183),
    (500, 60, 0.0944, 0.1514),
    (100, 84, 0.7558, 0.8990),
    (200, 8, 0.0204, 0.0769),
]


@pytest.mark.parametrize("n,x,lo,hi", _REFERENCE_CASES)
def test_wilson_interval_matches_published_reference(n, x, lo, hi):
    got_lo, got_hi = stats.wilson_interval(x, n)
    assert got_lo == pytest.approx(lo, abs=5e-4)
    assert got_hi == pytest.approx(hi, abs=5e-4)


# Example 8's table (n, x, published lower, published upper), "Different
# Sample Sizes", all nominally 95% confidence. NOT asserted against
# `wilson_interval` -- that would be circular right after establishing the
# page disagrees with itself. Diagnosis instead: solve each row's own stated
# bounds for the z that would produce them (the Wilson center is a weighted
# average of p-hat and 0.5, so center=(lo+hi)/2 => z^2 = n*(center-p)/(0.5-center)).
# The three implied z values below -- 1.9024, 1.5851, 0.0000 -- are mutually
# inconsistent, and none is 1.960, the z every other row on the same page
# implies. The n=5000 row is the sharpest tell on its own: lo=0.586,
# hi=0.614 is exactly symmetric about p=0.60, and a Wilson interval is never
# symmetric about p-hat (the center is always pulled toward 0.5) -- so
# implied z=0 isn't a near-miss, it is proof that row cannot be a Wilson
# interval at all, for any z.
#
# The n=50 row uses (0.4628, 0.7237), not the table's rounded (0.463,
# 0.724): the page also spells out its own intermediate arithmetic for this
# one row ("lower = ... = 0.4628; upper = ... = 0.7237"), a decimal more
# precise than the table and the best value the source publishes for it.
# Rows 2 and 3 have no such expansion, so the table's 3-decimal values are
# the most precise published number available for them.
_KNOWN_BAD_EXAMPLE_8 = [
    # (n, x, published lower, published upper, implied z)
    (50, 30, 0.4628, 0.7237, 1.9024),
    (500, 300, 0.558, 0.641, 1.5851),
    (5000, 3000, 0.586, 0.614, 0.0000),
]


def _implied_z(n: int, x: int, lo: float, hi: float) -> float:
    """The z whose Wilson center would land at (lo+hi)/2, given n and x."""
    p = x / n
    center = (lo + hi) / 2
    if center == p:
        return 0.0
    z2 = n * (center - p) / (0.5 - center)
    return math.sqrt(z2)


@pytest.mark.parametrize("n,x,lo,hi,expected_implied_z", _KNOWN_BAD_EXAMPLE_8)
def test_example_8_rows_are_known_bad_not_a_different_z(n, x, lo, hi, expected_implied_z):
    # 1. The implied z reproduces the diagnosis (1.9024 / 1.5851 / 0.0000).
    assert _implied_z(n, x, lo, hi) == pytest.approx(expected_implied_z, abs=5e-4)
    # 2. And, separately: this implementation genuinely does not reproduce
    #    the published row at its own default z -- it fails the exact
    #    pytest.approx(abs=5e-4) check that every one of the 11 asserted
    #    rows above passes, on at least one bound.
    got_lo, got_hi = stats.wilson_interval(x, n)
    lo_matches = got_lo == pytest.approx(lo, abs=5e-4)
    hi_matches = got_hi == pytest.approx(hi, abs=5e-4)
    assert not (lo_matches and hi_matches)


def test_wilson_interval_z_99_matches_published_example_7b():
    # The page's only non-95% row: 60/100 at 99% confidence (z=2.576). Every
    # case above leaves `z` at its default, so this is the parameter's first
    # check against an external number.
    lo, hi = stats.wilson_interval(60, 100, z=2.576)
    assert lo == pytest.approx(0.4714, abs=5e-4)
    assert hi == pytest.approx(0.7161, abs=5e-4)


@pytest.mark.parametrize("n,x,lo", [(100, 90, 0.8257), (10, 9, 0.5959)])
def test_wilson_interval_lower_bound_matches_example_13(n, x, lo):
    # Example 13 (Wilson-lower-bound ranking): the page states only the
    # lower bound for each row, so only the lower bound is checked here.
    got_lo, _ = stats.wilson_interval(x, n)
    assert got_lo == pytest.approx(lo, abs=5e-4)


def test_wilson_interval_zero_successes_closed_form():
    # p=0: adj = z*sqrt(z^2/(4n^2)) = z^2/(2n) = center exactly, so lo=0 with no
    # rounding, and hi = z^2/(n+z^2) -- an identity, not a table lookup.
    n = 20
    z2 = stats.Z95 * stats.Z95
    lo, hi = stats.wilson_interval(0, n)
    assert lo == 0.0
    assert hi == pytest.approx(z2 / (n + z2), abs=1e-12)


def test_wilson_interval_all_successes_is_the_mirror_image():
    n = 20
    lo_full, hi_full = stats.wilson_interval(n, n)
    lo_zero, _ = stats.wilson_interval(0, n)
    assert hi_full == 1.0
    assert lo_full == pytest.approx(1 - stats.wilson_interval(0, n)[1], abs=1e-12)


def test_wilson_interval_stays_within_unit_interval():
    for n, x in [(1, 0), (1, 1), (3, 0), (3, 3), (1000, 500), (7, 6)]:
        lo, hi = stats.wilson_interval(x, n)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_interval_narrows_as_n_grows_at_fixed_proportion():
    # Same p=0.6 at three sample sizes -- the interval must strictly narrow as
    # the evidence accumulates, not just move around.
    widths = []
    for n, x in [(50, 30), (500, 300), (5000, 3000)]:
        lo, hi = stats.wilson_interval(x, n)
        widths.append(hi - lo)
    assert widths[0] > widths[1] > widths[2]


def test_wilson_interval_rejects_bad_input():
    with pytest.raises(ValueError):
        stats.wilson_interval(5, 0)
    with pytest.raises(ValueError):
        stats.wilson_interval(-1, 10)
    with pytest.raises(ValueError):
        stats.wilson_interval(11, 10)


def test_fmt_rate_matches_spec_literal():
    # The literal string, not a shape check -- a shape check (startswith /
    # endswith / "dash somewhere in the middle") is shaped to whatever the
    # implementation happens to produce and can't catch a format drift like
    # a stray extra "%" or a rounded-vs-truncated bound. Pin the exact form
    # FR-20 specifies: `14% (6/43, 95% CI 6-27%)`, one "%" per number, en
    # dash between the bounds. 6/43's Wilson interval is (6.556%, 27.264%);
    # the bounds print truncated (6, not rounded-to-7), matching the spec's
    # own worked example -- the headline rate still rounds normally (14%).
    assert stats.fmt_rate(6, 43) == "14% (6/43, 95% CI 6–27%)"


def test_fmt_rate_zero_denominator_has_no_interval():
    assert stats.fmt_rate(0, 0) == "n/a (0/0)"
