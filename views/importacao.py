"""Módulo 1 — Importação de planilhas, saneamento de dados e gestão de lotes."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from database import db_manager as db
from services.utils import (fmt_data_hora, formatar_cnpj, limpar_cnpj, limpar_email,
                            normalizar_nome_coluna, validar_cnpj, validar_email)
from ui import components as ui

# Variações aceitas para cada coluna (comparadas já normalizadas: sem acento/espaço/caixa)
ALIASES = {
    "Razao_Social": ["razaosocial", "razao", "nomeempresarial", "empresa", "nome", "nomeempresa",
                     "denominacao", "nomerazaosocial"],
    "CNPJ": ["cnpj", "cnpjempresa", "nrcnpj", "numerocnpj", "cpfcnpj", "documento"],
    "CNAE": ["cnae", "cnaeprincipal", "codigocnae", "cnaefiscal", "codcnae", "atividadeprincipal"],
    "Email": ["email", "emailempresa", "correioeletronico", "enderecoeletronico", "emailcontato",
              "contatoemail"],
    "Descricao_CNAE": ["descricaocnae", "desccnae", "cnaedescricao", "descricaoatividade",
                       "descricao", "atividade", "descricaocnaeprincipal"],
}
OBRIGATORIAS = ["Razao_Social", "CNPJ", "CNAE", "Email"]
NAO_MAPEAR = "— não mapear —"


def _ler_arquivo(arquivo) -> pd.DataFrame:
    nome = arquivo.name.lower()
    dados = arquivo.getvalue()
    if nome.endswith(".csv"):
        for enc in ("utf-8-sig", "latin-1"):
            try:
                return pd.read_csv(io.BytesIO(dados), sep=None, engine="python", dtype=str, encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError("Não foi possível decodificar o CSV (use UTF-8 ou Latin-1).")
    return pd.read_excel(io.BytesIO(dados), dtype=str)


def _sugerir_mapeamento(colunas: list[str]) -> dict[str, str]:
    norm = {c: normalizar_nome_coluna(c) for c in colunas}
    sugestao = {}
    for alvo, aliases in ALIASES.items():
        for alias in [normalizar_nome_coluna(alvo)] + aliases:
            achada = next((c for c, n in norm.items() if n == alias and c not in sugestao.values()), None)
            if achada:
                sugestao[alvo] = achada
                break
    return sugestao


def _sanear(df: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    def col(nome):
        origem = mapa.get(nome)
        if not origem or origem == NAO_MAPEAR:
            return pd.Series([""] * len(df), index=df.index)
        return df[origem].fillna("").astype(str).str.strip()

    out = pd.DataFrame({
        "razao_social": col("Razao_Social").str.upper().str.replace(r"\s+", " ", regex=True),
        "cnpj_limpo": col("CNPJ").map(limpar_cnpj),
        "cnae": col("CNAE").str.replace(r"\.0$", "", regex=True),
        "descricao_cnae": col("Descricao_CNAE"),
        "email": col("Email").map(limpar_email),
    })
    out["cnpj"] = out["cnpj_limpo"].map(formatar_cnpj)
    out["cnpj_valido"] = out["cnpj_limpo"].map(validar_cnpj)
    out["email_valido"] = out["email"].map(validar_email)
    out["duplicado_arquivo"] = out["cnpj_limpo"].duplicated(keep="first") & (out["cnpj_limpo"] != "")
    existentes = db.cnpjs_existentes([c for c in out["cnpj_limpo"].unique() if c])
    out["ja_cadastrado"] = out["cnpj_limpo"].isin(existentes.keys())
    out["lote_existente"] = out["cnpj_limpo"].map(lambda c: existentes.get(c, {}).get("lote", ""))
    out["status_existente"] = out["cnpj_limpo"].map(lambda c: existentes.get(c, {}).get("status", ""))
    return out


def _aba_importar() -> None:
    st.markdown("#### 1. Arquivo de origem")
    arquivo = st.file_uploader("Planilha de empresas (.xlsx ou .csv)", type=["xlsx", "csv"])
    st.caption("Colunas obrigatórias: **Razao_Social, CNPJ, CNAE, Email** · opcional: **Descricao_CNAE**. "
               "Variações de nome são reconhecidas automaticamente. Gere um arquivo de teste com "
               "`python scripts/gerar_planilha_exemplo.py`.")
    if not arquivo:
        return
    try:
        df = _ler_arquivo(arquivo)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Erro ao ler o arquivo: {exc}")
        return
    df = df.dropna(how="all")
    if df.empty:
        st.warning("A planilha está vazia.")
        return
    st.success(f"{len(df)} linha(s) lida(s) de **{arquivo.name}**.")

    st.markdown("#### 2. Mapeamento de colunas")
    colunas = list(df.columns)
    sugestao = _sugerir_mapeamento(colunas)
    opcoes = [NAO_MAPEAR] + colunas
    mapa = {}
    cols = st.columns(5)
    for i, alvo in enumerate(OBRIGATORIAS + ["Descricao_CNAE"]):
        padrao = sugestao.get(alvo, NAO_MAPEAR)
        rotulo = f"{alvo}{' *' if alvo in OBRIGATORIAS else ' (opcional)'}"
        mapa[alvo] = cols[i].selectbox(rotulo, opcoes, index=opcoes.index(padrao),
                                       key=f"map_{alvo}_{arquivo.name}")
    faltando = [c for c in OBRIGATORIAS if mapa[c] == NAO_MAPEAR]
    if faltando:
        st.error(f"Mapeie as colunas obrigatórias: {', '.join(faltando)}.")
        return

    st.markdown("#### 3. Lote / Operação")
    c1, c2, c3 = st.columns([3, 1.2, 3])
    nome_lote = c1.text_input("Nome do Lote / Operação *",
                              placeholder="Ex.: Operação Construção Civil – Dez/2026")
    is_teste = c2.checkbox("Lote de teste", help="Use para testes com e-mails de servidores. "
                           "Envios de teste não contam no aquecimento gradual e o lote pode "
                           "ser excluído depois.")
    observacao = c3.text_input("Observação (opcional)")

    base = _sanear(df, mapa)
    sem_cnpj = base["cnpj_limpo"].str.len() != 14
    cnpj_dv_invalido = ~base["cnpj_valido"] & ~sem_cnpj
    sem_razao = base["razao_social"] == ""

    st.markdown("#### 4. Saneamento e prévia")
    ui.linha_kpis([
        (len(base), "Linhas"),
        (int((~base["email_valido"]).sum()), "E-mails inválidos", "aviso"),
        (int(sem_cnpj.sum() + sem_razao.sum()), "Sem CNPJ / Razão (descartadas)", "alerta"),
        (int(cnpj_dv_invalido.sum()), "CNPJ c/ DV inválido", "aviso"),
        (int(base["duplicado_arquivo"].sum()), "Duplicados no arquivo", "neutro"),
        (int(base["ja_cadastrado"].sum()), "Já cadastrados no banco", "alerta"),
    ])
    st.write("")

    politica = "ignorar"
    if base["ja_cadastrado"].any():
        st.warning(f"⚠️ **{int(base['ja_cadastrado'].sum())} CNPJ(s) já existem no banco de dados.** "
                   "Escolha como tratá-los:")
        politica = st.radio("Tratamento de duplicados", ["ignorar", "atualizar"], horizontal=True,
                            format_func=lambda x: {"ignorar": "Ignorar duplicados (manter cadastro atual)",
                                                   "atualizar": "Atualizar dados cadastrais "
                                                                "(mantém status e histórico)"}[x])
        with st.expander("Ver CNPJs já cadastrados"):
            st.dataframe(base.loc[base["ja_cadastrado"], ["cnpj", "razao_social", "lote_existente",
                                                          "status_existente"]], hide_index=True)

    c1, c2 = st.columns(2)
    importar_invalidos = c1.checkbox("Importar empresas com e-mail inválido/ausente "
                                     f"(status “{db.ST_EMAIL_INVALIDO}”)", value=True)
    importar_dv = c2.checkbox("Importar CNPJs com dígito verificador inválido", value=False)

    apto = ~sem_cnpj & ~sem_razao & ~base["duplicado_arquivo"]
    if not importar_invalidos:
        apto &= base["email_valido"]
    if not importar_dv:
        apto &= ~cnpj_dv_invalido

    previa = base.copy()
    previa["Status inicial"] = previa["email_valido"].map(
        lambda ok: db.ST_AGUARDANDO_ENVIO if ok else db.ST_EMAIL_INVALIDO)
    previa.loc[previa["ja_cadastrado"], "Status inicial"] = (
        "Duplicado – será ignorado" if politica == "ignorar" else "Duplicado – será atualizado")
    previa.loc[~apto, "Status inicial"] = "Descartado"
    st.dataframe(
        previa[["razao_social", "cnpj", "cnae", "descricao_cnae", "email", "email_valido",
                "cnpj_valido", "Status inicial"]],
        hide_index=True, height=320,
        column_config={"razao_social": "Razão Social", "cnpj": "CNPJ", "cnae": "CNAE",
                       "descricao_cnae": "Descrição CNAE", "email": "E-mail",
                       "email_valido": st.column_config.CheckboxColumn("E-mail OK"),
                       "cnpj_valido": st.column_config.CheckboxColumn("CNPJ OK")},
    )

    registros = base.loc[apto].to_dict("records")
    novos = int((apto & ~base["ja_cadastrado"]).sum())
    st.info(f"Serão gravados **{novos}** novo(s) registro(s)"
            + (f" e **{int((apto & base['ja_cadastrado']).sum())}** atualizado(s)" if politica == "atualizar" else "")
            + f" no lote **{nome_lote or '…'}**{' (TESTE)' if is_teste else ''}.")
    if st.button("💾 Salvar no banco de dados", type="primary", disabled=not nome_lote.strip()):
        resultado = db.importar_empresas(registros, nome_lote.strip(), is_teste, politica, observacao or None)
        st.success(f"Importação concluída: {resultado['inseridos']} inserido(s), "
                   f"{resultado['atualizados']} atualizado(s), {resultado['ignorados']} ignorado(s).")
        st.balloons()


def _aba_lotes() -> None:
    lotes = db.listar_lotes()
    if not lotes:
        st.info("Nenhum lote cadastrado ainda.")
        return
    df = pd.DataFrame(lotes)
    df["criado_em"] = df["criado_em"].map(fmt_data_hora)
    df["tipo"] = df["is_teste"].map(lambda t: "🧪 Teste" if t else "📋 Oficial")
    st.dataframe(df[["nome", "tipo", "empresas", "enviados", "criado_em", "observacao"]], hide_index=True,
                 column_config={"nome": "Lote / Operação", "tipo": "Tipo", "empresas": "Empresas",
                                "enviados": "E-mails enviados", "criado_em": "Criado em",
                                "observacao": "Observação"})

    st.markdown("#### 🗑️ Excluir lote")
    st.caption("Remove o lote, suas empresas, histórico, evidências e **o log de envios** — "
               "assim as métricas e o contador do aquecimento gradual não são contaminados por testes.")
    opcoes = {f"{l['nome']} ({'TESTE' if l['is_teste'] else 'OFICIAL'} · {l['empresas']} empresas · "
              f"{l['enviados']} enviados)": l for l in lotes}
    escolha = st.selectbox("Lote a excluir", list(opcoes.keys()))
    lote = opcoes[escolha]
    if not lote["is_teste"]:
        st.warning("⚠️ Este é um **lote oficial**. A exclusão apagará também o histórico de "
                   "fiscalização dessas empresas.")
    if lote["enviados"] and not lote["is_teste"]:
        st.error("Este lote oficial já teve e-mails enviados. Excluí-lo altera o histórico de "
                 "aquecimento e apaga registros de notificações já realizadas.")
    confirmacao = st.text_input(f"Para confirmar, digite o nome do lote: **{lote['nome']}**",
                                key=f"conf_{lote['id']}")
    if st.button("Excluir lote definitivamente", type="primary",
                 disabled=confirmacao.strip() != lote["nome"]):
        r = db.excluir_lote(lote["id"])
        st.success(f"Lote excluído: {r['empresas']} empresa(s) e {r['envios']} registro(s) de envio removidos.")
        st.rerun()


def render() -> None:
    ui.cabecalho("Importação de Planilhas e Gestão de Lotes",
                 "Carga da base cadastral, saneamento de CNPJ/e-mail e controle de duplicidade")
    aba1, aba2 = st.tabs(["📥 Importar planilha", "🗂️ Gerenciar lotes"])
    with aba1:
        _aba_importar()
    with aba2:
        _aba_lotes()
