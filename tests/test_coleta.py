"""Testes da camada de coleta (scraper, cliente de API e cliente HTTP)."""

import pytest
import requests

from coleta.api_client import ClienteApiCambio
from coleta.http_client import ClienteHttp
from coleta.scraper import ScraperXRates
from dominio.cotacao import BloqueioDetectado, ErroColeta, EstruturaInesperada
from tests.conftest import RespostaFalsa, SessaoFalsa


def cliente(respostas, tentativas=3):
    """ClienteHttp com sessão falsa e sem esperas reais."""
    return ClienteHttp(sessao=SessaoFalsa(respostas), max_tentativas=tentativas, dormir=lambda s: None)


# --------------------------------------------------------------------------- #
# ClienteHttp
# --------------------------------------------------------------------------- #
def test_http_tenta_novamente_apos_erro_transitorio():
    http = cliente({"site": [RespostaFalsa(503), requests.ConnectionError(), RespostaFalsa(200, "ok")]})
    assert http.get("https://site/x").text == "ok"


def test_http_rotaciona_user_agent_e_vira_bloqueio_apos_403s():
    sessao = SessaoFalsa({"site": RespostaFalsa(403)})
    http = ClienteHttp(sessao=sessao, max_tentativas=3, dormir=lambda s: None)
    with pytest.raises(BloqueioDetectado):
        http.get("https://site/x")
    assert len(sessao.chamadas) == 3
    assert all("User-Agent" in cabecalhos for _, cabecalhos in sessao.chamadas)


def test_http_respeita_retry_after():
    esperas = []
    sessao = SessaoFalsa({"site": [RespostaFalsa(429, headers={"Retry-After": "7"}), RespostaFalsa(200)]})
    ClienteHttp(sessao=sessao, max_tentativas=2, dormir=esperas.append).get("https://site/x")
    assert esperas == [7.0]


def test_http_404_nao_e_retentado():
    sessao = SessaoFalsa({})
    with pytest.raises(ErroColeta):
        ClienteHttp(sessao=sessao, max_tentativas=3, dormir=lambda s: None).get("https://site/x")
    assert len(sessao.chamadas) == 1


# --------------------------------------------------------------------------- #
# Scraper
# --------------------------------------------------------------------------- #
def test_scraper_extrai_tabela_completa(html_xrates):
    registros = ScraperXRates.extrair_registros(html_xrates)
    # Usa a tabela completa (3 válidas) e ignora a linha sem link.
    assert [r["codigo"] for r in registros] == ["ARS", "BRL", "EUR"]
    assert registros[1] == {
        "nome": "Brazilian Real", "codigo": "BRL", "taxa": "5.174922", "taxa_inversa": "0.193240",
    }


def test_scraper_falha_claramente_se_layout_mudar():
    with pytest.raises(EstruturaInesperada):
        ScraperXRates.extrair_registros("<html><body>layout novo</body></html>")


def test_scraper_coleta_completa_com_robots(html_xrates):
    http = cliente({
        "robots.txt": RespostaFalsa(200, "User-agent: *\nDisallow: /auth/"),
        "/table/": RespostaFalsa(200, html_xrates),
    })
    resultado = ScraperXRates(cliente_http=http, modo_selenium="nunca").coletar("usd")
    assert resultado.moeda_base == "USD"
    assert resultado.metadados["metodo"] == "requests"
    assert len(resultado.registros) == 3


def test_scraper_respeita_robots_txt_proibitivo(html_xrates):
    http = cliente({
        "robots.txt": RespostaFalsa(200, "User-agent: *\nDisallow: /"),
        "/table/": RespostaFalsa(200, html_xrates),
    })
    with pytest.raises(ErroColeta, match="robots.txt"):
        ScraperXRates(cliente_http=http, modo_selenium="nunca").coletar("USD")


def test_scraper_detecta_captcha_com_status_200():
    http = cliente({"/table/": RespostaFalsa(200, "<html>Please solve the CAPTCHA</html>")})
    scraper = ScraperXRates(cliente_http=http, modo_selenium="nunca", verificar_robots=False)
    with pytest.raises(BloqueioDetectado):
        scraper.coletar("USD")


def test_scraper_cai_para_selenium_quando_bloqueado(html_xrates, monkeypatch):
    http = cliente({"/table/": RespostaFalsa(403)})
    scraper = ScraperXRates(cliente_http=http, modo_selenium="auto", verificar_robots=False)
    monkeypatch.setattr(scraper, "_baixar_com_selenium", lambda url: html_xrates)
    resultado = scraper.coletar("USD")
    assert resultado.metadados["metodo"] == "selenium"


# --------------------------------------------------------------------------- #
# Cliente de API
# --------------------------------------------------------------------------- #
FRANKFURTER_OK = {"amount": 1.0, "base": "USD", "date": "2026-09-30", "rates": {"BRL": 5.2027, "EUR": 0.88067}}
MOEDAS_OK = {"BRL": "Brazilian Real", "EUR": "Euro", "USD": "United States Dollar"}
RESERVA_OK = {
    "result": "success", "base_code": "USD", "time_last_update_unix": 1790812951,
    "rates": {"USD": 1, "BRL": 5.21, "EUR": 0.881},
}


def test_api_principal():
    http = cliente({"currencies": RespostaFalsa(json_data=MOEDAS_OK), "latest": RespostaFalsa(json_data=FRANKFURTER_OK)})
    resultado = ClienteApiCambio(cliente_http=http).coletar("USD")
    assert "Frankfurter" in resultado.fonte
    assert resultado.metadados["data_referencia"] == "2026-09-30"
    assert {"codigo": "BRL", "nome": "Brazilian Real", "taxa": 5.2027} in resultado.registros


def test_api_usa_reserva_quando_principal_cai():
    http = cliente({
        "frankfurter": RespostaFalsa(500),
        "er-api": RespostaFalsa(json_data=RESERVA_OK),
    })
    resultado = ClienteApiCambio(cliente_http=http).coletar("USD")
    assert "ExchangeRate-API" in resultado.fonte
    assert [r["codigo"] for r in resultado.registros] == ["BRL", "EUR"]  # base removida


def test_api_rejeita_contrato_alterado():
    http = cliente({"currencies": RespostaFalsa(json_data={}), "latest": RespostaFalsa(json_data={"taxas": {}})})
    with pytest.raises(ErroColeta, match="Campo 'base' ausente"):
        ClienteApiCambio(cliente_http=http, usar_reserva=False).coletar("USD")


def test_api_erro_quando_todos_provedores_falham():
    http = cliente({"frankfurter": RespostaFalsa(503), "er-api": RespostaFalsa(json_data={"result": "error"})})
    with pytest.raises(ErroColeta, match="Todos os provedores"):
        ClienteApiCambio(cliente_http=http).coletar("USD")
