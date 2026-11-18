# Infrastructure

Terraform for the app's AWS hosting in Sydney (`ap-southeast-2`). The decisions behind it are in
[ADR 0005](../docs/adr/0005-lambda-over-ecs-fargate.md) (Lambda),
[0006](../docs/adr/0006-ipv6-egress-instead-of-nat.md) (IPv6 instead of NAT),
[0007](../docs/adr/0007-aurora-serverless-v2-with-auto-pause.md) (Aurora),
[0008](../docs/adr/0008-ssm-parameter-store-for-secrets.md) (secrets),
[0010](../docs/adr/0010-live-address-on-the-owners-own-domain.md) (the live address) and
[0012](../docs/adr/0012-drafts-on-sqs-with-a-lease-and-budget-holds.md) (drafts on SQS and the
budget).

The code is tested against a mocked provider. Nothing in this folder has been applied to AWS yet.

## What the app does on this stack

The app in `api/` is built for this stack. One image (built from `api/Dockerfile`) serves all three
Lambda functions, and the `APP_ROLE` setting picks what each one is.

- **Web Adapter.** The Lambda Web Adapter (version 1.1.0, pinned by digest) is copied into the
  image. It turns each Lambda event into an HTTP request to the server on port 8080.
- **Three roles from one image.**
  - `api` serves the public routes behind the HTTP API. It gets the database URL, the site URL, the
    Google client ID and secret, the bootstrap admin email, the queue URL and the daily draft limit.
  - `worker` reads the draft queue (`POST /events`, which only this role and `ops` serve). It gets
    the database URL, the site URL and the Anthropic key, and is the only function that can call
    the model. It writes the AI-spend metric. Its function lists `500-599` in
    `AWS_LWA_ERROR_STATUS_CODES`, so a 5xx fails the invocation and SQS delivers the message again.
    The API and ops functions do not: the API's 5xx must reach the browser, and the deploy reads
    the body of an ops 500.
  - `ops` is called only by a deploy, with a task (see "The ops function and the smoke check"). It
    gets the database URL, the site URL and the queue URL, and no Anthropic key.
- **Secrets.** A function is given the names of its parameters, as `<SETTING>_SSM_PARAMETER`
  settings (for example `DATABASE_URL_SSM_PARAMETER`), never the values. At cold start it reads each
  one once, with one `GetParameter` call per name (a batched `GetParameters` call is refused),
  through a dual-stack client. A missing parameter stops the start and names the setting, not a
  value.
- **The database can sleep.** The app uses SQLAlchemy's `NullPool` (no pooled connections to freeze
  and go stale) and a 20-second connect timeout. A connection that times out, or that Aurora refuses
  because it is still starting, answers 503 `database_waking` with `Retry-After: 5`, and the web app
  shows a waking screen. The worker tries to claim a job 3 times before it gives up and lets SQS
  deliver the message again.
- **Signed-out routes and `/api/v1/health` never touch the database** in demo and prod, so a crawler
  cannot keep a paused database awake. The ops function's `smoke` task checks the database instead.
- **The AI-spend metric.** After every job, including free replays, the worker prints one
  embedded-metric-format line: namespace `NursingAI`, metric `AiSpendUsd`, no dimensions. The worker
  role has no `cloudwatch:PutMetricData`, and any dimension would make the alarm match nothing.
- **Absolute URLs** (Google's sign-in callback, for one) are built from `SITE_URL`, which comes from
  the `site-url` parameter, never from the request's Host header. Behind CloudFront the API sees the
  execute-api host.
- **Drafts** go through SQS with a lease, under a budget that holds the worst case of each call
  first, as [ADR 0012](../docs/adr/0012-drafts-on-sqs-with-a-lease-and-budget-holds.md) explains.

## The ops function and the smoke check

The ops function runs inside the VPC, next to the database, so a deploy can reach what it cannot
reach from outside. Its `POST /events` takes `{"task": "..."}`:

| Task | What it does |
|---|---|
| `migrate` | Runs the database migrations. |
| `seed-demo` | Loads the synthetic demo data. Demo environment only; prod refuses it. |
| `smoke` | Checks every dependency, as below. |

It answers with JSON, `{"task": ..., "ok": true|false, "failed": [names]}`, and the deploy script
reads `ok`. `smoke` checks:

- The database, with `SELECT 1`. The database is exempt from the IPv6 rule because it is inside
  the VPC, not outbound.
- Google's discovery document, a TLS handshake with `api.anthropic.com`, and one cheap call each
  to SSM and SQS (through their `api.aws` dual-stack names). Each is checked **over IPv6 only**: a
  name with no IPv6 address, or a connection over IPv4, fails the check by name (see ADR 0006).

The ops function sits outside the brake (it is not one of the two roles the brake denies), so a
deploy in a braked month can still run `smoke` and say what is wrong.

## What is in each folder

| Folder | What it is |
|---|---|
| `bootstrap/` | Run once by hand. The Terraform state bucket, the GitHub sign-in (OIDC) and the two CI roles, the monthly budget, and the image registry. |
| `live/` | Everything the app runs on. CI applies it. It wires the modules below together. |
| `modules/network/` | VPC, two private dual-stack subnets, the IPv6 egress-only gateway, security groups. |
| `modules/aurora/` | The Aurora PostgreSQL cluster and the `database-url` parameter. |
| `modules/registry/` | The ECR image repository (keeps the newest 3 images). |
| `modules/compute/` | The API, worker and ops Lambda functions, the HTTP API, the job queue and its dead-letter queue. |
| `modules/web/` | The S3 bucket and CloudFront distribution for the web app. |
| `modules/ops/` | The four log groups (api, worker, ops and the HTTP API's access log), the three secret parameters, the `bootstrap-admin-email` and `site-url` parameters, the alarm topic and three alarms. |
| `modules/brake/` | The budget action that cuts the Lambda functions off from AWS at 100% of the budget. |
| `scripts/check.sh` | One command that runs every check. |

The deploy script is `scripts/deploy.sh` at the repository root, not in this folder.

No AWS account ID, email address or GitHub user name is written in the code. They come from
variables that have no default. Copy `terraform.tfvars.example` to `terraform.tfvars` (git-ignored)
in `bootstrap/` and in `live/`, and fill them in.

In `live/`, resource names come from `nursing-ai-<environment>`, for example `nursing-ai-demo`.
`bootstrap/` names its resources from `nursing-ai`, for example the `nursing-ai` image repository.

## Before you start

- An AWS account on a paid plan. A free-plan account only offers a limited Aurora option (outside
  your VPC, IPv4 only), which this design does not use (checked 2026-11-12).
- An AWS CLI profile named `nursing-ai` for the one-time bootstrap from your own PC.
- One environment per AWS account. Prod gets its own account, its own bootstrap and its own state
  bucket, because the state key, the account-wide `monthly-guard` budget, the brake and the
  AI-spend metric are all per account.
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
- **Deploys** run in the `production` environment and assume the `deploy` role. The only way to
  deploy is `scripts/deploy.sh` (see "Deploying"). It builds and pushes the image, migrates, applies
  `live`, seeds, smoke-tests, uploads the web app and checks the alarms. Do not run a bare
  `terraform apply` against a real environment: it would skip the migration, the smoke check and
  the guards, and without an `environment` setting it would apply the demo stack. No workflow runs
  the script yet. When one does, it runs in the `production` environment after its reviewer
  approves.
- `image_uri` has no default. Image tags are immutable, so every deploy uses a new tag.
- **Post-deploy IPv6 check.** The deploy runs the ops function's `smoke` task after each apply (see
  "The ops function and the smoke check").

## Deploying

`scripts/deploy.sh demo|prod` is the one command that deploys an environment. Run it from the
owner's PC with `DEPLOY_APPROVED=yes scripts/deploy.sh demo`. It is written so that a CI job in the
`production` environment can run the same line once its reviewer approves; no workflow calls it yet
(`make deploy` and the deploy workflow are not written).

It needs:

- `DEPLOY_APPROVED=yes`. Without it nothing runs: no build, no push, no apply.
- `STATE_BUCKET`, the state bucket (the `state_bucket_name` output of `bootstrap`).
- An AWS sign-in: a signed-in profile (`AWS_PROFILE`, also passed on to Terraform) or, in CI, the
  role the OIDC step assumed.
- Every Terraform variable but `image_uri`, as `TF_VAR_*` variables (for example
  `TF_VAR_alert_email` and `TF_VAR_domain_name`) or in the git-ignored `infra/live/terraform.tfvars`.
  The script sets `TF_VAR_environment` itself, and refuses a tfvars file that names another
  environment. A value in `terraform.tfvars` beats the same `TF_VAR_*` variable, so an uncommented
  `domain_validated` or `aws_profile` in that file wins over what you export.
- `docker`, `terraform`, `pnpm`, `python3`, `git` and the AWS CLI.

In order, it:

1. Runs `terraform init`, and decides whether this is the first deploy (the state has no ops
   function and Lambda says it does not exist). A state that belongs to another environment is
   refused before anything is built.
2. Builds the image once and pushes it to the registry. The tag is the 12-character git commit plus
   the UTC time, because tags are immutable.
3. Points the ops function at the new image, runs `migrate`, then runs `terraform apply` with that
   image. On the **first deploy** the ops function does not exist yet, so the apply comes first and
   the migration after it. The first apply is slow, because the functions wait for CloudFront.
4. In `demo` only, runs `seed-demo`.
5. Runs `smoke`. Any task whose answer is not `ok` stops the deploy.
6. Builds the web app and uploads it to S3. Every file except `index.html` gets a one-year
   `immutable` cache header (this includes the unhashed `fonts/` and `mockServiceWorker.js`).
   `index.html` gets `no-cache`, so a browser asks again before using it. Then it invalidates
   `/index.html` in CloudFront.
7. Checks the alarms: one in `ALARM`, or one watching the wrong HTTP API or queue, fails the
   deploy. One still in `INSUFFICIENT_DATA` (new alarms start there) prints a warning with its name.

The script itself makes no SSM or Secrets Manager call and never decrypts anything. (The apply it
runs refreshes the SSM parameters, which does decrypt them inside Terraform; nothing is printed.)
CI logs of this public repository are public, so:

- It prints the image tag, not the registry host, which holds the account ID.
- Every AWS CLI call that fails prints only the AWS error code (or "unknown AWS error"), never the
  raw message, which can carry the caller's ARN.
- The output of `terraform apply`, `terraform init` and the docker commands has every 12-digit
  number replaced, so an ARN's account ID is hidden.
- `alert_email`, `image_uri` and the `queue_url` output (an SQS URL holds the account ID) are
  `sensitive` in Terraform. The script still reads sensitive outputs with `terraform output -raw`.
- Once a custom domain is set, the apply's plan and outputs show it. That is the public address of
  the site, and CI deploys start only after it is live, so it is not hidden.

### A custom domain

The live site can use a subdomain of the owner's own domain, with its DNS on Cloudflare (see
[ADR 0010](../docs/adr/0010-live-address-on-the-owners-own-domain.md)). It takes two applies:

1. Set `TF_VAR_domain_name` (for example `app.example.com`) and deploy. This requests the
   certificate, in `us-east-1`.
2. Run `terraform output dns_records` in `infra/live/` and add both records in Cloudflare as
   **DNS only** (the grey cloud, not the orange one).
3. Set `TF_VAR_domain_validated=true` and deploy again. The functions read `site-url` at cold start,
   so the new address reaches them as that deploy restarts them.

To change `domain_name` later, set `domain_validated=false` first, apply, then do both steps again.
In Google's console, the live OAuth client needs the new origin's redirect,
`<site>/api/v1/auth/google/callback`, and the domain under Authorized domains.

## Filling the secrets

Terraform creates `/nursing-ai/<environment>/anthropic-api-key`, `google-client-id` and
`google-client-secret` as SecureString parameters with a placeholder value. It never reads them
back. You overwrite each one by hand. Read the value from a hidden prompt, so it is never typed on
the command line or kept in shell history:

```sh
read -rsp 'Value: ' VALUE; echo
aws ssm put-parameter --profile nursing-ai --region ap-southeast-2 \
  --name /nursing-ai/demo/anthropic-api-key \
  --type SecureString --overwrite --value "$VALUE"
unset VALUE
```

Repeat for `google-client-id`, `google-client-secret` and `bootstrap-admin-email` (also a
SecureString, the address of the first admin; its placeholder is `nobody@example.com`, so the app
starts before you set it; it must be exactly one email address, or every API cold start fails), with `prod` in the path for the prod environment.

Two parameters need no manual step. The database URL (`/nursing-ai/<environment>/database-url`) and
`site-url` (a plain `String`, the site's address, which Terraform writes) are written by Terraform.
Each Lambda function reads its parameters once at cold start (see "What the app does on this
stack"), so a new value reaches a running function after its next cold start.

Changing any setting of a write-only SSM parameter (the hand-set ones: the three secrets and
`bootstrap-admin-email`) other than its tags makes the next apply fail, because the provider sends
the write-only value only when the parameter's version changes. For these parameters, raising the version would overwrite the real value with the placeholder. So after
filling the secrets, run a plan and check that the parameters show no change, and never change
those resources' settings without filling the secrets in again afterwards.

On a prod environment, fill the prod secrets in the prod account (see "Before you start": one
environment per AWS account).

### Rotating or recovering the database password

The password is generated on each run and never stored in state. If an apply stops after the Aurora
cluster is created but before the `database-url` parameter is written, or the parameter is ever
recreated, the stored URL has a password the cluster never got. The app then cannot log in. Raise
the default of `database_password_version` by one in `infra/live/variables.tf`, in a reviewed pull
request (or set it in the deploy workflow), so that every apply sees the new value. The cluster and
the parameter both get the same new password. The same bump rotates the password on purpose. Never
lower the value: CI does not pass it, so a lower default would rotate the password again on the
next deploy and leave warm functions with a stale URL.

## Running the checks

```sh
make tools
infra/scripts/check.sh
```

`make tools` installs the pinned `tflint` and `trivy` into `.tools/bin` once.

It runs `terraform fmt -check`, `terraform init -backend=false`, `validate` and `test` in both
roots and every module, `tflint`, and `trivy config` for HIGH and CRITICAL findings. It also fails
if the code declares a NAT gateway, an internet gateway or an Elastic IP, or sets a plaintext
secret argument. A plaintext `value` is allowed only on a parameter whose type is `String`. The
secret scan reads heredocs, comments, strings and interpolations, and fails when it cannot follow a
file to its end. It needs no AWS sign-in, and it hides any AWS credentials from the commands it
runs. Allow a few minutes.

## The brake

The budget `monthly-guard` has a limit of $15 a month by default. It emails at $5, $10 and 100%
(actual) and at 100% (forecast). Credits are left out of the sum, so a month paid for by credits
still counts.

At 100% of actual spend, a budget action attaches a deny-everything policy
(`<name>-brake-deny-all`) to the API and worker Lambda roles. A deny beats every allow. The brake
role AWS Budgets runs as can attach and detach only that one policy, and only on those two roles.
That role's own policies are exclusive: its one inline policy is the only one it can have, and a
policy added to it by hand is removed on the next apply.

### Lifting the brake

Nothing lifts it at the start of a new month. Someone has to. After checking the bill, detach the
deny policy from the two Lambda roles (IAM, each role, Permissions, detach
`<name>-brake-deny-all`), or use Reverse on the action in the Budgets console. Once lifted, there is
no brake for the rest of that month, unless the action is Reset in the Budgets console.

### What the brake does not stop

The deny stops the functions' AWS API calls, such as SQS and SSM. It does not stop:

- Invocations through the HTTP API. They keep arriving and keep running.
- A password already in memory. A worker that is already running will keep the Anthropic key it has read
  at cold start until it ends. A warm API function can still log in to the database with the
  password it holds.

The faster fix is to set both functions' reserved concurrency to 0.

The compute module must never manage the Lambda roles' policy attachments exclusively (no
`aws_iam_role_policy_attachments_exclusive` on them). An apply would then detach the brake's deny
policy.

## After the first real apply

The mocked tests cannot prove the alarm wiring. The deploy checks that the 5xx alarm watches the
HTTP API and the dead-jobs alarm watches the dead-letter queue, and the state of all three
alarms, but open CloudWatch too and check:

- Each alarm shows OK, not INSUFFICIENT_DATA for days.
- The 5xx alarm's `ApiId` dimension is the HTTP API's ID.
- The dead-letter alarm's `QueueName` dimension is the dead-letter queue's name.
- The `AiSpendUsd` metric (namespace `NursingAI`) appears only after the first live job, so the AI
  spend alarm has no data until then. Once a job has run, confirm the line really reaches
  CloudWatch as a metric. The worker's `log_format` is JSON, and a wrapped line would leave the
  alarm without data.
- A worker 5xx fails its invocation, and SQS delivers the message again. The worker lists
  `500-599` in `AWS_LWA_ERROR_STATUS_CODES`; without it the adapter reports the 5xx as a success
  and SQS deletes the message. Check the worker function's configuration, and watch a message's
  receive count rise after a forced failure.
- An ops invoke returns its JSON body as the payload even when the task fails. The deploy reads
  `ok` from it.

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
| `compute` | 50,000 HTTP API requests at $1.29 per million. Lambda (the API, worker and ops functions; a deploy invokes the ops function a few times) and SQS are inside the free amounts. | about $0.06 |
| `web` | CloudFront is inside the free 1 TB and 10 million requests. The S3 bucket holds a web build of a few MB; S3 and CloudFront Function prices were not read. | Close to $0 |
| `ops` | Three alarms (10 are free), SNS email, four log groups (API, worker, ops and API access log; 5 GB a month free). Standard SSM parameters, including `site-url` and `bootstrap-admin-email`, are free. | $0 |
| certificate | The public ACM certificate for a custom domain is free. | $0 |
| domain | No AWS cost: the domain is the owner's own, with its DNS on Cloudflare, and there is no Route 53 zone. | $0 on AWS |
| `brake` | A budget action (the first two are free), one IAM policy and role. | $0 |
| **Total** | | **about $3 to $7** |

The rows add up to a little under the total. It is rounded up to cover the lines that were not
priced: S3 storage, Aurora backup and I/O.

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
- The owner's domain name, if you use one, is a yearly fee paid outside AWS and outside this table.

Budget data can arrive hours late. Because Aurora is capped at 1 ACU, 12 hours of delay adds at
most about $2.40 of database capacity.
