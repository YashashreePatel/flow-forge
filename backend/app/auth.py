from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: set[str]
    tenant_id: str = "default"

    def can(self, role: str) -> bool:
        return "admin" in self.roles or role in self.roles


def _token_map() -> dict[str, Principal]:
    configured = os.getenv("FLOWFORGE_AUTH_TOKENS")
    if not configured:
        return {
            "dev-admin-token": Principal("dev-admin", {"admin"}, "default"),
            "dev-operator-token": Principal("dev-operator", {"operator"}, "default"),
            "dev-viewer-token": Principal("dev-viewer", {"viewer"}, "default"),
        }

    tokens: dict[str, Principal] = {}
    for item in configured.split(","):
        token, subject, roles, tenant = item.split(":", 3)
        tokens[token] = Principal(subject, set(roles.split("|")), tenant)
    return tokens


def current_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not authorization:
        return Principal("anonymous-dev", {"admin"}, "default")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization must use Bearer token format",
        )
    token = authorization.removeprefix(prefix)
    principal = _token_map().get(token)
    if not principal:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return principal


def require_role(role: str):
    def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not principal.can(role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return principal

    return dependency
