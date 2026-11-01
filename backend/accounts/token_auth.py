# SPDX-License-Identifier: Apache-2.0
"""Bearer-token authentication for API clients (quickpoll fork: the MCP server).

`API_TOKENS` maps tokens to existing usernames: "token1=alice,token2=bob". A
request with `Authorization: Bearer <token>` acts as that user, through the same
permission checks as the SPA. A no-op while `API_TOKENS` is empty. Unlike
SessionAuthentication there is no CSRF check: the token itself is the proof.
"""
import hmac

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import authentication, exceptions


def parse_tokens(raw: str) -> dict[str, str]:
    """"t1=alice,t2=bob" -> {"t1": "alice", "t2": "bob"}; blank pairs are skipped."""
    tokens = {}
    for pair in raw.split(","):
        token, sep, username = pair.strip().partition("=")
        if sep and token.strip() and username.strip():
            tokens[token.strip()] = username.strip()
    return tokens


class ApiTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not settings.API_TOKENS or not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Invalid bearer header.")
        given = header[1].decode(errors="replace")
        username = next((u for t, u in settings.API_TOKENS.items() if hmac.compare_digest(t, given)), None)
        if username is None:
            raise exceptions.AuthenticationFailed("Invalid token.")
        user = get_user_model().objects.filter(username=username, is_active=True).first()
        if user is None:
            raise exceptions.AuthenticationFailed("The token's user does not exist.")
        return user, None

    def authenticate_header(self, request):
        return self.keyword
