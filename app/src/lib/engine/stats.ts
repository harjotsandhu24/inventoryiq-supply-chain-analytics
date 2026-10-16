// Normal-distribution helpers. Same algorithms and operation order as
// src/inventoryiq/inventory/stats.py so both engines agree numerically.

const A = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
const B = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
const C = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
const D = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];

/** Complementary error function (Numerical Recipes erfcc; |rel err| < 1.2e-7). */
export function erfc(x: number): number {
  const z = Math.abs(x);
  const t = 1.0 / (1.0 + 0.5 * z);
  const r =
    t *
    Math.exp(
      -z * z -
        1.26551223 +
        t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))),
    );
  return x >= 0 ? r : 2.0 - r;
}

export function normCdf(x: number): number {
  return 0.5 * erfc(-x / Math.sqrt(2.0));
}

export function normPdf(x: number): number {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2.0 * Math.PI);
}

/** Acklam's inverse normal CDF (relative error < 1.15e-9). */
export function normPpf(p: number): number {
  if (!(p > 0 && p < 1)) throw new RangeError("probability must be strictly between 0 and 1");
  const plow = 0.02425;
  const phigh = 1 - 0.02425;
  let q: number;
  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p));
    return (((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5]) / ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1);
  }
  if (p <= phigh) {
    q = p - 0.5;
    const r = q * q;
    return ((((((A[0] * r + A[1]) * r + A[2]) * r + A[3]) * r + A[4]) * r + A[5]) * q) / (((((B[0] * r + B[1]) * r + B[2]) * r + B[3]) * r + B[4]) * r + 1);
  }
  q = Math.sqrt(-2 * Math.log(1 - p));
  return -(((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5]) / ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1);
}

/** Standard normal loss G(k) = E[(Z - k)+]. */
export function lossFunction(k: number): number {
  return normPdf(k) - k * (1.0 - normCdf(k));
}

/** Round half-to-even at `digits` decimals, matching numpy.round for the comparisons that matter. */
export function roundTo(x: number, digits: number): number {
  const f = 10 ** digits;
  const y = x * f;
  const r = Math.round(y);
  // Math.round rounds .5 up; correct exact ties to even like numpy/Python
  if (Math.abs(y % 1) === 0.5 && r % 2 !== 0) return (r - 1) / f;
  return r / f;
}
