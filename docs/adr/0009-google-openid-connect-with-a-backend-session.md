# 9. Google OpenID Connect with a backend session

Date: 2026-11-17

## Status

Accepted

## Context

The app needs to know who is signing a nursing note. It starts as a public demo with made-up
nurses and may later serve one hospital ward, where only invited staff may get in. Three facts
shape the choice:

- Nurses already have Google accounts, and nobody wants a new password to forget.
- A signature on a clinical note must mean "this nurse, at this screen, now". Signing in once in
  the morning does not prove that.
- The ward computers are shared. A nurse walks away, the next one sits down, and the browser is
  still signed in to Google as the first.

The options for the sign-in itself were:

- **Amazon Cognito (a hosted user pool).** AWS runs the sign-in pages and holds the users, and
  Google is one of its identity providers. It brings a second user list that must be kept in sync
  with our invite list (who may get in, who was revoked), a paid service with its own pricing and
  limits, and a hosted flow that is harder to shape around our own PIN step and our own roles.
- **Tokens in the browser.** The web app signs in with Google directly and holds Google's ID or
  access token, sending it to the API on each call. It needs no server session, but any script
  that runs in the page, such as one injected through a cross-site scripting (XSS) hole, can read
  and send the token. The API must also check Google's token on every request, and a token cannot
  be taken back when someone is revoked.
- **Google OpenID Connect done by the backend, with our own server session.** The API sends the
  browser to Google, receives the answer itself, checks it, and then forgets Google's tokens. The
  browser only ever holds our session cookie.

## Decision

**The backend does the Google sign-in and keeps its own session.** The browser never sees a Google
token.

- **The API is the only party that sees tokens.** The browser goes to `GET /api/v1/auth/google/start`
  and comes back to the callback with a one-time code. The API exchanges it for the ID token, checks
  it and throws the tokens away. Nothing Google issued is stored in or sent to the page, so an XSS
  hole has no Google token to steal.
- **The session is a cookie.** It is httpOnly (scripts cannot read it) and `SameSite=Lax`, and
  Secure in the demo and in production. Each session also has its own random CSRF token, returned
  when the session is read. Every POST, PUT, PATCH and DELETE must send it back in a header, which
  is compared in constant time; a missing or wrong one is a 403 and a security event. The session
  lasts the facility's configured number of hours from sign-in, and an unlock never extends it.
- **The start route reads no database.** The auto-pausing database stays asleep when a crawler or
  a stray visitor opens the sign-in link. Every absolute URL, the callback included, comes from the
  configured site address, never from the `Host` header.
- **PKCE, state and nonce travel in one short cookie.** The start route makes a random state, nonce
  and PKCE verifier and puts them in `sl_oauth`: httpOnly, `SameSite=Lax`, limited to the callback's
  path, valid for ten minutes and signed with a key derived from the Google client secret, so a
  page on another site cannot plant an attempt of its own. The callback opens it, deletes it in the
  same answer, so it works once, and refuses a state that does not match. Google is asked with the
  S256 challenge and `prompt=select_account`.
- **The ID token is checked in full.** The signature against Google's published keys (fetched on
  first use and again, at most once a minute, when a token names a key we do not hold), then the
  issuer, the audience (our client), the expiry with a minute of allowed clock drift, the nonce, and
  that the email is verified. A token that fails any check is refused; nothing is "mostly valid".
- **Access is by invitation only.** An invite is a user row with an email, a role and a facility.
  The email is matched in lower case. A visitor who is not invited, was revoked, or has an
  unverified email gets a generic "no access" page and no session. At the first sign-in the row
  takes Google's `sub` (the account's permanent id) and Google's name; a later sign-in whose `sub`
  differs is refused. This stops a recycled or transferred email address from inheriting a nurse's
  account. A revoked row ends its sessions but is **kept**, because signed notes point at their
  author. Rows are never deleted. A bootstrap admin email becomes the admin at its first sign-in,
  and only while no active admin exists. Only the admin invites and revokes, and cannot revoke
  themselves. Demo personas never list, invite, revoke or reset anyone.

### The PIN, and why Google cannot force a fresh sign-in

On a shared ward computer a nurse's Google session outlives her shift. The obvious fix is to ask
Google to prove it is her again, with `prompt=login` or a `max_age` limit. We rejected that:

- It is not a reliable "it is still her" check. Google decides what to show, and a browser
  already holding the right account can pass with a click, or with a saved password.
- It costs a full trip to Google, with redirects, for every signature. A nurse signing five notes
  an hour would not accept it, and a check people avoid is no check.

So **our own six-digit PIN answers the question instead.** It is asked after every sign-in, to
unlock after the idle lock, on every signature, on every facility-settings save and on every
change to the staff list.

- A PIN is six ASCII digits. All-same digits and straight runs such as `123456` are refused. It is
  stored only as an Argon2id hash (the library's defaults), checked off the event loop, and never
  appears in a log line or in a response.
- **Five wrong tries lock a Google user's PIN** until a head nurse of the same facility, or the
  admin, resets it in person. The nurse then sets a new one at her next sign-in. The tries are
  counted claim-first in the database: a try is taken before the PIN is checked, so parallel
  guesses cannot get more than five checks, and a right guess racing the fifth wrong one cannot
  unlock a locked account.
- **Demo personas share one published PIN**, shown on the sign-in screen, because the demo has no
  secret to protect. Their wrong tries count per session, and the fifth ends only that session, so
  a visitor cannot lock the demo for the next one.

### The session gate is enforced by the server

One pure function decides a request's gate from the session and the user, first match wins:
`pin_locked`, `set_pin` (no PIN yet), `enter_pin` (not yet entered in this session),
`idle_locked` (no activity for the idle limit, five minutes by default), else `open`. Every data
route answers 423 with the gate as the problem code unless the gate is `open`. Reading the
session, setting the PIN, unlocking and signing out work at any gate.

A timer in the browser alone is not enough, because the browser is the part we do not trust: a
user, a script, or a second tab can ignore it and call the API directly. The lock a nurse sees is
a courtesy; the lock that counts is the 423.

Every open request refreshes the session's last-active time, with one exception: the web polls a
draft job while a note is written, and a poll is not a nurse at the screen. If it counted, a
walked-away ward PC would never lock.

## Consequences

- **No token in the browser.** An XSS hole can still act as the nurse while her page is open, but
  it cannot carry a Google token away, and CSRF tokens plus `SameSite=Lax` stop other sites from
  riding her session.
- **Simpler to run.** No user pool, no second user list to keep in sync with the invite list, no
  extra paid service. Revoking someone ends their sessions at once, which a token held in the
  browser could not do.
- **More code is ours.** The OAuth steps, the ID-token checks, the session table and the gate are
  all in the repository and need their own tests. The tests never call Google: they sign tokens
  with a local fake.
- **A shared ward PC is safer, not safe.** The idle lock and the PIN limit how long a walked-away
  screen can be used, and a signature always needs a fresh PIN. They do not stop a nurse who tells
  someone her PIN.
- **A sole admin who locks their own PIN has no way back.** A head nurse cannot reset an admin, and
  there is no email reset. Invite a second admin before relying on the app.
- **The live Google client is separate work.** The code is built and tested against the fake.
  Creating the real Google OAuth client, its redirect address and its secret in the parameter
  store is a deployment step, not part of this decision.
- **Later work.** Passkeys or a badge tap could replace the PIN for the "it is still her" check
  without changing the gate: the session would still go through `enter_pin`, with another way to
  answer it.
