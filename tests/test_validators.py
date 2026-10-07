"""Testes dos validadores (mensagens em PT e EN)."""

from clickhouse_users_cli.i18n import set_language
from clickhouse_users_cli.validators import (
    validate_at_least_one,
    validate_host,
    validate_new_password,
    validate_port,
    validate_required,
    validate_username,
)


def test_required():
    set_language("pt")
    assert validate_required(" x ") is True
    assert validate_required("  ") != True


def test_host():
    set_language("pt")
    assert validate_host("localhost") is True
    assert validate_host("10.0.0.5") is True
    assert validate_host("db.empresa.com") is True
    assert validate_host("") == "Informe o host (ex.: localhost ou 10.0.0.5)."
    assert "inválido" in validate_host("??").lower()


def test_port():
    set_language("pt")
    assert validate_port("8123") is True
    assert "numérica" in validate_port("abc")
    assert "65535" in validate_port("99999")


def test_username():
    set_language("pt")
    assert validate_username("analyst_julho") is True
    assert "reservado" in validate_username("default")
    assert validate_username("1abc") != True


def test_password():
    set_language("en")
    assert validate_new_password("12345678") is True
    assert "Minimum 8" in validate_new_password("abc")
    assert "Maximum 128" in validate_new_password("x" * 129)
    set_language("pt")


def test_at_least_one():
    assert validate_at_least_one(["a"]) is True
    assert validate_at_least_one([]) != True
