"""
Supervised Random Forest model for ECO-SENTINEL.

The model predicts:
    0 -> No Deforestation
    1 -> Deforestation / Forest Loss

The feature set contains the original 16 Sentinel-2 change features plus
6 spatial NBR/context features inspired by spatial-normalization research.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier


# ------------------------------------------------------------------
# Features used by the supervised model
# ------------------------------------------------------------------

FEATURE_COLUMNS = [
    "delta_B1",
    "delta_B2",
    "delta_B3",
    "delta_B4",
    "delta_B5",
    "delta_B6",
    "delta_B7",
    "delta_B8",
    "delta_B8A",
    "delta_B9",
    "delta_B11",
    "delta_B12",
    "delta_ndvi",
    "delta_nbr",
    "delta_ndwi",
    "delta_ndmi",
    "nbr_local_median_2023",
    "nbr_local_median_2025",
    "snbr_2023",
    "snbr_2025",
    "delta_snbr",
    "nbr_change_zscore",
]


class DeforestationRandomForest:
    """Random Forest classifier for polygon/pixel-level forest loss."""

    def __init__(
        self,
        n_estimators: int = 300,
        random_state: int = 42,
        class_weight: str = "balanced",
    ) -> None:
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            random_state=random_state,
            class_weight=class_weight,
            n_jobs=-1,
            max_features="sqrt",
        )

    @staticmethod
    def _prepare_features(
        rows: Iterable[dict],
    ) -> np.ndarray:
        """Convert feature dictionaries into the model matrix."""
        prepared = []

        for row in rows:
            values = []

            for feature in FEATURE_COLUMNS:
                value = row.get(feature, 0.0)

                if value is None:
                    value = 0.0

                values.append(float(value))

            prepared.append(values)

        if not prepared:
            return np.empty(
                (0, len(FEATURE_COLUMNS)),
                dtype=float,
            )

        return np.asarray(
            prepared,
            dtype=float,
        )

    def fit(
        self,
        rows: Iterable[dict],
        labels: Iterable[int],
    ) -> "DeforestationRandomForest":
        """Train the Random Forest."""
        X = self._prepare_features(rows)
        y = np.asarray(list(labels), dtype=int)

        if len(X) == 0:
            raise ValueError(
                "Cannot train the model with zero samples."
            )

        if len(X) != len(y):
            raise ValueError(
                "Number of feature rows and labels must match."
            )

        unique_labels = set(y.tolist())

        if not {0, 1}.issubset(unique_labels):
            raise ValueError(
                "Training requires both classes: "
                "0 = no deforestation and "
                "1 = deforestation."
            )

        self.model.fit(X, y)

        return self

    def predict(
        self,
        rows: Iterable[dict],
    ) -> list[int]:
        """Predict deforestation class."""
        X = self._prepare_features(rows)

        if len(X) == 0:
            return []

        return (
            self.model
            .predict(X)
            .astype(int)
            .tolist()
        )

    def predict_probability(
        self,
        rows: Iterable[dict],
    ) -> list[float]:
        """Return probability of the deforestation class."""
        X = self._prepare_features(rows)

        if len(X) == 0:
            return []

        probabilities = self.model.predict_proba(X)
        classes = list(self.model.classes_)

        if 1 not in classes:
            raise RuntimeError(
                "The trained model does not contain "
                "the deforestation class."
            )

        class_index = classes.index(1)

        return (
            probabilities[:, class_index]
            .astype(float)
            .tolist()
        )

    def feature_importance(self) -> dict[str, float]:
        """Return feature importance values."""
        if not hasattr(
            self.model,
            "feature_importances_",
        ):
            raise RuntimeError(
                "Model must be trained before "
                "reading feature importance."
            )

        return {
            feature: float(importance)
            for feature, importance in zip(
                FEATURE_COLUMNS,
                self.model.feature_importances_,
            )
        }

    def save(
        self,
        path: str | Path,
    ) -> None:
        """Save the trained model."""
        path = Path(path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        joblib.dump(
            self.model,
            path,
        )

    def load(
        self,
        path: str | Path,
    ) -> "DeforestationRandomForest":
        """Load a trained Random Forest."""
        self.model = joblib.load(path)
        return self
