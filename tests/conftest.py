"""Shared pytest fixtures.

Auth in this app is Supabase-Auth-only (the frontend calls
supabase.auth.signInWithPassword/signUp directly; the backend never issues
its own login tokens). dashboard_server.DashboardHandler.get_auth_payload()
verifies the Bearer token via supabase_client.verify_supabase_jwt() and
trusts whatever {"sub", "email", "role"} dict it returns.

mock_auth patches that one function with an in-memory token->payload store,
so tests can mint arbitrary (email, role) tokens without hitting real
Supabase or a local password DB.
"""
from __future__ import annotations

import uuid

import pytest


class _AuthMinter:
    def __init__(self, tokens: dict):
        self._tokens = tokens

    def mint(self, email: str, role: str = "user", sub: str | None = None) -> str:
        """Return a bearer token that get_auth_payload() will accept as this
        (email, role) identity. role should be "admin" or "user" directly
        (not the Supabase "authenticated" claim) -- get_auth_role() passes
        through any role that isn't literally "authenticated" unchanged.
        """
        token = str(uuid.uuid4())
        self._tokens[token] = {"sub": sub or str(uuid.uuid4()), "email": email, "role": role}
        return token

    def headers(self, email: str, role: str = "user", sub: str | None = None) -> dict:
        return {"Authorization": f"Bearer {self.mint(email, role, sub)}"}


@pytest.fixture
def mock_auth(monkeypatch):
    import supabase_client

    tokens: dict = {}
    monkeypatch.setattr(supabase_client, "verify_supabase_jwt", lambda token: tokens.get(token))
    return _AuthMinter(tokens)
