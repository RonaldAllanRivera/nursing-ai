"""Secrets from SSM at cold start, through dual-stack clients. boto3 runs only behind a Stubber."""

import logging
from pathlib import Path
from typing import Any

import pytest
from botocore.stub import Stubber
from nursing_api.aws.clients import dual_stack_client
from nursing_api.aws.ssm import SsmParameterError, load_ssm_settings
from nursing_api.settings import Settings
from types_boto3_ssm import SSMClient

REGION = "ap-southeast-2"


@pytest.fixture(autouse=True)
def fake_aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fake credentials and an empty config, so boto3 never reads a real profile."""
    empty = tmp_path / "empty"
    empty.write_text("")
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(empty))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(empty))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


def ssm_with(*parameters: tuple[str, str]) -> tuple[SSMClient, Stubber]:
    client = dual_stack_client("ssm")
    stubber = Stubber(client)
    for name, value in parameters:
        stubber.add_response(
            "get_parameter",
            {"Parameter": {"Name": name, "Value": value}},
            {"Name": name, "WithDecryption": True},
        )
    stubber.activate()
    return client, stubber


def test_each_parameter_read_once_with_decryption() -> None:
    client, stubber = ssm_with(("/app/db", "db-value"), ("/app/site", "https://site.example.com"))
    environ = {
        "DATABASE_URL_SSM_PARAMETER": "/app/db",
        "SITE_URL_SSM_PARAMETER": "/app/site",
        "APP_ROLE": "api",
    }
    assert load_ssm_settings(environ, client) == {
        "DATABASE_URL": "db-value",
        "SITE_URL": "https://site.example.com",
    }
    stubber.assert_no_pending_responses()


def test_no_ssm_call_without_parameter_names(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(service: str) -> None:
        raise AssertionError("a client was made")

    monkeypatch.setattr("nursing_api.aws.ssm.dual_stack_client", refuse)
    assert load_ssm_settings({"APP_ROLE": "api", "DATABASE_URL": "x"}) == {}


def test_a_missing_parameter_names_the_setting_never_the_value() -> None:
    client = dual_stack_client("ssm")
    stubber = Stubber(client)
    stubber.add_client_error(
        "get_parameter",
        service_error_code="ParameterNotFound",
        service_message="secret-canary-message",
    )
    stubber.activate()
    with pytest.raises(SsmParameterError) as raised:
        load_ssm_settings({"DATABASE_URL_SSM_PARAMETER": "/app/db-canary-path"}, client)
    assert "DATABASE_URL" in str(raised.value)
    assert "secret-canary-message" not in str(raised.value)
    assert "db-canary-path" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def test_resolved_secret_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    secret = "postgresql+asyncpg://u:canary-secret@h/db"  # noqa: S105
    client, _ = ssm_with(
        ("/app/key", "sk-canary-key"), ("/app/db", secret)
    )  # read in setting order
    values = load_ssm_settings(
        {"DATABASE_URL_SSM_PARAMETER": "/app/db", "ANTHROPIC_API_KEY_SSM_PARAMETER": "/app/key"},
        client,
    )
    assert "canary" not in caplog.text
    settings = Settings(**{k.lower(): v for k, v in values.items()})  # pyright: ignore[reportArgumentType]
    assert "sk-canary-key" not in repr(settings)
    assert "sk-canary-key" not in str(settings)


def test_database_url_password_not_in_settings_repr() -> None:
    settings = Settings(database_url="postgresql+asyncpg://u:canary-secret@h/db")
    assert "canary-secret" not in repr(settings)
    assert "canary-secret" not in str(settings)


@pytest.mark.parametrize("service", ["ssm", "sqs"])
def test_clients_use_dual_stack_endpoints(service: str) -> None:
    client = dual_stack_client("ssm") if service == "ssm" else dual_stack_client("sqs")
    host = client.meta.endpoint_url.split("//", 1)[1]
    assert host.endswith(".api.aws")
    config: Any = client.meta.config  # botocore's stubs don't declare the Config attributes
    assert config.retries["mode"] == "standard"
    assert (config.connect_timeout, config.read_timeout) == (5, 10)
