from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike


@dataclass
class OVRProjectionResult:
    posterior: np.ndarray
    log_scores: np.ndarray
    fitted_ovr_lr: np.ndarray
    rmse_logLR: float
    success: bool
    message: str
    diagnostics: dict[str, Any]


def _as_float_vector(values: ArrayLike, *, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1-D.")
    if arr.size < 2:
        raise ValueError(f"{name} must contain at least two entries.")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains non-finite values.")
    return arr


def _logit(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    clipped = np.clip(x, eps, 1.0 - eps)
    return np.log(clipped) - np.log1p(-clipped)


def _logistic(x: np.ndarray) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    pos = x >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-x[pos]))
    exp_x = np.exp(x[~pos])
    out[~pos] = exp_x / (1.0 + exp_x)
    return out


def independent_ovr_posteriors(priors: ArrayLike, ovr_lr: ArrayLike) -> np.ndarray:
    p = _as_float_vector(priors, name="priors")
    lr = _as_float_vector(ovr_lr, name="ovr_lr")
    if p.shape != lr.shape:
        raise ValueError("priors and ovr_lr must have matching shape.")
    if np.any(p <= 0) or np.any(p >= 1):
        raise ValueError("priors entries must be strictly between 0 and 1.")
    if np.any(lr <= 0):
        raise ValueError("ovr_lr entries must be strictly > 0.")
    return _logistic(_logit(p) + np.log(lr))


def sum_q_init(priors: ArrayLike, ovr_lr: ArrayLike) -> float:
    return float(np.sum(independent_ovr_posteriors(priors, ovr_lr)))


def is_sign_impossible(ovr_lr: ArrayLike, tol: float = 1e-12) -> bool:
    lr = _as_float_vector(ovr_lr, name="ovr_lr")
    return bool(np.all(lr > 1.0 + tol) or np.all(lr < 1.0 - tol))


def _model_log_ovr(priors: np.ndarray, log_scores: np.ndarray) -> np.ndarray:
    weighted = priors * np.exp(log_scores)
    n_classes = priors.size

    out = np.empty(n_classes, dtype=float)
    for k in range(n_classes):
        others = float(np.sum(weighted) - weighted[k])
        if others <= 0:
            raise ValueError("Numerical underflow: sum over non-k classes became non-positive.")
        out[k] = log_scores[k] - math.log(others) + math.log(max(1e-300, 1.0 - priors[k]))
    return out


def _posterior_from_scores(priors: np.ndarray, log_scores: np.ndarray) -> np.ndarray:
    weighted = priors * np.exp(log_scores)
    total = float(np.sum(weighted))
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Numerical issue: posterior denominator is non-positive.")
    return weighted / total


def _objective(
    *,
    priors: np.ndarray,
    target_log_lr: np.ndarray,
    log_scores: np.ndarray,
    weights: np.ndarray,
    reg: float,
    free_idx: np.ndarray,
) -> tuple[float, np.ndarray, np.ndarray]:
    fitted_log_lr = _model_log_ovr(priors, log_scores)
    residual = fitted_log_lr - target_log_lr
    data_term = 0.5 * float(np.sum(weights * residual * residual))
    reg_term = 0.5 * reg * float(np.sum(log_scores[free_idx] ** 2))
    return data_term + reg_term, fitted_log_lr, residual


def _jacobian(priors: np.ndarray, log_scores: np.ndarray, free_idx: np.ndarray) -> np.ndarray:
    n = priors.size
    jac = np.zeros((n, free_idx.size), dtype=float)
    weighted = priors * np.exp(log_scores)
    total = float(np.sum(weighted))

    for k in range(n):
        others = total - weighted[k]
        if others <= 0:
            raise ValueError("Numerical issue: others mass became non-positive.")
        for col_idx, m in enumerate(free_idx):
            if m == k:
                jac[k, col_idx] = 1.0
            else:
                jac[k, col_idx] = -weighted[m] / others
    return jac


def _fitted_ovr_from_scores(priors: np.ndarray, log_scores: np.ndarray) -> np.ndarray:
    return np.exp(_model_log_ovr(priors, log_scores))


def ovr_project_posterior(
    priors: ArrayLike,
    ovr_lr: ArrayLike,
    reg: float = 1e-6,
    weights: ArrayLike | None = None,
    baseline: int | None = None,
) -> OVRProjectionResult:
    try:
        p = _as_float_vector(priors, name="priors")
        lr_raw = _as_float_vector(ovr_lr, name="ovr_lr")
        if p.shape != lr_raw.shape:
            raise ValueError("priors and ovr_lr must have matching shape.")
        if np.any(p <= 0):
            raise ValueError("priors entries must be > 0.")
        p_sum = float(np.sum(p))
        if p_sum <= 0 or not math.isfinite(p_sum):
            raise ValueError("priors must have a positive finite sum.")
        p = p / p_sum
        if np.any(p >= 1):
            raise ValueError("priors entries must be < 1 after normalization.")
        if np.any(lr_raw <= 0):
            raise ValueError("ovr_lr entries must be > 0.")
        if reg < 0:
            raise ValueError("reg must be non-negative.")

        if weights is None:
            w = np.ones_like(p)
        else:
            w = _as_float_vector(weights, name="weights")
            if w.shape != p.shape:
                raise ValueError("weights must match priors shape.")
            if np.any(w <= 0):
                raise ValueError("weights must be strictly positive.")

        if baseline is None:
            baseline = int(np.argmax(p))
        if baseline < 0 or baseline >= p.size:
            raise ValueError(f"baseline index out of range: {baseline}")

        free_idx = np.array([idx for idx in range(p.size) if idx != baseline], dtype=int)
        target_log_lr = np.log(lr_raw)

        q0 = _logistic(_logit(p) + target_log_lr)
        q0_sum = float(np.sum(q0))
        if q0_sum <= 0:
            raise ValueError("Independent posterior initialization had non-positive sum.")
        q0_normalized = q0 / q0_sum

        log_scores = np.log(np.clip(q0_normalized, 1e-300, None)) - np.log(np.clip(p, 1e-300, None))
        log_scores = log_scores - log_scores[baseline]

        max_iter = 200
        tol = 1e-9
        objective_history: list[float] = []
        converged = False
        message = "ok"

        for _ in range(max_iter):
            objective, fitted_log_lr, residual = _objective(
                priors=p,
                target_log_lr=target_log_lr,
                log_scores=log_scores,
                weights=w,
                reg=reg,
                free_idx=free_idx,
            )
            objective_history.append(objective)

            jac = _jacobian(p, log_scores, free_idx)
            weighted_jac = jac * w[:, None]
            grad = jac.T @ (w * residual) + reg * log_scores[free_idx]
            hessian = jac.T @ weighted_jac + reg * np.eye(free_idx.size)

            try:
                step = np.linalg.solve(hessian, grad)
            except np.linalg.LinAlgError:
                step = np.linalg.lstsq(hessian, grad, rcond=None)[0]

            if not np.all(np.isfinite(step)):
                message = "non-finite optimizer step"
                break

            step_scale = 1.0
            accepted = False
            current = log_scores.copy()
            best_candidate = current
            best_obj = objective

            for _ in range(20):
                candidate = current.copy()
                candidate[free_idx] = candidate[free_idx] - step_scale * step
                candidate = candidate - candidate[baseline]
                candidate_obj, _, _ = _objective(
                    priors=p,
                    target_log_lr=target_log_lr,
                    log_scores=candidate,
                    weights=w,
                    reg=reg,
                    free_idx=free_idx,
                )
                if candidate_obj < best_obj:
                    best_obj = candidate_obj
                    best_candidate = candidate
                if candidate_obj <= objective:
                    log_scores = candidate
                    accepted = True
                    break
                step_scale *= 0.5

            if not accepted:
                # Tolerate tiny non-improving steps as convergence noise.
                rel_increase = (best_obj - objective) / max(1.0, abs(objective))
                if rel_increase <= 1e-10:
                    log_scores = best_candidate
                    converged = True
                    message = "converged (line-search tolerance)"
                    break
                message = "line search failed to improve objective"
                break

            max_delta = float(np.max(np.abs(step_scale * step)))
            if max_delta < tol:
                converged = True
                break

            if len(objective_history) > 1:
                if abs(objective_history[-2] - objective_history[-1]) < tol:
                    converged = True
                    break

        fitted_log_lr = _model_log_ovr(p, log_scores)
        fitted_lr = np.exp(fitted_log_lr)
        posterior = _posterior_from_scores(p, log_scores)
        rmse = float(np.sqrt(np.mean((fitted_log_lr - target_log_lr) ** 2)))

        q_fitted = independent_ovr_posteriors(p, fitted_lr)
        diagnostics = {
            "baseline": baseline,
            "iterations": len(objective_history),
            "objective_initial": objective_history[0] if objective_history else None,
            "objective_final": objective_history[-1] if objective_history else None,
            "sum_q_init": q0_sum,
            "sum_q_fitted": float(np.sum(q_fitted)),
            "sign_impossible_raw": is_sign_impossible(lr_raw),
            "sign_impossible_fitted": is_sign_impossible(fitted_lr),
            "converged": converged,
        }
        if converged and message == "ok":
            message = "converged"

        return OVRProjectionResult(
            posterior=posterior,
            log_scores=log_scores,
            fitted_ovr_lr=fitted_lr,
            rmse_logLR=rmse,
            success=converged,
            message=message,
            diagnostics=diagnostics,
        )
    except Exception as exc:
        return OVRProjectionResult(
            posterior=np.array([], dtype=float),
            log_scores=np.array([], dtype=float),
            fitted_ovr_lr=np.array([], dtype=float),
            rmse_logLR=float("nan"),
            success=False,
            message=str(exc),
            diagnostics={"error": repr(exc)},
        )
