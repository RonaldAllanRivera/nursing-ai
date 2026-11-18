# 10. The live address is a subdomain of the owner's own domain

Date: 2026-11-18

## Status

Accepted

## Context

The app needs one public address. CloudFront gives every distribution a free name ending in
`cloudfront.net`, so the app would work without any domain at all. Two things make that name a poor
choice for the live site:

- **Google sign-in.** The app signs users in with Google. Google lets a live OAuth client (one not
  in testing) redirect only to domains listed under Authorized domains, and it wants each domain
  verified as owned by the project. A `cloudfront.net` name belongs to Amazon, not to the owner, so
  it cannot be verified and the redirect address would be refused.
- **A name that stays put.** The CloudFront name is made when the distribution is created. If the
  distribution is ever rebuilt the name changes, and every saved link and the Google settings
  would change with it.

The owner already has a domain, with its DNS on Cloudflare. The questions were where the live name
should come from, and whether AWS should take over the DNS for it.

## Decision

**The live site is a subdomain of the owner's own domain, and its DNS stays on Cloudflare.**

- **No Route 53 zone.** AWS never holds the domain's DNS. Terraform makes no DNS records. It prints
  the two records to add, in the `dns_records` output: the certificate's validation CNAME and the
  site's own CNAME to the CloudFront name.
- **The certificate is in `us-east-1`.** CloudFront reads certificates only from that region, so
  the certificate is made there, in the live root (not in the web module, which could then not be
  validated on its own). Public ACM certificates cost nothing.
- **Two applies, because DNS is outside AWS.** ACM cannot confirm the validation record until it
  exists in DNS, and an apply that waited for a record nobody had added yet would hang. So:
  1. Set `TF_VAR_domain_name` and apply. This only requests the certificate.
  2. Run `terraform output dns_records` and add both records in Cloudflare as **DNS only** (the
     grey cloud). A proxied record would hide the validation record and put Cloudflare in front
     of CloudFront.
  3. Set `TF_VAR_domain_validated=true` and apply again. This waits for the certificate, gives
     CloudFront the alias and the certificate (SNI only, TLS 1.2 or newer), and changes the
     `site-url` parameter to `https://<domain_name>`.
- **The functions read `site-url` at cold start,** so the new address reaches them after the next
  deploy restarts them. The app builds every absolute URL, Google's callback included, from that
  setting, never from the request's Host header.
- **Changing the domain later** needs `domain_validated=false` first, so that the old alias and
  certificate are released, and then both applies again with the new name.
- **Google's side.** The live OAuth client needs the new origin's redirect
  (`<site>/api/v1/auth/google/callback`) and the domain under Authorized domains.
- **The name stays out of the repository.** It is read from `TF_VAR_domain_name` (or the
  git-ignored `terraform.tfvars`). The code, the docs and the tests say "a subdomain of the owner's
  own domain" and use `example.com` in examples. With no domain set, the stack still works on its
  `cloudfront.net` name; that is the default.

## Consequences

- **Google sign-in works on the live site,** on an address the owner can verify and keep.
- **No AWS cost.** The domain is paid for outside AWS, the certificate is free and there is no
  hosted zone (which would cost $0.50 a month).
- **Two manual DNS steps and a second apply.** It is a one-time cost, but a deploy between the two
  applies serves the CloudFront name, and a changed name means repeating the steps.
- **The certificate renews by itself only while its validation record stays.** Deleting that
  CNAME in Cloudflare later stops ACM renewing the certificate.
- **Cloudflare's own proxy is not used.** The records are DNS only, so Cloudflare's caching and
  firewall do not sit in front of the app; CloudFront does that job.

## Alternatives considered

- **The `cloudfront.net` name.** Free and no steps, but Google would not accept it for a live
  sign-in client. Kept as the default when no domain is set (local checks, a bare demo).
- **Move the domain's DNS to Route 53.** One apply, with Terraform adding the records itself. It
  costs $0.50 a month and either moves all of the owner's DNS to AWS or needs a separate zone for
  the subdomain with its own delegation. Not worth it for two records.
- **Cloudflare's proxy (orange cloud) in front of CloudFront.** Adds a second CDN and a second
  place for TLS and caching rules to disagree, and hides the ACM validation record.
- **A Terraform Cloudflare provider.** Would automate the two records and allow one apply. It adds
  a provider and a Cloudflare API token to the deploy's secrets, for a step done once.
