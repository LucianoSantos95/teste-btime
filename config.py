"""
Configurações centralizadas do projeto.

Manter URLs, tempos e caminhos em um único lugar evita "números mágicos"
espalhados pelo código e facilita ajustes sem mexer na lógica.
Os valores podem ser sobrescritos por variáveis de ambiente.
"""

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Caminhos
# --------------------------------------------------------------------------- #
RAIZ_PROJETO = Path(__file__).resolve().parent
PASTA_SAIDA = Path(os.getenv("PASTA_SAIDA", RAIZ_PROJETO / "saida"))

ARQUIVO_SCRAPING = PASTA_SAIDA / "dados_scraping.csv"
ARQUIVO_API = PASTA_SAIDA / "dados_api.csv"

# --------------------------------------------------------------------------- #
# Parâmetros gerais
# --------------------------------------------------------------------------- #
MOEDA_BASE_PADRAO = os.getenv("MOEDA_BASE", "USD")

# Tempo máximo (s) de espera por resposta: (conexão, leitura)
TIMEOUT = (5, 20)

# Tentativas automáticas para erros transitórios (429, 5xx, quedas de rede)
MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "4"))

# Fator do backoff exponencial: espera ≈ fator * 2^(tentativa-1) segundos
FATOR_BACKOFF = float(os.getenv("FATOR_BACKOFF", "1.5"))

# Status HTTP considerados transitórios (vale a pena tentar de novo)
STATUS_RETENTAVEIS = (429, 500, 502, 503, 504)

# --------------------------------------------------------------------------- #
# Script 1 — Web Scraping (x-rates.com)
# --------------------------------------------------------------------------- #
SCRAPING_URL_BASE = "https://www.x-rates.com"
SCRAPING_URL_TABELA = SCRAPING_URL_BASE + "/table/?from={base}&amount=1"
SCRAPING_FONTE = "x-rates.com (web scraping)"

# Intervalo aleatório (s) antes de cada requisição — "educação" com o servidor
# e redução da chance de bloqueio por padrão de acesso robótico.
SCRAPING_ATRASO_MIN = 1.0
SCRAPING_ATRASO_MAX = 3.0

# User-Agents de navegadores reais, rotacionados a cada tentativa.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 "
    "Firefox/130.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
]

# Trechos que indicam página de bloqueio/desafio anti-bot no lugar do conteúdo.
MARCADORES_BLOQUEIO = (
    "captcha",
    "cf-challenge",
    "challenge-platform",
    "access denied",
    "are you a robot",
    "unusual traffic",
)

# --------------------------------------------------------------------------- #
# Script 2 — API pública
# --------------------------------------------------------------------------- #
# API principal: Frankfurter (dados oficiais do Banco Central Europeu, sem chave)
API_FRANKFURTER_COTACOES = "https://api.frankfurter.dev/v1/latest?base={base}"
API_FRANKFURTER_MOEDAS = "https://api.frankfurter.dev/v1/currencies"
API_FRANKFURTER_FONTE = "Frankfurter API (Banco Central Europeu)"

# API reserva: ExchangeRate-API (endpoint aberto, sem chave)
API_RESERVA_COTACOES = "https://open.er-api.com/v6/latest/{base}"
API_RESERVA_FONTE = "ExchangeRate-API (open.er-api.com)"
