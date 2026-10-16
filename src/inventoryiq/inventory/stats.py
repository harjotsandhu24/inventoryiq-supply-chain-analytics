"""Normal-distribution helpers implemented identically in Python and TypeScript.

Using the same algorithms in both languages (rather than SciPy here and an
approximation in the browser) keeps the two engines numerically aligned.
Accuracy versus SciPy is verified in tests/test_stats.py.
"""

from __future__ import annotations

import math

import numpy as np

# Acklam's rational approximation for the inverse normal CDF.
_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)


def erfc(x: float) -> float:
    """Complementary error function (Numerical Recipes erfcc; |rel err| < 1.2e-7)."""
    z = abs(x)
    t = 1.0 / (1.0 + 0.5 * z)
    r = t * math.exp(
        -z * z
        - 1.26551223
        + t
        * (
            1.00002368
            + t
            * (
                0.37409196
                + t
                * (
                    0.09678418
                    + t
                    * (
                        -0.18628806
                        + t
                        * (
                            0.27886807
                            + t
                            * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))
                        )
                    )
                )
            )
        )
    )
    return r if x >= 0 else 2.0 - r


def norm_cdf(x: float) -> float:
    return 0.5 * erfc(-x / math.sqrt(2.0))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def norm_ppf(p: float) -> float:
    if not 0.0 < p < 1.0:
        raise ValueError("probability must be strictly between 0 and 1")
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1
        )
    elif p <= phigh:
        q = p - 0.5
        r = q * q
        x = (
            (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5])
            * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1)
        )
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1
        )
    return x  # relative error < 1.15e-9, identical operations to engine.ts


def loss_function(k: float) -> float:
    """Standard normal loss G(k) = E[(Z - k)+] = phi(k) - k (1 - Phi(k))."""
    return norm_pdf(k) - k * (1.0 - norm_cdf(k))


norm_cdf_v = np.vectorize(norm_cdf, otypes=[float])
loss_function_v = np.vectorize(loss_function, otypes=[float])
