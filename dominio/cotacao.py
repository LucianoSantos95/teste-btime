"""
Camada de DOMÍNIO: o "contrato" compartilhado por todo o sistema.

Nada aqui depende de bibliotecas externas (requests, BeautifulSoup, Selenium...).
É o núcleo estável da arquitetura: as camadas de coleta, formatação e
armazenamento dependem do domínio, nunca o contrário (regra de dependência da
Clean Architecture).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


# --------------------------------------------------------------------------- #
# Entidade
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Cotacao:
    """Uma cotação de câmbio já padronizada, independente da origem do dado.

    Exemplo: 1 USD (moeda_base) = 5.20 BRL (moeda_cotada).
    """

    moeda_base: str          # Código ISO 4217 da moeda de origem (ex.: "USD")
    moeda_cotada: str        # Código ISO 4217 da moeda de destino (ex.: "BRL")
    nome_moeda: str          # Nome legível da moeda cotada (ex.: "Brazilian Real")
    taxa: float              # Quanto 1 unidade da base vale na moeda cotada
    taxa_inversa: float      # Quanto 1 unidade da moeda cotada vale na base
    data_referencia: date    # Data a que a cotação se refere
    coletado_em: datetime    # Momento (UTC) em que o dado foi coletado
    fonte: str               # De onde veio o dado (site ou API)


# --------------------------------------------------------------------------- #
# Objeto que transporta o dado BRUTO da camada de coleta para a de formatação
# --------------------------------------------------------------------------- #
@dataclass
class ResultadoColeta:
    """Envelope com os dados brutos retornados por um coletor.

    A camada de coleta NÃO padroniza nada: só devolve o que encontrou na
    origem (strings do HTML, JSON da API) junto com metadados mínimos. Quem
    transforma isso em `Cotacao` é a camada de formatação.
    """

    fonte: str                                  # Identificador da origem
    moeda_base: str                             # Base solicitada na coleta
    registros: list[dict[str, Any]]             # Linhas brutas
    coletado_em: datetime                       # Momento (UTC) da coleta
    metadados: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Porta (interface) da camada de coleta — Arquitetura Hexagonal
# --------------------------------------------------------------------------- #
class ColetorCotacoes(ABC):
    """Porta de entrada de dados: qualquer fonte de cotações implementa isto.

    Os orquestradores (`main_*.py`) dependem desta abstração, então trocar o
    site raspado ou a API usada não exige mudança em formatação/armazenamento.
    """

    @abstractmethod
    def coletar(self, moeda_base: str) -> ResultadoColeta:
        """Busca as cotações brutas tendo `moeda_base` como referência."""


# --------------------------------------------------------------------------- #
# Exceções de domínio — permitem ao orquestrador reagir a cada falha
# --------------------------------------------------------------------------- #
class ErroColeta(Exception):
    """Erro genérico ao obter dados de uma fonte externa."""


class BloqueioDetectado(ErroColeta):
    """A fonte recusou o acesso (403, 429 persistente, captcha, desafio anti-bot)."""


class EstruturaInesperada(ErroColeta):
    """A fonte respondeu, mas o conteúdo não tem o formato esperado
    (ex.: o layout do site mudou ou a API alterou o contrato)."""


class DadosVazios(ErroColeta):
    """A coleta terminou sem nenhum registro válido."""
