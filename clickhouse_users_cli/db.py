"""Camada de acesso ao ClickHouse via clickhouse-connect."""

from __future__ import annotations

from dataclasses import dataclass

from clickhouse_users_cli.i18n import t


@dataclass
class ConnectionInfo:
    host: str
    port: int
    secure: bool
    username: str
    password: str

    @property
    def protocol(self) -> str:
        return "https" if self.secure else "http"


# Bancos internos que poluim a seleção — vão para o fim da lista, desmarcados.
SYSTEM_DATABASES = {"system", "information_schema", "INFORMATION_SCHEMA"}


class ClickHouseAdmin:
    def __init__(self, conn: ConnectionInfo):
        self.conn = conn
        self._client = None

    def connect(self):
        """Cria cliente e valida com SELECT 1. Levanta exceção com msg amigável."""
        try:
            from clickhouse_connect import get_client
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(t("db_no_dep")) from e

        try:
            self._client = get_client(
                host=self.conn.host,
                port=self.conn.port,
                username=self.conn.username,
                password=self.conn.password,
                secure=self.conn.secure,
            )
            self._client.query("SELECT 1")
        except Exception as e:
            raise RuntimeError(t("db_connect_fail", proto=self.conn.protocol, host=self.conn.host, port=self.conn.port, e=e)) from e
        return self

    @property
    def client(self):
        if self._client is None:
            raise RuntimeError(t("db_not_connected"))
        return self._client

    def list_databases(self) -> list[str]:
        rows = self.client.query("SHOW DATABASES").result_rows
        dbs = [r[0] for r in rows if r and r[0]]
        # UX: bancos de usuário primeiro (alfabético), sistema por último.
        user_dbs = sorted(d for d in dbs if d not in SYSTEM_DATABASES)
        sys_dbs = sorted(d for d in dbs if d in SYSTEM_DATABASES)
        return user_dbs + sys_dbs

    def list_tables(self, database: str) -> list[str]:
        # Escapa com backticks pois nome do banco vem do servidor, não do usuário.
        rows = self.client.query(f"SHOW TABLES FROM `{database}`").result_rows
        return sorted(r[0] for r in rows if r and r[0])

    def list_users(self) -> list[str]:
        rows = self.client.query("SHOW USERS").result_rows
        return sorted(r[0] for r in rows if r and r[0])

    def show_grants(self, username: str) -> list[str]:
        from clickhouse_users_cli.sql_builder import build_show_grants_sql

        rows = self.client.query(build_show_grants_sql(username)).result_rows
        return [r[0] for r in rows if r and r[0]]

    def show_create_user(self, username: str) -> str:
        from clickhouse_users_cli.sql_builder import build_show_create_user_sql

        rows = self.client.query(build_show_create_user_sql(username)).result_rows
        return rows[0][0] if rows and rows[0] else ""

    def deactivate_user(self, username: str) -> str:
        from clickhouse_users_cli.sql_builder import build_deactivate_user_sql

        sql = build_deactivate_user_sql(username)
        self.client.command(sql)
        return sql

    def activate_user(self, username: str) -> str:
        from clickhouse_users_cli.sql_builder import build_activate_user_sql

        sql = build_activate_user_sql(username)
        self.client.command(sql)
        return sql

    def drop_user(self, username: str) -> str:
        from clickhouse_users_cli.sql_builder import build_drop_user_sql

        sql = build_drop_user_sql(username)
        self.client.command(sql)
        return sql

    def execute_statements(self, statements: list[str]) -> None:
        for sql in statements:
            self.client.command(sql)
