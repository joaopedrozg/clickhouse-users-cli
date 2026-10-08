"""Construção do SQL DDL/DCL — separada do fluxo interativo para testar sem banco."""

from __future__ import annotations

from dataclasses import dataclass, field

from clickhouse_users_cli.i18n import t


def escape_ident(name: str) -> str:
    """Escapa identificador com backticks: `nome`."""
    return "`" + name.replace("`", "``") + "`"


def escape_string(value: str) -> str:
    """Escapa literal de string com aspas simples."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def escape_host(value: str) -> str:
    # HOST em CREATE USER aceita IP/hostname; aspas simples são o seguro.
    return escape_string(value)


@dataclass
class GrantScope:
    """Um alvo de GRANT: (database, table|None, table|*)."""

    database: str  # "*" = todas
    table: str | None = None  # None = db.* | "*" = *.* quando database == "*"

    def on_clause(self) -> str:
        if self.database == "*":
            return "*.*"
        if self.table in (None, "*"):
            return f"{escape_ident(self.database)}.*"
        return f"{escape_ident(self.database)}.{escape_ident(self.table)}"


@dataclass
class UserSpec:
    username: str
    password: str  # plaintext na criação; ClickHouse guarda o hash
    privileges: list[str] = field(default_factory=list)  # ex.: ["SELECT", "SHOW"]
    scopes: list[GrantScope] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)  # vazio = qualquer host
    if_not_exists: bool = True
    grant_option: bool = False  # WITH GRANT OPTION (só admin)
    # Quota futura: ex. "MAX QUERIES PER HOUR 1000" — mantido para evoluir sem quebrar API.


# Templates de perfil → privilégios padrão. "custom" deixa o usuário marcar.
PROFILE_PRIVILEGES: dict[str, list[str]] = {
    "readonly": ["SHOW", "SELECT"],
    "readwrite": ["SHOW", "SELECT", "INSERT"],
    "admin": ["ALL"],
    "custom": [],
}

PROFILE_LABELS: dict[str, str] = {
    "readonly": t("prof_readonly"),
    "readwrite": t("prof_readwrite"),
    "admin": t("prof_admin"),
    "custom": t("prof_custom"),
}


def build_create_user_sql(spec: UserSpec) -> str:
    ine = "IF NOT EXISTS " if spec.if_not_exists else ""
    parts = [f"CREATE USER {ine}{escape_ident(spec.username)}"]
    parts.append(f"IDENTIFIED WITH plaintext_password BY {escape_string(spec.password)}")
    if spec.hosts:
        hosts = ", ".join(f"HOST {escape_host(h)}" for h in spec.hosts)
        parts.append(hosts)
    else:
        parts.append("HOST ANY")
    return " ".join(parts)


def build_grant_sql(spec: UserSpec) -> list[str]:
    if not spec.scopes:
        raise ValueError(t("sql_no_scope"))
    if not spec.privileges:
        raise ValueError(t("sql_no_privs"))
    privs = ", ".join(spec.privileges)
    stmts: list[str] = []
    for scope in spec.scopes:
        suffix = " WITH GRANT OPTION" if spec.grant_option else ""
        stmts.append(f"GRANT {privs} ON {scope.on_clause()} TO {escape_ident(spec.username)}{suffix}")
    return stmts


def build_all_statements(spec: UserSpec) -> list[str]:
    return [build_create_user_sql(spec), *build_grant_sql(spec)]


def build_show_grants_sql(username: str) -> str:
    return f"SHOW GRANTS FOR {escape_ident(username)}"


def build_show_create_user_sql(username: str) -> str:
    return f"SHOW CREATE USER {escape_ident(username)}"


def build_deactivate_user_sql(username: str) -> str:
    """Desativa o login sem excluir: bloqueia qualquer origem (reversível)."""
    return f"ALTER USER {escape_ident(username)} HOST NONE"


def build_activate_user_sql(username: str) -> str:
    """Reativa o login: permite qualquer origem."""
    return f"ALTER USER {escape_ident(username)} HOST ANY"


def build_drop_user_sql(username: str, if_exists: bool = True) -> str:
    """Exclui o usuário em definitivo."""
    ine = "IF EXISTS " if if_exists else ""
    return f"DROP USER {ine}{escape_ident(username)}"


def build_revoke_all_sql(username: str) -> str:
    """Remove todos os privilégios em todos os escopos (zera antes de reaplicar)."""
    return f"REVOKE ALL ON *.* FROM {escape_ident(username)}"


def build_edit_grants_statements(
    username: str, privileges: list[str], scopes: list[GrantScope], grant_option: bool = False
) -> list[str]:
    """Edição de acessos: REVOKE ALL + GRANTs novos (com preview + confirmação no CLI)."""
    spec = UserSpec(username=username, password="", privileges=privileges, scopes=scopes, grant_option=grant_option)
    return [build_revoke_all_sql(username), *build_grant_sql(spec)]


# ── Leitura de grants atuais (pré-preencher a edição) ─────────────────────────

import re as _re


def _unquote_ident(part: str) -> str:
    p = (part or "").strip()
    if len(p) >= 2 and p.startswith("`") and p.endswith("`"):
        return p[1:-1].replace("``", "`")
    return p


_GRANT_RE = _re.compile(
    r"^\s*GRANT\s+(?P<privs>.+?)\s+ON\s+(?P<scope>\S+)\s+TO\s+.+?$",
    _re.IGNORECASE | _re.DOTALL,
)
_SCOPE_PARTS_RE = _re.compile(r"`(?:``|[^`])*`|[^\.]+")
_WITH_GRANT_RE = _re.compile(r"\s+WITH\s+GRANT\s+OPTION\s*$", _re.IGNORECASE)


def parse_grant_scope(text: str) -> GrantScope:
    """Converte `bd`.*, `bd`.`tb`, db.tbl ou *.* em GrantScope (tolerante)."""
    t = (text or "").strip()
    if t == "*.*":
        return GrantScope(database="*", table=None)
    parts = _SCOPE_PARTS_RE.findall(t)
    if len(parts) >= 2:
        db = _unquote_ident(parts[0])
        tb_raw = parts[1].strip()
        if tb_raw == "*":
            return GrantScope(database=db, table=None)
        return GrantScope(database=db, table=_unquote_ident(tb_raw))
    if len(parts) == 1:
        return GrantScope(database=_unquote_ident(parts[0]), table=None)
    return GrantScope(database=t, table=None)


def parse_grants(rows: list[str] | None) -> tuple[list[str], list[GrantScope], bool, bool]:
    """Interpreta linhas de SHOW GRANTS FOR.

    Retorna (privilégios-união, escopos, grant_option, heterogêneo).
    `heterogêneo` = True quando os privilégios variam por escopo — a edição
    normaliza para um conjunto único (o preview mostra o resultado).
    """
    privileges: list[str] = []
    seen_privs: set[str] = set()
    scopes: list[GrantScope] = []
    seen_scopes: set[tuple[str, str | None]] = set()
    grant_option = False
    priv_sets: set[tuple[str, ...]] = set()
    try:
        items = list(rows or [])
    except TypeError:
        return [], [], False, False
    for row in items:
        if not isinstance(row, str) or not row.strip():
            continue
        m = _GRANT_RE.match(row.strip())
        if not m:
            continue
        privs = [p.strip().upper() for p in m.group("privs").split(",") if p.strip()]
        if not privs:
            continue
        tail = row.strip()
        if _WITH_GRANT_RE.search(tail):
            grant_option = True
        priv_sets.add(tuple(privs))
        for p in privs:
            if p not in seen_privs:
                seen_privs.add(p)
                privileges.append(p)
        scope = parse_grant_scope(m.group("scope"))
        key = (scope.database, scope.table)
        if key not in seen_scopes:
            seen_scopes.add(key)
            scopes.append(scope)
    return privileges, scopes, grant_option, len(priv_sets) > 1


def infer_profile(privileges: list[str] | None, grant_option: bool = False) -> str:
    """Perfil mais próximo dos privilégios atuais (p/ pré-selecionar na edição)."""
    s = {p.strip().upper() for p in (privileges or []) if p and p.strip()}
    if s == {"ALL"}:
        return "admin"
    if s == {"SHOW", "SELECT"}:
        return "readonly"
    if s == {"SHOW", "SELECT", "INSERT"}:
        return "readwrite"
    return "custom"


# ── Metadados (tabelas gerenciadas pelo CLI) ──────────────────────────────────

import os as _os

DEFAULT_METADATA_DB = "ch_users_mgmt"
DEPARTMENTS_TABLE = "departments"
USER_METADATA_TABLE = "user_metadata"
USER_ACCESS_TABLE = "user_access"
USAGE_LOGS_TABLE = "usage_logs"


def get_metadata_db() -> str:
    """Banco das tabelas de metadados (override via CH_USERS_META_DB)."""
    return _os.environ.get("CH_USERS_META_DB", DEFAULT_METADATA_DB).strip() or DEFAULT_METADATA_DB


@dataclass
class Department:
    id: str = ""  # UUID em texto; vazio = gerar na inserção
    nome: str = ""
    descricao: str = ""


@dataclass
class UserMetadata:
    id: str = ""
    usuario: str = ""  # login no ClickHouse (ch_username)
    matricula: str = ""
    nome_completo: str = ""
    email_corporativo: str = ""
    departamento_id: str = ""
    departamento_nome: str = ""
    created_by: str = ""
    # Ciclo de vida (soft-delete / desativação reversível):
    #  updated_at  = última alteração dos metadados
    #  deleted     = 0 ativo / 1 excluído (soft-delete, mantém histórico)
    #  deactivated = 0 ativo / 1 desativado (HOST NONE, reversível)


@dataclass
class UserAccessEntry:
    """Um acesso concedido: o que cada usuário tem acesso (1 linha por escopo)."""

    usuario: str = ""
    privilegios: str = ""  # ex.: "SELECT, SHOW"
    database: str = ""
    tabela: str = ""  # "" = banco.* (todas as tabelas, atuais e futuras)
    grant_option: bool = False
    created_by: str = ""
    revogado: bool = False


@dataclass
class UsageLogEntry:
    """Log de utilização: quais tabelas/queries cada usuário executou."""

    usuario: str = ""
    query: str = ""
    tabelas: list[str] | None = None  # ex.: ["vendas.pedidos"]
    tipo_query: str = ""  # ex.: SELECT / INSERT / CREATE ...
    executada_em: str = ""  # vazio = now() no INSERT
    duracao_ms: int = 0
    status: str = "OK"


def build_create_metadata_db_sql(db: str | None = None) -> str:
    return f"CREATE DATABASE IF NOT EXISTS {escape_ident(db or get_metadata_db())}"


def build_create_departments_table_sql(db: str | None = None, table: str = DEPARTMENTS_TABLE) -> str:
    db = db or get_metadata_db()
    return (
        f"CREATE TABLE IF NOT EXISTS {escape_ident(db)}.{escape_ident(table)} "
        f"(`id` UUID DEFAULT generateUUIDv4(), `nome` String, "
        f"`descricao` String DEFAULT '', `created_at` DateTime DEFAULT now()) "
        f"ENGINE = MergeTree ORDER BY (`nome`, `id`)"
    )


def build_create_user_metadata_table_sql(db: str | None = None, table: str = USER_METADATA_TABLE) -> str:
    db = db or get_metadata_db()
    return (
        f"CREATE TABLE IF NOT EXISTS {escape_ident(db)}.{escape_ident(table)} "
        f"(`id` UUID DEFAULT generateUUIDv4(), `usuario` String, `matricula` String, "
        f"`nome_completo` String, `email_corporativo` String, "
        f"`departamento_id` UUID, `departamento_nome` String, "
        f"`created_at` DateTime DEFAULT now(), `created_by` String DEFAULT '', "
        f"`updated_at` DateTime DEFAULT now(), "
        f"`deleted` UInt8 DEFAULT 0, `deactivated` UInt8 DEFAULT 0) "
        f"ENGINE = MergeTree ORDER BY (`usuario`, `id`)"
    )


def build_alter_user_metadata_lifecycle_sql(
    db: str | None = None, table: str = USER_METADATA_TABLE,
) -> list[str]:
    """Migração para bancos já existentes: adiciona updated_at/deleted/deactivated.

    Idempotente (ADD COLUMN IF NOT EXISTS) — rode em todo ensure_metadata_schema.
    """
    db = db or get_metadata_db()
    base = f"{escape_ident(db)}.{escape_ident(table)}"
    return [
        f"ALTER TABLE {base} ADD COLUMN IF NOT EXISTS `updated_at` DateTime DEFAULT now()",
        f"ALTER TABLE {base} ADD COLUMN IF NOT EXISTS `deleted` UInt8 DEFAULT 0",
        f"ALTER TABLE {base} ADD COLUMN IF NOT EXISTS `deactivated` UInt8 DEFAULT 0",
    ]


def build_create_user_access_table_sql(db: str | None = None, table: str = USER_ACCESS_TABLE) -> str:
    """Tabela de acessos: o que cada usuário tem acesso (1 linha por escopo)."""
    db = db or get_metadata_db()
    return (
        f"CREATE TABLE IF NOT EXISTS {escape_ident(db)}.{escape_ident(table)} "
        f"(`id` UUID DEFAULT generateUUIDv4(), `usuario` String, "
        f"`privilegios` String, `database` String, `tabela` String DEFAULT '', "
        f"`grant_option` UInt8 DEFAULT 0, "
        f"`created_at` DateTime DEFAULT now(), `created_by` String DEFAULT '', "
        f"`revogado` UInt8 DEFAULT 0) "
        f"ENGINE = MergeTree ORDER BY (`usuario`, `database`, `tabela`, `id`)"
    )


def build_create_usage_logs_table_sql(db: str | None = None, table: str = USAGE_LOGS_TABLE) -> str:
    """Logs de utilização: quais tabelas/queries cada usuário executou."""
    db = db or get_metadata_db()
    return (
        f"CREATE TABLE IF NOT EXISTS {escape_ident(db)}.{escape_ident(table)} "
        f"(`id` UUID DEFAULT generateUUIDv4(), `usuario` String, "
        f"`query` String, `tabelas` Array(String), `tipo_query` String DEFAULT '', "
        f"`executada_em` DateTime DEFAULT now(), `duracao_ms` UInt32 DEFAULT 0, "
        f"`status` String DEFAULT 'OK', `created_by` String DEFAULT '') "
        f"ENGINE = MergeTree ORDER BY (`usuario`, `executada_em`, `id`)"
    )


def build_insert_department_sql(
    dept_id: str, nome: str, descricao: str = "",
    db: str | None = None, table: str = DEPARTMENTS_TABLE,
) -> str:
    db = db or get_metadata_db()
    return (
        f"INSERT INTO {escape_ident(db)}.{escape_ident(table)} (`id`, `nome`, `descricao`) "
        f"VALUES (toUUID({escape_string(dept_id)}), {escape_string(nome)}, {escape_string(descricao)})"
    )


def build_update_department_sql(
    dept_id: str, nome: str, descricao: str = "",
    db: str | None = None, table: str = DEPARTMENTS_TABLE,
) -> str:
    db = db or get_metadata_db()
    return (
        f"ALTER TABLE {escape_ident(db)}.{escape_ident(table)} "
        f"UPDATE `nome` = {escape_string(nome)}, `descricao` = {escape_string(descricao)} "
        f"WHERE `id` = toUUID({escape_string(dept_id)})"
    )


def build_delete_department_sql(
    dept_id: str, db: str | None = None, table: str = DEPARTMENTS_TABLE,
) -> str:
    db = db or get_metadata_db()
    return (
        f"ALTER TABLE {escape_ident(db)}.{escape_ident(table)} "
        f"DELETE WHERE `id` = toUUID({escape_string(dept_id)})"
    )


def build_insert_user_metadata_sql(
    meta: UserMetadata, db: str | None = None, table: str = USER_METADATA_TABLE,
) -> str:
    db = db or get_metadata_db()
    return (
        f"INSERT INTO {escape_ident(db)}.{escape_ident(table)} "
        f"(`id`, `usuario`, `matricula`, `nome_completo`, `email_corporativo`, "
        f"`departamento_id`, `departamento_nome`, `created_by`) VALUES "
        f"(toUUID({escape_string(meta.id)}), {escape_string(meta.usuario)}, "
        f"{escape_string(meta.matricula)}, {escape_string(meta.nome_completo)}, "
        f"{escape_string(meta.email_corporativo)}, toUUID({escape_string(meta.departamento_id)}), "
        f"{escape_string(meta.departamento_nome)}, {escape_string(meta.created_by)})"
    )


def build_touch_user_metadata_sql(
    username: str, db: str | None = None, table: str = USER_METADATA_TABLE,
) -> str:
    """Atualiza `updated_at` (carimba alteração sem mudar os demais campos)."""
    db = db or get_metadata_db()
    return (
        f"ALTER TABLE {escape_ident(db)}.{escape_ident(table)} "
        f"UPDATE `updated_at` = now() WHERE `usuario` = {escape_string(username)}"
    )


def build_set_user_deactivated_sql(
    username: str, deactivated: bool = True,
    db: str | None = None, table: str = USER_METADATA_TABLE,
) -> str:
    db = db or get_metadata_db()
    val = 1 if deactivated else 0
    return (
        f"ALTER TABLE {escape_ident(db)}.{escape_ident(table)} "
        f"UPDATE `deactivated` = {val}, `updated_at` = now() "
        f"WHERE `usuario` = {escape_string(username)}"
    )


def build_soft_delete_user_metadata_sql(
    username: str, db: str | None = None, table: str = USER_METADATA_TABLE,
) -> str:
    """Soft-delete: marca `deleted` = 1 (mantém histórico; DROP USER é separado)."""
    db = db or get_metadata_db()
    return (
        f"ALTER TABLE {escape_ident(db)}.{escape_ident(table)} "
        f"UPDATE `deleted` = 1, `updated_at` = now() "
        f"WHERE `usuario` = {escape_string(username)}"
    )


def build_restore_user_metadata_sql(
    username: str, db: str | None = None, table: str = USER_METADATA_TABLE,
) -> str:
    db = db or get_metadata_db()
    return (
        f"ALTER TABLE {escape_ident(db)}.{escape_ident(table)} "
        f"UPDATE `deleted` = 0, `deactivated` = 0, `updated_at` = now() "
        f"WHERE `usuario` = {escape_string(username)}"
    )


# ── Acessos (user_access) ─────────────────────────────────────────────────────

def build_insert_user_access_sql(
    entry: UserAccessEntry, db: str | None = None, table: str = USER_ACCESS_TABLE,
) -> str:
    import uuid as _uuid

    db = db or get_metadata_db()
    entry_id = str(getattr(entry, "id", "") or _uuid.uuid4())
    grant = 1 if entry.grant_option else 0
    rev = 1 if entry.revogado else 0
    return (
        f"INSERT INTO {escape_ident(db)}.{escape_ident(table)} "
        f"(`id`, `usuario`, `privilegios`, `database`, `tabela`, "
        f"`grant_option`, `created_by`, `revogado`) VALUES "
        f"(toUUID({escape_string(entry_id)}), {escape_string(entry.usuario)}, "
        f"{escape_string(entry.privilegios)}, {escape_string(entry.database)}, "
        f"{escape_string(entry.tabela)}, {grant}, {escape_string(entry.created_by)}, {rev})"
    )


def build_revoke_user_access_sql(
    username: str, db: str | None = None, table: str = USER_ACCESS_TABLE,
) -> str:
    """Marca todos os acessos vigentes como revogados (histórico preservado)."""
    db = db or get_metadata_db()
    return (
        f"ALTER TABLE {escape_ident(db)}.{escape_ident(table)} "
        f"UPDATE `revogado` = 1 WHERE `usuario` = {escape_string(username)} AND `revogado` = 0"
    )


# ── Logs de utilização (usage_logs) ───────────────────────────────────────────

def build_insert_usage_log_sql(
    entry: UsageLogEntry, db: str | None = None, table: str = USAGE_LOGS_TABLE,
) -> str:
    db = db or get_metadata_db()
    tabelas = entry.tabelas or []
    arr = "[" + ", ".join(escape_string(t) for t in tabelas) + "]"
    return (
        f"INSERT INTO {escape_ident(db)}.{escape_ident(table)} "
        f"(`usuario`, `query`, `tabelas`, `tipo_query`, `duracao_ms`, `status`, `created_by`) VALUES "
        f"({escape_string(entry.usuario)}, {escape_string(entry.query)}, {arr}, "
        f"{escape_string(entry.tipo_query)}, {int(entry.duracao_ms)}, "
        f"{escape_string(entry.status)}, {escape_string(getattr(entry, 'created_by', ''))})"
    )


def build_import_query_log_sql(
    username: str, limit: int = 100,
    db: str | None = None, table: str = USAGE_LOGS_TABLE,
) -> str:
    """Importa as últimas queries de `system.query_log` para a tabela de uso.

    Útil para auditoria: quais tabelas/queries cada user executou.
    Requer acesso a `system.query_log`.
    """
    db = db or get_metadata_db()
    lim = max(1, int(limit))
    return (
        f"INSERT INTO {escape_ident(db)}.{escape_ident(table)} "
        f"(`usuario`, `query`, `tabelas`, `tipo_query`, `executada_em`, `duracao_ms`, `status`) "
        f"SELECT `user`, `query`, `tables`, `query_kind`, `event_time`, "
        f"toUInt32(`query_duration_ms`), `type` "
        f"FROM system.query_log "
        f"WHERE `user` = {escape_string(username)} AND `type` = 'QueryFinish' "
        f"ORDER BY `event_time` DESC LIMIT {lim}"
    )
