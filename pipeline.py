"""
Caso de uso (camada de aplicação): o fluxo  coleta -> formatação -> armazenamento.

Os dois scripts executam exatamente o mesmo fluxo; só muda o coletor usado.
Por isso o fluxo vive aqui, uma única vez, e recebe o coletor por INJEÇÃO DE
DEPENDÊNCIA (qualquer objeto que implemente a porta `ColetorCotacoes`).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable

import config
from armazenamento.csv_writer import ErroArmazenamento, salvar_csv
from dominio.cotacao import BloqueioDetectado, ColetorCotacoes, ErroColeta
from formatacao.formatter import COLUNAS_CSV, formatar, para_linhas_csv

logger = logging.getLogger("pipeline")

# Códigos de saída do processo — úteis para agendadores (cron, Airflow etc.).
SUCESSO = 0
ERRO_BLOQUEIO = 2
ERRO_COLETA = 3
ERRO_ARMAZENAMENTO = 4
ERRO_INESPERADO = 1


def executar_coleta(
    coletor: ColetorCotacoes,
    moeda_base: str,
    caminho_saida: Path,
    moedas: Iterable[str] | None = None,
) -> Path:
    """Executa o fluxo completo e devolve o caminho do CSV gerado.

    As exceções de domínio sobem para quem chamou decidir o que fazer.
    Note que, se a coleta ou a formatação falharem, nada é gravado: o CSV
    da execução anterior é preservado.
    """
    bruto = coletor.coletar(moeda_base)                    # CAMADA 1
    cotacoes = formatar(bruto, moedas)                     # CAMADA 2
    linhas = para_linhas_csv(cotacoes)
    return salvar_csv(linhas, caminho_saida, COLUNAS_CSV)  # CAMADA 3


def rodar_com_tratamento(
    coletor: ColetorCotacoes, moeda_base: str, caminho_saida: Path, moedas: Iterable[str] | None
) -> int:
    """Envolve `executar_coleta` traduzindo exceções em mensagens e exit codes."""
    try:
        destino = executar_coleta(coletor, moeda_base, caminho_saida, moedas)
    except BloqueioDetectado as erro:
        logger.error("Acesso bloqueado pela fonte: %s", erro)
        return ERRO_BLOQUEIO
    except ErroColeta as erro:
        logger.error("Falha na coleta: %s", erro)
        return ERRO_COLETA
    except ErroArmazenamento as erro:
        logger.error("Falha ao salvar o CSV: %s", erro)
        return ERRO_ARMAZENAMENTO
    except KeyboardInterrupt:
        logger.warning("Execução interrompida pelo usuário.")
        return ERRO_INESPERADO
    except Exception:  # noqa: BLE001 — última barreira: registra o traceback completo
        logger.exception("Erro inesperado.")
        return ERRO_INESPERADO

    logger.info("Concluído com sucesso: %s", destino)
    return SUCESSO


# --------------------------------------------------------------------------- #
# Utilidades de linha de comando compartilhadas pelos dois scripts
# --------------------------------------------------------------------------- #
def criar_parser(descricao: str, saida_padrao: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=descricao)
    parser.add_argument(
        "--base",
        default=config.MOEDA_BASE_PADRAO,
        help="Moeda de referência, código ISO 4217 (padrão: %(default)s).",
    )
    parser.add_argument(
        "--moedas",
        type=lambda s: [m for m in s.split(",") if m.strip()],
        default=None,
        help="Filtra moedas específicas, separadas por vírgula (ex.: BRL,EUR,GBP). "
        "Padrão: todas as disponíveis.",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=saida_padrao,
        help="Caminho do CSV de saída (padrão: %(default)s).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Exibe logs de depuração.")
    return parser


def validar_moeda_base(valor: str) -> str:
    codigo = valor.strip().upper()
    if len(codigo) != 3 or not codigo.isalpha():
        raise SystemExit(f"Moeda base inválida: '{valor}'. Use um código ISO de 3 letras (ex.: USD).")
    return codigo


def configurar_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # Evita poluir o log com detalhes internos das bibliotecas HTTP.
    for ruidoso in ("urllib3", "selenium", "WDM"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
