"""Internacionalização — PT/EN com detecção automática do idioma do SO.

Ordem de decisão: ``CH_USERS_LANG`` > locale do sistema (``locale`` + variáveis
``LANGUAGE/LC_ALL/LC_MESSAGES/LANG``) > inglês (padrão).
"""

from __future__ import annotations

import locale
import os
import re

SUPPORTED = ("pt", "en")

STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        "nav_hint": "(↑↓ navega · enter confirma)",
        "check_hint": "(espaço marca · enter confirma)",
        "op_cancelled": "\n[dim]Operação cancelada pelo usuário.[/]",
        "yes": "sim",
        "no": "não",
        # Banner
        "banner_tagline": "Crie usuários com escopo mínimo necessário",
        "banner_hints": "criar   ◆   listar   ◆   desativar   ◆   auditar",
        "banner_sub": "least privilege por padrão",
        # Conexão
        "step_conn_t": "1/6 · Conexão com o ClickHouse",
        "step_conn_s": "Use uma conta admin (ex.: default). Nada é salvo em disco.",
        "q_host": "Host do servidor:",
        "q_proto": "Protocolo:",
        "proto_http": "http — porta 8123 (rede local / sem TLS)",
        "proto_https": "https — porta 8443 (TLS, recomendado)",
        "q_port": "Porta HTTP(S) [{port}]:",
        "q_admin_user": "Usuário admin:",
        "q_admin_pass": "Senha do admin (enter = vazia):",
        "connecting": "[cyan]Conectando em {proto}://{host}:{port}…[/]",
        "connected": "Conectado como '{username}' em {host}:{port}",
        "retry_q": "Não foi possível conectar. O que fazer?",
        "retry_again": "Tentar de novo",
        "retry_edit": "Editar credenciais",
        "retry_exit": "Sair",
        # Perfil
        "step_profile_t": "2/6 · Tipo de usuário",
        "step_profile_s": "O perfil define os privilégios padrão (least privilege primeiro).",
        "q_create_type": "Que tipo de usuário criar?",
        "estep_profile_t": "Editar · Tipo de acesso",
        "estep_profile_s": "O perfil redefine os privilégios (os atuais serão zerados).",
        "q_new_type": "Qual o novo tipo de acesso?",
        "prof_readonly": "Somente leitura — SELECT + SHOW (analistas, BI)",
        "prof_readwrite": "Leitura + escrita — SELECT + SHOW + INSERT (engenheiros)",
        "prof_admin": "Administrador — ALL com GRANT OPTION (acesso total!)",
        "prof_custom": "Personalizado — eu escolho os privilégios",
        # Credenciais do novo usuário
        "step_creds_t": "3/6 · Novo usuário",
        "step_creds_s": "Nome segue regra do ClickHouse: letras, números e _ .",
        "q_new_name": "Nome do novo usuário:",
        "q_new_pass": "Senha do novo usuário (mín. 8 chars):",
        "q_confirm_pass": "Confirme a senha:",
        "err_pw_mismatch": "Senhas não conferem — tente de novo.",
        # Bancos
        "scope_hint": "Espaço marca · A confirma · Ctrl+A inverte a seleção.",
        "step_dbs_t": "4/6 · Escopo — bancos",
        "estep_dbs_t": "Editar · Escopo — bancos",
        "listing_dbs": "[cyan]Listando bancos…[/]",
        "err_list_dbs": "Falha ao listar bancos: {e}",
        "err_no_dbs": "Nenhum banco encontrado.",
        "all_dbs": "✓ Todos os bancos",
        "db_system_tag": "{db}  (sistema)",
        "q_which_dbs": "Em quais bancos o usuário terá acesso?",
        # Tabelas
        "step_tables_t": "4/6 · Escopo — tabelas",
        "estep_tables_t": "Editar · Escopo — tabelas",
        "scope_tables_hint": "Escolha '*' para o banco inteiro ou marque tabelas específicas.",
        "err_list_tables": "Falha ao listar tabelas de '{db}': {e} — usando '{db}.*'.",
        "info_no_tables": "Banco '{db}' sem tabelas — será concedido '{db}.*'.",
        "all_tables": "{db}.*  — todas as tabelas (atuais e futuras)",
        "q_tables": "Tabelas de '{db}':",
        # Privilégios
        "step_privs_t": "5/6 · Privilégios personalizados",
        "estep_privs_t": "Editar · Privilégios personalizados",
        "privs_hint": "Marque só o necessário — DROP/TRUNCATE exigem confirmação extra.",
        "q_which_privs": "Quais privilégios conceder?",
        "q_destructive": "Você marcou privilégio destrutivo. Tem certeza?",
        "q_grant_option": "Permitir repassar acessos (WITH GRANT OPTION)?",
        "priv_select": "Ler dados",
        "priv_show": "Ver bancos/tabelas/colunas",
        "priv_insert": "Inserir dados",
        "priv_create": "Criar bancos/tabelas/views",
        "priv_alter": "Alterar estrutura/config",
        "priv_drop": "Excluir bancos/tabelas — perigoso!",
        "priv_truncate": "Apagar todos os dados da tabela — perigoso!",
        "priv_optimize": "Otimizar partições",
        "priv_kill": "Cancelar queries em execução",
        # Origem (HOST)
        "step_host_t": "5/6 · Restrição de origem",
        "step_host_s": "De onde esse usuário poderá conectar?",
        "q_allow_from": "Permitir conexão de:",
        "host_any": "Qualquer host — HOST ANY (padrão, mais simples)",
        "host_local": "Somente localhost — HOST LOCALHOST",
        "host_custom": "IPs/hosts específicos — ex.: 10.0.0.5",
        "q_hosts": "Hosts/IPs (separados por vírgula):",
        # Opções de criação
        "q_if_not_exists": "Usar IF NOT EXISTS (não falha se o usuário já existir)?",
        # Revisão
        "step_review_t": "6/6 · Revisão",
        "step_review_s": "Confira o resumo e o SQL exato que será executado.",
        "review_title": "Resumo do novo usuário",
        "col_field": "Campo",
        "col_value": "Valor",
        "f_user": "Usuário",
        "f_privs": "Privilégios",
        "f_scope": "Escopo",
        "f_hosts": "Hosts",
        "f_grant_option": "GRANT OPTION",
        "hosts_any": "ANY (qualquer host)",
        "sql_to_run": "[dim]SQL a executar:[/]",
        "q_create_now": "Criar usuário '{username}' agora?",
        "nothing_done": "[dim]Nada foi executado.[/]",
        "running_ddl": "[cyan]Executando DDL…[/]",
        "err_create": "Falha ao criar usuário: {e}",
        "hint_create_perms": "Dica: verifique se sua conta admin tem permissão CREATE USER + GRANT.",
        "created": "Usuário '{username}' criado com {n} comando(s).",
        "test_hint": "Teste: clickhouse-client --user {username} --password '***' --query 'SHOW TABLES'",
        # Sessão salva
        "step_saved_t": "Sessão salva",
        "saved_file_note": "Arquivo: {path} (senha em texto puro — nunca compartilhe)",
        "saved_invalid_q": "A sessão salva está inválida. O que fazer?",
        "fix_delete": "Apagar e digitar nova conexão",
        "fix_keep": "Digitar nova conexão (manter arquivo)",
        "deleted": "Sessão apagada.",
        "saved_conn_info": "Conexão guardada: {proto}://{host}:{port} · usuário '{username}'.",
        "use_saved_q": "Usar a conexão salva?",
        "use_saved": "Usar conexão salva",
        "new_conn": "Nova conexão (digitar de novo)",
        "del_saved": "Apagar conexão salva",
        "remember_warn": "A senha será gravada em texto puro no arquivo — só use em máquina confiável.",
        "remember_q": "Manter conectado neste computador (salvar sessão)?",
        "saved_to": "Sessão salva em {path}",
        "none_saved": "Nenhuma sessão salva.",
        "step_forget_t": "Esquecer sessão",
        "forget_q": "Apagar a sessão salva (vai pedir credenciais na próxima vez)?",
        "nothing_deleted": "[dim]Nada foi apagado.[/]",
        # Menu
        "act_create": "Criar usuário — com privilégio mínimo",
        "act_list": "Listar usuários — SHOW USERS + grants",
        "act_manage": "Gerenciar usuário — acessos, desativar / reativar / excluir",
        "act_forget": "Esquecer sessão — apagar YAML salvo",
        "act_exit": "Sair",
        "q_what_do": "O que deseja fazer?",
        "bye": "[dim]Até logo![/]",
        "interrupted": "\n[dim]Interrompido. Nada foi executado.[/]",
        "unexpected": "Erro inesperado: {e}",
        # Listar
        "step_list_t": "Usuários · Lista",
        "step_list_s": "SHOW USERS — depois escolha um para ver grants.",
        "listing_users": "[cyan]Listando usuários…[/]",
        "err_list_users": "Falha ao listar usuários: {e}",
        "hint_show_users": "Dica: sua conta precisa de SHOW USERS / acesso a system.users.",
        "no_users": "Nenhum usuário encontrado.",
        "users_title": "{n} usuário(s)",
        "col_num": "#",
        "col_user": "Usuário",
        "q_see_details": "Ver detalhes (grants) de um usuário?",
        "q_which_user": "Qual usuário?",
        "err_details": "Falha ao ver detalhes de '{username}': {e}",
        "err_grants": "Falha ao ver grants de '{username}': {e}",
        "user_title": "Usuário {username}",
        "col_status": "Status",
        "col_grants": "Grants",
        "status_active": "ativo",
        "status_inactive": "inativo (HOST NONE)",
        "grants_none": "(nenhum grant explícito)",
        "current_def": "[dim]Definição atual:[/]",
        # Gerenciar / editar
        "step_manage_t": "Usuários · Gerenciar",
        "step_manage_s": "Desativar = HOST NONE (reversível). Excluir = DROP USER (definitivo).",
        "q_which_manage": "Qual usuário gerenciar?",
        "self_warn_deactivate": "'{username}' é o usuário conectado agora. Desativar/excluir pode te derrubar.",
        "opt_reactivate": "Reativar — ALTER USER … HOST ANY",
        "opt_deactivate": "Desativar — ALTER USER … HOST NONE (reversível)",
        "opt_edit": "Editar permissões — bancos/tabelas + tipo de acesso",
        "opt_drop": "Excluir — DROP USER (definitivo!)",
        "opt_back": "Voltar ao menu",
        "q_action": "Ação:",
        "lbl_deactivate": "Desativar '{target}' agora?",
        "lbl_activate": "Reativar '{target}' agora?",
        "lbl_drop": "EXCLUIR '{target}' em definitivo?",
        "running": "[cyan]Executando…[/]",
        "err_op": "Falha na operação: {e}",
        "hint_alter": "Dica: verifique se sua conta tem ALTER USER / DROP USER.",
        "done_deactivate": "Usuário '{target}' desativado (HOST NONE).",
        "done_activate": "Usuário '{target}' reativado (HOST ANY).",
        "done_drop": "Usuário '{target}' excluído.",
        "step_edit_t": "Usuários · Editar permissões",
        "step_edit_s": "Os acessos atuais serão zerados e reaplicados. Nada muda sem confirmação.",
        "self_warn_zero": "'{username}' é o usuário conectado agora. Zerar os próprios acessos pode te derrubar.",
        "new_access_title": "Novos acessos de '{username}'",
        "col_privs": "Privilégios",
        "col_scope": "Escopo",
        "col_grant": "Grant option",
        "sql_order_note": "[dim]SQL a executar (ordem importa: primeiro zera, depois concede):[/]",
        "q_apply": "Aplicar novos acessos a '{username}' agora?",
        "err_edit": "Falha ao editar acessos: {e}",
        "hint_edit": "Dica: a conta precisa de GRANT/REVOKE nos escopos envolvidos. Os acessos antigos podem ter sido zerados — confira com Listar.",
        "updated": "Acessos de '{username}' atualizados ({n} comando(s)).",
        # Validadores
        "v_required": "Valor obrigatório — digite algo para continuar.",
        "v_host_empty": "Informe o host (ex.: localhost ou 10.0.0.5).",
        "v_host_invalid": "Host inválido. Ex.: localhost, db.empresa.com, 10.0.0.5",
        "v_port_nonnumeric": "Porta deve ser numérica. Ex.: 8123 (http) ou 8443 (https).",
        "v_port_range": "Porta fora do intervalo 1–65535.",
        "v_user_invalid": "Use letras, números e _ , começando com letra ou _. Ex.: analyst_julho",
        "v_user_reserved": "'{v}' é reservado — escolha outro nome.",
        "v_pass_short": "Mínimo 8 caracteres (recomendado 12+ com letras + números).",
        "v_pass_long": "Máximo 128 caracteres.",
        "v_pick_one": "Selecione pelo menos 1 item (espaço marca, enter confirma).",
        # Camada de banco
        "db_no_dep": "Dependência 'clickhouse-connect' não instalada. Rode: pip install -r requirements.txt",
        "db_connect_fail": "Falha ao conectar em {proto}://{host}:{port}: {e}",
        "db_not_connected": "Não conectado. Chame .connect() primeiro.",
        # Sessão YAML
        "sess_no_yaml": "Dependência 'pyyaml' não instalada. Rode: pip install pyyaml",
        "sess_incomplete": "Arquivo de sessão incompleto (falta {e}). Apague e salve de novo.",
        "sess_read_fail": "Não foi possível ler a sessão salva: {e}",
        # SQL builder
        "sql_no_scope": "Nenhum escopo (banco/tabela) selecionado.",
        "sql_no_privs": "Nenhum privilégio selecionado.",
    },
    "en": {
        "nav_hint": "(↑↓ navigate · enter confirms)",
        "check_hint": "(space toggles · enter confirms)",
        "op_cancelled": "\n[dim]Operation cancelled by user.[/]",
        "yes": "yes",
        "no": "no",
        # Banner
        "banner_tagline": "Create users with the minimum required scope",
        "banner_hints": "create   ◆   list   ◆   disable   ◆   audit",
        "banner_sub": "least privilege by default",
        # Connection
        "step_conn_t": "1/6 · ClickHouse connection",
        "step_conn_s": "Use an admin account (e.g. default). Nothing is saved to disk.",
        "q_host": "Server host:",
        "q_proto": "Protocol:",
        "proto_http": "http — port 8123 (local network / no TLS)",
        "proto_https": "https — port 8443 (TLS, recommended)",
        "q_port": "HTTP(S) port [{port}]:",
        "q_admin_user": "Admin user:",
        "q_admin_pass": "Admin password (enter = empty):",
        "connecting": "[cyan]Connecting to {proto}://{host}:{port}…[/]",
        "connected": "Connected as '{username}' on {host}:{port}",
        "retry_q": "Could not connect. What now?",
        "retry_again": "Try again",
        "retry_edit": "Edit credentials",
        "retry_exit": "Exit",
        # Profile
        "step_profile_t": "2/6 · User type",
        "step_profile_s": "The profile sets the default privileges (least privilege first).",
        "q_create_type": "What kind of user to create?",
        "estep_profile_t": "Edit · Access type",
        "estep_profile_s": "The profile redefines privileges (current ones will be wiped).",
        "q_new_type": "What is the new access type?",
        "prof_readonly": "Read only — SELECT + SHOW (analysts, BI)",
        "prof_readwrite": "Read + write — SELECT + SHOW + INSERT (engineers)",
        "prof_admin": "Administrator — ALL with GRANT OPTION (full access!)",
        "prof_custom": "Custom — I pick the privileges",
        # New user credentials
        "step_creds_t": "3/6 · New user",
        "step_creds_s": "Name follows the ClickHouse rule: letters, numbers and _ .",
        "q_new_name": "New username:",
        "q_new_pass": "New user password (min. 8 chars):",
        "q_confirm_pass": "Confirm the password:",
        "err_pw_mismatch": "Passwords do not match — try again.",
        # Databases
        "scope_hint": "Space toggles · A confirms · Ctrl+A inverts the selection.",
        "step_dbs_t": "4/6 · Scope — databases",
        "estep_dbs_t": "Edit · Scope — databases",
        "listing_dbs": "[cyan]Listing databases…[/]",
        "err_list_dbs": "Failed to list databases: {e}",
        "err_no_dbs": "No databases found.",
        "all_dbs": "✓ All databases",
        "db_system_tag": "{db}  (system)",
        "q_which_dbs": "Which databases will the user access?",
        # Tables
        "step_tables_t": "4/6 · Scope — tables",
        "estep_tables_t": "Edit · Scope — tables",
        "scope_tables_hint": "Pick '*' for the whole database or select specific tables.",
        "err_list_tables": "Failed to list tables in '{db}': {e} — using '{db}.*'.",
        "info_no_tables": "Database '{db}' has no tables — '{db}.*' will be granted.",
        "all_tables": "{db}.*  — all tables (current and future)",
        "q_tables": "Tables in '{db}':",
        # Privileges
        "step_privs_t": "5/6 · Custom privileges",
        "estep_privs_t": "Edit · Custom privileges",
        "privs_hint": "Grant only what is needed — DROP/TRUNCATE ask for extra confirmation.",
        "q_which_privs": "Which privileges to grant?",
        "q_destructive": "You selected a destructive privilege. Are you sure?",
        "q_grant_option": "Allow passing access on (WITH GRANT OPTION)?",
        "priv_select": "Read data",
        "priv_show": "See databases/tables/columns",
        "priv_insert": "Insert data",
        "priv_create": "Create databases/tables/views",
        "priv_alter": "Alter structure/config",
        "priv_drop": "Drop databases/tables — dangerous!",
        "priv_truncate": "Delete all table data — dangerous!",
        "priv_optimize": "Optimize partitions",
        "priv_kill": "Kill running queries",
        # Origin (HOST)
        "step_host_t": "5/6 · Origin restriction",
        "step_host_s": "Where will this user connect from?",
        "q_allow_from": "Allow connections from:",
        "host_any": "Any host — HOST ANY (default, simplest)",
        "host_local": "Localhost only — HOST LOCALHOST",
        "host_custom": "Specific IPs/hosts — e.g. 10.0.0.5",
        "q_hosts": "Hosts/IPs (comma separated):",
        # Creation options
        "q_if_not_exists": "Use IF NOT EXISTS (won't fail if the user exists)?",
        # Review
        "step_review_t": "6/6 · Review",
        "step_review_s": "Check the summary and the exact SQL to run.",
        "review_title": "New user summary",
        "col_field": "Field",
        "col_value": "Value",
        "f_user": "User",
        "f_privs": "Privileges",
        "f_scope": "Scope",
        "f_hosts": "Hosts",
        "f_grant_option": "GRANT OPTION",
        "hosts_any": "ANY (any host)",
        "sql_to_run": "[dim]SQL to run:[/]",
        "q_create_now": "Create user '{username}' now?",
        "nothing_done": "[dim]Nothing was executed.[/]",
        "running_ddl": "[cyan]Running DDL…[/]",
        "err_create": "Failed to create user: {e}",
        "hint_create_perms": "Tip: check if your admin account has CREATE USER + GRANT.",
        "created": "User '{username}' created with {n} statement(s).",
        "test_hint": "Test: clickhouse-client --user {username} --password '***' --query 'SHOW TABLES'",
        # Saved session
        "step_saved_t": "Saved session",
        "saved_file_note": "File: {path} (plaintext password — never share it)",
        "saved_invalid_q": "The saved session is invalid. What now?",
        "fix_delete": "Delete it and type a new connection",
        "fix_keep": "Type a new connection (keep the file)",
        "deleted": "Session deleted.",
        "saved_conn_info": "Stored connection: {proto}://{host}:{port} · user '{username}'.",
        "use_saved_q": "Use the saved connection?",
        "use_saved": "Use saved connection",
        "new_conn": "New connection (type again)",
        "del_saved": "Delete saved connection",
        "remember_warn": "The password will be stored in plaintext — only use on a trusted machine.",
        "remember_q": "Stay signed in on this computer (save session)?",
        "saved_to": "Session saved to {path}",
        "none_saved": "No saved session.",
        "step_forget_t": "Forget session",
        "forget_q": "Delete the saved session (credentials will be asked next time)?",
        "nothing_deleted": "[dim]Nothing was deleted.[/]",
        # Menu
        "act_create": "Create user — with least privilege",
        "act_list": "List users — SHOW USERS + grants",
        "act_manage": "Manage user — access, disable / re-enable / delete",
        "act_forget": "Forget session — delete saved YAML",
        "act_exit": "Exit",
        "q_what_do": "What do you want to do?",
        "bye": "[dim]See you![/]",
        "interrupted": "\n[dim]Interrupted. Nothing was executed.[/]",
        "unexpected": "Unexpected error: {e}",
        # List
        "step_list_t": "Users · List",
        "step_list_s": "SHOW USERS — then pick one to see grants.",
        "listing_users": "[cyan]Listing users…[/]",
        "err_list_users": "Failed to list users: {e}",
        "hint_show_users": "Tip: your account needs SHOW USERS / access to system.users.",
        "no_users": "No users found.",
        "users_title": "{n} user(s)",
        "col_num": "#",
        "col_user": "User",
        "q_see_details": "See details (grants) of a user?",
        "q_which_user": "Which user?",
        "err_details": "Failed to show details of '{username}': {e}",
        "err_grants": "Failed to show grants of '{username}': {e}",
        "user_title": "User {username}",
        "col_status": "Status",
        "col_grants": "Grants",
        "status_active": "active",
        "status_inactive": "inactive (HOST NONE)",
        "grants_none": "(no explicit grants)",
        "current_def": "[dim]Current definition:[/]",
        # Manage / edit
        "step_manage_t": "Users · Manage",
        "step_manage_s": "Disable = HOST NONE (reversible). Delete = DROP USER (final).",
        "q_which_manage": "Which user to manage?",
        "self_warn_deactivate": "'{username}' is the user you are signed in with. Disabling/deleting it may lock you out.",
        "opt_reactivate": "Re-enable — ALTER USER … HOST ANY",
        "opt_deactivate": "Disable — ALTER USER … HOST NONE (reversible)",
        "opt_edit": "Edit permissions — databases/tables + access type",
        "opt_drop": "Delete — DROP USER (final!)",
        "opt_back": "Back to menu",
        "q_action": "Action:",
        "lbl_deactivate": "Disable '{target}' now?",
        "lbl_activate": "Re-enable '{target}' now?",
        "lbl_drop": "DELETE '{target}' permanently?",
        "running": "[cyan]Running…[/]",
        "err_op": "Operation failed: {e}",
        "hint_alter": "Tip: check if your account has ALTER USER / DROP USER.",
        "done_deactivate": "User '{target}' disabled (HOST NONE).",
        "done_activate": "User '{target}' re-enabled (HOST ANY).",
        "done_drop": "User '{target}' deleted.",
        "step_edit_t": "Users · Edit permissions",
        "step_edit_s": "Current access will be wiped and re-applied. Nothing changes without confirmation.",
        "self_warn_zero": "'{username}' is the user you are signed in with. Wiping your own access may lock you out.",
        "new_access_title": "New access for '{username}'",
        "col_privs": "Privileges",
        "col_scope": "Scope",
        "col_grant": "Grant option",
        "sql_order_note": "[dim]SQL to run (order matters: wipe first, then grant):[/]",
        "q_apply": "Apply new access to '{username}' now?",
        "err_edit": "Failed to edit access: {e}",
        "hint_edit": "Tip: the account needs GRANT/REVOKE on the scopes involved. Old access may have been wiped — check with List.",
        "updated": "Access of '{username}' updated ({n} statement(s)).",
        # Validators
        "v_required": "Value is required — type something to continue.",
        "v_host_empty": "Enter the host (e.g. localhost or 10.0.0.5).",
        "v_host_invalid": "Invalid host. E.g. localhost, db.company.com, 10.0.0.5",
        "v_port_nonnumeric": "Port must be numeric. E.g. 8123 (http) or 8443 (https).",
        "v_port_range": "Port out of range 1–65535.",
        "v_user_invalid": "Use letters, numbers and _, starting with a letter or _. E.g. analyst_july",
        "v_user_reserved": "'{v}' is reserved — pick another name.",
        "v_pass_short": "Minimum 8 characters (12+ with letters + numbers recommended).",
        "v_pass_long": "Maximum 128 characters.",
        "v_pick_one": "Select at least 1 item (space toggles, enter confirms).",
        # DB layer
        "db_no_dep": "Missing 'clickhouse-connect' dependency. Run: pip install -r requirements.txt",
        "db_connect_fail": "Failed to connect to {proto}://{host}:{port}: {e}",
        "db_not_connected": "Not connected. Call .connect() first.",
        # YAML session
        "sess_no_yaml": "Missing 'pyyaml' dependency. Run: pip install pyyaml",
        "sess_incomplete": "Saved session file is incomplete (missing {e}). Delete it and save again.",
        "sess_read_fail": "Could not read the saved session: {e}",
        # SQL builder
        "sql_no_scope": "No scope (database/table) selected.",
        "sql_no_privs": "No privileges selected.",
    },
}


def _split_candidates(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p for p in re.split(r"[:;]", raw) if p]


def detect_language() -> str:
    """Detecta 'pt' ou 'en' a partir do SO. Qualquer coisa fora PT cai em EN."""
    candidates: list[str] = [os.environ.get("CH_USERS_LANG", "")]
    try:
        loc = locale.getlocale()
        if loc and loc[0]:
            candidates.append(loc[0])
    except Exception:
        pass
    try:
        dloc = locale.getdefaultlocale()
        if dloc and dloc[0]:
            candidates.append(dloc[0])
    except Exception:
        pass
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        candidates.append(os.environ.get(var, ""))
    for raw in candidates:
        for part in _split_candidates(raw):
            code = part.strip().lower().replace("-", "_").split(".")[0].split("@")[0]
            if code.startswith("pt") or code.startswith("portuguese"):
                return "pt"
            if code.startswith("en") or code.startswith("english") or code.startswith("c.") or code == "c":
                return "en"
    return "en"


_current: str = detect_language()


def set_language(lang: str) -> str:
    """Fixa o idioma ('pt'|'en'). Retorna o idioma efetivo."""
    global _current
    _current = "pt" if lang.lower().startswith("pt") else "en"
    return _current


def get_language() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    """Tradução com interpolação {nome}. Chave ausente devolve a própria chave."""
    lang = _current if _current in SUPPORTED else "en"
    template = STRINGS[lang].get(key, STRINGS["en"].get(key, key))
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
