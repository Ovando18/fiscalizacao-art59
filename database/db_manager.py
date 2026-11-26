"""
Camada de persistência do sistema (SQLAlchemy ORM).

- Banco padrão: SQLite em database/fiscalizacao_art59.db
- Para migrar para PostgreSQL/Supabase basta definir a variável de ambiente
  DATABASE_URL (ex.: postgresql+psycopg2://usuario:senha@host:5432/banco).
  Os modelos usam apenas tipos portáveis.

Responsabilidades:
  * Modelos (Lote, Empresa, Historico, Envio, EvidenciaArquivo, Configuracao)
  * CRUD e controle de duplicidade de CNPJ
  * Gestão de lotes (inclusive exclusão segura de lotes de teste)
  * Cálculo da cota diária de aquecimento gradual (ramp-up)
"""
from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, String, Text,
                        create_engine, func, select)
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column, relationship,
                            sessionmaker)

from services.utils import agora_local, calcular_data_limite, hoje_local

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "fiscalizacao_art59.db"
EVIDENCIAS_DIR = BASE_DIR / "evidencias"

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH.as_posix()}"

# --------------------------------------------------------------------------- #
# Status do fluxo de fiscalização
# --------------------------------------------------------------------------- #
ST_AGUARDANDO_ENVIO = "Aguardando Envio"
ST_EMAIL_INVALIDO = "E-mail Inválido / Sem Contato"
ST_FALHA_ENVIO = "Falha no Envio"
ST_NOTIFICADO = "Notificado - Aguardando Prazo"
ST_PRAZO_ENCERRADO = "Prazo Encerrado - Investigar Atuação"
ST_RESPONDEU = "Respondeu / Em Análise"
ST_REGULARIZADA = "Regularizada (Registro Efetivado)"
ST_ATUACAO_CONFIRMADA = "Atuação Confirmada (Investigação / Fiscalização)"
ST_VISITA_IN_LOCO = "Aguardando Visita In-Loco"

TODOS_STATUS = [
    ST_AGUARDANDO_ENVIO, ST_EMAIL_INVALIDO, ST_FALHA_ENVIO, ST_NOTIFICADO, ST_PRAZO_ENCERRADO,
    ST_RESPONDEU, ST_REGULARIZADA, ST_ATUACAO_CONFIRMADA, ST_VISITA_IN_LOCO,
]


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class Base(DeclarativeBase):
    pass


def _agora() -> datetime:
    # Armazenamos data/hora local "ingênua" (sem tzinfo) para portabilidade SQLite/Postgres
    return agora_local().replace(tzinfo=None, microsecond=0)


class Lote(Base):
    __tablename__ = "lotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(200), unique=True)
    is_teste: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=_agora)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)

    empresas: Mapped[list["Empresa"]] = relationship(back_populates="lote")


class Empresa(Base):
    __tablename__ = "empresas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), index=True)
    razao_social: Mapped[str] = mapped_column(String(300))
    cnpj: Mapped[str] = mapped_column(String(18))                    # formatado
    cnpj_limpo: Mapped[str] = mapped_column(String(14), unique=True, index=True)
    cnae: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    descricao_cnae: Mapped[str | None] = mapped_column(String(400), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    email_valido: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(80), default=ST_AGUARDANDO_ENVIO, index=True)

    data_importacao: Mapped[datetime] = mapped_column(DateTime, default=_agora)
    data_envio: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    prazo_dias: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_limite: Mapped[date | None] = mapped_column(Date, nullable=True)
    assunto_enviado: Mapped[str | None] = mapped_column(Text, nullable=True)
    corpo_enviado: Mapped[str | None] = mapped_column(Text, nullable=True)   # texto puro
    tentativas_envio: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_erro: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resposta / regularização
    resposta_resumo: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocolo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data_resposta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    numero_registro: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data_regularizacao: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Investigação (OSINT)
    indicios_internet: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evidencias_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_investigacao: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responsavel_investigacao: Mapped[str | None] = mapped_column(String(200), nullable=True)

    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=_agora, onupdate=_agora)

    lote: Mapped[Lote] = relationship(back_populates="empresas")
    historico: Mapped[list["Historico"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan", order_by="Historico.data_hora")
    arquivos: Mapped[list["EvidenciaArquivo"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan")


class Historico(Base):
    """Linha do tempo de cada empresa (base do dossiê)."""
    __tablename__ = "historico"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    data_hora: Mapped[datetime] = mapped_column(DateTime, default=_agora)
    evento: Mapped[str] = mapped_column(String(120))
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    usuario: Mapped[str | None] = mapped_column(String(200), nullable=True)

    empresa: Mapped[Empresa] = relationship(back_populates="historico")


class Envio(Base):
    """Log de cada tentativa de disparo (base do cálculo de aquecimento)."""
    __tablename__ = "envios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    empresa_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    lote_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    destinatario: Mapped[str | None] = mapped_column(String(254), nullable=True)
    data_hora: Mapped[datetime] = mapped_column(DateTime, default=_agora)
    data_local: Mapped[date] = mapped_column(Date, index=True)
    sucesso: Mapped[bool] = mapped_column(Boolean)
    is_teste: Mapped[bool] = mapped_column(Boolean, default=False)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenciaArquivo(Base):
    __tablename__ = "evidencias_arquivos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    nome_original: Mapped[str] = mapped_column(String(300))
    caminho: Mapped[str] = mapped_column(String(600))
    enviado_em: Mapped[datetime] = mapped_column(DateTime, default=_agora)

    empresa: Mapped[Empresa] = relationship(back_populates="arquivos")


class Configuracao(Base):
    __tablename__ = "configuracoes"
    chave: Mapped[str] = mapped_column(String(100), primary_key=True)
    valor: Mapped[str] = mapped_column(Text)


# --------------------------------------------------------------------------- #
# Engine / sessão
# --------------------------------------------------------------------------- #
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIAS_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


@contextmanager
def sessao() -> Iterable[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _registrar(s: Session, empresa_id: int, evento: str, detalhe: str | None = None,
               usuario: str | None = None) -> None:
    s.add(Historico(empresa_id=empresa_id, evento=evento, detalhe=detalhe, usuario=usuario))


# --------------------------------------------------------------------------- #
# Configurações (chave/valor JSON)
# --------------------------------------------------------------------------- #
CONFIG_PADRAO: dict[str, Any] = {
    "prazo_dias": 30,
    "aquecimento_ativo": True,
    "aquecimento_inicial": 20,
    "aquecimento_incremento": 5,
    "aquecimento_teto": 90,
    "janela_inicio": "12:00",
    "janela_fim": "18:00",
    "jitter_min": 45,
    "jitter_max": 90,
    "incluir_assinatura": False,
    "embutir_logo": False,
    "assunto_template": "",
    "corpo_template": "",
    "responsavel_nome": "",
    "responsavel_cargo": "Agente de Fiscalização – DFI/Crea-MS",
    "dias_alerta_vencimento": 5,
}


def obter_config(chave: str) -> Any:
    with sessao() as s:
        reg = s.get(Configuracao, chave)
        if reg is None:
            return CONFIG_PADRAO.get(chave)
        return json.loads(reg.valor)


def obter_todas_config() -> dict[str, Any]:
    cfg = dict(CONFIG_PADRAO)
    with sessao() as s:
        for reg in s.scalars(select(Configuracao)):
            cfg[reg.chave] = json.loads(reg.valor)
    return cfg


def salvar_config(valores: dict[str, Any]) -> None:
    with sessao() as s:
        for chave, valor in valores.items():
            reg = s.get(Configuracao, chave)
            if reg is None:
                s.add(Configuracao(chave=chave, valor=json.dumps(valor, ensure_ascii=False)))
            else:
                reg.valor = json.dumps(valor, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Lotes
# --------------------------------------------------------------------------- #
def listar_lotes() -> list[dict]:
    with sessao() as s:
        linhas = s.execute(
            select(Lote, func.count(Empresa.id))
            .outerjoin(Empresa, Empresa.lote_id == Lote.id)
            .group_by(Lote.id).order_by(Lote.criado_em.desc())
        ).all()
        resultado = []
        for lote, qtd in linhas:
            enviados = s.scalar(select(func.count(Envio.id)).where(
                Envio.lote_id == lote.id, Envio.sucesso.is_(True))) or 0
            resultado.append({"id": lote.id, "nome": lote.nome, "is_teste": lote.is_teste,
                              "criado_em": lote.criado_em, "empresas": qtd, "enviados": enviados,
                              "observacao": lote.observacao})
        return resultado


def obter_ou_criar_lote(s: Session, nome: str, is_teste: bool, observacao: str | None = None) -> Lote:
    lote = s.scalar(select(Lote).where(Lote.nome == nome))
    if lote is None:
        lote = Lote(nome=nome, is_teste=is_teste, observacao=observacao)
        s.add(lote)
        s.flush()
    return lote


def excluir_lote(lote_id: int) -> dict:
    """
    Exclui o lote, suas empresas, históricos, evidências (arquivos) e o log de envios.
    Remover o log de envios garante que o contador de aquecimento não seja contaminado.
    """
    with sessao() as s:
        lote = s.get(Lote, lote_id)
        if lote is None:
            return {"empresas": 0, "envios": 0}
        empresas = list(s.scalars(select(Empresa).where(Empresa.lote_id == lote_id)))
        for emp in empresas:
            pasta = EVIDENCIAS_DIR / emp.cnpj_limpo
            if pasta.exists():
                shutil.rmtree(pasta, ignore_errors=True)
            s.delete(emp)
        envios = list(s.scalars(select(Envio).where(Envio.lote_id == lote_id)))
        for env in envios:
            s.delete(env)
        s.delete(lote)
        return {"empresas": len(empresas), "envios": len(envios)}


# --------------------------------------------------------------------------- #
# Empresas — importação e duplicidade
# --------------------------------------------------------------------------- #
def cnpjs_existentes(cnpjs_limpos: list[str]) -> dict[str, dict]:
    """Retorna {cnpj_limpo: {razao_social, lote, status}} dos CNPJs já cadastrados."""
    if not cnpjs_limpos:
        return {}
    resultado: dict[str, dict] = {}
    with sessao() as s:
        # Consulta em blocos para respeitar limites de parâmetros do SQLite
        for i in range(0, len(cnpjs_limpos), 500):
            bloco = cnpjs_limpos[i:i + 500]
            for emp in s.scalars(select(Empresa).where(Empresa.cnpj_limpo.in_(bloco))):
                resultado[emp.cnpj_limpo] = {"razao_social": emp.razao_social,
                                             "lote": emp.lote.nome, "status": emp.status}
    return resultado


def importar_empresas(registros: list[dict], nome_lote: str, is_teste: bool,
                      politica_duplicados: str = "ignorar", observacao: str | None = None) -> dict:
    """
    Importa registros já saneados. Cada registro: razao_social, cnpj, cnpj_limpo, cnae,
    descricao_cnae, email, email_valido.

    politica_duplicados: 'ignorar' (mantém o cadastro existente) ou 'atualizar'
    (atualiza dados cadastrais, sem apagar histórico/status de fiscalização).
    """
    inseridos = atualizados = ignorados = 0
    with sessao() as s:
        lote = obter_ou_criar_lote(s, nome_lote, is_teste, observacao)
        for r in registros:
            existente = s.scalar(select(Empresa).where(Empresa.cnpj_limpo == r["cnpj_limpo"]))
            if existente:
                if politica_duplicados == "atualizar":
                    alteracoes = []
                    for campo in ("razao_social", "cnae", "descricao_cnae", "email"):
                        novo = r.get(campo) or None
                        if novo and novo != getattr(existente, campo):
                            alteracoes.append(f"{campo}: '{getattr(existente, campo)}' → '{novo}'")
                            setattr(existente, campo, novo)
                    existente.email_valido = r["email_valido"]
                    if existente.status == ST_EMAIL_INVALIDO and r["email_valido"]:
                        existente.status = ST_AGUARDANDO_ENVIO
                    _registrar(s, existente.id, "Dados atualizados por reimportação",
                               f"Lote '{nome_lote}'. " + ("; ".join(alteracoes) or "Sem alterações."))
                    atualizados += 1
                else:
                    ignorados += 1
                continue
            emp = Empresa(
                lote_id=lote.id, razao_social=r["razao_social"], cnpj=r["cnpj"],
                cnpj_limpo=r["cnpj_limpo"], cnae=r.get("cnae") or None,
                descricao_cnae=r.get("descricao_cnae") or None, email=r.get("email") or None,
                email_valido=r["email_valido"],
                status=ST_AGUARDANDO_ENVIO if r["email_valido"] else ST_EMAIL_INVALIDO,
            )
            s.add(emp)
            s.flush()
            _registrar(s, emp.id, "Importação da base cadastral",
                       f"Lote '{nome_lote}'{' (TESTE)' if is_teste else ''}. CNAE {emp.cnae or '—'}.")
            inseridos += 1
    return {"inseridos": inseridos, "atualizados": atualizados, "ignorados": ignorados}


def _empresa_para_dict(emp: Empresa) -> dict:
    d = {c.name: getattr(emp, c.name) for c in Empresa.__table__.columns}
    d["lote_nome"] = emp.lote.nome
    d["lote_teste"] = emp.lote.is_teste
    return d


def listar_empresas(incluir_teste: bool = True) -> list[dict]:
    with sessao() as s:
        q = select(Empresa).join(Lote)
        if not incluir_teste:
            q = q.where(Lote.is_teste.is_(False))
        return [_empresa_para_dict(e) for e in s.scalars(q.order_by(Empresa.razao_social))]


def obter_empresa(empresa_id: int) -> dict | None:
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        if emp is None:
            return None
        d = _empresa_para_dict(emp)
        d["historico"] = [{"data_hora": h.data_hora, "evento": h.evento, "detalhe": h.detalhe,
                           "usuario": h.usuario} for h in emp.historico]
        d["arquivos"] = [{"id": a.id, "nome_original": a.nome_original, "caminho": a.caminho,
                          "enviado_em": a.enviado_em} for a in emp.arquivos]
        return d


def fila_envio(lote_ids: list[int] | None = None, incluir_falhas: bool = False) -> list[dict]:
    """Empresas aptas ao disparo, na ordem de importação."""
    status = [ST_AGUARDANDO_ENVIO] + ([ST_FALHA_ENVIO] if incluir_falhas else [])
    with sessao() as s:
        q = select(Empresa).where(Empresa.status.in_(status), Empresa.email_valido.is_(True))
        if lote_ids:
            q = q.where(Empresa.lote_id.in_(lote_ids))
        return [_empresa_para_dict(e) for e in s.scalars(q.order_by(Empresa.id))]


# --------------------------------------------------------------------------- #
# Empresas — transições de status
# --------------------------------------------------------------------------- #
def registrar_envio_sucesso(empresa_id: int, assunto: str, corpo_texto: str, prazo_dias: int) -> None:
    agora = _agora()
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        emp.status = ST_NOTIFICADO
        emp.data_envio = agora
        emp.prazo_dias = int(prazo_dias)
        emp.data_limite = calcular_data_limite(agora.date(), prazo_dias)
        emp.assunto_enviado = assunto
        emp.corpo_enviado = corpo_texto
        emp.tentativas_envio += 1
        emp.ultimo_erro = None
        s.add(Envio(empresa_id=emp.id, lote_id=emp.lote_id, destinatario=emp.email, data_hora=agora,
                    data_local=agora.date(), sucesso=True, is_teste=emp.lote.is_teste))
        _registrar(s, emp.id, "E-mail orientativo enviado",
                   f"Destinatário: {emp.email}. Prazo: {prazo_dias} dias. "
                   f"Data limite: {emp.data_limite.strftime('%d/%m/%Y')}.")


def registrar_envio_falha(empresa_id: int, erro: str) -> None:
    agora = _agora()
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        emp.status = ST_FALHA_ENVIO
        emp.tentativas_envio += 1
        emp.ultimo_erro = erro[:2000]
        s.add(Envio(empresa_id=emp.id, lote_id=emp.lote_id, destinatario=emp.email, data_hora=agora,
                    data_local=agora.date(), sucesso=False, is_teste=emp.lote.is_teste, erro=erro[:2000]))
        _registrar(s, emp.id, "Falha no envio do e-mail", erro[:500])


def atualizar_prazos_vencidos() -> int:
    """Move notificações com prazo esgotado para a etapa de investigação. Retorna a quantidade."""
    hoje = hoje_local()
    with sessao() as s:
        vencidas = list(s.scalars(select(Empresa).where(
            Empresa.status == ST_NOTIFICADO, Empresa.data_limite < hoje)))
        for emp in vencidas:
            emp.status = ST_PRAZO_ENCERRADO
            _registrar(s, emp.id, "Prazo encerrado sem regularização",
                       f"Prazo final em {emp.data_limite.strftime('%d/%m/%Y')}. "
                       "Encaminhada para Investigação de Atuação.", "Sistema")
        return len(vencidas)


def marcar_respondeu(empresa_id: int, resumo: str, protocolo: str | None, usuario: str | None) -> None:
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        emp.status = ST_RESPONDEU
        emp.resposta_resumo = resumo
        emp.protocolo = protocolo or None
        emp.data_resposta = _agora()
        _registrar(s, emp.id, "Resposta da empresa registrada",
                   f"Protocolo: {protocolo or '—'}. {resumo}", usuario)


def marcar_regularizada(empresa_id: int, numero_registro: str, observacao: str | None,
                        usuario: str | None) -> None:
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        emp.status = ST_REGULARIZADA
        emp.numero_registro = numero_registro
        emp.data_regularizacao = _agora()
        _registrar(s, emp.id, "Regularização (registro efetivado)",
                   f"Registro Crea-MS nº {numero_registro}. {observacao or ''}".strip(), usuario)


def alterar_status(empresa_id: int, novo_status: str, motivo: str, usuario: str | None) -> None:
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        anterior = emp.status
        emp.status = novo_status
        _registrar(s, emp.id, "Alteração manual de status",
                   f"{anterior} → {novo_status}. Motivo: {motivo}", usuario)


def atualizar_email(empresa_id: int, novo_email: str, valido: bool, usuario: str | None) -> None:
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        antigo = emp.email
        emp.email = novo_email
        emp.email_valido = valido
        if valido and emp.status in (ST_EMAIL_INVALIDO, ST_FALHA_ENVIO):
            emp.status = ST_AGUARDANDO_ENVIO
        _registrar(s, emp.id, "E-mail de contato alterado", f"{antigo or '—'} → {novo_email}", usuario)


def registrar_investigacao(empresa_id: int, indicios: bool, texto: str, usuario: str | None) -> str:
    novo = ST_ATUACAO_CONFIRMADA if indicios else ST_VISITA_IN_LOCO
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        emp.indicios_internet = indicios
        emp.evidencias_texto = texto
        emp.data_investigacao = _agora()
        emp.responsavel_investigacao = usuario
        emp.status = novo
        if indicios:
            detalhe = "Localizados indícios de atuação na internet. " + (texto or "")
        else:
            detalhe = ("Não foram localizados indícios de atuação na internet. "
                       "NECESSÁRIA VISITA IN-LOCO PARA CONSTATAÇÃO DE ATUAÇÃO. " + (texto or ""))
        _registrar(s, emp.id, "Diligência de investigação na internet (OSINT)", detalhe.strip(), usuario)
    return novo


def adicionar_evidencia(empresa_id: int, nome_original: str, conteudo: bytes) -> str:
    with sessao() as s:
        emp = s.get(Empresa, empresa_id)
        pasta = EVIDENCIAS_DIR / emp.cnpj_limpo
        pasta.mkdir(parents=True, exist_ok=True)
        nome_seguro = "".join(c if c.isalnum() or c in "._-" else "_" for c in nome_original)
        destino = pasta / f"{_agora().strftime('%Y%m%d_%H%M%S')}_{nome_seguro}"
        destino.write_bytes(conteudo)
        s.add(EvidenciaArquivo(empresa_id=emp.id, nome_original=nome_original,
                               caminho=str(destino.relative_to(BASE_DIR))))
        _registrar(s, emp.id, "Evidência anexada", nome_original)
        return str(destino)


def adicionar_observacao(empresa_id: int, texto: str, usuario: str | None) -> None:
    with sessao() as s:
        _registrar(s, empresa_id, "Anotação", texto, usuario)


# --------------------------------------------------------------------------- #
# Aquecimento gradual (ramp-up)
# --------------------------------------------------------------------------- #
def dias_com_envio_anteriores(ate: date | None = None) -> int:
    """Quantidade de dias distintos (antes de `ate`) com pelo menos um envio oficial com sucesso."""
    ate = ate or hoje_local()
    with sessao() as s:
        return s.scalar(select(func.count(func.distinct(Envio.data_local))).where(
            Envio.sucesso.is_(True), Envio.is_teste.is_(False), Envio.data_local < ate)) or 0


def enviados_no_dia(dia: date | None = None, incluir_teste: bool = False) -> int:
    dia = dia or hoje_local()
    with sessao() as s:
        q = select(func.count(Envio.id)).where(Envio.sucesso.is_(True), Envio.data_local == dia)
        if not incluir_teste:
            q = q.where(Envio.is_teste.is_(False))
        return s.scalar(q) or 0


def calcular_cota_hoje(cfg: dict | None = None) -> dict:
    """
    Cota diária = min(inicial + incremento × dias_anteriores_com_envio, teto).
    Dias sem disparo não contam (o aquecimento só avança quando há envio efetivo).
    Envios de lotes de teste não contam nem consomem a cota.
    """
    cfg = cfg or obter_todas_config()
    dias = dias_com_envio_anteriores()
    enviados = enviados_no_dia()
    if cfg.get("aquecimento_ativo", True):
        meta = min(int(cfg["aquecimento_inicial"]) + int(cfg["aquecimento_incremento"]) * dias,
                   int(cfg["aquecimento_teto"]))
    else:
        meta = int(cfg["aquecimento_teto"])
    return {"meta": meta, "enviados": enviados, "restantes": max(meta - enviados, 0),
            "dia_aquecimento": dias + 1}


def estatisticas_envio(dias: int = 30) -> list[dict]:
    inicio = hoje_local() - timedelta(days=dias)
    with sessao() as s:
        linhas = s.execute(
            select(Envio.data_local, Envio.sucesso, func.count(Envio.id))
            .where(Envio.data_local >= inicio, Envio.is_teste.is_(False))
            .group_by(Envio.data_local, Envio.sucesso).order_by(Envio.data_local)
        ).all()
    return [{"data": d, "sucesso": ok, "quantidade": q} for d, ok, q in linhas]
