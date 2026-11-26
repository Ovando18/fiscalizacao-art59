"""Módulo 4 — Investigação de Atuação (OSINT) e encaminhamento para fiscalização in-loco."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from database import db_manager as db
from services.osint_helper import gerar_links
from services.utils import fmt_data, fmt_data_hora
from ui import components as ui

@st.cache_data(ttl=600, show_spinner=False, max_entries=200)
def _ler_evidencia(chave: str) -> bytes | None:
    """Evita baixar a mesma evidência do Storage a cada interação."""
    return db.ler_evidencia(chave)


STATUS_INVESTIGACAO = [db.ST_PRAZO_ENCERRADO, db.ST_ATUACAO_CONFIRMADA, db.ST_VISITA_IN_LOCO]


def render() -> None:
    ui.cabecalho("Investigação de Atuação (OSINT) e Encaminhamento In-Loco",
                 "Diligência em fontes abertas para empresas com prazo encerrado sem regularização")

    incluir_teste = st.toggle("Incluir lotes de teste", value=False)
    empresas = [e for e in db.listar_empresas(incluir_teste) if e["status"] in STATUS_INVESTIGACAO]
    pendentes = [e for e in empresas if e["status"] == db.ST_PRAZO_ENCERRADO]
    ui.linha_kpis([
        (len(pendentes), "Aguardando diligência", "alerta"),
        (sum(e["status"] == db.ST_ATUACAO_CONFIRMADA for e in empresas), "Atuação confirmada", "aviso"),
        (sum(e["status"] == db.ST_VISITA_IN_LOCO for e in empresas), "Aguardando visita in-loco", "neutro"),
    ])
    st.write("")
    if not empresas:
        st.success("Nenhuma empresa com prazo encerrado no momento. 🎉")
        return

    mostrar = st.radio("Exibir", ["Pendentes de diligência", "Todas as investigações"], horizontal=True)
    lista = pendentes if mostrar.startswith("Pendentes") else empresas
    if not lista:
        st.info("Nenhuma empresa pendente de diligência.")
        return

    rotulos = {e["id"]: f"{e['razao_social']} · {e['cnpj']} · limite {fmt_data(e['data_limite'])} · {e['status']}"
               for e in lista}
    ids = list(rotulos)
    preferida = st.session_state.pop("empresa_investigar", None)
    indice = ids.index(preferida) if preferida in ids else 0
    empresa_id = st.selectbox("Empresa", ids, index=indice, format_func=rotulos.get)
    emp = db.obter_empresa(empresa_id)
    usuario = ui.usuario_atual()

    st.markdown(
        f"""<div class="cartao"><h3 style="margin:0">{emp['razao_social']}</h3>
        <div style="margin:6px 0 8px 0">{ui.badge_status(emp['status'])}</div>
        <b>CNPJ:</b> {emp['cnpj']} · <b>CNAE:</b> {emp['cnae'] or '—'} – {emp['descricao_cnae'] or '—'} ·
        <b>E-mail:</b> {emp['email'] or '—'}<br><b>Notificada em:</b> {fmt_data_hora(emp['data_envio'])} ·
        <b>Prazo encerrado em:</b> {fmt_data(emp['data_limite'])}</div>""",
        unsafe_allow_html=True,
    )
    if emp["status"] == db.ST_VISITA_IN_LOCO:
        st.markdown('<div class="alerta-inloco">NECESSÁRIA VISITA IN-LOCO PARA CONSTATAÇÃO DE ATUAÇÃO</div>',
                    unsafe_allow_html=True)

    col_busca, col_reg = st.columns([1, 1], gap="large")
    with col_busca:
        st.markdown("#### 🔎 Assistente de busca na internet")
        st.caption("Links pré-formatados com Razão Social e CNPJ. Abra cada fonte, faça capturas de tela "
                   "do que for relevante e registre ao lado.")
        for categoria, links in gerar_links(emp["razao_social"], emp["cnpj"]).items():
            with st.expander(categoria, expanded=categoria.startswith("1")):
                for i in range(0, len(links), 2):
                    cols = st.columns(2)
                    for col, link in zip(cols, links[i:i + 2]):
                        col.link_button(link["rotulo"], link["url"], help=link["descricao"], width="stretch")

    with col_reg:
        st.markdown("#### 🗂️ Registro de evidências")
        with st.form(f"inv_{empresa_id}"):
            indicios = st.checkbox("Indícios de atuação localizados na internet?",
                                   value=bool(emp.get("indicios_internet")))
            texto = st.text_area("Links, nº de empenho/contrato, descrições e observações",
                                 value=emp.get("evidencias_texto") or "", height=170,
                                 placeholder="Ex.: Extrato de contrato nº 12/2026 – Prefeitura de ... – "
                                             "https://...\nInstagram com fotos de obras em andamento: https://...")
            arquivos = st.file_uploader("Prints / comprovantes (.png, .jpg, .pdf)",
                                        type=["png", "jpg", "jpeg", "pdf"], accept_multiple_files=True)
            enviar = st.form_submit_button("Concluir diligência e aplicar regra de decisão", type="primary")
        if enviar:
            if indicios and not (texto.strip() or arquivos or emp["arquivos"]):
                st.error("Descreva ou anexe as evidências dos indícios localizados.")
            else:
                try:
                    for arq in arquivos or []:
                        db.adicionar_evidencia(empresa_id, arq.name, arq.getvalue())
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Falha ao gravar a evidência: {exc}. A diligência não foi concluída.")
                    st.stop()
                novo = db.registrar_investigacao(empresa_id, indicios, texto.strip(), usuario)
                if novo == db.ST_VISITA_IN_LOCO:
                    st.toast("Sem indícios: encaminhada para visita in-loco.", icon="📍")
                else:
                    st.toast("Atuação confirmada registrada.", icon="⚠️")
                st.rerun()

        st.caption("Regra: com indícios → **Atuação Confirmada (Investigação / Fiscalização)**; "
                   "sem indícios → **Aguardando Visita In-Loco**.")
        if emp["arquivos"]:
            st.markdown(f"**Evidências anexadas ({len(emp['arquivos'])})**")
            for a in emp["arquivos"]:
                c1, c2 = st.columns([4, 1], vertical_alignment="center")
                c1.caption(f"📎 {a['nome_original']} · {fmt_data_hora(a['enviado_em'])}")
                try:
                    conteudo = _ler_evidencia(a["caminho"])
                except Exception as exc:  # noqa: BLE001
                    c1.error(f"Não foi possível carregar o arquivo: {exc}")
                    continue
                if conteudo is None:
                    c1.warning("Arquivo não encontrado no armazenamento.")
                    continue
                c2.download_button("Baixar", conteudo, file_name=a["nome_original"],
                                   key=f"dl_{a['id']}", width="stretch")
                if Path(a["caminho"]).suffix.lower() in (".png", ".jpg", ".jpeg"):
                    st.image(conteudo, width=320)
