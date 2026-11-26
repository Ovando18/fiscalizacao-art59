"""
Funções utilitárias compartilhadas: CNPJ, e-mail, datas/fuso e números por extenso.

Observação sobre CNPJ: a partir de julho/2026 a Receita Federal passou a emitir
CNPJs alfanuméricos (IN RFB nº 2.229/2024). As funções abaixo aceitam tanto o
formato numérico tradicional quanto o alfanumérico (letras maiúsculas nas
12 primeiras posições e dígitos verificadores numéricos).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

FUSO_LOCAL = ZoneInfo("America/Campo_Grande")

# --------------------------------------------------------------------------- #
# Datas e fuso horário
# --------------------------------------------------------------------------- #

def agora_local() -> datetime:
    """Data/hora atual no fuso de Mato Grosso do Sul (America/Campo_Grande)."""
    return datetime.now(FUSO_LOCAL)


def hoje_local() -> date:
    return agora_local().date()


def fmt_data(valor: date | datetime | str | None) -> str:
    """Formata data no padrão brasileiro (dd/mm/aaaa)."""
    if not valor:
        return "—"
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor)
        except ValueError:
            return valor
    return valor.strftime("%d/%m/%Y")


def fmt_data_hora(valor: datetime | str | None) -> str:
    if not valor:
        return "—"
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor)
        except ValueError:
            return valor
    return valor.strftime("%d/%m/%Y %H:%M")


def calcular_data_limite(data_envio: date, prazo_dias: int) -> date:
    """Prazo em dias corridos contados a partir do dia seguinte ao envio."""
    return data_envio + timedelta(days=int(prazo_dias))


# --------------------------------------------------------------------------- #
# CNPJ
# --------------------------------------------------------------------------- #

_PESOS_DV1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_PESOS_DV2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def limpar_cnpj(valor) -> str:
    """Remove máscara e caracteres inválidos. Recompõe zeros à esquerda perdidos pelo Excel."""
    if valor is None:
        return ""
    texto = str(valor).strip().upper()
    # Excel pode transformar CNPJ numérico em float (ex.: '1234567000189.0')
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]
    texto = re.sub(r"[^0-9A-Z]", "", texto)
    if texto.isdigit() and len(texto) < 14:
        texto = texto.zfill(14)
    return texto


def _valor_char(c: str) -> int:
    # Regra oficial do CNPJ alfanumérico: valor = código ASCII - 48
    return ord(c) - 48


def validar_cnpj(valor) -> bool:
    """Valida dígitos verificadores (numérico ou alfanumérico)."""
    cnpj = limpar_cnpj(valor)
    if not re.fullmatch(r"[0-9A-Z]{12}\d{2}", cnpj):
        return False
    if len(set(cnpj)) == 1:
        return False
    soma = sum(_valor_char(c) * p for c, p in zip(cnpj[:12], _PESOS_DV1))
    dv1 = 0 if soma % 11 < 2 else 11 - soma % 11
    soma = sum(_valor_char(c) * p for c, p in zip(cnpj[:12] + str(dv1), _PESOS_DV2))
    dv2 = 0 if soma % 11 < 2 else 11 - soma % 11
    return cnpj[-2:] == f"{dv1}{dv2}"


def formatar_cnpj(valor) -> str:
    """Formata no padrão 00.000.000/0000-00. Retorna o texto limpo se não tiver 14 posições."""
    c = limpar_cnpj(valor)
    if len(c) != 14:
        return c
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


# --------------------------------------------------------------------------- #
# E-mail
# --------------------------------------------------------------------------- #

_RE_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def limpar_email(valor) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip().lower()
    if texto in {"nan", "none", "null"}:
        return ""
    # Algumas bases trazem vários e-mails separados por ';' ou ',' — usa o primeiro
    texto = re.split(r"[;,\s]+", texto)[0]
    return texto.strip(" .<>")


def validar_email(valor) -> bool:
    email = limpar_email(valor)
    return bool(email) and len(email) <= 254 and bool(_RE_EMAIL.match(email)) and ".." not in email


# --------------------------------------------------------------------------- #
# Texto
# --------------------------------------------------------------------------- #

def normalizar_nome_coluna(nome: str) -> str:
    """'Razão Social ' -> 'razaosocial' (para mapear variações de cabeçalho)."""
    nome = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", nome.lower())


def slug_arquivo(texto: str, limite: int = 50) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_")
    return texto[:limite] or "empresa"


_UNIDADES = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
             "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete",
             "dezoito", "dezenove"]
_DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta",
            "oitenta", "noventa"]
_CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos",
             "setecentos", "oitocentos", "novecentos"]


def numero_por_extenso(n: int) -> str:
    """Número inteiro (0–999) por extenso em português. Ex.: 30 -> 'trinta'."""
    n = int(n)
    if n < 0 or n > 999:
        return str(n)
    if n < 20:
        return _UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _DEZENAS[d] + (f" e {_UNIDADES[u]}" if u else "")
    if n == 100:
        return "cem"
    c, resto = divmod(n, 100)
    return _CENTENAS[c] + (f" e {numero_por_extenso(resto)}" if resto else "")
