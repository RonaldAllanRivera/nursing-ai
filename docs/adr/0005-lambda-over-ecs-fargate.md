# 5. AWS Lambda instead of ECS Fargate

Date: 2026-11-13

## Status

Accepted

## Context

The app has two server parts. An HTTP API answers the web app. A worker turns a queued job into a
draft, which can take up to two minutes because it waits on an AI provider. Both are the same
Python code. Use is light and bursty: a few demo sessions a week, with long idle gaps.

We want the hosting bill to follow use. A demo that nobody opens should cost close to nothing. The
whole stack is meant to sit near a few dollars a month (see the cost table in `infra/README.md`).

## Decision

We build one container image and run it as two AWS Lambda functions, `<name>-api` and
`<name>-worker`.

- Both functions use the image through the Lambda Web Adapter. The adapter lets an ordinary web
  server on port 8080 run on Lambda without changes to the code.
- `APP_ROLE=api` makes the first function serve the public API. `APP_ROLE=worker` makes the second
  serve the `/events` route that the queue sends jobs to. The adapter is told to pass queue events
  to `/events` (`AWS_LWA_PASS_THROUGH_PATH`). The route exists only when `APP_ROLE=worker`, so the
  public API cannot serve it.
- The adapter checks that the server is ready by opening a TCP connection to port 8080. An HTTP
  readiness check would call a health route that pings the database, and every cold start would
  then wake the database.
- An HTTP API in front of the API function takes the web traffic. An SQS queue feeds the worker,
  with a batch size of 1 and a maximum concurrency of 2.
- Each function has its own IAM role. Only the worker can read the Anthropic key.

## Consequences

- Idle time costs nothing for compute. Lambda bills per request and per millisecond of run time,
  and the monthly free amounts (1 million requests and 400,000 GB-seconds) cover this stack.
  Prices read 2026-11-12, Sydney.
- There is no load balancer, no server to patch and no cluster to size.
- A cold start loads a container image, so the first request after a quiet period is slow. The web
  app shows a "waking" screen and retries.
- The API function has a 29-second timeout, which is the longest an HTTP API waits. Long work goes
  through the queue to the worker (a 120-second timeout by default).
- Both functions join the VPC to reach the database. That is why the network has no internet route
  except IPv6 (see ADR 0006).
- One image means one build, and both functions always run the same code. The cost is that the
  image carries what both roles need.
- The image is still a plain web server, so it runs the same way on a laptop or on any container
  host.

## Alternatives considered

- **ECS on Fargate.** A familiar container model with no cold start. But a Fargate service has no
  scale to zero: it keeps at least one task running, and billed, all day. An HTTP service also
  needs a load balancer, which is a second fixed hourly charge. Both are paid while nobody uses
  the app. That is the wrong shape for a demo that is idle most of the time.
- **Two separate images**, one per role. Each image could be smaller. We chose one image to keep a
  single build and to stop the two drifting apart.
- **A small EC2 instance** running the containers. Cheaper than Fargate when always on, but we
  would patch the host, and it still bills while idle.
