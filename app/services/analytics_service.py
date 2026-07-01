"""
Fale com Seus Dados — Analytics Service (Análise Avançada)

Descriptive: central tendency, dispersion, position, histograms, correlation matrix,
             scatter plots, frequency tables + charts.
Predictive:  linear regression, logistic regression (AUC/KS/precision/recall/F1/accuracy/
             confusion matrix), KMeans clustering (silhouette, inertia).
All charts rendered via Chart.js.
"""

import json
import math
import time
import warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge, Lasso, ElasticNet
from sklearn.ensemble import (
    RandomForestClassifier, GradientBoostingClassifier, ExtraTreesClassifier,
    RandomForestRegressor, GradientBoostingRegressor, ExtraTreesRegressor,
)
from sklearn.svm import SVC, SVR
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
from sklearn.naive_bayes import GaussianNB
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.model_selection import cross_val_score, StratifiedKFold, KFold
from sklearn.cluster import KMeans
from sklearn.metrics import (
    r2_score, mean_absolute_error, mean_squared_error,
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, roc_auc_score, silhouette_score,
    explained_variance_score, calinski_harabasz_score, davies_bouldin_score,
    mean_absolute_percentage_error,
)
from sklearn.preprocessing import LabelEncoder, StandardScaler

import os as _os
import sys as _sys
try:
    _stderr_backup = _sys.stderr
    _sys.stderr = open(_os.devnull, 'w')
    from autogluon.tabular import TabularPredictor as _AutoGluonPredictor
    _sys.stderr.close()
    _sys.stderr = _stderr_backup
    _AUTOGLUON_AVAILABLE = True
except ImportError:
    _sys.stderr = _stderr_backup if '_stderr_backup' in dir() else _sys.stderr
    _AutoGluonPredictor = None
    _AUTOGLUON_AVAILABLE = False

import contextlib
@contextlib.contextmanager
def _suppress_stderr():
    old = _sys.stderr
    _sys.stderr = open(_os.devnull, 'w')
    try:
        yield
    finally:
        _sys.stderr.close()
        _sys.stderr = old

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return round(float(v), 4)
    if isinstance(v, np.ndarray):
        return [_safe(x) for x in v]
    return v


def _data_to_df(data: dict) -> pd.DataFrame | None:
    rows = data.get("rows", [])
    if not rows:
        return None
    df = pd.DataFrame(rows)
    return df if not df.empty else None


# ---------------------------------------------------------------------------
# Descriptive Statistics
# ---------------------------------------------------------------------------

def compute_descriptive(data: dict) -> dict:
    df = _data_to_df(data)
    if df is None:
        return {"error": "Sem dados"}

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    numeric_stats = []
    for col in numeric_cols:
        s = df[col].dropna()
        if s.empty:
            continue
        q1 = _safe(s.quantile(0.25))
        q2 = _safe(s.quantile(0.50))
        q3 = _safe(s.quantile(0.75))
        iqr = _safe(q3 - q1) if q1 is not None and q3 is not None else None
        mode_result = s.mode()
        mode_val = _safe(mode_result.iloc[0]) if not mode_result.empty else None
        numeric_stats.append({
            "column": col, "count": int(s.count()), "missing": int(df[col].isna().sum()),
            "mean": _safe(s.mean()), "median": _safe(s.median()), "mode": mode_val,
            "std": _safe(s.std()), "variance": _safe(s.var()),
            "min": _safe(s.min()), "max": _safe(s.max()), "range": _safe(s.max() - s.min()),
            "q1": q1, "q2": q2, "q3": q3, "iqr": iqr,
            "skewness": _safe(s.skew()), "kurtosis": _safe(s.kurtosis()),
            "p5": _safe(s.quantile(0.05)), "p10": _safe(s.quantile(0.10)),
            "p90": _safe(s.quantile(0.90)), "p95": _safe(s.quantile(0.95)),
        })

    histograms = {}
    for col in numeric_cols:
        s = df[col].dropna()
        if s.empty or len(s) < 2:
            continue
        counts, edges = np.histogram(s, bins=min(20, max(5, len(s) // 5)))
        histograms[col] = {
            "labels": [f"{_safe(edges[i])}" for i in range(len(counts))],
            "values": [int(c) for c in counts],
        }

    correlation = {}
    corr_cols = numeric_cols[:12]
    if len(corr_cols) >= 2:
        corr_df = df[corr_cols].dropna()
        if len(corr_df) >= 3:
            corr_matrix = corr_df.corr(method="pearson")
            correlation = {
                "columns": corr_cols,
                "values": [[_safe(corr_matrix.iloc[i, j]) for j in range(len(corr_cols))] for i in range(len(corr_cols))],
            }

    freq_tables = {}
    for col in categorical_cols:
        vc = df[col].value_counts().head(30)
        freq_tables[col] = {
            "labels": vc.index.astype(str).tolist(),
            "values": vc.values.tolist(),
            "total": int(df[col].count()),
        }

    scatter_pairs = []
    scatter_cols = numeric_cols[:4]
    for i in range(len(scatter_cols)):
        for j in range(i + 1, len(scatter_cols)):
            cx, cy = scatter_cols[i], scatter_cols[j]
            sample = df[[cx, cy]].dropna().head(200)
            if len(sample) < 2:
                continue
            scatter_pairs.append({
                "x_col": cx, "y_col": cy,
                "x": [_safe(v) for v in sample[cx].tolist()],
                "y": [_safe(v) for v in sample[cy].tolist()],
            })

    return {
        "row_count": len(df), "col_count": len(df.columns),
        "numeric_cols": numeric_cols, "categorical_cols": categorical_cols,
        "numeric_stats": numeric_stats, "histograms": histograms,
        "correlation": correlation,
        "freq_tables": freq_tables, "scatter_pairs": scatter_pairs,
    }


# ---------------------------------------------------------------------------
# KS Statistic
# ---------------------------------------------------------------------------

def _compute_ks(y_true, y_prob_positive):
    try:
        pos = y_prob_positive[y_true == 1]
        neg = y_prob_positive[y_true == 0]
        if len(pos) == 0 or len(neg) == 0:
            return None
        stat, _ = sp_stats.ks_2samp(pos, neg)
        return _safe(stat)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Predictive Analysis
# ---------------------------------------------------------------------------

def run_prediction(data: dict, target: str, features: list[str], model_type: str, n_clusters: int = 0, task_type: str = "auto") -> dict:
    df = _data_to_df(data)
    if df is None:
        return {"error": "Sem dados"}

    if model_type == "clustering":
        return _run_clustering(df, features, n_clusters=n_clusters)
 
    if model_type == "pca":
        return _run_pca(df, features, n_components=n_clusters)
 
    if model_type == "automl":
        time_limit = n_clusters if n_clusters and n_clusters > 0 else 60
        return _run_automl(df, target, features, time_limit=time_limit, task_type=task_type)

    if target not in df.columns:
        return {"error": f"Coluna alvo '{target}' não encontrada"}

    for f in features:
        if f not in df.columns:
            return {"error": f"Feature '{f}' não encontrada"}

    work = df[features + [target]].dropna()
    if len(work) < 10:
        return {"error": "Dados insuficientes (mínimo 10 registros sem nulos)"}

    encoders = {}
    X = work[features].copy()
    for col in features:
        if not pd.api.types.is_numeric_dtype(X[col]):
            le = LabelEncoder()
            X[col] = le.fit_transform(X[col].astype(str))
            encoders[col] = {str(v): int(i) for i, v in enumerate(le.classes_)}

    y = work[target].copy()

    # For logistic regression: do NOT pre-encode here.
    # _run_logistic does its own LabelEncoder and preserves the original class names.
    if model_type == "logistic":
        return _run_logistic(X, y, features, target, work)

    target_encoded = False
    if not pd.api.types.is_numeric_dtype(y):
        le_y = LabelEncoder()
        y = pd.Series(le_y.fit_transform(y.astype(str)), index=y.index)
        target_encoded = True

    return _run_linear(X, y, features, target, work, target_encoded=target_encoded)


def _classification_metrics(y_true, y_pred, y_prob=None):
    n_classes = len(set(y_true))
    is_binary = n_classes == 2
    avg = "binary" if is_binary else "weighted"

    metrics = {
        "accuracy": _safe(accuracy_score(y_true, y_pred)),
        "precision": _safe(precision_score(y_true, y_pred, average=avg, zero_division=0)),
        "recall": _safe(recall_score(y_true, y_pred, average=avg, zero_division=0)),
        "f1": _safe(f1_score(y_true, y_pred, average=avg, zero_division=0)),
        "auc": None,
        "ks": None,
    }

    if y_prob is not None:
        try:
            if is_binary:
                prob_pos = y_prob if y_prob.ndim == 1 else y_prob[:, 1]
                metrics["auc"] = _safe(roc_auc_score(y_true, prob_pos))
                metrics["ks"] = _compute_ks(y_true, prob_pos)
            else:
                metrics["auc"] = _safe(roc_auc_score(y_true, y_prob, multi_class="ovr", average="weighted"))
        except Exception:
            pass

    return metrics


def _safe_inv(M):
    """Matrix inverse with pinv fallback — never raises."""
    try:
        return np.linalg.inv(M)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(M)


def _coeff_table_linear(X_train, y_train, model, features):
    """
    Coefficient table for linear regression.
    ALWAYS returns one row per variable (+ intercept).
    Uses pinv fallback so singular/near-singular matrices never drop rows.
    """
    n, p = X_train.shape
    df_res = n - p - 1
    all_names = ["(Intercepto)"] + list(features)
    all_coefs = np.concatenate([[model.intercept_], model.coef_])

    # Build table skeleton — even if SE/p-value computation fails,
    # every variable will still appear with its coefficient.
    table = []
    for i, name in enumerate(all_names):
        table.append({
            "name": name,
            "coeff": _safe(float(all_coefs[i])),
            "se": None, "wald": None, "p_value": None,
            "exp_b": _safe(math.exp(min(max(float(all_coefs[i]), -500), 500))),
            "lower": None, "upper": None, "vif": None,
            "significant": False,
        })

    if df_res < 1:
        return table

    try:
        y_pred_train = model.predict(X_train)
        residuals = y_train - y_pred_train
        mse = float(np.sum(residuals ** 2) / df_res)

        X_with_int = np.column_stack([np.ones(n), X_train])
        cov = _safe_inv(X_with_int.T @ X_with_int) * mse
        se_all = np.sqrt(np.abs(np.diag(cov)))

        t_crit = sp_stats.t.ppf(0.975, df_res)

        for i in range(len(all_names)):
            coef = float(all_coefs[i])
            se = float(se_all[i]) if se_all[i] > 0 else 1e-12
            t_val = coef / se
            p_val = float(2 * (1 - sp_stats.t.cdf(abs(t_val), df_res)))
            table[i].update({
                "se": _safe(se),
                "wald": _safe(t_val),
                "p_value": _safe(p_val),
                "lower": _safe(coef - t_crit * se),
                "upper": _safe(coef + t_crit * se),
                "significant": bool(p_val < 0.05),
            })

        # VIF
        if p > 1:
            for j in range(p):
                others = [k for k in range(p) if k != j]
                X_others = X_train[:, others]
                X_j = X_train[:, j]
                from sklearn.linear_model import LinearRegression as _LR
                _m = _LR().fit(X_others, X_j)
                ss_tot_j = np.sum((X_j - X_j.mean()) ** 2)
                ss_res_j = np.sum((X_j - _m.predict(X_others)) ** 2)
                r2_j = 1 - ss_res_j / ss_tot_j if ss_tot_j > 0 else 0
                vif = _safe(1 / (1 - r2_j)) if r2_j < 1 else None
                table[j + 1]["vif"] = vif  # +1 to skip intercept

    except Exception:
        pass  # table already has coeff; SE/p remain None but rows are present

    return table


def _coeff_table_logistic(X_train, y_train, model, features):
    """
    Coefficient table for logistic regression.
    ALWAYS returns one row per variable (+ intercept).
    For multiclass: uses mean coefficients across classes (OvR average).
    Uses pinv fallback for singular Fisher information matrices.
    """
    n = len(X_train)      # ← required for np.ones(n) below
    n_classes = len(model.classes_)
    all_names = ["(Intercepto)"] + list(features)

    # Extract coefficients — mean across classes for multiclass
    if model.coef_.ndim == 2 and model.coef_.shape[0] > 1:
        coefs = model.coef_.mean(axis=0)
        intercept = float(model.intercept_.mean())
    else:
        coefs = model.coef_.flatten()
        intercept = float(model.intercept_[0]) if hasattr(model.intercept_, '__len__') else float(model.intercept_)

    all_coefs = np.concatenate([[intercept], coefs])

    # Build skeleton — coeff always present even if SE computation fails
    table = []
    for i, name in enumerate(all_names):
        coef = float(all_coefs[i])
        table.append({
            "name": name,
            "coeff": _safe(coef),
            "se": None, "wald": None, "p_value": None,
            "exp_b": _safe(math.exp(min(max(coef, -500), 500))),
            "lower": None, "upper": None,
            "significant": False,
        })

    try:
        y_prob = model.predict_proba(X_train)
        X_with_int = np.column_stack([np.ones(n), X_train])

        if n_classes == 2:
            p_hat = np.clip(y_prob[:, 1], 1e-10, 1 - 1e-10)
            W = p_hat * (1 - p_hat)
            # Use element-wise: (X.T * W) @ X  — avoids n×n diag matrix
            XtWX = (X_with_int.T * W) @ X_with_int
            cov_matrix = _safe_inv(XtWX)
        else:
            # Average Fisher information across OvR models
            cov_accum = np.zeros((X_with_int.shape[1], X_with_int.shape[1]))
            for c in range(n_classes):
                p_c = np.clip(y_prob[:, c], 1e-10, 1 - 1e-10)
                W_c = p_c * (1 - p_c)
                XtWX_c = (X_with_int.T * W_c) @ X_with_int
                cov_accum += _safe_inv(XtWX_c)
            cov_matrix = cov_accum / n_classes

        se_all = np.sqrt(np.abs(np.diag(cov_matrix)))

        for i, name in enumerate(all_names):
            coef = float(all_coefs[i])
            se = float(se_all[i]) if se_all[i] > 0 else 1e-12
            wald = (coef / se) ** 2
            p_val = float(1 - sp_stats.chi2.cdf(wald, 1))
            lower_coef = coef - 1.96 * se
            upper_coef = coef + 1.96 * se
            table[i].update({
                "se": _safe(se),
                "wald": _safe(wald),
                "p_value": _safe(p_val),
                "exp_b": _safe(math.exp(min(max(coef, -500), 500))),
                "lower": _safe(math.exp(min(max(lower_coef, -500), 500))),
                "upper": _safe(math.exp(min(max(upper_coef, -500), 500))),
                "significant": bool(p_val < 0.05),
            })

    except Exception:
        pass  # skeleton already has all rows with coefficients

    return table


def _variable_recommendation(coeff_table):
    if not coeff_table:
        return ""
    sig_vars = [r for r in coeff_table if r["significant"] and r["name"] != "(Intercepto)"]
    nonsig_vars = [r for r in coeff_table if not r["significant"] and r["name"] != "(Intercepto)"]

    if not sig_vars:
        return "Nenhuma variável apresentou significância estatística (p < 0.05). Considere revisar as features selecionadas, aumentar o volume de dados ou verificar a adequação do modelo."

    sig_vars.sort(key=lambda x: x["p_value"] if x["p_value"] is not None else 1)

    parts = []
    parts.append(f"<strong>{len(sig_vars)}</strong> variável(eis) estatisticamente significativa(s) (p &lt; 0.05):")
    for v in sig_vars:
        p_str = f"{v['p_value']:.10f}".rstrip('0').rstrip('.') if v['p_value'] is not None and v['p_value'] >= 1e-10 else "&lt; 0.0000000001"
        direction = "positivo" if (v['coeff'] or 0) > 0 else "negativo"
        exp_str = f"{v['exp_b']:.10f}".rstrip('0').rstrip('.')
        parts.append(f"&nbsp;&nbsp;→ <strong>{v['name']}</strong> (p = {p_str}, efeito {direction}, Exp(B) = {exp_str})" if v['exp_b'] is not None else f"&nbsp;&nbsp;→ <strong>{v['name']}</strong> (p = {p_str}, efeito {direction})")

    if nonsig_vars:
        names = ", ".join(v["name"] for v in nonsig_vars)
        parts.append(f"Variáveis <strong>não significativas</strong> (p ≥ 0.05): {names}. Considere removê-las para simplificar o modelo.")

    return "<br>".join(parts)

# ── Champion rationale ────────────────────────────────────────────────
def _build_rationale(lb, task_name, metric_name):
    valid = [r for r in lb if r["error"] is None]
    if not valid:
        return ""
    best = valid[0]
    runner = valid[1] if len(valid) > 1 else None
    margin_txt = ""
    if runner and runner["score"] is not None and best["score"] is not None:
        diff = (best["score"] or 0) - (runner["score"] or 0)
        margin_txt = (
            f" Margem sobre o 2º colocado ({runner['name']}): "
            f"{diff:+.6f}."
        )
    metric_explain = {
        "regression": "R² mede a proporção da variância explicada (0 a 1). Valores mais altos indicam melhor capacidade preditiva.",
        "binary": "AUC-ROC mede a capacidade de discriminação entre classes (0.5 = aleatório, 1.0 = perfeito).",
        "multiclass": "AUC-ROC ponderado (OvR) avalia a discriminação entre múltiplas classes simultaneamente.",
    }
    n_ok = len(valid)
    n_fail = len(lb) - n_ok
    fail_txt = f" {n_fail} modelo(s) falharam durante o treinamento." if n_fail > 0 else ""
    return (
        f"<strong>{best['name']}</strong> foi selecionado como modelo campeão por apresentar "
        f"o maior <strong>{metric_name}</strong> médio em validação cruzada 5-fold: "
        f"<strong>{_safe(best['score'])}</strong>"
        f"{' ± ' + str(_safe(best['std'])) if best.get('std') is not None else ''}. "
        f"Foram avaliados {n_ok} modelos com convergência bem-sucedida "
        f"de {len(lb)} candidatos.{fail_txt}{margin_txt} "
        f"{metric_explain.get(task_name, '')}"
    )


# ---------------------------------------------------------------------------
# AutoML — multi-model tournament with AutoGluon fallback to sklearn
# ---------------------------------------------------------------------------

def _run_automl(df: pd.DataFrame, target: str, features: list[str], time_limit: int = 60, task_type: str = "auto") -> dict:
    """
    AutoML engine.
    - If AutoGluon is installed: uses TabularPredictor (best_quality preset, 60s budget).
    - Otherwise: sklearn tournament — 9-10 models, 5-fold CV, ranked leaderboard.
      Automatically detects task type (binary clf / multiclass clf / regression).
    Returns leaderboard + best-model metrics + feature importances.
    """
    for f in features:
        if f not in df.columns:
            return {"error": f"Feature '{f}' não encontrada"}
    if target not in df.columns:
        return {"error": f"Coluna alvo '{target}' não encontrada"}

    work = df[features + [target]].dropna()
    n = len(work)
    if n < 10:
        return {"error": "Dados insuficientes (mínimo 10 registros)"}

    # ── detect task type ──────────────────────────────────────────────────
    y_raw = work[target].copy()
    n_unique = y_raw.nunique()

    if task_type == "regression":
        is_regression, is_binary, is_multiclass = True, False, False
    elif task_type == "classification":
        is_regression = False
        is_binary = n_unique == 2
        is_multiclass = n_unique > 2
    else:
        # auto-detect (comportamento original)
        is_regression = pd.api.types.is_numeric_dtype(y_raw) and n_unique > 10
        is_binary     = not is_regression and n_unique == 2
        is_multiclass = not is_regression and n_unique > 2

    task = "regression" if is_regression else ("binary" if is_binary else "multiclass")

    # ── encode features ───────────────────────────────────────────────────
    X_enc = work[features].copy()
    for col in features:
        if not pd.api.types.is_numeric_dtype(X_enc[col]):
            le = LabelEncoder()
            X_enc[col] = le.fit_transform(X_enc[col].astype(str))
    X = X_enc.values.astype(float)

    # ── encode target ─────────────────────────────────────────────────────
    le_y = LabelEncoder()
    if is_regression:
        y = y_raw.values.astype(float)
        class_names = None
    else:
        y = le_y.fit_transform(y_raw.astype(str))
        class_names = [str(c) for c in le_y.classes_]

    # ── try AutoGluon first ───────────────────────────────────────────────
    if _AUTOGLUON_AVAILABLE:
        return _run_automl_autogluon(work, features, target, task, class_names, n, task_type=task_type, time_limit=time_limit)

    # ── sklearn tournament ────────────────────────────────────────────────
    return _run_automl_sklearn(X, y, features, target, task, class_names, n, work)


def _run_automl_autogluon(work, features, target, task, class_names, n, task_type="auto", time_limit=60):
    """AutoGluon TabularPredictor backend."""
    import tempfile, os, shutil
    tmp_dir = tempfile.mkdtemp(prefix="qi_ag_")
    try:
        problem_type = {"regression": "regression", "binary": "binary", "multiclass": "multiclass"}[task]
        eval_metric  = "r2" if task == "regression" else "roc_auc" if task == "binary" else "accuracy"

        with _suppress_stderr():
            predictor = _AutoGluonPredictor(
                label=target,
                problem_type=problem_type,
                eval_metric=eval_metric,
                path=tmp_dir,
                verbosity=0,
            )
            predictor.fit(
                work[features + [target]],
                time_limit=max(time_limit, 30),
                presets="medium_quality",
                excluded_model_types=["CAT", "NN_TORCH", "FASTAI"],
            )
            lb = predictor.leaderboard(silent=True)
        
        lb_records = lb[["model", "score_val", "fit_time"]].head(10).to_dict("records")
        leaderboard = [
            {"name": str(r["model"]), "score": _safe(r["score_val"]),
             "score_label": eval_metric.upper(), "time": _safe(r["fit_time"])}
            for r in lb_records
        ]

        # Feature importance
        fi = predictor.feature_importance(work[features + [target]], silent=True)
        feat_imp = [{"feature": str(f), "importance": _safe(float(fi.loc[f, "importance"]))}
                    for f in fi.index[:15]]

        # Best model predictions for confusion matrix / scatter
        best_name = leaderboard[0]["name"] if leaderboard else "best"
        y_pred_raw = predictor.predict(work[features])

        result = {
            "model_type": "automl", "backend": "autogluon",
            "task": task, "target": target, "features": features,
            "n_obs": n, "n_models": len(leaderboard),
            "best_model": best_name,
            "best_score": leaderboard[0]["score"] if leaderboard else None,
            "score_label": eval_metric.upper(),
            "leaderboard": leaderboard,
            "feature_importance": feat_imp,
            "class_names": class_names,
        }

        # Champion rationale
        runner = leaderboard[1] if len(leaderboard) > 1 else None
        margin_txt = ""
        if runner and runner["score"] is not None and leaderboard[0]["score"] is not None:
            diff = (leaderboard[0]["score"] or 0) - (runner["score"] or 0)
            margin_txt = f" Margem sobre o 2º ({runner['name']}): {diff:+.6f}."
        metric_explain = {
            "r2": "R² mede a proporção da variância explicada (0 a 1).",
            "roc_auc": "AUC-ROC mede a capacidade de discriminação entre classes.",
            "accuracy": "Acurácia mede a proporção de classificações corretas.",
        }
        champion_rationale = (
            f"<strong>{best_name}</strong> foi selecionado pelo AutoGluon como melhor modelo "
            f"com base no <strong>{eval_metric.upper()}</strong> de validação: "
            f"<strong>{_safe(leaderboard[0]['score'])}</strong>. "
            f"O torneio avaliou {len(leaderboard)} modelo(s) em {time_limit}s.{margin_txt} "
            f"{metric_explain.get(eval_metric, '')}"
        )

        if task == "regression":
            y_true = work[target].values.astype(float)
            y_pred = y_pred_raw.values.astype(float)
            result.update({
                "r2": _safe(r2_score(y_true, y_pred)),
                "mae": _safe(mean_absolute_error(y_true, y_pred)),
                "rmse": _safe(float(np.sqrt(mean_squared_error(y_true, y_pred)))),
                "actual":    [_safe(v) for v in y_true[:300]],
                "predicted": [_safe(v) for v in y_pred[:300]],
            })
        else:
            le_y = LabelEncoder().fit(work[target].astype(str))
            y_true = le_y.transform(work[target].astype(str))
            y_pred = le_y.transform(y_pred_raw.astype(str))
            class_names = [str(c) for c in le_y.classes_]  # usar labels do mesmo encoder
            cm = confusion_matrix(y_true, y_pred, labels=list(range(len(class_names))))
            result.update({
                "confusion_matrix": cm.tolist(),
                "accuracy": _safe(accuracy_score(y_true, y_pred)),
            })

        # ACOMPANHAR
        result.update({
            "champion_rationale": champion_rationale,
        })

        return result

    except Exception as e:
        # AutoGluon failed — fall back to sklearn
        return {"error": f"AutoGluon erro: {str(e)[:200]}"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_automl_sklearn(X, y, features, target, task, class_names, n, work_df):
    """
    sklearn multi-model tournament.
    Trains all candidate models via cross-validation, ranks them,
    then re-fits the winner on full data for final metrics + importance.
    """
    warnings.filterwarnings("ignore")

    if task == "regression":
        cv   = KFold(n_splits=5, shuffle=True, random_state=42)
        metric = "r2"
        candidates = [
            ("Ridge",             Ridge()),
            ("Lasso",             Lasso()),
            ("ElasticNet",        ElasticNet()),
            ("Random Forest",     RandomForestRegressor(n_estimators=100, random_state=42)),
            ("Gradient Boosting", GradientBoostingRegressor(n_estimators=100, random_state=42)),
            ("Extra Trees",       ExtraTreesRegressor(n_estimators=100, random_state=42)),
            ("Decision Tree",     DecisionTreeRegressor(random_state=42)),
            ("KNN",               KNeighborsRegressor()),
            ("SVR (scaled)",      Pipeline([("sc", StandardScaler()), ("svr", SVR())])),
            ("MLP",               MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42)),
        ]
    else:
        cv   = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        metric = "roc_auc" if task == "binary" else "roc_auc_ovr_weighted"
        scoring = "roc_auc" if task == "binary" else "roc_auc_ovr_weighted"
        candidates = [
            ("Logistic Regression", LogisticRegression(max_iter=1000, random_state=42)),
            ("Random Forest",       RandomForestClassifier(n_estimators=100, random_state=42)),
            ("Gradient Boosting",   GradientBoostingClassifier(n_estimators=100, random_state=42)),
            ("Extra Trees",         ExtraTreesClassifier(n_estimators=100, random_state=42)),
            ("Decision Tree",       DecisionTreeClassifier(random_state=42)),
            ("KNN",                 KNeighborsClassifier()),
            ("Naive Bayes",         GaussianNB()),
            ("SVC (scaled)",        Pipeline([("sc", StandardScaler()), ("svc", SVC(probability=True, random_state=42))])),
            ("MLP",                 MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42)),
        ]
        scoring = "roc_auc" if task == "binary" else "roc_auc_ovr_weighted"
        metric = "AUC" if task == "binary" else "AUC (OvR)"

    # ── CV tournament ─────────────────────────────────────────────────────
    leaderboard = []
    for name, model in candidates:
        t0 = time.time()
        try:
            sc = cross_val_score(
                model, X, y, cv=cv,
                scoring="roc_auc" if task == "binary" else ("roc_auc_ovr_weighted" if task == "multiclass" else "r2"),
                error_score=float("nan"),
                n_jobs=1,
            )
            mean_sc = float(np.nanmean(sc))
            std_sc  = float(np.nanstd(sc))
            err = None
        except Exception as e:
            mean_sc, std_sc, err = float("nan"), 0.0, str(e)[:80]
        leaderboard.append({
            "name": name, "score": _safe(mean_sc), "std": _safe(std_sc),
            "score_label": metric, "time": _safe(time.time() - t0),
            "error": err,
        })

    leaderboard.sort(key=lambda r: -(r["score"] or -999))

    # ── Re-fit best model on full data ────────────────────────────────────
    best_entry = next((r for r in leaderboard if r["error"] is None), None)
    if best_entry is None:
        return {"error": "Nenhum modelo convergiu com sucesso"}

    best_name = best_entry["name"]
    best_model_obj = next(m for (nm, m) in candidates if nm == best_name)
    best_model_obj.fit(X, y)

    y_pred = best_model_obj.predict(X)

    result = {
        "model_type": "automl", "backend": "sklearn",
        "task": task, "target": target, "features": features,
        "n_obs": n, "n_models": len(leaderboard),
        "best_model": best_name,
        "best_score": best_entry["score"],
        "best_score_std": best_entry["std"],
        "score_label": metric,
        "leaderboard": leaderboard,
        "class_names": class_names,
    }

    # ── Feature importance ────────────────────────────────────────────────
    fi_model = best_model_obj
    if isinstance(fi_model, Pipeline):
        fi_model = fi_model.steps[-1][1]
    feat_imp = []
    if hasattr(fi_model, "feature_importances_"):
        imp = fi_model.feature_importances_
        feat_imp = sorted(
            [{"feature": features[i], "importance": _safe(float(imp[i]))} for i in range(len(features))],
            key=lambda x: -(x["importance"] or 0),
        )
    elif hasattr(fi_model, "coef_"):
        coef = fi_model.coef_.flatten() if fi_model.coef_.ndim > 1 else fi_model.coef_
        # normalised absolute coefficient as proxy
        total = sum(abs(c) for c in coef) or 1
        feat_imp = sorted(
            [{"feature": features[i], "importance": _safe(float(abs(coef[i]) / total))} for i in range(len(features))],
            key=lambda x: -(x["importance"] or 0),
        )
    result["feature_importance"] = feat_imp

    # ── Task-specific metrics ─────────────────────────────────────────────
    if task == "regression":
        result.update({
            "r2":   _safe(r2_score(y, y_pred)),
            "mae":  _safe(mean_absolute_error(y, y_pred)),
            "rmse": _safe(float(np.sqrt(mean_squared_error(y, y_pred)))),
            "actual":    [_safe(float(v)) for v in y[:300]],
            "predicted": [_safe(float(v)) for v in y_pred[:300]],
        })
    else:
        cm = confusion_matrix(y, y_pred, labels=list(range(len(class_names))))
        acc = _safe(accuracy_score(y, y_pred))
        # Per-class accuracy
        class_acc = []
        for i, cn in enumerate(class_names):
            total_i = int(cm[i].sum())
            correct_i = int(cm[i, i])
            class_acc.append({"class": cn, "total": total_i, "correct": correct_i,
                               "pct": _safe(correct_i / total_i * 100) if total_i > 0 else 0})
        result.update({
            "confusion_matrix": cm.tolist(),
            "accuracy": acc,
            "class_accuracy": class_acc,
            "overall_accuracy": acc,
        })

        # ACOMPANHAR
        result.update({
            "champion_rationale": _build_rationale(leaderboard, task, metric),
        })

    return result


def _run_linear(X, y, features, target, work, target_encoded=False):
    X_all = X.values
    y_all = y.values
    n = len(y_all)
    p = X_all.shape[1]

    model = LinearRegression()
    model.fit(X_all, y_all)
    y_pred = model.predict(X_all)
    residuals = y_all - y_pred

    y_mean = float(np.mean(y_all))
    ss_total = float(np.sum((y_all - y_mean) ** 2))
    ss_residual = float(np.sum(residuals ** 2))
    ss_regression = ss_total - ss_residual

    df_regression = p
    df_residual = n - p - 1
    df_total = n - 1

    ms_regression = ss_regression / df_regression if df_regression > 0 else 0
    ms_residual = ss_residual / df_residual if df_residual > 0 else 1e-15

    f_stat = ms_regression / ms_residual if ms_residual > 0 else 0
    f_p_value = 1 - sp_stats.f.cdf(f_stat, df_regression, df_residual) if df_residual > 0 else 1

    r2 = ss_regression / ss_total if ss_total > 0 else 0
    r2_adj = 1 - (1 - r2) * df_total / df_residual if df_residual > 0 else r2
    multiple_r = math.sqrt(max(r2, 0))
    std_error_reg = math.sqrt(ms_residual)

    aic = n * math.log(ss_residual / n) + 2 * (p + 1) if n > 0 and ss_residual > 0 else None
    aicc = aic + 2 * (p + 2) * (p + 3) / (n - p - 3) if aic is not None and (n - p - 3) > 0 else None
    sbc = n * math.log(ss_residual / n) + (p + 1) * math.log(n) if n > 0 and ss_residual > 0 else None

    regression_stats = {
        "multiple_r": _safe(multiple_r),
        "r_square": _safe(r2),
        "r_square_adj": _safe(r2_adj),
        "std_error": _safe(std_error_reg),
        "observations": n,
        "aic": _safe(aic),
        "aicc": _safe(aicc),
        "sbc": _safe(sbc),
    }

    anova = {
        "regression": {
            "df": df_regression, "ss": _safe(ss_regression),
            "ms": _safe(ms_regression), "f": _safe(f_stat),
            "f_significance": _safe(f_p_value),
        },
        "residual": {
            "df": df_residual, "ss": _safe(ss_residual),
            "ms": _safe(ms_residual),
        },
        "total": {
            "df": df_total, "ss": _safe(ss_total),
        },
    }

    # ALWAYS show all variables via the robust _coeff_table_linear
    coeff_table = _coeff_table_linear(X_all, y_all, model, features)
    recommendation = _variable_recommendation(coeff_table)

    std_error_safe = std_error_reg if std_error_reg > 0 else 1
    std_residuals = residuals / std_error_safe
    max_residuals = min(n, 500)
    residual_output = [
        {
            "obs": int(i + 1),
            "predicted": _safe(float(y_pred[i])),
            "residual": _safe(float(residuals[i])),
            "std_residual": _safe(float(std_residuals[i])),
        }
        for i in range(max_residuals)
    ]

    dw = None
    if n > 1:
        diff_res = np.diff(residuals)
        dw = _safe(float(np.sum(diff_res ** 2) / ss_residual)) if ss_residual > 0 else None

    median_val = float(np.median(y_all))
    y_true_bin = (y_all > median_val).astype(int)
    y_pred_bin = (y_pred > median_val).astype(int)
    y_range = max(y_pred.max() - y_pred.min(), 1e-9)
    y_prob_lin = (y_pred - y_pred.min()) / y_range
    clf_metrics = _classification_metrics(y_true_bin, y_pred_bin, y_prob_lin)

    try:
        mape = _safe(mean_absolute_percentage_error(y_all, y_pred))
    except Exception:
        mape = None

    return {
        "model_type": "linear", "target": target, "features": features,
        "regression_stats": regression_stats,
        "anova": anova,
        "metrics": {
            "r2": _safe(r2), "r2_adj": _safe(r2_adj),
            "mae": _safe(mean_absolute_error(y_all, y_pred)),
            "mse": _safe(mean_squared_error(y_all, y_pred)),
            "rmse": _safe(float(np.sqrt(mean_squared_error(y_all, y_pred)))),
            "mape": mape,
            "explained_var": _safe(explained_variance_score(y_all, y_pred)),
        },
        "classification_metrics": clf_metrics,
        "coeff_table": coeff_table,
        "recommendation": recommendation,
        "coefficients": {f: _safe(c) for f, c in zip(features, model.coef_)},
        "intercept": _safe(model.intercept_),
        "actual": [_safe(v) for v in y_all[:500]],
        "predicted": [_safe(v) for v in y_pred[:500]],
        "residual_output": residual_output,
        "durbin_watson": dw,
        "observations": n,
    }


def _run_logistic(X, y, features, target, work):
    """
    Logistic regression.
    FIX 1: coefficient table ALWAYS has all variables (intercept + all features).
    FIX 2: confusion matrix ALWAYS shows ALL classes, even if some have 0 predictions.
            Categorical targets are label-encoded; class_names shows original labels.
    """
    le_target = LabelEncoder()
    # FIX: encode to str first so categorical targets are handled uniformly
    y_enc = le_target.fit_transform(y.astype(str))
    class_names = [str(c) for c in le_target.classes_]   # original labels
    n_classes = len(class_names)
    is_binary = n_classes == 2

    X_all = X.values
    y_all = y_enc
    n = len(y_all)
    p = X_all.shape[1]
    all_labels = list(range(n_classes))   # explicit label list for confusion_matrix

    try:
        model = LogisticRegression(max_iter=5000, random_state=42, solver="lbfgs")
        model.fit(X_all, y_all)
    except Exception:
        try:
            scaler = StandardScaler()
            X_all = scaler.fit_transform(X_all)
            model = LogisticRegression(max_iter=5000, random_state=42, solver="saga")
            model.fit(X_all, y_all)
        except Exception as e:
            return {"error": f"Erro ao treinar modelo logístico: {str(e)[:200]}"}

    y_pred = model.predict(X_all)

    try:
        y_prob = model.predict_proba(X_all)
    except Exception:
        y_prob = None

    # FIX 2: force ALL classes in confusion matrix via labels= parameter
    cm = confusion_matrix(y_all, y_pred, labels=all_labels)
    clf_metrics = _classification_metrics(y_all, y_pred, y_prob)

    # Significance testing
    model_summary = None
    omnibus_test = None
    try:
        eps = 1e-15
        y_prob_clipped = np.clip(y_prob, eps, 1 - eps)
        ll_model = sum(math.log(y_prob_clipped[i, y_all[i]]) for i in range(n))
        class_freq = np.bincount(y_all, minlength=n_classes) / n
        class_freq = np.clip(class_freq, eps, 1 - eps)
        ll_null = sum(math.log(class_freq[y_all[i]]) for i in range(n))

        chi2_model = 2 * (ll_model - ll_null)
        df_model = p
        chi2_p_value = 1 - sp_stats.chi2.cdf(chi2_model, df_model) if df_model > 0 else 1

        mcfadden = 1 - (ll_model / ll_null) if ll_null != 0 else 0
        cox_snell = 1 - math.exp((-2 / n) * (ll_model - ll_null))
        cox_snell_max = 1 - math.exp((2 * ll_null) / n)
        nagelkerke = cox_snell / cox_snell_max if cox_snell_max > 0 else 0

        aic = -2 * ll_model + 2 * (p + 1)
        bic = -2 * ll_model + (p + 1) * math.log(n)

        model_summary = {
            "ll0": _safe(ll_null),
            "ll1": _safe(ll_model),
            "neg2ll": _safe(-2 * ll_model),
            "neg2ll_null": _safe(-2 * ll_null),
            "mcfadden_r2": _safe(mcfadden),
            "cox_snell_r2": _safe(cox_snell),
            "nagelkerke_r2": _safe(nagelkerke),
            "aic": _safe(aic),
            "bic": _safe(bic),
            "observations": n,
        }

        omnibus_test = {
            "chi2": _safe(chi2_model),
            "df": df_model,
            "p_value": _safe(chi2_p_value),
        }
    except Exception:
        pass

    # FIX 1: use robust _coeff_table_logistic — always returns all variables
    coeff_table = _coeff_table_logistic(X_all, y_all, model, features)
    recommendation = _variable_recommendation(coeff_table)

    # FIX 2: class_accuracy uses all_labels so every class has a row
    class_accuracy = []
    for i, cn in enumerate(class_names):
        total_actual = int(cm[i].sum())
        correct = int(cm[i, i])
        pct = _safe(correct / total_actual * 100) if total_actual > 0 else 0
        class_accuracy.append({"class": cn, "total": total_actual, "correct": correct, "pct": pct})
    overall_correct = int(np.trace(cm))
    overall_pct = _safe(overall_correct / n * 100) if n > 0 else 0

    roc_curve_data = None
    if is_binary and y_prob is not None:
        try:
            from sklearn.metrics import roc_curve
            prob_pos = y_prob[:, 1]
            fpr, tpr, _ = roc_curve(y_all, prob_pos)
            step = max(1, len(fpr) // 100)
            roc_curve_data = {
                "fpr": [_safe(v) for v in fpr[::step]],
                "tpr": [_safe(v) for v in tpr[::step]],
            }
        except Exception:
            pass

    return {
        "model_type": "logistic", "target": target, "features": features,
        "model_summary": model_summary,
        "omnibus_test": omnibus_test,
        "classification_metrics": clf_metrics,
        "coeff_table": coeff_table,
        "recommendation": recommendation,
        "confusion_matrix": cm.tolist(),
        "class_names": class_names,        # original decoded labels
        "class_accuracy": class_accuracy,
        "overall_accuracy": overall_pct,
        "roc_curve": roc_curve_data,
        "observations": n,
    }

def _run_pca(df, features, n_components: int = 0):
    """Principal Component Analysis — dimensionality reduction."""
    from sklearn.decomposition import PCA
 
    valid_features = [f for f in features if f in df.columns]
    if len(valid_features) < 2:
        return {"error": "PCA requer pelo menos 2 features"}
 
    work = df[valid_features].dropna()
    X = work.copy()
    encoders = {}
    for col in valid_features:
        if not pd.api.types.is_numeric_dtype(X[col]):
            le = LabelEncoder()
            X[col] = le.fit_transform(X[col].astype(str))
            encoders[col] = {str(v): int(i) for i, v in enumerate(le.classes_)}
 
    if len(X) < 5:
        return {"error": "Dados insuficientes (mínimo 5 registros sem nulos)"}
 
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X.values)
 
    max_components = min(len(valid_features), len(X))
    if n_components and 1 <= n_components <= max_components:
        n_comp = n_components
    else:
        n_comp = max_components
 
    pca = PCA(n_components=n_comp, random_state=42)
    X_pca = pca.fit_transform(X_scaled)
 
    explained = pca.explained_variance_ratio_
    cumulative = np.cumsum(explained)
 
    # Auto-select: components explaining ≥ 80% variance
    auto_k = int(np.searchsorted(cumulative, 0.80) + 1)
    auto_k = min(auto_k, n_comp)
 
    # Loadings matrix (components × features)
    loadings = pca.components_  # shape: (n_comp, n_features)
    loadings_data = []
    for i in range(n_comp):
        row = {"component": f"PC{i+1}"}
        for j, feat in enumerate(valid_features):
            row[feat] = _safe(float(loadings[i, j]))
        loadings_data.append(row)
 
    # Top contributors per component
    top_contributors = []
    for i in range(min(n_comp, 10)):
        abs_loadings = np.abs(loadings[i])
        sorted_idx = np.argsort(abs_loadings)[::-1]
        contribs = []
        for idx in sorted_idx[:5]:
            contribs.append({
                "feature": valid_features[idx],
                "loading": _safe(float(loadings[i, idx])),
                "abs_loading": _safe(float(abs_loadings[idx])),
            })
        top_contributors.append({
            "component": f"PC{i+1}",
            "explained_pct": _safe(float(explained[i]) * 100),
            "contributors": contribs,
        })
 
    # Scatter of first 2 PCs
    scatter = None
    if n_comp >= 2:
        sample_n = min(500, len(X_pca))
        scatter = {
            "x_col": "PC1", "y_col": "PC2",
            "points": [
                {"x": _safe(float(X_pca[i, 0])), "y": _safe(float(X_pca[i, 1]))}
                for i in range(sample_n)
            ],
        }
 
    # Biplot vectors (feature arrows in PC1-PC2 space)
    biplot_vectors = None
    if n_comp >= 2:
        biplot_vectors = [
            {
                "feature": valid_features[j],
                "pc1": _safe(float(loadings[0, j])),
                "pc2": _safe(float(loadings[1, j])),
            }
            for j in range(len(valid_features))
        ]
 
    # Eigenvalues
    eigenvalues = [
        {
            "component": f"PC{i+1}",
            "eigenvalue": _safe(float(pca.explained_variance_[i])),
            "explained_pct": _safe(float(explained[i]) * 100),
            "cumulative_pct": _safe(float(cumulative[i]) * 100),
        }
        for i in range(n_comp)
    ]
 
    # Kaiser criterion: eigenvalues > 1
    kaiser_k = int(np.sum(pca.explained_variance_ > 1.0))
 
    return {
        "model_type": "pca",
        "features": valid_features,
        "n_components": n_comp,
        "auto_k": auto_k,
        "kaiser_k": kaiser_k,
        "total_points": len(X),
        "explained_variance": [_safe(float(v) * 100) for v in explained],
        "cumulative_variance": [_safe(float(v) * 100) for v in cumulative],
        "eigenvalues": eigenvalues,
        "loadings": loadings_data,
        "top_contributors": top_contributors,
        "scatter": scatter,
        "biplot_vectors": biplot_vectors,
        "metrics": {
            "total_variance_explained": _safe(float(cumulative[auto_k - 1]) * 100) if auto_k <= len(cumulative) else None,
            "n_components_80pct": auto_k,
            "kaiser_components": kaiser_k,
        },
        "classification_metrics": {
            "accuracy": None, "precision": None, "recall": None,
            "f1": None, "auc": None, "ks": None,
        },
    }


def _run_pca_OLD(df, features, n_components: int = 0):
    """Principal Component Analysis — dimensionality reduction."""
    from sklearn.decomposition import PCA
 
    valid_features = [f for f in features if f in df.columns]
    if len(valid_features) < 2:
        return {"error": "PCA requer pelo menos 2 features"}
 
    work = df[valid_features].dropna()
    X = work.copy()
    for col in valid_features:
        if not pd.api.types.is_numeric_dtype(X[col]):
            le = LabelEncoder()
            X[col] = le.fit_transform(X[col].astype(str))
 
    if len(X) < 5:
        return {"error": "Dados insuficientes (mínimo 5 registros sem nulos)"}
 
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X.values)
 
    max_comp = min(len(valid_features), len(X))
    n_comp = n_components if 1 <= n_components <= max_comp else max_comp
 
    pca = PCA(n_components=n_comp, random_state=42)
    X_pca = pca.fit_transform(X_scaled)
 
    explained = pca.explained_variance_ratio_
    cumulative = np.cumsum(explained)
    auto_k = min(int(np.searchsorted(cumulative, 0.80) + 1), n_comp)
    kaiser_k = int(np.sum(pca.explained_variance_ > 1.0))
 
    loadings = pca.components_
    loadings_data = []
    for i in range(n_comp):
        row = {"component": f"PC{i+1}"}
        for j, feat in enumerate(valid_features):
            row[feat] = _safe(float(loadings[i, j]))
        loadings_data.append(row)
 
    top_contributors = []
    for i in range(min(n_comp, 10)):
        abs_ld = np.abs(loadings[i])
        sorted_idx = np.argsort(abs_ld)[::-1]
        contribs = [{"feature": valid_features[idx], "loading": _safe(float(loadings[i, idx])),
                      "abs_loading": _safe(float(abs_ld[idx]))} for idx in sorted_idx[:5]]
        top_contributors.append({"component": f"PC{i+1}",
                                  "explained_pct": _safe(float(explained[i]) * 100),
                                  "contributors": contribs})
 
    scatter = None
    if n_comp >= 2:
        sn = min(500, len(X_pca))
        scatter = {"x_col": "PC1", "y_col": "PC2",
                   "points": [{"x": _safe(float(X_pca[i, 0])), "y": _safe(float(X_pca[i, 1]))} for i in range(sn)]}
 
    biplot_vectors = None
    if n_comp >= 2:
        biplot_vectors = [{"feature": valid_features[j], "pc1": _safe(float(loadings[0, j])),
                           "pc2": _safe(float(loadings[1, j]))} for j in range(len(valid_features))]
 
    eigenvalues = [{"component": f"PC{i+1}", "eigenvalue": _safe(float(pca.explained_variance_[i])),
                    "explained_pct": _safe(float(explained[i]) * 100),
                    "cumulative_pct": _safe(float(cumulative[i]) * 100)} for i in range(n_comp)]
 
    return {
        "model_type": "pca", "features": valid_features, "n_components": n_comp,
        "auto_k": auto_k, "kaiser_k": kaiser_k, "total_points": len(X),
        "explained_variance": [_safe(float(v) * 100) for v in explained],
        "cumulative_variance": [_safe(float(v) * 100) for v in cumulative],
        "eigenvalues": eigenvalues, "loadings": loadings_data,
        "top_contributors": top_contributors, "scatter": scatter,
        "biplot_vectors": biplot_vectors,
        "metrics": {"total_variance_explained": _safe(float(cumulative[auto_k - 1]) * 100) if auto_k <= len(cumulative) else None,
                    "n_components_80pct": auto_k, "kaiser_components": kaiser_k},
        "classification_metrics": {"accuracy": None, "precision": None, "recall": None,
                                    "f1": None, "auc": None, "ks": None},
    }
 
 
def _run_clustering(df, features, n_clusters: int = 0):
    valid_features = [f for f in features if f in df.columns]
    if len(valid_features) < 2:
        return {"error": "Clusterização requer pelo menos 2 features"}

    work = df[valid_features].dropna()
    X = work.copy()
    for col in valid_features:
        if not pd.api.types.is_numeric_dtype(X[col]):
            le = LabelEncoder()
            X[col] = le.fit_transform(X[col].astype(str))

    if len(X) < 10:
        return {"error": "Dados insuficientes (mínimo 10 registros sem nulos)"}

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X.values)

    max_k = min(10, len(X) // 3)
    if max_k < 2:
        max_k = 2
    inertias = []
    silhouettes = []
    for k in range(2, max_k + 1):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X_scaled)
        inertias.append({"k": k, "inertia": _safe(km.inertia_)})
        sil = silhouette_score(X_scaled, labels) if len(set(labels)) > 1 else 0
        silhouettes.append({"k": k, "silhouette": _safe(sil)})

    auto_k = True
    if n_clusters and n_clusters >= 2:
        best_k = min(n_clusters, max_k)
        auto_k = False
    else:
        best_k = max(silhouettes, key=lambda s: s["silhouette"] or 0)["k"]

    if auto_k:
        best_sil = next(s for s in silhouettes if s["k"] == best_k)
        rationale = (
            f"K={best_k} selecionado automaticamente. "
            f"Critério: maior Silhouette Score ({best_sil['silhouette']:.4f}). "
        )
        if len(inertias) >= 3:
            drops = []
            for i in range(1, len(inertias)):
                prev = inertias[i - 1]["inertia"]
                curr = inertias[i]["inertia"]
                drop_pct = (prev - curr) / prev * 100 if prev > 0 else 0
                drops.append({"k": inertias[i]["k"], "drop_pct": round(drop_pct, 1)})
            max_drop_k = max(drops, key=lambda d: d["drop_pct"])["k"]
            rationale += (
                f"Pelo método do cotovelo, a maior queda percentual de inertia ocorre em K={max_drop_k}. "
                f"A partir desse ponto, acrescentar clusters gera ganho marginal decrescente."
            )
        else:
            rationale += "Dados insuficientes para análise de cotovelo detalhada."
    else:
        rationale = f"K={best_k} definido manualmente pelo usuário."

    km_final = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    final_labels = km_final.fit_predict(X_scaled)
    final_sil = _safe(silhouette_score(X_scaled, final_labels))
    centroids = km_final.cluster_centers_

    try:
        calinski = _safe(calinski_harabasz_score(X_scaled, final_labels))
    except Exception:
        calinski = None
    try:
        davies = _safe(davies_bouldin_score(X_scaled, final_labels))
    except Exception:
        davies = None

    from scipy.spatial.distance import cdist
    euclidean_matrix = cdist(centroids, centroids, metric="euclidean")
    euclidean_data = {
        "labels": [f"C{i}" for i in range(best_k)],
        "values": [[_safe(euclidean_matrix[i][j]) for j in range(best_k)] for i in range(best_k)],
    }

    unique, counts = np.unique(final_labels, return_counts=True)
    cluster_sizes = [{"cluster": int(u), "size": int(c)} for u, c in zip(unique, counts)]

    work_with_labels = work.copy()
    work_with_labels["_cluster"] = final_labels
    cluster_profiles = []
    for cl in sorted(unique):
        subset = work_with_labels[work_with_labels["_cluster"] == cl]
        profile = {"cluster": int(cl), "size": int(len(subset))}
        for f in valid_features:
            if pd.api.types.is_numeric_dtype(work[f]):
                profile[f] = _safe(subset[f].mean())
            else:
                profile[f] = str(subset[f].mode().iloc[0]) if not subset[f].mode().empty else ""
        cluster_profiles.append(profile)

    f1, f2 = valid_features[0], valid_features[1]
    scatter = {
        "x_col": f1, "y_col": f2,
        "points": [
            {"x": _safe(X.iloc[i][f1]), "y": _safe(X.iloc[i][f2]), "c": int(final_labels[i])}
            for i in range(min(500, len(X)))
        ],
    }

    return {
        "model_type": "clustering", "features": valid_features,
        "best_k": best_k, "auto_k": auto_k, "rationale": rationale,
        "metrics": {
            "silhouette": final_sil,
            "inertia": _safe(km_final.inertia_),
            "calinski_harabasz": calinski,
            "davies_bouldin": davies,
        },
        "classification_metrics": {
            "accuracy": None, "precision": None, "recall": None,
            "f1": None, "auc": None, "ks": None,
        },
        "euclidean": euclidean_data,
        "inertias": inertias, "silhouettes": silhouettes,
        "cluster_sizes": cluster_sizes, "cluster_profiles": cluster_profiles,
        "scatter": scatter, "total_points": len(X),
    }



# ─── CAUSAL INFERENCE FUNCTIONS ───────────────────────────────────────────

def run_causal_analysis(data: dict, method: str, config: dict) -> dict:
    """Main dispatcher for causal inference methods."""
    df = _data_to_df(data)
    if df is None:
        return {"error": "Sem dados"}
    dispatch = {
        "dag":               _run_dag,
        "psm":               _run_psm,
        "mediation":         _run_mediation,
        "synthetic_control": _run_synthetic_control,
        "iv":                _run_iv,
    }
    fn = dispatch.get(method)
    if fn is None:
        return {"error": f"Método '{method}' não reconhecido"}
    try:
        return fn(df, config)
    except Exception as e:
        return {"error": str(e)[:300]}


# ── helpers ──────────────────────────────────────────────────────────────

def _encode_df_cols(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """In-place label-encode categorical columns; return modified copy."""
    out = df.copy()
    for col in cols:
        if col in out.columns and not pd.api.types.is_numeric_dtype(out[col]):
            le = LabelEncoder()
            out[col] = le.fit_transform(out[col].astype(str))
    return out


def _ols_fit(y: np.ndarray, *X_cols):
    """
    OLS: y ~ X_cols.
    Returns (beta, se, r2, residuals).
    beta[0] = intercept, beta[1..] = slopes in order of X_cols.
    """
    n = len(y)
    Xm = np.column_stack([np.ones(n)] + list(X_cols))
    beta = np.linalg.lstsq(Xm, y, rcond=None)[0]
    y_hat = Xm @ beta
    residuals = y - y_hat
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - y.mean())**2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    df_res = max(n - Xm.shape[1], 1)
    mse = ss_res / df_res
    try:
        cov = _safe_inv(Xm.T @ Xm) * mse
        se = np.sqrt(np.abs(np.diag(cov)))
    except Exception:
        se = np.zeros(len(beta))
    return beta, se, r2, residuals


# ── 1. DAG ────────────────────────────────────────────────────────────────

def _run_dag(df: pd.DataFrame, config: dict) -> dict:
    """
    Skeleton of a causal graph via partial-correlation analysis (PC-algorithm step 0).
    Edges = pairs not conditionally independent (Fisher z-test on partial corr).
    """
    variables = [v for v in config.get("variables", []) if v in df.columns]
    alpha = float(config.get("alpha", 0.05))

    if len(variables) < 2:
        return {"error": "Selecione pelo menos 2 variáveis"}

    work = _encode_df_cols(df[variables].dropna(), variables)
    n, k = len(work), len(variables)
    if n < k + 5:
        return {"error": "Dados insuficientes para o número de variáveis selecionadas"}

    Xm = work.values.astype(float)

    # Pearson correlation
    corr = np.corrcoef(Xm.T)

    # Partial correlation via precision matrix
    try:
        prec = _safe_inv(corr)
        pcor = np.zeros((k, k))
        for i in range(k):
            for j in range(k):
                denom = math.sqrt(abs(prec[i, i] * prec[j, j]))
                pcor[i, j] = -prec[i, j] / denom if denom > 1e-12 else 0.0
        np.fill_diagonal(pcor, 1.0)
    except Exception:
        pcor = corr.copy()

    # Fisher z-test on partial correlations
    df_z = max(n - k - 1, 1)
    edges, adjacency = [], np.zeros((k, k))

    for i in range(k):
        for j in range(i + 1, k):
            r = float(np.clip(pcor[i, j], -0.9999, 0.9999))
            z = 0.5 * math.log((1 + r) / (1 - r))
            se_z = 1.0 / math.sqrt(df_z)
            z_stat = z / se_z
            p_val = float(2 * (1 - sp_stats.norm.cdf(abs(z_stat))))

            # Also compute raw Pearson p for additional info
            r_raw = float(np.clip(corr[i, j], -0.9999, 0.9999))
            t_raw = r_raw * math.sqrt((n - 2) / max(1 - r_raw**2, 1e-12))
            p_raw = float(2 * (1 - sp_stats.t.cdf(abs(t_raw), n - 2)))

            sig = p_val < alpha
            if sig:
                adjacency[i, j] = r
                adjacency[j, i] = r

            edges.append({
                "from": variables[i],
                "to": variables[j],
                "pearson_r": _safe(r_raw),
                "pearson_p": _safe(p_raw),
                "partial_r": _safe(r),
                "partial_p": _safe(p_val),
                "significant": sig,
                "direction": "positive" if r > 0 else "negative",
            })

    # Markov blanket per variable
    mb = {
        variables[i]: [variables[j] for j in range(k) if j != i and adjacency[i, j] != 0]
        for i in range(k)
    }

    # Degree centrality
    degree = {variables[i]: int(np.sum(adjacency[i, :] != 0)) for i in range(k)}

    return {
        "method": "dag",
        "variables": variables,
        "n_obs": n,
        "alpha": alpha,
        "corr_matrix": {
            "columns": variables,
            "values": [[_safe(float(corr[i, j])) for j in range(k)] for i in range(k)],
        },
        "partial_corr": {
            "columns": variables,
            "values": [[_safe(float(pcor[i, j])) for j in range(k)] for i in range(k)],
        },
        "edges": sorted(edges, key=lambda e: e["partial_p"]),
        "adjacency": [[_safe(float(adjacency[i, j])) for j in range(k)] for i in range(k)],
        "markov_blankets": mb,
        "degree": degree,
        "n_edges": int(np.sum(adjacency != 0) // 2),
    }


# ── 2. PSM ────────────────────────────────────────────────────────────────

def _run_psm(df: pd.DataFrame, config: dict) -> dict:
    """
    Propensity Score Matching (1:1 nearest-neighbour, with replacement).
    Estimates ATT: Average Treatment Effect on the Treated.
    """
    treatment  = config.get("treatment")
    outcome    = config.get("outcome")
    covariates = config.get("covariates", [])

    for col in ([treatment, outcome] + covariates):
        if not col or col not in df.columns:
            return {"error": f"Coluna '{col}' não encontrada"}

    # Capture original labels before encoding (for display in results)
    _raw = df[[treatment, outcome] + covariates].dropna()
    _orig_treat_vals = sorted(_raw[treatment].astype(str).unique())
    _orig_outcome_cat = not pd.api.types.is_numeric_dtype(_raw[outcome])
    _orig_outcome_map = (
        {i: v for i, v in enumerate(sorted(_raw[outcome].astype(str).unique()))}
        if _orig_outcome_cat else None
    )
    work = _encode_df_cols(_raw.copy(), [treatment, outcome] + covariates)
    n = len(work)
    if n < 20:
        return {"error": "Dados insuficientes (mínimo 20 registros)"}

    # Binarize treatment
    t_unique = sorted(work[treatment].unique())
    if len(t_unique) != 2:
        return {"error": f"Tratamento deve ser binário. Valores encontrados: {t_unique[:5]}"}
    work["_T"] = (work[treatment] == t_unique[1]).astype(int)

    n_treated = int(work["_T"].sum())
    n_control = int((work["_T"] == 0).sum())
    if n_treated < 5 or n_control < 5:
        return {"error": "Grupos insuficientes (mínimo 5 unidades por grupo)"}

    X_cov = work[covariates].values
    T_vec = work["_T"].values

    # Propensity score
    ps_model = LogisticRegression(max_iter=2000, random_state=42, solver="lbfgs")
    ps_model.fit(X_cov, T_vec)
    ps = ps_model.predict_proba(X_cov)[:, 1]
    work["_ps"] = ps

    # 1:1 NN matching (treated → nearest control, with replacement)
    ctrl_idx = work.index[work["_T"] == 0].tolist()
    trt_idx  = work.index[work["_T"] == 1].tolist()
    matched_t, matched_c = [], []
    for ti in trt_idx:
        ps_t = work.loc[ti, "_ps"]
        best = min(ctrl_idx, key=lambda ci: abs(work.loc[ci, "_ps"] - ps_t))
        matched_t.append(ti)
        matched_c.append(best)

    yt = work.loc[matched_t, outcome].values.astype(float)
    yc = work.loc[matched_c, outcome].values.astype(float)
    att = float(np.mean(yt - yc))

    t_stat, p_val = sp_stats.ttest_rel(yt, yc)
    ci = sp_stats.t.interval(0.95, df=len(yt)-1, loc=np.mean(yt-yc),
                              scale=sp_stats.sem(yt-yc))

    # Covariate balance (SMD)
    balance = []
    for cov in covariates:
        tv = work.loc[work["_T"]==1, cov].values.astype(float)
        cv = work.loc[work["_T"]==0, cov].values.astype(float)
        pooled = math.sqrt((np.var(tv) + np.var(cv)) / 2 + 1e-12)
        smd_before = (np.mean(tv) - np.mean(cv)) / pooled

        tm = work.loc[matched_t, cov].values.astype(float)
        cm = work.loc[matched_c, cov].values.astype(float)
        pooled_m = math.sqrt((np.var(tm) + np.var(cm)) / 2 + 1e-12)
        smd_after = (np.mean(tm) - np.mean(cm)) / pooled_m

        balance.append({
            "covariate": cov,
            "mean_t_before": _safe(np.mean(tv)), "mean_c_before": _safe(np.mean(cv)),
            "smd_before": _safe(smd_before),
            "mean_t_after": _safe(np.mean(tm)), "mean_c_after": _safe(np.mean(cm)),
            "smd_after": _safe(smd_after),
            "balanced": bool(abs(smd_after) < 0.1),
        })

    ps_treated = [_safe(v) for v in work.loc[work["_T"]==1, "_ps"].tolist()[:300]]
    ps_control = [_safe(v) for v in work.loc[work["_T"]==0, "_ps"].tolist()[:300]]

    return {
        "method": "psm",
        "treatment": treatment, "outcome": outcome, "covariates": covariates,
        "n_obs": n, "n_treated": n_treated, "n_control": n_control,
        "n_matched_pairs": len(matched_t),
        "att": _safe(att),
        "att_pct": _safe(att / (abs(np.mean(yc)) + 1e-10) * 100),
        "ci_lower": _safe(ci[0]), "ci_upper": _safe(ci[1]),
        "t_stat": _safe(float(t_stat)), "p_value": _safe(float(p_val)),
        "significant": bool(p_val < 0.05),
        "mean_treated": _safe(np.mean(yt)), "mean_control": _safe(np.mean(yc)),
        "balance": balance,
        "ps_treated": ps_treated, "ps_control": ps_control,
        "label_0": _orig_treat_vals[0] if len(_orig_treat_vals) > 0 else str(t_unique[0]), "label_1": _orig_treat_vals[1] if len(_orig_treat_vals) > 1 else str(t_unique[1]),
    }


# ── 3. Mediation ─────────────────────────────────────────────────────────

def _run_mediation(df: pd.DataFrame, config: dict) -> dict:
    """
    Baron-Kenny mediation analysis with Sobel test + bootstrap CI (n_boot=500).
    """
    exposure   = config.get("exposure")
    mediator   = config.get("mediator")
    outcome    = config.get("outcome")
    covariates = config.get("covariates", [])
    n_boot     = int(config.get("n_bootstrap", 500))

    for col in ([exposure, mediator, outcome] + covariates):
        if not col or col not in df.columns:
            return {"error": f"Coluna '{col}' não encontrada"}

    work = _encode_df_cols(df[[exposure, mediator, outcome] + covariates].dropna(),
                           [exposure, mediator, outcome] + covariates)
    n = len(work)
    if n < 20:
        return {"error": "Dados insuficientes (mínimo 20 registros)"}

    X = work[exposure].values.astype(float)
    M = work[mediator].values.astype(float)
    Y = work[outcome].values.astype(float)
    Ws = [work[c].values.astype(float) for c in covariates]

    def fit(y, *preds):
        return _ols_fit(y, *preds)

    # Step 1: X → Y  (total effect c)
    b_c, se_c, r2_c, _ = fit(Y, X, *Ws)
    c_val, se_c_val = float(b_c[1]), float(se_c[1])

    # Step 2: X → M  (a path)
    b_a, se_a, r2_a, _ = fit(M, X, *Ws)
    a_val, se_a_val = float(b_a[1]), float(se_a[1])

    # Step 3: X + M → Y  (direct effect c', b path)
    b_d, se_d, r2_d, _ = fit(Y, X, M, *Ws)
    c_prime_val, se_cp_val = float(b_d[1]), float(se_d[1])
    b_val,       se_b_val  = float(b_d[2]), float(se_d[2])

    indirect = a_val * b_val

    # Sobel test
    se_sobel = math.sqrt(a_val**2 * se_b_val**2 + b_val**2 * se_a_val**2 + 1e-20)
    z_sobel  = indirect / se_sobel
    p_sobel  = float(2 * (1 - sp_stats.norm.cdf(abs(z_sobel))))

    # Bootstrap CI for indirect effect
    rng = np.random.default_rng(42)
    boot = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        Xi, Mi, Yi = X[idx], M[idx], Y[idx]
        Wsi = [w[idx] for w in Ws]
        ba, *_ = fit(Mi, Xi, *Wsi)
        bd, *_ = fit(Yi, Xi, Mi, *Wsi)
        boot.append(float(ba[1]) * float(bd[2]))
    boot = np.array(boot)
    ci_lo, ci_hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))

    prop_med = _safe(indirect / c_val) if abs(c_val) > 1e-10 else None

    df_res = max(n - 3 - len(covariates), 1)

    def _t_p(coef, se):
        t = coef / (se + 1e-20)
        p = float(2 * (1 - sp_stats.t.cdf(abs(t), df_res)))
        return _safe(t), _safe(p)

    t_c,  p_c  = _t_p(c_val,     se_c_val)
    t_a,  p_a  = _t_p(a_val,     se_a_val)
    t_b,  p_b  = _t_p(b_val,     se_b_val)
    t_cp, p_cp = _t_p(c_prime_val, se_cp_val)

    return {
        "method": "mediation",
        "exposure": exposure, "mediator": mediator, "outcome": outcome,
        "n_obs": n,
        "total_effect": _safe(c_val),
        "direct_effect": _safe(c_prime_val),
        "indirect_effect": _safe(indirect),
        "a_path": _safe(a_val),
        "b_path": _safe(b_val),
        "proportion_mediated": prop_med,
        "sobel_z": _safe(z_sobel), "sobel_p": _safe(p_sobel),
        "boot_ci_lower": _safe(ci_lo), "boot_ci_upper": _safe(ci_hi),
        "boot_significant": bool(ci_lo > 0 or ci_hi < 0),
        "r2_total": _safe(r2_c), "r2_direct": _safe(r2_d), "r2_a_path": _safe(r2_a),
        "paths": [
            {"name": "Efeito Total (c)",       "value": _safe(c_val),      "se": _safe(se_c_val),  "t": t_c,  "p": p_c,  "sig": bool(float(p_c  or 1) < 0.05)},
            {"name": "Caminho a  (X → M)",     "value": _safe(a_val),      "se": _safe(se_a_val),  "t": t_a,  "p": p_a,  "sig": bool(float(p_a  or 1) < 0.05)},
            {"name": "Caminho b  (M → Y | X)", "value": _safe(b_val),      "se": _safe(se_b_val),  "t": t_b,  "p": p_b,  "sig": bool(float(p_b  or 1) < 0.05)},
            {"name": "Efeito Direto (c')",     "value": _safe(c_prime_val),"se": _safe(se_cp_val), "t": t_cp, "p": p_cp, "sig": bool(float(p_cp or 1) < 0.05)},
            {"name": "Efeito Indireto (a×b)",  "value": _safe(indirect),   "se": _safe(se_sobel),  "t": _safe(z_sobel), "p": _safe(p_sobel), "sig": bool(p_sobel < 0.05)},
        ],
        "boot_distribution": [_safe(v) for v in boot[:300].tolist()],
    }


# ── 4. Synthetic Control ──────────────────────────────────────────────────

def _run_synthetic_control(df: pd.DataFrame, config: dict) -> dict:
    """
    Synthetic Control: find optimal donor weights so pre-treatment synthetic
    ≈ treated, then estimate ATT in post-treatment period.
    """
    unit_col      = config.get("unit_col")
    time_col      = config.get("time_col")
    outcome_col   = config.get("outcome_col")
    treated_unit  = config.get("treated_unit")
    treatment_time = str(config.get("treatment_time", ""))

    for col in ([unit_col, time_col, outcome_col]):
        if not col or col not in df.columns:
            return {"error": f"Coluna '{col}' não encontrada"}
    if not treated_unit or not treatment_time:
        return {"error": "Especifique a unidade tratada e o período de tratamento"}

    work = df[[unit_col, time_col, outcome_col]].dropna().copy()
    work[time_col] = work[time_col].astype(str)
    treatment_time = str(treatment_time)

    # Label-encode outcome_col if categorical
    outcome_encoding_map = None
    if not pd.api.types.is_numeric_dtype(work[outcome_col]):
        _le_out = LabelEncoder()
        work[outcome_col] = _le_out.fit_transform(work[outcome_col].astype(str))
        outcome_encoding_map = {str(i): str(c) for i, c in enumerate(_le_out.classes_)}

    try:
        pivot = work.pivot_table(
            index=time_col, columns=unit_col, values=outcome_col, aggfunc="mean"
        )
    except Exception as e:
        return {"error": f"Erro ao organizar dados em painel: {str(e)[:120]}"}

    pivot.columns = [str(c) for c in pivot.columns]
    pivot.index   = [str(t) for t in pivot.index]
    treated_unit  = str(treated_unit)

    if treated_unit not in pivot.columns:
        return {"error": f"Unidade tratada '{treated_unit}' não encontrada. Disponíveis: {list(pivot.columns)[:10]}"}
    if treatment_time not in pivot.index:
        return {"error": f"Período '{treatment_time}' não encontrado. Disponíveis: {sorted(pivot.index)[:10]}"}

    donors = [c for c in pivot.columns if c != treated_unit]
    if len(donors) < 2:
        return {"error": "Pool de controle insuficiente (mínimo 2 unidades)"}

    all_times  = sorted(pivot.index)
    pre_times  = [t for t in all_times if t <  treatment_time]
    post_times = [t for t in all_times if t >= treatment_time]

    if len(pre_times) < 2:
        return {"error": "Período pré-tratamento insuficiente (mínimo 2 períodos)"}

    Ytp  = pivot.loc[pre_times,  treated_unit].ffill().bfill().values.astype(float)
    Ydp  = pivot.loc[pre_times,  donors       ].ffill().bfill().values.astype(float)
    Yt_all = pivot.loc[all_times, treated_unit].ffill().bfill().values.astype(float)
    Yd_all = pivot.loc[all_times, donors       ].ffill().bfill().values.astype(float)

    nd = len(donors)
    from scipy.optimize import minimize as _minimize
    def obj(w): return float(np.sum((Ytp - Ydp @ w)**2))
    res = _minimize(obj, np.full(nd, 1/nd), method="SLSQP",
                    bounds=[(0, 1)]*nd,
                    constraints={"type":"eq","fun": lambda w: w.sum()-1},
                    options={"maxiter":2000, "ftol":1e-12})
    weights = res.x

    Ys_all  = Yd_all @ weights
    pre_pos  = [i for i, t in enumerate(all_times) if t <  treatment_time]
    post_pos = [i for i, t in enumerate(all_times) if t >= treatment_time]

    rmse_pre = float(np.sqrt(np.mean((Yt_all[pre_pos] - Ys_all[pre_pos])**2)))
    att_avg  = float(np.mean(Yt_all[post_pos] - Ys_all[post_pos])) if post_pos else None
    att_pct  = float(att_avg / (abs(np.mean(Ys_all[post_pos])) + 1e-10) * 100) if att_avg is not None else None

    series = [
        {
            "time": t,
            "actual":    _safe(float(Yt_all[i])),
            "synthetic": _safe(float(Ys_all[i])),
            "gap":       _safe(float(Yt_all[i]) - float(Ys_all[i])),
            "post":      t >= treatment_time,
        }
        for i, t in enumerate(all_times)
    ]

    donor_weights = sorted(
        [{"unit": donors[i], "weight": _safe(float(weights[i]))} for i in range(nd)],
        key=lambda x: -(x["weight"] or 0),
    )

    return {
        "method": "synthetic_control",
        "treated_unit": treated_unit,
        "treatment_time": treatment_time,
        "n_pre": len(pre_times), "n_post": len(post_times),
        "n_donors": nd,
        "att_avg": _safe(att_avg),
        "att_pct": _safe(att_pct),
        "rmse_pre": _safe(rmse_pre),
        "optimization_success": bool(res.success),
        "donor_weights": donor_weights,
        "series": series,
    }


# ── 5. IV / Natural Experiment ────────────────────────────────────────────

def _run_iv(df: pd.DataFrame, config: dict) -> dict:
    """
    Two-Stage Least Squares (2SLS).
    Estimates LATE (Local Average Treatment Effect) using Z as instrument for D.
    """
    instrument = config.get("instrument")
    treatment  = config.get("treatment")
    outcome    = config.get("outcome")
    covariates = config.get("covariates", [])

    for col in ([instrument, treatment, outcome] + covariates):
        if not col or col not in df.columns:
            return {"error": f"Coluna '{col}' não encontrada"}

    work = _encode_df_cols(
        df[[instrument, treatment, outcome] + covariates].dropna(),
        [instrument, treatment, outcome] + covariates,
    )
    n = len(work)
    if n < 20:
        return {"error": "Dados insuficientes (mínimo 20 registros)"}

    Z = work[instrument].values.astype(float)
    D = work[treatment].values.astype(float)
    Y = work[outcome].values.astype(float)
    Ws = [work[c].values.astype(float) for c in covariates]

    # First stage: D ~ Z + W
    b1, se1, r2_first, _ = _ols_fit(D, Z, *Ws)
    D_hat = np.column_stack([np.ones(n), Z] + Ws) @ b1

    # First-stage F-statistic (for instrument relevance)
    k1 = 2 + len(Ws)
    ss_tot_d = np.sum((D - D.mean())**2)
    ss_res_d = np.sum((D - D_hat)**2)
    df1, df2 = 1, max(n - k1, 1)
    ms_expl  = (ss_tot_d - ss_res_d) / df1
    ms_res1  = ss_res_d / max(n - k1, 1)
    f_stat   = float(ms_expl / (ms_res1 + 1e-20))
    f_pval   = float(1 - sp_stats.f.cdf(f_stat, df1, df2))
    strength = "forte (≥10)" if f_stat >= 10 else ("moderado (5–10)" if f_stat >= 5 else "fraco (<5)")

    # Second stage: Y ~ D_hat + W
    b2, se2, r2_second, resid2 = _ols_fit(Y, D_hat, *Ws)
    late    = float(b2[1])
    se_late = float(se2[1])
    df_2nd  = max(n - 2 - len(Ws), 1)
    t_late  = late / (se_late + 1e-20)
    p_late  = float(2 * (1 - sp_stats.t.cdf(abs(t_late), df_2nd)))
    ci_late = sp_stats.t.interval(0.95, df=df_2nd, loc=late, scale=se_late)

    # OLS (naive, endogenous) for comparison
    b_ols, se_ols, _, _ = _ols_fit(Y, D, *Ws)
    ols_est = float(b_ols[1])

    # Reduced form: Y ~ Z + W
    b_rf, _, r2_rf, _ = _ols_fit(Y, Z, *Ws)
    rf_est = float(b_rf[1])

    # Hausman test (simplified: compare OLS vs IV)
    hausman_diff = late - ols_est
    # Variance of difference (approx)
    var_diff = max(se_late**2 - se_ols[1]**2, 1e-20)
    hausman_chi2 = float(hausman_diff**2 / var_diff)
    hausman_p    = float(1 - sp_stats.chi2.cdf(hausman_chi2, 1))

    corr_zi = float(np.corrcoef(Z, D)[0, 1])
    corr_zy = float(np.corrcoef(Z, Y)[0, 1])

    return {
        "method": "iv",
        "instrument": instrument, "treatment": treatment, "outcome": outcome,
        "n_obs": n,
        # First stage
        "first_stage_f": _safe(f_stat),
        "first_stage_f_pval": _safe(f_pval),
        "first_stage_r2": _safe(r2_first),
        "instrument_strength": strength,
        # 2SLS (LATE)
        "late": _safe(late),
        "se_late": _safe(se_late),
        "t_late": _safe(t_late),
        "p_late": _safe(p_late),
        "ci_late_lower": _safe(float(ci_late[0])),
        "ci_late_upper": _safe(float(ci_late[1])),
        "late_significant": bool(p_late < 0.05),
        # OLS comparison
        "ols_estimate": _safe(ols_est),
        "ols_se": _safe(float(se_ols[1])),
        # Reduced form
        "reduced_form": _safe(rf_est),
        # Hausman
        "hausman_chi2": _safe(hausman_chi2),
        "hausman_p": _safe(hausman_p),
        "endogeneity_detected": bool(hausman_p < 0.1),
        # Correlations
        "corr_instrument_treatment": _safe(corr_zi),
        "corr_instrument_outcome": _safe(corr_zy),
    }


# ---------------------------------------------------------------------------
# HTML Page Generator
# ---------------------------------------------------------------------------

def generate_analytics_html(data: dict) -> str:
    df = _data_to_df(data)
    if df is None:
        return _empty_html()

    desc = compute_descriptive(data)
    data_json = json.dumps(data, default=str)
    desc_json = json.dumps(desc, default=str)
    numeric_cols = desc["numeric_cols"]
    categorical_cols = desc["categorical_cols"]
    all_cols = numeric_cols + categorical_cols

    cols_json = json.dumps(all_cols)
    num_cols_json = json.dumps(numeric_cols)
    cat_cols_json = json.dumps(categorical_cols)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fale com Seus Dados — Análise Avançada</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ background:#0a0c10; color:#c9d1d9; font-family:'Space Grotesk',sans-serif; }}
        ::-webkit-scrollbar {{ width:6px; height:6px; }}
        ::-webkit-scrollbar-track {{ background:transparent; }}
        ::-webkit-scrollbar-thumb {{ background:#30363d; border-radius:3px; }}

        .aa-header {{ background:#0d1117; border-bottom:1px solid #30363d; padding:12px 24px; display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:100; }}
        .aa-logo {{ font-family:'JetBrains Mono',monospace; font-size:14px; font-weight:600; }}
        .aa-logo span {{ color:#ff6347; }}
        .aa-tabs {{ display:flex; gap:0; }}
        .aa-tab {{ padding:8px 20px; font-size:12px; font-weight:600; cursor:pointer; border:1px solid #30363d; background:#161b22; color:#8b949e; transition:all 0.15s; }}
        .aa-tab:first-child {{ border-radius:8px 0 0 8px; }}
        .aa-tab:last-child {{ border-radius:0 8px 8px 0; }}
        .aa-tab.active {{ background:#ff6347; color:white; border-color:#ff6347; }}
        .aa-tab:hover:not(.active) {{ color:#c9d1d9; background:#21262d; }}

        .aa-panel {{ display:none; padding:24px; max-width:1400px; margin:0 auto; }}
        .aa-panel.active {{ display:block; }}

        .aa-section {{ margin-bottom:28px; }}
        .aa-section-title {{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:600; color:#ff6347; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid #21262d; }}

        .aa-grid {{ display:grid; gap:16px; }}
        .aa-grid-2 {{ grid-template-columns:repeat(auto-fit, minmax(500px, 1fr)); }}
        .aa-grid-3 {{ grid-template-columns:repeat(auto-fit, minmax(340px, 1fr)); }}
        .aa-grid-4 {{ grid-template-columns:repeat(auto-fit, minmax(250px, 1fr)); }}
        .aa-grid-6 {{ grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); }}

        .aa-card {{ background:#0d1117; border:1px solid #30363d; border-radius:12px; padding:16px; }}
        .aa-card-title {{ font-size:11px; font-weight:600; color:#58a6ff; margin-bottom:10px; font-family:'JetBrains Mono',monospace; text-transform:uppercase; letter-spacing:0.05em; }}

        .aa-stat {{ display:flex; justify-content:space-between; padding:4px 0; font-size:12px; border-bottom:1px solid #161b22; }}
        .aa-stat-label {{ color:#8b949e; }}
        .aa-stat-value {{ color:#c9d1d9; font-family:'JetBrains Mono',monospace; font-weight:500; }}

        .aa-chart-wrap {{ height:260px; position:relative; }}

        .aa-freq-table {{ width:100%; border-collapse:collapse; font-size:11px; }}
        .aa-freq-table th {{ text-align:left; padding:6px 8px; background:#161b22; color:#ff6347; font-family:'JetBrains Mono',monospace; font-size:10px; text-transform:uppercase; letter-spacing:0.05em; border-bottom:1px solid #30363d; position:sticky; top:0; }}
        .aa-freq-table td {{ padding:5px 8px; border-bottom:1px solid #161b22; font-family:'JetBrains Mono',monospace; }}
        .aa-freq-table tr:hover td {{ background:#161b22; }}

        .aa-form-group {{ margin-bottom:14px; }}
        .aa-label {{ display:block; font-size:10px; color:#8b949e; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px; font-family:'JetBrains Mono',monospace; }}
        .aa-select {{ width:100%; background:#161b22; border:1px solid #30363d; color:#c9d1d9; padding:8px 12px; border-radius:8px; font-size:12px; font-family:'Space Grotesk',sans-serif; }}
        .aa-select:focus {{ border-color:#ff6347; outline:none; }}
        .aa-checkbox-list {{ max-height:180px; overflow-y:auto; background:#161b22; border:1px solid #30363d; border-radius:8px; padding:8px; }}
        .aa-checkbox-item {{ display:flex; align-items:center; gap:6px; padding:3px 0; font-size:12px; cursor:pointer; }}
        .aa-checkbox-item input {{ accent-color:#ff6347; }}

        .aa-btn {{ padding:8px 20px; border-radius:8px; font-size:12px; font-weight:600; cursor:pointer; border:none; transition:all 0.15s; font-family:'Space Grotesk',sans-serif; }}
        .aa-btn-primary {{ background:#ff6347; color:white; }}
        .aa-btn-primary:hover {{ background:#ff4500; }}
        .aa-btn-primary:disabled {{ opacity:0.5; cursor:not-allowed; }}

        .aa-metric-card {{ background:#161b22; border:1px solid #30363d; border-radius:10px; padding:14px; text-align:center; }}
        .aa-metric-value {{ font-size:22px; font-weight:700; font-family:'JetBrains Mono',monospace; color:#39d353; }}
        .aa-metric-label {{ font-size:10px; color:#8b949e; text-transform:uppercase; letter-spacing:0.05em; margin-top:4px; }}

        .aa-coeff-bar {{ height:18px; border-radius:4px; min-width:2px; transition:width 0.4s; }}

        .aa-coeff-stats-table th {{ white-space:nowrap; }}
        .aa-coeff-stats-table td {{ font-family:'JetBrains Mono',monospace; font-size:11px; }}
        .aa-row-significant {{ background:rgba(57,211,83,0.05) !important; }}
        .aa-row-significant:hover {{ background:rgba(57,211,83,0.1) !important; }}

        .aa-tooltip-trigger {{ position:relative; cursor:help; white-space:nowrap; }}
        .aa-tooltip-icon {{ display:inline-flex; align-items:center; justify-content:center; width:14px; height:14px; border-radius:50%; background:#30363d; color:#8b949e; font-size:9px; font-weight:700; margin-left:3px; vertical-align:middle; }}
        .aa-tooltip-text {{ visibility:hidden; opacity:0; position:absolute; bottom:calc(100% + 8px); left:50%; transform:translateX(-50%); background:#1c2128; border:1px solid #444c56; border-radius:8px; padding:10px 12px; font-size:11px; font-weight:400; color:#c9d1d9; line-height:1.5; width:280px; white-space:normal; z-index:100; pointer-events:none; box-shadow:0 4px 12px rgba(0,0,0,0.4); transition:opacity 0.2s; }}
        .aa-tooltip-text::after {{ content:''; position:absolute; top:100%; left:50%; transform:translateX(-50%); border:6px solid transparent; border-top-color:#444c56; }}
        .aa-tooltip-trigger:hover .aa-tooltip-text {{ visibility:visible; opacity:1; }}

        .aa-badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:10px; font-family:'JetBrains Mono',monospace; font-weight:600; }}
        .aa-badge-num {{ background:rgba(88,166,255,0.15); color:#58a6ff; }}
        .aa-badge-cat {{ background:rgba(255,99,71,0.15); color:#ff6347; }}

        .aa-info {{ font-size:11px; color:#8b949e; background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px 14px; line-height:1.6; }}

        .corr-grid {{ display:inline-grid; gap:1px; background:#21262d; border-radius:8px; overflow:hidden; }}
        .corr-cell {{ width:56px; height:32px; display:flex; align-items:center; justify-content:center; font-size:9px; font-family:'JetBrains Mono',monospace; font-weight:600; }}
        .corr-header {{ background:#161b22; color:#8b949e; font-size:8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; padding:0 2px; }}
    </style>
</head>
<body>

<div class="aa-header">
    <div class="aa-logo">FALE COM <span>SEUS DADOS</span> — Análise Avançada</div>
    <div class="aa-tabs">
        <div class="aa-tab active" onclick="switchTab('descriptive',this)">Descritiva</div>
        <div class="aa-tab" onclick="switchTab('predictive',this)">Preditiva</div>
        <div class="aa-tab" onclick="switchTab('causal',this)">Inferência Causal (beta)</div>
    </div>
    <div style="font-size:11px;color:#8b949e;font-family:'JetBrains Mono',monospace">
        {len(df)} registros · {len(df.columns)} colunas
    </div>
</div>

<!-- ==================== DESCRIPTIVE TAB ==================== -->
<div id="panel-descriptive" class="aa-panel active">

    <div class="aa-section">
        <div class="aa-section-title">Visão Geral do Dataset</div>
        <div class="aa-grid aa-grid-4">
            <div class="aa-metric-card"><div class="aa-metric-value">{len(df)}</div><div class="aa-metric-label">Registros</div></div>
            <div class="aa-metric-card"><div class="aa-metric-value">{len(numeric_cols)}</div><div class="aa-metric-label">Colunas Numéricas</div></div>
            <div class="aa-metric-card"><div class="aa-metric-value">{len(categorical_cols)}</div><div class="aa-metric-label">Colunas Categóricas</div></div>
            <div class="aa-metric-card"><div class="aa-metric-value">{int(df.isna().sum().sum())}</div><div class="aa-metric-label">Valores Nulos</div></div>
        </div>
    </div>

    <div class="aa-section" id="sectionNumericStats"></div>
    <div class="aa-section" id="sectionHistograms"></div>
    <div class="aa-section" id="sectionCorrelation"></div>
    <div class="aa-section" id="sectionScatter"></div>
    <div class="aa-section" id="sectionFrequency"></div>

</div>

<!-- ==================== PREDICTIVE TAB ==================== -->
<div id="panel-predictive" class="aa-panel">
    <div class="aa-grid" style="grid-template-columns:360px 1fr;gap:20px;">

        <div class="aa-card" style="position:sticky;top:70px;align-self:start;">
            <div class="aa-card-title">Configuração do Modelo</div>

            <div class="aa-form-group">
                <label class="aa-label">Motor</label>
                <div style="display:flex;gap:8px;margin-bottom:12px;">
                    <button id="engineTraditional" onclick="setEngine('traditional')"
                        style="flex:1;padding:8px;font-size:11px;font-weight:600;border-radius:8px;border:1px solid #30363d;background:#161b22;color:#8b949e;cursor:pointer;transition:all 0.15s;"
                        onmouseover="if(!this.classList.contains('engine-active'))this.style.color='#c9d1d9'"
                        onmouseout="if(!this.classList.contains('engine-active'))this.style.color='#8b949e'">
                        ⚙ Tradicional
                    </button>
                    <button id="engineAutoML" onclick="setEngine('automl')"
                        style="flex:1;padding:8px;font-size:11px;font-weight:600;border-radius:8px;border:1px solid #30363d;background:#161b22;color:#8b949e;cursor:pointer;transition:all 0.15s;"
                        onmouseover="if(!this.classList.contains('engine-active'))this.style.color='#c9d1d9'"
                        onmouseout="if(!this.classList.contains('engine-active'))this.style.color='#8b949e'">
                        ⚡ AutoML
                    </button>
                </div>
            </div>

            <!-- Traditional mode -->
            <div id="modoTradicionalFields">
            <div class="aa-form-group">
                <label class="aa-label">Tipo de Modelo</label>
                <select id="predModelType" class="aa-select" onchange="updatePredUI()">
                    <option value="linear">Regressão Linear</option>
                    <option value="logistic">Regressão Logística</option>
                    <option value="clustering">Clusterização (K-Means)</option>
                    <option value="pca">PCA</option>                
                </select>
            </div>
            </div>

            <!-- AutoML mode -->
            <div id="modoAutoMLFields" style="display:none;">
                <div class="aa-form-group">
                    <label class="aa-label">Tipo de Tarefa</label>
                    <select id="automlTaskType" class="aa-select">
                        <option value="auto">Automático (detectar pelo alvo)</option>
                        <option value="regression">Regressão (prever valor numérico)</option>
                        <option value="classification">Classificação (prever categoria)</option>
                    </select>
                </div>
                <div class="aa-form-group">
                    <label class="aa-label">Limite de Tempo</label>
                    <select id="automlTimeLimit" class="aa-select">
                    <option value="30">30 seg (rápido)</option>
                    <option value="60" selected>60 seg (padrão)</option>
                    <option value="120">2 min</option>
                    <option value="300">5 min (qualidade)</option>
                </select>
            </div>
            <div class="aa-form-group">
                <label class="aa-label">Preset de Qualidade</label>
                <select id="automlPreset" class="aa-select">
                    <option value="medium_quality" selected>Médio (padrão)</option>
                    <option value="good_quality">Bom</option>
                    <option value="high_quality">Alto</option>
                    <option value="best_quality">Melhor (mais lento)</option>
                </select>
            </div>
            <div class="aa-info" style="margin-bottom:8px;font-size:10px;">
                AutoGluon treina múltiplos modelos automaticamente (Random Forest, Extra Trees, ensemble) e seleciona o melhor. Regressão e classificação são detectadas automaticamente pelo tipo da variável alvo.
            </div>
            </div>

            <div class="aa-info" id="predModelInfo" style="margin-bottom:14px;display:block;">
                Regressão Linear: prevê um valor numérico contínuo a partir das features selecionadas.
            </div>

            <div class="aa-form-group" id="predTargetGroup">
                <label class="aa-label">Variável Alvo (Y)</label>
                <select id="predTarget" class="aa-select">
                    {"".join(f'<option value="{c}">{c}</option>' for c in all_cols)}
                </select>
            </div>

            <div class="aa-form-group" id="predClustersGroup" style="display:none;">
                <label class="aa-label">Quantidade de Clusters (0 = automático)</label>
                <input id="predNClusters" type="number" min="0" max="20" value="0"
                       class="aa-select" style="font-family:'JetBrains Mono',monospace;">
            </div>

            <div class="aa-form-group">
                <label class="aa-label">Features (X)</label>
                <div class="aa-checkbox-list" id="predFeatures">
                    {"".join(f'<label class="aa-checkbox-item"><input type="checkbox" value="{c}"><span>{c}</span> <span class="aa-badge {"aa-badge-num" if c in numeric_cols else "aa-badge-cat"}">{"num" if c in numeric_cols else "cat"}</span></label>' for c in all_cols)}
                </div>
            </div>

            <button class="aa-btn aa-btn-primary" style="width:100%" onclick="runPrediction()" id="predRunBtn">Executar Modelo</button>
            <div id="predStatus" style="margin-top:8px;font-size:11px;text-align:center;"></div>
        </div>

        <div id="predResult">
            <div class="aa-card" style="text-align:center;padding:40px;">
                <div style="color:#8b949e;font-size:13px;">Configure o modelo e clique em "Executar Modelo" para ver os resultados.</div>
            </div>
        </div>
    </div>
</div>

<script>
const DATA = {data_json};
const DESC = {desc_json};
const NUMERIC_COLS = {num_cols_json};
const CAT_COLS = {cat_cols_json};
const ALL_COLS = {cols_json};

Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#21262d';
Chart.defaults.font.family = "'Space Grotesk', sans-serif";

function switchTab(tab, el) {{
    document.querySelectorAll('.aa-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.aa-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('panel-' + tab).classList.add('active');
    el.classList.add('active');
}}

// ============================
// Render Descriptive
// ============================
function renderNumericStats() {{
    const section = document.getElementById('sectionNumericStats');
    if (!DESC.numeric_stats || DESC.numeric_stats.length === 0) {{ section.innerHTML = ''; return; }}
    let html = '<div class="aa-section-title">Estatísticas Numéricas</div><div class="aa-grid aa-grid-3">';
    DESC.numeric_stats.forEach(s => {{
        html += `<div class="aa-card">
            <div class="aa-card-title">${{s.column}}</div>
            <div class="aa-stat"><span class="aa-stat-label">Média</span><span class="aa-stat-value">${{fmt(s.mean)}}</span></div>
            <div class="aa-stat"><span class="aa-stat-label">Mediana</span><span class="aa-stat-value">${{fmt(s.median)}}</span></div>
            <div class="aa-stat"><span class="aa-stat-label">Moda</span><span class="aa-stat-value">${{fmt(s.mode)}}</span></div>
            <div class="aa-stat"><span class="aa-stat-label">Desvio Padrão</span><span class="aa-stat-value">${{fmt(s.std)}}</span></div>
            <div class="aa-stat"><span class="aa-stat-label">Variância</span><span class="aa-stat-value">${{fmt(s.variance)}}</span></div>
            <div class="aa-stat"><span class="aa-stat-label">Amplitude</span><span class="aa-stat-value">${{fmt(s.range)}}</span></div>
            <div class="aa-stat"><span class="aa-stat-label">IQR (Q3-Q1)</span><span class="aa-stat-value">${{fmt(s.iqr)}}</span></div>
            <div style="margin-top:8px;padding-top:6px;border-top:1px solid #21262d;">
                <div class="aa-stat"><span class="aa-stat-label">Min</span><span class="aa-stat-value">${{fmt(s.min)}}</span></div>
                <div class="aa-stat"><span class="aa-stat-label">Q1 (25%)</span><span class="aa-stat-value">${{fmt(s.q1)}}</span></div>
                <div class="aa-stat"><span class="aa-stat-label">Q2 (50%)</span><span class="aa-stat-value">${{fmt(s.q2)}}</span></div>
                <div class="aa-stat"><span class="aa-stat-label">Q3 (75%)</span><span class="aa-stat-value">${{fmt(s.q3)}}</span></div>
                <div class="aa-stat"><span class="aa-stat-label">Max</span><span class="aa-stat-value">${{fmt(s.max)}}</span></div>
            </div>
            <div style="margin-top:6px;">
                <div class="aa-stat"><span class="aa-stat-label">Assimetria</span><span class="aa-stat-value">${{fmt(s.skewness)}}</span></div>
                <div class="aa-stat"><span class="aa-stat-label">Curtose</span><span class="aa-stat-value">${{fmt(s.kurtosis)}}</span></div>
                <div class="aa-stat"><span class="aa-stat-label">Nulos</span><span class="aa-stat-value">${{s.missing}}</span></div>
            </div>
        </div>`;
    }});
    html += '</div>';
    section.innerHTML = html;
}}

function renderHistograms() {{
    const section = document.getElementById('sectionHistograms');
    const hists = DESC.histograms;
    const cols = Object.keys(hists);
    if (cols.length === 0) {{ section.innerHTML = ''; return; }}
    let html = '<div class="aa-section-title">Histogramas</div><div class="aa-grid aa-grid-2">';
    cols.forEach((col, idx) => {{
        html += `<div class="aa-card"><div class="aa-card-title">${{col}}</div><div class="aa-chart-wrap"><canvas id="hist_${{idx}}"></canvas></div></div>`;
    }});
    html += '</div>';
    section.innerHTML = html;
    cols.forEach((col, idx) => {{
        new Chart(document.getElementById('hist_' + idx), {{
            type: 'bar',
            data: {{ labels: hists[col].labels, datasets: [{{ label: col, data: hists[col].values, backgroundColor: 'rgba(255,99,71,0.4)', borderColor: '#ff6347', borderWidth: 1, borderRadius: 3 }}] }},
            options: {{ responsive:true, maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }}, scales:{{ x:{{ ticks:{{ maxRotation:45, font:{{ size:9 }} }} }}, y:{{ beginAtZero:true }} }} }},
        }});
    }});
}}

function renderCorrelation() {{
    const section = document.getElementById('sectionCorrelation');
    const corr = DESC.correlation;
    if (!corr || !corr.columns || corr.columns.length < 2) {{ section.innerHTML = ''; return; }}

    const cols = corr.columns;
    const vals = corr.values;
    const n = cols.length;

    function corrColor(v) {{
        if (v === null || v === undefined) return '#161b22';
        const abs = Math.abs(v);
        if (v > 0) return `rgba(57, 211, 83, ${{(abs * 0.7 + 0.1).toFixed(2)}})`;
        return `rgba(255, 99, 71, ${{(abs * 0.7 + 0.1).toFixed(2)}})`;
    }}
    function corrText(v) {{
        if (v === null || v === undefined) return '—';
        return v.toFixed(2);
    }}

    let html = '<div class="aa-section-title">Matriz de Correlação (Pearson)</div>';
    html += '<div class="aa-card" style="overflow-x:auto;padding:20px;">';
    html += `<div class="corr-grid" style="grid-template-columns:80px repeat(${{n}}, 56px);">`;

    html += '<div class="corr-cell corr-header"></div>';
    cols.forEach(c => {{ html += `<div class="corr-cell corr-header" title="${{c}}">${{c.length > 7 ? c.slice(0,6) + '…' : c}}</div>`; }});

    for (let i = 0; i < n; i++) {{
        html += `<div class="corr-cell corr-header" title="${{cols[i]}}" style="width:80px;justify-content:flex-end;padding-right:6px;">${{cols[i].length > 10 ? cols[i].slice(0,9) + '…' : cols[i]}}</div>`;
        for (let j = 0; j < n; j++) {{
            const v = vals[i][j];
            const bg = corrColor(v);
            const textColor = Math.abs(v) > 0.5 ? '#fff' : '#c9d1d9';
            html += `<div class="corr-cell" style="background:${{bg}};color:${{textColor}}" title="${{cols[i]}} × ${{cols[j]}}: ${{corrText(v)}}">${{corrText(v)}}</div>`;
        }}
    }}
    html += '</div>';

    html += `<div style="display:flex;align-items:center;gap:12px;margin-top:12px;font-size:10px;color:#8b949e;">
        <span>Legenda:</span>
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:14px;height:14px;border-radius:3px;background:rgba(255,99,71,0.7);"></span> Correlação negativa</span>
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:14px;height:14px;border-radius:3px;background:#161b22;border:1px solid #30363d;"></span> Sem correlação</span>
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:14px;height:14px;border-radius:3px;background:rgba(57,211,83,0.7);"></span> Correlação positiva</span>
    </div>`;
    html += '</div>';
    section.innerHTML = html;
}}

function renderScatter() {{
    const section = document.getElementById('sectionScatter');
    const pairs = DESC.scatter_pairs;
    if (!pairs || pairs.length === 0) {{ section.innerHTML = ''; return; }}
    let html = '<div class="aa-section-title">Diagramas de Dispersão</div><div class="aa-grid aa-grid-2">';
    pairs.forEach((p, idx) => {{
        html += `<div class="aa-card"><div class="aa-card-title">${{p.x_col}} × ${{p.y_col}}</div><div class="aa-chart-wrap"><canvas id="scatter_${{idx}}"></canvas></div></div>`;
    }});
    html += '</div>';
    section.innerHTML = html;
    pairs.forEach((p, idx) => {{
        new Chart(document.getElementById('scatter_' + idx), {{
            type: 'scatter',
            data: {{ datasets: [{{ label: `${{p.x_col}} × ${{p.y_col}}`, data: p.x.map((x, i) => ({{ x, y: p.y[i] }})), backgroundColor: 'rgba(255,99,71,0.5)', borderColor: '#ff6347', pointRadius: 3, pointHoverRadius: 5 }}] }},
            options: {{ responsive:true, maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }}, scales:{{ x:{{ title:{{ display:true, text:p.x_col, color:'#c9d1d9', font:{{ size:11 }} }} }}, y:{{ title:{{ display:true, text:p.y_col, color:'#c9d1d9', font:{{ size:11 }} }} }} }} }},
        }});
    }});
}}

function renderFrequency() {{
    const section = document.getElementById('sectionFrequency');
    const ft = DESC.freq_tables;
    const cols = Object.keys(ft);
    if (cols.length === 0) {{ section.innerHTML = ''; return; }}
    const palette = ['#ff6347','#58a6ff','#39d353','#f0883e','#a371f7','#3fb950','#d2a8ff','#79c0ff','#ffa657','#ff7b72'];
    let html = '<div class="aa-section-title">Tabelas de Frequência + Gráficos</div><div class="aa-grid aa-grid-2">';
    cols.forEach((col, idx) => {{
        const f = ft[col];
        html += `<div class="aa-card">
            <div class="aa-card-title">${{col}} <span style="color:#8b949e;font-weight:400">(${{f.total}} registros)</span></div>
            <div class="aa-chart-wrap" style="height:200px;margin-bottom:12px;"><canvas id="freq_chart_${{idx}}"></canvas></div>
            <div style="max-height:180px;overflow-y:auto;">
                <table class="aa-freq-table"><thead><tr><th>Valor</th><th>Freq.</th><th>%</th></tr></thead>
                <tbody>${{f.labels.map((l, i) => `<tr><td>${{l}}</td><td>${{f.values[i]}}</td><td>${{(f.values[i]/f.total*100).toFixed(1)}}%</td></tr>`).join('')}}</tbody></table>
            </div>
        </div>`;
    }});
    html += '</div>';
    section.innerHTML = html;
    cols.forEach((col, idx) => {{
        const f = ft[col];
        const useBar = f.labels.length > 6;
        new Chart(document.getElementById('freq_chart_' + idx), {{
            type: useBar ? 'bar' : 'doughnut',
            data: {{ labels: f.labels, datasets: [{{ data: f.values, backgroundColor: useBar ? 'rgba(255,99,71,0.4)' : f.labels.map((_, i) => palette[i % palette.length]), borderColor: useBar ? '#ff6347' : '#0d1117', borderWidth: useBar ? 1 : 2, borderRadius: useBar ? 3 : 0 }}] }},
            options: {{ responsive:true, maintainAspectRatio:false, plugins:{{ legend:{{ display:!useBar, position:'right', labels:{{ font:{{ size:9 }} }} }} }}, ...(useBar ? {{ scales:{{ x:{{ ticks:{{ maxRotation:45, font:{{ size:9 }} }} }}, y:{{ beginAtZero:true }} }} }} : {{}}) }},
        }});
    }});
}}

// ============================
// Predictive UI
// ============================
let _predEngine = 'traditional';

function setEngine(engine) {{
    _predEngine = engine;
    const btnT = document.getElementById('engineTraditional');
    const btnA = document.getElementById('engineAutoML');
    const activeStyle = 'flex:1;padding:8px;font-size:11px;font-weight:600;border-radius:8px;cursor:pointer;transition:all 0.15s;';
    if (engine === 'traditional') {{
        btnT.style.cssText = activeStyle + 'border:1px solid rgba(255,99,71,0.5);background:rgba(255,99,71,0.15);color:#ff6347;';
        btnA.style.cssText = activeStyle + 'border:1px solid #30363d;background:#161b22;color:#8b949e;';
    }} else {{
        btnA.style.cssText = activeStyle + 'border:1px solid rgba(57,211,83,0.5);background:rgba(57,211,83,0.12);color:#39d353;';
        btnT.style.cssText = activeStyle + 'border:1px solid #30363d;background:#161b22;color:#8b949e;';
    }}
    updatePredUI();
}}

function updatePredUI() {{
    const mt = document.getElementById('predModelType').value;
    const info = document.getElementById('predModelInfo');
    const targetGroup = document.getElementById('predTargetGroup');
    const clustersGroup = document.getElementById('predClustersGroup');
    const modelTypeGroup = document.getElementById('predModelType').closest('.aa-form-group');

    const automlFields = document.getElementById('modoAutoMLFields');
    const tradFields   = document.getElementById('modoTradicionalFields');
    if (_predEngine === 'automl') {{
        info.innerHTML = '<strong style="color:#39d353;">⚡ AutoML (AutoGluon)</strong> — treina múltiplos modelos em paralelo e seleciona o melhor via validação cruzada. Selecione o tipo de tarefa ou deixe "Automático" para detecção pelo tipo da variável alvo.';
        modelTypeGroup.style.display = 'none';
        targetGroup.style.display = 'block';
        clustersGroup.style.display = 'none';
        if (automlFields) automlFields.style.display = 'block';
        if (tradFields)   tradFields.style.display   = 'none';
        return;
    }}
    modelTypeGroup.style.display = 'block';
    if (automlFields) automlFields.style.display = 'none';
    if (tradFields)   tradFields.style.display   = 'block';
    if (mt === 'linear') {{
        info.textContent = 'Regressão Linear: prevê um valor numérico contínuo. Variáveis categóricas serão codificadas automaticamente (Label Encoding).';
        targetGroup.style.display = 'block';
        clustersGroup.style.display = 'none';
    }} else if (mt === 'logistic') {{
        info.textContent = 'Regressão Logística: classifica em categorias. Métricas: AUC, KS, Precision, Recall, F1, Acurácia + Matriz de Confusão.';
        targetGroup.style.display = 'block';
        clustersGroup.style.display = 'none';
    }} else if (mt === 'pca') {{
        info.textContent = 'PCA (Análise de Componentes Principais): reduz dimensionalidade preservando máxima variância. Sem variável alvo. Mostra eigenvalues, loadings, scree plot e biplot.';
        targetGroup.style.display = 'none';
        clustersGroup.style.display = 'block';
    }} else {{
        info.textContent = 'Clusterização K-Means: agrupa dados similares. Informe a quantidade de clusters ou deixe 0 para detecção automática via Silhouette Score.';
        targetGroup.style.display = 'none';
        clustersGroup.style.display = 'block';
    }}
}}

async function runPrediction() {{
    const modelType = _predEngine === 'automl' ? 'automl' : document.getElementById('predModelType').value;
    const target = document.getElementById('predTarget').value;
    const checkboxes = document.querySelectorAll('#predFeatures input:checked');
    const features = Array.from(checkboxes).map(cb => cb.value).filter(f => f !== target || modelType === 'clustering');

    if (features.length === 0) {{ alert('Selecione pelo menos uma feature.'); return; }}

    const btn = document.getElementById('predRunBtn');
    const status = document.getElementById('predStatus');
    btn.disabled = true;
    status.style.color = '#8b949e';
    status.textContent = modelType === 'automl' ? '⚡ Executando torneio AutoML…' : 'Executando modelo...';

    try {{
        const automlTime = parseInt(document.getElementById('automlTimeLimit')?.value) || 60;
        const automlTaskType = document.getElementById('automlTaskType')?.value || 'auto';
        const body = {{
            query_data: DATA,
            target: modelType === 'clustering' ? '' : target,
            features,
            model_type: modelType,
            n_clusters: modelType === 'clustering' ? parseInt(document.getElementById('predNClusters').value) || 0
                        : modelType === 'automl' ? automlTime : 0,
            task_type: modelType === 'automl' ? automlTaskType : 'auto',
        }};
        const res = await fetch('/api/analytics/predict', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(body),
        }});
        const result = await res.json();
        if (result.error) {{
            status.style.color = '#ff6347';
            status.textContent = result.error;
            btn.disabled = false;
            return;
        }}
        status.textContent = '';
        renderPredictionResult(result);
    }} catch(e) {{
        status.style.color = '#ff6347';
        status.textContent = 'Erro: ' + e.message;
    }}
    btn.disabled = false;
}}

function renderPredictionResult(r) {{
    const container = document.getElementById('predResult');
    let html = '';

    if (r.model_type === 'automl') {{
        html += renderAutoMLResult(r);
    }} else if (r.model_type === 'linear') {{
        html += renderLinearResult(r);
    }} else if (r.model_type === 'logistic') {{
        html += renderLogisticResult(r);
    }} else if (r.model_type === 'pca') {{
        html += renderPCAResult(r);
    }} else if (r.model_type === 'clustering') {{
        html += renderClusteringResult(r);
    }}

    container.innerHTML = html;
    setTimeout(() => renderPredCharts(r), 50);
}}

function renderAutoMLResult(r) {{
    const backendBadge = r.backend === 'autogluon'
        ? '<span style="background:rgba(57,211,83,0.15);color:#39d353;border:1px solid rgba(57,211,83,0.3);border-radius:4px;padding:1px 8px;font-size:10px;margin-left:8px;">AutoGluon</span>'
        : '<span style="background:rgba(88,166,255,0.15);color:#58a6ff;border:1px solid rgba(88,166,255,0.3);border-radius:4px;padding:1px 8px;font-size:10px;margin-left:8px;">sklearn</span>';
    const taskLabels = {{regression: 'Regressão', binary: 'Classificação Binária', multiclass: 'Classificação Multiclasse'}};
    const taskBadge = `<span style="background:#21262d;color:#8b949e;border:1px solid #30363d;border-radius:4px;padding:1px 8px;font-size:10px;margin-left:4px;">${{taskLabels[r.task] || r.task}}</span>`;
    const scoreLabel = r.score_label || 'Score';
    const bestScore  = r.best_score !== null && r.best_score !== undefined ? fmt(r.best_score) : '—';
    const bestStd    = r.best_score_std !== null && r.best_score_std !== undefined ? ` ±${{fmt(r.best_score_std)}}` : '';

    let html = `<div class="aa-section"><div class="aa-section-title">AutoML — ${{r.target}} ${{backendBadge}} ${{taskBadge}}</div>
    <div class="aa-grid aa-grid-4" style="margin-bottom:16px;">
        <div class="aa-metric-card"><div class="aa-metric-value" style="color:#39d353;">${{r.best_model.split(' (')[0].slice(0,22)}}</div><div class="aa-metric-label">Melhor Modelo</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{bestScore}}${{bestStd}}</div><div class="aa-metric-label">${{scoreLabel}} (CV)</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{r.n_models}}</div><div class="aa-metric-label">Modelos testados</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{r.n_obs}}</div><div class="aa-metric-label">Observações</div></div>
    </div></div>`;

    // ── Leaderboard table ────────────────────────────────────────────────
    html += `<div class="aa-section"><div class="aa-section-title">🏆 Leaderboard — Ranking dos Modelos</div>
    <div class="aa-card" style="overflow-x:auto;">
    <table class="aa-freq-table aa-coeff-stats-table">
    <thead><tr><th>#</th><th>Modelo</th><th>${{scoreLabel}} (CV)</th><th>Desvio Padrão</th><th>Tempo (s)</th><th>Status</th></tr></thead>
    <tbody>`;
    (r.leaderboard || []).forEach((row, idx) => {{
        const isBest = idx === 0 && !row.error;
        const scoreColor = isBest ? '#39d353' : (row.error ? '#8b949e' : '#c9d1d9');
        const rowClass = isBest ? 'aa-row-significant' : '';
        const medal = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `${{idx+1}}`;
        const barW = row.score && !row.error ? Math.max(Math.round((row.score / (r.leaderboard[0].score || 1)) * 100), 4) : 0;
        html += `<tr class="${{rowClass}}">
            <td style="text-align:center;font-size:13px;">${{medal}}</td>
            <td style="font-weight:${{isBest?'700':'400'}};color:${{isBest?'#58a6ff':'#c9d1d9'}};">${{row.name}}</td>
            <td>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="width:${{barW}}px;max-width:100px;height:6px;background:${{isBest?'#39d353':'rgba(88,166,255,0.5)'}};border-radius:3px;flex-shrink:0;"></div>
                    <span style="color:${{scoreColor}};font-weight:${{isBest?'700':'400'}}">${{row.error ? '—' : fmtC(row.score)}}</span>
                </div>
            </td>
            <td style="color:#8b949e;">${{row.std !== null && row.std !== undefined && !row.error ? '±' + fmtC(row.std) : '—'}}</td>
            <td style="color:#8b949e;">${{row.time !== null && row.time !== undefined ? row.time.toFixed(2) + 's' : '—'}}</td>
            <td style="font-size:10px;color:${{row.error?'#f0883e':'#39d353'}}">${{row.error ? '✗ ' + row.error.slice(0,40) : '✓ OK'}}</td>
        </tr>`;
    }});
    html += '</tbody></table></div></div>';

    // ── Champion rationale ────────────────────────────────────────────────
    // ── Champion rationale ────────────────────────────────────────────────
    if (r.champion_rationale) {{
        html += `<div class="aa-section"><div class="aa-section-title">Justificativa — Seleção do Modelo Campeão</div>
        <div class="aa-card" style="border-left:3px solid #39d353;padding:14px 16px;">
            <div style="font-size:12px;line-height:1.8;color:#c9d1d9;">${{r.champion_rationale}}</div>
        </div></div>`;
    }}

    // ── Feature Importance ────────────────────────────────────────────────
    if (r.feature_importance && r.feature_importance.length > 0) {{
        const maxImp = Math.max(...r.feature_importance.map(f => f.importance || 0), 0.001);
        html += `<div class="aa-section"><div class="aa-section-title">Importância das Features — ${{r.best_model}}</div>
        <div class="aa-card">`;
        r.feature_importance.forEach(fi => {{
            const pct  = ((fi.importance || 0) / maxImp * 100).toFixed(1);
            const pctLabel = ((fi.importance || 0) * 100).toFixed(1) + '%';
            html += `<div style="display:flex;align-items:center;gap:10px;padding:5px 0;border-bottom:1px solid #1c2128;">
                <div style="width:130px;font-size:11px;font-family:'JetBrains Mono',monospace;color:#58a6ff;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${{fi.feature}}">${{fi.feature}}</div>
                <div style="flex:1;background:#161b22;border-radius:4px;height:14px;overflow:hidden;">
                    <div style="width:${{pct}}%;height:100%;background:linear-gradient(90deg,rgba(57,211,83,0.7),rgba(88,166,255,0.6));border-radius:4px;transition:width 0.4s;"></div>
                </div>
                <div style="width:44px;text-align:right;font-size:11px;font-family:'JetBrains Mono',monospace;color:#c9d1d9;">${{pctLabel}}</div>
            </div>`;
        }});
        html += '</div></div>';
    }}

    // ── Task-specific results ─────────────────────────────────────────────
    if (r.task === 'regression') {{
        html += `<div class="aa-section"><div class="aa-section-title">Métricas do Melhor Modelo (treino completo)</div>
        <div class="aa-grid aa-grid-3" style="margin-bottom:16px;">
            <div class="aa-metric-card"><div class="aa-metric-value">${{r.r2 !== null ? fmt(r.r2) : '—'}}</div><div class="aa-metric-label">R²</div></div>
            <div class="aa-metric-card"><div class="aa-metric-value">${{r.mae !== null ? fmt(r.mae) : '—'}}</div><div class="aa-metric-label">MAE</div></div>
            <div class="aa-metric-card"><div class="aa-metric-value">${{r.rmse !== null ? fmt(r.rmse) : '—'}}</div><div class="aa-metric-label">RMSE</div></div>
        </div></div>`;
        if (r.actual && r.predicted) {{
            html += `<div class="aa-section"><div class="aa-section-title">Real vs Previsto — ${{r.best_model}}</div><div class="aa-card"><div style="height:300px;"><canvas id="predChart1"></canvas></div></div></div>`;
        }}
    }} else if (r.confusion_matrix) {{
        html += `<div class="aa-section"><div class="aa-section-title">Classification Table — ${{r.best_model}}</div>
        <div class="aa-card" style="overflow-x:auto;"><table class="aa-freq-table"><thead><tr><th>Real \\ Pred</th>`;
        (r.class_names || []).forEach(c => html += `<th>${{c}}</th>`);
        html += '<th>% Correct</th></tr></thead><tbody>';
        (r.confusion_matrix || []).forEach((row, i) => {{
            html += `<tr><td style="font-weight:600;color:#58a6ff">${{(r.class_names||[])[i]||i}}</td>`;
            row.forEach((v, j) => {{
                const bg = i===j ? 'rgba(57,211,83,0.15)' : (v>0 ? 'rgba(255,99,71,0.1)' : '');
                html += `<td style="background:${{bg}}">${{v}}</td>`;
            }});
            const ca = (r.class_accuracy||[])[i];
            html += `<td style="color:#39d353;font-weight:600;">${{ca ? ca.pct.toFixed(1)+'%' : '—'}}</td></tr>`;
        }});
        html += `<tr style="border-top:1px solid #30363d;"><td style="font-weight:600;color:#58a6ff;">Overall</td>`;
        (r.class_names||[]).forEach(()=>html+='<td></td>');
        html += `<td style="font-weight:700;color:#39d353;">${{typeof r.overall_accuracy==='number'?(r.overall_accuracy*100).toFixed(1)+'%':'—'}}</td></tr>`;
        html += '</tbody></table></div></div>';
    }}

    return html;
}}

function renderClfMetrics(clf, label) {{
    if (!clf) return '';
    const fmtPct = v => v !== null && v !== undefined ? (v * 100).toFixed(1) + '%' : '—';
    return `<div class="aa-section"><div class="aa-section-title">${{label || 'Métricas Estatísticas'}}</div>
    <div class="aa-grid aa-grid-6" style="margin-bottom:16px;">
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmtPct(clf.accuracy)}}</div><div class="aa-metric-label">Acurácia</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmtPct(clf.precision)}}</div><div class="aa-metric-label">Precision</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmtPct(clf.recall)}}</div><div class="aa-metric-label">Recall</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{clf.f1 !== null && clf.f1 !== undefined ? fmt(clf.f1) : '—'}}</div><div class="aa-metric-label">F1-Score</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{clf.auc !== null && clf.auc !== undefined ? fmt(clf.auc) : '—'}}</div><div class="aa-metric-label">AUC-ROC</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{clf.ks !== null && clf.ks !== undefined ? fmt(clf.ks) : '—'}}</div><div class="aa-metric-label">KS</div></div>
    </div></div>`;
}}

function renderCoeffTable(table, recommendation, modelType) {{
    if (!table || table.length === 0) return '';
    const isLogistic = modelType === 'logistic';
    const hasVIF = !isLogistic && table.some(r => r.vif !== null && r.vif !== undefined);
    const tooltips = {{
        coeff: 'Coeficiente (B): magnitude e direção do efeito da variável sobre o alvo. Positivo = aumenta; Negativo = diminui.',
        se: 'Erro Padrão (S.E.): incerteza da estimativa do coeficiente. Quanto menor, mais precisa a estimativa.',
        wald: isLogistic
            ? 'Wald (χ²): teste de significância — (B / S.E.)². Valores altos indicam que o coeficiente é significativamente diferente de zero.'
            : 'Estatística t: teste de significância — B / S.E. Valores com |t| > 2 geralmente indicam significância.',
        p_value: 'p-valor: probabilidade de observar este efeito por acaso. p < 0.05 = estatisticamente significativo (95% de confiança).',
        exp_b: isLogistic
            ? 'Exp(B) — Odds Ratio: multiplicador da chance. >1 = aumenta a chance; <1 = diminui a chance; =1 = sem efeito.'
            : 'Exp(B): exponencial do coeficiente.',
        lower: isLogistic
            ? 'Limite Inferior do IC 95% para Exp(B). Se o intervalo contém 1, o efeito pode não ser significativo.'
            : 'Limite Inferior do IC 95% para o coeficiente. Se o intervalo contém 0, o efeito pode não ser significativo.',
        upper: isLogistic
            ? 'Limite Superior do IC 95% para Exp(B).'
            : 'Limite Superior do IC 95% para o coeficiente.',
        vif: 'VIF (Variance Inflation Factor): detecta multicolinearidade. VIF > 5 indica correlação alta entre preditores; VIF > 10 é problemático.',
    }};

    const th = (label, key) => `<th><span class="aa-tooltip-trigger">${{label}} <span class="aa-tooltip-icon">?</span><span class="aa-tooltip-text">${{tooltips[key]}}</span></span></th>`;

    let html = `<div class="aa-section"><div class="aa-section-title">Tabela de Coeficientes</div>
    <div class="aa-card" style="overflow-x:auto;">
    <table class="aa-freq-table aa-coeff-stats-table">
    <thead><tr>
        <th>Variável</th>
        ${{th('coeff', 'coeff')}}
        ${{th('std err', 'se')}}
        ${{th(isLogistic ? 'Wald' : 't stat', 'wald')}}
        ${{th('p-value', 'p_value')}}
        ${{isLogistic ? th('exp(b)', 'exp_b') : ''}}
        ${{th('lower', 'lower')}}
        ${{th('upper', 'upper')}}
        ${{hasVIF ? th('vif', 'vif') : ''}}
    </tr></thead>
    <tbody>`;

    table.forEach(row => {{
        const sig = row.significant;
        const rowClass = sig ? 'aa-row-significant' : '';
        const pFmt = row.p_value !== null && row.p_value !== undefined ? (row.p_value < 0.0000000001 ? '< 0.0000000001' : fmtC(row.p_value)) : '—';
        const pColor = sig ? '#39d353' : (row.p_value !== null && row.p_value !== undefined && row.p_value < 0.1 ? '#f0883e' : '#8b949e');
        const nameStyle = row.name === '(Intercepto)' ? 'color:#8b949e;font-style:italic;' : (sig ? 'color:#58a6ff;font-weight:600;' : '');

        html += `<tr class="${{rowClass}}">
            <td style="${{nameStyle}}">${{row.name}} ${{sig ? '<span style="color:#39d353;font-size:10px;">★</span>' : ''}}</td>
            <td>${{fmtC(row.coeff)}}</td>
            <td>${{row.se !== null && row.se !== undefined ? fmtC(row.se) : '—'}}</td>
            <td>${{row.wald !== null && row.wald !== undefined ? fmtC(row.wald) : '—'}}</td>
            <td style="color:${{pColor}};font-weight:${{sig ? '600' : 'normal'}}">${{pFmt}}</td>
            ${{isLogistic ? `<td>${{fmtC(row.exp_b)}}</td>` : ''}}
            <td>${{row.lower !== null && row.lower !== undefined ? fmtC(row.lower) : '—'}}</td>
            <td>${{row.upper !== null && row.upper !== undefined ? fmtC(row.upper) : '—'}}</td>
            ${{hasVIF ? `<td style="color:${{row.vif && row.vif > 5 ? '#f0883e' : '#8b949e'}}">${{row.vif !== null && row.vif !== undefined ? fmtC(row.vif) : ''}}</td>` : ''}}
        </tr>`;
    }});

    html += `</tbody></table>
    <div style="margin-top:8px;font-size:10px;color:#8b949e;">
        ★ = significativo (p &lt; 0.05) &nbsp;|&nbsp; IC = Intervalo de Confiança 95%${{isLogistic ? ' para Exp(B)' : ''}}
    </div></div></div>`;

    if (recommendation) {{
        html += `<div class="aa-section"><div class="aa-section-title">Recomendação de Variáveis</div>
        <div class="aa-card" style="border-left:3px solid #58a6ff;padding:14px 16px;">
            <div style="font-size:12px;line-height:1.7;color:#c9d1d9;">${{recommendation}}</div>
        </div></div>`;
    }}

    return html;
}}

function renderLinearResult(r) {{
    const m = r.metrics;
    const rs = r.regression_stats;
    const an = r.anova;

    let html = `<div class="aa-section"><div class="aa-section-title">Regressão Linear — ${{r.target}}</div>`;

    if (rs) {{
        html += `<div class="aa-grid" style="grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
        <div class="aa-card">
        <div class="aa-card-title">OVERALL FIT</div>
        <table class="aa-freq-table" style="max-width:100%;">
            <tbody>
                <tr><td style="color:#8b949e;">Multiple R</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(rs.multiple_r)}}</td></tr>
                <tr><td style="color:#8b949e;">R Square</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(rs.r_square)}}</td></tr>
                <tr><td style="color:#8b949e;">Adjusted R Square</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(rs.r_square_adj)}}</td></tr>
                <tr><td style="color:#8b949e;">Standard Error</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(rs.std_error)}}</td></tr>
                <tr><td style="color:#8b949e;">Observations</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{rs.observations}}</td></tr>
            </tbody>
        </table></div>
        <div class="aa-card">
        <div class="aa-card-title">&nbsp;</div>
        <table class="aa-freq-table" style="max-width:100%;">
            <tbody>
                <tr><td style="color:#8b949e;">AIC</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{rs.aic !== null ? fmtC(rs.aic) : '—'}}</td></tr>
                <tr><td style="color:#8b949e;">AICc</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{rs.aicc !== null ? fmtC(rs.aicc) : '—'}}</td></tr>
                <tr><td style="color:#8b949e;">SBC (BIC)</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{rs.sbc !== null ? fmtC(rs.sbc) : '—'}}</td></tr>
                ${{r.durbin_watson !== null && r.durbin_watson !== undefined ? `<tr><td style="color:#8b949e;">Durbin-Watson</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(r.durbin_watson)}}</td></tr>` : ''}}
            </tbody>
        </table></div></div>`;
    }}

    if (an) {{
        const pFmt = an.regression.f_significance !== null
            ? (an.regression.f_significance < 0.0000000001 ? '< 0.0000000001' : fmtC(an.regression.f_significance))
            : '—';
        const pColor = an.regression.f_significance !== null && an.regression.f_significance < 0.05 ? '#39d353' : '#8b949e';
        const sig = an.regression.f_significance !== null && an.regression.f_significance < 0.05 ? 'yes' : 'no';
        const sigColor = sig === 'yes' ? '#39d353' : '#8b949e';
        html += `<div class="aa-card" style="margin-bottom:16px;">
        <div class="aa-card-title">ANOVA</div>
        <div style="overflow-x:auto;">
        <table class="aa-freq-table aa-coeff-stats-table">
            <thead><tr>
                <th></th><th>df</th><th>SS</th><th>MS</th><th>F</th><th>p-value</th><th>sig</th>
            </tr></thead>
            <tbody>
                <tr>
                    <td style="font-weight:600;color:#58a6ff;">Regression</td>
                    <td>${{an.regression.df}}</td>
                    <td>${{fmtC(an.regression.ss)}}</td>
                    <td>${{fmtC(an.regression.ms)}}</td>
                    <td style="font-weight:600;">${{fmtC(an.regression.f)}}</td>
                    <td style="color:${{pColor}};font-weight:600;">${{pFmt}}</td>
                    <td style="color:${{sigColor}};font-weight:600;text-align:center;">${{sig}}</td>
                </tr>
                <tr>
                    <td style="font-weight:600;color:#58a6ff;">Residual</td>
                    <td>${{an.residual.df}}</td>
                    <td>${{fmtC(an.residual.ss)}}</td>
                    <td>${{fmtC(an.residual.ms)}}</td>
                    <td></td><td></td><td></td>
                </tr>
                <tr style="border-top:1px solid #30363d;">
                    <td style="font-weight:600;color:#58a6ff;">Total</td>
                    <td>${{an.total.df}}</td>
                    <td>${{fmtC(an.total.ss)}}</td>
                    <td></td><td></td><td></td><td></td>
                </tr>
            </tbody>
        </table></div></div>`;
    }}

    html += `</div>`;
    html += renderCoeffTable(r.coeff_table, r.recommendation, 'linear');

    html += `<div class="aa-section"><div class="aa-section-title">Métricas (100% das observações)</div>
    <div class="aa-grid aa-grid-6" style="margin-bottom:16px;">
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmt(m.mae)}}</div><div class="aa-metric-label">MAE</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmt(m.mse)}}</div><div class="aa-metric-label">MSE</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmt(m.rmse)}}</div><div class="aa-metric-label">RMSE</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{m.mape !== null ? (m.mape * 100).toFixed(1) + '%' : '—'}}</div><div class="aa-metric-label">MAPE</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmt(m.explained_var)}}</div><div class="aa-metric-label">Var. Explicada</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{r.observations}}</div><div class="aa-metric-label">Observações</div></div>
    </div></div>`;

    html += renderClfMetrics(r.classification_metrics, 'Métricas de Classificação (binarizado pela mediana)');

    html += `<div class="aa-section"><div class="aa-section-title">Real vs Previsto</div><div class="aa-card"><div style="height:300px;"><canvas id="predChart1"></canvas></div></div></div>`;

    if (r.residual_output && r.residual_output.length > 0) {{
        html += `<div class="aa-section"><div class="aa-section-title">Saída de Resíduos</div>
        <div class="aa-card" style="overflow-x:auto;max-height:400px;overflow-y:auto;">
        <table class="aa-freq-table aa-coeff-stats-table">
        <thead><tr><th>Obs</th><th>Previsto</th><th>Resíduo</th><th>Resíduo Padrão</th></tr></thead>
        <tbody>`;
        r.residual_output.forEach(row => {{
            const absStd = Math.abs(row.std_residual || 0);
            const outlier = absStd > 2 ? 'color:#f0883e;font-weight:600;' : '';
            html += `<tr>
                <td>${{row.obs}}</td>
                <td>${{fmtC(row.predicted)}}</td>
                <td>${{fmtC(row.residual)}}</td>
                <td style="${{outlier}}">${{fmtC(row.std_residual)}}</td>
            </tr>`;
        }});
        html += `</tbody></table></div></div>`;
    }}

    return html;
}}

function renderLogisticResult(r) {{
    let html = `<div class="aa-section"><div class="aa-section-title">Regressão Logística — ${{r.target}}</div>`;

    const ms = r.model_summary;
    const ot = r.omnibus_test;
    if (ms || ot) {{
        html += `<div class="aa-grid" style="grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">`;

        if (ot && ms) {{
            const pFmt = ot.p_value !== null ? (ot.p_value < 0.0000000001 ? '< 0.0000000001' : fmtC(ot.p_value)) : '—';
            const pColor = ot.p_value !== null && ot.p_value < 0.05 ? '#39d353' : '#8b949e';
            const sig = ot.p_value !== null && ot.p_value < 0.05 ? 'yes' : 'no';
            const sigColor = sig === 'yes' ? '#39d353' : '#8b949e';
            html += `<div class="aa-card">
            <div class="aa-card-title">Significance Testing</div>
            <table class="aa-freq-table" style="max-width:100%;">
                <tbody>
                    <tr><td style="color:#8b949e;">LL0</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(ms.ll0)}}</td></tr>
                    <tr><td style="color:#8b949e;">LL1</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(ms.ll1)}}</td></tr>
                    <tr style="border-top:1px solid #30363d;"><td style="color:#8b949e;">Chi-Sq</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;font-weight:600;">${{fmtC(ot.chi2)}}</td></tr>
                    <tr><td style="color:#8b949e;">df</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{ot.df}}</td></tr>
                    <tr><td style="color:#8b949e;">p-value</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;color:${{pColor}};font-weight:600;">${{pFmt}}</td></tr>
                    <tr><td style="color:#8b949e;">sig</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;color:${{sigColor}};font-weight:600;">${{sig}}</td></tr>
                </tbody>
            </table></div>`;

            html += `<div class="aa-card">
            <div class="aa-card-title">R-Square & Information Criteria</div>
            <table class="aa-freq-table" style="max-width:100%;">
                <tbody>
                    <tr><td style="color:#8b949e;">R-Sq (L) McFadden</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(ms.mcfadden_r2)}}</td></tr>
                    <tr><td style="color:#8b949e;">R-Sq (CS) Cox &amp; Snell</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(ms.cox_snell_r2)}}</td></tr>
                    <tr><td style="color:#8b949e;">R-Sq (N) Nagelkerke</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{fmtC(ms.nagelkerke_r2)}}</td></tr>
                    <tr style="border-top:1px solid #30363d;"><td style="color:#8b949e;">AIC</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{ms.aic !== null && ms.aic !== undefined ? fmtC(ms.aic) : '—'}}</td></tr>
                    <tr><td style="color:#8b949e;">BIC</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{ms.bic !== null && ms.bic !== undefined ? fmtC(ms.bic) : '—'}}</td></tr>
                    <tr><td style="color:#8b949e;">Observations</td><td style="text-align:right;font-family:'JetBrains Mono',monospace;">${{ms.observations}}</td></tr>
                </tbody>
            </table></div>`;
        }}
        html += `</div>`;
    }}

    html += `</div>`;
    html += renderCoeffTable(r.coeff_table, r.recommendation, 'logistic');
    html += renderClfMetrics(r.classification_metrics, 'Métricas Estatísticas (100% das observações)');

    html += `<div class="aa-section"><div class="aa-section-title">Classification Table & Curva ROC</div>
    <div class="aa-grid" style="grid-template-columns:1fr 1fr;gap:16px;">`;

    html += '<div class="aa-card"><div class="aa-card-title">Classification Table</div>';
    if (r.class_names && r.confusion_matrix) {{
        html += `<div style="overflow-x:auto;max-height:400px;overflow-y:auto;"><table class="aa-freq-table"><thead><tr><th style="min-width:80px;">Real (${{r.target}}) \\ Pred</th>`;
        html += `<div class="aa-section"><div class="aa-section-title">Classification Table — ${{r.best_model}}</div>
        <div class="aa-card" style="overflow-x:auto;"><table class="aa-freq-table"><thead><tr><th>Real (${{r.target}}) \\ Pred</th>`;
        (r.class_names || []).forEach(c => html += `<th>${{c}}</th>`);
        html += '<th>% Correct</th></tr></thead><tbody>';
        r.confusion_matrix.forEach((row, i) => {{
            html += `<tr><td style="font-weight:600;color:#58a6ff">${{r.class_names[i]}}</td>`;
            row.forEach((v, j) => {{
                const bg = i === j ? 'rgba(57,211,83,0.15)' : (v > 0 ? 'rgba(255,99,71,0.1)' : '');
                html += `<td style="background:${{bg}}">${{v}}</td>`;
            }});
            const ca = r.class_accuracy ? r.class_accuracy[i] : null;
            const pct = ca ? ca.pct : '—';
            html += `<td style="font-weight:600;color:#39d353;">${{typeof pct === 'number' ? pct.toFixed(1) + '%' : pct}}</td></tr>`;
        }});
        html += `<tr style="border-top:1px solid #30363d;"><td style="font-weight:600;color:#58a6ff;">Overall</td>`;
        r.class_names.forEach(() => html += '<td></td>');
        html += `<td style="font-weight:700;color:#39d353;">${{typeof r.overall_accuracy === 'number' ? r.overall_accuracy.toFixed(1) + '%' : '—'}}</td></tr>`;
        html += '</tbody></table></div>';
    }}
    html += '</div>';

    html += '<div class="aa-card"><div class="aa-card-title">Curva ROC</div>';
    if (r.roc_curve) {{
        html += '<div style="height:280px;"><canvas id="predChart1"></canvas></div>';
    }} else {{
        html += '<div style="padding:40px;text-align:center;color:#8b949e;font-size:12px;">Curva ROC disponível apenas para classificação binária.</div>';
    }}
    html += '</div></div></div>';

    html += `<div class="aa-section"><div class="aa-section-title">Distribuição das Predições</div><div class="aa-card"><div style="height:260px;"><canvas id="predChart2"></canvas></div></div></div>`;

    return html;
}}

function renderClusteringResult(r) {{
    const m = r.metrics;
    let html = `<div class="aa-section"><div class="aa-section-title">Clusterização K-Means — ${{r.best_k}} Clusters ${{r.auto_k ? '(automático)' : '(definido pelo usuário)'}}</div>
    <div class="aa-grid aa-grid-6" style="margin-bottom:16px;">
        <div class="aa-metric-card"><div class="aa-metric-value">${{r.best_k}}</div><div class="aa-metric-label">Clusters (K)</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmt(m.silhouette)}}</div><div class="aa-metric-label">Silhouette</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmt(m.inertia)}}</div><div class="aa-metric-label">Inertia</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmt(m.calinski_harabasz)}}</div><div class="aa-metric-label">Calinski-Harabasz</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{fmt(m.davies_bouldin)}}</div><div class="aa-metric-label">Davies-Bouldin</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{r.total_points}}</div><div class="aa-metric-label">Total Pontos</div></div>
    </div></div>`;

    html += renderClfMetrics(r.classification_metrics, 'Métricas Estatísticas (não aplicável — sem variável alvo)');

    html += '<div class="aa-section"><div class="aa-section-title">Tamanho dos Clusters</div><div class="aa-grid aa-grid-4">';
    const clPalette = ['#ff6347','#58a6ff','#39d353','#f0883e','#a371f7','#3fb950','#d2a8ff','#79c0ff'];
    r.cluster_sizes.forEach(cs => {{
        html += `<div class="aa-metric-card" style="border-left:3px solid ${{clPalette[cs.cluster % clPalette.length]}}"><div class="aa-metric-value">${{cs.size}}</div><div class="aa-metric-label">Cluster ${{cs.cluster}}</div></div>`;
    }});
    html += '</div></div>';

    html += `<div class="aa-section"><div class="aa-section-title">Visualizações</div>
    <div class="aa-grid aa-grid-2">
        <div class="aa-card"><div class="aa-card-title">Dispersão (${{r.scatter.x_col}} × ${{r.scatter.y_col}})</div><div style="height:300px;"><canvas id="predChart1"></canvas></div></div>
        <div class="aa-card"><div class="aa-card-title">Método do Cotovelo (Elbow)</div><div style="height:300px;"><canvas id="predChart2"></canvas></div>
            <div class="aa-info" style="margin-top:10px;">${{r.rationale || ''}}</div>
        </div>
    </div>
    <div class="aa-grid aa-grid-2" style="margin-top:16px;">
        <div class="aa-card"><div class="aa-card-title">Distância Euclidiana entre Centróides</div><div style="height:300px;"><canvas id="predChart3"></canvas></div></div>
        <div class="aa-card"><div class="aa-card-title">Matriz de Distância Euclidiana</div>`;

    if (r.euclidean) {{
        const euc = r.euclidean;
        const n = euc.labels.length;
        html += `<div style="overflow-x:auto;"><div class="corr-grid" style="grid-template-columns:56px repeat(${{n}}, 56px);display:inline-grid;gap:1px;background:#21262d;border-radius:8px;overflow:hidden;">`;
        html += '<div class="corr-cell corr-header"></div>';
        euc.labels.forEach(l => html += `<div class="corr-cell corr-header">${{l}}</div>`);
        const maxDist = Math.max(...euc.values.flat().filter(v => v !== null), 0.01);
        for (let i = 0; i < n; i++) {{
            html += `<div class="corr-cell corr-header" style="width:56px;justify-content:flex-end;padding-right:4px;">${{euc.labels[i]}}</div>`;
            for (let j = 0; j < n; j++) {{
                const v = euc.values[i][j];
                const intensity = i === j ? 0 : (v / maxDist);
                const bg = i === j ? '#161b22' : `rgba(255, 99, 71, ${{(intensity * 0.7 + 0.1).toFixed(2)}})`;
                const tc = intensity > 0.4 ? '#fff' : '#c9d1d9';
                html += `<div class="corr-cell" style="background:${{bg}};color:${{tc}}" title="${{euc.labels[i]}} ↔ ${{euc.labels[j]}}: ${{v !== null ? v.toFixed(3) : '—'}}">${{i === j ? '0' : (v !== null ? v.toFixed(2) : '—')}}</div>`;
            }}
        }}
        html += '</div></div>';
    }}
    html += '</div></div></div>';

    if (r.cluster_profiles && r.cluster_profiles.length > 0) {{
        html += '<div class="aa-section"><div class="aa-section-title">Perfil dos Clusters (Médias)</div>';
        html += '<div class="aa-card" style="overflow-x:auto;"><table class="aa-freq-table"><thead><tr><th>Cluster</th><th>Tamanho</th>';
        r.features.forEach(f => html += `<th>${{f}}</th>`);
        html += '</tr></thead><tbody>';
        r.cluster_profiles.forEach(p => {{
            html += `<tr><td style="font-weight:600;color:${{clPalette[p.cluster % clPalette.length]}}">Cluster ${{p.cluster}}</td><td>${{p.size}}</td>`;
            r.features.forEach(f => html += `<td>${{fmt(p[f])}}</td>`);
            html += '</tr>';
        }});
        html += '</tbody></table></div></div>';
    }}

    return html;
}}

function renderPCAResult(r) {{
    const palette = ['#ff6347','#58a6ff','#39d353','#f0883e','#a371f7','#3fb950','#d2a8ff','#79c0ff','#ffa657','#ff7b72'];
 
    let html = `<div class="aa-section"><div class="aa-section-title">PCA — Análise de Componentes Principais</div>
    <div class="aa-grid aa-grid-4" style="margin-bottom:16px;">
        <div class="aa-metric-card"><div class="aa-metric-value">${{r.total_points}}</div><div class="aa-metric-label">Observações</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{r.features.length}}</div><div class="aa-metric-label">Features Originais</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value" style="color:#39d353">${{r.auto_k}}</div><div class="aa-metric-label">Componentes (≥80% var.)</div></div>
        <div class="aa-metric-card"><div class="aa-metric-value">${{r.kaiser_k}}</div><div class="aa-metric-label">Kaiser (eigenvalue &gt; 1)</div></div>
    </div></div>`;
 
    html += `<div class="aa-section"><div class="aa-section-title">Eigenvalues &amp; Variância Explicada</div>
    <div class="aa-grid" style="grid-template-columns:1fr 1fr;gap:16px;">
    <div class="aa-card" style="overflow-x:auto;">
    <table class="aa-freq-table aa-coeff-stats-table">
    <thead><tr><th>Componente</th><th>Eigenvalue</th><th>Variância (%)</th><th>Acumulada (%)</th></tr></thead>
    <tbody>`;
    (r.eigenvalues || []).forEach((ev, i) => {{
        const rowCls = i < r.auto_k ? 'aa-row-significant' : '';
        html += `<tr class="${{rowCls}}">
            <td style="font-weight:600;color:#58a6ff;">${{ev.component}}</td>
            <td>${{fmtC(ev.eigenvalue)}}</td>
            <td>${{fmtC(ev.explained_pct)}}%</td>
            <td style="font-weight:600;color:${{ev.cumulative_pct >= 80 ? '#39d353' : '#c9d1d9'}}">${{fmtC(ev.cumulative_pct)}}%</td>
        </tr>`;
    }});
    html += `</tbody></table>
    <div style="margin-top:6px;font-size:10px;color:#8b949e;">★ componentes retidos (≥ 80% variância acumulada)</div>
    </div>
    <div class="aa-card"><div class="aa-card-title">Scree Plot + Variância Acumulada</div><div style="height:280px;"><canvas id="predChart1"></canvas></div></div>
    </div></div>`;
 
    if (r.top_contributors && r.top_contributors.length > 0) {{
        html += `<div class="aa-section"><div class="aa-section-title">Principais Contribuições por Componente</div><div class="aa-grid aa-grid-2">`;
        r.top_contributors.slice(0, 6).forEach(tc => {{
            const maxAbs = Math.max(...tc.contributors.map(c => c.abs_loading || 0), 0.01);
            html += `<div class="aa-card"><div class="aa-card-title">${{tc.component}} <span style="color:#8b949e;font-weight:400;">(${{fmtC(tc.explained_pct)}}%)</span></div>`;
            tc.contributors.forEach(c => {{
                const pct = ((c.abs_loading || 0) / maxAbs * 100).toFixed(0);
                const color = (c.loading || 0) > 0 ? '#39d353' : '#ff6347';
                const dir = (c.loading || 0) > 0 ? '+' : '';
                html += `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid #1c2128;">
                    <div style="width:100px;font-size:11px;font-family:'JetBrains Mono',monospace;color:#58a6ff;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${{c.feature}}">${{c.feature}}</div>
                    <div style="flex:1;background:#161b22;border-radius:3px;height:10px;overflow:hidden;">
                        <div style="width:${{pct}}%;height:100%;background:${{color}};border-radius:3px;"></div>
                    </div>
                    <div style="width:50px;text-align:right;font-size:10px;font-family:'JetBrains Mono',monospace;color:${{color}}">${{dir}}${{fmtC(c.loading)}}</div>
                </div>`;
            }});
            html += `</div>`;
        }});
        html += `</div></div>`;
    }}
 
    if (r.loadings && r.loadings.length > 0) {{
        const feats = r.features;
        const maxShow = Math.min(r.loadings.length, 10);
        html += `<div class="aa-section"><div class="aa-section-title">Matriz de Loadings</div>
        <div class="aa-card" style="overflow-x:auto;">
        <table class="aa-freq-table aa-coeff-stats-table">
        <thead><tr><th></th>`;
        feats.forEach(f => html += `<th style="font-size:9px;max-width:70px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${{f}}">${{f.length > 8 ? f.slice(0,7) + '…' : f}}</th>`);
        html += `</tr></thead><tbody>`;
        r.loadings.slice(0, maxShow).forEach(row => {{
            html += `<tr><td style="font-weight:600;color:#58a6ff;">${{row.component}}</td>`;
            feats.forEach(f => {{
                const v = row[f] || 0;
                const abs = Math.abs(v);
                const bg = v > 0 ? `rgba(57,211,83,${{(abs*0.8+0.05).toFixed(2)}})` : `rgba(255,99,71,${{(abs*0.8+0.05).toFixed(2)}})`;
                const tc = abs > 0.4 ? '#fff' : '#c9d1d9';
                html += `<td style="background:${{bg}};color:${{tc}};text-align:center;font-size:10px;">${{fmtC(v)}}</td>`;
            }});
            html += `</tr>`;
        }});
        html += `</tbody></table></div></div>`;
    }}
 
    if (r.scatter) {{
        html += `<div class="aa-section"><div class="aa-section-title">Projeção PC1 × PC2${{r.biplot_vectors ? ' (Biplot)' : ''}}</div>
        <div class="aa-card"><div style="height:380px;"><canvas id="predChart2"></canvas></div></div></div>`;
    }}
 
    return html;
}}
 
function renderPredCharts(r) {{
    if (r.model_type === 'automl' && r.task === 'regression' && r.actual && r.predicted) {{
        const c1 = document.getElementById('predChart1');
        if (c1) {{
            new Chart(c1, {{
                type: 'scatter',
                data: {{ datasets: [
                    {{ label: 'Real vs Previsto', data: r.actual.map((a,i) => ({{x:a,y:r.predicted[i]}})), backgroundColor: 'rgba(57,211,83,0.5)', borderColor: '#39d353', pointRadius: 3 }},
                    {{ label: 'Perfeito', data: [{{x:Math.min(...r.actual),y:Math.min(...r.actual)}},{{x:Math.max(...r.actual),y:Math.max(...r.actual)}}], type:'line', borderColor:'#58a6ff', borderDash:[5,5], pointRadius:0, borderWidth:2 }},
                ] }},
                options: {{ responsive:true, maintainAspectRatio:false, scales:{{ x:{{title:{{display:true,text:'Real',color:'#c9d1d9'}}}}, y:{{title:{{display:true,text:'Previsto',color:'#c9d1d9'}}}} }} }},
            }});
        }}
        return;
    }}
    if (r.model_type === 'linear') {{
        const c1 = document.getElementById('predChart1');
        if (c1) {{
            new Chart(c1, {{
                type: 'scatter',
                data: {{ datasets: [
                    {{ label: 'Real vs Previsto', data: r.actual.map((a, i) => ({{ x: a, y: r.predicted[i] }})), backgroundColor: 'rgba(255,99,71,0.5)', borderColor: '#ff6347', pointRadius: 3 }},
                    {{ label: 'Perfeito', data: [{{ x: Math.min(...r.actual), y: Math.min(...r.actual) }}, {{ x: Math.max(...r.actual), y: Math.max(...r.actual) }}], type: 'line', borderColor: '#39d353', borderDash: [5,5], pointRadius: 0, borderWidth: 2 }},
                ] }},
                options: {{ responsive:true, maintainAspectRatio:false, scales:{{ x:{{ title:{{ display:true, text:'Real', color:'#c9d1d9' }} }}, y:{{ title:{{ display:true, text:'Previsto', color:'#c9d1d9' }} }} }} }},
            }});
        }}

    }} else if (r.model_type === 'logistic') {{
        if (r.roc_curve) {{
            const c1 = document.getElementById('predChart1');
            if (c1) {{
                new Chart(c1, {{
                    type: 'line',
                    data: {{ labels: r.roc_curve.fpr, datasets: [
                        {{ label: `ROC (AUC=${{r.classification_metrics && r.classification_metrics.auc ? r.classification_metrics.auc.toFixed(3) : '—'}})`, data: r.roc_curve.tpr, borderColor: '#ff6347', backgroundColor: 'rgba(255,99,71,0.1)', fill: true, tension: 0.2, pointRadius: 0 }},
                        {{ label: 'Aleatório', data: r.roc_curve.fpr, borderColor: '#30363d', borderDash: [5,5], pointRadius: 0, borderWidth: 1 }},
                    ] }},
                    options: {{ responsive:true, maintainAspectRatio:false, scales:{{ x:{{ title:{{ display:true, text:'FPR (False Positive Rate)', color:'#c9d1d9', font:{{ size:10 }} }}, ticks:{{ callback: v => typeof v==='number' ? v.toFixed(1) : v }} }}, y:{{ title:{{ display:true, text:'TPR (True Positive Rate)', color:'#c9d1d9', font:{{ size:10 }} }}, min:0, max:1 }} }} }},
                }});
            }}
        }}

        const c2 = document.getElementById('predChart2');
        if (c2 && r.confusion_matrix) {{
            const cm = r.confusion_matrix;
            const labels = [];
            const values = [];
            const colors = [];
            r.class_names.forEach((real, i) => {{
                r.class_names.forEach((pred, j) => {{
                    labels.push(`R:${{real}} P:${{pred}}`);
                    values.push(cm[i][j]);
                    colors.push(i === j ? 'rgba(57,211,83,0.6)' : 'rgba(255,99,71,0.5)');
                }});
            }});
            new Chart(c2, {{
                type: 'bar',
                data: {{ labels, datasets: [{{ data: values, backgroundColor: colors, borderWidth: 0, borderRadius: 3 }}] }},
                options: {{ responsive:true, maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }}, scales:{{ x:{{ ticks:{{ font:{{ size:9 }} }} }}, y:{{ beginAtZero:true }} }} }},
            }});
        }}

    }} else if (r.model_type === 'pca') {{
        const c1 = document.getElementById('predChart1');
        if (c1 && r.explained_variance) {{
            const labels = r.explained_variance.map((_, i) => 'PC' + (i + 1));
            new Chart(c1, {{
                type: 'bar',
                data: {{ labels, datasets: [
                    {{ label: 'Variância (%)', data: r.explained_variance, backgroundColor: 'rgba(255,99,71,0.4)', borderColor: '#ff6347', borderWidth: 1, borderRadius: 3, yAxisID: 'y' }},
                    {{ label: 'Acumulada (%)', data: r.cumulative_variance, type: 'line', borderColor: '#39d353', backgroundColor: 'rgba(57,211,83,0.1)', fill: true, tension: 0.3, pointRadius: 4, yAxisID: 'y1' }},
                ] }},
                options: {{ responsive:true, maintainAspectRatio:false, scales: {{
                    y: {{ title: {{ display:true, text:'Variância (%)', color:'#ff6347' }}, position:'left', beginAtZero:true }},
                    y1: {{ title: {{ display:true, text:'Acumulada (%)', color:'#39d353' }}, position:'right', grid: {{ drawOnChartArea:false }}, min:0, max:100 }}
                }} }},
            }});
        }}
        const c2 = document.getElementById('predChart2');
        if (c2 && r.scatter) {{
            const datasets = [{{ label: 'Observações', data: r.scatter.points.map(p => ({{x:p.x, y:p.y}})), backgroundColor: 'rgba(88,166,255,0.35)', borderColor: '#58a6ff', pointRadius: 3 }}];
            if (r.biplot_vectors) {{
                const vp = ['#ff6347','#39d353','#f0883e','#a371f7','#3fb950','#d2a8ff','#79c0ff','#ffa657'];
                const xs = r.scatter.points.map(p => Math.abs(p.x));
                const ys = r.scatter.points.map(p => Math.abs(p.y));
                const scale = Math.max(Math.max(...xs), Math.max(...ys), 1) * 0.8;
                r.biplot_vectors.forEach((v, i) => {{
                    if (Math.sqrt(v.pc1*v.pc1 + v.pc2*v.pc2) < 0.1) return;
                    datasets.push({{ label: v.feature, data: [{{x:0,y:0}}, {{x:v.pc1*scale, y:v.pc2*scale}}], type:'line', borderColor: vp[i%vp.length], borderWidth:2, pointRadius:[0,5], pointStyle:['circle','triangle'], pointBackgroundColor: vp[i%vp.length], showLine:true, fill:false }});
                }});
            }}
            new Chart(c2, {{
                type: 'scatter', data: {{ datasets }},
                options: {{ responsive:true, maintainAspectRatio:false, plugins: {{ legend: {{ labels: {{ color:'#c9d1d9', font:{{size:10}} }}, position:'right' }} }}, scales: {{ x: {{ title: {{ display:true, text:'PC1', color:'#c9d1d9' }} }}, y: {{ title: {{ display:true, text:'PC2', color:'#c9d1d9' }} }} }} }},
            }});
        }}
 
    }} else if (r.model_type === 'clustering') {{
        const clPalette = ['#ff6347','#58a6ff','#39d353','#f0883e','#a371f7','#3fb950','#d2a8ff','#79c0ff'];

        const c1 = document.getElementById('predChart1');
        if (c1 && r.scatter) {{
            const datasets = [];
            for (let k = 0; k < r.best_k; k++) {{
                const pts = r.scatter.points.filter(p => p.c === k).map(p => ({{ x: p.x, y: p.y }}));
                datasets.push({{ label: `Cluster ${{k}}`, data: pts, backgroundColor: clPalette[k % clPalette.length] + '80', borderColor: clPalette[k % clPalette.length], pointRadius: 3, pointHoverRadius: 5 }});
            }}
            new Chart(c1, {{
                type: 'scatter',
                data: {{ datasets }},
                options: {{ responsive:true, maintainAspectRatio:false, scales:{{ x:{{ title:{{ display:true, text:r.scatter.x_col, color:'#c9d1d9' }} }}, y:{{ title:{{ display:true, text:r.scatter.y_col, color:'#c9d1d9' }} }} }} }},
            }});
        }}

        const c2 = document.getElementById('predChart2');
        if (c2 && r.inertias) {{
            new Chart(c2, {{
                type: 'line',
                data: {{
                    labels: r.inertias.map(d => 'K=' + d.k),
                    datasets: [
                        {{ label: 'Inertia', data: r.inertias.map(d => d.inertia), borderColor: '#ff6347', backgroundColor: 'rgba(255,99,71,0.1)', fill: true, tension: 0.3 }},
                        {{ label: 'Silhouette', data: r.silhouettes.map(d => d.silhouette), borderColor: '#39d353', yAxisID: 'y1', tension: 0.3 }},
                    ],
                }},
                options: {{ responsive:true, maintainAspectRatio:false, scales:{{ y:{{ title:{{ display:true, text:'Inertia', color:'#ff6347' }}, position:'left' }}, y1:{{ title:{{ display:true, text:'Silhouette', color:'#39d353' }}, position:'right', grid:{{ drawOnChartArea:false }}, min:0, max:1 }} }} }},
            }});
        }}

        const c3 = document.getElementById('predChart3');
        if (c3 && r.euclidean) {{
            const euc = r.euclidean;
            const labels = [];
            const values = [];
            const colors = [];
            for (let i = 0; i < euc.labels.length; i++) {{
                for (let j = i + 1; j < euc.labels.length; j++) {{
                    labels.push(`${{euc.labels[i]}} ↔ ${{euc.labels[j]}}`);
                    values.push(euc.values[i][j]);
                    colors.push(clPalette[(i + j) % clPalette.length] + '99');
                }}
            }}
            new Chart(c3, {{
                type: 'bar',
                data: {{ labels, datasets: [{{ label: 'Distância Euclidiana', data: values, backgroundColor: colors, borderWidth: 0, borderRadius: 4 }}] }},
                options: {{ responsive:true, maintainAspectRatio:false, indexAxis:'y', plugins:{{ legend:{{ display:false }} }}, scales:{{ x:{{ title:{{ display:true, text:'Distância Euclidiana', color:'#c9d1d9', font:{{ size:10 }} }}, beginAtZero:true }}, y:{{ ticks:{{ font:{{ size:10 }} }} }} }} }},
            }});
        }}
    }}
}}

// ============================
// Utils
// ============================
function fmt(v) {{
    if (v === null || v === undefined) return '—';
    if (typeof v === 'number') {{
        if (Number.isInteger(v)) return v.toLocaleString('pt-BR');
        return v.toLocaleString('pt-BR', {{ minimumFractionDigits: 2, maximumFractionDigits: 4 }});
    }}
    return String(v);
}}

function fmtC(v) {{
    if (v === null || v === undefined) return '—';
    if (typeof v !== 'number') return String(v);
    const s = v.toFixed(10);
    return s.replace(/0+$/, '').replace(/[.]{1}$/, '.0');
}}

// ============================
// Init
// ============================
renderNumericStats();
renderHistograms();
renderCorrelation();
renderScatter();
renderFrequency();
// Init engine toggle to traditional
setEngine('traditional');
</script>

<!-- ==================== CAUSAL TAB ==================== -->
<div id="panel-causal" class="aa-panel">
    <div class="aa-grid" style="grid-template-columns:340px 1fr;gap:20px;">

        <!-- Config panel -->
        <div class="aa-card" style="position:sticky;top:70px;align-self:start;">
            <div class="aa-card-title">Método Causal</div>

            <div class="aa-form-group">
                <label class="aa-label">Método</label>
                <select id="causalMethod" class="aa-select" onchange="updateCausalUI()">
                    <option value="dag">Grafo Causal (DAG)</option>
                    <option value="psm">Propensity Score Matching</option>
                    <option value="mediation">Análise de Mediação</option>
                    <option value="synthetic_control">Controle Sintético</option>
                    <option value="iv">Experimento Naturalista (VI)</option>
                </select>
            </div>

            <div class="aa-info" id="causalMethodInfo" style="margin-bottom:14px;"></div>

            <!-- DAG fields -->
            <div id="causalFieldsDAG">
                <div class="aa-form-group">
                    <label class="aa-label">Variáveis</label>
                    <div class="aa-checkbox-list" id="dagVars" style="max-height:220px;"></div>
                </div>
                <div class="aa-form-group">
                    <label class="aa-label">Nível de Significância α</label>
                    <select id="dagAlpha" class="aa-select">
                        <option value="0.01">0.01 (mais conservador)</option>
                        <option value="0.05" selected>0.05 (padrão)</option>
                        <option value="0.10">0.10 (mais liberal)</option>
                    </select>
                </div>
            </div>

            <!-- PSM fields -->
            <div id="causalFieldsPSM" style="display:none;">
                <div class="aa-form-group"><label class="aa-label">Variável de Tratamento (binária)</label>
                    <select id="psmTreatment" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Desfecho (Y)</label>
                    <select id="psmOutcome" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Covariáveis de Matching</label>
                    <div class="aa-checkbox-list" id="psmCovariates" style="max-height:160px;"></div></div>
            </div>

            <!-- Mediation fields -->
            <div id="causalFieldsMediation" style="display:none;">
                <div class="aa-form-group"><label class="aa-label">Exposição / Causa (X)</label>
                    <select id="medExposure" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Mediador (M)</label>
                    <select id="medMediator" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Desfecho (Y)</label>
                    <select id="medOutcome" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Bootstrap samples</label>
                    <select id="medBoot" class="aa-select">
                        <option value="200">200 (rápido)</option>
                        <option value="500" selected>500 (padrão)</option>
                        <option value="1000">1000 (preciso)</option>
                    </select></div>
            </div>

            <!-- Synthetic Control fields -->
            <div id="causalFieldsSC" style="display:none;">
                <div class="aa-form-group"><label class="aa-label">Coluna de Unidade</label>
                    <select id="scUnit" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Coluna de Tempo</label>
                    <select id="scTime" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Coluna de Desfecho</label>
                    <select id="scOutcome" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Unidade Tratada</label>
                    <select id="scTreatedUnit" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Período de Intervenção</label>
                    <select id="scTreatmentTime" class="aa-select"></select></div>
            </div>

            <!-- IV fields -->
            <div id="causalFieldsIV" style="display:none;">
                <div class="aa-form-group"><label class="aa-label">Instrumento (Z)</label>
                    <select id="ivInstrument" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Tratamento / Endógena (D)</label>
                    <select id="ivTreatment" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Desfecho (Y)</label>
                    <select id="ivOutcome" class="aa-select"></select></div>
                <div class="aa-form-group"><label class="aa-label">Controles (opcional)</label>
                    <div class="aa-checkbox-list" id="ivCovariates" style="max-height:130px;"></div></div>
            </div>

            <button class="aa-btn aa-btn-primary" style="width:100%;margin-top:8px;" onclick="runCausal()" id="causalRunBtn">Executar Análise</button>
            <div id="causalStatus" style="margin-top:8px;font-size:11px;text-align:center;color:#8b949e;"></div>
        </div>

        <!-- Results -->
        <div id="causalResult">
            <div class="aa-card" style="text-align:center;padding:40px;">
                <div style="font-size:32px;margin-bottom:12px;">🔗</div>
                <div style="color:#8b949e;font-size:13px;">Selecione um método e configure as variáveis para iniciar a análise causal.</div>
            </div>
        </div>
    </div>
</div>

<script>
// ============================================================
// CAUSAL INFERENCE — JS ENGINE
// ============================================================

const CAUSAL_INFO = {{
  dag: 'Constrói o esqueleto de um Grafo Acíclico Direcionado (DAG) via correlações parciais e teste Fisher-z. Identifica independências condicionais entre variáveis.',
  psm: 'Propensity Score Matching estima o Efeito Médio do Tratamento nos Tratados (ATT) equilibrando grupos via Regressão Logística + matching 1:1 por vizinho mais próximo.',
  mediation: 'Análise de Mediação (Baron-Kenny) decompõe o efeito total em direto e indireto (mediado). Inclui Teste de Sobel e IC Bootstrap 95%.',
  synthetic_control: 'Controle Sintético estima o contrafactual de uma unidade tratada combinando unidades doadores de forma ótima no pré-tratamento, depois mede o efeito pós-intervenção.',
  iv: 'Variável Instrumental (2SLS) estima o LATE quando o tratamento é endógeno. Reporta F-estatística de 1ª etapa, LATE, OLS ingênuo e Teste de Hausman.',
}};

function updateCausalUI() {{
  const m = document.getElementById('causalMethod').value;
  document.getElementById('causalMethodInfo').textContent = CAUSAL_INFO[m] || '';
  ['DAG','PSM','Mediation','SC','IV'].forEach(k => {{
    const el = document.getElementById('causalFields' + k);
    if (el) el.style.display = 'none';
  }});
  const map = {{dag:'DAG',psm:'PSM',mediation:'Mediation',synthetic_control:'SC',iv:'IV'}};
  const show = document.getElementById('causalFields' + map[m]);
  if (show) show.style.display = 'block';
  populateCausalSelects(m);
}}

function populateCausalSelects(method) {{
  const cols = ALL_COLS;
  const numCols = NUMERIC_COLS;
  const allOpts = cols.map(c => `<option value="${{c}}">${{c}}</option>`).join('');
  const numOpts = numCols.map(c => `<option value="${{c}}">${{c}}</option>`).join('');
  const mkChecks = (id, list) => {{
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = list.map(c => `<label class="aa-checkbox-item"><input type="checkbox" value="${{c}}"><span>${{c}}</span></label>`).join('');
  }};

  if (method === 'dag') {{
    mkChecks('dagVars', cols);
    // pre-select all numeric
    document.querySelectorAll('#dagVars input').forEach(cb => {{
      if (numCols.includes(cb.value)) cb.checked = true;
    }});
  }}
  if (method === 'psm') {{
    ['psmTreatment','psmOutcome'].forEach(id => document.getElementById(id).innerHTML = allOpts);
    mkChecks('psmCovariates', cols);
  }}
  if (method === 'mediation') {{
    ['medExposure','medMediator','medOutcome'].forEach(id => document.getElementById(id).innerHTML = allOpts);
  }}
  if (method === 'synthetic_control') {{
    ['scUnit','scTime','scOutcome'].forEach(id => document.getElementById(id).innerHTML = allOpts);
    // When unit/time changes, populate units/times from data
    ['scUnit','scTime'].forEach(id => {{
      document.getElementById(id).onchange = () => populateSCDynamics();
    }});
    populateSCDynamics();
  }}
  if (method === 'iv') {{
    ['ivInstrument','ivTreatment','ivOutcome'].forEach(id => document.getElementById(id).innerHTML = allOpts);
    mkChecks('ivCovariates', cols);
  }}
}}

function populateSCDynamics() {{
  const unitCol = document.getElementById('scUnit')?.value;
  const timeCol = document.getElementById('scTime')?.value;
  if (!unitCol || !timeCol || !DATA.rows) return;

  const units  = [...new Set(DATA.rows.map(r => String(r[unitCol] ?? '')))].sort();
  const times  = [...new Set(DATA.rows.map(r => String(r[timeCol] ?? '')))].sort();

  document.getElementById('scTreatedUnit').innerHTML  = units.map(u => `<option>${{u}}</option>`).join('');
  document.getElementById('scTreatmentTime').innerHTML = times.map(t => `<option>${{t}}</option>`).join('');
}}

async function runCausal() {{
  const method = document.getElementById('causalMethod').value;
  const config = buildCausalConfig(method);
  if (!config) return;

  const btn = document.getElementById('causalRunBtn');
  const status = document.getElementById('causalStatus');
  btn.disabled = true;
  status.textContent = 'Executando…';

  try {{
    const res = await fetch('/api/analytics/causal', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ query_data: DATA, method, config }}),
    }});
    const result = await res.json();
    status.textContent = '';
    if (result.error) {{ status.style.color = '#ff6347'; status.textContent = result.error; btn.disabled = false; return; }}
    renderCausalResult(result);
  }} catch(e) {{
    status.style.color = '#ff6347';
    status.textContent = 'Erro: ' + e.message;
  }}
  btn.disabled = false;
}}

function buildCausalConfig(method) {{
  if (method === 'dag') {{
    const vars = [...document.querySelectorAll('#dagVars input:checked')].map(c => c.value);
    if (vars.length < 2) {{ alert('Selecione pelo menos 2 variáveis.'); return null; }}
    return {{ variables: vars, alpha: parseFloat(document.getElementById('dagAlpha').value) }};
  }}
  if (method === 'psm') {{
    const covs = [...document.querySelectorAll('#psmCovariates input:checked')].map(c => c.value);
    if (!covs.length) {{ alert('Selecione pelo menos 1 covariável.'); return null; }}
    return {{ treatment: document.getElementById('psmTreatment').value, outcome: document.getElementById('psmOutcome').value, covariates: covs }};
  }}
  if (method === 'mediation') {{
    return {{ exposure: document.getElementById('medExposure').value, mediator: document.getElementById('medMediator').value, outcome: document.getElementById('medOutcome').value, n_bootstrap: parseInt(document.getElementById('medBoot').value) }};
  }}
  if (method === 'synthetic_control') {{
    return {{ unit_col: document.getElementById('scUnit').value, time_col: document.getElementById('scTime').value, outcome_col: document.getElementById('scOutcome').value, treated_unit: document.getElementById('scTreatedUnit').value, treatment_time: document.getElementById('scTreatmentTime').value }};
  }}
  if (method === 'iv') {{
    const covs = [...document.querySelectorAll('#ivCovariates input:checked')].map(c => c.value);
    return {{ instrument: document.getElementById('ivInstrument').value, treatment: document.getElementById('ivTreatment').value, outcome: document.getElementById('ivOutcome').value, covariates: covs }};
  }}
  return null;
}}

// ─── Render dispatcher ───────────────────────────────────────────────────

function renderCausalResult(r) {{
  const container = document.getElementById('causalResult');
  let html = '';
  if      (r.method === 'dag')               html = renderDAG(r);
  else if (r.method === 'psm')               html = renderPSM(r);
  else if (r.method === 'mediation')         html = renderMediation(r);
  else if (r.method === 'synthetic_control') html = renderSC(r);
  else if (r.method === 'iv')               html = renderIV(r);
  container.innerHTML = html;
  setTimeout(() => renderCausalCharts(r), 50);
}}

// ─── DAG ──────────────────────────────────────────────────────────────────

function renderDAG(r) {{
  const cols = r.variables;
  const pcor = r.partial_corr.values;
  const k = cols.length;

  function heatCell(v, diagonal) {{
    if (diagonal) return `<td style="background:#161b22;color:#484f58;text-align:center;font-family:'JetBrains Mono',monospace;font-size:10px;">1.00</td>`;
    const abs = Math.abs(v||0);
    const bg = (v||0) > 0 ? `rgba(57,211,83,${{(abs*0.7+0.1).toFixed(2)}})` : `rgba(255,99,71,${{(abs*0.7+0.1).toFixed(2)}})`;
    const tc = abs > 0.5 ? '#fff' : '#c9d1d9';
    return `<td style="background:${{bg}};color:${{tc}};text-align:center;font-family:'JetBrains Mono',monospace;font-size:10px;padding:5px 8px;">${{(v||0).toFixed(2)}}</td>`;
  }}

  let heatHtml = `<div class="aa-section"><div class="aa-section-title">Correlações Parciais (esqueleto do DAG)</div><div class="aa-card" style="overflow-x:auto;"><table class="aa-freq-table"><thead><tr><th></th>${{cols.map(c=>`<th>${{c}}</th>`).join('')}}</tr></thead><tbody>`;
  for (let i=0;i<k;i++) {{
    heatHtml += `<tr><td style="font-weight:600;color:#58a6ff;font-family:'JetBrains Mono',monospace;">${{cols[i]}}</td>`;
    for (let j=0;j<k;j++) heatHtml += heatCell(pcor[i][j], i===j);
    heatHtml += '</tr>';
  }}
  heatHtml += '</tbody></table></div></div>';

  // Significant edges
  const sigEdges = r.edges.filter(e => e.significant);
  let edgeHtml = `<div class="aa-section"><div class="aa-section-title">Arestas Significativas (p &lt; ${{r.alpha}}) — ${{r.n_edges}} encontradas</div>`;
  if (!sigEdges.length) {{
    edgeHtml += '<div class="aa-info">Nenhuma aresta significativa encontrada. Considere aumentar o nível α ou selecionar mais variáveis.</div>';
  }} else {{
    edgeHtml += `<div class="aa-card" style="overflow-x:auto;"><table class="aa-freq-table aa-coeff-stats-table"><thead><tr><th>Variável A</th><th>Variável B</th><th>r Pearson</th><th>r Parcial</th><th>p-valor</th><th>Direção</th></tr></thead><tbody>`;
    sigEdges.forEach(e => {{
      const dc = e.direction === 'positive' ? '#39d353' : '#ff6347';
      edgeHtml += `<tr class="aa-row-significant"><td style="color:#58a6ff;font-weight:600;">${{e.from}}</td><td style="color:#58a6ff;font-weight:600;">${{e.to}}</td><td>${{fmtC(e.pearson_r)}}</td><td style="font-weight:600;">${{fmtC(e.partial_r)}}</td><td style="color:#39d353;font-weight:600;">${{fmtC(e.partial_p)}}</td><td style="color:${{dc}};font-weight:600;">${{e.direction==='positive'?'↑ positiva':'↓ negativa'}}</td></tr>`;
    }});
    edgeHtml += '</tbody></table></div>';
  }}
  edgeHtml += '</div>';

  // Markov blankets + degree
  let mbHtml = `<div class="aa-section"><div class="aa-section-title">Manto de Markov & Grau de Centralidade</div><div class="aa-grid aa-grid-3">`;
  cols.forEach(v => {{
    const mb = (r.markov_blankets[v] || []);
    const deg = r.degree[v] || 0;
    mbHtml += `<div class="aa-card"><div class="aa-card-title">${{v}} <span style="color:#8b949e;font-weight:400;">(grau ${{deg}})</span></div>`;
    mbHtml += mb.length ? mb.map(n => `<span style="display:inline-block;background:rgba(88,166,255,0.15);color:#58a6ff;border-radius:4px;padding:2px 8px;font-size:11px;margin:2px;">${{n}}</span>`).join('') : '<span style="color:#8b949e;font-size:11px;">Nenhum vizinho significativo</span>';
    mbHtml += '</div>';
  }});
  mbHtml += '</div></div>';

  return `<div class="aa-section"><div class="aa-section-title">Grafo Causal (DAG) — ${{r.n_obs}} obs · ${{cols.length}} variáveis</div>
  <div class="aa-grid aa-grid-4" style="margin-bottom:16px;">
    <div class="aa-metric-card"><div class="aa-metric-value">${{r.n_edges}}</div><div class="aa-metric-label">Arestas</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{cols.length}}</div><div class="aa-metric-label">Nós</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{r.alpha}}</div><div class="aa-metric-label">α utilizado</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{r.n_obs}}</div><div class="aa-metric-label">Observações</div></div>
  </div></div>` + heatHtml + edgeHtml + mbHtml;
}}

// ─── PSM ─────────────────────────────────────────────────────────────────

function renderPSM(r) {{
  const sigColor = r.significant ? '#39d353' : '#f0883e';
  const att_dir  = (r.att||0) > 0 ? '▲' : '▼';

  let html = `<div class="aa-section"><div class="aa-section-title">PSM — Tratamento: ${{r.treatment}} → Desfecho: ${{r.outcome}}</div>
  <div class="aa-grid aa-grid-4" style="margin-bottom:16px;">
    <div class="aa-metric-card"><div class="aa-metric-value" style="color:${{sigColor}}">${{fmtC(r.att)}}</div><div class="aa-metric-label">ATT (efeito)</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{r.att_pct !== null ? r.att_pct.toFixed(1)+'%' : '—'}}</div><div class="aa-metric-label">ATT relativo</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value" style="color:${{sigColor}}">${{fmtC(r.p_value)}}</div><div class="aa-metric-label">p-valor (t-test)</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{r.n_matched_pairs}}</div><div class="aa-metric-label">Pares matched</div></div>
  </div>
  <div class="aa-grid aa-grid-3" style="margin-bottom:16px;">
    <div class="aa-card"><div class="aa-card-title">Média Tratados (matched)</div><div class="aa-metric-value" style="font-size:18px;color:#c9d1d9;">${{fmtC(r.mean_treated)}}</div></div>
    <div class="aa-card"><div class="aa-card-title">Média Controles (matched)</div><div class="aa-metric-value" style="font-size:18px;color:#c9d1d9;">${{fmtC(r.mean_control)}}</div></div>
    <div class="aa-card"><div class="aa-card-title">IC 95% ATT</div><div class="aa-metric-value" style="font-size:16px;color:#c9d1d9;">[${{fmtC(r.ci_lower)}}, ${{fmtC(r.ci_upper)}}]</div></div>
  </div></div>`;

  // Balance table
  html += `<div class="aa-section"><div class="aa-section-title">Balanço de Covariáveis (SMD — ideal &lt; 0.10)</div><div class="aa-card" style="overflow-x:auto;">
  <table class="aa-freq-table aa-coeff-stats-table"><thead><tr><th>Covariável</th><th>Média T (antes)</th><th>Média C (antes)</th><th>SMD antes</th><th>Média T (depois)</th><th>Média C (depois)</th><th>SMD depois</th><th>Balanceado?</th></tr></thead><tbody>`;
  (r.balance || []).forEach(b => {{
    const bc = b.balanced ? '#39d353' : '#f0883e';
    html += `<tr class="${{b.balanced?'aa-row-significant':''}}"><td style="font-weight:600;">${{b.covariate}}</td><td>${{fmtC(b.mean_t_before)}}</td><td>${{fmtC(b.mean_c_before)}}</td><td style="color:${{Math.abs(b.smd_before||0)>0.1?'#f0883e':'#8b949e'}};font-weight:600;">${{fmtC(b.smd_before)}}</td><td>${{fmtC(b.mean_t_after)}}</td><td>${{fmtC(b.mean_c_after)}}</td><td style="color:${{bc}};font-weight:600;">${{fmtC(b.smd_after)}}</td><td style="color:${{bc}};font-weight:700;text-align:center;">${{b.balanced?'✓':'✗'}}</td></tr>`;
  }});
  html += '</tbody></table></div></div>';

  // PS distribution chart
  html += `<div class="aa-section"><div class="aa-section-title">Distribuição dos Propensity Scores</div><div class="aa-card"><div style="height:280px;"><canvas id="causalChart1"></canvas></div></div></div>`;

  return html;
}}

// ─── Mediation ────────────────────────────────────────────────────────────

function renderMediation(r) {{
  const indSig = r.boot_significant;
  const indColor = indSig ? '#39d353' : '#f0883e';

  // Path diagram (ASCII art in styled div)
  const pct = r.proportion_mediated !== null ? (r.proportion_mediated*100).toFixed(1)+'%' : '—';
  let diagram = `<div class="aa-section"><div class="aa-section-title">Diagrama de Caminhos</div>
  <div class="aa-card" style="font-family:'JetBrains Mono',monospace;font-size:12px;padding:20px;">
    <div style="display:flex;align-items:center;justify-content:center;gap:0;flex-wrap:wrap;">
      <div style="background:#21262d;border:1px solid #30363d;border-radius:8px;padding:10px 16px;color:#58a6ff;font-weight:700;">${{r.exposure}}</div>
      <div style="display:flex;flex-direction:column;align-items:center;margin:0 8px;">
        <span style="color:#39d353;font-size:10px;">a=${{fmtC(r.a_path)}}</span>
        <span style="font-size:18px;color:#39d353;">→</span>
      </div>
      <div style="background:#21262d;border:1px solid #30363d;border-radius:8px;padding:10px 16px;color:#a371f7;font-weight:700;">${{r.mediator}}</div>
      <div style="display:flex;flex-direction:column;align-items:center;margin:0 8px;">
        <span style="color:#39d353;font-size:10px;">b=${{fmtC(r.b_path)}}</span>
        <span style="font-size:18px;color:#39d353;">→</span>
      </div>
      <div style="background:#21262d;border:1px solid #30363d;border-radius:8px;padding:10px 16px;color:#f0883e;font-weight:700;">${{r.outcome}}</div>
    </div>
    <div style="text-align:center;margin-top:12px;color:#8b949e;font-size:11px;">
      Efeito total (c) = ${{fmtC(r.total_effect)}} &nbsp;|&nbsp; Direto (c') = ${{fmtC(r.direct_effect)}} &nbsp;|&nbsp; <span style="color:${{indColor}};font-weight:700;">Indireto (a×b) = ${{fmtC(r.indirect_effect)}}</span>
    </div>
  </div></div>`;

  let html = `<div class="aa-section"><div class="aa-section-title">Mediação — ${{r.exposure}} → ${{r.mediator}} → ${{r.outcome}}</div>
  <div class="aa-grid aa-grid-4" style="margin-bottom:16px;">
    <div class="aa-metric-card"><div class="aa-metric-value">${{fmtC(r.total_effect)}}</div><div class="aa-metric-label">Efeito Total (c)</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{fmtC(r.direct_effect)}}</div><div class="aa-metric-label">Efeito Direto (c')</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value" style="color:${{indColor}}">${{fmtC(r.indirect_effect)}}</div><div class="aa-metric-label">Efeito Indireto (a×b)</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{pct}}</div><div class="aa-metric-label">Proporção Mediada</div></div>
  </div></div>` + diagram;

  // Paths table
  html += `<div class="aa-section"><div class="aa-section-title">Tabela de Caminhos</div><div class="aa-card" style="overflow-x:auto;">
  <table class="aa-freq-table aa-coeff-stats-table"><thead><tr><th>Caminho</th><th>Estimativa</th><th>Std Err</th><th>t / z</th><th>p-valor</th><th>Sig.</th></tr></thead><tbody>`;
  (r.paths||[]).forEach(p => {{
    html += `<tr class="${{p.sig?'aa-row-significant':''}}"><td style="font-weight:600;">${{p.name}}</td><td>${{fmtC(p.value)}}</td><td>${{fmtC(p.se)}}</td><td>${{fmtC(p.t)}}</td><td style="color:${{p.sig?'#39d353':'#8b949e'}};font-weight:${{p.sig?'600':'normal'}}">${{fmtC(p.p)}}</td><td style="color:${{p.sig?'#39d353':'#8b949e'}};text-align:center;">${{p.sig?'★':''}}</td></tr>`;
  }});
  html += '</tbody></table></div></div>';

  // Bootstrap CI
  const bootSigText = r.boot_significant ? '<span style="color:#39d353">Significativo — IC não contém zero</span>' : '<span style="color:#f0883e">Não significativo — IC contém zero</span>';
  html += `<div class="aa-section"><div class="aa-section-title">Bootstrap IC 95% para Efeito Indireto</div>
  <div class="aa-grid aa-grid-3" style="margin-bottom:12px;">
    <div class="aa-card"><div class="aa-card-title">IC Inferior</div><div class="aa-metric-value" style="color:${{indColor}};font-size:18px;">${{fmtC(r.boot_ci_lower)}}</div></div>
    <div class="aa-card"><div class="aa-card-title">IC Superior</div><div class="aa-metric-value" style="color:${{indColor}};font-size:18px;">${{fmtC(r.boot_ci_upper)}}</div></div>
    <div class="aa-card" style="display:flex;align-items:center;justify-content:center;"><div style="font-size:13px;">${{bootSigText}}</div></div>
  </div>
  <div class="aa-card"><div class="aa-card-title">Distribuição Bootstrap do Efeito Indireto</div><div style="height:240px;"><canvas id="causalChart1"></canvas></div></div></div>`;

  return html;
}}

// ─── Synthetic Control ────────────────────────────────────────────────────

function renderSC(r) {{
  const attColor = (r.att_avg||0) > 0 ? '#39d353' : '#ff6347';

  let html = `<div class="aa-section"><div class="aa-section-title">Controle Sintético — Unidade: ${{r.treated_unit}} · Intervenção: ${{r.treatment_time}}</div>
  <div class="aa-grid aa-grid-4" style="margin-bottom:16px;">
    <div class="aa-metric-card"><div class="aa-metric-value" style="color:${{attColor}}">${{fmtC(r.att_avg)}}</div><div class="aa-metric-label">ATT médio pós</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{r.att_pct !== null ? r.att_pct.toFixed(1)+'%' : '—'}}</div><div class="aa-metric-label">ATT relativo</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{fmtC(r.rmse_pre)}}</div><div class="aa-metric-label">RMSE pré</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value">${{r.n_donors}}</div><div class="aa-metric-label">Doadores</div></div>
  </div></div>`;

  // Time series chart
  html += `<div class="aa-section"><div class="aa-section-title">Série Temporal — Real vs Sintético</div><div class="aa-card"><div style="height:320px;"><canvas id="causalChart1"></canvas></div></div></div>`;

  // Gap chart
  html += `<div class="aa-section"><div class="aa-section-title">Gap (Real − Sintético)</div><div class="aa-card"><div style="height:200px;"><canvas id="causalChart2"></canvas></div></div></div>`;

  // Donor weights
  const topDonors = (r.donor_weights||[]).slice(0,15);
  html += `<div class="aa-section"><div class="aa-section-title">Pesos dos Doadores (pool de controle)</div>
  <div class="aa-card" style="overflow-x:auto;"><table class="aa-freq-table"><thead><tr><th>Unidade</th><th>Peso</th><th>Visualização</th></tr></thead><tbody>`;
  topDonors.forEach(d => {{
    const pct = ((d.weight||0)*100).toFixed(1);
    html += `<tr><td style="font-family:'JetBrains Mono',monospace;">${{d.unit}}</td><td style="font-family:'JetBrains Mono',monospace;">${{pct}}%</td><td><div style="width:${{Math.max(parseFloat(pct),1)}}%;min-width:2px;height:8px;background:#58a6ff;border-radius:2px;"></div></td></tr>`;
  }});
  html += '</tbody></table></div></div>';

  return html;
}}

// ─── IV ──────────────────────────────────────────────────────────────────

function renderIV(r) {{
  const lateSig = r.late_significant;
  const lateColor = lateSig ? '#39d353' : '#f0883e';
  const fColor = r.first_stage_f >= 10 ? '#39d353' : (r.first_stage_f >= 5 ? '#f0883e' : '#ff6347');
  const endog = r.endogeneity_detected;

  let html = `<div class="aa-section"><div class="aa-section-title">Variável Instrumental (2SLS) — Z: ${{r.instrument}} · D: ${{r.treatment}} · Y: ${{r.outcome}}</div>
  <div class="aa-grid aa-grid-4" style="margin-bottom:16px;">
    <div class="aa-metric-card"><div class="aa-metric-value" style="color:${{lateColor}}">${{fmtC(r.late)}}</div><div class="aa-metric-label">LATE (2SLS)</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value" style="color:#8b949e;">${{fmtC(r.ols_estimate)}}</div><div class="aa-metric-label">OLS (ingênuo)</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value" style="color:${{fColor}}">${{r.first_stage_f !== null ? r.first_stage_f.toFixed(1) : '—'}}</div><div class="aa-metric-label">F 1ª etapa</div></div>
    <div class="aa-metric-card"><div class="aa-metric-value" style="color:${{endog?'#f0883e':'#39d353'}}">${{endog?'Sim':'Não'}}</div><div class="aa-metric-label">Endogeneidade (p&lt;0.10)</div></div>
  </div></div>`;

  // Detailed stats
  html += `<div class="aa-grid aa-grid-2" style="gap:16px;margin-bottom:16px;">
  <div class="aa-card"><div class="aa-card-title">1ª Etapa — Instrumento → Tratamento</div>
    <div class="aa-stat"><span class="aa-stat-label">F-estatística</span><span class="aa-stat-value" style="color:${{fColor}}">${{fmtC(r.first_stage_f)}} (${{r.instrument_strength}})</span></div>
    <div class="aa-stat"><span class="aa-stat-label">p-valor (F)</span><span class="aa-stat-value">${{fmtC(r.first_stage_f_pval)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">R² 1ª etapa</span><span class="aa-stat-value">${{fmtC(r.first_stage_r2)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">Corr(Z, D)</span><span class="aa-stat-value">${{fmtC(r.corr_instrument_treatment)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">Corr(Z, Y)</span><span class="aa-stat-value">${{fmtC(r.corr_instrument_outcome)}}</span></div>
  </div>
  <div class="aa-card"><div class="aa-card-title">2ª Etapa — Estimativa LATE</div>
    <div class="aa-stat"><span class="aa-stat-label">LATE (2SLS)</span><span class="aa-stat-value" style="color:${{lateColor}};font-weight:700;">${{fmtC(r.late)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">Erro Padrão</span><span class="aa-stat-value">${{fmtC(r.se_late)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">t-estatística</span><span class="aa-stat-value">${{fmtC(r.t_late)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">p-valor</span><span class="aa-stat-value" style="color:${{lateColor}};font-weight:600;">${{fmtC(r.p_late)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">IC 95%</span><span class="aa-stat-value">[${{fmtC(r.ci_late_lower)}}, ${{fmtC(r.ci_late_upper)}}]</span></div>
  </div></div>`;

  // Comparison + Hausman
  const biasDir = (r.late||0) > (r.ols_estimate||0) ? 'OLS subestima' : 'OLS superestima';
  const biasDelta = (r.late||0) - (r.ols_estimate||0);
  html += `<div class="aa-section"><div class="aa-section-title">Comparação LATE vs OLS & Teste de Hausman</div>
  <div class="aa-card">
    <div class="aa-stat"><span class="aa-stat-label">LATE (2SLS — efeito causal)</span><span class="aa-stat-value" style="color:${{lateColor}};font-weight:700;">${{fmtC(r.late)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">OLS (viés potencial)</span><span class="aa-stat-value" style="color:#8b949e;">${{fmtC(r.ols_estimate)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">Forma Reduzida (Z→Y)</span><span class="aa-stat-value">${{fmtC(r.reduced_form)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">Diferença LATE−OLS</span><span class="aa-stat-value" style="color:${{Math.abs(biasDelta||0)>0.05?'#f0883e':'#8b949e'}}">${{fmtC(biasDelta)}} (${{biasDir}})</span></div>
    <div class="aa-stat"><span class="aa-stat-label">Hausman χ²</span><span class="aa-stat-value">${{fmtC(r.hausman_chi2)}}</span></div>
    <div class="aa-stat"><span class="aa-stat-label">Hausman p-valor</span><span class="aa-stat-value" style="color:${{endog?'#f0883e':'#39d353'}}">${{fmtC(r.hausman_p)}} ${{endog?'→ endogeneidade detectada':'→ sem evidência de endogeneidade'}}</span></div>
  </div></div>`;

  return html;
}}

// ─── Charts ───────────────────────────────────────────────────────────────

function renderCausalCharts(r) {{
  if (r.method === 'psm') {{
    // PS distribution: treated vs control
    const c1 = document.getElementById('causalChart1');
    if (c1 && r.ps_treated && r.ps_control) {{
      const bins = 20;
      function mkHist(vals) {{
        const counts = new Array(bins).fill(0);
        vals.forEach(v => {{ const b = Math.min(Math.floor(v*bins), bins-1); counts[b]++; }});
        return counts;
      }}
      const labels = Array.from({{length:bins}},(_,i) => ((i/bins)+0.025).toFixed(2));
      new Chart(c1, {{
        type: 'bar',
        data: {{ labels, datasets: [
          {{label:`Tratados (${{r.n_treated}})`, data: mkHist(r.ps_treated), backgroundColor:'rgba(255,99,71,0.5)', borderColor:'#ff6347', borderWidth:1}},
          {{label:`Controles (${{r.n_control}})`, data: mkHist(r.ps_control), backgroundColor:'rgba(88,166,255,0.4)', borderColor:'#58a6ff', borderWidth:1}},
        ]}},
        options: {{ responsive:true, maintainAspectRatio:false, plugins:{{legend:{{labels:{{color:'#c9d1d9'}}}}}}, scales:{{x:{{title:{{display:true,text:'Propensity Score',color:'#c9d1d9'}}}},y:{{beginAtZero:true}}}} }},
      }});
    }}
  }}

  if (r.method === 'mediation' && r.boot_distribution) {{
    const c1 = document.getElementById('causalChart1');
    if (c1) {{
      const vals = r.boot_distribution.filter(v=>v!==null);
      const min = Math.min(...vals), max = Math.max(...vals);
      const bins = 25, w = (max-min)/bins;
      const counts = new Array(bins).fill(0);
      vals.forEach(v => {{ const b = Math.min(Math.floor((v-min)/w), bins-1); counts[b]++; }});
      const labels = Array.from({{length:bins}},(_,i)=>((min+i*w)+w/2).toFixed(3));
      const bgColors = labels.map(l => {{
        const v = parseFloat(l);
        return (r.boot_ci_lower <= v && v <= r.boot_ci_upper) ? 'rgba(88,166,255,0.6)' : 'rgba(255,99,71,0.3)';
      }});
      new Chart(c1, {{
        type:'bar',
        data:{{labels, datasets:[{{label:'Bootstrap samples', data:counts, backgroundColor:bgColors, borderWidth:0, borderRadius:2}}]}},
        options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{title:{{display:true,text:'Efeito Indireto (a×b)',color:'#c9d1d9'}},ticks:{{maxRotation:45,font:{{size:9}}}}}},y:{{beginAtZero:true}}}}}},
      }});
    }}
  }}

  if (r.method === 'synthetic_control' && r.series) {{
    const c1 = document.getElementById('causalChart1');
    const c2 = document.getElementById('causalChart2');
    const labels  = r.series.map(s=>s.time);
    const actual  = r.series.map(s=>s.actual);
    const synth   = r.series.map(s=>s.synthetic);
    const gap     = r.series.map(s=>s.gap);
    const postIdx = r.series.findIndex(s=>s.post);

    if (c1) {{
      new Chart(c1, {{
        type:'line',
        data:{{labels, datasets:[
          {{label:`${{r.treated_unit}} (real)`, data:actual, borderColor:'#ff6347', backgroundColor:'rgba(255,99,71,0.1)', fill:false, tension:0.3, pointRadius:4}},
          {{label:'Sintético (contrafactual)', data:synth, borderColor:'#58a6ff', borderDash:[6,3], backgroundColor:'rgba(88,166,255,0.05)', fill:false, tension:0.3, pointRadius:3}},
        ]}},
        options:{{responsive:true,maintainAspectRatio:false,
          plugins:{{legend:{{labels:{{color:'#c9d1d9'}}}}}},
          scales:{{x:{{ticks:{{maxRotation:45,font:{{size:9}}}}}},y:{{title:{{display:true,text:'Desfecho',color:'#c9d1d9'}}}}}},
        }},
      }});
    }}
    if (c2) {{
      const gapColors = gap.map((v,i) => r.series[i].post ? 'rgba(57,211,83,0.6)' : 'rgba(139,148,158,0.4)');
      new Chart(c2, {{
        type:'bar',
        data:{{labels, datasets:[{{label:'Gap (Real − Sintético)', data:gap, backgroundColor:gapColors, borderWidth:0, borderRadius:2}}]}},
        options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{color:'#c9d1d9'}}}}}},scales:{{x:{{ticks:{{maxRotation:45,font:{{size:9}}}}}},y:{{title:{{display:true,text:'Gap',color:'#c9d1d9'}}}} }} }},
      }});
    }}
  }}
}}

// ─── Init causal tab ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => updateCausalUI());
</script>

</body>
</html>"""


def _empty_html() -> str:
    return """<!DOCTYPE html>
<html><head><title>Fale com Seus Dados</title></head>
<body style="background:#0a0c10;color:#8b949e;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center">
<h2 style="color:#ff6347">Sem dados para análise</h2>
<p>Execute uma consulta que retorne resultados tabulares.</p>
</div></body></html>"""
