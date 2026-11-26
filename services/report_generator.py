"""
Gerador do Dossiê / Relatório de Instrução e Constatação – Art. 59 da Lei nº 5.194/1966.

Usa fpdf2 com fontes padrão (Helvetica / Latin-1), sem dependências externas.
Caracteres fora do Latin-1 (travessões, aspas tipográficas, emojis) são normalizados.
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from database import db_manager as db
from services.utils import agora_local, fmt_data, fmt_data_hora, slug_arquivo

BASE_DIR = Path(__file__).resolve().parent.parent
LOGO_PATH = BASE_DIR / "assets" / "logo_creams.png"

AZUL_MARINHO = (0, 51, 102)
AZUL_MEDIO = (0, 85, 165)
CINZA_CLARO = (244, 246, 249)
VERMELHO = (180, 20, 30)

TITULO = "RELATÓRIO DE INSTRUÇÃO E CONSTATAÇÃO – ART. 59 DA LEI Nº 5.194/1966"

_SUBSTITUICOES = {
    "–": "-", "—": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "•": "-", "…": "...",
    "→": "->", "☎": "Tel.:", "✉": "E-mail:", " ": " ", "​": "",
}


def _t(texto) -> str:
    """Normaliza texto para Latin-1 (fontes padrão do PDF)."""
    if texto is None:
        return "-"
    texto = str(texto)
    for de, para in _SUBSTITUICOES.items():
        texto = texto.replace(de, para)
    return texto.encode("latin-1", "replace").decode("latin-1")


class DossiePDF(FPDF):
    def __init__(self, protocolo: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.protocolo = protocolo
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(18, 15, 18)

    # Cabeçalho oficial em todas as páginas
    def header(self):
        if LOGO_PATH.exists():
            self.image(str(LOGO_PATH), x=18, y=10, h=14)
        self.set_xy(110, 11)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*AZUL_MARINHO)
        self.multi_cell(82, 4, _t("Departamento de Fiscalização – DFI\nCrea-MS"), align="R")
        self.set_xy(110, self.get_y())
        self.set_font("Helvetica", "", 7)
        self.cell(82, 4, _t(f"Dossiê nº {self.protocolo}"), align="R")
        self.set_draw_color(*AZUL_MEDIO)
        self.set_line_width(0.6)
        self.line(18, 27, 192, 27)
        self.set_y(31)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(110, 110, 110)
        self.cell(0, 5, _t(f"Gerado em {fmt_data_hora(agora_local())} – Sistema de Gestão de "
                           f"Notificações Art. 59 – DFI/Crea-MS"), align="L")
        self.cell(0, 5, f"Página {self.page_no()}/{{nb}}", align="R")

    # Helpers de layout
    def secao(self, titulo: str):
        if self.get_y() > 255:
            self.add_page()
        self.ln(3)
        self.set_fill_color(*AZUL_MARINHO)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 7, _t("  " + titulo), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)
        self.set_text_color(30, 30, 30)

    def campo(self, rotulo: str, valor, larg_rotulo: float = 42):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*AZUL_MARINHO)
        y = self.get_y()
        self.multi_cell(larg_rotulo, 5.5, _t(rotulo), new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 5.5, _t(valor if valor not in (None, "") else "-"),
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(max(self.get_y(), y + 5.5))

    def paragrafo(self, texto: str, tamanho: int = 9, estilo: str = ""):
        self.set_font("Helvetica", estilo, tamanho)
        self.multi_cell(0, 5, _t(texto), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def destaque(self, texto: str, cor=VERMELHO):
        self.ln(1)
        self.set_fill_color(*cor)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 10)
        self.multi_cell(0, 7, _t(texto), fill=True, align="C",
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(30, 30, 30)
        self.ln(1)


def _conclusao(emp: dict) -> tuple[str, bool]:
    """Texto de conclusão automática conforme o estágio do processo. Retorna (texto, destaque_in_loco)."""
    st = emp["status"]
    limite = fmt_data(emp.get("data_limite"))
    if st == db.ST_REGULARIZADA:
        return (f"A empresa promoveu sua regularização perante o Crea-MS, com registro de pessoa "
                f"jurídica nº {emp.get('numero_registro') or '-'} efetivado em "
                f"{fmt_data(emp.get('data_regularizacao'))}. A orientação atingiu sua finalidade, "
                f"sugerindo-se o arquivamento do presente procedimento.", False)
    if st == db.ST_RESPONDEU:
        return (f"A empresa apresentou resposta/esclarecimentos em {fmt_data(emp.get('data_resposta'))} "
                f"(protocolo {emp.get('protocolo') or '-'}), que se encontram em análise pelo DFI. "
                f"Aguarda-se a conclusão da análise para definição das providências cabíveis.", False)
    if st == db.ST_ATUACAO_CONFIRMADA:
        return (f"Encerrado em {limite} o prazo concedido na notificação orientativa sem a devida "
                f"regularização, foram localizados, em diligência realizada em fontes abertas na "
                f"internet, indícios de atuação da empresa em atividades fiscalizadas pelo Sistema "
                f"Confea/Crea, conforme registros acima. Encaminha-se o presente dossiê para a "
                f"adoção das providências fiscalizatórias cabíveis, nos termos do art. 59 da Lei "
                f"nº 5.194/1966.", False)
    if st == db.ST_VISITA_IN_LOCO:
        return (f"Encerrado em {limite} o prazo concedido na notificação orientativa sem a devida "
                f"regularização, e não tendo sido localizados indícios de atuação em diligência "
                f"realizada em fontes abertas na internet, faz-se NECESSÁRIA VISITA IN-LOCO PARA "
                f"CONSTATAÇÃO DE ATUAÇÃO, razão pela qual se encaminha o presente dossiê à equipe "
                f"de fiscalização para programação da diligência.", True)
    if st == db.ST_PRAZO_ENCERRADO:
        return (f"O prazo concedido encerrou-se em {limite} sem registro de regularização ou "
                f"resposta. Pendente a diligência de investigação de atuação em fontes abertas.", False)
    if st == db.ST_NOTIFICADO:
        return (f"A empresa foi notificada em caráter orientativo e encontra-se dentro do prazo "
                f"concedido (data limite: {limite}).", False)
    return (f"Procedimento em fase preliminar (situação atual: {st}).", False)


def gerar_dossie(empresa_id: int, responsavel_nome: str = "", responsavel_cargo: str = "") -> tuple[bytes, str]:
    """Gera o PDF do dossiê. Retorna (bytes_pdf, nome_arquivo)."""
    emp = db.obter_empresa(empresa_id)
    if emp is None:
        raise ValueError("Empresa não encontrada.")

    protocolo = f"DFI-ART59-{emp['id']:06d}-{agora_local().strftime('%Y%m%d')}"
    pdf = DossiePDF(protocolo)
    pdf.alias_nb_pages()
    pdf.add_page()

    # Título
    pdf.set_font("Helvetica", "B", 12.5)
    pdf.set_text_color(*AZUL_MARINHO)
    pdf.multi_cell(0, 7, _t(TITULO), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _t("Fundamentação: art. 59 da Lei nº 5.194/1966; art. 1º da Lei nº 6.839/1980; "
                      "art. 3º da Resolução Confea nº 1.121/2019"), align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 1. Dados cadastrais
    pdf.secao("1. IDENTIFICAÇÃO DA EMPRESA")
    pdf.campo("Razão Social:", emp["razao_social"])
    pdf.campo("CNPJ:", emp["cnpj"])
    pdf.campo("CNAE:", f"{emp.get('cnae') or '-'} - {emp.get('descricao_cnae') or 'descrição não informada'}")
    pdf.campo("E-mail:", emp.get("email"))
    pdf.campo("Lote / Operação:", f"{emp['lote_nome']}{' (LOTE DE TESTE)' if emp['lote_teste'] else ''}")
    pdf.campo("Situação atual:", emp["status"])

    # 2. Notificação orientativa
    pdf.secao("2. NOTIFICAÇÃO ORIENTATIVA")
    pdf.campo("Data de importação:", fmt_data_hora(emp.get("data_importacao")))
    pdf.campo("Envio do e-mail:", fmt_data_hora(emp.get("data_envio")) if emp.get("data_envio")
              else "Não enviado")
    pdf.campo("Prazo concedido:", f"{emp['prazo_dias']} dias" if emp.get("prazo_dias") else "-")
    pdf.campo("Data limite:", fmt_data(emp.get("data_limite")))
    if emp.get("assunto_enviado"):
        pdf.campo("Assunto:", emp["assunto_enviado"])
    if emp.get("corpo_enviado"):
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*AZUL_MARINHO)
        pdf.cell(0, 5, _t("Texto integral enviado:"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_fill_color(*CINZA_CLARO)
        pdf.set_text_color(40, 40, 40)
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(0, 4.2, _t(emp["corpo_enviado"]), fill=True, border=0,
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 3. Resposta / regularização
    pdf.secao("3. RESPOSTA / REGULARIZAÇÃO")
    if emp.get("data_resposta") or emp.get("numero_registro"):
        if emp.get("data_resposta"):
            pdf.campo("Data da resposta:", fmt_data_hora(emp["data_resposta"]))
            pdf.campo("Protocolo:", emp.get("protocolo"))
            pdf.campo("Resumo:", emp.get("resposta_resumo"))
        if emp.get("numero_registro"):
            pdf.campo("Registro Crea-MS:", emp["numero_registro"])
            pdf.campo("Data:", fmt_data_hora(emp.get("data_regularizacao")))
    else:
        pdf.paragrafo("Não houve registro de resposta ou de regularização até a data de emissão "
                      "deste relatório.")

    # 4. Diligência na internet
    pdf.secao("4. DILIGÊNCIA EM FONTES ABERTAS (INTERNET)")
    if emp.get("data_investigacao"):
        pdf.campo("Data da diligência:", fmt_data_hora(emp["data_investigacao"]))
        pdf.campo("Responsável:", emp.get("responsavel_investigacao"))
        pdf.campo("Indícios localizados:", "SIM" if emp.get("indicios_internet") else "NÃO")
        pdf.campo("Registros:", emp.get("evidencias_texto"))
    else:
        pdf.paragrafo("Diligência ainda não realizada.")

    arquivos = emp.get("arquivos") or []
    if arquivos:
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*AZUL_MARINHO)
        pdf.cell(0, 5, _t(f"Evidências anexadas ({len(arquivos)}):"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(30, 30, 30)
        for i, arq in enumerate(arquivos, 1):
            caminho = BASE_DIR / arq["caminho"]
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(0, 4.5, _t(f"Anexo {i}: {arq['nome_original']} "
                                      f"(incluído em {fmt_data_hora(arq['enviado_em'])})"),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if caminho.suffix.lower() in (".png", ".jpg", ".jpeg") and caminho.exists():
                try:
                    if pdf.get_y() > 170:
                        pdf.add_page()
                    pdf.image(str(caminho), x=pdf.l_margin, w=120, keep_aspect_ratio=True, h=90)
                    pdf.ln(3)
                except Exception:  # noqa: BLE001 - imagem corrompida não deve impedir o dossiê
                    pdf.paragrafo("(imagem não pôde ser incorporada)", 8, "I")
            elif caminho.suffix.lower() == ".pdf":
                pdf.paragrafo(f"Documento PDF arquivado em: {arq['caminho']}", 8, "I")

    # 5. Histórico cronológico
    pdf.secao("5. HISTÓRICO CRONOLÓGICO")
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_fill_color(*CINZA_CLARO)
    pdf.set_text_color(*AZUL_MARINHO)
    pdf.cell(32, 6, _t("Data/Hora"), fill=True)
    pdf.cell(52, 6, _t("Evento"), fill=True)
    pdf.cell(0, 6, _t("Detalhe"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "", 8)
    for h in emp["historico"]:
        if pdf.get_y() > 265:
            pdf.add_page()
        y0 = pdf.get_y()
        pdf.multi_cell(32, 4.5, _t(fmt_data_hora(h["data_hora"])), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.multi_cell(52, 4.5, _t(h["evento"]), new_x=XPos.RIGHT, new_y=YPos.TOP)
        detalhe = (h["detalhe"] or "") + (f" [{h['usuario']}]" if h.get("usuario") else "")
        pdf.multi_cell(0, 4.5, _t(detalhe or "-"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        y1 = max(pdf.get_y(), y0 + 4.5)
        pdf.set_draw_color(220, 225, 232)
        pdf.set_line_width(0.2)
        pdf.line(18, y1 + 0.8, 192, y1 + 0.8)
        pdf.set_y(y1 + 1.6)

    # 6. Conclusão
    pdf.secao("6. CONCLUSÃO")
    texto, in_loco = _conclusao(emp)
    if in_loco:
        pdf.destaque("NECESSÁRIA VISITA IN-LOCO PARA CONSTATAÇÃO DE ATUAÇÃO")
    pdf.paragrafo(texto, 9.5)

    # Assinatura
    if pdf.get_y() > 235:
        pdf.add_page()
    pdf.ln(14)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _t(f"Campo Grande/MS, {fmt_data(agora_local())}."), align="R",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(14)
    pdf.set_draw_color(60, 60, 60)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(1.5)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _t(responsavel_nome or "Nome do responsável"), align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(0, 5, _t(responsavel_cargo or "Cargo / Matrícula"), align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 5, _t("Departamento de Fiscalização – DFI / Crea-MS"), align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    nome_arquivo = f"Dossie_{emp['cnpj_limpo']}_{slug_arquivo(emp['razao_social'])}.pdf"
    return bytes(pdf.output()), nome_arquivo
