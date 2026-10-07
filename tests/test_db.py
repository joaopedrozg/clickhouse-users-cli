"""Testes da camada ClickHouse com cliente falso (sem rede)."""

import sys
import types
from types import SimpleNamespace

import pytest

from clickhouse_users_cli.db import SYSTEM_DATABASES, ClickHouseAdmin, ConnectionInfo
from clickhouse_users_cli.i18n import set_language


@pytest.fixture(autouse=True)
def _lang():
    set_language("pt")
    yield


class FakeClient:
    def __init__(self):
        self.queries = []
        self.commands = []

    def query(self, sql):
        self.queries.append(sql)

        class R:
            pass

        r = R()
        if sql == "SHOW USERS":
            r.result_rows = [("default",), ("ana",)]
        elif sql.startswith("SHOW GRANTS FOR"):
            r.result_rows = [("GRANT SELECT ON db.t TO ana",)]
        elif sql.startswith("SHOW CREATE USER"):
            r.result_rows = [("CREATE USER ana HOST ANY",)]
        elif sql == "SHOW DATABASES":
            r.result_rows = [("vendas",), ("system",)]
        elif sql.startswith("SHOW TABLES FROM"):
            r.result_rows = [("pedidos",), ("clientes",)]
        else:
            r.result_rows = [("1",)]
        return r

    def command(self, sql):
        self.commands.append(sql)


def _admin():
    a = ClickHouseAdmin(ConnectionInfo(host="h", port=8123, secure=False,
                                       username="default", password=""))
    a._client = FakeClient()
    return a


def test_client_requires_connect():
    a = ClickHouseAdmin(ConnectionInfo(host="h", port=1, secure=False, username="u", password=""))
    with pytest.raises(RuntimeError):
        _ = a.client


def test_list_users_sorted():
    assert _admin().list_users() == ["ana", "default"]


def test_show_grants_escapes_ident():
    a = _admin()
    assert a.show_grants("ana") == ["GRANT SELECT ON db.t TO ana"]
    assert a.show_create_user("ana") == "CREATE USER ana HOST ANY"
    assert a.client.queries[-2].startswith("SHOW GRANTS FOR `ana`")


def test_databases_system_last():
    assert _admin().list_databases() == ["vendas", "system"]
    assert "system" in SYSTEM_DATABASES


def test_manage_commands():
    a = _admin()
    a.deactivate_user("ana")
    a.activate_user("ana")
    a.drop_user("ana")
    assert a.client.commands == [
        "ALTER USER `ana` HOST NONE",
        "ALTER USER `ana` HOST ANY",
        "DROP USER IF EXISTS `ana`",
    ]


def test_execute_statements_runs_all():
    a = _admin()
    a.execute_statements(["A", "B"])
    assert a.client.commands == ["A", "B"]


def test_connect_missing_dependency():
    monkeypatch_target = sys.modules.get("clickhouse_connect")
    sys.modules["clickhouse_connect"] = None  # força ImportError no import interno
    try:
        a = ClickHouseAdmin(ConnectionInfo(host="h", port=1, secure=False, username="u", password=""))
        with pytest.raises(RuntimeError, match="clickhouse-connect"):
            a.connect()
    finally:
        if monkeypatch_target is None:
            sys.modules.pop("clickhouse_connect", None)
        else:
            sys.modules["clickhouse_connect"] = monkeypatch_target


def test_connect_success_and_failure_wrap():
    mod = types.ModuleType("clickhouse_connect")

    def ok_client(**kw):
        return FakeClient()

    def boom_client(**kw):
        raise ConnectionError("refused")

    sys.modules["clickhouse_connect"] = mod
    try:
        mod.get_client = ok_client
        a = ClickHouseAdmin(ConnectionInfo(host="h", port=8123, secure=False, username="u", password=""))
        assert a.connect() is a
        mod.get_client = boom_client
        with pytest.raises(RuntimeError, match="Falha ao conectar"):
            a.connect()
    finally:
        sys.modules.pop("clickhouse_connect", None)
