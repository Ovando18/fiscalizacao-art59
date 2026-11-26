"""Módulo 5 — Gerador de Dossiê / Relatório de Fiscalização Individual."""
from __future__ import annotations

import io
import zipfile

import streamlit as st

from database import db_manager as db
from services.report_generator import gerar_dossie
from ui import components as ui


def render() -> None:
    ui.cabecalho("Dossiê de Fiscalização",
                 "Relatório de Instrução e Constatação – Art. 59 da Lei nº 5.194/1966")
    cfg = db.obter_todas_config()

    with st.expander("✍️ Responsável pela assinatura do dossiê", expanded=not cfg["responsavel_nome"]):
        with st.form("responsavel"):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome do responsável (DFI)", value=cfg["responsavel_nome"])
            cargo = c2.text_input("Cargo / Matrícula", value=cfg["responsavel_cargo"])
            if st.form_submit_button("Salvar"):
                db.salvar_config({"responsavel_nome": nome.strip(), "responsavel_cargo": cargo.strip()})
                st.rerun()

    incluir_teste = st.toggle("Incluir lotes de teste", value=False)
    empresas = db.listar_empresas(incluir_teste)
    if not empresas:
        st.info("Nenhuma empresa cadastrada.")
        return

    c1, c2 = st.columns([2, 3])
    status = c1.multiselect("Filtrar por status", db.TODOS_STATUS,
                            default=[db.ST_ATUACAO_CONFIRMADA, db.ST_VISITA_IN_LOCO])
    busca = c2.text_input("Buscar CNPJ / Razão Social")
    lista = [e for e in empresas if (not status or e["status"] in status)
             and (not busca or busca.upper() in e["razao_social"].upper()
                  or "".join(ch for ch in busca.upper() if ch.isalnum()) in e["cnpj_limpo"])]
    if not lista:
        st.info("Nenhuma empresa no filtro.")
        return

    rotulos = {e["id"]: f"{e['razao_social']} · {e['cnpj']} · {e['status']}" for e in lista}
    st.markdown("#### Dossiê individual")
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    empresa_id = c1.selectbox("Empresa", list(rotulos), format_func=rotulos.get)
    if c2.button("📄 Gerar Dossiê de Fiscalização", type="primary", width="stretch"):
        pdf, nome_arq = gerar_dossie(empresa_id, cfg["responsavel_nome"] or ui.usuario_atual(),
                                     cfg["responsavel_cargo"])
        st.session_state["dossie_pdf"] = (empresa_id, pdf, nome_arq)
    gerado = st.session_state.get("dossie_pdf")
    if gerado and gerado[0] == empresa_id:
        st.success(f"Dossiê gerado: **{gerado[2]}**")
        st.download_button("⬇️ Baixar PDF", gerado[1], file_name=gerado[2], mime="application/pdf",
                           type="primary")

    st.divider()
    st.markdown("#### Geração em lote")
    st.caption(f"Gera um arquivo .zip com o dossiê de cada uma das **{len(lista)}** empresa(s) filtradas.")
    if st.button(f"🗜️ Gerar {len(lista)} dossiê(s) em .zip", disabled=len(lista) > 500):
        buf = io.BytesIO()
        barra = st.progress(0.0)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i, e in enumerate(lista, 1):
                pdf, nome_arq = gerar_dossie(e["id"], cfg["responsavel_nome"] or ui.usuario_atual(),
                                             cfg["responsavel_cargo"])
                z.writestr(nome_arq, pdf)
                barra.progress(i / len(lista))
        st.download_button("⬇️ Baixar .zip", buf.getvalue(), file_name="Dossies_Art59.zip",
                           mime="application/zip", type="primary")
