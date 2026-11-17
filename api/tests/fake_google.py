"""A local stand-in for Google: no test reaches the network or the real Google.

`FakeGoogle` holds an RSA key made when the test starts. It answers the discovery document, the
key set and the token endpoint through a mock transport (of `httpx2`, the library Authlib's HTTP
client actually imports here), signing ID tokens with that key, so route tests run the real
verifier. `add_google_user` writes an invited Google-kind user through the table (the way
`helpers.sign_in` writes sessions), and `google_sign_in` drives the start and callback routes.
"""

import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import httpx2
from fastapi import FastAPI
from joserfc import jwt
from joserfc.jwk import RSAKey
from nursing_core.auth.pins import hash_pin
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from sqlalchemy import insert, select

CLIENT_ID = "test-client.apps.example.com"
CLIENT_SECRET = "test-client-secret"  # noqa: S105
SITE_URL = "http://app.example.com"
CALLBACK = "/api/v1/auth/google/callback"
START = "/api/v1/auth/google/start"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
ISSUER = "https://accounts.google.com"


@dataclass
class _Grant:
    claims: dict[str, Any]
    code_challenge: str | None
    key: RSAKey | None


class FakeGoogle:
    """Google's discovery document, keys and token endpoint, served from memory."""

    def __init__(self, client_id: str = CLIENT_ID) -> None:
        self.client_id = client_id
        self._key = RSAKey.generate_key(2048, auto_kid=True)
        self._grants: dict[str, _Grant] = {}
        self.requests: list[tuple[str, str]] = []  # (method, url) of every call, for assertions
        self.transport = httpx2.MockTransport(self._handle)

    def public_keys(self) -> dict[str, Any]:
        return {"keys": [self._key.as_dict(private=False)]}

    def sign(self, claims: dict[str, Any], *, key: RSAKey | None = None) -> str:
        use = key or self._key
        return jwt.encode({"alg": "RS256", "kid": use.kid}, claims, use)

    def foreign_key(self) -> RSAKey:
        """A key Google does not publish: a token signed with it must be refused."""
        return RSAKey.generate_key(2048, auto_kid=True)

    def grant(
        self,
        *,
        nonce: str,
        code_challenge: str | None,
        sub: str,
        email: str,
        email_verified: bool = True,
        name: str | None = "Test Person",
        aud: str | None = None,
        iss: str = ISSUER,
        expires_in: int = 3600,
        sign_with: RSAKey | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Registers a one-time code that the token endpoint swaps for a signed ID token."""
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": iss,
            "aud": aud or self.client_id,
            "sub": sub,
            "email": email,
            "email_verified": email_verified,
            "nonce": nonce,
            "iat": now,
            "exp": now + expires_in,
        }
        if name is not None:
            claims["name"] = name
        claims.update(extra or {})
        code = f"code-{uuid4().hex}"
        self._grants[code] = _Grant(claims, code_challenge, sign_with)
        return code

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.requests.append((request.method, url))
        if url == DISCOVERY_URL:
            return httpx2.Response(
                200,
                json={"issuer": ISSUER, "token_endpoint": TOKEN_URL, "jwks_uri": JWKS_URL},
            )
        if url == JWKS_URL:
            return httpx2.Response(200, json=self.public_keys())
        if url == TOKEN_URL and request.method == "POST":
            return self._token(request)
        raise AssertionError(f"the fake Google was asked for {request.method} {url}")

    def _token(self, request: httpx2.Request) -> httpx2.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        grant = self._grants.pop(form.get("code", ""), None)
        if grant is None or form.get("grant_type") != "authorization_code":
            return httpx2.Response(400, json={"error": "invalid_grant"})
        if grant.code_challenge is not None:
            verifier = form.get("code_verifier", "")
            expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            if expected.rstrip(b"=").decode() != grant.code_challenge:
                return httpx2.Response(400, json={"error": "invalid_grant"})
        token = self.sign(grant.claims, key=grant.key)
        return httpx2.Response(
            200, json={"access_token": "unused", "token_type": "Bearer", "id_token": token}
        )


async def google_sign_in(
    client: httpx.AsyncClient,
    google: FakeGoogle,
    *,
    email: str,
    sub: str = "sub-1",
    **grant: Any,
) -> httpx.Response:
    """Starts a sign-in on `client` and answers the callback as Google would: the callback's
    response (a redirect, not followed). `grant` overrides what the ID token says."""
    started = await client.get(START)
    assert started.status_code == 302, started.text
    query = parse_qs(urlsplit(started.headers["location"]).query)
    code = google.grant(
        nonce=grant.pop("nonce", query["nonce"][0]),
        code_challenge=query["code_challenge"][0],
        sub=sub,
        email=email,
        **grant,
    )
    return await client.get(CALLBACK, params={"code": code, "state": query["state"][0]})


async def add_google_user(
    app: FastAPI,
    email: str,
    role: Role,
    facility_key: str | None,
    *,
    pin: str | None = None,
    sub: str | None = None,
    name: str | None = None,
) -> UUID:
    """An invited Google-kind user, written through the table. `sub` None leaves it `invited`
    (never signed in); a value binds that Google account. Email addresses are example.com."""
    user_id = uuid4()
    async with app.state.engine.begin() as conn:
        facility_id = None
        if facility_key is not None:
            facility_id = await conn.scalar(
                select(tables.facility.c.id).where(tables.facility.c.key == facility_key)
            )
        await conn.execute(
            insert(tables.app_user).values(
                id=user_id,
                display_name=name or email,
                initials=(name or email)[:1].upper(),
                role=role.value,
                facility_id=facility_id,
                email=email.lower(),
                google_sub=sub,
                pin_hash=None if pin is None else hash_pin(pin),
            )
        )
    return user_id


def query_of(location: str) -> dict[str, str]:
    """The first value of each query parameter of a redirect's address."""
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
