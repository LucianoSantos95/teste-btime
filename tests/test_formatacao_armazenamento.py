"""Testes das camadas de formatação e armazenamento (e do fluxo completo)."""

import csv
from datetime import date, datetime, timezone

import pytest

from armazenamento.csv_writer import salvar_csv
from dominio.cotacao import DadosVazios, ResultadoColeta
from formatacao.formatter import COLUNAS_CSV, formatar, para_linhas_csv
from pipeline import executar_coleta

AGORA = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def resultado(registros, **metadados):
    return ResultadoColeta(fonte="teste", moeda_base="usd", registros=registros, coletado_em=AGORA, metadados=metadados)


def test_formata_strings_do_scraping():
    bruto = resultado([
        {"nome": "Argentine Peso", "codigo": "ars", "taxa": "1,524.234057", "taxa_inversa": "0.000656"},
        {"nome": "Brazilian Real", "codigo": "BRL", "taxa": "5.174922", "taxa_inversa": "0.193240"},
    ])
    ars, brl = formatar(bruto)
    assert (ars.moeda_base, ars.moeda_cotada, ars.taxa) == ("USD", "ARS", 1524.234057)
    assert brl.taxa_inversa == 0.19324
    assert brl.data_referencia == date(2026, 10, 1)  # sem data da fonte -> data da coleta


def test_formata_json_da_api_e_calcula_inversa():
    bruto = resultado([{"codigo": "BRL", "nome": "Brazilian Real", "taxa": 5.0}], data_referencia="2026-09-30")
    (brl,) = formatar(bruto)
    assert brl.taxa_inversa == 0.2
    assert brl.data_referencia == date(2026, 9, 30)


def test_descarta_invalidos_remove_duplicatas_e_ordena():
    bruto = resultado([
        {"codigo": "EUR", "taxa": "0.88"},
        {"codigo": "BRL", "taxa": "N/A"},      # taxa ilegível
        {"codigo": "JPY", "taxa": "0"},        # taxa zero
        {"codigo": "XX", "taxa": "1"},         # código inválido
        {"codigo": "EUR", "taxa": "0.99"},     # duplicata
        {"codigo": "CAD", "taxa": 1.41},
    ])
    assert [(c.moeda_cotada, c.taxa) for c in formatar(bruto)] == [("CAD", 1.41), ("EUR", 0.88)]


def test_filtro_de_moedas():
    bruto = resultado([{"codigo": c, "taxa": 1.5} for c in ("BRL", "EUR", "GBP")])
    assert [c.moeda_cotada for c in formatar(bruto, ["brl", "gbp", "XYZ"])] == ["BRL", "GBP"]


def test_sem_dados_validos_gera_erro():
    with pytest.raises(DadosVazios):
        formatar(resultado([{"codigo": "BRL", "taxa": "abc"}]))


def test_linhas_csv_sem_notacao_cientifica():
    (idr,) = formatar(resultado([{"codigo": "IDR", "taxa": 17891}]))
    linha = para_linhas_csv([idr])[0]
    assert linha["taxa"] == "17891"
    assert linha["taxa_inversa"] == "0.00005589"
    assert linha["coletado_em_utc"] == "2026-10-01T12:00:00Z"
    assert tuple(linha) == COLUNAS_CSV


def test_csv_writer_cria_pasta_e_grava(tmp_path):
    destino = tmp_path / "sub" / "dados.csv"
    salvar_csv([{"a": "1", "b": "ç"}], destino, ["a", "b"])
    with destino.open(encoding="utf-8-sig") as arquivo:
        assert list(csv.DictReader(arquivo)) == [{"a": "1", "b": "ç"}]
    assert list(destino.parent.glob("*.tmp")) == []  # nenhum temporário largado


def test_falha_na_coleta_preserva_csv_anterior(tmp_path):
    destino = tmp_path / "dados.csv"
    destino.write_text("conteudo anterior", encoding="utf-8")

    class ColetorVazio:
        def coletar(self, moeda_base):
            return resultado([])

    with pytest.raises(DadosVazios):
        executar_coleta(ColetorVazio(), "USD", destino)
    assert destino.read_text(encoding="utf-8") == "conteudo anterior"
