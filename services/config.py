"""
Carrega a configuração antes de qualquer conexão:

  1. `.env` local (desenvolvimento / servidor interno)
  2. Secrets do Streamlit (`.streamlit/secrets.toml` ou painel do Streamlit Cloud)

Chaves de nível raiz dos Secrets são copiadas para as variáveis de ambiente, sem
sobrescrever valores já definidos. Assim o restante do sistema lê tudo via os.getenv.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv


def carregar_configuracao() -> None:
    load_dotenv()
    try:
        import streamlit as st

        for chave, valor in st.secrets.items():
            if isinstance(valor, (str, int, float, bool)) and chave not in os.environ:
                os.environ[chave] = str(valor)
    except Exception:  # noqa: BLE001 - sem secrets.toml é um cenário válido
        pass
