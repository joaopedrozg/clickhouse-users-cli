"""Validadores semânticos para cada tipo de input."""

from __future__ import annotations

import re

from clickhouse_users_cli.i18n import t

USERNAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
HOST_RE = re.compile(
    r"^([a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*|localhost|\d{1,3}(\.\d{1,3}){3})$"
)


def validate_required(value: str) -> bool | str:
    if value and value.strip():
        return True
    return t("v_required")


def validate_host(value: str) -> bool | str:
    if not value.strip():
        return t("v_host_empty")
    if not HOST_RE.match(value.strip()):
        return t("v_host_invalid")
    return True


def validate_port(value: str) -> bool | str:
    v = value.strip()
    if not v.isdigit():
        return t("v_port_nonnumeric")
    n = int(v)
    if not 1 <= n <= 65535:
        return t("v_port_range")
    return True


def validate_username(value: str) -> bool | str:
    v = value.strip()
    if not USERNAME_RE.match(v):
        return t("v_user_invalid")
    if v.lower() in {"default", "root", "admin", "system"}:
        return t("v_user_reserved", v=v)
    return True


def validate_new_password(value: str) -> bool | str:
    if len(value) < 8:
        return t("v_pass_short")
    if len(value) > 128:
        return t("v_pass_long")
    return True


def validate_at_least_one(selection: list) -> bool | str:
    if selection:
        return True
    return t("v_pick_one")
