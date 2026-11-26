"""
Armazenamento das evidências (prints e comprovantes) da investigação.

Dois backends com a mesma interface:
  * LocalStorage    → pasta `evidencias/` (uso local / servidor interno)
  * SupabaseStorage → bucket PRIVADO do Supabase Storage (uso em nuvem, ex.: Streamlit Cloud,
                      cujo disco é apagado a cada reinício)

O Supabase é usado automaticamente quando SUPABASE_URL e SUPABASE_SERVICE_KEY estão definidos
(variáveis de ambiente ou Secrets do Streamlit). As chaves de arquivo têm o formato
"{cnpj_limpo}/{AAAAMMDD_HHMMSS}_{nome}".
"""
from __future__ import annotations

import mimetypes
import os
import shutil
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
EVIDENCIAS_DIR = BASE_DIR / "evidencias"


class ErroArmazenamento(RuntimeError):
    pass


class LocalStorage:
    nome = "Disco local (evidencias/)"

    def __init__(self, raiz: Path = EVIDENCIAS_DIR):
        self.raiz = raiz

    def _caminho(self, chave: str) -> Path:
        # Compatibilidade com registros antigos gravados como "evidencias/..."
        chave = chave.removeprefix("evidencias/")
        destino = (self.raiz / chave).resolve()
        if self.raiz.resolve() not in destino.parents:
            raise ErroArmazenamento("Caminho de evidência inválido.")
        return destino

    def salvar(self, chave: str, conteudo: bytes, content_type: str | None = None) -> None:
        destino = self._caminho(chave)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)

    def ler(self, chave: str) -> bytes | None:
        caminho = self._caminho(chave)
        return caminho.read_bytes() if caminho.exists() else None

    def excluir_prefixo(self, prefixo: str) -> None:
        pasta = self._caminho(prefixo)
        if pasta.is_dir():
            shutil.rmtree(pasta, ignore_errors=True)

    def preparar(self) -> None:
        self.raiz.mkdir(parents=True, exist_ok=True)


class SupabaseStorage:
    """Cliente mínimo da API REST do Supabase Storage (sem dependências extras)."""

    nome = "Supabase Storage"

    def __init__(self, url: str, chave: str, bucket: str = "evidencias", timeout: int = 60):
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.timeout = timeout
        self.sessao = requests.Session()
        self.sessao.headers["apikey"] = chave
        # Chaves legadas (service_role) são JWT e também vão no Authorization.
        # As chaves novas (sb_secret_...) vão apenas no cabeçalho apikey.
        if chave.startswith("eyJ"):
            self.sessao.headers["Authorization"] = f"Bearer {chave}"

    def _url_objeto(self, chave: str) -> str:
        return f"{self.base}/object/{self.bucket}/{quote(chave)}"

    @staticmethod
    def _verificar(resp: requests.Response, acao: str) -> None:
        if resp.status_code >= 400:
            raise ErroArmazenamento(f"Supabase Storage ({acao}) – HTTP {resp.status_code}: {resp.text[:300]}")

    def preparar(self) -> None:
        """Cria o bucket privado, se ainda não existir."""
        resp = self.sessao.get(f"{self.base}/bucket/{self.bucket}", timeout=self.timeout)
        if resp.status_code == 200:
            if resp.json().get("public"):
                raise ErroArmazenamento(f"O bucket '{self.bucket}' está PÚBLICO. Torne-o privado no Supabase.")
            return
        resp = self.sessao.post(f"{self.base}/bucket", json={"id": self.bucket, "name": self.bucket,
                                                             "public": False}, timeout=self.timeout)
        if resp.status_code >= 400 and "already exists" not in resp.text.lower():
            self._verificar(resp, "criar bucket")

    def salvar(self, chave: str, conteudo: bytes, content_type: str | None = None) -> None:
        tipo = content_type or mimetypes.guess_type(chave)[0] or "application/octet-stream"
        resp = self.sessao.post(self._url_objeto(chave), data=conteudo, timeout=self.timeout,
                                headers={"Content-Type": tipo, "x-upsert": "true"})
        self._verificar(resp, "upload")

    def ler(self, chave: str) -> bytes | None:
        resp = self.sessao.get(f"{self.base}/object/authenticated/{self.bucket}/{quote(chave)}",
                               timeout=self.timeout)
        if resp.status_code in (400, 404):
            return None
        self._verificar(resp, "download")
        return resp.content

    def excluir_prefixo(self, prefixo: str) -> None:
        resp = self.sessao.post(f"{self.base}/object/list/{self.bucket}", timeout=self.timeout,
                                json={"prefix": prefixo.rstrip("/") + "/", "limit": 1000, "offset": 0})
        self._verificar(resp, "listar")
        chaves = [f"{prefixo.rstrip('/')}/{o['name']}" for o in resp.json() if o.get("name")]
        if chaves:
            resp = self.sessao.delete(f"{self.base}/object/{self.bucket}", json={"prefixes": chaves},
                                      timeout=self.timeout)
            self._verificar(resp, "excluir")


@lru_cache(maxsize=1)
def obter_storage() -> LocalStorage | SupabaseStorage:
    url = os.getenv("SUPABASE_URL", "").strip()
    chave = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if url and chave:
        return SupabaseStorage(url, chave, os.getenv("SUPABASE_BUCKET", "evidencias").strip() or "evidencias")
    return LocalStorage()
