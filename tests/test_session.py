"""Testes da sessão YAML — roundtrip em diretório temporário."""

import pytest

from clickhouse_users_cli import session as s
from clickhouse_users_cli.db import ConnectionInfo
from clickhouse_users_cli.i18n import set_language


@pytest.fixture(autouse=True)
def _tmp_session(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(s, "SESSION_FILE", tmp_path / "connection.yaml")
    set_language("pt")
    yield


def _conn():
    return ConnectionInfo(host="db.empresa.com", port=8443, secure=True,
                          username="default", password="s3cr3t!")


def test_roundtrip():
    assert not s.has_saved_session()
    path = s.save_session(_conn())
    assert path.is_file()
    assert s.has_saved_session()
    back = s.load_session()
    assert (back.host, back.port, back.secure, back.username, back.password) == \
        ("db.empresa.com", 8443, True, "default", "s3cr3t!")


def test_delete():
    s.save_session(_conn())
    assert s.delete_session() is True
    assert not s.has_saved_session()
    assert s.delete_session() is False


def test_load_missing_is_friendly():
    with pytest.raises(RuntimeError):
        s.load_session()


def test_load_corrupt_is_friendly():
    s.SESSION_FILE.write_text("{{{ nao: [yaml valido", encoding="utf-8")
    with pytest.raises(RuntimeError):
        s.load_session()


def test_load_incomplete_points_missing_key():
    s.SESSION_FILE.write_text("host: x\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="incompleto"):
        s.load_session()
