from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.baseline_deviation import (
    BaselineRule,
    MetricPoint,
    detect_baseline_deviations,
)


def rule(**changes):
    """Usa el rango de conexiones del piloto como configuración de prueba."""
    base = BaselineRule(
        company_id=1,
        source_id=2,
        resource_key="ManagedServer1",
        metric_name="jdbc_active_connections",
        unit="count",
        profile_code="NORMALITY-001",
        profile_version="1.0",
        series_key="{}",
        max_gap_seconds=90,
        lower_threshold=20,
        upper_threshold=55,
    )
    return replace(base, **changes)


def points(values, minutes=None):
    start = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)

    if minutes is None:
        minutes = range(len(values))

    return [
        MetricPoint(
            metric_id=index + 1,
            observed_at=start + timedelta(minutes=minute),
            value=value,
        )
        for index, (minute, value) in enumerate(zip(minutes, values))
    ]


def test_inclusive_normal_range():
    assert detect_baseline_deviations(
        points([20, 35, 55]), rule()
    ) == []


def test_groups_upper_deviation_and_preserves_evidence():
    result = detect_baseline_deviations(
        points([30, 56, 60, 40]), rule()
    )

    assert len(result) == 1
    evidence = result[0]

    assert evidence.comparison == "above_upper_threshold"
    assert evidence.threshold_value == 55
    assert evidence.metric_ids == (2, 3)
    assert evidence.sample_count == 2
    assert evidence.duration_seconds == 60
    assert evidence.min_observed == 56
    assert evidence.max_observed == 60
    assert evidence.company_id == 1
    assert evidence.source_id == 2


def test_separates_opposite_deviations():
    result = detect_baseline_deviations(points([10, 60]), rule())

    assert len(result) == 2
    assert result[0].comparison == "below_lower_threshold"
    assert result[1].comparison == "above_upper_threshold"


def test_gap_interrupts_group():
    result = detect_baseline_deviations(
        points([60, 61], minutes=[0, 5]), rule()
    )

    assert len(result) == 2
    assert all(item.duration_seconds == 0 for item in result)


def test_exact_maximum_gap_is_allowed():
    result = detect_baseline_deviations(
        points([60, 61]),
        rule(max_gap_seconds=60),
    )

    assert len(result) == 1
    assert result[0].sample_count == 2


def test_minimum_samples():
    result = detect_baseline_deviations(
        points([60, 40, 61, 62]),
        rule(min_samples=2),
    )

    assert len(result) == 1
    assert result[0].metric_ids == (3, 4)


def test_expected_numeric_value():
    result = detect_baseline_deviations(
        points([0, 1, 2, 0]),
        rule(lower_threshold=0, upper_threshold=0),
    )

    assert len(result) == 1
    assert result[0].metric_ids == (2, 3)


def test_sorts_input_and_keeps_final_deviation():
    result = detect_baseline_deviations(
        reversed(points([40, 60, 61])), rule()
    )

    assert len(result) == 1
    assert result[0].metric_ids == (2, 3)


def test_empty_input():
    assert detect_baseline_deviations([], rule()) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"lower_threshold": None, "upper_threshold": None},
        {"lower_threshold": 60, "upper_threshold": 55},
        {"upper_threshold": float("nan")},
        {"max_gap_seconds": 0},
        {"min_samples": 0},
    ],
)
def test_rejects_invalid_rule(changes):
    with pytest.raises(ValueError):
        detect_baseline_deviations([], rule(**changes))


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_rejects_nonfinite_samples(value):
    with pytest.raises(ValueError):
        detect_baseline_deviations(points([value]), rule())


def test_rejects_naive_timestamp():
    sample = MetricPoint(1, datetime(2026, 10, 26, 12), 60)

    with pytest.raises(ValueError, match="zona horaria"):
        detect_baseline_deviations([sample], rule())


def test_rejects_duplicate_metric_id():
    sample = points([60])[0]

    with pytest.raises(ValueError, match="duplicado"):
        detect_baseline_deviations([sample, sample], rule())


def test_rejects_ambiguous_same_timestamp():
    """Rechaza dos mediciones de la misma serie con igual fecha."""
    first = points([60])[0]
    second = replace(first, metric_id=2, value=40)

    with pytest.raises(ValueError, match="misma serie e instante"):
        detect_baseline_deviations([first, second], rule())