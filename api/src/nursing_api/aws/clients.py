"""boto3 clients for the Lambda VPC, which has IPv6 egress only.

Every client uses the dual-stack endpoints (`*.api.aws`), which resolve over IPv6, standard
retries and short timeouts. boto3 is synchronous: callers in async code run its calls through
`asyncio.to_thread`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

import boto3
from botocore.config import Config

if TYPE_CHECKING:  # the stubs are a dev dependency: never imported at run time
    from types_boto3_lambda import LambdaClient
    from types_boto3_sqs import SQSClient
    from types_boto3_ssm import SSMClient

# Short timeouts keep a hanging call well inside the API's 29 s (botocore's default is 60 s to
# connect, three attempts).
CONFIG = Config(
    use_dualstack_endpoint=True,
    retries={"mode": "standard"},
    connect_timeout=5,
    read_timeout=10,
)
# A send runs while a nurse waits for her request to answer: two attempts of at most 3 s to connect
# and 5 s to read, plus a short back-off, stay under 29 s (a lost send is re-sent by the poll).
SQS_CONFIG = Config(
    use_dualstack_endpoint=True,
    retries={"mode": "standard", "total_max_attempts": 2},
    connect_timeout=3,
    read_timeout=5,
)


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
        sqs: SQSClient = boto3.client("sqs", config=SQS_CONFIG)
        return sqs
    lam: LambdaClient = boto3.client("lambda", config=CONFIG)
    return lam
