"""The Google OpenID Connect port. The auth lane implements it with Authlib; tests use a local
fake that signs ID tokens, so no test ever reaches Google."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class GoogleIdentity(BaseModel):
    """Who Google says signed in, from a verified ID token."""

    model_config = ConfigDict(frozen=True)

    sub: str  # Google's stable id for the account, bound at the first sign-in
    email: str
    email_verified: bool
    name: str | None


class GoogleOidc(Protocol):
    def authorization_url(
        self, *, state: str, nonce: str, code_challenge: str, redirect_uri: str
    ) -> str:
        """Google's sign-in address for this browser (PKCE S256, `prompt=select_account`)."""
        ...

    async def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        """The callback's code, swapped for an ID token."""
        ...

    async def verify_id_token(self, id_token: str, *, nonce: str) -> GoogleIdentity:
        """Checks Google's signature, `iss`, `aud`, `exp` and the nonce."""
        ...
