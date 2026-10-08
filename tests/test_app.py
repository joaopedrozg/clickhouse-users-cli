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
    admin.show_grants.return_value = ["GRANT SHOW, SELECT ON `vendas`.`pedidos` TO `ana`"]
    seen = {}
    monkeypatch.setattr(app, "ask_profile", lambda *a, **k: seen.setdefault("profile_kw", k) or "readwrite")
    monkeypatch.setattr(app, "ask_privileges", lambda *a, **k: (["SHOW", "SELECT"], False))
    monkeypatch.setattr(app, "ask_databases", lambda *a, **k: seen.setdefault("db_defaults", k.get("defaults")) or ["vendas"])
    monkeypatch.setattr(app, "ask_tables",
                         lambda *a, **k: seen.setdefault("scopes_defaults", k.get("defaults")) or [GrantScope(database="vendas", table="pedidos")])
    monkeypatch.setattr(app.Q, "confirm", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: True)
    app.flow_edit_grants(admin, "ana")
    stmts = admin.execute_statements.call_args[0][0]
    assert stmts[0] == "REVOKE ALL ON *.* FROM `ana`"
    assert stmts[1] == "GRANT SHOW, SELECT ON `vendas`.`pedidos` TO `ana`"
    # Pré-preenchimento: perfil inferido + escopos atuais repassados como padrão.
    assert seen["profile_kw"].get("default_profile") == "readonly"
    assert seen["db_defaults"] == ["vendas"]
    assert seen["scopes_defaults"] == [GrantScope(database="vendas", table="pedidos")]


def test_flow_edit_grants_cancelled_runs_nothing(monkeypatch):
    admin = MagicMock()
    admin.conn.username = "default"
    admin.show_grants.return_value = []
    monkeypatch.setattr(app, "ask_profile", lambda *a, **k: "readonly")
    monkeypatch.setattr(app, "ask_privileges", lambda *a, **k: (["SHOW"], False))
    monkeypatch.setattr(app, "ask_databases", lambda *a, **k: ["vendas"])
    monkeypatch.setattr(app, "ask_tables",
                         lambda *a, **k: [GrantScope(database="vendas", table=None)])
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


# ── Navegação "voltar" no fluxo de criação ────────────────────────────────────

def test_ask_profile_back_raises(monkeypatch):
    captured = {}

    def fake_select(msg, choices, default, style, qmark, instruction):
        captured["values"] = [c.value for c in choices]
        return MagicMock()

    monkeypatch.setattr(app.Q, "select", fake_select)
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: app.BACK_VALUE)
    with pytest.raises(app.BackStep):
        app.ask_profile(allow_back=True)
    assert app.BACK_VALUE in captured["values"]


def test_ask_profile_no_back_by_default(monkeypatch):
    captured = {}

    def fake_select(msg, choices, default, style, qmark, instruction):
        captured["values"] = [c.value for c in choices]
        return MagicMock()

    monkeypatch.setattr(app.Q, "select", fake_select)
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: "readonly")
    assert app.ask_profile() == "readonly"
    assert app.BACK_VALUE not in captured["values"]


def test_ask_databases_back_raises(monkeypatch):
    admin = MagicMock()
    admin.list_databases.return_value = ["vendas"]
    monkeypatch.setattr(app.Q, "checkbox", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: [app.BACK_VALUE])
    with pytest.raises(app.BackStep):
        app.ask_databases(admin, allow_back=True)


def test_ask_new_credentials_back_keyword(monkeypatch):
    monkeypatch.setattr(app.Q, "text", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: ":voltar")
    with pytest.raises(app.BackStep):
        app.ask_new_credentials(allow_back=True)


def test_ask_privileges_custom_back_raises(monkeypatch):
    monkeypatch.setattr(app.Q, "checkbox", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: [app.BACK_VALUE])
    with pytest.raises(app.BackStep):
        app.ask_privileges("custom", allow_back=True)


def test_ask_host_restriction_back_raises(monkeypatch):
    monkeypatch.setattr(app.Q, "select", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: app.BACK_VALUE)
    with pytest.raises(app.BackStep):
        app.ask_host_restriction(allow_back=True)


def test_confirm_and_execute_adjust_goes_back(monkeypatch):
    from clickhouse_users_cli.sql_builder import UserSpec

    spec = UserSpec(username="ana", password="x" * 9, privileges=["SELECT"],
                    scopes=[GrantScope(database="vendas", table=None)])
    monkeypatch.setattr(app.Q, "select", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(app, "_ask_or_abort", lambda prompt: "adjust")
    with pytest.raises(app.BackStep):
        app.confirm_and_execute(MagicMock(), spec, None, allow_back=True)


def test_flow_create_user_back_then_forward(monkeypatch):
    admin = MagicMock()
    monkeypatch.setattr(app, "ask_profile", lambda **kw: "readonly")
    monkeypatch.setattr(app, "ask_new_credentials", lambda **kw: ("ana", "pwd123456"))
    meta = MagicMock()
    meta.matricula = "123"
    meta.nome_completo = "Ana"
    meta.email_corporativo = "ana@empresa.com"
    meta.departamento_id = "dept-1"
    meta.departamento_nome = "Vendas"
    meta_calls = {"n": 0}

    def fake_meta(a, username, **kw):
        meta_calls["n"] += 1
        return meta

    monkeypatch.setattr(app, "ask_user_metadata", fake_meta)
    db_calls = {"n": 0}

    def fake_dbs(a, **kw):
        db_calls["n"] += 1
        if db_calls["n"] == 1:
            raise app.BackStep()
        return ["vendas"]

    monkeypatch.setattr(app, "ask_databases", fake_dbs)
    monkeypatch.setattr(app, "ask_tables", lambda *a, **kw: [GrantScope(database="vendas", table=None)])
    monkeypatch.setattr(app, "ask_privileges", lambda *a, **kw: (["SELECT"], False))
    monkeypatch.setattr(app, "ask_host_restriction", lambda **kw: [])
    monkeypatch.setattr(app, "ask_create_options", lambda **kw: True)
    finished = {}

    def fake_confirm(a, spec, m, **kw):
        finished["spec"] = spec

    monkeypatch.setattr(app, "confirm_and_execute", fake_confirm)
    app.flow_create_user(admin)
    # Voltou 1x (bancos → metadados) e refez: metadados perguntado 2x, fim ok.
    assert meta_calls["n"] == 2
    assert db_calls["n"] == 2
    assert finished["spec"].username == "ana"
