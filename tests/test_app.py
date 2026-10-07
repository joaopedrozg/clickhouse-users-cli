"""Testes dos fluxos interativos com prompts simulados (sem console real)."""

from unittest.mock import MagicMock, patch

import pytest

from clickhouse_users_cli import app
from clickhouse_users_cli.i18n import set_language
from clickhouse_users_cli.sql_builder import GrantScope


@pytest.fixture(autouse=True)
def _lang():
    set_language("pt")
    yield
    set_language("pt")


def _patch_factories(monkeypatch, **answers):
    """Substitui os factories do questionary por retornos fixos."""
    for name, value in answers.items():
        monkeypatch.setattr(app.Q, name, MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", MagicMock(side_effect=lambda prompt: answers.get("__ask__")))


def test_ask_profile_questions_by_mode(monkeypatch):
    asked = {}

    def fake_select(msg, **kw):
        asked["q"] = msg
        return MagicMock()

    monkeypatch.setattr(app.Q, "select", fake_select)
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: "readonly")
    app.ask_profile()
    assert asked["q"] == "Que tipo de usuário criar?"
    app.ask_profile(mode="edit")
    assert asked["q"] == "Qual o novo tipo de acesso?"


def test_ask_profile_question_english(monkeypatch):
    set_language("en")
    monkeypatch.setattr(app.Q, "select", lambda msg, **kw: MagicMock())
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: "readonly")
    with patch.object(app, "step") as step:
        app.ask_profile()
        assert "User type" in step.call_args[0][0]


def test_ask_databases_all_and_partial(monkeypatch):
    admin = MagicMock()
    admin.list_databases.return_value = ["vendas", "system"]
    captured = {}

    def fake_checkbox(msg, choices, validate, style, qmark, instruction):
        captured["values"] = [c.value for c in choices]
        captured["checked"] = [c.checked for c in choices]
        return MagicMock()

    monkeypatch.setattr(app.Q, "checkbox", fake_checkbox)
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: ["__ALL__"])
    assert app.ask_databases(admin) == ["vendas", "system"]
    assert captured["values"][0] == "__ALL__"
    assert captured["checked"] == [False] * len(captured["values"])

    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: ["vendas"])
    assert app.ask_databases(admin) == ["vendas"]


def test_ask_tables_all_and_specific(monkeypatch):
    admin = MagicMock()
    admin.list_tables.return_value = ["pedidos", "clientes"]
    monkeypatch.setattr(app.Q, "checkbox", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: ["__ALL__"])
    scopes = app.ask_tables(admin, ["vendas"])
    assert scopes == [GrantScope(database="vendas", table=None)]
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: ["pedidos"])
    scopes = app.ask_tables(admin, ["vendas"])
    assert scopes == [GrantScope(database="vendas", table="pedidos")]


def test_ask_privileges_profiles():
    assert app.ask_privileges("readonly") == (["SHOW", "SELECT"], False)
    assert app.ask_privileges("admin") == (["ALL"], True)


def test_ask_privileges_custom(monkeypatch):
    monkeypatch.setattr(app.Q, "checkbox", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app.Q, "confirm", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", MagicMock(side_effect=[["SELECT"], False]))
    assert app.ask_privileges("custom") == (["SELECT"], False)


def test_flow_edit_grants_revokes_first(monkeypatch):
    admin = MagicMock()
    admin.conn.username = "default"
    monkeypatch.setattr(app, "ask_profile", lambda mode="create": "readwrite")
    monkeypatch.setattr(app, "ask_privileges", lambda profile, mode="create": (["SHOW", "SELECT"], False))
    monkeypatch.setattr(app, "ask_databases", lambda admin, mode="create": ["vendas"])
    monkeypatch.setattr(app, "ask_tables",
                         lambda admin, dbs, mode="create": [GrantScope(database="vendas", table="pedidos")])
    monkeypatch.setattr(app.Q, "confirm", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: True)
    app.flow_edit_grants(admin, "ana")
    stmts = admin.execute_statements.call_args[0][0]
    assert stmts[0] == "REVOKE ALL ON *.* FROM `ana`"
    assert stmts[1] == "GRANT SHOW, SELECT ON `vendas`.`pedidos` TO `ana`"


def test_flow_edit_grants_cancelled_runs_nothing(monkeypatch):
    admin = MagicMock()
    admin.conn.username = "default"
    monkeypatch.setattr(app, "ask_profile", lambda mode="create": "readonly")
    monkeypatch.setattr(app, "ask_privileges", lambda profile, mode="create": (["SHOW"], False))
    monkeypatch.setattr(app, "ask_databases", lambda admin, mode="create": ["vendas"])
    monkeypatch.setattr(app, "ask_tables",
                         lambda admin, dbs, mode="create": [GrantScope(database="vendas", table=None)])
    monkeypatch.setattr(app.Q, "confirm", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: False)
    app.flow_edit_grants(admin, "ana")
    admin.execute_statements.assert_not_called()


def test_maybe_load_without_file_returns_none(monkeypatch):
    monkeypatch.setattr("clickhouse_users_cli.session.has_saved_session", lambda: False)
    ask = MagicMock(side_effect=AssertionError("nao deveria perguntar"))
    monkeypatch.setattr(app, "_ask_or_abort", ask)
    assert app.maybe_load_saved_session() is None


def test_maybe_load_use_saved(monkeypatch):
    from clickhouse_users_cli.db import ConnectionInfo

    conn = ConnectionInfo(host="h", port=8123, secure=False, username="u", password="p")
    monkeypatch.setattr("clickhouse_users_cli.session.has_saved_session", lambda: True)
    monkeypatch.setattr("clickhouse_users_cli.session.load_session", lambda: conn)
    monkeypatch.setattr(app.Q, "select", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: "use")
    assert app.maybe_load_saved_session() is conn


def test_main_menu_forget_flag(monkeypatch):
    seen = {}

    def fake_select(msg, choices, default, style, qmark, instruction):
        seen["values"] = [c.value for c in choices]
        return MagicMock()

    monkeypatch.setattr(app.Q, "select", fake_select)
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: "exit")
    app.ask_main_action(show_forget=False)
    assert "forget" not in seen["values"]
    app.ask_main_action(show_forget=True)
    assert "forget" in seen["values"]
