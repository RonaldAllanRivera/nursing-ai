"""Google OpenID Connect with Authlib (the HTTP) and joserfc (the ID token).

`authorization_url` is plain string work and uses Google's documented endpoint. `exchange` and
`verify_id_token` use the discovery document's `token_endpoint` and `jwks_uri`, fetched the first
time they are needed and kept on the instance, with the keys. Google rotates its keys, so a token
whose signature check fails for any reason (a key we don't hold, or a bad signature alike) fetches
the key set again (at most once a minute) and is checked once more.

Authlib's httpx integration runs on `httpx2` here, so this module never imports `httpx`; a test
hands in an HTTP transport of that library instead of reaching Google. An ID token that fails
any check raises: nothing here is "mostly valid".
"""

import time
from collections.abc import Callable, Mapping
from contextlib import aclosing
from typing import Any, Protocol, cast
from urllib.parse import urlencode

from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from nursing_api.auth.oidc import GoogleIdentity

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
SCOPE = "openid email profile"
SIGNING_ALGORITHMS = ["RS256"]
KEY_REFRESH_SECONDS = 60
# Our clock and Google's may differ a little: `iat` and `exp` are judged within this much.
CLOCK_DRIFT_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10.0


class _Response(Protocol):
    """What this module reads of an HTTP answer (Authlib is untyped, so we name it)."""

    def raise_for_status(self) -> object: ...
    def json(self) -> Any: ...


class _Http(Protocol):
    """What this module uses of Authlib's async OAuth2 client."""

    async def request(self, method: str, url: str, *, withhold_token: bool) -> _Response: ...
    async def fetch_token(self, url: str, **params: str) -> Mapping[str, object]: ...
    async def aclose(self) -> None: ...


class InvalidIdToken(Exception):
    """The ID token failed a check (signature, issuer, audience, expiry, nonce or shape)."""


class AuthlibGoogleOidc:
    """The `GoogleOidc` port against the real Google (or, in a test, a stand-in transport)."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: object | None = None,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        self._now = now  # seconds since the epoch; None is the real time
        self._endpoints: tuple[str, str] | None = None  # (token_endpoint, jwks_uri)
        self._keys: KeySet | None = None
        self._keys_fetched_at = 0.0

    def _http(self) -> _Http:
        extra: dict[str, Any] = {"timeout": HTTP_TIMEOUT_SECONDS}
        if self._transport is not None:
            extra["transport"] = self._transport
        client = AsyncOAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            token_endpoint_auth_method="client_secret_post",  # noqa: S106
            **extra,
        )
        return cast("_Http", client)

    def authorization_url(
        self, *, state: str, nonce: str, code_challenge: str, redirect_uri: str
    ) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": SCOPE,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
        return f"{AUTHORIZATION_ENDPOINT}?{query}"

    async def _discover(self) -> tuple[str, str]:
        if self._endpoints is None:
            async with aclosing(self._http()) as http:
                response = await http.request("GET", DISCOVERY_URL, withhold_token=True)
            response.raise_for_status()
            document = cast("dict[str, Any]", response.json())
            self._endpoints = (str(document["token_endpoint"]), str(document["jwks_uri"]))
        return self._endpoints

    async def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        token_endpoint, _ = await self._discover()
        async with aclosing(self._http()) as http:
            token = await http.fetch_token(
                token_endpoint,
                grant_type="authorization_code",
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            )
        id_token = token.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise InvalidIdToken("Google's answer held no ID token")
        return id_token

    async def _key_set(self, *, refresh: bool = False) -> KeySet:
        due = time.monotonic() - self._keys_fetched_at >= KEY_REFRESH_SECONDS
        if self._keys is None or (refresh and due):
            _, jwks_uri = await self._discover()
            async with aclosing(self._http()) as http:
                response = await http.request("GET", jwks_uri, withhold_token=True)
            response.raise_for_status()
            self._keys = KeySet.import_key_set(response.json())
            self._keys_fetched_at = time.monotonic()
        return self._keys

    async def verify_id_token(self, id_token: str, *, nonce: str) -> GoogleIdentity:
        keys = await self._key_set()
        try:
            token = _decode(id_token, keys)
        except JoseError:
            # Perhaps Google rotated its keys since we fetched them: look once more, then decide.
            token = _decode(id_token, await self._key_set(refresh=True))
        claims = token.claims
        registry = jwt.JWTClaimsRegistry(
            now=self._now,
            leeway=CLOCK_DRIFT_SECONDS,
            iss={"essential": True, "values": ISSUERS},
            aud={"essential": True, "value": self._client_id},
            exp={"essential": True},
            sub={"essential": True},
            email={"essential": True},
            nonce={"essential": True, "value": nonce},
        )
        registry.validate(claims)  # raises joserfc's own error naming the claim that failed
        name = claims.get("name")
        return GoogleIdentity(
            sub=str(claims["sub"]),
            email=str(claims["email"]),
            email_verified=claims.get("email_verified") in (True, "true"),
            name=name if isinstance(name, str) and name.strip() else None,
        )


def _decode(id_token: str, keys: KeySet) -> jwt.Token:
    """The token with its signature checked against Google's published keys (RS256 only)."""
    return jwt.decode(id_token, keys, algorithms=SIGNING_ALGORITHMS)
