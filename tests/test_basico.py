"""Testes básicos (pytest). Usam um banco SQLite temporário."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/teste.db"

from database import db_manager as db  # noqa: E402
from services import mailer  # noqa: E402
from services.utils import (formatar_cnpj, limpar_cnpj, numero_por_extenso,  # noqa: E402
                            validar_cnpj, validar_email)


def test_cnpj():
    assert validar_cnpj("11.222.333/0001-81")
    assert not validar_cnpj("11.222.333/0001-82")
    assert validar_cnpj("12ABC34501DE35")             # CNPJ alfanumérico
    assert limpar_cnpj("1222333000181.0") == "01222333000181"
    assert formatar_cnpj("11222333000181") == "11.222.333/0001-81"


def test_email_e_extenso():
    assert validar_email("dfi@creams.org.br")
    assert not validar_email("a@@b")
    assert numero_por_extenso(30) == "trinta"
    assert numero_por_extenso(45) == "quarenta e cinco"


def test_fluxo_cota_e_status():
    db.init_db()
    reg = dict(razao_social="ACME LTDA", cnpj="11.222.333/0001-81", cnpj_limpo="11222333000181",
               cnae="7112-0/00", descricao_cnae="Serviços de engenharia", email="a@b.com", email_valido=True)
    assert db.importar_empresas([reg], "Oficial", False)["inseridos"] == 1
    assert db.importar_empresas([reg], "Oficial", False)["ignorados"] == 1
    cota = db.calcular_cota_hoje()
    assert cota["meta"] == 20 and cota["restantes"] == 20
    emp = db.fila_envio()[0]
    em = mailer.preparar_email(emp, "", "", 30, False, False)
    assert "ACME LTDA" in em["assunto"] and "trinta" in em["texto"]
    db.registrar_envio_sucesso(emp["id"], em["assunto"], em["texto"], 30)
    assert db.calcular_cota_hoje()["enviados"] == 1
    assert db.registrar_investigacao(emp["id"], False, "", "teste") == db.ST_VISITA_IN_LOCO
    lote_id = db.listar_lotes()[0]["id"]
    assert db.excluir_lote(lote_id) == {"empresas": 1, "envios": 1}
    assert db.calcular_cota_hoje()["enviados"] == 0


def test_mensagem_mime():
    cfg = mailer.SMTPConfig("smtp.exemplo", 587, "dfi@creams.org.br", "x")
    em = mailer.preparar_email({"razao_social": "X", "cnpj": "1"}, "", "", 10, True, False)
    msg = mailer.construir_mensagem(cfg, "a@b.com", em["assunto"], em["html"], True)
    tipos = [p.get_content_type() for p in msg.walk()]
    assert tipos[0] == "multipart/alternative" and "text/plain" in tipos and "text/html" in tipos


def test_storage_local_e_url(tmp_path):
    from services.storage import ErroArmazenamento, LocalStorage
    st = LocalStorage(tmp_path)
    st.salvar("11222333000181/a.png", b"x")
    assert st.ler("11222333000181/a.png") == b"x"
    assert st.ler("evidencias/11222333000181/a.png") == b"x"   # registros antigos
    st.excluir_prefixo("11222333000181")
    assert st.ler("11222333000181/a.png") is None
    try:
        st.ler("../../etc/passwd")
        raise AssertionError("deveria bloquear path traversal")
    except ErroArmazenamento:
        pass
    assert db._normalizar_url("postgres://u:p@h:5432/d") == "postgresql+psycopg2://u:p@h:5432/d"
    assert db._normalizar_url("postgresql://u:p@h/d").startswith("postgresql+psycopg2://")
