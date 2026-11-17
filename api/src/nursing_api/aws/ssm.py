"""Secrets and the site address come from SSM Parameter Store, once, at cold start."""

from collections.abc import Mapping

from types_boto3_ssm import SSMClient

from nursing_api.aws.clients import dual_stack_client

SUFFIX = "_SSM_PARAMETER"


class SsmParameterError(RuntimeError):
    """A parameter could not be read. The text names the setting, never a value or AWS's message."""


def load_ssm_settings(
    environ: Mapping[str, str], client: SSMClient | None = None
) -> dict[str, str]:
    """Reads each `<NAME>_SSM_PARAMETER` (the parameter's name) and returns `{NAME: value}`.

    One `GetParameter` per name, with decryption: the roles refuse the batched call. With no such
    name in `environ` no client is made.
    """
    names = {
        key.removesuffix(SUFFIX): value
        for key, value in environ.items()
        if key.endswith(SUFFIX) and value
    }
    if not names:
        return {}
    ssm = client if client is not None else dual_stack_client("ssm")
    values: dict[str, str] = {}
    for setting, parameter in sorted(names.items()):
        try:
            response = ssm.get_parameter(Name=parameter, WithDecryption=True)
            value = response["Parameter"].get("Value")
            if value is None:
                raise LookupError("no value")
            values[setting] = value
        except Exception as error:
            raise SsmParameterError(
                f"{setting}: the SSM parameter could not be read ({type(error).__name__})"
            ) from None
    return values
