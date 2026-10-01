"""
SCRIPT 1 — Ponto de entrada da coleta via WEB SCRAPING.

Fluxo:  ScraperXRates (coleta) -> formatter (formatação) -> csv_writer (armazenamento)

Uso:
    python main_scraping.py
    python main_scraping.py --base BRL --moedas USD,EUR,GBP
    python main_scraping.py --selenium sempre
"""

import sys

import config
from coleta.scraper import ScraperXRates
from pipeline import configurar_logging, criar_parser, rodar_com_tratamento, validar_moeda_base


def main() -> int:
    parser = criar_parser(
        "Coleta cotações de câmbio do x-rates.com via web scraping e salva em CSV.",
        saida_padrao=config.ARQUIVO_SCRAPING,
    )
    parser.add_argument(
        "--selenium",
        choices=("auto", "nunca", "sempre"),
        default="auto",
        help="auto: usa Selenium só se requests for bloqueado (padrão); "
        "nunca: só requests; sempre: só Selenium.",
    )
    args = parser.parse_args()
    configurar_logging(args.verbose)

    # Composição das dependências: aqui (e só aqui) escolhemos a implementação.
    coletor = ScraperXRates(modo_selenium=args.selenium)

    return rodar_com_tratamento(coletor, validar_moeda_base(args.base), args.saida, args.moedas)


if __name__ == "__main__":
    sys.exit(main())
