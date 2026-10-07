"""Testes do construtor de SQL — puros, sem banco."""

import pytest

from clickhouse_users_cli.sql_builder import (
    GrantScope,
    UserSpec,
    build_activate_user_sql,
    build_all_statements,
    build_create_user_sql,
    build_deactivate_user_sql,
    build_drop_user_sql,
    build_edit_grants_statements,
    build_grant_sql,
    build_revoke_all_sql,
    build_show_create_user_sql,
    build_show_grants_sql,
    escape_host,
    escape_ident,
    escape_string,
)


def test_escape_ident():
    assert escape_ident("vendas") == "`vendas`"
    assert escape_ident("a`b") == "`a``b`"


def test_escape_string():
    assert escape_string("abc") == "'abc'"
    assert escape_string("o'b") == "'o\\'b'"
    assert escape_string("a\\b") == "'a\\\\b'"
    assert escape_host("10.0.0.5") == "'10.0.0.5'"


def test_on_clause():
    assert GrantScope(database="*").on_clause() == "*.*"
    assert GrantScope(database="vendas", table=None).on_clause() == "`vendas`.*"
    assert GrantScope(database="vendas", table="*").on_clause() == "`vendas`.*"
    assert GrantScope(database="vendas", table="pedidos").on_clause() == "`vendas`.`pedidos`"


def _spec(**kw):
    base = dict(username="ana", password="s3cret!!", privileges=["SHOW", "SELECT"],
                scopes=[GrantScope(database="vendas", table="pedidos")])
    base.update(kw)
    return UserSpec(**base)


def test_create_user_any_host():
    sql = build_create_user_sql(_spec())
    assert sql == ("CREATE USER IF NOT EXISTS `ana` IDENTIFIED WITH plaintext_password"
                   " BY 's3cret!!' HOST ANY")


def test_create_user_custom_hosts_and_no_ine():
    sql = build_create_user_sql(_spec(hosts=["LOCALHOST", "10.0.0.5"], if_not_exists=False))
    assert "IF NOT EXISTS" not in sql
    assert "HOST 'LOCALHOST', HOST '10.0.0.5'" in sql


def test_grant_sql_and_grant_option():
    stmts = build_grant_sql(_spec(scopes=[GrantScope(database="v", table=None)], grant_option=True))
    assert stmts == ["GRANT SHOW, SELECT ON `v`.* TO `ana` WITH GRANT OPTION"]


def test_grant_sql_validates():
    with pytest.raises(ValueError):
        build_grant_sql(_spec(scopes=[]))
    with pytest.raises(ValueError):
        build_grant_sql(_spec(privileges=[]))


def test_all_statements_order():
    stmts = build_all_statements(_spec())
    assert stmts[0].startswith("CREATE USER")
    assert stmts[1].startswith("GRANT")


def test_manage_statements():
    assert build_show_grants_sql("ana") == "SHOW GRANTS FOR `ana`"
    assert build_show_create_user_sql("ana") == "SHOW CREATE USER `ana`"
    assert build_deactivate_user_sql("ana") == "ALTER USER `ana` HOST NONE"
    assert build_activate_user_sql("ana") == "ALTER USER `ana` HOST ANY"
    assert build_drop_user_sql("ana") == "DROP USER IF EXISTS `ana`"
    assert build_drop_user_sql("ana", if_exists=False) == "DROP USER `ana`"
    assert build_revoke_all_sql("ana") == "REVOKE ALL ON *.* FROM `ana`"


def test_edit_grants_statements_revoke_first():
    stmts = build_edit_grants_statements("ana", ["SELECT"], [GrantScope(database="v", table="t")], False)
    assert stmts[0] == "REVOKE ALL ON *.* FROM `ana`"
    assert stmts[1] == "GRANT SELECT ON `v`.`t` TO `ana`"
