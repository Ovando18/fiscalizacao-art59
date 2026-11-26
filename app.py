"""
Sistema de Gestão de Notificações Orientativas – Art. 59 da Lei nº 5.194/1966
Departamento de Fiscalização (DFI) – Crea-MS

Execução:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="DFI Crea-MS · Notificações Art. 59",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

from database import db_manager as db  # noqa: E402
from ui import components as ui  # noqa: E402
from views import disparo, dossie, importacao, investigacao, painel  # noqa: E402


@st.cache_resource
def _inicializar_banco() -> bool:
    db.init_db()
    return True


_inicializar_banco()

# A cada carregamento, notificações com prazo esgotado seguem para investigação
_vencidas = db.atualizar_prazos_vencidos()
if _vencidas:
    st.toast(f"{_vencidas} empresa(s) tiveram o prazo encerrado e foram encaminhadas para "
             f"Investigação de Atuação.", icon="⏰")

ui.aplicar_estilo()
ui.logo_sidebar()

paginas = {
    "Gestão": [
        st.Page(painel.render, title="Painel de Controle", icon="📊", default=True),
        st.Page(importacao.render, title="Importação e Lotes", icon="📥", url_path="importacao"),
    ],
    "Notificação": [
        st.Page(disparo.render, title="Template e Disparo", icon="✉️", url_path="disparo"),
    ],
    "Fiscalização": [
        st.Page(investigacao.render, title="Investigação (OSINT)", icon="🔎", url_path="investigacao"),
        st.Page(dossie.render, title="Dossiê de Fiscalização", icon="📄", url_path="dossie"),
    ],
}
navegacao = st.navigation(paginas)
# Referências às páginas para navegação programática (st.switch_page) entre módulos
st.session_state["_paginas"] = {p.url_path: p for grupo in paginas.values() for p in grupo}

with st.sidebar:
    if "operador" not in st.session_state:
        st.session_state["operador"] = db.obter_config("responsavel_nome") or ""
    st.text_input("👤 Operador (trilha de auditoria)", key="operador", placeholder="Seu nome")
    if st.session_state.get("fila_rodando"):
        st.info("📤 Fila de envio ativa. Os envios só prosseguem com a página "
                "*Template e Disparo* aberta.")
    st.caption("Crea-MS · Departamento de Fiscalização\n\n"
               "0800 368 1000 · dfi@creams.org.br")

navegacao.run()
