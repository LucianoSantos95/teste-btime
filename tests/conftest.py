"""Configuração compartilhada dos testes: dublês de HTTP sem acesso à rede."""

import sys
from pathlib import Path

import pytest

# Permite importar os pacotes do projeto (config, coleta, ...) a partir de tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASTA_FIXTURES = Path(__file__).parent / "fixtures"


class RespostaFalsa:
    """Imita o mínimo de `requests.Response` usado pelo projeto."""

    def __init__(self, status_code=200, texto="", json_data=None, headers=None):
        self.status_code = status_code
        self.text = texto
        self._json = json_data
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("sem JSON")
        return self._json


class SessaoFalsa:
    """Devolve respostas pré-programadas por URL (ou em sequência)."""

    def __init__(self, respostas):
        # respostas: dict {trecho_da_url: RespostaFalsa | Exception | list[...]}
        self._respostas = respostas
        self.chamadas = []

    def get(self, url, headers=None, timeout=None):
        self.chamadas.append((url, headers))
        for trecho, resposta in self._respostas.items():
            if trecho in url:
                if isinstance(resposta, list):
                    resposta = resposta.pop(0) if len(resposta) > 1 else resposta[0]
                if isinstance(resposta, Exception):
                    raise resposta
                return resposta
        return RespostaFalsa(status_code=404)

    def close(self):
        pass


@pytest.fixture
def html_xrates():
    return (PASTA_FIXTURES / "xrates_tabela.html").read_text(encoding="utf-8")
