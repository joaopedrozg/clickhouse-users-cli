"""Estilo centralizado (UI) + helpers de apresentação com Rich."""

from questionary import Style
from rich.align import Align
from rich.box import DOUBLE, ROUNDED
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from clickhouse_users_cli import __version__
from clickhouse_users_cli.i18n import t

console = Console()

CYAN = "#00d7ff"
MAGENTA = "#c792ea"
GREEN = "#00ff87"
RED = "#ff5555"
AMBER = "#ffcb6b"
MUTED = "#6c7086"
BORDER = "#3a3f4b"

# Estilo questionary: alto contraste, foco visível, perigo em vermelho.
# Mantém a navegação por teclado óbvia (setas + espaço + enter).
APP_STYLE = Style(
    [
        ("qmark", "fg:#00d7ff bold"),       # "?" das perguntas
        ("question", "fg:#ffffff bold"),     # texto da pergunta
        ("answer", "fg:#00ff87 bold"),       # resposta escolhida
        ("pointer", "fg:#00d7ff bold"),      # "»" do item focado
        ("highlighted", "fg:#00d7ff bold"), # item focado
        ("selected", "fg:#00ff87"),          # checkbox marcado "●"
        ("separator", "fg:#6c7086"),
        ("instruction", "fg:#a6adc8 italic"),
        ("text", "fg:#ffffff"),
        ("disabled", "fg:#6c7086 italic"),
    ]
)


def _logo_title() -> Text:
    """Título em degradê ciano → magenta."""
    t = Text(no_wrap=True)
    t.append("⬢ ", style=f"bold {CYAN}")
    t.append("ClickHouse", style=f"bold {CYAN}")
    t.append(" ", style="bold")
    t.append("Users CLI", style=f"bold {MAGENTA}")
    return t


def banner() -> None:
    mark = Text("╭──────────╮\n│ ▓▓▓▓▓▓▓▓ │\n│          │\n╰──────────╯", style=f"bold {CYAN}", justify="center")
    body = Group(
        Align.center(mark),
        Align.center(_logo_title()),
        Align.center(Text(t("banner_tagline"), style="dim")),
        Align.center(Text(t("banner_hints"), style=f"bold {CYAN}")),
    )
    console.print(
        Panel(
            body,
            box=DOUBLE,
            border_style=CYAN,
            title=f"[black on {CYAN}] v{__version__} ",
            subtitle=f"[dim]{t('banner_sub')}[/]",
            padding=(1, 4),
        )
    )


def step(title: str, subtitle: str = "") -> None:
    """Cabeçalho de etapa — orienta o usuário sobre 'onde estou' no fluxo."""
    console.print()
    console.print(Rule(f"[black on {CYAN}] {title} [/]", style=CYAN))
    if subtitle:
        console.print(f"  [dim]{subtitle}[/]")


def make_table(title: str) -> Table:
    """Tabela padrão: bordas arredondadas, cabeçalho ciano."""
    return Table(
        title=f"[bold white]{title}[/]",
        show_header=True,
        header_style=f"bold {CYAN}",
        border_style=BORDER,
        box=ROUNDED,
        show_lines=False,
        padding=(0, 1),
    )


def success(msg: str) -> None:
    console.print(f"[black on {GREEN}] ✔ [/] [bold {GREEN}]{msg}[/]")


def error(msg: str) -> None:
    console.print(
        Panel(
            f"[bold {RED}]{msg}[/]",
            title=f"[bold {RED}]✘ Erro[/]",
            border_style=RED,
            box=ROUNDED,
            padding=(0, 1),
        )
    )


def warn(msg: str) -> None:
    console.print(f"[black on {AMBER}] ! [/] [{AMBER}]{msg}[/]")


def info(msg: str) -> None:
    console.print(f"[dim]▸ {msg}[/]")
