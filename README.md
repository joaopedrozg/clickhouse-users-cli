# ⬢ ClickHouse Users CLI

[![PyPI version](https://img.shields.io/pypi/v/clickhouse-users-cli.svg)](https://pypi.org/project/clickhouse-users-cli/)
[![Python](https://img.shields.io/pypi/pyversions/clickhouse-users-cli.svg)](https://pypi.org/project/clickhouse-users-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-00d7ff.svg)](https://opensource.org/licenses/MIT)

> Crie e gerencie usuários no ClickHouse com **privilégio mínimo** (*least privilege*) — sem decorar sintaxe de `GRANT`, sem acesso amplo por acidente.

CLI interativa em Python ([`questionary`](https://questionary.readthedocs.io/) + [`rich`](https://github.com/Textualize/rich)): ela pergunta, você marca com `espaço`, confere o **SQL exato com preview** e só então executa. Nada roda sem confirmação.

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                                 ╭──────────╮                                 ║
║                                 │ ▓▓▓▓▓▓▓▓ │                                 ║
║                                 │          │                                 ║
║                                 ╰──────────╯                                 ║
║                            ⬢ ClickHouse Users CLI                            ║
║                  Crie usuários com escopo mínimo necessário                  ║
║               criar   ◆   listar   ◆   desativar   ◆   auditar                ║
║                                                                              ║
╚═════════════════════════ least privilege por padrão ═════════════════════════╝
```

---

## 🚀 Instalação

```powershell
pip install clickhouse-users-cli
ch-users
```

| Cenário | Comando |
|---|---|
| Instalar / atualizar | `pip install -U clickhouse-users-cli` |
| Rodar | `ch-users` |
| Do código-fonte | `uv sync` + `uv run ch-users` |
| Requisitos | Python `>= 3.10` ([UV](https://docs.astral.sh/uv/) gerencia tudo via `uv.lock`) + conta admin no ClickHouse (ex.: `default`) |
| Idioma | Automático pelo sistema operacional: PT em sistemas em português, EN nos demais. Force com `CH_USERS_LANG=pt` ou `CH_USERS_LANG=en` |

---

## ⚡ Comece em 60 segundos

1. Rode `ch-users` e conecte com sua conta admin (host, protocolo, porta, usuário/senha — testado com `SELECT 1`).
2. Escolha **Criar usuário** → perfil `readonly` → nome + senha → marque os bancos/tabelas → confira o preview.
3. Confirme. Pronto — o SQL abaixo foi executado:

```sql
CREATE USER IF NOT EXISTS `analyst_julho` IDENTIFIED WITH plaintext_password BY '***' HOST ANY;
GRANT SHOW, SELECT ON `vendas`.`pedidos` TO `analyst_julho`;
GRANT SHOW, SELECT ON `vendas`.`clientes` TO `analyst_julho`;
```

---

## 🧭 Menu principal

Após conectar, o menu fica em loop — dá para fazer várias operações sem reconectar:

| Opção | O que faz |
|---|---|
| 🌱 **Criar usuário** | Fluxo guiado em 6 etapas (perfil → credenciais → escopo → hosts → revisão) |
| 📋 **Listar usuários** | Tabela via `SHOW USERS` + detalhe opcional (`SHOW CREATE USER` e `SHOW GRANTS FOR`) |
| 🛠️ **Gerenciar usuário** | Editar permissões · desativar · reativar · excluir |
| 🧹 **Esquecer sessão** | Apaga o YAML de conexão salva *(aparece só se existir)* |
| 👋 **Sair** | Encerra (Ctrl+C também sai limpo, sem executar nada) |

### Criar — as 6 etapas

1. 🔌 **Conexão** — host, protocolo (`http:8123` / `https:8443`), porta, usuário/senha admin. Falhou? Tentar de novo / editar / sair.
2. 🎭 **Tipo de usuário** — perfil com descrição (`readonly`, `readwrite`, `admin`, `custom`).
3. 🪪 **Novo usuário** — nome validado (letras, números, `_`; bloqueia `default`, `root`…) + senha com confirmação.
4. 🗂️ **Escopo** — `SHOW DATABASES` → marque bancos (nada vem marcado; há a opção `✓ Todos os bancos`) → por banco, marque tabelas ou `banco.*` (vale para tabelas futuras).
5. 🔑 **Privilégios + origem** — no `custom`, marque só o necessário (`DROP`/`TRUNCATE` pedem confirmação extra); depois `HOST ANY | LOCALHOST | IPs`.
6. 👀 **Revisão** — tabela-resumo + SQL com syntax highlight + confirmação final.

### Gerenciar — os 4 poderes

Escolhe 1 usuário, vê status (`HOST NONE` = inativo) + grants atuais, depois:

| Ação | SQL executado | Reversível? |
|---|---|---|
| ✏️ **Editar permissões** | `REVOKE ALL ON *.*` + novos `GRANTs` (perfil + escopo perguntados de novo, com frases próprias de edição) | ✅ ( reaplicando) |
| 🚫 **Desativar** | `ALTER USER \`nome\` HOST NONE` (bloqueia login, mantém grants) | ✅ via Reativar |
| ✅ **Reativar** | `ALTER USER \`nome\` HOST ANY` | — |
| 🗑️ **Excluir** | `DROP USER IF EXISTS \`nome\`` | ❌ definitivo |

> Todo DDL tem preview + confirmação com default **não**. Mexer no próprio usuário logado gera alerta extra. 👻

### 💾 Sessão salva (manter conectado)

- Após conectar, o CLI pergunta se quer **manter conectado**: salva `~/.ch-users/connection.yaml` (host, porta, protocolo, usuário, senha).
- Na próxima execução: **usar a salva · nova conexão · apagar a salva** (a senha nunca é exibida).
- ⚠️ A senha fica em **texto puro** no arquivo (`0600` no Linux/mac; no Windows vale o aviso em tela). Use só em máquina confiável — nunca compartilhe o arquivo.

---

## 🔐 Permissões que sua conta admin precisa

| Para… | Privilégio ClickHouse |
|---|---|
| Criar + conceder | `CREATE USER` + `GRANT` (nos escopos) |
| Listar / auditar | `SHOW USERS` (+ acesso aos grants) |
| Desativar / reativar / editar acessos | `ALTER USER` + `GRANT`/`REVOKE` nos escopos |
| Excluir | `DROP USER` |

Sem a permissão, o comando falha com mensagem amigável + dica — nada quebra pela metade sem aviso (na edição, se o `GRANT` falhar após o `REVOKE`, o CLI avisa para conferir em **Listar**).

---

## 🎭 Perfis (tipo de acesso)

| Perfil | Privilégios | Feito para |
|---|---|---|
| `readonly` | `SHOW, SELECT` | BI, analistas |
| `readwrite` | `SHOW, SELECT, INSERT` | Engenheiros, ingestão |
| `admin` | `ALL ... WITH GRANT OPTION` | ⚠️ Acesso total — cuidado! |
| `custom` | Você marca: `SELECT/SHOW/INSERT/CREATE/ALTER/DROP/TRUNCATE/OPTIMIZE/KILL QUERY` | Casos especiais |

---

## 🧠 Por que cada tela é do jeito que é

| Dado | Widget | Motivo |
|---|---|---|
| Host, porta, nomes, IPs | `text` + validação + `default` | Entrada livre com exemplo; `default` acelera localhost:8123 |
| Senhas | `password` mascarado | Não ecoa segredo; novo usuário pede confirmação |
| Protocolo / perfil / ação | `select` com descrição | Escolha única; descrição explica o impacto |
| Bancos, tabelas, privilégios | `checkbox` (espaço marca) | Multi-seleção; `banco.*` evita marcar 100 tabelas |
| Confirmações destrutivas | `confirm` com default seguro | O "não" é sempre o padrão |
| Progresso | spinner + cabeçalho de etapa | Você sempre sabe "onde estou" e o que está carregando |
| Revisão | tabela + SQL destacado | Sem caixa-preta: o SQL exato antes de executar |

Princípios: **opt-in explícito** (nada pré-marcado), **escape correto** (backticks em identificadores, aspas simples em strings), **SQL separado da UI** (`sql_builder.py` é puro e testável sem banco).

---

## 🧑‍💻 Desenvolvimento

```powershell
uv sync                  # instala tudo (usa uv.lock)
uv run ch-users          # roda o CLI do fonte
uv run python main.py    # alternativa direta
uv run pytest -q         # suíte de testes (44 testes, sem banco)
uv build                 # gera sdist + wheel em dist/
uvx twine check dist/*   # valida (inclusive este README)
uv publish               # publica (UV_PUBLISH_TOKEN)
```

Versão em fonte única: `clickhouse_users_cli/__init__.py` (`__version__`).

> 🤖 **CI**: todo merge na `main` publica sozinho via `.github/workflows/publish.yml` — incrementa o patch, commita (`[skip ci]`), builda e sobe ao PyPI com o secret `KEI_API_PYPI`.

```
main.py                  # entrypoint (dev local)
pyproject.toml           # build + metadados PyPI (comando: ch-users)
uv.lock                  # dependências travadas
.python-version          # Python do projeto (uv)
clickhouse_users_cli/
  __init__.py            # __version__
  app.py                 # fluxos interativos (criar, listar, gerenciar, sessão)
  db.py                  # clickhouse-connect: connect, SHOWs, DDL
  session.py             # sessão YAML local (salvar/carregar/apagar)
  sql_builder.py         # CREATE/ALTER/DROP/GRANT/REVOKE puros (testável)
  validators.py          # validações por tipo de input
  style.py               # banner, etapas, tabelas e mensagens (Rich)
```

---

## 📝 Changelog

| Versão | Novidade |
|---|---|
| `0.1.4` | Frases próprias no modo edição (sem `2/6`, `4/6` da criação) |
| `0.1.3` | Editar permissões (`REVOKE ALL` + novos `GRANTs`) |
| `0.1.2` | Sessão salva em YAML + visual profissional (banner, badges, tabelas) |
| `0.1.1` | Lista sem pré-seleção + opção `✓ Todos os bancos` |
| `0.1.0` | Criar, listar e gerenciar (desativar/reativar/excluir) |

---

## 📄 Licença

MIT — veja [LICENSE](LICENSE).
