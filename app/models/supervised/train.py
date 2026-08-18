"""
Train and evaluate the ECO-SENTINEL supervised Random Forest.

Labels:
    0 = no reference forest loss
    1 = reference forest loss

The model is evaluated on a held-out test set that is never used
during training.
"""

from __future__ import annotations

import json
import os

import joblib
import pandas as pd

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_score,
    recall_score,
    f1_score,
)
from sklearn.model_selection import train_test_split

from app.models.supervised.random_forest import FEATURE_COLUMNS


DATASET_PATH = r".\data\supervised\training_samples.csv"
MODEL_DIR = r".\data\supervised"
MODEL_PATH = os.path.join(
    MODEL_DIR,
    "deforestation_random_forest.joblib",
)
METRICS_PATH = os.path.join(
    MODEL_DIR,
    "model_metrics.json",
)


def main() -> None:
    print("=" * 60)
    print("ECO-SENTINEL SUPERVISED MODEL TRAINING")
    print("=" * 60)

    df = pd.read_csv(DATASET_PATH)

    print(f"Dataset: {df.shape[0]:,} samples")
    print(f"Features: {len(FEATURE_COLUMNS)}")

    X = df[FEATURE_COLUMNS]
    y = df["label"].astype(int)

    # ---------------------------------------------------------
    # 80% training / 20% testing.
    # Stratification preserves the class balance.
    # ---------------------------------------------------------

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=42,
        stratify=y,
    )

    print(f"Training samples: {len(X_train):,}")
    print(f"Testing samples:  {len(X_test):,}")

    # ---------------------------------------------------------
    # Random Forest
    # ---------------------------------------------------------

    model = RandomForestClassifier(
        n_estimators=300,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
        max_features="sqrt",
    )

    print("\nTraining Random Forest...")

    model.fit(
        X_train,
        y_train,
    )

    print("Training complete.")

    # ---------------------------------------------------------
    # Evaluation
    # ---------------------------------------------------------

    predictions = model.predict(X_test)

    accuracy = accuracy_score(
        y_test,
        predictions,
    )

    precision = precision_score(
        y_test,
        predictions,
        zero_division=0,
    )

    recall = recall_score(
        y_test,
        predictions,
        zero_division=0,
    )

    f1 = f1_score(
        y_test,
        predictions,
        zero_division=0,
    )

    matrix = confusion_matrix(
        y_test,
        predictions,
    )

    print("\n" + "=" * 60)
    print("MODEL EVALUATION")
    print("=" * 60)

    print(f"Accuracy : {accuracy:.4f}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall   : {recall:.4f}")
    print(f"F1 Score : {f1:.4f}")

    print("\nConfusion Matrix:")
    print(matrix)

    print("\nClassification Report:")
    print(
        classification_report(
            y_test,
            predictions,
            target_names=[
                "No Deforestation",
                "Deforestation",
            ],
            zero_division=0,
        )
    )

    # ---------------------------------------------------------
    # Feature importance
    # ---------------------------------------------------------

    feature_importance = {
        feature: float(importance)
        for feature, importance in zip(
            FEATURE_COLUMNS,
            model.feature_importances_,
        )
    }

    feature_importance = dict(
        sorted(
            feature_importance.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )

    print("\nFeature Importance:")
    for feature, importance in feature_importance.items():
        print(
            f"  {feature:<20} {importance:.4f}"
        )

    # ---------------------------------------------------------
    # Save model
    # ---------------------------------------------------------

    os.makedirs(
        MODEL_DIR,
        exist_ok=True,
    )

    joblib.dump(
        model,
        MODEL_PATH,
    )

    metrics = {
        "model": "RandomForestClassifier",
        "random_state": 42,
        "n_estimators": 300,
        "test_size": 0.20,
        "training_samples": int(len(X_train)),
        "testing_samples": int(len(X_test)),
        "accuracy": float(accuracy),
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1),
        "confusion_matrix": matrix.tolist(),
        "feature_importance": feature_importance,
        "features": FEATURE_COLUMNS,
        "dataset": DATASET_PATH,
        "model_path": MODEL_PATH,
    }

    with open(
        METRICS_PATH,
        "w",
    ) as f:
        json.dump(
            metrics,
            f,
            indent=2,
        )

    print("\n" + "=" * 60)
    print("MODEL SAVED")
    print("=" * 60)
    print(f"Model  : {MODEL_PATH}")
    print(f"Metrics: {METRICS_PATH}")


if __name__ == "__main__":
    main()