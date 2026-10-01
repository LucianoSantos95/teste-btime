"""
SCRIPT 1 — Coleta via WEB SCRAPING (camada de coleta).

Fonte: tabela de câmbio do x-rates.com (https://www.x-rates.com/table/).

Responsabilidade ÚNICA desta camada: buscar a página e extrair as linhas da
tabela como dados BRUTOS (strings exatamente como aparecem no HTML).
Conversão de tipos, cálculo e padronização ficam na camada de formatação.

Estratégia contra bloqueios e restrições:
  1. Consulta o robots.txt antes de acessar a página (scraping ético).
  2. Usa `requests` + BeautifulSoup (rápido e leve) através do `ClienteHttp`,
     que aplica retentativas com backoff, rotação de User-Agent, atrasos
     aleatórios e respeito ao Retry-After.
  3. Detecta páginas de bloqueio "disfarçadas" (HTTP 200 com captcha/desafio).
  4. Se for bloqueado ou a tabela não vier no HTML (ex.: conteúdo passou a ser
     renderizado por JavaScript), recorre ao Selenium com Chrome headless,
     que se comporta como um navegador real.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

import config
from coleta.http_client import ClienteHttp
from dominio.cotacao import (
    BloqueioDetectado,
    ColetorCotacoes,
    DadosVazios,
    ErroColeta,
    EstruturaInesperada,
    ResultadoColeta,
)

logger = logging.getLogger(__name__)

# "auto": tenta requests e cai para Selenium se necessário
# "nunca": só requests | "sempre": só Selenium
ModoSelenium = Literal["auto", "nunca", "sempre"]

# Seletor CSS da tabela completa (ordem alfabética). A página também tem uma
# tabela "Top 10" com a mesma classe `ratesTable`, que serve de plano B.
SELETOR_TABELA_COMPLETA = "table.tablesorter.ratesTable"
SELETOR_TABELA_QUALQUER = "table.ratesTable"


class ScraperXRates(ColetorCotacoes):
    """Adaptador (Hexagonal) que implementa a porta `ColetorCotacoes` via scraping."""

    def __init__(
        self,
        cliente_http: ClienteHttp | None = None,
        modo_selenium: ModoSelenium = "auto",
        verificar_robots: bool = True,
    ) -> None:
        self._http = cliente_http or ClienteHttp(
            atraso=(config.SCRAPING_ATRASO_MIN, config.SCRAPING_ATRASO_MAX)
        )
        self._modo_selenium = modo_selenium
        self._verificar_robots = verificar_robots

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def coletar(self, moeda_base: str) -> ResultadoColeta:
        url = config.SCRAPING_URL_TABELA.format(base=moeda_base.upper())
        logger.info("Iniciando scraping de %s", url)

        if self._verificar_robots:
            self._garantir_permissao_robots(url)

        registros, metodo, timestamp_site = self._obter_registros(url)

        if not registros:
            raise DadosVazios("Nenhuma cotação válida foi extraída da página.")

        logger.info("%d cotações extraídas via %s.", len(registros), metodo)
        return ResultadoColeta(
            fonte=config.SCRAPING_FONTE,
            moeda_base=moeda_base.upper(),
            registros=registros,
            coletado_em=datetime.now(timezone.utc),
            metadados={"url": url, "metodo": metodo, "timestamp_site": timestamp_site},
        )

    # ------------------------------------------------------------------ #
    # Fluxo de obtenção (requests -> fallback Selenium)
    # ------------------------------------------------------------------ #
    def _obter_registros(self, url: str) -> tuple[list[dict[str, Any]], str, str | None]:
        if self._modo_selenium == "sempre":
            html = self._baixar_com_selenium(url)
            return self.extrair_registros(html), "selenium", self.extrair_timestamp(html)

        try:
            html = self._baixar_com_requests(url)
            return self.extrair_registros(html), "requests", self.extrair_timestamp(html)
        except (BloqueioDetectado, EstruturaInesperada) as erro:
            if self._modo_selenium == "nunca":
                raise
            logger.warning("Coleta via requests falhou (%s). Tentando com Selenium...", erro)
            html = self._baixar_com_selenium(url)
            return self.extrair_registros(html), "selenium", self.extrair_timestamp(html)

    def _baixar_com_requests(self, url: str) -> str:
        resposta = self._http.get(url)
        html = resposta.text
        self._checar_pagina_de_bloqueio(html)
        return html

    def _baixar_com_selenium(self, url: str) -> str:
        """Abre a página em um Chrome headless e devolve o HTML renderizado.

        O import é feito aqui dentro para que o Selenium seja uma dependência
        opcional: o scraper funciona sem ele enquanto não houver bloqueio.
        """
        try:
            from selenium import webdriver
            from selenium.common.exceptions import TimeoutException, WebDriverException
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as ec
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as erro:
            raise ErroColeta(
                "Fallback com Selenium indisponível: instale com `pip install selenium`."
            ) from erro

        opcoes = webdriver.ChromeOptions()
        opcoes.add_argument("--headless=new")
        opcoes.add_argument("--no-sandbox")
        opcoes.add_argument("--disable-dev-shm-usage")
        opcoes.add_argument("--window-size=1366,900")
        # Reduz sinais óbvios de automação que alguns sites usam para bloquear.
        opcoes.add_argument("--disable-blink-features=AutomationControlled")
        opcoes.add_experimental_option("excludeSwitches", ["enable-automation"])
        opcoes.add_argument(f"user-agent={config.USER_AGENTS[0]}")

        driver = None
        try:
            # Selenium 4.6+ baixa o ChromeDriver compatível automaticamente.
            driver = webdriver.Chrome(options=opcoes)
            driver.set_page_load_timeout(config.TIMEOUT[1] * 2)
            driver.get(url)
            WebDriverWait(driver, config.TIMEOUT[1]).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, SELETOR_TABELA_QUALQUER))
            )
            html = driver.page_source
        except TimeoutException as erro:
            raise EstruturaInesperada(
                "Selenium não encontrou a tabela de cotações dentro do tempo limite."
            ) from erro
        except WebDriverException as erro:
            raise ErroColeta(f"Falha ao executar o Chrome via Selenium: {erro.msg}") from erro
        finally:
            if driver is not None:
                driver.quit()

        self._checar_pagina_de_bloqueio(html)
        return html

    # ------------------------------------------------------------------ #
    # Parsing do HTML (métodos estáticos = fáceis de testar sem rede)
    # ------------------------------------------------------------------ #
    @staticmethod
    def extrair_registros(html: str) -> list[dict[str, Any]]:
        """Extrai as linhas da tabela de câmbio como dicionários de strings.

        Cada linha do x-rates tem 3 colunas:
            <td>Brazilian Real</td>
            <td class='rtRates'><a href='...?from=USD&to=BRL'>5.174922</a></td>
            <td class='rtRates'><a href='...?from=BRL&to=USD'>0.193240</a></td>
        O código ISO da moeda não aparece no texto, então é lido do link.

        Raises:
            EstruturaInesperada: se nenhuma tabela de cotações for encontrada.
        """
        sopa = BeautifulSoup(html, "html.parser")
        tabela = sopa.select_one(SELETOR_TABELA_COMPLETA) or sopa.select_one(
            SELETOR_TABELA_QUALQUER
        )
        if tabela is None:
            raise EstruturaInesperada(
                "Tabela de cotações não encontrada — o layout do site pode ter mudado."
            )

        registros: list[dict[str, Any]] = []
        linhas = tabela.select("tbody tr") or tabela.select("tr")

        for numero, linha in enumerate(linhas, start=1):
            colunas = linha.find_all("td")
            if len(colunas) < 3:
                continue  # cabeçalho ou linha decorativa

            link = colunas[1].find("a")
            codigo = ScraperXRates._codigo_da_url(link.get("href", "") if link else "")
            if not codigo:
                # Linha fora do padrão: registra e segue, sem derrubar a coleta inteira.
                logger.warning("Linha %d ignorada: código da moeda não identificado.", numero)
                continue

            registros.append(
                {
                    "nome": colunas[0].get_text(strip=True),
                    "codigo": codigo,
                    "taxa": colunas[1].get_text(strip=True),
                    "taxa_inversa": colunas[2].get_text(strip=True),
                }
            )

        return registros

    @staticmethod
    def extrair_timestamp(html: str) -> str | None:
        """Lê o carimbo de data exibido pelo site (apenas informativo)."""
        elemento = BeautifulSoup(html, "html.parser").select_one(".ratesTimestamp")
        return elemento.get_text(strip=True) if elemento else None

    @staticmethod
    def _codigo_da_url(href: str) -> str | None:
        """Extrai o parâmetro `to` (código ISO) de um link do x-rates."""
        valores = parse_qs(urlparse(href).query).get("to")
        if valores and len(valores[0]) == 3 and valores[0].isalpha():
            return valores[0].upper()
        return None

    # ------------------------------------------------------------------ #
    # Proteções
    # ------------------------------------------------------------------ #
    @staticmethod
    def _checar_pagina_de_bloqueio(html: str) -> None:
        """Alguns anti-bots respondem HTTP 200 com uma página de desafio."""
        trecho = html[:20000].lower()
        for marcador in config.MARCADORES_BLOQUEIO:
            if marcador in trecho:
                raise BloqueioDetectado(f"Página de bloqueio detectada (marcador: '{marcador}').")

    def _garantir_permissao_robots(self, url: str) -> None:
        """Respeita o robots.txt. Se ele não puder ser lido, segue a convenção
        de considerar o acesso permitido (e registra o aviso no log)."""
        url_robots = urljoin(config.SCRAPING_URL_BASE, "/robots.txt")
        leitor = RobotFileParser()
        try:
            leitor.parse(self._http.get(url_robots).text.splitlines())
        except ErroColeta as erro:
            logger.warning("Não foi possível ler o robots.txt (%s). Prosseguindo.", erro)
            return

        if not leitor.can_fetch("*", url):
            raise ErroColeta(f"O robots.txt do site não permite acessar {url}.")
        logger.debug("robots.txt permite o acesso a %s", url)
