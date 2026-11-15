# Infrastructure

Terraform for the app's AWS hosting in Sydney (`ap-southeast-2`). The decisions behind it are in
[ADR 0005](../docs/adr/0005-lambda-over-ecs-fargate.md) (Lambda),
[0006](../docs/adr/0006-ipv6-egress-instead-of-nat.md) (IPv6 instead of NAT),
[0007](../docs/adr/0007-aurora-serverless-v2-with-auto-pause.md) (Aurora) and
[0008](../docs/adr/0008-ssm-parameter-store-for-secrets.md) (secrets).

The code is tested against a mocked provider. Nothing in this folder has been applied to AWS yet.

## What is in each folder

| Folder | What it is |
|---|---|
| `bootstrap/` | Run once by hand. The Terraform state bucket, the GitHub sign-in (OIDC) and the two CI roles, the monthly budget, and the image registry. |
| `live/` | Everything the app runs on. CI applies it. It wires the modules below together. |
| `modules/network/` | VPC, two private dual-stack subnets, the IPv6 egress-only gateway, security groups. |
| `modules/aurora/` | The Aurora PostgreSQL cluster and the `database-url` parameter. |
| `modules/registry/` | The ECR image repository (keeps the newest 3 images). |
| `modules/compute/` | The API and worker Lambda functions, the HTTP API, the job queue and its dead-letter queue. |
| `modules/web/` | The S3 bucket and CloudFront distribution for the web app. |
| `modules/ops/` | Log groups, the three secret parameters, the alarm topic and three alarms. |
| `modules/brake/` | The budget action that cuts the Lambda functions off from AWS at 100% of the budget. |
| `scripts/check.sh` | One command that runs every check. |

No AWS account ID, email address or GitHub user name is written in the code. They come from
variables that have no default. Copy `terraform.tfvars.example` to `terraform.tfvars` (git-ignored)
in `bootstrap/` and in `live/`, and fill them in.

Resource names come from `nursing-ai-<environment>`, for example `nursing-ai-demo`.

## Before you start

- An AWS account on a paid plan. A free-plan account only offers a limited Aurora option (outside
  your VPC, IPv4 only), which this design does not use (checked 2026-11-12).
- An AWS CLI profile named `nursing-ai` for the one-time bootstrap from your own PC.
- Terraform 1.11 or newer. Both roots and every module pin the AWS provider to exactly 6.71.0.

## One-time bootstrap

The state bucket is created by the same code that stores its state in it, so the first apply uses
local state.

1. In `infra/bootstrap/`, create `backend_override.tf`. It is git-ignored. It swaps in the local
   backend:

   ```hcl
   terraform {
     backend "local" {}
   }
   ```

2. Run `terraform init`, then `terraform apply`. This creates the state bucket, the budget (an
   `import` block adopts the budget named `monthly-guard`, so make that budget in the console
   first), the image registry and, if
   `enable_github_oidc` is true, the OIDC provider and the CI roles.
3. Delete `backend_override.tf`.
4. Move the state into the new bucket. Read the bucket name from the `state_bucket_name` output.

   ```sh
   terraform init -migrate-state \
     -backend-config="bucket=<state-bucket>" \
     -backend-config="profile=nursing-ai"
   ```

   With the override still present this fails, because the local backend has no `bucket` setting.

5. Keep `enable_github_oidc = false` until the account can create OIDC providers. Then set it to
   `true`, set `github_repository = "<owner>/<repo>"` and apply again.

### GitHub settings Terraform does not make

The deploy role trusts only a job that runs in the `production` environment of your repository.
That is only safe if you set up two things in GitHub by hand:

- The `production` environment needs a required reviewer.
- The `production` environment needs a deployment-branch rule that allows `main` only.

## How CI applies `live`

- **Pull requests** assume the read-only `plan` role. The workflow must use the `pull_request`
  trigger, never `pull_request_target`, and run `terraform plan -refresh=false`. A pull request's
  plan runs that pull request's own code. So the plan role is denied SecureString decryption, S3
  objects outside the state bucket, log events, queue messages, RDS log downloads and Secrets
  Manager values. The AWS provider decrypts every SSM parameter it refreshes, so a refreshing plan
  would be refused. That is why the plan skips the refresh.
- The deny is a list on top of the `ReadOnlyAccess` policy. The plan role can still pull container
  images and read Lambda configuration. That is fine only while no secret is baked into an image or
  a Lambda environment variable. Secrets live in SSM SecureStrings.
- **Deploys** run in the `production` environment and assume the `deploy` role. CI builds the image,
  pushes it to the registry (the `repository_url` output of `bootstrap`), then applies `live`:

  ```sh
  cd infra/live
  terraform init -backend-config="bucket=<state-bucket>"
  terraform apply -var="image_uri=<registry-url>:<tag>" -var="alert_email=you@example.com"
  ```

  On a PC, also pass `-backend-config="profile=nursing-ai"` and `-var="aws_profile=nursing-ai"`.
- `image_uri` has no default. Image tags are immutable, so every deploy uses a new tag.
- **Post-deploy IPv6 check.** The deploy workflow will run a smoke test after each apply. It checks
  that each outbound dependency answers over IPv6 from inside the VPC: the Anthropic API, Google
  sign-in, and SQS and SSM through their `api.aws` dual-stack names (see ADR 0006). The test does
  not exist yet.

## Filling the secrets

Terraform creates `/nursing-ai/<environment>/anthropic-api-key`, `google-client-id` and
`google-client-secret` as SecureString parameters with a placeholder value. It never reads them
back. You overwrite each one by hand. Read the value from a hidden prompt, so it is never typed on
the command line or kept in shell history:

```sh
read -rs VALUE
aws ssm put-parameter --profile nursing-ai \
  --name /nursing-ai/demo/anthropic-api-key \
  --type SecureString --overwrite --value "$VALUE"
unset VALUE
```

Repeat for `google-client-id` and `google-client-secret`, with `prod` in the path for the prod
environment. The database URL (`/nursing-ai/<environment>/database-url`) is written by Terraform
and needs no manual step. Each Lambda function reads its secrets once at cold start, so a new
value reaches a running function after its next cold start.

### Rotating or recovering the database password

The password is generated on each run and never stored in state. If an apply stops after the Aurora
cluster is created but before the `database-url` parameter is written, or the parameter is ever
recreated, the stored URL has a password the cluster never got. The app then cannot log in. Raise
`database_password_version` by one in the next apply (`-var="database_password_version=2"`). The
cluster and the parameter both get the same new password. The same bump rotates the password on
purpose.

## Running the checks

```sh
infra/scripts/check.sh
```

It runs `terraform fmt -check`, `terraform init -backend=false`, `validate` and `test` in both
roots and every module, `tflint`, and `trivy config` for HIGH and CRITICAL findings. It also fails
if the code declares a NAT gateway, an internet gateway or an Elastic IP, or sets a plaintext
secret argument. It needs no AWS sign-in, and it hides any AWS credentials from the commands it
runs. Allow a few minutes.

## The brake

The budget `monthly-guard` has a limit of $15 a month by default. It emails at $5, $10 and 100%
(actual) and at 100% (forecast). Credits are left out of the sum, so a month paid for by credits
still counts.

At 100% of actual spend, a budget action attaches a deny-everything policy
(`<name>-brake-deny-all`) to the API and worker Lambda roles. A deny beats every allow. The brake
role AWS Budgets runs as can attach and detach only that one policy, and only on those two roles.

### Lifting the brake

Nothing lifts it at the start of a new month. Someone has to. After checking the bill, detach the
deny policy from the two Lambda roles (IAM, each role, Permissions, detach
`<name>-brake-deny-all`), or use Reverse on the action in the Budgets console. Once lifted, there is
no brake for the rest of that month, unless the action is Reset in the Budgets console.

### What the brake does not stop

The deny stops the functions' AWS API calls, such as SQS and SSM. It does not stop:

- Invocations through the HTTP API. They keep arriving and keep running.
- A password already in memory. A worker that is already running keeps the Anthropic key it read
  at cold start until it ends. A warm API function can still log in to the database with the
  password it holds.

The faster fix is to set both functions' reserved concurrency to 0.

The compute module must never manage the Lambda roles' policy attachments exclusively (no
`aws_iam_role_policy_attachments_exclusive` on them). An apply would then detach the brake's deny
policy.

## After the first real apply

The mocked tests cannot prove the alarm wiring. Open CloudWatch and check three things:

- Each alarm shows OK, not INSUFFICIENT_DATA for days.
- The 5xx alarm's `ApiId` dimension is the HTTP API's ID.
- The dead-letter alarm's `QueueName` dimension is the dead-letter queue's name.

Also confirm the alarm-topic email subscription and the budget emails (each must be accepted from
the link in its first email).

## Monthly cost

Prices read 2026-11-12, Sydney (`ap-southeast-2`), in US dollars. These are estimates for a demo
that is mostly idle, not a quote.

Assumptions:

- Aurora is awake 10 to 30 hours a month at up to 1 ACU ($0.20 per ACU-hour), about 1 GB of data
  ($0.11 per GB-month).
- 3 images of about 1 GB each in the registry ($0.10 per GB-month).
- About 50,000 HTTP API requests a month ($1.29 per million).
- Lambda, SQS, CloudFront, SNS and CloudWatch stay inside their monthly free amounts: Lambda 1
  million requests and 400,000 GB-seconds, SQS 1 million requests, CloudFront 1 TB and 10 million
  requests, SNS 1,000 emails, CloudWatch 10 alarms and 5 GB of logs. Logs are kept 14 days.
- New AWS accounts do not get a free allowance for Aurora, the HTTP API, ECR or S3 storage.
  Account credits, if you have any, are paid first.

| Module | What costs money | Per month |
|---|---|---|
| `bootstrap` | The state bucket, the budget and the OIDC roles. Budgets and IAM are free. S3 is billed per GB and the state is a few small files. | Close to $0 (S3 price not read) |
| `network` | VPC, subnets, security groups and the egress-only gateway are not billed. No NAT gateway, no public IPv4 address. | $0 |
| `aurora` | Capacity 10 to 30 hours at up to $0.20 an hour, plus about 1 GB storage at $0.11. Backup and I/O charges depend on use and were not priced here. | about $2 to $6 |
| `registry` | 3 images of about 1 GB at $0.10 per GB-month. | about $0.30 |
| `compute` | 50,000 HTTP API requests at $1.29 per million. Lambda and SQS are inside the free amounts. | about $0.06 |
| `web` | CloudFront is inside the free 1 TB and 10 million requests. The S3 bucket holds a web build of a few MB; S3 and CloudFront Function prices were not read. | Close to $0 |
| `ops` | Three alarms (10 are free), SNS email, three log groups (5 GB a month free). Standard SSM parameters are free. | $0 |
| `brake` | A budget action (the first two are free), one IAM policy and role. | $0 |
| **Total** | | **about $3 to $7** |

What moves the total:

- **Aurora is nearly all of it.** If one connection stays open, Aurora never pauses. At 1 ACU all
  month that is 730 hours at $0.20, close to $146. Check the Aurora ACU-hours on the bill: tens of
  hours is healthy, hours near 730 means it never paused.
- A NAT gateway would add about $46.72 a month ($0.059 an hour plus $3.65 for its IPv4 address).
  Any NAT gateway or public IPv4 line on the bill means someone added what ADR 0006 left out.
- Data sent to the internet is $0.114 per GB after the first 100 GB a month, and this app sends
  kilobytes per draft.
- Claude API usage is billed by Anthropic, not AWS. The app's own monthly cap limits it
  (`ai_monthly_cap_usd`).
- A domain name, if you add one, is a yearly fee outside this table.

Budget data can arrive hours late. Because Aurora is capped at 1 ACU, 12 hours of delay adds at
most about $2.40 of database capacity.
