"""
Camada de ARMAZENAMENTO: grava as linhas formatadas em um arquivo CSV.

Não sabe nada sobre scraping, APIs ou câmbio — recebe linhas prontas e as
persiste. Trocar CSV por banco de dados, por exemplo, afetaria só este módulo.

Robustez:
  * escrita ATÔMICA: grava em um arquivo temporário e só então substitui o
    destino. Se algo falhar no meio, o CSV anterior continua intacto (nunca
    fica um arquivo pela metade);
  * cria a pasta de saída se ela não existir;
  * UTF-8 com BOM, para o Excel exibir acentos corretamente.
"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)


class ErroArmazenamento(Exception):
    """Falha ao gravar o arquivo de saída."""


def salvar_csv(linhas: Iterable[dict[str, str]], caminho: Path, colunas: Sequence[str]) -> Path:
    """Grava `linhas` em `caminho` com as `colunas` na ordem informada.

    Returns:
        O caminho absoluto do arquivo gravado.

    Raises:
        ErroArmazenamento: se o arquivo não puder ser gravado.
    """
    destino = Path(caminho).resolve()
    arquivo_temp: str | None = None

    try:
        destino.parent.mkdir(parents=True, exist_ok=True)

        # O temporário fica na mesma pasta para que os.replace seja atômico.
        descritor, arquivo_temp = tempfile.mkstemp(
            dir=destino.parent, prefix=f".{destino.stem}_", suffix=".tmp"
        )
        with os.fdopen(descritor, "w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.DictWriter(
                arquivo,
                fieldnames=list(colunas),
                extrasaction="ignore",  # ignora chaves fora do layout definido
                quoting=csv.QUOTE_MINIMAL,
            )
            escritor.writeheader()
            total = 0
            for linha in linhas:
                escritor.writerow(linha)
                total += 1

        os.replace(arquivo_temp, destino)
        arquivo_temp = None  # já foi movido; nada a limpar
    except OSError as erro:
        raise ErroArmazenamento(f"Não foi possível gravar {destino}: {erro}") from erro
    finally:
        if arquivo_temp and os.path.exists(arquivo_temp):
            os.remove(arquivo_temp)

    logger.info("%d linha(s) gravada(s) em %s", total, destino)
    return destino
