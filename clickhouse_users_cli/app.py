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


# ── Navegação "voltar" no fluxo de criação ─────────────────────────────────────

class BackStep(Exception):
    """Sinal interno: o usuário escolheu voltar à etapa anterior."""

    pass


BACK_VALUE = "__BACK__"
BACK_KEYWORDS = (":voltar", ":back", ":v", "<<")
BACK_HINT_SHOWN: set[str] = set()


def _is_back_keyword(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in BACK_KEYWORDS


def _back_choice():
    """Opção '← Voltar' para prompts de lista (select/checkbox)."""
    return Q.Choice(t("opt_back_to_prev"), value=BACK_VALUE)


def _raise_if_back(answer: object) -> None:
    """Levanta BackStep se a resposta for a opção/palavra-chave de voltar."""
    if answer == BACK_VALUE or _is_back_keyword(answer):
        raise BackStep()


def _maybe_back_hint(step_key: str = "create") -> None:
    """Explica como voltar (1x por sessão — evita poluir toda etapa)."""
    if step_key not in BACK_HINT_SHOWN:
        BACK_HINT_SHOWN.add(step_key)
        info(t("back_hint"))


def _with_back_validator(validator):
    """Envolve um validador de texto/senha para deixar ':voltar' passar."""
    def _wrapped(value):
        if _is_back_keyword(value):
            return True
        if validator is None:
            return True
        return validator(value)

    return _wrapped


def _ask_confirm_or_back(question: str, default: bool = True) -> bool:
    """Sim/Não/Voltar (usado no lugar de `confirm` quando voltar é permitido)."""
    ans = _ask_or_abort(
        Q.select(
            question,
            choices=[
                Q.Choice(t("yes"), value=True),
                Q.Choice(t("no"), value=False),
                _back_choice(),
            ],
            default=default,
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )
    _raise_if_back(ans)
    return bool(ans)


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

def ask_profile(mode: str = "create", allow_back: bool = False, default_profile: str = "readonly") -> str:
    if mode == "edit":
        step(t("estep_profile_t"), t("estep_profile_s"))
        question = t("q_new_type")
    else:
        step(t("step_profile_t"), t("step_profile_s"))
        question = t("q_create_type")
    choices = [Q.Choice(PROFILE_LABELS[k], value=k) for k in ("readonly", "readwrite", "admin", "custom")]
    if allow_back:
        choices.append(_back_choice())
        _maybe_back_hint("create")
    ans = _ask_or_abort(
        Q.select(
            question,
            choices=choices,
            default=default_profile,
            style=APP_STYLE, qmark="›",
            instruction=t("nav_hint"),
        )
    )
    _raise_if_back(ans)
    return ans


# ── Etapa 3: credenciais do novo usuário ──────────────────────────────────────

def ask_new_credentials(allow_back: bool = False, default_username: str = "") -> tuple[str, str]:
    step(t("step_creds_t"), t("step_creds_s"))
    if allow_back:
        _maybe_back_hint("create")
    username = (default_username or "").strip()
    need_username = True
    while True:
        if need_username:
            raw = _ask_or_abort(
                Q.text(t("q_new_name"), default=username, validate=_with_back_validator(validate_username), style=APP_STYLE, qmark="›")
            )
            if allow_back:
                _raise_if_back(raw)
            username = raw.strip()
        pwd = _ask_or_abort(
            Q.password(t("q_new_pass"), validate=_with_back_validator(validate_new_password), style=APP_STYLE, qmark="›")
        )
        if allow_back:
            if _is_back_keyword(pwd):
                need_username = True  # volta ao campo de usuário da mesma etapa
                continue
        confirm = _ask_or_abort(Q.password(t("q_confirm_pass"), style=APP_STYLE, qmark="›"))
        if allow_back:
            if _is_back_keyword(confirm):
                need_username = True
                continue
        if pwd != confirm:
            error(t("err_pw_mismatch"))
            need_username = False  # mantém o usuário, repete só a senha
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


def ask_user_metadata(
    admin: ClickHouseAdmin, ch_username: str,
    allow_back: bool = False, defaults: dict | None = None,
) -> UserMetadata:
    """Pergunta matrícula/nome/email + departamento (só da tabela — sem digitação livre)."""
    from clickhouse_users_cli.sql_builder import UserMetadata as _UM

    step(t("meta_step_t"), t("meta_step_s"))
    if allow_back:
        _maybe_back_hint("create")
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

    prev: dict = dict(defaults or {})
    # Navegação interna campo a campo: voltar no 1º campo volta à etapa
    # anterior (credenciais); nos demais volta ao campo anterior.
    values: dict = {
        "matricula": str(prev.get("matricula", "")),
        "nome": str(prev.get("nome_completo", prev.get("nome", ""))),
        "email": str(prev.get("email_corporativo", prev.get("email", ""))),
        "dept": prev.get("dept"),
    }
    order = ["matricula", "nome", "email", "dept"]
    idx = 0
    while idx < len(order):
        field = order[idx]
        if field == "matricula":
            raw = _ask_or_abort(
                Q.text(t("q_matricula"), default=values["matricula"], validate=_with_back_validator(validate_matricula), style=APP_STYLE, qmark="›")
            )
            if allow_back and _is_back_keyword(raw):
                if idx == 0:
                    raise BackStep()
                idx -= 1
                continue
            values["matricula"] = raw.strip()
        elif field == "nome":
            raw = _ask_or_abort(
                Q.text(t("q_full_name"), default=values["nome"], validate=_with_back_validator(validate_full_name), style=APP_STYLE, qmark="›")
            )
            if allow_back and _is_back_keyword(raw):
                idx -= 1
                continue
            values["nome"] = raw.strip()
        elif field == "email":
            raw = _ask_or_abort(
                Q.text(t("q_email"), default=values["email"], validate=_with_back_validator(validate_email), style=APP_STYLE, qmark="›")
            )
            if allow_back and _is_back_keyword(raw):
                idx -= 1
                continue
            values["email"] = raw.strip()
        else:
            # Departamento: apenas escolha da lista existente (nada de texto livre).
            choices = [Q.Choice(f"{d['nome']}" + (f" — {d['descricao']}" if d.get("descricao") else ""), value=d) for d in depts]
            default_dept = values["dept"] if values["dept"] in depts else None
            if allow_back:
                choices.append(_back_choice())
            dept = _ask_or_abort(
                Q.select(
                    t("q_dept"),
                    choices=choices,
                    **({"default": default_dept} if default_dept is not None else {}),
                    style=APP_STYLE, qmark="›",
                    instruction=t("nav_hint"),
                )
            )
            if allow_back and dept == BACK_VALUE:
                idx -= 1
                continue
            values["dept"] = dept
        idx += 1

    dept = values["dept"]
    return _UM(
        usuario=ch_username, matricula=values["matricula"], nome_completo=values["nome"],
        email_corporativo=values["email"], departamento_id=dept["id"], departamento_nome=dept["nome"],
        created_by=admin.conn.username,
    )


# ── Etapa 4: escopo (bancos → tabelas) ────────────────────────────────────────

def ask_databases(
    admin: ClickHouseAdmin, mode: str = "create",
    allow_back: bool = False, defaults: list[str] | None = None,
) -> list[str]:
    step(t("estep_dbs_t") if mode == "edit" else t("step_dbs_t"), t("scope_hint"))
    if allow_back:
        _maybe_back_hint("create")
    with console.status(t("listing_dbs"), spinner="dots"):
        try:
            databases = admin.list_databases()
        except Exception as e:
            error(t("err_list_dbs", e=e))
            raise SystemExit(1)

    if not databases:
        error(t("err_no_dbs"))
        raise SystemExit(1)

    prev = set(defaults or [])
    choices = [Q.Choice(title=t("all_dbs"), value="__ALL__")] + [
        Q.Choice(
            title=t("db_system_tag", db=db) if db in SYSTEM_DATABASES else db,
            value=db,
            # UX: nada pré-marcado (least privilege) — o usuário opta explicitamente.
            checked=(db in prev),
        )
        for db in databases
    ]
    if allow_back:
        choices.append(_back_choice())
    selected = _ask_or_abort(
        Q.checkbox(
            t("q_which_dbs"),
            choices=choices,
            validate=validate_at_least_one,
            style=APP_STYLE, qmark="›",
            instruction=t("check_hint"),
        )
    )
    if allow_back and BACK_VALUE in (selected or []):
        raise BackStep()
    if "__ALL__" in selected:
        return list(databases)
    return selected


def ask_tables(
    admin: ClickHouseAdmin, databases: list[str], mode: str = "create",
    allow_back: bool = False, defaults: list[GrantScope] | None = None,
) -> list[GrantScope]:
    step(t("estep_tables_t") if mode == "edit" else t("step_tables_t"), t("scope_tables_hint"))
    if allow_back:
        _maybe_back_hint("create")
    prev_by_db: dict[str, set[str | None]] = {}
    for s in defaults or []:
        prev_by_db.setdefault(s.database, set()).add(s.table)
    star_all = "*" in prev_by_db  # GRANT ON *.* vigente: tudo pré-marcado
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

        prev = prev_by_db.get(db, set())
        prev_all = star_all or None in prev or "*" in prev
        choices = [Q.Choice(title=t("all_tables", db=db), value="__ALL__", checked=prev_all)] + [
            Q.Choice(title=f"{db}.{t}", value=t, checked=(t in prev or prev_all)) for t in tables
        ]
        if allow_back:
            choices.append(_back_choice())
        picked: list[str] = _ask_or_abort(
            Q.checkbox(
                t("q_tables", db=db),
                choices=choices,
                validate=validate_at_least_one,
                style=APP_STYLE, qmark="›",
                instruction=t("check_hint"),
            )
        )
        if allow_back and BACK_VALUE in (picked or []):
            raise BackStep()
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


def ask_privileges(
    profile: str, mode: str = "create",
    allow_back: bool = False, defaults: tuple[list[str], bool] | None = None,
) -> tuple[list[str], bool]:
    """Retorna (privilégios, grant_option)."""
    if profile != "custom":
        grant_option = profile == "admin"
        return list(PROFILE_PRIVILEGES[profile]), grant_option

    step(t("estep_privs_t") if mode == "edit" else t("step_privs_t"), t("privs_hint"))
    if allow_back:
        _maybe_back_hint("create")
    prev_privs = list((defaults or ([], False))[0])
    prev_grant = bool((defaults or ([], False))[1])
    choices = [Q.Choice(f"{name:12} — {desc}", value=name, checked=(name in prev_privs)) for name, desc in PRIVILEGE_CHOICES]
    if allow_back:
        choices.append(_back_choice())
    privs: list[str] = _ask_or_abort(
        Q.checkbox(
            t("q_which_privs"),
            choices=choices,
            validate=validate_at_least_one,
            style=APP_STYLE, qmark="›",
        )
    )
    if allow_back and BACK_VALUE in (privs or []):
        raise BackStep()
    grant_option = False
    if any(p in privs for p in ("DROP", "TRUNCATE")):
        if allow_back:
            grant_option_confirm = _ask_confirm_or_back(t("q_destructive"), default=False)
        else:
            grant_option_confirm = _ask_or_abort(
                Q.confirm(t("q_destructive"), default=False, style=APP_STYLE, qmark="›")
            )
        if not grant_option_confirm:
            return ask_privileges("custom", mode=mode, allow_back=allow_back, defaults=defaults)
    else:
        if allow_back:
            grant_option = _ask_confirm_or_back(t("q_grant_option"), default=prev_grant)
        else:
            grant_option = _ask_or_abort(
                Q.confirm(t("q_grant_option"), default=False, style=APP_STYLE, qmark="›")
            )
    return privs, grant_option


def ask_host_restriction(
    allow_back: bool = False, default_mode: str = "any", default_hosts: str = "",
) -> list[str]:
    step(t("step_host_t"), t("step_host_s"))
    if allow_back:
        _maybe_back_hint("create")
    choices = [
        Q.Choice(t("host_any"), value="any"),
        Q.Choice(t("host_local"), value="localhost"),
        Q.Choice(t("host_custom"), value="custom"),
    ]
    if allow_back:
        choices.append(_back_choice())
    mode = _ask_or_abort(
        Q.select(
            t("q_allow_from"),
            choices=choices,
            default=default_mode if default_mode in ("any", "localhost", "custom") else "any",
            style=APP_STYLE, qmark="›",
        )
    )
    if allow_back:
        _raise_if_back(mode)
    if mode == "any":
        return []
    if mode == "localhost":
        return ["LOCALHOST"]
    raw = _ask_or_abort(
        Q.text(t("q_hosts"), default=default_hosts, validate=_with_back_validator(validate_required), style=APP_STYLE, qmark="›")
    )
    if allow_back:
        _raise_if_back(raw)
    return [h.strip() for h in raw.split(",") if h.strip()]


def ask_create_options(allow_back: bool = False, default: bool = True) -> bool:
    if allow_back:
        _maybe_back_hint("create")
        return _ask_confirm_or_back(t("q_if_not_exists"), default=default)
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


def confirm_and_execute(admin: ClickHouseAdmin, spec: UserSpec, meta: UserMetadata | None = None, allow_back: bool = False) -> None:
    show_review(spec, meta)
    if allow_back:
        nav = _ask_or_abort(
            Q.select(
                t("q_review_nav", username=spec.username),
                choices=[
                    Q.Choice(t("opt_create_confirm"), value="create"),
                    Q.Choice(t("opt_adjust"), value="adjust"),
                    Q.Choice(t("opt_cancel"), value="cancel"),
                ],
                default="create",
                style=APP_STYLE, qmark="›",
                instruction=t("nav_hint"),
            )
        )
        if nav == "adjust":
            raise BackStep()
        if nav == "cancel":
            console.print(t("nothing_done"))
            raise SystemExit(0)
    else:
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
    # Snapshot dos acessos em user_access (o que cada usuário tem acesso).
    try:
        admin.sync_user_access(spec.username, spec.privileges, spec.scopes, spec.grant_option)
    except Exception:
        pass
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
        Q.Choice(t("act_access"), value="access"),
        Q.Choice(t("act_logs"), value="logs"),
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
    try:
        accesses = admin.list_user_access(username)
    except Exception:
        accesses = []
    try:
        logs = admin.list_usage_logs(username, limit=5)
    except Exception:
        logs = []

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
        if meta.get("updated_at"):
            table.add_row(t("f_updated"), str(meta.get("updated_at", "")))
        table.add_row(t("f_deleted"), t("yes") if meta.get("deleted") else t("no"))
        table.add_row(t("f_deactivated"), t("yes") if meta.get("deactivated") else t("no"))
    else:
        table.add_row(t("f_dept"), t("meta_none"))
    table.add_row(t("col_grants"), "\n".join(grants) if grants else t("grants_none"))
    console.print(table)

    if accesses:
        acc = make_table(t("access_title", username=username, n=len(accesses)))
        acc.add_column(t("col_privs"), style="bold")
        acc.add_column(t("col_scope"), style="bold")
        acc.add_column(t("col_grant"), style="dim")
        for a in accesses:
            scope = f"{a['database']}.*" if not a.get("tabela") else f"{a['database']}.{a['tabela']}"
            acc.add_row(a.get("privilegios", ""), scope, t("yes") if a.get("grant_option") else t("no"))
        console.print(acc)
    else:
        info(t("access_none", username=username))

    if logs:
        lg = make_table(t("logs_title", username=username, n=len(logs)))
        lg.add_column(t("col_query"), style="dim")
        lg.add_column(t("col_tables"), style="bold")
        for e in logs:
            lg.add_row((e.get("query", "")[:80]), ", ".join(e.get("tabelas", []) or []))
        console.print(lg)

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
    """Redefine os acessos: REVOKE ALL + GRANTs novos (perfil + escopo + hosts intactos).

    Os acessos atuais (SHOW GRANTS FOR) vêm pré-marcados — para acrescentar
    algo, basta marcar o novo item e confirmar; o resto segue igual.
    """
    from clickhouse_users_cli.sql_builder import infer_profile, parse_grants

    step(t("step_edit_t"), t("step_edit_s"))
    if username == admin.conn.username:
        warn(t("self_warn_zero", username=username))

    # Estado atual = cache da edição. Falhou? Segue em branco (comportamento antigo).
    try:
        current_rows = admin.show_grants(username)
    except Exception:
        current_rows = []
    cur_privs, cur_scopes, cur_grant, hetero = parse_grants(current_rows)
    cur_profile = infer_profile(cur_privs, cur_grant) if cur_privs else "readonly"
    if hetero:
        info(t("edit_hetero_note"))
    if cur_scopes:
        info(t("edit_prefill_note", n=len(cur_scopes)))

    profile = ask_profile(mode="edit", default_profile=cur_profile)
    if profile == "custom":
        privileges, grant_option = ask_privileges(
            profile, mode="edit", defaults=(cur_privs, cur_grant),
        )
    else:
        privileges, grant_option = ask_privileges(profile, mode="edit")
    if profile == "admin":
        grant_option = True
    if any(s.database == "*" for s in cur_scopes):
        try:
            db_defaults: list[str] | None = admin.list_databases()
        except Exception:
            db_defaults = None
    else:
        db_defaults = sorted({s.database for s in cur_scopes})
    databases = ask_databases(admin, mode="edit", defaults=db_defaults or None)
    scopes = ask_tables(admin, databases, mode="edit", defaults=cur_scopes or None)

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
    try:  # mantém user_access espelhado com os grants reais
        admin.sync_user_access(username, privileges, scopes, grant_option)
    except Exception:
        pass


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
    """Assistente de criação com voltar: cada etapa aceita retornar à anterior.

    Os valores já digitados são reaproveitados como padrão ao avançar de novo,
    então corrigir uma etapa não obriga redigitar tudo.
    """
    state: dict = {}
    idx = 0
    while True:
        try:
            if idx == 0:
                state["profile"] = ask_profile(
                    allow_back=False, default_profile=state.get("profile", "readonly"),
                )
                idx = 1
            elif idx == 1:
                username, password = ask_new_credentials(
                    allow_back=True, default_username=state.get("username", ""),
                )
                state["username"], state["password"] = username, password
                idx = 2
            elif idx == 2:
                meta = ask_user_metadata(
                    admin, state["username"],
                    allow_back=True, defaults=state.get("meta_defaults"),
                )
                state["meta"] = meta
                state["meta_defaults"] = {
                    "matricula": meta.matricula,
                    "nome_completo": meta.nome_completo,
                    "email_corporativo": meta.email_corporativo,
                    "dept": {"id": meta.departamento_id, "nome": meta.departamento_nome},
                }
                idx = 3
            elif idx == 3:
                state["databases"] = ask_databases(
                    admin, allow_back=True, defaults=state.get("databases"),
                )
                idx = 4
            elif idx == 4:
                state["scopes"] = ask_tables(
                    admin, state["databases"], allow_back=True, defaults=state.get("scopes"),
                )
                idx = 5
            elif idx == 5:
                privileges, grant_option = ask_privileges(
                    state["profile"], allow_back=True, defaults=state.get("priv_defaults"),
                )
                if state["profile"] == "admin":
                    grant_option = True
                state["privileges"], state["grant_option"] = privileges, grant_option
                state["priv_defaults"] = (privileges, grant_option)
                idx = 6
            elif idx == 6:
                state["hosts"] = ask_host_restriction(
                    allow_back=True,
                    default_mode=state.get("host_mode", "any"),
                    default_hosts=state.get("hosts_text", ""),
                )
                # Guarda o modo p/ pré-selecionar ao voltar: [] = any, [LOCALHOST] = localhost.
                hosts = state["hosts"]
                if not hosts:
                    state["host_mode"] = "any"
                elif len(hosts) == 1 and hosts[0] == "LOCALHOST":
                    state["host_mode"] = "localhost"
                else:
                    state["host_mode"] = "custom"
                    state["hosts_text"] = ", ".join(hosts)
                idx = 7
            elif idx == 7:
                state["if_not_exists"] = ask_create_options(
                    allow_back=True, default=state.get("if_not_exists", True),
                )
                idx = 8
            else:
                spec = UserSpec(
                    username=state["username"],
                    password=state["password"],
                    privileges=state["privileges"],
                    scopes=state["scopes"],
                    hosts=state["hosts"],
                    if_not_exists=state.get("if_not_exists", True),
                    grant_option=state.get("grant_option", False),
                )
                confirm_and_execute(admin, spec, state.get("meta"), allow_back=True)
                return
        except BackStep:
            idx = max(0, idx - 1)
            info(t("back_to_prev"))
            continue


# ── Acessos + logs de utilização (auditoria) ──────────────────────────────────

def _pick_user(admin: ClickHouseAdmin) -> str | None:
    try:
        users = admin.list_users()
    except Exception as e:
        error(t("err_list_users", e=e))
        return None
    if not users:
        info(t("no_users"))
        return None
    return _ask_or_abort(
        Q.select(t("q_which_user"), choices=users, style=APP_STYLE, qmark="›", instruction=t("nav_hint"))
    )


def flow_show_access(admin: ClickHouseAdmin) -> None:
    step(t("step_access_t"), t("step_access_s"))
    ensure_metadata_schema(admin)
    target = _pick_user(admin)
    if not target:
        return
    try:
        accesses = admin.list_user_access(target)
    except Exception as e:
        error(t("err_op", e=e))
        return
    if not accesses:
        info(t("access_none", username=target))
        return
    table = make_table(t("access_title", username=target, n=len(accesses)))
    table.add_column(t("col_privs"), style="bold")
    table.add_column(t("col_scope"), style="bold")
    table.add_column(t("col_grant"), style="dim")
    for a in accesses:
        scope = f"{a['database']}.*" if not a.get("tabela") else f"{a['database']}.{a['tabela']}"
        table.add_row(a.get("privilegios", ""), scope, t("yes") if a.get("grant_option") else t("no"))
    console.print(table)


def flow_show_logs(admin: ClickHouseAdmin) -> None:
    step(t("step_logs_t"), t("step_logs_s"))
    ensure_metadata_schema(admin)
    target = _pick_user(admin)
    if not target:
        return
    sync = _ask_or_abort(Q.confirm(t("q_import_log", username=target), default=False, style=APP_STYLE, qmark="›"))
    if sync:
        with console.status(t("running"), spinner="dots"):
            try:
                admin.import_query_log(target, limit=100)
                success(t("logs_imported", username=target))
            except Exception as e:
                error(t("err_op", e=e))
                info(t("hint_query_log"))
    try:
        logs = admin.list_usage_logs(target, limit=20)
    except Exception as e:
        error(t("err_op", e=e))
        return
    if not logs:
        info(t("logs_none", username=target))
        return
    table = make_table(t("logs_title", username=target, n=len(logs)))
    table.add_column(t("col_when"), style="dim")
    table.add_column(t("col_query"), style="dim")
    table.add_column(t("col_tables"), style="bold")
    table.add_column(t("col_status"), style="dim")
    for e in logs:
        table.add_row(str(e.get("executada_em", "")), (e.get("query", "")[:80]), ", ".join(e.get("tabelas", []) or []), str(e.get("status", "")))
    console.print(table)


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
            elif action == "access":
                flow_show_access(admin)
            elif action == "logs":
                flow_show_logs(admin)
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
