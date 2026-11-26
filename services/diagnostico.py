"""
Diagnóstico de conexão (banco PostgreSQL/Supabase e Supabase Storage).

Exibido quando a inicialização falha. Nunca mostra senhas nem chaves: apenas
o que foi detectado, o resultado de cada teste e a causa provável com a correção.
"""
from __future__ import annotations

import os
import re

from sqlalchemy import text
from sqlalchemy.engine import make_url

# (padrão no texto do erro, causa provável e correção)
_DICAS_BANCO = [
    (r'host name "db\.[^"]+\.supabase\.co"|db\.[a-z0-9]+\.supabase\.co.*(unreachable|translate)',
     "Você está usando a **conexão direta** (`db.<ref>.supabase.co`), que só funciona via IPv6 — o Streamlit "
     "Cloud não tem IPv6. No Supabase, clique em **Connect**, escolha **Session pooler** e copie essa string "
     "(host `aws-...pooler.supabase.com`, usuário `postgres.<ref>`)."),
    (r'role "[^"]+" does not exist',
     "Usuário inexistente. No Session pooler o usuário é `postgres.<ref-do-projeto>`; na conexão direta, `postgres`."),
    (r"tenant or user not found",
     "Usuário ou região do pooler incorretos. No Session pooler o usuário é "
     "`postgres.<ref-do-projeto>` (com o ponto) e o host deve ser exatamente o mostrado em "
     "**Connect › Session pooler** (a região, ex.: `aws-0-sa-east-1`, precisa ser a do seu projeto)."),
    (r"password authentication failed|authentication failed",
     "Senha do banco incorreta. Redefina em **Project Settings › Database › Reset database password** "
     "e atualize a `DATABASE_URL` (use uma senha só com letras e números)."),
    (r"network is unreachable|cannot assign requested address|address family|2600:|2a05:",
     "Conexão direta (`db.<ref>.supabase.co`) só funciona via IPv6, que o Streamlit Cloud não tem. "
     "Use a string do **Session pooler** (`aws-0-...pooler.supabase.com`)."),
    (r"could not translate host name|name or service not known|nodename nor servname",
     "Host não encontrado. Confira o endereço na `DATABASE_URL`. Se a senha tiver `@`, `:`, `/`, `#` ou `?`, "
     "ela quebra a URL — troque a senha por uma só com letras e números."),
    (r"invalid integer value|invalid port|port.*invalid",
     "URL malformada (provável caractere especial na senha, como `@` ou `:`). "
     "Use uma senha só com letras e números."),
    (r"connection refused",
     "Conexão recusada: host ou porta incorretos. Para o Session pooler use a porta **5432** e o host "
     "exatamente como aparece em **Connect › Session pooler**."),
    (r"timeout|timed out",
     "Tempo de conexão esgotado. Confira host e porta (5432 para o Session pooler) e se o projeto "
     "Supabase não está pausado (projetos gratuitos pausam após inatividade)."),
    (r"max clients|too many connections|remaining connection slots",
     "Limite de conexões do pooler atingido. Aguarde alguns minutos e reinicie o app."),
    (r"\[password\]|%5bpassword%5d|your-password",
     "A `DATABASE_URL` ainda contém o texto de exemplo `[YOUR-PASSWORD]`. Substitua pela senha real, sem colchetes."),
]

_DICAS_STORAGE = [
    (r"HTTP 401|HTTP 403|invalid compact jws|invalid api key|unauthorized|signature",
     "Chave recusada. Use a **Secret key** (`sb_secret_...`) ou a **service_role** em "
     "`SUPABASE_SERVICE_KEY` — não a publishable/anon. Copie sem espaços nem aspas extras."),
    (r"HTTP 404|not found",
     "Endereço não encontrado. `SUPABASE_URL` deve ser só `https://<ref>.supabase.co`, sem `/rest/v1` "
     "ou outros caminhos."),
    (r"PÚBLICO",
     "O bucket `evidencias` está público. No Supabase: **Storage › evidencias › Edit bucket** e desmarque "
     "*Public bucket*."),
    (r"name or service not known|failed to resolve|max retries|connection",
     "Não foi possível acessar o Supabase. Confira se `SUPABASE_URL` está correta e o projeto não está pausado."),
]


def _dica(erro: str, dicas: list[tuple[str, str]]) -> str:
    for padrao, texto in dicas:
        if re.search(padrao, erro, re.IGNORECASE):
            return texto
    return "Veja a mensagem técnica abaixo."


def _mascarar(texto: str) -> str:
    """Remove senhas/chaves que possam aparecer em mensagens de erro."""
    for var in ("SUPABASE_SERVICE_KEY", "SMTP_PASSWORD"):
        valor = os.getenv(var)
        if valor and len(valor) > 4:
            texto = texto.replace(valor, "****")
    url = os.getenv("DATABASE_URL", "")
    try:
        senha = make_url(url).password if url else None
    except Exception:  # noqa: BLE001
        senha = None
    if senha:
        texto = texto.replace(senha, "****")
    return re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1****@", texto)


def resumo_configuracao() -> list[dict]:
    """O que foi lido dos Secrets/ambiente (sem valores sensíveis)."""
    linhas = []
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        linhas.append({"Item": "DATABASE_URL", "Situação": "❌ não encontrada (usando SQLite local)"})
    else:
        try:
            u = make_url(url.strip('"').strip("'"))
            alerta = ""
            if u.host and u.host.startswith("db.") and u.host.endswith(".supabase.co"):
                alerta = " ⚠️ conexão direta (IPv6) — use o Session pooler"
            elif u.host and "pooler.supabase.com" in u.host and u.username and "." not in u.username:
                alerta = " ⚠️ no pooler o usuário deve ser postgres.<ref>"
            if u.password and re.search(r"[\[\]]|YOUR-PASSWORD", u.password, re.IGNORECASE):
                alerta += " ⚠️ senha ainda é o texto de exemplo"
            linhas.append({"Item": "DATABASE_URL",
                           "Situação": f"✅ host `{u.host}` · porta `{u.port}` · usuário `{u.username}` · "
                                       f"banco `{u.database}` · senha {'informada' if u.password else '❌ ausente'}"
                                       + alerta})
        except Exception as exc:  # noqa: BLE001
            linhas.append({"Item": "DATABASE_URL", "Situação": f"❌ formato inválido: {_mascarar(str(exc))}"})
    sb_url = os.getenv("SUPABASE_URL", "").strip()
    chave = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    linhas.append({"Item": "SUPABASE_URL", "Situação": f"✅ `{sb_url}`" if sb_url else "❌ não encontrada"})
    if chave:
        tipo = ("secret (sb_secret_)" if chave.startswith("sb_secret_") else
                "⚠️ publishable — não serve, use a secret" if chave.startswith("sb_publishable_") else
                "JWT (service_role ou anon — precisa ser service_role)" if chave.startswith("eyJ") else
                "⚠️ formato não reconhecido")
        linhas.append({"Item": "SUPABASE_SERVICE_KEY", "Situação": f"✅ informada · tipo: {tipo}"})
    else:
        linhas.append({"Item": "SUPABASE_SERVICE_KEY", "Situação": "❌ não encontrada (evidências no disco local)"})
    return linhas


def testar_conexoes() -> list[dict]:
    """Testa banco e storage separadamente. Retorna [{etapa, ok, dica, erro}]."""
    from database import db_manager as db
    from services.storage import obter_storage

    resultados = []
    try:
        with db.engine.connect() as con:
            con.execute(text("SELECT 1"))
        resultados.append({"etapa": f"Banco de dados ({db.descricao_backend()['banco']})", "ok": True,
                           "dica": "", "erro": ""})
    except Exception as exc:  # noqa: BLE001
        erro = _mascarar(str(exc))
        resultados.append({"etapa": "Banco de dados", "ok": False, "dica": _dica(erro, _DICAS_BANCO),
                           "erro": erro})
    try:
        obter_storage().preparar()
        resultados.append({"etapa": f"Evidências ({obter_storage().nome})", "ok": True, "dica": "", "erro": ""})
    except Exception as exc:  # noqa: BLE001
        erro = _mascarar(str(exc))
        resultados.append({"etapa": f"Evidências ({obter_storage().nome})", "ok": False,
                           "dica": _dica(erro, _DICAS_STORAGE), "erro": erro})
    return resultados
