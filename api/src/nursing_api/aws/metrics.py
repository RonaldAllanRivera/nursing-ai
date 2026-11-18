"""The AI-spend metric, as a CloudWatch embedded-metric-format log line.

Lambda sends stdout to CloudWatch Logs, which turns this line into a metric: no API call, no
boto3 and no extra permission. No dimensions, so one metric covers every job.
"""

import json
import time
from decimal import Decimal

NAMESPACE = "NursingAI"
METRIC = "AiSpendUsd"


def emit_ai_spend(cost_usd: Decimal) -> None:
    """Prints one metric line: what one draft job cost (0 for a mock or replayed draft)."""
    line: dict[str, object] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [list[str]()],
                    "Metrics": [{"Name": METRIC, "Unit": "None"}],
                }
            ],
        },
        METRIC: float(cost_usd),
    }
    print(json.dumps(line), flush=True)
