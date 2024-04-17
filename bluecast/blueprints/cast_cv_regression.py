from typing import Any, List, Literal, Optional, Tuple, Union

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from bluecast.blueprints.cast_regression import BlueCastRegression
from bluecast.config.training_config import TrainingConfig, XgboostFinalParamConfig
from bluecast.config.training_config import (
    XgboostTuneParamsRegressionConfig as XgboostTuneParamsConfig,
)
from bluecast.conformal_prediction.conformal_prediction_regression import (
    ConformalPredictionRegressionWrapper,
)
from bluecast.experimentation.tracking import ExperimentTracker
from bluecast.general_utils.general_utils import logger
from bluecast.ml_modelling.xgboost import XgboostModel
from bluecast.preprocessing.custom import CustomPreprocessing
from bluecast.preprocessing.feature_selection import RFECVSelector


class BlueCastCVRegression:
    """Wrapper to train and predict multiple blueCast intstances.

    Check the BlueCast class documentation for additional parameter details.
    A custom splitter can be provided.
    """

    def __init__(
        self,
        class_problem: Literal["regression"] = "regression",
        stratifier: Optional[Any] = None,
        conf_training: Optional[TrainingConfig] = None,
        conf_xgboost: Optional[XgboostTuneParamsConfig] = None,
        conf_params_xgboost: Optional[XgboostFinalParamConfig] = None,
        experiment_tracker: Optional[ExperimentTracker] = None,
        custom_in_fold_preprocessor: Optional[CustomPreprocessing] = None,
        custom_last_mile_computation: Optional[CustomPreprocessing] = None,
        custom_preprocessor: Optional[CustomPreprocessing] = None,
        custom_feature_selector: Optional[
            Union[RFECVSelector, CustomPreprocessing]
        ] = None,
        ml_model: Optional[Union[XgboostModel, Any]] = None,
    ):
        self.class_problem = class_problem
        self.conf_xgboost = conf_xgboost
        self.conf_training = conf_training
        self.conf_params_xgboost = conf_params_xgboost
        self.custom_in_fold_preprocessor = custom_in_fold_preprocessor
        self.custom_preprocessor = custom_preprocessor
        self.custom_feature_selector = custom_feature_selector
        self.custom_last_mile_computation = custom_last_mile_computation
        self.bluecast_models: List[BlueCastRegression] = []
        self.stratifier = stratifier
        self.ml_model = ml_model
        self.conformal_prediction_wrapper: Optional[
            ConformalPredictionRegressionWrapper
        ] = None

        if experiment_tracker:
            self.experiment_tracker = experiment_tracker
        else:
            self.experiment_tracker = ExperimentTracker()

    def prepare_data(
        self, df: pd.DataFrame, target: str
    ) -> Tuple[pd.DataFrame, pd.Series]:
        df = df.reset_index(drop=True)
        y = df[target]
        X = df.drop(target, axis=1)
        return X, y

    def show_oof_scores(self, metric: str = "RMSE") -> Tuple[float, float]:
        """
        Show out of fold scores.

        When calling BlueCastCVRegression's fit_eval function multiple BlueCastRegression
        instances are called and each of them predicts on unseen/oof data.

        This function collects these scores and return mean and average of them.

        :param metric: String indicating which metric shall be returned.
        :return: Tuple with (mean, std) of oof scores
        """
        all_metrics = []
        for bluecast_instance in self.bluecast_models:
            if bluecast_instance.eval_metrics:
                score = bluecast_instance.eval_metrics.get(metric)
                all_metrics.append(score)

        score_mean = np.asarray(all_metrics).mean()
        score_std = np.asarray(all_metrics).std()
        message = f"The mean out of fold {metric} score is {score_mean} with an std of {score_std}"
        logger(message)

        return score_mean, score_std

    def fit(self, df: pd.DataFrame, target_col: str) -> None:
        """Fit multiple BlueCastRegression instances on different data splits.

        Input df is expected the target column."""
        X, y = self.prepare_data(df, target_col)

        if not self.conf_training:
            self.conf_training = TrainingConfig()

        if not self.stratifier:
            self.stratifier = KFold(
                n_splits=5,
                shuffle=True,
                random_state=self.conf_training.global_random_state,
            )

        for fn, (trn_idx, val_idx) in enumerate(self.stratifier.split(X, y)):
            X_train, X_val = X.iloc[trn_idx], X.iloc[val_idx]
            y_train, y_val = y.iloc[trn_idx], y.iloc[val_idx]
            x_train = pd.concat([X_train, X_val], ignore_index=True)
            y_train = pd.concat([y_train, y_val], ignore_index=True)

            X_train = x_train.reset_index(drop=True)
            y_train = y_train.reset_index(drop=True)
            X_train[target_col] = y_train.values

            self.conf_training.global_random_state += (
                self.conf_training.increase_random_state_in_bluecast_cv_by
            )
            logger(
                f"Start fitting model number {fn} with random seed {self.conf_training.global_random_state}"
            )

            automl = BlueCastRegression(
                class_problem=self.class_problem,
                conf_training=self.conf_training,
                conf_xgboost=self.conf_xgboost,
                conf_params_xgboost=self.conf_params_xgboost,
                experiment_tracker=self.experiment_tracker,
                custom_in_fold_preprocessor=self.custom_in_fold_preprocessor,
                custom_preprocessor=self.custom_preprocessor,
                custom_feature_selector=self.custom_feature_selector,
                custom_last_mile_computation=self.custom_last_mile_computation,
                ml_model=self.ml_model,
            )
            automl.fit(X_train, target_col=target_col)
            self.bluecast_models.append(automl)

            # overwrite experiment tracker to pass it into next iteration
            self.experiment_tracker = automl.experiment_tracker

    def fit_eval(self, df: pd.DataFrame, target_col: str) -> Tuple[float, float]:
        """Fit multiple BlueCastRegression instances on different data splits.

        Input df is expected the target column. Evaluation is executed on out-of-fold dataset
        in each split.
        :param df: Pandas DataFrame that includes the target column
        :param target_col: String indicating the name of the target column
        :returns Tuple of (oof_mean, oof_std) with scores on unseen data during eval
        """
        X, y = self.prepare_data(df, target_col)

        if not self.conf_training:
            self.conf_training = TrainingConfig()

        if not self.stratifier:
            self.stratifier = KFold(
                n_splits=5,
                shuffle=True,
                random_state=self.conf_training.global_random_state,
            )

        for fn, (trn_idx, val_idx) in enumerate(self.stratifier.split(X, y)):
            X_train, X_val = X.iloc[trn_idx], X.iloc[val_idx]
            y_train, y_val = y.iloc[trn_idx], y.iloc[val_idx]

            X_train.loc[:, target_col] = y_train

            self.conf_training.global_random_state += (
                self.conf_training.increase_random_state_in_bluecast_cv_by
            )
            logger(
                f"Start fitting model number {fn} with random seed {self.conf_training.global_random_state}"
            )

            automl = BlueCastRegression(
                class_problem=self.class_problem,
                conf_training=self.conf_training,
                conf_xgboost=self.conf_xgboost,
                conf_params_xgboost=self.conf_params_xgboost,
                experiment_tracker=self.experiment_tracker,
                custom_in_fold_preprocessor=self.custom_in_fold_preprocessor,
                custom_preprocessor=self.custom_preprocessor,
                custom_feature_selector=self.custom_feature_selector,
                custom_last_mile_computation=self.custom_last_mile_computation,
                ml_model=self.ml_model,
            )
            automl.fit_eval(X_train, X_val, y_val, target_col=target_col)
            self.bluecast_models.append(automl)

            # overwrite experiment tracker to pass it into next iteration
            self.experiment_tracker = automl.experiment_tracker

        oof_mean, oof_std = self.show_oof_scores()
        return oof_mean, oof_std

    def predict(
        self, df: pd.DataFrame, return_sub_models_preds: bool = False
    ) -> Union[pd.DataFrame, pd.Series]:
        """Predict on unseen data using multiple trained BlueCastRegression instances"""
        or_cols = df.columns
        pred_cols: list[str] = []
        result_df = pd.DataFrame()  # Create an empty DataFrame to store results

        for fn, pipeline in enumerate(self.bluecast_models):
            y_preds = pipeline.predict(df.loc[:, or_cols])
            result_df[f"preds_{fn}"] = y_preds
            pred_cols.append(f"preds_{fn}")

        if return_sub_models_preds:
            return result_df
        else:
            return result_df.mean(axis=1)

    def calibrate(
        self, x_calibration: pd.DataFrame, y_calibration: pd.Series, **kwargs
    ) -> None:
        self.conformal_prediction_wrapper = ConformalPredictionRegressionWrapper(
            self, **kwargs
        )
        self.conformal_prediction_wrapper.calibrate(x_calibration, y_calibration)

    def predict_interval(self, df: pd.DataFrame, alphas: List[float]) -> np.ndarray:
        if self.conformal_prediction_wrapper:
            pred_interval = self.conformal_prediction_wrapper.predict_interval(
                df, alphas=alphas
            )
            return pred_interval
        else:
            raise ValueError(
                """This instance has not been calibrated yet. Make use of calibrate to fit the
            ConformalPredictionWrapper."""
            )
