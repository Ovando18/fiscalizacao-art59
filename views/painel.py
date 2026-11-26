"""Módulo 3 — Painel de Controle: KPIs, filtros, prazos e ações por empresa."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from database import db_manager as db
from services.report_generator import gerar_dossie
from services.utils import fmt_data, fmt_data_hora, validar_email, limpar_email
from ui import components as ui


def _dataframe_empresas(incluir_teste: bool, dias_alerta: int) -> pd.DataFrame:
    dados = db.listar_empresas(incluir_teste=incluir_teste)
    if not dados:
        return pd.DataFrame()
    df = pd.DataFrame(dados)
    situacoes = [ui.situacao_prazo(s, d, dias_alerta) for s, d in zip(df["status"], df["data_limite"])]
    df["situacao_prazo"] = [s[0] for s in situacoes]
    df["cnae"] = df["cnae"].fillna("(sem CNAE)")
    return df


def _kpis(df: pd.DataFrame) -> None:
    c = df["status"].value_counts() if not df.empty else pd.Series(dtype=int)
    g = lambda s: int(c.get(s, 0))  # noqa: E731
    ui.linha_kpis([
        (len(df), "Total de empresas"),
        (g(db.ST_AGUARDANDO_ENVIO) + g(db.ST_FALHA_ENVIO) + g(db.ST_EMAIL_INVALIDO), "Aguardando envio", "neutro"),
        (g(db.ST_NOTIFICADO), "Dentro do prazo"),
        (g(db.ST_PRAZO_ENCERRADO), "Prazo vencido (ação necessária)", "alerta"),
        (g(db.ST_RESPONDEU), "Respondeu / em análise", "aviso"),
        (g(db.ST_REGULARIZADA), "Regularizadas", "ok"),
        (g(db.ST_ATUACAO_CONFIRMADA), "Atuação confirmada", "alerta"),
        (g(db.ST_VISITA_IN_LOCO), "Encaminhadas p/ fiscalização in-loco", "aviso"),
    ])


def _filtros(df: pd.DataFrame) -> pd.DataFrame:
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
        cnaes = c1.multiselect("CNAE", sorted(df["cnae"].unique()), placeholder="Todos (base unificada)")
        status = c2.multiselect("Status", db.TODOS_STATUS, placeholder="Todos")
        lotes = c3.multiselect("Lote", sorted(df["lote_nome"].unique()), placeholder="Todos")
        busca = c4.text_input("Buscar CNPJ / Razão Social", placeholder="Digite parte do nome ou CNPJ")
        somente_alerta = st.toggle("Mostrar apenas prazos vencidos ou próximos do vencimento")
    f = df
    if cnaes:
        f = f[f["cnae"].isin(cnaes)]
    if status:
        f = f[f["status"].isin(status)]
    if lotes:
        f = f[f["lote_nome"].isin(lotes)]
    if busca:
        termo = busca.strip().upper()
        digitos = "".join(ch for ch in termo if ch.isalnum())
        f = f[f["razao_social"].str.upper().str.contains(termo, regex=False)
              | (f["cnpj_limpo"].str.contains(digitos, regex=False) if digitos else False)]
    if somente_alerta:
        f = f[f["situacao_prazo"].str.startswith(("🔴", "🟡"))]
    return f


def _exportar(df: pd.DataFrame) -> bytes:
    colunas = {"razao_social": "Razão Social", "cnpj": "CNPJ", "cnae": "CNAE", "descricao_cnae": "Descrição CNAE",
               "email": "E-mail", "lote_nome": "Lote", "status": "Status", "situacao_prazo": "Situação do Prazo",
               "data_envio": "Data Envio", "data_limite": "Data Limite", "protocolo": "Protocolo",
               "numero_registro": "Registro Crea-MS"}
    saida = df[list(colunas)].rename(columns=colunas).copy()
    saida["Situação do Prazo"] = saida["Situação do Prazo"].str[2:]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        saida.to_excel(w, index=False, sheet_name="Empresas")
    return buf.getvalue()


def _detalhe(empresa_id: int, dias_alerta: int) -> None:
    emp = db.obter_empresa(empresa_id)
    if not emp:
        return
    usuario = ui.usuario_atual()
    texto_prazo, classe = ui.situacao_prazo(emp["status"], emp["data_limite"], dias_alerta)
    st.markdown(
        f"""<div class="cartao"><h3 style="margin:0">{emp['razao_social']}</h3>
        <div style="margin:6px 0 10px 0">{ui.badge_status(emp['status'])} {ui.badge(texto_prazo, classe)}
        {ui.badge('LOTE DE TESTE', 'b-amarelo') if emp['lote_teste'] else ''}</div>
        <b>CNPJ:</b> {emp['cnpj']} &nbsp;·&nbsp; <b>CNAE:</b> {emp['cnae'] or '—'} – {emp['descricao_cnae'] or '—'}
        &nbsp;·&nbsp; <b>E-mail:</b> {emp['email'] or '—'} &nbsp;·&nbsp; <b>Lote:</b> {emp['lote_nome']}<br>
        <b>Envio:</b> {fmt_data_hora(emp['data_envio'])} &nbsp;·&nbsp; <b>Prazo:</b>
        {str(emp['prazo_dias']) + ' dias' if emp['prazo_dias'] else '—'} &nbsp;·&nbsp;
        <b>Data limite:</b> {fmt_data(emp['data_limite'])}</div>""",
        unsafe_allow_html=True,
    )
    if emp["status"] == db.ST_FALHA_ENVIO and emp.get("ultimo_erro"):
        st.error(f"Último erro de envio: {emp['ultimo_erro']}")
    if emp["status"] == db.ST_PRAZO_ENCERRADO:
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.error("⏰ Prazo encerrado sem regularização — realizar a **Investigação de Atuação**.")
        if c2.button("🔎 Ir para Investigação", type="primary", width="stretch"):
            st.session_state["empresa_investigar"] = empresa_id
            st.switch_page(st.session_state["_paginas"]["investigacao"])
    if emp["status"] == db.ST_VISITA_IN_LOCO:
        st.markdown('<div class="alerta-inloco">NECESSÁRIA VISITA IN-LOCO PARA CONSTATAÇÃO DE ATUAÇÃO</div>',
                    unsafe_allow_html=True)

    t1, t2, t3, t4, t5 = st.tabs(["🕑 Histórico", "💬 Respondeu / Em análise", "✅ Regularizada",
                                  "✏️ Contato e status", "📄 Dossiê"])
    with t1:
        hist = pd.DataFrame(emp["historico"])
        if not hist.empty:
            hist["data_hora"] = hist["data_hora"].map(fmt_data_hora)
            st.dataframe(hist, hide_index=True, column_config={
                "data_hora": "Data/Hora", "evento": "Evento", "detalhe": st.column_config.TextColumn("Detalhe", width="large"),
                "usuario": "Usuário"})
        if emp.get("corpo_enviado"):
            with st.expander("Texto do e-mail enviado"):
                st.markdown(f"**Assunto:** {emp['assunto_enviado']}")
                st.code(emp["corpo_enviado"], language=None)
        with st.form(f"obs_{empresa_id}", clear_on_submit=True):
            obs = st.text_area("Adicionar anotação ao histórico", height=80)
            if st.form_submit_button("Registrar anotação") and obs.strip():
                db.adicionar_observacao(empresa_id, obs.strip(), usuario)
                st.rerun()
    with t2:
        with st.form(f"resp_{empresa_id}"):
            protocolo = st.text_input("Protocolo / nº do documento", value=emp.get("protocolo") or "")
            resumo = st.text_area("Resumo da resposta", value=emp.get("resposta_resumo") or "", height=110)
            if st.form_submit_button("Marcar como Respondeu / Em Análise", type="primary"):
                if not resumo.strip():
                    st.error("Informe o resumo da resposta.")
                else:
                    db.marcar_respondeu(empresa_id, resumo.strip(), protocolo.strip(), usuario)
                    st.success("Resposta registrada.")
                    st.rerun()
    with t3:
        with st.form(f"reg_{empresa_id}"):
            numero = st.text_input("Número do registro no Crea-MS *", value=emp.get("numero_registro") or "")
            obs = st.text_input("Observação (opcional)")
            if st.form_submit_button("Marcar como Regularizada (Registro Efetivado)", type="primary"):
                if not numero.strip():
                    st.error("Informe o número do registro.")
                else:
                    db.marcar_regularizada(empresa_id, numero.strip(), obs.strip(), usuario)
                    st.success("Empresa marcada como regularizada.")
                    st.rerun()
    with t4:
        with st.form(f"email_{empresa_id}"):
            novo = st.text_input("Corrigir e-mail de contato", value=emp.get("email") or "")
            if st.form_submit_button("Salvar e-mail (reenfileira se inválido/falha)"):
                e = limpar_email(novo)
                if not validar_email(e):
                    st.error("E-mail inválido.")
                else:
                    db.atualizar_email(empresa_id, e, True, usuario)
                    st.success("E-mail atualizado.")
                    st.rerun()
        with st.form(f"status_{empresa_id}"):
            st.caption("Alteração manual de status (fica registrada no histórico).")
            novo_status = st.selectbox("Novo status", db.TODOS_STATUS, index=db.TODOS_STATUS.index(emp["status"]))
            motivo = st.text_input("Motivo *")
            if st.form_submit_button("Alterar status"):
                if not motivo.strip():
                    st.error("Informe o motivo.")
                elif novo_status != emp["status"]:
                    db.alterar_status(empresa_id, novo_status, motivo.strip(), usuario)
                    st.rerun()
    with t5:
        cfg = db.obter_todas_config()
        if st.button("Gerar Dossiê de Fiscalização", key=f"gd_{empresa_id}"):
            pdf, nome = gerar_dossie(empresa_id, cfg["responsavel_nome"] or usuario, cfg["responsavel_cargo"])
            st.download_button("⬇️ Baixar PDF", pdf, file_name=nome, mime="application/pdf", type="primary")


def render() -> None:
    ui.cabecalho("Painel de Controle – Gestão de Prazos e Triagem",
                 "Acompanhamento das notificações orientativas de empresas sem registro no Crea-MS")
    cfg = db.obter_todas_config()
    dias_alerta = int(cfg["dias_alerta_vencimento"])

    incluir_teste = st.toggle("Exibir lotes de teste", value=False,
                              help="Por padrão os lotes de teste ficam ocultos e fora dos indicadores.")
    df = _dataframe_empresas(incluir_teste, dias_alerta)
    _kpis(df)
    st.write("")
    if df.empty:
        st.info("Nenhuma empresa cadastrada. Comece pela página **📥 Importação e Lotes**.")
        return

    filtrado = _filtros(df)
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    c1.markdown(f"**{len(filtrado)}** empresa(s) no filtro · selecione uma linha para ver detalhes e ações.")
    c2.download_button("⬇️ Exportar Excel", _exportar(filtrado), "empresas_art59.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    tabela = filtrado[["id", "situacao_prazo", "razao_social", "cnpj", "cnae", "email", "status",
                       "data_envio", "data_limite", "lote_nome"]].reset_index(drop=True)
    evento = st.dataframe(
        tabela, hide_index=True, height=min(420, 38 + 35 * max(len(tabela), 1)), on_select="rerun", selection_mode="single-row",
        column_order=["situacao_prazo", "razao_social", "cnpj", "cnae", "email", "status",
                      "data_envio", "data_limite", "lote_nome"],
        column_config={
            "situacao_prazo": st.column_config.TextColumn("Situação do prazo", width="medium"),
            "razao_social": st.column_config.TextColumn("Razão Social", width="large"),
            "cnpj": "CNPJ", "cnae": "CNAE", "email": "E-mail", "status": "Status",
            "data_envio": st.column_config.DatetimeColumn("Envio", format="DD/MM/YYYY HH:mm"),
            "data_limite": st.column_config.DateColumn("Data limite", format="DD/MM/YYYY"),
            "lote_nome": "Lote",
        },
    )
    linhas = evento.selection.rows if evento and evento.selection else []
    if linhas:
        st.divider()
        _detalhe(int(tabela.iloc[linhas[0]]["id"]), dias_alerta)
