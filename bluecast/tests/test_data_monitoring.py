from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from bluecast.monitoring.data_monitoring import DataDrift


@pytest.fixture
def mock_logger():
    with patch("bluecast.general_utils.general_utils.logger") as mock:
        yield mock


def test_kolmogorov_smirnov_test(mock_logger):
    data_drift = DataDrift()

    # Generate sample data for testing
    data = pd.DataFrame({"col1": [1, 2, 3, 4], "col2": [5, 6, 7, 8]})
    new_data = pd.DataFrame({"col1": [1, 2, 3, 4], "col2": [9, 10, 11, 12]})

    # Test Kolmogorov-Smirnov test with no data drift
    data_drift.kolmogorov_smirnov_test(data, new_data, threshold=0.05)
    assert not any(data_drift.kolmogorov_smirnov_flags.values())
    mock_logger.assert_called_once_with(
        f"{datetime.utcnow()}: Start checking for data drift via Kolmogorov-Smirnov test."
    )


def test_population_stability_index(mock_logger):
    data_drift = DataDrift()

    # Generate sample data for testing
    data = pd.DataFrame({"col1": [1, 2, 3, 4], "col2": [5, 6, 7, 8]})
    new_data = pd.DataFrame({"col1": [1, 2, 3, 4], "col2": [9, 10, 11, 12]})

    # Test Population Stability Index with no data drift
    data_drift.population_stability_index(data, new_data)
    assert not any(data_drift.population_stability_index_flags.values())
    mock_logger.assert_called_once_with(
        f"{datetime.utcnow()}: Start checking for data drift via population stability index."
    )
