"""boto3 clients for the Lambda VPC, which has IPv6 egress only.

Every client uses the dual-stack endpoints (`*.api.aws`), which resolve over IPv6, and standard
retries. boto3 is synchronous: callers in async code run its calls through `asyncio.to_thread`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

import boto3
from botocore.config import Config

if TYPE_CHECKING:  # the stubs are a dev dependency: never imported at run time
    from types_boto3_lambda import LambdaClient
    from types_boto3_sqs import SQSClient
    from types_boto3_ssm import SSMClient

CONFIG = Config(use_dualstack_endpoint=True, retries={"mode": "standard"})


@overload
def dual_stack_client(service: Literal["ssm"]) -> SSMClient: ...
@overload
def dual_stack_client(service: Literal["sqs"]) -> SQSClient: ...
@overload
def dual_stack_client(service: Literal["lambda"]) -> LambdaClient: ...
def dual_stack_client(
    service: Literal["ssm", "sqs", "lambda"],
) -> SSMClient | SQSClient | LambdaClient:
    """A client for `service` over the dual-stack endpoint. The region comes from boto3's usual
    resolution (`AWS_DEFAULT_REGION`, which Lambda sets)."""
    if service == "ssm":
        ssm: SSMClient = boto3.client("ssm", config=CONFIG)
        return ssm
    if service == "sqs":
        sqs: SQSClient = boto3.client("sqs", config=CONFIG)
        return sqs
    lam: LambdaClient = boto3.client("lambda", config=CONFIG)
    return lam
