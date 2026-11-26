"""Identidade visual institucional (CSS) e componentes reutilizáveis da interface."""
from __future__ import annotations

import base64
import html
from datetime import date
from pathlib import Path

import streamlit as st

from database import db_manager as db
from services.utils import hoje_local

BASE_DIR = Path(__file__).resolve().parent.parent
LOGO_PATH = BASE_DIR / "assets" / "logo_creams.png"

AZUL_MARINHO = "#003366"
AZUL_MEDIO = "#0055A5"
CINZA_CLARO = "#F4F6F9"

CSS = f"""
<style>
:root {{
  --azul-marinho: {AZUL_MARINHO};
  --azul-medio: {AZUL_MEDIO};
  --cinza-claro: {CINZA_CLARO};
}}
.stApp {{ background: var(--cinza-claro); }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1500px; }}
section[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, var(--azul-marinho) 0%, #002447 100%);
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] *,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] *,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *,
section[data-testid="stSidebar"] [data-testid="stSidebarNavSeparator"] * {{ color: #E8EEF6 !important; }}
section[data-testid="stSidebar"] [data-testid="stNavSectionHeader"] {{ color: #9FC2E8 !important; }}
section[data-testid="stSidebar"] a[aria-current="page"],
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: rgba(255,255,255,.14) !important; border-radius: 8px;
}}
h1, h2, h3 {{ color: var(--azul-marinho); }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {{
  background: var(--azul-medio); border-color: var(--azul-medio);
}}
.stButton > button[kind="primary"]:disabled {{ background:#B8C6D6; border-color:#B8C6D6; color:#fff; }}
.stButton > button[kind="primary"]:hover {{ background: var(--azul-marinho); border-color: var(--azul-marinho); }}
div[data-testid="stExpander"], div[data-testid="stForm"] {{ background: #fff; border-radius: 10px; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
.stTabs [data-baseweb="tab"] {{ background: #fff; border-radius: 8px 8px 0 0; padding: 8px 16px; }}
.stTabs [aria-selected="true"] {{ background: var(--azul-marinho) !important; color: #fff !important; }}

/* Cabeçalho institucional */
.cms-header {{
  display:flex; align-items:center; justify-content:space-between; gap:16px;
  background:#fff; border-radius:12px; padding:14px 22px; margin-bottom:18px;
  border-left:6px solid var(--azul-medio); box-shadow:0 1px 3px rgba(0,51,102,.08);
}}
.cms-titulo {{ display:flex; align-items:center; gap:20px; flex:1; min-width:0; }}
.cms-logo {{ height:52px; width:auto; padding-right:20px; border-right:1px solid #d9e0ea; }}
.cms-header h1 {{ font-size:1.4rem; margin:0; line-height:1.2; }}
.cms-header p {{ margin:2px 0 0 0; color:#5b6b7f; font-size:.9rem; }}
.cms-tag {{ background:var(--azul-marinho); color:#fff; padding:4px 10px; border-radius:999px;
           font-size:.75rem; font-weight:600; white-space:nowrap; }}

/* KPIs */
.kpi {{ background:#fff; border-radius:12px; padding:12px 14px; height:100%;
        border-top:4px solid var(--azul-medio); box-shadow:0 1px 3px rgba(0,51,102,.08); }}
.kpi .v {{ font-size:1.75rem; font-weight:700; color:var(--azul-marinho); line-height:1.1; }}
.kpi .l {{ font-size:.7rem; line-height:1.3; overflow-wrap:normal; word-break:normal; color:#5b6b7f; text-transform:uppercase; letter-spacing:.03em; margin-top:4px; }}
.kpi.alerta {{ border-top-color:#C62828; }} .kpi.alerta .v {{ color:#C62828; }}
.kpi.ok {{ border-top-color:#2E7D32; }} .kpi.ok .v {{ color:#2E7D32; }}
.kpi.aviso {{ border-top-color:#EF8F00; }}
.kpi.neutro {{ border-top-color:#8A99AD; }}

/* Badges */
.badge {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:.78rem; font-weight:600; }}
.b-verde {{ background:#E5F4E7; color:#1B5E20; }} .b-amarelo {{ background:#FFF4D6; color:#8A5A00; }}
.b-vermelho {{ background:#FDE4E4; color:#B71C1C; }} .b-azul {{ background:#E3EEFA; color:#003366; }}
.b-cinza {{ background:#ECEFF3; color:#44505F; }} .b-roxo {{ background:#EFE7FA; color:#4A2A80; }}

.cartao {{ background:#fff; border-radius:12px; padding:16px 20px; margin-bottom:12px;
           box-shadow:0 1px 3px rgba(0,51,102,.08); }}
.alerta-inloco {{ background:#B71C1C; color:#fff; font-weight:800; text-align:center; padding:16px;
                  border-radius:10px; font-size:1.1rem; letter-spacing:.02em; margin:10px 0; }}
.contador {{ font-size:2.2rem; font-weight:700; color:var(--azul-medio); }}
@media (max-width: 1100px) {{ .cms-logo {{ display:none; }} .cms-tag {{ display:none; }} }}
</style>
"""


def aplicar_estilo() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def logo_sidebar() -> None:
    if LOGO_PATH.exists():
        st.logo(str(LOGO_PATH), size="large")


@st.cache_data
def _logo_base64() -> str | None:
    if not LOGO_PATH.exists():
        return None
    return base64.b64encode(LOGO_PATH.read_bytes()).decode()


def cabecalho(titulo: str, subtitulo: str = "") -> None:
    """Cabeçalho institucional com o logo (carregado com segurança, se existir)."""
    b64 = _logo_base64()
    logo_html = (f'<img src="data:image/png;base64,{b64}" alt="Crea-MS" class="cms-logo">' if b64 else "")
    st.markdown(
        f"""<div class="cms-header"><div class="cms-titulo">{logo_html}<div><h1>{html.escape(titulo)}</h1>
        <p>{html.escape(subtitulo)}</p></div></div>
        <span class="cms-tag">DFI · Art. 59 – Lei nº 5.194/1966</span></div>""",
        unsafe_allow_html=True,
    )
    if not b64:
        st.warning("Logo institucional não encontrado. Coloque o arquivo em `assets/logo_creams.png` "
                   "para exibi-lo na interface, nos e-mails e nos dossiês.", icon="🖼️")


def kpi(valor, rotulo: str, variante: str = "") -> str:
    return f'<div class="kpi {variante}"><div class="v">{valor}</div><div class="l">{html.escape(rotulo)}</div></div>'


def linha_kpis(itens: list[tuple], por_linha: int = 6) -> None:
    """Exibe cartões de KPI; acima de `por_linha` itens, divide em linhas equilibradas."""
    if len(itens) > por_linha:
        por_linha = (len(itens) + 1) // 2
    for inicio in range(0, len(itens), por_linha):
        grupo = itens[inicio:inicio + por_linha]
        cols = st.columns(por_linha)
        for col, item in zip(cols, grupo):
            col.markdown(kpi(*item), unsafe_allow_html=True)
        if inicio + por_linha < len(itens):
            st.write("")


COR_STATUS = {
    db.ST_AGUARDANDO_ENVIO: "b-cinza", db.ST_EMAIL_INVALIDO: "b-amarelo", db.ST_FALHA_ENVIO: "b-vermelho",
    db.ST_NOTIFICADO: "b-azul", db.ST_PRAZO_ENCERRADO: "b-vermelho", db.ST_RESPONDEU: "b-roxo",
    db.ST_REGULARIZADA: "b-verde", db.ST_ATUACAO_CONFIRMADA: "b-vermelho", db.ST_VISITA_IN_LOCO: "b-amarelo",
}


def badge(texto: str, classe: str) -> str:
    return f'<span class="badge {classe}">{html.escape(texto)}</span>'


def badge_status(status: str) -> str:
    return badge(status, COR_STATUS.get(status, "b-cinza"))


def situacao_prazo(status: str, data_limite: date | None, dias_alerta: int = 5) -> tuple[str, str]:
    """Retorna (texto com emoji, classe css) da situação do prazo."""
    if status == db.ST_REGULARIZADA:
        return "✅ Regularizada", "b-verde"
    if status == db.ST_RESPONDEU:
        return "💬 Em análise", "b-roxo"
    if status in (db.ST_PRAZO_ENCERRADO, db.ST_ATUACAO_CONFIRMADA, db.ST_VISITA_IN_LOCO):
        return "🔴 Prazo encerrado", "b-vermelho"
    if status == db.ST_NOTIFICADO and data_limite:
        restantes = (data_limite - hoje_local()).days
        if restantes < 0:
            return "🔴 Prazo encerrado", "b-vermelho"
        if restantes == 0:
            return "🟡 Vence hoje", "b-amarelo"
        if restantes <= dias_alerta:
            return f"🟡 Vence em {restantes} dia(s)", "b-amarelo"
        return f"🟢 No prazo ({restantes} dias)", "b-verde"
    return "⚪ Não notificada", "b-cinza"


def usuario_atual() -> str:
    """Nome do operador (informado na barra lateral) para trilha de auditoria."""
    return st.session_state.get("operador") or db.obter_config("responsavel_nome") or "Operador DFI"
