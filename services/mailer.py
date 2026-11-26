"""
Motor de envio SMTP (Zimbra) com práticas anti-spam:

  * Mensagens multipart/alternative (texto puro + HTML leve)
  * Logo opcional embutido via CID (multipart/related)
  * Anexo opcional
  * Janela de expediente (padrão 12:00–18:00, America/Campo_Grande)
  * Intervalo randômico (jitter) entre envios
  * Log em logs/envios.log

Este módulo não depende do Streamlit: pode ser reutilizado por um worker/CLI.
"""
from __future__ import annotations

import html
import logging
import mimetypes
import random
import re
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from services.utils import (FUSO_LOCAL, agora_local, calcular_data_limite, fmt_data,
                            numero_por_extenso)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PADRAO = BASE_DIR / "templates" / "email_template.html"
LOGO_PATH = BASE_DIR / "assets" / "logo_creams.png"
LOG_DIR = BASE_DIR / "logs"

ASSUNTO_PADRAO = "Orientação sobre Registro de Pessoa Jurídica no Crea-MS – {razao_social}"

VARIAVEIS_SUPORTADAS = ["razao_social", "cnpj", "cnae", "descricao_cnae", "prazo_dias",
                        "prazo_extenso", "data_envio", "data_limite"]

# Rodapé institucional (opcional — desmarcado por padrão para não duplicar a assinatura)
RODAPE_INSTITUCIONAL = (
    '<p style="margin-top:18px;border-top:1px solid #d0d7e2;padding-top:10px;'
    'font-size:12px;color:#003366;">'
    "<strong>Departamento de Fiscalização – DFI</strong><br>"
    "Conselho Regional de Engenharia e Agronomia de Mato Grosso do Sul – Crea-MS<br>"
    "0800 368 1000 (ramais 1080 / 1014 / 1019) – dfi@creams.org.br</p>"
)

# --------------------------------------------------------------------------- #
# Log
# --------------------------------------------------------------------------- #
LOG_DIR.mkdir(exist_ok=True)
logger = logging.getLogger("mailer")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _h = logging.FileHandler(LOG_DIR / "envios.log", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_h)


# --------------------------------------------------------------------------- #
# Configuração SMTP
# --------------------------------------------------------------------------- #
@dataclass
class SMTPConfig:
    host: str
    port: int
    usuario: str
    senha: str
    remetente_nome: str = "Crea-MS – Departamento de Fiscalização"
    timeout: int = 30

    @property
    def usa_ssl(self) -> bool:
        return int(self.port) == 465


def _conectar(cfg: SMTPConfig) -> smtplib.SMTP:
    contexto = ssl.create_default_context()
    if cfg.usa_ssl:
        servidor = smtplib.SMTP_SSL(cfg.host, int(cfg.port), timeout=cfg.timeout, context=contexto)
    else:
        servidor = smtplib.SMTP(cfg.host, int(cfg.port), timeout=cfg.timeout)
        servidor.ehlo()
        servidor.starttls(context=contexto)
        servidor.ehlo()
    servidor.login(cfg.usuario, cfg.senha)
    return servidor


def testar_conexao(cfg: SMTPConfig) -> tuple[bool, str]:
    try:
        with _conectar(cfg) as srv:
            srv.noop()
        logger.info("Teste de conexão OK: %s:%s (%s)", cfg.host, cfg.port, cfg.usuario)
        return True, f"Conexão e autenticação bem-sucedidas em {cfg.host}:{cfg.port}."
    except smtplib.SMTPAuthenticationError:
        return False, "Falha de autenticação: verifique usuário e senha."
    except Exception as exc:  # noqa: BLE001
        logger.warning("Teste de conexão falhou: %s", exc)
        return False, f"Não foi possível conectar: {exc}"


# --------------------------------------------------------------------------- #
# Template
# --------------------------------------------------------------------------- #
def carregar_template_padrao() -> str:
    if TEMPLATE_PADRAO.exists():
        return TEMPLATE_PADRAO.read_text(encoding="utf-8")
    return "<p>Prezados(as),</p><p>Template padrão não encontrado.</p>"


def montar_variaveis(empresa: dict, prazo_dias: int, data_envio: datetime | None = None) -> dict:
    data_envio = data_envio or agora_local()
    data_limite = calcular_data_limite(data_envio.date(), prazo_dias)
    return {
        "razao_social": empresa.get("razao_social") or "",
        "cnpj": empresa.get("cnpj") or "",
        "cnae": empresa.get("cnae") or "não informado",
        "descricao_cnae": empresa.get("descricao_cnae") or "descrição não informada",
        "prazo_dias": str(prazo_dias),
        "prazo_extenso": numero_por_extenso(prazo_dias),
        "data_envio": fmt_data(data_envio),
        "data_limite": fmt_data(data_limite),
    }


def renderizar(texto: str, variaveis: dict, escapar_html: bool = True) -> str:
    """
    Substitui apenas as variáveis suportadas ({razao_social}, {cnpj}...).
    Não usa str.format para não quebrar chaves de CSS/HTML do template.
    """
    for chave, valor in variaveis.items():
        valor = html.escape(str(valor)) if escapar_html else str(valor)
        texto = texto.replace("{" + chave + "}", valor)
    return texto


def html_para_texto(conteudo_html: str) -> str:
    """Converte o HTML leve do template em texto puro legível (parte text/plain)."""
    t = re.sub(r"(?is)<(script|style).*?</\1>", "", conteudo_html)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)<li[^>]*>", "\n  • ", t)
    t = re.sub(r"(?i)</(p|div|ol|ul|h\d|tr)>", "\n\n", t)
    t = re.sub(r'(?i)<a[^>]+href="mailto:([^"]+)"[^>]*>.*?</a>', r"\1", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def compor_html(corpo: str, embutir_logo: bool, incluir_rodape: bool) -> str:
    """Envolve o corpo num HTML leve (sem CSS externo, sem imagens remotas)."""
    cabecalho = ""
    if embutir_logo and LOGO_PATH.exists():
        cabecalho = ('<p><img src="cid:logo_creams" alt="Crea-MS" width="220" '
                     'style="display:block;border:0;"></p>')
    rodape = RODAPE_INSTITUCIONAL if incluir_rodape else ""
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"></head>'
        '<body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        'line-height:1.5;color:#1f2933;">'
        f"{cabecalho}{corpo}{rodape}</body></html>"
    )


# --------------------------------------------------------------------------- #
# Montagem e envio
# --------------------------------------------------------------------------- #
def construir_mensagem(cfg: SMTPConfig, destinatario: str, assunto: str, html_completo: str,
                       embutir_logo: bool = False, anexo: tuple[str, bytes] | None = None
                       ) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.remetente_nome, cfg.usuario))
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg["Date"] = formatdate(localtime=True)
    dominio = cfg.usuario.split("@")[-1] if "@" in cfg.usuario else None
    msg["Message-ID"] = make_msgid(idstring=uuid.uuid4().hex[:12], domain=dominio)
    msg["Reply-To"] = cfg.usuario

    # multipart/alternative: texto puro primeiro, HTML depois
    msg.set_content(html_para_texto(html_completo), subtype="plain", charset="utf-8")
    msg.add_alternative(html_completo, subtype="html", charset="utf-8")

    if embutir_logo and LOGO_PATH.exists():
        parte_html = msg.get_payload()[1]
        # add_related transforma a parte HTML em multipart/related com a imagem CID
        parte_html.add_related(LOGO_PATH.read_bytes(), maintype="image", subtype="png",
                               cid="<logo_creams>", filename="logo_creams.png")

    if anexo:
        nome, conteudo = anexo
        tipo, _ = mimetypes.guess_type(nome)
        maintype, subtype = (tipo or "application/octet-stream").split("/", 1)
        msg.add_attachment(conteudo, maintype=maintype, subtype=subtype, filename=nome)
    return msg


def enviar(cfg: SMTPConfig, msg: EmailMessage) -> None:
    """Envia uma mensagem (abre e fecha a conexão — mais seguro em filas longas com jitter)."""
    with _conectar(cfg) as srv:
        srv.send_message(msg)
    logger.info("ENVIADO | para=%s | assunto=%s", msg["To"], msg["Subject"])


def preparar_email(empresa: dict, assunto_tpl: str, corpo_tpl: str, prazo_dias: int,
                   embutir_logo: bool, incluir_rodape: bool) -> dict:
    """Renderiza assunto/corpo para uma empresa. Retorna assunto, html e texto puro."""
    variaveis = montar_variaveis(empresa, prazo_dias)
    assunto = renderizar(assunto_tpl or ASSUNTO_PADRAO, variaveis, escapar_html=False)
    assunto = re.sub(r"\s+", " ", assunto).strip()
    corpo = renderizar(corpo_tpl or carregar_template_padrao(), variaveis)
    html_completo = compor_html(corpo, embutir_logo, incluir_rodape)
    return {"assunto": assunto, "html": html_completo, "texto": html_para_texto(html_completo)}


# --------------------------------------------------------------------------- #
# Janela de expediente e jitter
# --------------------------------------------------------------------------- #
def _hora(texto: str) -> time:
    h, m = texto.split(":")
    return time(int(h), int(m))


def dentro_da_janela(inicio: str, fim: str, agora: datetime | None = None) -> bool:
    agora = agora or agora_local()
    return _hora(inicio) <= agora.time() < _hora(fim)


def proxima_abertura(inicio: str, fim: str, agora: datetime | None = None) -> datetime:
    """Data/hora em que a próxima janela de envio abre (no fuso local)."""
    agora = agora or agora_local()
    abertura_hoje = datetime.combine(agora.date(), _hora(inicio), tzinfo=FUSO_LOCAL)
    if agora < abertura_hoje:
        return abertura_hoje
    return abertura_hoje + timedelta(days=1)


def sortear_intervalo(minimo: int, maximo: int) -> int:
    minimo, maximo = sorted((int(minimo), int(maximo)))
    return random.randint(minimo, maximo)
