"""Wilson score confidence interval for a binomial proportion (FR-20).

Every rate this project reports sits on a small denominator — single-digit
numerators on 8-97-ticket tiers and, per language, half that. A normal (Wald)
interval on a proportion near 0 or 1 at that scale routinely produces bounds
outside [0,1] and understates uncertainty; the Wilson score interval stays
inside [0,1] by construction and is the standard textbook fix, so rates print
with one alongside the raw count: `14% (6/43, 95% CI 6-27%)`.

The one thing this module must not do is grade its own homework: `tests/test_stats.py`
checks the interval maths against numbers this module did not produce (published
worked examples), not against a second call to `wilson_interval` itself.
"""
from __future__ import annotations

import math

# z_(0.975), the two-sided 95% critical value (norm.ppf(0.975)).
Z95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The (lower, upper) Wilson score bound for `successes` out of `n` trials.

    Closed form, no iteration: https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval#Wilson_score_interval.
    Clamped to [0, 1] only to absorb floating-point overshoot at p=0 or p=1 — the
    formula itself never produces a bound outside that range.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if not 0 <= successes <= n:
        raise ValueError(f"successes={successes} out of range for n={n}")
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = p + z2 / (2 * n)
    half_width = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    lo = (center - half_width) / denom
    hi = (center + half_width) / denom
    return max(0.0, lo), min(1.0, hi)


def fmt_rate(successes: int, n: int, z: float = Z95) -> str:
    """FR-20's print form: `14% (6/43, 95% CI 6-27%)`. `n=0` has no rate to show.

    The headline rate rounds to the nearest percent (`round()`-style, via `:.0%`).
    The two CI bounds are truncated, not rounded: 6/43's Wilson lower bound is
    6.556%, and the spec's own worked example prints `6`, not the `7` rounding
    would give. `round(..., 9)` before flooring only absorbs float noise (e.g.
    6.999999999998 for an intended 7.0); it does not change which integer percent
    an honest bound truncates to.
    """
    if n <= 0:
        return f"n/a (0/{n})"
    lo, hi = wilson_interval(successes, n, z)
    lo_pct = math.floor(round(lo * 100, 9))
    hi_pct = math.floor(round(hi * 100, 9))
    return f"{successes / n:.0%} ({successes}/{n}, 95% CI {lo_pct}–{hi_pct}%)"
