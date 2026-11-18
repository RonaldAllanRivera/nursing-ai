# 12. Drafts on SQS with a lease, and budget holds

Date: 2026-11-18

## Status

Accepted

## Context

A draft takes the model tens of seconds, so the API does not wait for it. It saves the rough note,
creates a job row and answers at once; a worker drafts the note and the web app polls the job.
Locally (and in CI) the "queue" is a set of tasks inside the API process. On AWS it has to survive
a Lambda function freezing or dying, so the jobs go on Amazon SQS and a separate worker function
reads them.

SQS is **at-least-once**: the same message can arrive twice, and a worker can die half way. If
nothing is done about that:

- A job could run twice at the same time, or again after it finished, and the model would be paid
  for twice.
- A job whose worker died could stay "running" forever.

The second concern is money. The app has a monthly cap on AI spending. Checking "spent so far is
below the cap" before each call is racy: two workers can both check, both pass, and both spend.

## Decision

### Jobs: one claim, a lease, three attempts

- The job row is the source of truth. The SQS message carries only the job's id.
- **The claim is one conditional `UPDATE`.** It takes a job that is `queued`, or `running` with a
  claim older than the lease, and sets it to `running` with the time and one more attempt. If it
  changes no row, someone else has the job (or it is finished) and the worker does nothing.
- **The lease is 150 seconds, longer than the worker's 120-second timeout.** A worker that is
  still alive has been cut off by then, so a reclaim never overlaps a live run.
- **Three attempts.** The claim counts them. The fourth claim marks the job failed
  (`provider_error`) and runs nothing. This sits under the queue's `maxReceiveCount` of 5, so the
  app fails a job cleanly before SQS would send its message to the dead-letter queue.
- **When an outcome cannot be recorded** (the database is unreachable when the worker tries to mark
  the job done or failed) the worker answers 5xx. The Lambda Web Adapter turns a 5xx into a failed invocation only
  for the status codes listed in `AWS_LWA_ERROR_STATUS_CODES`, so the worker (and only the
  worker) lists `500-599`. SQS then delivers the message again after its visibility timeout
  (720 seconds, six times the worker's). By then the lease has run out and the next claim retries
  the job.
- **The in-process queue** (local, CI) runs at most 2 jobs at once, like the worker's concurrency
  of 2, and keeps the startup recovery after a restart: it fails the jobs a crash left `running` and
  runs the `queued` ones again. Lambda never does that recovery: a new worker starting up would
  fail a job another worker is still running.

### Budget: hold the worst case first

- Before each live model call the budget guard **takes a hold** for the worst-case cost of that
  call. The hold is taken in one transaction under a single `pg_advisory_xact_lock`, so holds are
  taken one at a time.
- Under the lock, one SQL statement reads this month's spend and the open holds together (one
  snapshot, so a hold turning into a usage row cannot be missed or counted twice). If spend plus
  holds plus the new hold is over the cap, the call is refused.
- The hold is **released in the same transaction that writes the usage row**, so money is never
  counted twice or not at all.
- **A hold expires after 15 minutes,** which frees the money of a crashed worker.
- Holds with no job (the tool that records replays) and holds of calls that failed without being
  billed stay until they expire. That errs on the side of spending less.
- **Personas get recorded replays,** never the live model, so they cost nothing and are never
  capped. **Invited users also get a daily draft limit,** counted and inserted in one transaction
  under a lock for that author, so two parallel requests cannot both slip in under the limit.

## Consequences

- **A job runs at most once at a time and at most three times in all,** and a stuck job ends as
  failed, not as "running".
- **The cap holds under concurrency.** Two workers cannot both spend the last dollar. The price is
  that a hold reserves more than a call usually costs, so the cap can refuse a call a little early.
- **One lock for all holds** is fine at two concurrent workers. It would be a bottleneck at much
  higher volume.
- **Known limits.**
  - An `/events` answer of 5xx before a job is claimed (for example the database is still waking)
    uses an SQS receive without counting an attempt. If the database sleeps through five
    deliveries, SQS moves the message to the dead-letter queue (the dead-letter alarm fires) while
    the job row is still `queued`.
  - A job can also be left `running` when its outcome cannot be saved and the redelivery
    never comes (for example the message already used its five receives). The lease lets the next
    delivery reclaim it, but nothing sends one.
  - If sending the SQS message fails after the job row has been saved (or the API times out
    first), the job stays `queued` and the startup recovery, which exists only in process, does
    not help. It recovers on the next replay of the same request or the next "try drafting again",
    which send the message again while the job is still `queued` (a duplicate message is a no-op,
    because the claim is conditional). Until then the note shows "drafting" and the job counts
    toward the daily cap. The clients' short timeouts (5 s to connect, 10 s to read) keep a
    hanging send well inside the API's 29 s.

## Alternatives considered

- **A visibility-timeout heartbeat,** where the worker keeps extending the message's invisibility
  while it runs. It would replace the lease, but needs the worker to call SQS during the draft
  (more permissions, more calls), and does not help when the database is what is wrong.
- **DynamoDB conditional writes for the claim.** Fine for claims, but jobs and notes live in
  Postgres: a second store adds cost and a second place where the two can disagree.
- **Step Functions** for the whole draft. Gives retries and state for free, but adds a service, a
  state machine to deploy and a per-transition cost, for one step with one retry rule.
- **A plain "is spend under the cap" check before the call.** Simple, and racy: parallel workers
  all pass the check and the month ends over the cap.
