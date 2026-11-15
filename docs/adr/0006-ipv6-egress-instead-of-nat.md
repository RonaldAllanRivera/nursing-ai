# 6. IPv6 egress instead of a NAT gateway

Date: 2026-11-13

## Status

Accepted

## Context

The Lambda functions sit in private subnets so they can reach the database, which has no public
address. They also need to call services on the internet: the Anthropic API, Google sign-in, and
AWS's own SQS and SSM.

A private subnet has no way out by default. The usual fix is a NAT gateway. A NAT gateway bills
every hour it exists, whether or not traffic flows, and it needs a public IPv4 address, which AWS
also bills by the hour.

Prices read 2026-11-12, Sydney:

- NAT gateway: $0.059 an hour, plus $0.005 an hour for its IPv4 address ($3.65 a month). About
  $46.72 a month with no traffic at all.
- fck-nat, an open-source NAT that runs on a small EC2 server you manage: about $3 to $5 a month
  (an estimate, not a list price), plus the same $3.65 for the IPv4 address.
- An egress-only internet gateway for IPv6: no charge.

The whole stack is meant to cost a few dollars a month, so a $47 fixed line is out of the question.

## Decision

The VPC gets an IPv6 range, the subnets are dual-stack, and one egress-only internet gateway gives
them a one-way route to the internet over IPv6. There is no NAT gateway, no internet gateway and
no Elastic IP. The check script `infra/scripts/check.sh` fails if the code declares any of them.

An egress-only gateway lets a connection start inside the VPC and blocks any connection that
starts outside. Security groups allow outbound HTTPS to `::/0` and traffic to the database.

The rule that follows: **every outbound dependency must be reachable over IPv6.** With no IPv4
route, a destination that has only IPv4 cannot be reached. Checked 2026-11-12:

| Dependency | Reachable over IPv6 | How |
|---|---|---|
| Anthropic API | yes | its normal name |
| Google sign-in | yes | its normal names |
| SQS | yes, only through the dual-stack name | `sqs.ap-southeast-2.api.aws` |
| SSM Parameter Store | yes, only through the dual-stack name | `ssm.ap-southeast-2.api.aws` |

The usual `...amazonaws.com` names for SQS and SSM are IPv4-only. The application must ask the AWS
SDK for dual-stack endpoints, set per client, because a global setting breaks any service that has
no dual-stack name. Each Lambda function also turns on the VPC setting that lets a function use
IPv6 in dual-stack subnets (`ipv6_allowed_for_dual_stack`).

A post-deploy smoke test checks this rule. It calls each outbound dependency from inside the VPC
and passes only if each one answers over IPv6. It is listed in `infra/README.md`, and the deploy
workflow will run it after each apply. The test does not exist in the repository yet.

If a future dependency has no IPv6 address, the fallback is fck-nat. It would sit in a public
subnet and cost about $3 to $5 a month plus $3.65 for the address, and we would own its patching.

## Consequences

- The network has no fixed hourly cost. Data sent to the internet is billed per GB after the free
  allowance, as it would be with any route.
- Adding a service that has no IPv6 address is a design decision, not a one-line change.
- The app depends on dual-stack endpoint names. A client built without them fails to reach SQS or
  SSM, and the smoke test exists to catch that.
- A VPC function that goes unused for about 14 days can lose its network interface, and the next
  call is slow while a new one is made. The web app's retry screen covers this.
- The database is not reachable from the internet at all.

## Alternatives considered

- **A NAT gateway.** The simplest and most compatible choice, and it works with IPv4-only
  services. About $46.72 a month before any traffic, which is many times the whole target.
- **fck-nat.** Far cheaper than a NAT gateway, but it is a server we patch and watch, it is a
  single machine, and it still needs a billed IPv4 address. We keep it as the fallback.
- **Public subnets for the functions.** No NAT needed, but every function would need a public IPv4
  address (billed by the hour). It widens the attack surface for no gain.
- **VPC endpoints** for SQS and SSM. They fix AWS services only. They bill per hour, and the
  Anthropic API and Google would still need a way out.
