"""
SCRIPT 2 — Coleta via API PÚBLICA (camada de coleta).

Fontes (ambas gratuitas e sem chave de acesso):
  * Principal: Frankfurter API — taxas de referência do Banco Central Europeu.
  * Reserva:   ExchangeRate-API (open.er-api.com) — usada se a principal falhar.

Responsabilidade ÚNICA desta camada: chamar a API, validar que a resposta tem
o formato esperado e devolver os dados BRUTOS. A padronização para o formato
final (o mesmo do scraping) é feita pela camada de formatação.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

import requests

import config
from coleta.http_client import ClienteHttp
from dominio.cotacao import (
    ColetorCotacoes,
    DadosVazios,
    ErroColeta,
    EstruturaInesperada,
    ResultadoColeta,
)

logger = logging.getLogger(__name__)


class ClienteApiCambio(ColetorCotacoes):
    """Adaptador (Hexagonal) que implementa a porta `ColetorCotacoes` via API.

    Tenta os provedores em ordem; o primeiro que responder com dados válidos
    vence. Assim, a indisponibilidade de uma API não interrompe a coleta.
    """

    def __init__(self, cliente_http: ClienteHttp | None = None, usar_reserva: bool = True) -> None:
        self._http = cliente_http or ClienteHttp()
        self._provedores: list[tuple[str, Callable[[str], ResultadoColeta]]] = [
            (config.API_FRANKFURTER_FONTE, self._coletar_frankfurter),
        ]
        if usar_reserva:
            self._provedores.append((config.API_RESERVA_FONTE, self._coletar_reserva))

    # ------------------------------------------------------------------ #
    def coletar(self, moeda_base: str) -> ResultadoColeta:
        base = moeda_base.upper()
        falhas: list[str] = []

        for nome, coletar_no_provedor in self._provedores:
            try:
                logger.info("Consultando %s (base %s)...", nome, base)
                resultado = coletar_no_provedor(base)
                logger.info("%d cotações recebidas de %s.", len(resultado.registros), nome)
                return resultado
            except ErroColeta as erro:
                # Falha em um provedor não é fatal enquanto houver outro para tentar.
                logger.warning("Provedor %s falhou: %s", nome, erro)
                falhas.append(f"{nome}: {erro}")

        raise ErroColeta("Todos os provedores de API falharam -> " + " | ".join(falhas))

    # ------------------------------------------------------------------ #
    # Provedor principal: Frankfurter
    # ------------------------------------------------------------------ #
    def _coletar_frankfurter(self, base: str) -> ResultadoColeta:
        dados = self._get_json(config.API_FRANKFURTER_COTACOES.format(base=base))
        self._validar_campos(dados, {"base": str, "date": str, "rates": dict})

        nomes = self._buscar_nomes_frankfurter()
        registros = self._registros_de_taxas(dados["rates"], base, nomes)

        return ResultadoColeta(
            fonte=config.API_FRANKFURTER_FONTE,
            moeda_base=dados["base"],
            registros=registros,
            coletado_em=datetime.now(timezone.utc),
            metadados={"data_referencia": dados["date"]},
        )

    def _buscar_nomes_frankfurter(self) -> dict[str, str]:
        """Nomes das moedas (ex.: BRL -> Brazilian Real).

        É um dado complementar: se falhar, a coleta continua sem os nomes.
        """
        try:
            nomes = self._get_json(config.API_FRANKFURTER_MOEDAS)
            return {k: v for k, v in nomes.items() if isinstance(v, str)}
        except ErroColeta as erro:
            logger.warning("Não foi possível obter nomes das moedas (%s).", erro)
            return {}

    # ------------------------------------------------------------------ #
    # Provedor reserva: ExchangeRate-API
    # ------------------------------------------------------------------ #
    def _coletar_reserva(self, base: str) -> ResultadoColeta:
        dados = self._get_json(config.API_RESERVA_COTACOES.format(base=base))

        # Esta API sinaliza erro no corpo (HTTP 200 com result="error").
        if dados.get("result") != "success":
            raise ErroColeta(f"API reserva retornou erro: {dados.get('error-type', 'desconhecido')}")
        self._validar_campos(
            dados, {"base_code": str, "time_last_update_unix": int, "rates": dict}
        )

        data_ref = datetime.fromtimestamp(dados["time_last_update_unix"], tz=timezone.utc)
        registros = self._registros_de_taxas(dados["rates"], base, nomes={})

        return ResultadoColeta(
            fonte=config.API_RESERVA_FONTE,
            moeda_base=dados["base_code"],
            registros=registros,
            coletado_em=datetime.now(timezone.utc),
            metadados={"data_referencia": data_ref.date().isoformat()},
        )

    # ------------------------------------------------------------------ #
    # Auxiliares
    # ------------------------------------------------------------------ #
    def _get_json(self, url: str) -> dict[str, Any]:
        """GET resiliente + decodificação segura do JSON."""
        resposta = self._http.get(url, cabecalhos_extras={"Accept": "application/json"})
        try:
            dados = resposta.json()
        except (ValueError, requests.JSONDecodeError) as erro:
            raise EstruturaInesperada(f"Resposta não é um JSON válido ({url}).") from erro
        if not isinstance(dados, dict):
            raise EstruturaInesperada(f"JSON inesperado: esperava um objeto em {url}.")
        return dados

    @staticmethod
    def _validar_campos(dados: dict[str, Any], esperado: dict[str, type]) -> None:
        """Garante que o contrato da API não mudou antes de usar os dados."""
        for campo, tipo in esperado.items():
            if not isinstance(dados.get(campo), tipo):
                raise EstruturaInesperada(
                    f"Campo '{campo}' ausente ou com tipo inválido na resposta da API."
                )

    @staticmethod
    def _registros_de_taxas(
        taxas: dict[str, Any], base: str, nomes: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Converte o dicionário {código: taxa} em uma lista de registros brutos."""
        registros = [
            {"codigo": codigo, "nome": nomes.get(codigo, ""), "taxa": taxa}
            for codigo, taxa in taxas.items()
            if codigo != base  # a própria base (taxa 1.0) não é informação útil
        ]
        if not registros:
            raise DadosVazios("A API não retornou nenhuma cotação.")
        return registros
