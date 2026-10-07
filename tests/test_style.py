"""Smoke tests visuais — nada pode quebrar ao renderizar."""

from clickhouse_users_cli import style
from clickhouse_users_cli.i18n import set_language


def test_render_pt_and_en(capfd):
    for lang in ("pt", "en"):
        set_language(lang)
        style.banner()
        style.step("4/6 · Teste", "subtítulo")
        style.success("ok")
        style.error("falhou")
        style.warn("atenção")
        style.info("dica")
        table = style.make_table("Título")
        table.add_column("A")
        table.add_row("1")
        style.console.print(table)
    set_language("pt")
    out, _ = capfd.readouterr()
    assert "ClickHouse Users CLI" in out
