from __future__ import annotations

import math

import numpy as np

from dx_chat_entropy.lr_one_vs_rest_coherence import (
    independent_ovr_posteriors,
    is_sign_impossible,
    ovr_project_posterior,
    sum_q_init,
)


def _model_ovr_lr_from_scores(priors: np.ndarray, scores: np.ndarray) -> np.ndarray:
    weighted = priors * np.exp(scores)
    out = []
    for k in range(len(priors)):
        others = np.sum(weighted) - weighted[k]
        log_lr = scores[k] - math.log(others) + math.log(1 - priors[k])
        out.append(math.exp(log_lr))
    return np.asarray(out, dtype=float)


def test_projection_keeps_already_coherent_inputs_nearly_unchanged() -> None:
    priors = np.asarray([0.5, 0.3, 0.2], dtype=float)
    scores = np.asarray([0.0, 0.2, -0.1], dtype=float)
    coherent_lr = _model_ovr_lr_from_scores(priors, scores)

    result = ovr_project_posterior(priors=priors, ovr_lr=coherent_lr, reg=1e-6)
    assert result.success
    assert np.all(result.fitted_ovr_lr > 0)
    assert np.allclose(result.fitted_ovr_lr, coherent_lr, rtol=1e-3, atol=1e-3)
    assert np.isclose(float(np.sum(result.posterior)), 1.0, atol=1e-9)


def test_projection_regression_example_from_ticket() -> None:
    priors = np.asarray([0.5, 0.3, 0.2], dtype=float)
    raw_ovr = np.asarray([4.0, 3.0, 2.0], dtype=float)

    result = ovr_project_posterior(priors=priors, ovr_lr=raw_ovr, reg=1e-6)
    assert result.success
    assert result.diagnostics["sum_q_init"] > 1.0
    assert np.all(result.fitted_ovr_lr > 0)
    assert np.isclose(float(np.sum(result.posterior)), 1.0, atol=1e-9)
    assert np.isclose(result.fitted_ovr_lr[0], 1.0706, atol=0.03)
    assert np.isclose(result.fitted_ovr_lr[1], 0.9932, atol=0.03)
    assert result.diagnostics["sign_impossible_raw"]
    assert not result.diagnostics["sign_impossible_fitted"]


def test_independent_posterior_sum_is_one_after_projection_not_before() -> None:
    priors = np.asarray([0.4, 0.35, 0.25], dtype=float)
    raw_ovr = np.asarray([2.5, 1.8, 1.4], dtype=float)

    raw_sum_q = sum_q_init(priors, raw_ovr)
    assert raw_sum_q > 1.0

    result = ovr_project_posterior(priors=priors, ovr_lr=raw_ovr)
    assert result.success

    fitted_sum_q = float(np.sum(independent_ovr_posteriors(priors, result.fitted_ovr_lr)))
    assert np.isclose(fitted_sum_q, 1.0, atol=1e-6)
    assert not is_sign_impossible(result.fitted_ovr_lr)
