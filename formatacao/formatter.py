"""
Camada de FORMATAÇÃO: transforma dados brutos em `Cotacao` padronizadas.

É aqui que os dois scripts "se encontram": tanto o HTML raspado quanto o JSON
da API saem desta camada exatamente no mesmo formato, o que garante CSVs com
colunas, tipos e convenções idênticas.

Regras aplicadas:
  * códigos de moeda em maiúsculas (ISO 4217);
  * taxas convertidas de texto/JSON para float, aceitando "1,234.56";
  * registros inválidos (taxa vazia, zero, negativa) são descartados com log,
    sem derrubar o restante da coleta;
  * taxa inversa usada quando a fonte informa; senão é calculada (1 / taxa);
  * duplicatas removidas e resultado ordenado pelo código da moeda;
  * filtro opcional por lista de moedas de interesse.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Iterable

from dominio.cotacao import Cotacao, DadosVazios, ResultadoColeta

logger = logging.getLogger(__name__)

# Ordem e nomes das colunas do CSV final — comum aos dois scripts.
COLUNAS_CSV: tuple[str, ...] = (
    "moeda_base",
    "moeda_cotada",
    "nome_moeda",
    "taxa",
    "taxa_inversa",
    "data_referencia",
    "coletado_em_utc",
    "fonte",
)

CASAS_DECIMAIS = 8


def formatar(resultado: ResultadoColeta, moedas: Iterable[str] | None = None) -> list[Cotacao]:
    """Converte um `ResultadoColeta` (bruto) em uma lista de `Cotacao`.

    Args:
        resultado: dados brutos vindos de qualquer coletor (scraping ou API).
        moedas: se informado, mantém apenas essas moedas (ex.: {"BRL", "EUR"}).

    Raises:
        DadosVazios: se, após a limpeza, não sobrar nenhuma cotação válida.
    """
    filtro = {m.strip().upper() for m in moedas} if moedas else None
    base = resultado.moeda_base.upper()
    data_ref = _data_referencia(resultado)

    cotacoes: dict[str, Cotacao] = {}
    descartados = 0

    for bruto in resultado.registros:
        cotacao = _converter_registro(bruto, base, data_ref, resultado)
        if cotacao is None:
            descartados += 1
            continue
        if filtro and cotacao.moeda_cotada not in filtro:
            continue
        # Dicionário por código = remoção natural de duplicatas.
        cotacoes.setdefault(cotacao.moeda_cotada, cotacao)

    if descartados:
        logger.warning("%d registro(s) descartado(s) por dados inválidos.", descartados)

    if filtro:
        ausentes = filtro - cotacoes.keys()
        if ausentes:
            logger.warning("Moedas solicitadas não disponíveis na fonte: %s", ", ".join(sorted(ausentes)))

    if not cotacoes:
        raise DadosVazios("Nenhuma cotação válida após a formatação.")

    return sorted(cotacoes.values(), key=lambda c: c.moeda_cotada)


def para_linhas_csv(cotacoes: Iterable[Cotacao]) -> list[dict[str, str]]:
    """Serializa as cotações em dicionários de texto, prontos para o CSV.

    Convenções: datas em ISO 8601, ponto como separador decimal e sem notação
    científica (para abrir corretamente em qualquer ferramenta).
    """
    return [
        {
            "moeda_base": c.moeda_base,
            "moeda_cotada": c.moeda_cotada,
            "nome_moeda": c.nome_moeda,
            "taxa": _numero_para_texto(c.taxa),
            "taxa_inversa": _numero_para_texto(c.taxa_inversa),
            "data_referencia": c.data_referencia.isoformat(),
            "coletado_em_utc": c.coletado_em.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fonte": c.fonte,
        }
        for c in cotacoes
    ]


# --------------------------------------------------------------------------- #
# Funções auxiliares (privadas ao módulo)
# --------------------------------------------------------------------------- #
def _converter_registro(
    bruto: dict[str, Any], base: str, data_ref: date, resultado: ResultadoColeta
) -> Cotacao | None:
    codigo = str(bruto.get("codigo") or "").strip().upper()
    taxa = _para_float(bruto.get("taxa"))

    if len(codigo) != 3 or not codigo.isalpha() or codigo == base:
        logger.debug("Registro ignorado (código inválido): %r", bruto)
        return None
    if taxa is None:
        logger.debug("Registro ignorado (taxa inválida): %r", bruto)
        return None

    # Prefere a inversa informada pela fonte; calcula se ausente/inválida.
    inversa = _para_float(bruto.get("taxa_inversa")) or 1 / taxa

    return Cotacao(
        moeda_base=base,
        moeda_cotada=codigo,
        nome_moeda=str(bruto.get("nome") or "").strip(),
        taxa=round(taxa, CASAS_DECIMAIS),
        taxa_inversa=round(inversa, CASAS_DECIMAIS),
        data_referencia=data_ref,
        coletado_em=resultado.coletado_em,
        fonte=resultado.fonte,
    )


def _para_float(valor: Any) -> float | None:
    """Converte texto/número em float positivo e finito; senão retorna None."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(str(valor).replace(",", "").strip())
    except ValueError:
        return None
    if not math.isfinite(numero) or numero <= 0:
        return None
    return numero


def _data_referencia(resultado: ResultadoColeta) -> date:
    """Usa a data informada pela fonte; na falta dela, a data da coleta."""
    informada = resultado.metadados.get("data_referencia")
    if informada:
        try:
            return date.fromisoformat(str(informada))
        except ValueError:
            logger.warning("Data de referência inválida na fonte: %r", informada)
    return resultado.coletado_em.date()


def _numero_para_texto(numero: float) -> str:
    """5.20270000 -> '5.2027' | 0.00005589 -> '0.00005589' (sem 'e-05')."""
    texto = f"{numero:.{CASAS_DECIMAIS}f}".rstrip("0").rstrip(".")
    return texto or "0"
