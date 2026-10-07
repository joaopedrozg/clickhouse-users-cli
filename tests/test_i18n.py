"""Testes do i18n — paridade PT/EN, detecção e interpolação."""

import locale

from clickhouse_users_cli.i18n import STRINGS, detect_language, get_language, set_language, t


def test_key_parity():
    assert set(STRINGS["pt"]) == set(STRINGS["en"])
    assert len(STRINGS["pt"]) > 100


def test_interpolation_and_fallback():
    set_language("pt")
    assert t("q_port", port="8123") == "Porta HTTP(S) [8123]:"
    assert t("connected", username="u", host="h", port=1) == "Conectado como 'u' em h:1"
    assert t("chave_que_nao_existe") == "chave_que_nao_existe"
    set_language("en")
    assert t("q_port", port="8123") == "HTTP(S) port [8123]:"
    assert get_language() == "en"
    set_language("pt")


def _detect_with(env: dict, loc=(None, None)):
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, env, clear=False):
        with patch.object(locale, "getlocale", return_value=loc), patch.object(
            locale, "getdefaultlocale", return_value=(None, None)
        ):
            # limpa variáveis que poderiam interferir
            for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
                os.environ.pop(var, None)
            for k, v in env.items():
                os.environ[k] = v
            return detect_language()


def test_detect_language():
    assert _detect_with({"LANG": "pt_BR.UTF-8"}) == "pt"
    assert _detect_with({"LANG": "Portuguese_Brazil"}) == "pt"
    assert _detect_with({"LANG": "en_US.UTF-8"}) == "en"
    assert _detect_with({"LANG": "C"}) == "en"
    assert _detect_with({}) == "en"
    assert _detect_with({"CH_USERS_LANG": "pt", "LANG": "en_US.UTF-8"}) == "pt"
    assert _detect_with({"CH_USERS_LANG": "en", "LANG": "pt_BR.UTF-8"}) == "en"
