"""
SCRIPT 2 — Ponto de entrada da coleta via API PÚBLICA.

Fluxo:  ClienteApiCambio (coleta) -> formatter (formatação) -> csv_writer (armazenamento)

Uso:
    python main_api.py
    python main_api.py --base BRL --moedas USD,EUR,GBP
    python main_api.py --sem-reserva
"""

import sys

import config
from coleta.api_client import ClienteApiCambio
from pipeline import configurar_logging, criar_parser, rodar_com_tratamento, validar_moeda_base


def main() -> int:
    parser = criar_parser(
        "Coleta cotações de câmbio de uma API pública e salva em CSV.",
        saida_padrao=config.ARQUIVO_API,
    )
    parser.add_argument(
        "--sem-reserva",
        action="store_true",
        help="Não usa a API reserva caso a principal (Frankfurter) falhe.",
    )
    args = parser.parse_args()
    configurar_logging(args.verbose)

    # Composição das dependências: aqui (e só aqui) escolhemos a implementação.
    coletor = ClienteApiCambio(usar_reserva=not args.sem_reserva)

    return rodar_com_tratamento(coletor, validar_moeda_base(args.base), args.saida, args.moedas)


if __name__ == "__main__":
    sys.exit(main())
