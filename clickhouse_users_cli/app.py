"""Fluxo interativo — cada função = 1 etapa, 1 widget ideal para o tipo de dado."""

from __future__ import annotations

import sys

import questionary
from rich.syntax import Syntax

from clickhouse_users_cli.db import SYSTEM_DATABASES, ClickHouseAdmin, ConnectionInfo
from clickhouse_users_cli.sql_builder import (
    PROFILE_LABELS,
    PROFILE_PRIVILEGES,
    Department,
    GrantScope,
    UserMetadata,
    UserSpec,
    build_activate_user_sql,
    build_all_statements,
    build_deactivate_user_sql,
    build_drop_user_sql,
    build_edit_grants_statements,
    get_metadata_db,
)
from clickhouse_users_cli.style import APP_STYLE, banner, console, error, info, make_table, step, success, warn
from clickhouse_users_cli.i18n import t
from clickhouse_users_cli.session import SESSION_FILE
from clickhouse_users_cli.validators import (
    validate_at_least_one,
    validate_dept_name,
    validate_email,
    validate_full_name,
    validate_host,
    validate_matricula,
    validate_new_password,
    validate_port,
    validate_required,
    validate_username,
)

Q = questionary  # alias curto


def _ask_or_abort(prompt):
    """questionary retorna None no Ctrl+C — converte em saída limpa."""
    answer = prompt.ask()
    if answer is None:
        console.print(t("op_cancelled"))
        raise SystemExit(0)
    return answer


# ── Etapa 1: conexão ──────────────────────────────────────────────────────────

def ask_connection() -> ConnectionInfo:
    step(t("step_conn_t"), t("step_conn_s"))

    host = _ask_or_abort(
        Q.text(t("q_host"), default="localhost", validate=validate_host, style=APP_STYLE, qmark="›")
    ).strip()

    protocol = _ask_or_abort(
        Q.select(
            t("q_proto"),
            choices=[
                Q.Choice(t("proto_http"), value=False),
                Q.Choice(t("proto_https"), value=True),
            ],
            default=False,
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )
    default_port = "8443" if protocol else "8123"

    port = int(
        _ask_or_abort(
            Q.text(t("q_port", port=default_port), default=default_port, validate=validate_port, style=APP_STYLE, qmark="›")
        ).strip()
        or default_port
    )

    admin_user = _ask_or_abort(
        Q.text(t("q_admin_user"), default="default", validate=validate_required, style=APP_STYLE, qmark="›")
    ).strip()

    admin_pass = _ask_or_abort(Q.password(t("q_admin_pass"), style=APP_STYLE, qmark="›"))

    return ConnectionInfo(host=host, port=port, secure=protocol, username=admin_user, password=admin_pass)


def connect_with_retry(conn: ConnectionInfo) -> ClickHouseAdmin:
    while True:
        with console.status(t("connecting", proto=conn.protocol, host=conn.host, port=conn.port), spinner="dots"):
            try:
                admin = ClickHouseAdmin(conn).connect()
                success(t("connected", username=conn.username, host=conn.host, port=conn.port))
                return admin
            except RuntimeError as e:
                error(str(e))
        action = _ask_or_abort(
            Q.select(
                t("retry_q"),
                choices=[t("retry_again"), t("retry_edit"), t("retry_exit")],
                style=APP_STYLE, qmark="›",
            )
        )
        if action == t("retry_again"):
            continue
        if action == t("retry_edit"):
            return connect_with_retry(ask_connection())
        raise SystemExit(1)


# ── Etapa 2: perfil do novo usuário ───────────────────────────────────────────

def ask_profile(mode: str = "create") -> str:
    if mode == "edit":
        step(t("estep_profile_t"), t("estep_profile_s"))
        question = t("q_new_type")
    else:
        step(t("step_profile_t"), t("step_profile_s"))
        question = t("q_create_type")
    return _ask_or_abort(
        Q.select(
            question,
            choices=[Q.Choice(PROFILE_LABELS[k], value=k) for k in ("readonly", "readwrite", "admin", "custom")],
            default="readonly",
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )


# ── Etapa 3: credenciais do novo usuário ──────────────────────────────────────

def ask_new_credentials() -> tuple[str, str]:
    step(t("step_creds_t"), t("step_creds_s"))
    username = _ask_or_abort(
        Q.text(t("q_new_name"), validate=validate_username, style=APP_STYLE, qmark="›")
    ).strip()

    while True:
        pwd = _ask_or_abort(
            Q.password(t("q_new_pass"), validate=validate_new_password, style=APP_STYLE, qmark="›")
        )
        confirm = _ask_or_abort(Q.password(t("q_confirm_pass"), style=APP_STYLE, qmark="›"))
        if pwd != confirm:
            error(t("err_pw_mismatch"))
            continue
        return username, pwd


# ── Etapa 3b: metadados do colaborador (obrigatório) ──────────────────────────

def ensure_metadata_schema(admin: ClickHouseAdmin) -> str:
    """Garante DB + tabelas de metadados. Aborta com msg amigável se sem permissão."""
    meta_db = get_metadata_db()
    with console.status(t("listing_dbs"), spinner="dots"):
        try:
            admin.ensure_metadata_schema(meta_db)
        except Exception as e:
            error(t("err_meta_schema", db=meta_db, e=e))
            info(t("hint_meta_perms", db=meta_db))
            raise SystemExit(1)
    return meta_db


def _fetch_departments_or_abort(admin: ClickHouseAdmin) -> list[dict]:
    try:
        return admin.list_departments()
    except Exception as e:
        error(t("err_meta_schema", db=get_metadata_db(), e=e))
        raise SystemExit(1)


def flow_create_department(admin: ClickHouseAdmin, preset_name: str = "") -> dict | None:
    """Cria 1 departamento e retorna o dict. None se cancelar/falhar."""
    name = _ask_or_abort(
        Q.text(t("q_dept_name"), default=preset_name, validate=validate_dept_name, style=APP_STYLE, qmark="›")
    ).strip()
    desc = _ask_or_abort(
        Q.text(t("q_dept_desc"), default="", style=APP_STYLE, qmark="›")
    ).strip()
    with console.status(t("running"), spinner="dots"):
        try:
            dept_id = admin.create_department(name.strip(), desc.strip())
        except Exception as e:
            error(t("err_op", e=e))
            return None
    success(t("dept_created", name=name.strip()))
    return {"id": dept_id, "nome": name.strip(), "descricao": desc.strip()}


def ask_user_metadata(admin: ClickHouseAdmin, ch_username: str) -> UserMetadata:
    """Pergunta matrícula/nome/email + departamento (só da tabela — sem digitação livre)."""
    from clickhouse_users_cli.sql_builder import UserMetadata as _UM

    step(t("meta_step_t"), t("meta_step_s"))
    ensure_metadata_schema(admin)
    depts = _fetch_departments_or_abort(admin)
    if not depts:
        error(t("err_no_depts"))
        go = _ask_or_abort(Q.confirm(t("q_create_dept_first"), default=True, style=APP_STYLE, qmark="›"))
        if not go:
            raise SystemExit(1)
        created = flow_create_department(admin)
        if not created:
            raise SystemExit(1)
        depts = _fetch_departments_or_abort(admin)

    matricula = _ask_or_abort(
        Q.text(t("q_matricula"), validate=validate_matricula, style=APP_STYLE, qmark="›")
    ).strip()
    nome = _ask_or_abort(
        Q.text(t("q_full_name"), validate=validate_full_name, style=APP_STYLE, qmark="›")
    ).strip()
    email = _ask_or_abort(
        Q.text(t("q_email"), validate=validate_email, style=APP_STYLE, qmark="›")
    ).strip()

    # Departamento: apenas escolha da lista existente (nada de texto livre).
    dept = _ask_or_abort(
        Q.select(
            t("q_dept"),
            choices=[Q.Choice(f"{d['nome']}" + (f" — {d['descricao']}" if d.get("descricao") else ""), value=d) for d in depts],
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )
    return _UM(
        usuario=ch_username, matricula=matricula, nome_completo=nome,
        email_corporativo=email, departamento_id=dept["id"], departamento_nome=dept["nome"],
        created_by=admin.conn.username,
    )


# ── Etapa 4: escopo (bancos → tabelas) ────────────────────────────────────────

def ask_databases(admin: ClickHouseAdmin, mode: str = "create") -> list[str]:
    step(t("estep_dbs_t") if mode == "edit" else t("step_dbs_t"), t("scope_hint"))
    with console.status(t("listing_dbs"), spinner="dots"):
        try:
            databases = admin.list_databases()
        except Exception as e:
            error(t("err_list_dbs", e=e))
            raise SystemExit(1)

    if not databases:
        error(t("err_no_dbs"))
        raise SystemExit(1)

    choices = [Q.Choice(title=t("all_dbs"), value="__ALL__")] + [
        Q.Choice(
            title=t("db_system_tag", db=db) if db in SYSTEM_DATABASES else db,
            value=db,
            # UX: nada pré-marcado (least privilege) — o usuário opta explicitamente.
            checked=False,
        )
        for db in databases
    ]
    selected = _ask_or_abort(
        Q.checkbox(
            t("q_which_dbs"),
            choices=choices,
            validate=validate_at_least_one,
            style=APP_STYLE, qmark="›",
            instruction=t("check_hint"),
        )
    )
    if "__ALL__" in selected:
        return list(databases)
    return selected


def ask_tables(admin: ClickHouseAdmin, databases: list[str], mode: str = "create") -> list[GrantScope]:
    step(t("estep_tables_t") if mode == "edit" else t("step_tables_t"), t("scope_tables_hint"))
    scopes: list[GrantScope] = []
    for db in databases:
        try:
            tables = admin.list_tables(db)
        except Exception as e:
            error(t("err_list_tables", db=db, e=e))
            scopes.append(GrantScope(database=db, table=None))
            continue

        if not tables:
            info(t("info_no_tables", db=db))
            scopes.append(GrantScope(database=db, table=None))
            continue

        choices = [Q.Choice(title=t("all_tables", db=db), value="__ALL__")] + [
            Q.Choice(title=f"{db}.{t}", value=t) for t in tables
        ]
        picked: list[str] = _ask_or_abort(
            Q.checkbox(
                t("q_tables", db=db),
                choices=choices,
                validate=validate_at_least_one,
                style=APP_STYLE, qmark="›",
                instruction=t("check_hint"),
            )
        )
        if "__ALL__" in picked:
            scopes.append(GrantScope(database=db, table=None))
        else:
            scopes.extend(GrantScope(database=db, table=t) for t in picked)
    return scopes


# ── Etapa 5: privilégios + restrições ─────────────────────────────────────────

PRIVILEGE_CHOICES = [
    ("SELECT", t("priv_select")),
    ("SHOW", t("priv_show")),
    ("INSERT", t("priv_insert")),
    ("CREATE", t("priv_create")),
    ("ALTER", t("priv_alter")),
    ("DROP", t("priv_drop")),
    ("TRUNCATE", t("priv_truncate")),
    ("OPTIMIZE", t("priv_optimize")),
    ("KILL QUERY", t("priv_kill")),
]


def ask_privileges(profile: str, mode: str = "create") -> tuple[list[str], bool]:
    """Retorna (privilégios, grant_option)."""
    if profile != "custom":
        grant_option = profile == "admin"
        return list(PROFILE_PRIVILEGES[profile]), grant_option

    step(t("estep_privs_t") if mode == "edit" else t("step_privs_t"), t("privs_hint"))
    privs: list[str] = _ask_or_abort(
        Q.checkbox(
            t("q_which_privs"),
            choices=[Q.Choice(f"{name:12} — {desc}", value=name) for name, desc in PRIVILEGE_CHOICES],
            validate=validate_at_least_one,
            style=APP_STYLE, qmark="›",
        )
    )
    grant_option = False
    if any(p in privs for p in ("DROP", "TRUNCATE")):
        grant_option_confirm = _ask_or_abort(
            Q.confirm(t("q_destructive"), default=False, style=APP_STYLE, qmark="›")
        )
        if not grant_option_confirm:
            return ask_privileges("custom", mode=mode)
    else:
        grant_option = _ask_or_abort(
            Q.confirm(t("q_grant_option"), default=False, style=APP_STYLE, qmark="›")
        )
    return privs, grant_option


def ask_host_restriction() -> list[str]:
    step(t("step_host_t"), t("step_host_s"))
    mode = _ask_or_abort(
        Q.select(
            t("q_allow_from"),
            choices=[
                Q.Choice(t("host_any"), value="any"),
                Q.Choice(t("host_local"), value="localhost"),
                Q.Choice(t("host_custom"), value="custom"),
            ],
            default="any",
            style=APP_STYLE, qmark="›",
        )
    )
    if mode == "any":
        return []
    if mode == "localhost":
        return ["LOCALHOST"]
    raw = _ask_or_abort(
        Q.text(t("q_hosts"), validate=validate_required, style=APP_STYLE, qmark="›")
    )
    return [h.strip() for h in raw.split(",") if h.strip()]


def ask_create_options() -> bool:
    return _ask_or_abort(
        Q.confirm(t("q_if_not_exists"), default=True, style=APP_STYLE, qmark="›")
    )


# ── Etapa 6: revisão + execução ───────────────────────────────────────────────

def show_review(spec: UserSpec, meta: UserMetadata | None = None) -> None:
    step(t("step_review_t"), t("step_review_s"))
    table = make_table(t("review_title"))
    table.add_column(t("col_field"), style="dim")
    table.add_column(t("col_value"), style="bold")
    table.add_row(t("f_user"), spec.username)
    if meta is not None:
        table.add_row(t("f_matricula"), meta.matricula)
        table.add_row(t("f_full_name"), meta.nome_completo)
        table.add_row(t("f_email"), meta.email_corporativo)
        table.add_row(t("f_dept"), meta.departamento_nome)
    table.add_row(t("f_privs"), ", ".join(spec.privileges))
    table.add_row(t("f_scope"), ", ".join(s.on_clause() for s in spec.scopes))
    table.add_row(t("f_hosts"), ", ".join(spec.hosts) if spec.hosts else t("hosts_any"))
    table.add_row(t("f_grant_option"), t("yes") if spec.grant_option else t("no"))
    console.print(table)

    console.print(t("sql_to_run"))
    from rich.panel import Panel as RichPanel

    for sql in build_all_statements(spec):
        console.print(RichPanel(Syntax(sql + ";", "sql", theme="monokai"), border_style="dim"))


def confirm_and_execute(admin: ClickHouseAdmin, spec: UserSpec, meta: UserMetadata | None = None) -> None:
    show_review(spec, meta)
    go = _ask_or_abort(Q.confirm(t("q_create_now", username=spec.username), default=True, style=APP_STYLE, qmark="›"))
    if not go:
        console.print(t("nothing_done"))
        raise SystemExit(0)

    statements = build_all_statements(spec)
    with console.status(t("running_ddl"), spinner="dots"):
        try:
            admin.execute_statements(statements)
        except Exception as e:
            error(t("err_create", e=e))
            info(t("hint_create_perms"))
            raise SystemExit(1)
    success(t("created", username=spec.username, n=len(statements)))

    if meta is not None:
        with console.status(t("running"), spinner="dots"):
            try:
                admin.insert_user_metadata(meta)
            except Exception as e:
                error(t("meta_save_fail", e=e))
                info(t("hint_meta_perms", db=get_metadata_db()))
                raise SystemExit(1)
        success(t("meta_saved", username=spec.username))
    info(t("test_hint", username=spec.username))




# ── Sessão salva (YAML local, opt-in) ────────────────────────────────────────────

def maybe_load_saved_session() -> ConnectionInfo | None:
    """Se há YAML salvo, oferece usar / nova conexão / apagar. None = digitar."""
    from clickhouse_users_cli.session import delete_session, has_saved_session, load_session

    if not has_saved_session():
        return None
    step(t("step_saved_t"), t("saved_file_note", path=SESSION_FILE))
    try:
        saved = load_session()
    except RuntimeError as e:
        error(str(e))
        fix = _ask_or_abort(
            Q.select(
                t("saved_invalid_q"),
                choices=[
                    Q.Choice(t("fix_delete"), value="delete"),
                    Q.Choice(t("fix_keep"), value="new"),
                ],
                style=APP_STYLE, qmark="›",
            )
        )
        if fix == "delete":
            delete_session()
            success(t("deleted"))
        return None

    info(t("saved_conn_info", proto=saved.protocol, host=saved.host, port=saved.port, username=saved.username))
    choice = _ask_or_abort(
        Q.select(
            t("use_saved_q"),
            choices=[
                Q.Choice(t("use_saved"), value="use"),
                Q.Choice(t("new_conn"), value="new"),
                Q.Choice(t("del_saved"), value="delete"),
            ],
            default="use",
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )
    if choice == "delete":
        delete_session()
        success(t("deleted"))
        return None
    if choice == "new":
        return None
    return saved


def ask_remember(conn: ConnectionInfo) -> None:
    """Opt-in: salva a conexão em YAML local (senha em texto puro)."""
    from clickhouse_users_cli.session import save_session

    warn(t("remember_warn"))
    keep = _ask_or_abort(
        Q.confirm(t("remember_q"), default=False, style=APP_STYLE, qmark="›")
    )
    if not keep:
        return
    try:
        path = save_session(conn)
    except RuntimeError as e:
        error(str(e))
        return
    success(t("saved_to", path=path))


def flow_forget_session() -> None:
    from clickhouse_users_cli.session import delete_session, has_saved_session

    if not has_saved_session():
        info(t("none_saved"))
        return
    step(t("step_forget_t"), t("saved_file_note", path=SESSION_FILE))
    go = _ask_or_abort(
        Q.confirm(t("forget_q"), default=False, style=APP_STYLE, qmark="›")
    )
    if not go:
        console.print(t("nothing_deleted"))
        return
    delete_session()
    success(t("deleted"))


# ── Menu principal + listar/gerenciar ────────────────────────────────────────────

def ask_main_action(show_forget: bool = False) -> str:
    choices = [
        Q.Choice(t("act_create"), value="create"),
        Q.Choice(t("act_list"), value="list"),
        Q.Choice(t("act_manage"), value="manage"),
        Q.Choice(t("act_depts"), value="depts"),
    ]
    if show_forget:
        choices.append(Q.Choice(t("act_forget"), value="forget"))
    choices.append(Q.Choice(t("act_exit"), value="exit"))
    return _ask_or_abort(
        Q.select(
            t("q_what_do"),
            choices=choices,
            default="create",
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )


def _is_inactive(create_sql: str) -> bool:
    return "HOST NONE" in (create_sql or "").upper()


def show_user_details(admin: ClickHouseAdmin, username: str) -> tuple[str, list[str]]:
    """Busca CREATE + GRANTS + metadados e exibe. Retorna (create_sql, grants)."""
    try:
        create_sql = admin.show_create_user(username)
    except Exception as e:
        error(t("err_details", username=username, e=e))
        create_sql = ""
    try:
        grants = admin.show_grants(username)
    except Exception as e:
        error(t("err_grants", username=username, e=e))
        grants = []
    try:
        meta = admin.get_user_metadata(username)
    except Exception:
        meta = None

    table = make_table(t("user_title", username=username))
    table.add_column(t("col_field"), style="dim")
    table.add_column(t("col_value"), style="bold")
    status = t("status_inactive") if _is_inactive(create_sql) else t("status_active")
    table.add_row(t("col_status"), status)
    if meta:
        table.add_row(t("f_matricula"), meta.get("matricula", ""))
        table.add_row(t("f_full_name"), meta.get("nome_completo", ""))
        table.add_row(t("f_email"), meta.get("email_corporativo", ""))
        table.add_row(t("f_dept"), meta.get("departamento_nome", ""))
    else:
        table.add_row(t("f_dept"), t("meta_none"))
    table.add_row(t("col_grants"), "\n".join(grants) if grants else t("grants_none"))
    console.print(table)

    if create_sql:
        console.print(t("current_def"))
        from rich.panel import Panel as RichPanel

        console.print(RichPanel(Syntax(create_sql + ";", "sql", theme="monokai"), border_style="dim"))
    return create_sql, grants


def flow_list_users(admin: ClickHouseAdmin) -> None:
    step(t("step_list_t"), t("step_list_s"))
    with console.status(t("listing_users"), spinner="dots"):
        try:
            users = admin.list_users()
        except Exception as e:
            error(t("err_list_users", e=e))
            info(t("hint_show_users"))
            return

    if not users:
        info(t("no_users"))
        return

    table = make_table(t("users_title", n=len(users)))
    table.add_column(t("col_num"), style="dim")
    table.add_column(t("col_user"), style="bold")
    for i, u in enumerate(users, 1):
        table.add_row(str(i), u)
    console.print(table)

    see = _ask_or_abort(
        Q.confirm(t("q_see_details"), default=True, style=APP_STYLE, qmark="›")
    )
    if not see:
        return
    target = _ask_or_abort(
        Q.select(
            t("q_which_user"),
            choices=users,
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )
    show_user_details(admin, target)


def flow_edit_grants(admin: ClickHouseAdmin, username: str) -> None:
    """Redefine os acessos: REVOKE ALL + GRANTs novos (perfil + escopo + hosts intactos)."""
    step(t("step_edit_t"), t("step_edit_s"))
    if username == admin.conn.username:
        warn(t("self_warn_zero", username=username))

    profile = ask_profile(mode="edit")
    privileges, grant_option = ask_privileges(profile, mode="edit")
    if profile == "admin":
        grant_option = True
    databases = ask_databases(admin, mode="edit")
    scopes = ask_tables(admin, databases, mode="edit")

    statements = build_edit_grants_statements(username, privileges, scopes, grant_option)
    table = make_table(t("new_access_title", username=username))
    table.add_column(t("col_privs"), style="bold")
    table.add_column(t("col_scope"), style="bold")
    table.add_column(t("col_grant"), style="dim")
    for s in scopes:
        table.add_row(", ".join(privileges), s.on_clause(), t("yes") if grant_option else t("no"))
    console.print(table)

    console.print(t("sql_order_note"))
    from rich.panel import Panel as RichPanel

    for sql in statements:
        console.print(RichPanel(Syntax(sql + ";", "sql", theme="monokai"), border_style="dim"))

    go = _ask_or_abort(Q.confirm(t("q_apply", username=username), default=False, style=APP_STYLE, qmark="›"))
    if not go:
        console.print(t("nothing_done"))
        return

    with console.status(t("running"), spinner="dots"):
        try:
            admin.execute_statements(statements)
        except Exception as e:
            error(t("err_edit", e=e))
            info(t("hint_edit"))
            return
    success(t("updated", username=username, n=len(statements)))


# ── Departamentos (CRUD) ────────────────────────────────────────────────────

def flow_manage_departments(admin: ClickHouseAdmin) -> None:
    step(t("step_depts_t"), t("step_depts_s"))
    ensure_metadata_schema(admin)
    while True:
        try:
            depts = admin.list_departments()
        except Exception as e:
            error(t("err_meta_schema", db=get_metadata_db(), e=e))
            return

        if depts:
            table = make_table(t("depts_title", n=len(depts)))
            table.add_column(t("col_num"), style="dim")
            table.add_column(t("col_dept"), style="bold")
            table.add_column(t("col_desc"), style="dim")
            for i, d in enumerate(depts, 1):
                table.add_row(str(i), d["nome"], d.get("descricao") or "")
            console.print(table)
        else:
            info(t("no_depts"))

        action = _ask_or_abort(
            Q.select(
                t("q_dept_action"),
                choices=[
                    Q.Choice(t("opt_dept_create"), value="create"),
                    Q.Choice(t("opt_dept_edit"), value="edit"),
                    Q.Choice(t("opt_dept_delete"), value="delete"),
                    Q.Choice(t("opt_back"), value="back"),
                ],
                style=APP_STYLE, qmark="›",
            )
        )
        if action == "back":
            return
        if action == "create":
            flow_create_department(admin)
            continue
        # edit/delete exigem lista não vazia
        if not depts:
            error(t("no_depts"))
            continue
        target = _ask_or_abort(
            Q.select(
                t("q_which_dept"),
                choices=[Q.Choice(d["nome"], value=d) for d in depts],
                style=APP_STYLE, qmark="›",
                instruction=t("nav_hint"),
            )
        )
        if action == "edit":
            new_name = _ask_or_abort(
                Q.text(t("q_dept_name"), default=target["nome"], validate=validate_dept_name, style=APP_STYLE, qmark="›")
            ).strip()
            new_desc = _ask_or_abort(
                Q.text(t("q_dept_desc"), default=target.get("descricao") or "", style=APP_STYLE, qmark="›")
            ).strip()
            with console.status(t("running"), spinner="dots"):
                try:
                    admin.update_department(target["id"], new_name, new_desc)
                except Exception as e:
                    error(t("err_op", e=e))
                    continue
            success(t("dept_updated", name=new_name))
        else:
            go = _ask_or_abort(
                Q.confirm(t("q_dept_delete_confirm", name=target["nome"]), default=False, style=APP_STYLE, qmark="›")
            )
            if not go:
                console.print(t("nothing_done"))
                continue
            with console.status(t("running"), spinner="dots"):
                try:
                    admin.delete_department(target["id"])
                except Exception as e:
                    error(str(e))
                    continue
            success(t("dept_deleted", name=target["nome"]))


def flow_manage_users(admin: ClickHouseAdmin) -> None:
    step(t("step_manage_t"), t("step_manage_s"))
    with console.status(t("listing_users"), spinner="dots"):
        try:
            users = admin.list_users()
        except Exception as e:
            error(t("err_list_users", e=e))
            return

    if not users:
        info(t("no_users"))
        return

    target = _ask_or_abort(
        Q.select(
            t("q_which_manage"),
            choices=users,
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )
    create_sql, _grants = show_user_details(admin, target)
    inactive = _is_inactive(create_sql)

    if target == admin.conn.username:
        warn(t("self_warn_deactivate", username=target))

    options = []
    if inactive:
        options.append(Q.Choice(t("opt_reactivate"), value="activate"))
    else:
        options.append(Q.Choice(t("opt_deactivate"), value="deactivate"))
    options += [
        Q.Choice(t("opt_edit"), value="edit"),
        Q.Choice(t("opt_drop"), value="drop"),
        Q.Choice(t("opt_back"), value="back"),
    ]
    action = _ask_or_abort(
        Q.select(t("q_action"), choices=options, style=APP_STYLE, qmark="›")
    )
    if action == "back":
        return
    if action == "edit":
        flow_edit_grants(admin, target)
        return

    preview = {
        "deactivate": build_deactivate_user_sql(target),
        "activate": build_activate_user_sql(target),
        "drop": build_drop_user_sql(target),
    }[action]

    console.print(t("sql_to_run"))
    from rich.panel import Panel as RichPanel

    console.print(RichPanel(Syntax(preview + ";", "sql", theme="monokai"), border_style="dim"))

    # Confirmação: default sempre o mais seguro (não executar).
    label = {"deactivate": t("lbl_deactivate", target=target), "activate": t("lbl_activate", target=target), "drop": t("lbl_drop", target=target)}[action]
    go = _ask_or_abort(Q.confirm(label, default=False, style=APP_STYLE, qmark="›"))
    if not go:
        console.print(t("nothing_done"))
        return

    with console.status(t("running"), spinner="dots"):
        try:
            if action == "deactivate":
                admin.deactivate_user(target)
            elif action == "activate":
                admin.activate_user(target)
            else:
                admin.drop_user(target)
        except Exception as e:
            error(t("err_op", e=e))
            info(t("hint_alter"))
            return
    success(t("done_deactivate" if action == "deactivate" else "done_activate" if action == "activate" else "done_drop", target=target))


def flow_create_user(admin: ClickHouseAdmin) -> None:
    profile = ask_profile()
    username, password = ask_new_credentials()
    meta = ask_user_metadata(admin, username)
    databases = ask_databases(admin)
    scopes = ask_tables(admin, databases)
    privileges, grant_option = ask_privileges(profile)
    if profile == "admin":
        grant_option = True
    hosts = ask_host_restriction()
    if_not_exists = ask_create_options()

    spec = UserSpec(
        username=username,
        password=password,
        privileges=privileges,
        scopes=scopes,
        hosts=hosts,
        if_not_exists=if_not_exists,
        grant_option=grant_option,
    )
    confirm_and_execute(admin, spec, meta)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        banner()
        from clickhouse_users_cli.session import has_saved_session

        saved_conn = maybe_load_saved_session()
        conn = saved_conn or ask_connection()
        admin = connect_with_retry(conn)
        if saved_conn is None:
            ask_remember(conn)

        while True:
            action = ask_main_action(show_forget=has_saved_session())
            if action == "create":
                flow_create_user(admin)
            elif action == "list":
                flow_list_users(admin)
            elif action == "manage":
                flow_manage_users(admin)
            elif action == "depts":
                flow_manage_departments(admin)
            elif action == "forget":
                flow_forget_session()
            else:
                console.print(t("bye"))
                return
    except SystemExit:
        raise
    except KeyboardInterrupt:
        console.print(t("interrupted"))
    except Exception as e:  # pragma: no cover — guarda-chuva final
        error(t("unexpected", e=e))
        sys.exit(1)


if __name__ == "__main__":
    main()
