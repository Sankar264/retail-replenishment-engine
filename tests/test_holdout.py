import numpy as np
from src import forecasting as F
from src.generate import generate
from src.util import load_config


def _setup():
    cfg = load_config("tiny")
    g = generate(cfg)
    return cfg, g, F.build_mats(g["tables"], g["aux"])


def test_holdout_is_temporal_and_metrics_reported_on_test_only():
    cfg, g, m = _setup()
    ev = F.evaluate_holdout(m, cfg["holdout_days"], cfg["min_history_days"])
    assert ev["train_end_date"] < ev["test_start_date"]
    assert ev["train_days"] + ev["test_days"] == cfg["n_days"]
    assert ev["methods"]["hybrid"]["overall_daily"]["n_obs"] > 0
    assert "naive_last28" in ev["methods"]


def test_forecast_never_reads_data_at_or_after_cutoff():
    """Perturbing every sale on/after the cutoff must not change the forecast (no future-sales leakage)."""
    cfg, g, m = _setup()
    c = cfg["n_days"] - cfg["holdout_days"]
    H = cfg["holdout_days"]
    base = F.forecast(m, c, H, cfg["min_history_days"]).pred["hybrid"].copy()
    m.units[:, c:] = m.units[:, c:] * 7 + 3
    m.oh_end[:, c:] = 0
    m.flag[:, c:] = True
    again = F.forecast(m, c, H, cfg["min_history_days"]).pred["hybrid"]
    assert np.allclose(base, again)


def test_censored_days_excluded_from_training():
    cfg, g, m = _setup()
    assert m.censored.sum() > 0
    assert not (m.valid & m.censored).any()


def test_final_forecast_cutoff_precedes_period():
    cfg, g, m = _setup()
    fct, _ = F.build_forecast_table(m, g["tables"], g["aux"], cfg)
    assert (fct["training_cutoff_date"] < fct["period_start"]).all()
