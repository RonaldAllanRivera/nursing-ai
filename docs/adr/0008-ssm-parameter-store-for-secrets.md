# 8. SSM Parameter Store for secrets

Date: 2026-11-13

## Status

Accepted

## Context

The app has four secrets: the database URL, the Anthropic API key, and the Google sign-in client ID
and client secret. They must reach the Lambda functions, never sit in the repository, and stay out
of Terraform state, which is plain text.

AWS has two main places for them. Prices read 2026-11-12, Sydney:

- **SSM Parameter Store**, SecureString type, standard tier: no charge for storage.
- **Secrets Manager**: $0.40 per secret per month, plus $0.05 per 10,000 API calls.

AWS recommends Secrets Manager for credentials, and it offers automatic rotation. It also has
dual-stack endpoints, so this is a question of price and fit, not IPv6.

## Decision

All four secrets are SSM SecureString parameters under `/nursing-ai/<environment>/`:
`database-url`, `anthropic-api-key`, `google-client-id` and `google-client-secret`.

- Terraform writes the database URL in the same apply that creates the cluster, through a
  write-only argument. The password is an ephemeral value, so neither the URL nor the password
  reaches the state or the plan.
- The other three are created with a write-only placeholder. The operator then overwrites each
  with `aws ssm put-parameter --overwrite`, reading the value from a hidden prompt. Terraform never
  reads these values back. The check script refuses a plaintext `value`, `master_password` or
  `insecure_value` argument anywhere in the code.
- The Lambda functions get only the parameter names, as environment variables such as
  `ANTHROPIC_API_KEY_SSM_PARAMETER`. They never get a secret value in an environment variable,
  because those sit in state and in the console in plain text.
- Each function reads its secrets once, at cold start, and keeps them in memory. Each read is one
  decryption request, so the count stays inside the free allowance (20,000 a month, then $0.03 per
  10,000).
- IAM limits who can read what. Only the worker role can read the Anthropic key. Only the API role
  can read the Google settings and send to the queue.
- The parameters use the AWS-managed SSM key. It costs nothing and its key policy already allows
  callers in the account.

## Consequences

- Secrets cost $0 a month.
- A secret is never on a command line or in shell history if the operator uses the hidden prompt
  shown in `infra/README.md`.
- **No automatic rotation.** An RDS-managed Secrets Manager secret would rotate the password itself
  and could not drift from the cluster, at $0.40 a month per secret. Here, rotation is a manual
  step: raise `database_password_version` in the live root and apply. The cluster and the stored URL
  are both rewritten with the same new password. The same bump is the recovery if an apply stops
  after the cluster is created but before the URL is written, or if the parameter is ever
  recreated. If it is forgotten, the stored URL carries a password the cluster never got, and the
  app cannot log in.
- A rotated secret reaches a running function only after its next cold start.
- The read-only plan role used for pull requests is denied SecureString decryption. It must run
  `terraform plan -refresh=false`, because the AWS provider decrypts every parameter it refreshes
  (see `infra/README.md`).
- That plan role can still pull container images and read Lambda configuration. This is safe only
  while no secret is baked into an image or a Lambda environment variable.

## Alternatives considered

- **Secrets Manager.** Better rotation, and AWS's own recommendation for credentials. For four
  secrets it is $1.60 a month, a large share of a $3 to $7 stack, for rotation we do not use.
- **Lambda environment variables.** Free and simple, but the values sit in state and in the console.
- **Secrets in the container image.** They would be copied with every image and readable by anyone
  who can pull it.
