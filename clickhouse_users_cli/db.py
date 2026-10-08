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

    # ── Metadados (departamentos + user_metadata) ─────────────────────────

    def ensure_metadata_schema(self, db: str | None = None) -> str:
        from clickhouse_users_cli.sql_builder import (
            build_create_departments_table_sql,
            build_create_metadata_db_sql,
            build_create_user_metadata_table_sql,
            get_metadata_db,
        )

        meta_db = db or get_metadata_db()
        self.client.command(build_create_metadata_db_sql(meta_db))
        self.client.command(build_create_departments_table_sql(meta_db))
        self.client.command(build_create_user_metadata_table_sql(meta_db))
        return meta_db

    def list_departments(self, db: str | None = None) -> list[dict]:
        from clickhouse_users_cli.sql_builder import (
            DEPARTMENTS_TABLE,
            escape_ident,
            get_metadata_db,
        )

        meta_db = db or get_metadata_db()
        rows = self.client.query(
            f"SELECT `id`, `nome`, `descricao` FROM {escape_ident(meta_db)}.{escape_ident(DEPARTMENTS_TABLE)} ORDER BY `nome`"
        ).result_rows
        out: list[dict] = []
        for r in rows or []:
            if not r or len(r) < 2:
                continue
            out.append({"id": str(r[0]), "nome": str(r[1]), "descricao": str(r[2]) if len(r) > 2 else ""})
        return out

    def create_department(self, nome: str, descricao: str = "", dept_id: str | None = None, db: str | None = None) -> str:
        import uuid as _uuid

        from clickhouse_users_cli.sql_builder import build_insert_department_sql, get_metadata_db

        meta_db = db or get_metadata_db()
        dept_id = dept_id or str(_uuid.uuid4())
        self.client.command(build_insert_department_sql(dept_id, nome, descricao, meta_db))
        return dept_id

    def update_department(self, dept_id: str, nome: str, descricao: str = "", db: str | None = None) -> str:
        from clickhouse_users_cli.sql_builder import build_update_department_sql, get_metadata_db

        meta_db = db or get_metadata_db()
        sql = build_update_department_sql(dept_id, nome, descricao, meta_db)
        self.client.command(sql)
        return sql

    def delete_department(self, dept_id: str, db: str | None = None) -> str:
        from clickhouse_users_cli.sql_builder import (
            build_delete_department_sql,
            escape_string,
            escape_ident,
            get_metadata_db,
            USER_METADATA_TABLE,
        )

        meta_db = db or get_metadata_db()
        # Guarda: não excluir departamento em uso nos metadados.
        cnt_rows = self.client.query(
            f"SELECT count() FROM {escape_ident(meta_db)}.{escape_ident(USER_METADATA_TABLE)} "
            f"WHERE `departamento_id` = toUUID({escape_string(dept_id)})"
        ).result_rows
        cnt = int(cnt_rows[0][0]) if cnt_rows and cnt_rows[0] else 0
        if cnt > 0:
            from clickhouse_users_cli.i18n import t

            raise RuntimeError(t("dept_in_use", n=cnt))
        sql = build_delete_department_sql(dept_id, meta_db)
        self.client.command(sql)
        return sql

    def insert_user_metadata(
        self,
        meta,  # UserMetadata
        db: str | None = None,
    ) -> str:
        import uuid as _uuid

        from clickhouse_users_cli.sql_builder import build_insert_user_metadata_sql, get_metadata_db

        meta_db = db or get_metadata_db()
        if not meta.id:
            meta.id = str(_uuid.uuid4())
        sql = build_insert_user_metadata_sql(meta, meta_db)
        self.client.command(sql)
        return sql

    def get_user_metadata(self, username: str, db: str | None = None) -> dict | None:
        from clickhouse_users_cli.sql_builder import (
            USER_METADATA_TABLE,
            escape_ident,
            escape_string,
            get_metadata_db,
        )

        meta_db = db or get_metadata_db()
        rows = self.client.query(
            f"SELECT `id`, `usuario`, `matricula`, `nome_completo`, `email_corporativo`, "
            f"`departamento_id`, `departamento_nome` FROM {escape_ident(meta_db)}.{escape_ident(USER_METADATA_TABLE)} "
            f"WHERE `usuario` = {escape_string(username)} ORDER BY `created_at` DESC LIMIT 1"
        ).result_rows
        if not rows or not rows[0]:
            return None
        r = rows[0]
        return {
            "id": str(r[0]),
            "usuario": str(r[1]),
            "matricula": str(r[2]),
            "nome_completo": str(r[3]),
            "email_corporativo": str(r[4]),
            "departamento_id": str(r[5]),
            "departamento_nome": str(r[6]),
        }
