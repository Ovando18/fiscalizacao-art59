"""
Assistente de investigação em fontes abertas (OSINT).

Gera links de busca pré-formatados (dorks) com a Razão Social e o CNPJ, agrupados
pelas categorias usadas na diligência de constatação de atuação. Nenhuma busca é
feita automaticamente: o agente abre cada link e registra o que encontrar.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

from services.utils import formatar_cnpj, limpar_cnpj

_SUFIXOS = r"\b(LTDA|ME|EPP|EIRELI|S/?A|SLU|MEI|LIMITADA)\b\.?"


def nome_busca(razao_social: str) -> str:
    """Remove sufixos societários para ampliar a busca ('ACME OBRAS LTDA ME' -> 'ACME OBRAS')."""
    nome = re.sub(_SUFIXOS, "", razao_social.upper())
    nome = re.sub(r"[-–.,]+\s*$", "", re.sub(r"\s+", " ", nome)).strip()
    return nome or razao_social


def _google(q: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(q)}"


def gerar_links(razao_social: str, cnpj: str, municipio_uf: str = "MS") -> dict[str, list[dict]]:
    """Retorna {categoria: [{rotulo, url, descricao}]}."""
    nome = nome_busca(razao_social)
    cnpj_fmt = formatar_cnpj(cnpj)
    cnpj_num = limpar_cnpj(cnpj)
    ident = f'("{nome}" OR "{cnpj_fmt}" OR "{cnpj_num}")'

    return {
        "1. Contratos, empenhos, notas fiscais, obras e serviços": [
            {"rotulo": "Contratos / empenhos / NF",
             "url": _google(f'{ident} (contrato OR empenho OR "nota fiscal" OR "ordem de serviço")'),
             "descricao": "Busca geral por contratos, empenhos e notas fiscais."},
            {"rotulo": "Obras e serviços técnicos",
             "url": _google(f'{ident} (obra OR reforma OR construção OR instalação OR '
                            f'manutenção OR projeto OR orçamento) {municipio_uf}'),
             "descricao": "Indícios de execução de obras/serviços de engenharia."},
            {"rotulo": "Documentos PDF/planilhas",
             "url": _google(f'{ident} (filetype:pdf OR filetype:xlsx OR filetype:xls)'),
             "descricao": "Atas, planilhas orçamentárias e relatórios publicados."},
        ],
        "2. Portal da Transparência, Diários Oficiais e Licitações": [
            {"rotulo": "Portal da Transparência (CGU)",
             "url": f"https://portaldatransparencia.gov.br/busca?termo={cnpj_num}",
             "descricao": "Pagamentos e contratos federais vinculados ao CNPJ."},
            {"rotulo": "PNCP – Contratações Públicas",
             "url": f"https://pncp.gov.br/app/editais?q={quote_plus(cnpj_num)}",
             "descricao": "Portal Nacional de Contratações Públicas."},
            {"rotulo": "Diários Oficiais (.gov.br / .ms.gov.br)",
             "url": _google(f'{ident} (site:ms.gov.br OR site:gov.br OR site:diariooficialms.com.br '
                            f'OR site:diariomunicipal.com.br) (extrato OR homologação OR contrato)'),
             "descricao": "Extratos de contrato, homologações e publicações oficiais."},
            {"rotulo": "Licitações em geral",
             "url": _google(f'{ident} (licitação OR pregão OR "tomada de preços" OR dispensa '
                            f'OR "ata de registro de preços")'),
             "descricao": "Participação em certames públicos."},
        ],
        "3. Redes sociais": [
            {"rotulo": "Instagram",
             "url": _google(f'site:instagram.com "{nome}"'),
             "descricao": "Postagens de obras, serviços e portfólio."},
            {"rotulo": "LinkedIn",
             "url": _google(f'site:linkedin.com "{nome}"'),
             "descricao": "Página da empresa e profissionais vinculados."},
            {"rotulo": "Facebook",
             "url": _google(f'site:facebook.com "{nome}"'),
             "descricao": "Página comercial, avaliações e publicações."},
            {"rotulo": "Site próprio / Google Maps",
             "url": f"https://www.google.com/maps/search/{quote_plus(nome + ' ' + municipio_uf)}",
             "descricao": "Endereço, fotos e avaliações de clientes."},
        ],
        "4. Consulta pública de CNPJ / situação cadastral": [
            {"rotulo": "Receita Federal (Comprovante CNPJ)",
             "url": "https://solucoes.receita.fazenda.gov.br/Servicos/cnpjreva/Cnpjreva_Solicitacao.aspx",
             "descricao": f"Informe o CNPJ {cnpj_fmt} (exige captcha)."},
            {"rotulo": "BrasilAPI (dados abertos – JSON)",
             "url": f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_num}",
             "descricao": "Situação cadastral, CNAEs secundários, QSA e endereço."},
            {"rotulo": "Busca geral do CNPJ",
             "url": _google(f'"{cnpj_fmt}" OR "{cnpj_num}"'),
             "descricao": "Agregadores públicos de dados cadastrais."},
        ],
    }
