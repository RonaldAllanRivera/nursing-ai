"""The one image: the pinned Lambda Web Adapter, and the app on 8080 everywhere."""

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_dockerfile_copies_the_pinned_web_adapter_and_listens_on_8080() -> None:
    text = DOCKERFILE.read_text()
    final_stage = text.rsplit("\nFROM ", 1)[1]
    assert re.search(
        r"^COPY --from=public\.ecr\.aws/awsguru/aws-lambda-adapter:1\.1\.0@sha256:[0-9a-f]{64} "
        r"/lambda-adapter /opt/extensions/lambda-adapter$",
        final_stage,
        re.MULTILINE,
    )
    assert "EXPOSE 8080" in final_stage
    assert re.search(r'^CMD \[.*"--port", "8080"\]$', final_stage, re.MULTILINE)
