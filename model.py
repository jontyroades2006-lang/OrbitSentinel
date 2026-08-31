from __future__ import annotations

import os
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import joblib

MODEL_PATH = os.path.join(os.path.dirname(__file__), "uncertainty_model.joblib")

FEATURE_NAMES = [
    "propagation_hours",   # how far ahead we're predicting
    "tle_age_days",        # staleness of the mean elements
    "perigee_alt_km",
    "eccentricity",
    "inclination_deg",
]


def _synthesize_training_data(n_samples: int = 6000, seed: int = 42):
    rng = np.random.default_rng(seed)

    propagation_hours = rng.uniform(0, 120, n_samples)          # 0-5 days lookahead
    tle_age_days = rng.uniform(0, 14, n_samples)                 # 0-2 weeks stale
    perigee_alt_km = rng.uniform(300, 2000, n_samples)           # LEO band
    eccentricity = np.abs(rng.normal(0.001, 0.01, n_samples))
    inclination_deg = rng.uniform(0, 100, n_samples)

    # Physically-motivated base error model (km), loosely reflecting
    # published SGP4 accuracy studies (errors of ~1-3 km/day growing faster
    # at low altitude due to drag mismodeling).
    drag_factor = np.clip(1.6 - (perigee_alt_km / 1000.0), 0.15, 1.6)
    base_growth_per_day = 0.9 * drag_factor + 0.15 * (eccentricity * 100)
    time_days = propagation_hours / 24.0
    age_penalty = 0.35 * tle_age_days * drag_factor

    error_km = (
        base_growth_per_day * time_days
        + age_penalty
        + 0.01 * inclination_deg * 0  # inclination has weak independent effect
        + 0.05
    )
    # multiplicative + additive noise, always positive
    noise = rng.normal(0, 0.15, n_samples) * error_km + rng.normal(0, 0.05, n_samples)
    error_km = np.clip(error_km + noise, 0.02, None)

    X = np.column_stack([
        propagation_hours, tle_age_days, perigee_alt_km, eccentricity, inclination_deg,
    ])
    y = error_km
    return X, y


class UncertaintyModel:
    """Thin wrapper around a GradientBoostingRegressor predicting expected
    3D position error (km, 1-sigma-ish) for an SGP4 propagation."""

    def __init__(self):
        self.model: GradientBoostingRegressor | None = None
        self.metrics: dict = {}

    def train(self, save: bool = True) -> dict:
        X, y = _synthesize_training_data()
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=7
        )
        model = GradientBoostingRegressor(
            n_estimators=200, max_depth=3, learning_rate=0.08, random_state=7
        )
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        mae = mean_absolute_error(y_test, preds)

        self.model = model
        self.metrics = {
            "mae_km": round(float(mae), 4),
            "n_train": len(X_train),
            "n_test": len(X_test),
            "feature_names": FEATURE_NAMES,
        }
        if save:
            joblib.dump({"model": model, "metrics": self.metrics}, MODEL_PATH)
        return self.metrics

    def load_or_train(self) -> dict:
        if os.path.exists(MODEL_PATH):
            payload = joblib.load(MODEL_PATH)
            self.model = payload["model"]
            self.metrics = payload["metrics"]
            return self.metrics
        return self.train(save=True)

    def predict_error_km(self, propagation_hours: float, tle_age_days: float,
                          perigee_alt_km: float, eccentricity: float,
                          inclination_deg: float) -> float:
        if self.model is None:
            self.load_or_train()
        X = np.array([[propagation_hours, tle_age_days, perigee_alt_km,
                        eccentricity, inclination_deg]])
        pred = float(self.model.predict(X)[0])
        return max(pred, 0.01)


_singleton: UncertaintyModel | None = None


def get_model() -> UncertaintyModel:
    global _singleton
    if _singleton is None:
        _singleton = UncertaintyModel()
        _singleton.load_or_train()
    return _singleton
