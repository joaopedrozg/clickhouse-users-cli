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
