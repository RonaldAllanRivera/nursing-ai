"""The AI-spend metric: one CloudWatch embedded-metric-format line on stdout."""

import json
from decimal import Decimal

import pytest
from nursing_api.aws.metrics import emit_ai_spend


def test_ai_spend_metric_line_has_no_dimensions(capsys: pytest.CaptureFixture[str]) -> None:
    emit_ai_spend(Decimal("0.123456"))

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    line = json.loads(lines[0])
    declared = line["_aws"]
    assert isinstance(declared["Timestamp"], int)
    assert declared["CloudWatchMetrics"] == [
        {
            "Namespace": "NursingAI",
            "Dimensions": [[]],
            "Metrics": [{"Name": "AiSpendUsd", "Unit": "None"}],
        }
    ]
    assert line["AiSpendUsd"] == 0.123456
    assert set(line) == {"_aws", "AiSpendUsd"}


def test_a_free_replay_still_reports_zero(capsys: pytest.CaptureFixture[str]) -> None:
    emit_ai_spend(Decimal(0))

    assert json.loads(capsys.readouterr().out)["AiSpendUsd"] == 0.0
