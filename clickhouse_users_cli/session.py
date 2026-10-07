"""Sessão local opcional — salva a conexão admin em YAML para reutilizar.

Segurança: a senha fica em texto puro no arquivo. O arquivo é criado com
permissão restrita (0600 no POSIX) e o salvamento é sempre opt-in explícito.
"""

from __future__ import annotations

import os
from pathlib import Path

from clickhouse_users_cli.db import ConnectionInfo
from clickhouse_users_cli.i18n import t

SESSION_DIR = Path.home() / ".ch-users"
SESSION_FILE = SESSION_DIR / "connection.yaml"


def has_saved_session() -> bool:
    return SESSION_FILE.is_file()


def save_session(conn: ConnectionInfo) -> Path:
    """Grava a conexão em YAML com permissão restrita. Retorna o caminho."""
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(t("sess_no_yaml")) from e

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": conn.host,
        "port": conn.port,
        "secure": conn.secure,
        "username": conn.username,
        "password": conn.password,
    }
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
    try:
        os.chmod(SESSION_FILE, 0o600)
    except OSError:
        pass  # Windows: melhor esforço; o aviso em tela cobre o risco
    return SESSION_FILE


def load_session() -> ConnectionInfo:
    """Lê o YAML e devolve ConnectionInfo. Erro amigável se ausente/corrompido."""
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(t("sess_no_yaml")) from e

    try:
        with open(SESSION_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return ConnectionInfo(
            host=str(data["host"]),
            port=int(data["port"]),
            secure=bool(data["secure"]),
            username=str(data["username"]),
            password=str(data.get("password") or ""),
        )
    except KeyError as e:
        raise RuntimeError(t("sess_incomplete", e=e)) from e
    except Exception as e:
        # OSError, ValueError, TypeError, yaml.YAMLError… — qualquer falha de
        # leitura/parse vira mensagem amigável em vez de stack trace.
        raise RuntimeError(t("sess_read_fail", e=e)) from e


def delete_session() -> bool:
    """Apaga o YAML. Retorna True se algo foi removido."""
    try:
        SESSION_FILE.unlink()
        return True
    except FileNotFoundError:
        return False
