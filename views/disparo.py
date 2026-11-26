"""Módulo 2 — Template do e-mail, regras anti-spam, servidor SMTP (Zimbra) e fila de disparo."""
from __future__ import annotations

import base64
import os
import time as _time
from datetime import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv, set_key

from database import db_manager as db
from services import mailer
from services.utils import agora_local
from ui import components as ui

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
EMPRESA_EXEMPLO = {"razao_social": "EMPRESA EXEMPLO ENGENHARIA LTDA", "cnpj": "11.222.333/0001-81",
                   "cnae": "7112-0/00", "descricao_cnae": "Serviços de engenharia"}


# --------------------------------------------------------------------------- #
# Estado / configuração SMTP
# --------------------------------------------------------------------------- #
def _init_estado() -> None:
    load_dotenv(ENV_PATH, override=False)
    padroes = {
        "smtp_host": os.getenv("SMTP_HOST", ""),
        "smtp_port": int(os.getenv("SMTP_PORT", "587") or 587),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_pass": os.getenv("SMTP_PASSWORD", ""),
        "smtp_nome": os.getenv("SMTP_FROM_NAME", "Crea-MS – Departamento de Fiscalização"),
        "fila_rodando": False,
        "ultimo_envio_ts": 0.0,
        "log_fila": [],
    }
    for k, v in padroes.items():
        st.session_state.setdefault(k, v)


def _smtp_cfg() -> mailer.SMTPConfig | None:
    s = st.session_state
    if not (s.smtp_host and s.smtp_user and s.smtp_pass):
        return None
    return mailer.SMTPConfig(host=s.smtp_host.strip(), port=int(s.smtp_port), usuario=s.smtp_user.strip(),
                             senha=s.smtp_pass, remetente_nome=s.smtp_nome.strip())


def _templates(cfg: dict) -> tuple[str, str]:
    return (cfg.get("assunto_template") or mailer.ASSUNTO_PADRAO,
            cfg.get("corpo_template") or mailer.carregar_template_padrao())


# --------------------------------------------------------------------------- #
# Abas de configuração
# --------------------------------------------------------------------------- #
_CAMPOS_SMTP = ["smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_nome"]


def _aba_smtp() -> None:
    # O Streamlit descarta o estado de widgets ao trocar de página; por isso os valores
    # ficam em chaves próprias (smtp_*) e os widgets usam chaves espelho (w_smtp_*).
    for k in _CAMPOS_SMTP:
        if f"w_{k}" not in st.session_state:
            st.session_state[f"w_{k}"] = st.session_state[k]
    st.markdown("#### Servidor SMTP do Zimbra")
    # Formulário: garante que todos os campos (inclusive a senha) sejam confirmados juntos.
    with st.form("form_smtp"):
        c1, c2 = st.columns([3, 1])
        c1.text_input("Servidor SMTP", key="w_smtp_host", placeholder="ex.: mail.creams.org.br")
        c2.selectbox("Porta", [587, 465], key="w_smtp_port",
                     format_func=lambda p: f"{p} – {'STARTTLS' if p == 587 else 'SSL/TLS'}")
        c1, c2 = st.columns(2)
        c1.text_input("E-mail institucional (login)", key="w_smtp_user",
                      placeholder="fiscalizacao@creams.org.br")
        c2.text_input("Senha", key="w_smtp_pass", type="password")
        st.text_input("Nome do remetente", key="w_smtp_nome")
        salvar_senha = st.checkbox("Ao salvar no .env, incluir também a senha", value=False,
                                   help="O .env está no .gitignore e nunca deve ser enviado ao GitHub.")
        b1, b2, b3, _ = st.columns([1, 1, 1, 2])
        aplicar = b1.form_submit_button("✅ Aplicar", type="primary", width="stretch")
        testar = b2.form_submit_button("🔌 Testar Conexão", width="stretch")
        salvar = b3.form_submit_button("💾 Salvar no .env", width="stretch")
    for k in _CAMPOS_SMTP:
        st.session_state[k] = st.session_state[f"w_{k}"]

    if aplicar:
        st.success("Configuração aplicada nesta sessão.")
    if testar:
        cfg = _smtp_cfg()
        if not cfg:
            st.error("Preencha servidor, e-mail e senha.")
        else:
            with st.spinner("Conectando ao servidor…"):
                ok, msg = mailer.testar_conexao(cfg)
            (st.success if ok else st.error)(msg)
    if salvar:
        ENV_PATH.touch(exist_ok=True)
        s = st.session_state
        for chave, valor in [("SMTP_HOST", s.smtp_host), ("SMTP_PORT", str(s.smtp_port)),
                             ("SMTP_USER", s.smtp_user), ("SMTP_FROM_NAME", s.smtp_nome)]:
            set_key(str(ENV_PATH), chave, valor or "")
        if salvar_senha:
            set_key(str(ENV_PATH), "SMTP_PASSWORD", s.smtp_pass or "")
        st.success("Configurações salvas em .env" + (" (com senha)." if salvar_senha else
                                                     " (senha mantida apenas nesta sessão)."))

    st.divider()
    st.markdown("#### ✉️ Enviar e-mail de teste")
    st.caption("Envia o template atual com dados fictícios, sem registrar no banco nem contar no aquecimento. "
               "Útil para conferir formatação, logo e a assinatura.")
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    destino = c1.text_input("Destinatário do teste", placeholder="seu.email@creams.org.br")
    if c2.button("Enviar teste", width="stretch"):
        cfg_smtp = _smtp_cfg()
        if not cfg_smtp or not destino:
            st.error("Configure o SMTP e informe o destinatário.")
        else:
            cfg = db.obter_todas_config()
            assunto_tpl, corpo_tpl = _templates(cfg)
            em = mailer.preparar_email(EMPRESA_EXEMPLO, "[TESTE] " + assunto_tpl, corpo_tpl,
                                       int(cfg["prazo_dias"]), cfg["embutir_logo"], cfg["incluir_assinatura"])
            try:
                mailer.enviar(cfg_smtp, mailer.construir_mensagem(cfg_smtp, destino, em["assunto"], em["html"],
                                                                  cfg["embutir_logo"]))
                st.success(f"E-mail de teste enviado para {destino}.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Falha no envio: {exc}")


def _aba_template(cfg: dict) -> None:
    assunto_tpl, corpo_tpl = _templates(cfg)
    c_ed, c_prev = st.columns([1, 1])
    with c_ed:
        st.markdown("#### Editor")
        assunto = st.text_input("Assunto", value=assunto_tpl)
        corpo = st.text_area("Corpo (HTML leve)", value=corpo_tpl, height=430)
        st.caption("Variáveis: " + " ".join(f"`{{{v}}}`" for v in mailer.VARIAVEIS_SUPORTADAS))
        c1, c2 = st.columns(2)
        prazo = c1.number_input("Prazo concedido (dias)", 1, 365, int(cfg["prazo_dias"]))
        dias_alerta = c2.number_input("Alertar vencimento com (dias)", 1, 60, int(cfg["dias_alerta_vencimento"]))
        incluir_ass = st.checkbox("Incluir assinatura/rodapé institucional no corpo do e-mail",
                                  value=bool(cfg["incluir_assinatura"]))
        embutir_logo = st.checkbox("Embutir logo do Crea-MS no topo (imagem CID, não remota)",
                                   value=bool(cfg["embutir_logo"]),
                                   disabled=not mailer.LOGO_PATH.exists())
        st.info("ℹ️ **Sobre a assinatura:** a assinatura automática do Zimbra é inserida pelo "
                "*cliente web* ao compor uma mensagem. Envios via SMTP **normalmente não a recebem**, "
                "a menos que o servidor aplique rodapé/disclaimer de domínio. Faça um *e-mail de teste* "
                "(aba Servidor SMTP) e, se a assinatura não aparecer, marque a opção acima.", icon="✍️")
        b1, b2 = st.columns(2)
        if b1.button("💾 Salvar template e opções", type="primary", width="stretch"):
            db.salvar_config({"assunto_template": assunto, "corpo_template": corpo, "prazo_dias": int(prazo),
                              "incluir_assinatura": incluir_ass, "embutir_logo": embutir_logo,
                              "dias_alerta_vencimento": int(dias_alerta)})
            st.success("Template salvo.")
            st.rerun()
        if b2.button("↩️ Restaurar template padrão", width="stretch"):
            db.salvar_config({"assunto_template": "", "corpo_template": ""})
            st.rerun()
    with c_prev:
        st.markdown("#### Pré-visualização")
        fila = db.fila_envio()
        exemplo = fila[0] if fila else EMPRESA_EXEMPLO
        st.caption(f"Dados de: **{exemplo['razao_social']}**" + ("" if fila else " (fictício)"))
        em = mailer.preparar_email(exemplo, assunto, corpo, int(prazo), embutir_logo, incluir_ass)
        st.markdown(f"**Assunto:** {em['assunto']}")
        html_prev = em["html"]
        if embutir_logo and mailer.LOGO_PATH.exists():
            b64 = base64.b64encode(mailer.LOGO_PATH.read_bytes()).decode()
            html_prev = html_prev.replace("cid:logo_creams", f"data:image/png;base64,{b64}")
        # st.html sanitiza o conteúdo (sem scripts) — mais seguro que um iframe para pré-visualização
        with st.container(height=620, border=True):
            st.html(f'<div style="background:#fff;padding:6px 10px">{html_prev}</div>')
        with st.expander("Versão texto puro (parte text/plain)"):
            st.code(em["texto"], language=None)


def _aba_regras(cfg: dict) -> None:
    with st.form("regras"):
        st.markdown("#### 📈 Aquecimento gradual (ramp-up diário)")
        ativo = st.toggle("Ativar aquecimento gradual", value=bool(cfg["aquecimento_ativo"]))
        c1, c2, c3 = st.columns(3)
        inicial = c1.number_input("Limite inicial (1º dia)", 1, 1000, int(cfg["aquecimento_inicial"]))
        incremento = c2.number_input("Incremento por dia de envio", 0, 500, int(cfg["aquecimento_incremento"]))
        teto = c3.number_input("Limite máximo / teto diário", 1, 5000, int(cfg["aquecimento_teto"]))
        st.caption("A cota só avança em dias com envio efetivo (lotes de teste não contam). "
                   "Com o aquecimento desativado, vale apenas o teto diário.")

        st.markdown("#### 🕛 Janela de expediente (America/Campo_Grande)")
        c1, c2 = st.columns(2)
        h_ini = c1.time_input("Início", time.fromisoformat(cfg["janela_inicio"]), step=900)
        h_fim = c2.time_input("Término", time.fromisoformat(cfg["janela_fim"]), step=900)

        st.markdown("#### ⏱️ Intervalo randômico entre envios (jitter)")
        c1, c2 = st.columns(2)
        j_min = c1.number_input("Mínimo (segundos)", 5, 3600, int(cfg["jitter_min"]))
        j_max = c2.number_input("Máximo (segundos)", 5, 3600, int(cfg["jitter_max"]))

        if st.form_submit_button("💾 Salvar regras", type="primary"):
            if h_fim <= h_ini:
                st.error("O término deve ser posterior ao início.")
            elif j_max < j_min:
                st.error("O jitter máximo deve ser maior ou igual ao mínimo.")
            else:
                db.salvar_config({"aquecimento_ativo": ativo, "aquecimento_inicial": int(inicial),
                                  "aquecimento_incremento": int(incremento), "aquecimento_teto": int(teto),
                                  "janela_inicio": h_ini.strftime("%H:%M"), "janela_fim": h_fim.strftime("%H:%M"),
                                  "jitter_min": int(j_min), "jitter_max": int(j_max)})
                st.success("Regras salvas.")
                st.rerun()

    # Simulação da curva
    if cfg["aquecimento_ativo"]:
        curva = [min(int(cfg["aquecimento_inicial"]) + int(cfg["aquecimento_incremento"]) * d,
                     int(cfg["aquecimento_teto"])) for d in range(20)]
        st.caption("Projeção da cota nos próximos 20 dias de envio: " + ", ".join(map(str, curva)))


# --------------------------------------------------------------------------- #
# Fila de disparo
# --------------------------------------------------------------------------- #
def _iniciar():
    st.session_state.fila_rodando = True
    st.session_state.log_fila = []


def _pausar():
    st.session_state.fila_rodando = False


def _log(caixa, texto: str) -> None:
    st.session_state.log_fila.insert(0, f"{agora_local().strftime('%H:%M:%S')} · {texto}")
    st.session_state.log_fila = st.session_state.log_fila[:200]
    caixa.code("\n".join(st.session_state.log_fila[:40]), language=None)


def _aguardar(segundos: int, contador, motivo: str) -> bool:
    """Contagem regressiva visível. Retorna False se a fila foi pausada."""
    for restante in range(int(segundos), 0, -1):
        if not st.session_state.fila_rodando:
            return False
        contador.markdown(f'⏳ {motivo}: <span class="contador">{restante}s</span>', unsafe_allow_html=True)
        _time.sleep(1)
    contador.empty()
    return True


def _executar_fila(cfg: dict, cfg_smtp: mailer.SMTPConfig, lote_ids: list[int], incluir_falhas: bool,
                   anexo: tuple[str, bytes] | None, teste_fora_janela: bool) -> None:
    fila = db.fila_envio(lote_ids or None, incluir_falhas)
    total = len(fila)
    if not total:
        st.session_state.fila_rodando = False
        st.info("Não há empresas aguardando envio para os lotes selecionados.")
        return

    st.markdown("##### Execução em tempo real")
    progresso = st.progress(0.0, text=f"0 de {total}")
    atual = st.empty()
    contador = st.empty()
    caixa_log = st.empty()
    assunto_tpl, corpo_tpl = _templates(cfg)
    enviados = falhas_seguidas = pulados_cota = 0

    for i, emp in enumerate(fila, start=1):
        if not st.session_state.fila_rodando:
            _log(caixa_log, "Fila pausada pelo operador.")
            break
        teste = emp["lote_teste"]

        # Janela de expediente
        if not (teste and teste_fora_janela) and not mailer.dentro_da_janela(cfg["janela_inicio"], cfg["janela_fim"]):
            prox = mailer.proxima_abertura(cfg["janela_inicio"], cfg["janela_fim"])
            st.session_state.fila_rodando = False
            st.warning(f"🕛 Fora da janela de expediente ({cfg['janela_inicio']}–{cfg['janela_fim']}). "
                       f"A próxima janela abre em **{prox.strftime('%d/%m/%Y às %H:%M')}**.")
            break

        # Cota diária (somente lotes oficiais)
        if not teste and db.calcular_cota_hoje(cfg)["restantes"] <= 0:
            pulados_cota += 1
            continue

        # Garante o intervalo mínimo mesmo após pausa/retomada
        decorrido = _time.time() - st.session_state.ultimo_envio_ts
        if decorrido < int(cfg["jitter_min"]):
            if not _aguardar(int(cfg["jitter_min"] - decorrido), contador, "Intervalo mínimo desde o último envio"):
                break

        atual.markdown(f'<div class="cartao">📤 <b>Enviando {i}/{total}</b> — {emp["razao_social"]} '
                       f'· {emp["cnpj"]} · <code>{emp["email"]}</code>'
                       f'{" · 🧪 teste" if teste else ""}</div>', unsafe_allow_html=True)
        em = mailer.preparar_email(emp, assunto_tpl, corpo_tpl, int(cfg["prazo_dias"]),
                                   cfg["embutir_logo"], cfg["incluir_assinatura"])
        # Importante: nenhuma chamada st.* entre o envio e o registro no banco,
        # para que uma pausa não interrompa a operação no meio.
        try:
            msg = mailer.construir_mensagem(cfg_smtp, emp["email"], em["assunto"], em["html"],
                                            cfg["embutir_logo"], anexo)
            mailer.enviar(cfg_smtp, msg)
            db.registrar_envio_sucesso(emp["id"], em["assunto"], em["texto"], int(cfg["prazo_dias"]))
            ok, erro = True, None
        except Exception as exc:  # noqa: BLE001
            db.registrar_envio_falha(emp["id"], str(exc))
            mailer.logger.error("FALHA | para=%s | erro=%s", emp["email"], exc)
            ok, erro = False, str(exc)
        st.session_state.ultimo_envio_ts = _time.time()

        if ok:
            enviados += 1
            falhas_seguidas = 0
            _log(caixa_log, f"✅ {emp['razao_social']} <{emp['email']}>")
        else:
            falhas_seguidas += 1
            _log(caixa_log, f"❌ {emp['razao_social']} <{emp['email']}> — {erro[:150]}")
            if falhas_seguidas >= 3:
                st.session_state.fila_rodando = False
                st.error("⛔ 3 falhas consecutivas: fila interrompida por segurança. Verifique o servidor "
                         "SMTP, a senha ou possível bloqueio por limite de envio.")
                break

        progresso.progress(i / total, text=f"{i} de {total} processados · {enviados} enviados")
        if i < total:
            espera = mailer.sortear_intervalo(cfg["jitter_min"], cfg["jitter_max"])
            if not _aguardar(espera, contador, "Próximo envio em"):
                _log(caixa_log, "Fila pausada pelo operador.")
                break
    else:
        st.session_state.fila_rodando = False

    atual.empty()
    contador.empty()
    if pulados_cota:
        st.session_state.fila_rodando = False
        st.warning(f"🎯 Meta diária de aquecimento atingida — {pulados_cota} envio(s) oficial(is) ficam para "
                   f"o próximo dia de expediente.")
    st.success(f"Ciclo encerrado: {enviados} e-mail(s) enviado(s) nesta execução.")


def _aba_fila(cfg: dict) -> None:
    cota = db.calcular_cota_hoje(cfg)
    janela_aberta = mailer.dentro_da_janela(cfg["janela_inicio"], cfg["janela_fim"])
    pendentes = db.fila_envio()
    ui.linha_kpis([
        (cota["meta"], f"Meta de hoje (aquecimento · dia {cota['dia_aquecimento']})"),
        (cota["enviados"], "Enviados hoje", "ok"),
        (cota["restantes"], "Restantes hoje", "aviso" if cota["restantes"] else "alerta"),
        (len(pendentes), "Aguardando envio (todos os lotes)", "neutro"),
        ("Aberta" if janela_aberta else "Fechada",
         f"Janela {cfg['janela_inicio']}–{cfg['janela_fim']} · agora {agora_local().strftime('%H:%M')}",
         "ok" if janela_aberta else "alerta"),
    ])
    st.markdown(f"**Meta de hoje (aquecimento): {cota['meta']} | Enviados hoje: {cota['enviados']} | "
                f"Restantes hoje: {cota['restantes']}**")
    if not janela_aberta:
        prox = mailer.proxima_abertura(cfg["janela_inicio"], cfg["janela_fim"])
        st.warning(f"Fora da janela de expediente. Novos envios oficiais liberados em "
                   f"**{prox.strftime('%d/%m/%Y às %H:%M')}**.")

    lotes = db.listar_lotes()
    opcoes = {f"{'🧪 ' if l['is_teste'] else ''}{l['nome']}": l["id"] for l in lotes}
    c1, c2 = st.columns([3, 2])
    sel = c1.multiselect("Lotes a disparar (vazio = todos os lotes com pendências)", list(opcoes.keys()),
                         disabled=st.session_state.fila_rodando)
    anexo_arq = c2.file_uploader("Anexo opcional (mesmo arquivo para todos)", type=None,
                                 disabled=st.session_state.fila_rodando)
    c1, c2 = st.columns(2)
    incluir_falhas = c1.checkbox("Reprocessar empresas com “Falha no Envio”", value=False)
    teste_fora = c2.checkbox("Permitir lotes de teste fora da janela de expediente", value=True)

    cfg_smtp = _smtp_cfg()
    if not cfg_smtp:
        st.error("Configure o servidor SMTP na aba **🔐 Servidor SMTP** antes de iniciar.")

    b1, b2, _ = st.columns([1, 1, 3])
    b1.button("▶️ Iniciar / Retomar fila", type="primary", on_click=_iniciar, width="stretch",
              disabled=st.session_state.fila_rodando or not cfg_smtp)
    b2.button("⏸️ Pausar Fila", on_click=_pausar, width="stretch", disabled=not st.session_state.fila_rodando)

    if st.session_state.fila_rodando and cfg_smtp:
        st.caption("Mantenha esta página aberta durante o envio. Os registros são gravados a cada "
                   "e-mail; se a página for fechada, basta retomar a fila depois.")
        anexo = (anexo_arq.name, anexo_arq.getvalue()) if anexo_arq else None
        _executar_fila(cfg, cfg_smtp, [opcoes[s] for s in sel], incluir_falhas, anexo, teste_fora)
    elif st.session_state.log_fila:
        with st.expander("Log da última execução"):
            st.code("\n".join(st.session_state.log_fila), language=None)

    with st.expander("📋 Próximos da fila"):
        if pendentes:
            st.dataframe([{"Razão Social": p["razao_social"], "CNPJ": p["cnpj"], "E-mail": p["email"],
                           "Lote": p["lote_nome"], "Teste": p["lote_teste"]} for p in pendentes[:200]],
                         hide_index=True)
        else:
            st.caption("Fila vazia.")
    with st.expander("📈 Histórico de envios oficiais (30 dias)"):
        est = db.estatisticas_envio()
        if est:
            import pandas as pd
            df = pd.DataFrame(est)
            df["resultado"] = df["sucesso"].map({True: "Sucesso", False: "Falha"})
            tabela = df.pivot_table(index="data", columns="resultado", values="quantidade",
                                    aggfunc="sum").fillna(0)
            cores = {"Falha": "#C62828", "Sucesso": "#0055A5"}
            st.bar_chart(tabela, color=[cores[c] for c in tabela.columns])
        else:
            st.caption("Sem envios oficiais registrados.")


def render() -> None:
    _init_estado()
    ui.cabecalho("Template e Motor de Disparo",
                 "Envio via SMTP do Zimbra com aquecimento gradual, janela de expediente e intervalo randômico")
    cfg = db.obter_todas_config()
    aba_fila, aba_tpl, aba_regras, aba_smtp = st.tabs(
        ["🚀 Fila de Disparo", "📝 Template do E-mail", "🛡️ Regras Anti-Spam", "🔐 Servidor SMTP"])
    # As abas de configuração são desenhadas antes da fila, pois o laço de envio bloqueia a execução.
    with aba_tpl:
        _aba_template(cfg)
    with aba_regras:
        _aba_regras(cfg)
    with aba_smtp:
        _aba_smtp()
    with aba_fila:
        _aba_fila(cfg)
