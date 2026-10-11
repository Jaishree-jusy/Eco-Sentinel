"""
Train and evaluate the ECO-SENTINEL supervised deforestation classifier.

Model:
    LightGBM gradient boosting classifier.

Labels:
    0 = no reference forest loss
    1 = reference forest loss

Evaluation:
    70% training
    10% validation
    20% final test

The validation set is used for:
    - LightGBM early stopping
    - decision-threshold selection

The final test set is never used during training or threshold selection.
"""

from __future__ import annotations

import json
import os

import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb

from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split

from app.models.supervised.random_forest import FEATURE_COLUMNS


DATASET_PATH = r".\data\supervised\training_samples.csv"

MODEL_DIR = r".\data\supervised"

MODEL_PATH = os.path.join(
    MODEL_DIR,
    "deforestation_lightgbm.joblib",
)

METRICS_PATH = os.path.join(
    MODEL_DIR,
    "lightgbm_model_metrics.json",
)


def find_best_accuracy_threshold(
    y_true,
    probabilities,
):
    """
    Find the probability threshold that gives the highest
    accuracy on the validation set.

    The final test set is NOT used here.
    """

    thresholds = np.arange(
        0.10,
        0.91,
        0.01,
    )

    best_threshold = 0.50
    best_accuracy = 0.0

    for threshold in thresholds:

        predictions = (
            probabilities >= threshold
        ).astype(int)

        accuracy = accuracy_score(
            y_true,
            predictions,
        )

        if accuracy > best_accuracy:

            best_accuracy = accuracy
            best_threshold = float(threshold)

    return best_threshold, best_accuracy


def main() -> None:

    print("=" * 70)
    print("ECO-SENTINEL LIGHTGBM MODEL TRAINING")
    print("=" * 70)

    # ---------------------------------------------------------
    # Load dataset
    # ---------------------------------------------------------

    df = pd.read_csv(
        DATASET_PATH
    )

    print(
        f"Dataset: {df.shape[0]:,} samples"
    )

    print(
        f"Features: {len(FEATURE_COLUMNS)}"
    )

    X = df[
        FEATURE_COLUMNS
    ]

    y = df[
        "label"
    ].astype(int)

    # ---------------------------------------------------------
    # 70% TRAIN / 30% TEMP
    # ---------------------------------------------------------

    X_train, X_temp, y_train, y_temp = train_test_split(
        X,
        y,
        test_size=0.30,
        random_state=42,
        stratify=y,
    )

    # ---------------------------------------------------------
    # TEMP → 10% VALIDATION + 20% TEST
    #
    # 30% temp:
    #
    # 1/3 = 10% validation
    # 2/3 = 20% test
    # ---------------------------------------------------------

    X_val, X_test, y_val, y_test = train_test_split(
        X_temp,
        y_temp,
        test_size=(2 / 3),
        random_state=42,
        stratify=y_temp,
    )

    print(
        f"Training samples:   {len(X_train):,}"
    )

    print(
        f"Validation samples: {len(X_val):,}"
    )

    print(
        f"Testing samples:    {len(X_test):,}"
    )

    # ---------------------------------------------------------
    # LightGBM MODEL
    # ---------------------------------------------------------

    model = lgb.LGBMClassifier(
        n_estimators=1000,
        learning_rate=0.03,
        num_leaves=63,
        max_depth=-1,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
        verbosity=-1,
    )

    print("\nTraining LightGBM...")

    model.fit(
        X_train,
        y_train,
        eval_set=[
            (X_val, y_val)
        ],
        eval_metric="binary_logloss",
        callbacks=[
            lgb.early_stopping(
                stopping_rounds=75,
                verbose=False,
            )
        ],
    )

    print("Training complete.")

    if hasattr(
        model,
        "best_iteration_",
    ):
        print(
            f"Best iteration: {model.best_iteration_}"
        )

    # ---------------------------------------------------------
    # VALIDATION
    #
    # Used ONLY for threshold selection.
    # ---------------------------------------------------------

    val_probabilities = model.predict_proba(
        X_val
    )[:, 1]

    best_threshold, validation_accuracy = (
        find_best_accuracy_threshold(
            y_val,
            val_probabilities,
        )
    )

    print("\n" + "=" * 70)
    print("VALIDATION THRESHOLD SELECTION")
    print("=" * 70)

    print(
        f"Best threshold:      {best_threshold:.2f}"
    )

    print(
        f"Validation accuracy: {validation_accuracy:.4f}"
    )

    # ---------------------------------------------------------
    # FINAL TEST
    #
    # Completely untouched until this point.
    # ---------------------------------------------------------

    test_probabilities = model.predict_proba(
        X_test
    )[:, 1]

    # Default threshold = 0.5
    default_predictions = (
        test_probabilities >= 0.50
    ).astype(int)

    # Tuned threshold
    tuned_predictions = (
        test_probabilities >= best_threshold
    ).astype(int)

    # ---------------------------------------------------------
    # DEFAULT TEST METRICS
    # ---------------------------------------------------------

    default_accuracy = accuracy_score(
        y_test,
        default_predictions,
    )

    # ---------------------------------------------------------
    # TUNED TEST METRICS
    # ---------------------------------------------------------

    accuracy = accuracy_score(
        y_test,
        tuned_predictions,
    )

    precision = precision_score(
        y_test,
        tuned_predictions,
        zero_division=0,
    )

    recall = recall_score(
        y_test,
        tuned_predictions,
        zero_division=0,
    )

    f1 = f1_score(
        y_test,
        tuned_predictions,
        zero_division=0,
    )

    matrix = confusion_matrix(
        y_test,
        tuned_predictions,
    )

    # ---------------------------------------------------------
    # RESULTS
    # ---------------------------------------------------------

    print("\n" + "=" * 70)
    print("FINAL TEST RESULTS")
    print("=" * 70)

    print(
        f"Accuracy @ 0.50 threshold : "
        f"{default_accuracy:.4f}"
    )

    print(
        f"Accuracy @ tuned threshold: "
        f"{accuracy:.4f}"
    )

    print(
        f"Precision                 : "
        f"{precision:.4f}"
    )

    print(
        f"Recall                    : "
        f"{recall:.4f}"
    )

    print(
        f"F1 Score                  : "
        f"{f1:.4f}"
    )

    print("\nConfusion Matrix:")

    print(matrix)

    print("\nClassification Report:")

    print(
        classification_report(
            y_test,
            tuned_predictions,
            target_names=[
                "No Deforestation",
                "Deforestation",
            ],
            zero_division=0,
        )
    )

    # ---------------------------------------------------------
    # FEATURE IMPORTANCE
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
            f"  {feature:<20} "
            f"{importance:.4f}"
        )

    # ---------------------------------------------------------
    # SAVE MODEL
    # ---------------------------------------------------------

    os.makedirs(
        MODEL_DIR,
        exist_ok=True,
    )

    joblib.dump(
        {
            "model": model,
            "threshold": best_threshold,
        },
        MODEL_PATH,
    )

    # ---------------------------------------------------------
    # SAVE METRICS
    # ---------------------------------------------------------

    metrics = {
        "model": "LGBMClassifier",
        "random_state": 42,
        "best_iteration": int(
            getattr(
                model,
                "best_iteration_",
                0,
            )
        ),
        "decision_threshold": float(
            best_threshold
        ),
        "training_samples": int(
            len(X_train)
        ),
        "validation_samples": int(
            len(X_val)
        ),
        "testing_samples": int(
            len(X_test)
        ),
        "validation_accuracy": float(
            validation_accuracy
        ),
        "accuracy_default_threshold": float(
            default_accuracy
        ),
        "accuracy": float(
            accuracy
        ),
        "precision": float(
            precision
        ),
        "recall": float(
            recall
        ),
        "f1_score": float(
            f1
        ),
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

    # ---------------------------------------------------------
    # COMPLETE
    # ---------------------------------------------------------

    print("\n" + "=" * 70)
    print("LIGHTGBM MODEL SAVED")
    print("=" * 70)

    print(
        f"Model  : {MODEL_PATH}"
    )

    print(
        f"Metrics: {METRICS_PATH}"
    )


if __name__ == "__main__":
    main()