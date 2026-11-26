"""
Gera `exemplo_planilha_cnaes.xlsx` (dados FICTÍCIOS) para testar a importação.

Uso:  python scripts/gerar_planilha_exemplo.py

A planilha usa propositalmente cabeçalhos com acentos/variações ("Razão Social",
"E-mail", "Descrição CNAE") para demonstrar o mapeamento automático, e inclui
casos de teste: e-mail inválido, e-mail ausente, CNPJ sem máscara e linha duplicada.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.utils import formatar_cnpj  # noqa: E402

CNAES = [
    ("4120-4/00", "Construção de edifícios"),
    ("4211-1/01", "Construção de rodovias e ferrovias"),
    ("4321-5/00", "Instalação e manutenção elétrica"),
    ("4322-3/02", "Instalação e manutenção de sistemas centrais de ar condicionado, de ventilação e refrigeração"),
    ("7112-0/00", "Serviços de engenharia"),
    ("7119-7/01", "Serviços de cartografia, topografia e geodésia"),
    ("4330-4/04", "Serviços de pintura de edifícios em geral"),
    ("0161-0/01", "Serviço de pulverização e controle de pragas agrícolas"),
]
PREFIXOS = ["ALFA", "BETA", "PANTANAL", "CERRADO", "HORIZONTE", "PIONEIRA", "AURORA", "VALE VERDE",
            "SERRA AZUL", "PRIMUS", "NOVA ERA", "TERRA FIRME", "ATLAS", "VETOR", "ÁGUA CLARA"]
SUFIXOS = {"4120-4/00": "CONSTRUÇÕES", "4211-1/01": "TERRAPLENAGEM", "4321-5/00": "INSTALAÇÕES ELÉTRICAS",
           "4322-3/02": "CLIMATIZAÇÃO", "7112-0/00": "ENGENHARIA", "7119-7/01": "TOPOGRAFIA",
           "4330-4/04": "PINTURAS E REFORMAS", "0161-0/01": "AGROSERVIÇOS"}


def gerar_cnpj(rng: random.Random) -> str:
    """CNPJ numérico fictício com dígitos verificadores válidos (matriz 0001)."""
    base = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    d1 = sum(a * b for a, b in zip(base, pesos1)) % 11
    d1 = 0 if d1 < 2 else 11 - d1
    d2 = sum(a * b for a, b in zip(base + [d1], pesos2)) % 11
    d2 = 0 if d2 < 2 else 11 - d2
    return "".join(map(str, base + [d1, d2]))


def main() -> Path:
    rng = random.Random(59)
    linhas = []
    for i in range(30):
        cnae, desc = CNAES[i % len(CNAES)]
        nome = f"{rng.choice(PREFIXOS)} {SUFIXOS[cnae]} {rng.choice(['LTDA', 'LTDA - ME', 'EIRELI', 'S/A'])}"
        cnpj = gerar_cnpj(rng)
        email = f"contato{i + 1:02d}@empresa-ficticia-{i + 1:02d}.com.br"
        linhas.append({"Razão Social": nome,
                       "CNPJ": formatar_cnpj(cnpj) if i % 3 else cnpj,   # mistura com e sem máscara
                       "CNAE": cnae, "Descrição CNAE": desc, "E-mail": email})
    # Casos de teste de saneamento
    linhas[4]["E-mail"] = "contato.empresa@@invalido"
    linhas[9]["E-mail"] = ""
    linhas[14]["E-mail"] = "  FINANCEIRO@EMPRESA-FICTICIA-15.COM.BR ; outro@x.com"
    linhas.append(dict(linhas[2]))  # linha duplicada no próprio arquivo

    destino = Path(__file__).resolve().parent.parent / "exemplo_planilha_cnaes.xlsx"
    with pd.ExcelWriter(destino, engine="openpyxl") as w:
        pd.DataFrame(linhas).to_excel(w, index=False, sheet_name="Empresas")
        ws = w.sheets["Empresas"]
        for col, larg in zip("ABCDE", (48, 22, 12, 70, 46)):
            ws.column_dimensions[col].width = larg
    print(f"Planilha gerada: {destino} ({len(linhas)} linhas)")
    return destino


if __name__ == "__main__":
    main()
