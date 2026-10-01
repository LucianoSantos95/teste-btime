"""
Cliente HTTP resiliente, compartilhado pelo scraper e pelo cliente de API.

Concentra aqui as estratégias contra falhas e bloqueios comuns:
  * tentativas automáticas com backoff exponencial + jitter (aleatoriedade);
  * respeito ao cabeçalho `Retry-After` enviado em respostas 429/503;
  * rotação de User-Agent a cada tentativa (evita assinatura fixa de robô);
  * atraso aleatório antes de cada requisição (acesso "educado");
  * timeouts explícitos (nunca fica pendurado esperando o servidor);
  * tradução de erros HTTP em exceções de domínio claras.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, Sequence

import requests

import config
from dominio.cotacao import BloqueioDetectado, ErroColeta

logger = logging.getLogger(__name__)


class ClienteHttp:
    """Wrapper de `requests.Session` com política de retentativas."""

    def __init__(
        self,
        user_agents: Sequence[str] | None = None,
        max_tentativas: int = config.MAX_TENTATIVAS,
        fator_backoff: float = config.FATOR_BACKOFF,
        timeout: tuple[float, float] = config.TIMEOUT,
        atraso: tuple[float, float] = (0.0, 0.0),
        sessao: requests.Session | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._user_agents = list(user_agents or config.USER_AGENTS)
        self._max_tentativas = max(1, max_tentativas)
        self._fator_backoff = fator_backoff
        self._timeout = timeout
        self._atraso = atraso
        self._sessao = sessao or requests.Session()
        # `dormir` é injetável para que os testes não precisem esperar de verdade.
        self._dormir = dormir

    # ------------------------------------------------------------------ #
    def get(self, url: str, cabecalhos_extras: dict[str, str] | None = None) -> requests.Response:
        """Faz um GET aplicando a política de resiliência.

        Raises:
            BloqueioDetectado: 403 ou 429 persistentes após todas as tentativas.
            ErroColeta: erro de rede, 5xx persistente ou 4xx não recuperável.
        """
        ultimo_erro: str = ""

        for tentativa in range(1, self._max_tentativas + 1):
            self._aguardar_atraso_educado()
            cabecalhos = self._montar_cabecalhos(cabecalhos_extras)

            try:
                logger.debug("GET %s (tentativa %d/%d)", url, tentativa, self._max_tentativas)
                resposta = self._sessao.get(url, headers=cabecalhos, timeout=self._timeout)
            except (requests.ConnectionError, requests.Timeout) as erro:
                # Falha de rede é transitória por natureza: vale tentar de novo.
                ultimo_erro = f"falha de rede: {erro.__class__.__name__}"
                logger.warning("Tentativa %d falhou (%s).", tentativa, ultimo_erro)
                if tentativa < self._max_tentativas:
                    self._esperar_backoff(tentativa)
                continue

            status = resposta.status_code
            if status < 400:
                return resposta

            # 403 pode ser bloqueio por User-Agent: tentamos de novo com outro UA.
            if status == 403 or status in config.STATUS_RETENTAVEIS:
                ultimo_erro = f"HTTP {status}"
                logger.warning("Tentativa %d recebeu %s.", tentativa, ultimo_erro)
                if tentativa < self._max_tentativas:
                    self._esperar_backoff(tentativa, resposta.headers.get("Retry-After"))
                continue

            # Demais 4xx (404, 400...) indicam erro na requisição: insistir não ajuda.
            raise ErroColeta(f"Requisição rejeitada: HTTP {status} em {url}")

        # Esgotadas as tentativas: decide qual exceção representa melhor a falha.
        if ultimo_erro in ("HTTP 403", "HTTP 429"):
            raise BloqueioDetectado(
                f"Acesso bloqueado após {self._max_tentativas} tentativas ({ultimo_erro}) em {url}"
            )
        raise ErroColeta(
            f"Falha após {self._max_tentativas} tentativas ({ultimo_erro}) em {url}"
        )

    # ------------------------------------------------------------------ #
    def fechar(self) -> None:
        """Libera as conexões abertas da sessão."""
        self._sessao.close()

    def __enter__(self) -> "ClienteHttp":
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    # ------------------------------------------------------------------ #
    # Auxiliares privados
    # ------------------------------------------------------------------ #
    def _montar_cabecalhos(self, extras: dict[str, str] | None) -> dict[str, str]:
        """Cabeçalhos parecidos com os de um navegador real, com UA sorteado."""
        cabecalhos = {
            "User-Agent": random.choice(self._user_agents),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
            "Connection": "keep-alive",
        }
        if extras:
            cabecalhos.update(extras)
        return cabecalhos

    def _aguardar_atraso_educado(self) -> None:
        minimo, maximo = self._atraso
        if maximo > 0:
            self._dormir(random.uniform(minimo, maximo))

    def _esperar_backoff(self, tentativa: int, retry_after: str | None = None) -> None:
        """Espera antes da próxima tentativa.

        Prioriza o `Retry-After` do servidor; senão usa backoff exponencial
        com jitter para não sincronizar novas tentativas com outros clientes.
        """
        if retry_after and retry_after.isdigit():
            espera = float(retry_after)
        else:
            espera = self._fator_backoff * (2 ** (tentativa - 1)) + random.uniform(0, 1)
        logger.info("Aguardando %.1fs antes de tentar novamente...", espera)
        self._dormir(espera)
