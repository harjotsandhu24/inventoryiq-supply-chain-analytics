import numpy as np
import pytest
from scipy import integrate, stats

from inventoryiq.inventory.stats import erfc, loss_function, norm_cdf, norm_ppf


@pytest.mark.parametrize("p", [0.5, 0.8, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999, 0.01, 0.3])
def test_norm_ppf_matches_scipy(p):
    assert norm_ppf(p) == pytest.approx(stats.norm.ppf(p), rel=1e-8, abs=1e-9)


@pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.5])
def test_norm_ppf_rejects_invalid(p):
    with pytest.raises(ValueError):
        norm_ppf(p)


@pytest.mark.parametrize("x", np.linspace(-6, 6, 25))
def test_norm_cdf_matches_scipy(x):
    assert norm_cdf(x) == pytest.approx(stats.norm.cdf(x), abs=2e-7)


def test_erfc_symmetry():
    for x in (0.1, 0.7, 2.3):
        assert erfc(x) + erfc(-x) == pytest.approx(2.0, abs=1e-12)


@pytest.mark.parametrize("k", [-2.0, -0.5, 0.0, 0.5, 1.645, 3.0])
def test_loss_function_matches_integral(k):
    expected, _ = integrate.quad(lambda z: (z - k) * stats.norm.pdf(z), k, np.inf)
    assert loss_function(k) == pytest.approx(expected, abs=1e-6)
