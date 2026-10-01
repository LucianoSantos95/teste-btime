# Coleta de Cotações de Câmbio — Web Scraping x API

Dois scripts Python que coletam **cotações de moedas** da mesma forma e geram
CSVs com **exatamente o mesmo layout**:

| Script | Fonte | Técnica |
|---|---|---|
| `main_scraping.py` | [x-rates.com](https://www.x-rates.com/table/?from=USD&amount=1) | Web scraping com `requests` + BeautifulSoup, com fallback para Selenium |
| `main_api.py` | [Frankfurter API](https://frankfurter.dev) (Banco Central Europeu), com [ExchangeRate-API](https://www.exchangerate-api.com/docs/free) como reserva | Requisição REST/JSON |

**Por que câmbio?** É um dado público, atualizado com frequência e disponível
tanto em sites quanto em APIs gratuitas sem chave. Isso permite comparar as
duas abordagens com o mesmo dado.

---

## 1. Instalação

Pré-requisitos: **Python 3.10+**. O **Google Chrome** só é necessário para o
fallback com Selenium; o ChromeDriver é baixado automaticamente pelo Selenium 4.

```bash
git clone <url-do-repositorio>
cd teste-btime

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

Dependências (`requirements.txt`):

| Biblioteca | Uso |
|---|---|
| `requests` | Requisições HTTP nos dois scripts |
| `beautifulsoup4` | Parsing do HTML (Script 1) |
| `selenium` | Fallback do Script 1 quando há bloqueio ou conteúdo renderizado por JS |
| `pytest` | Testes automatizados |

---

## 2. Execução

### Script 1 — Web Scraping
```bash
python main_scraping.py
```
Gera `saida/dados_scraping.csv`.

### Script 2 — API
```bash
python main_api.py
```
Gera `saida/dados_api.csv`.

### Opções (valem para os dois scripts)

| Opção | Descrição | Padrão |
|---|---|---|
| `--base USD` | Moeda de referência (ISO 4217) | `USD` |
| `--moedas BRL,EUR,GBP` | Filtra apenas essas moedas | todas |
| `--saida caminho.csv` | Caminho do arquivo gerado | `saida/dados_*.csv` |
| `-v`, `--verbose` | Logs de depuração | desligado |
| `--selenium auto\|nunca\|sempre` | *(só scraping)* quando usar o Selenium | `auto` |
| `--sem-reserva` | *(só API)* não usa a API reserva | desligado |

Exemplos:
```bash
python main_scraping.py --base BRL --moedas USD,EUR,GBP
python main_scraping.py --selenium sempre        # força o navegador headless
python main_api.py --base EUR -v
```

### Códigos de saída
Úteis para agendadores (cron, Airflow, Task Scheduler):

| Código | Significado |
|---|---|
| `0` | Sucesso |
| `1` | Erro inesperado |
| `2` | Acesso bloqueado pela fonte |
| `3` | Falha na coleta (rede, API fora, layout mudou, dados vazios) |
| `4` | Falha ao gravar o CSV |

### Testes
```bash
python -m pytest -v
```
São 22 testes que rodam **sem internet**: o HTTP é simulado e o scraper usa um
trecho real da página em `tests/fixtures/`.

---

## 3. Formato do CSV

Os dois scripts produzem as mesmas colunas, na mesma ordem e com as mesmas
convenções (UTF-8 com BOM, separador `,`, decimal `.`, datas ISO 8601).

| Coluna | Exemplo | Descrição |
|---|---|---|
| `moeda_base` | `USD` | Moeda de referência |
| `moeda_cotada` | `BRL` | Moeda cotada (ISO 4217) |
| `nome_moeda` | `Brazilian Real` | Nome da moeda cotada |
| `taxa` | `5.2027` | 1 `moeda_base` = *taxa* `moeda_cotada` |
| `taxa_inversa` | `0.19220789` | 1 `moeda_cotada` = *taxa_inversa* `moeda_base` |
| `data_referencia` | `2026-09-30` | Data a que a cotação se refere |
| `coletado_em_utc` | `2026-10-01T13:03:05Z` | Momento da coleta |
| `fonte` | `Frankfurter API (Banco Central Europeu)` | Origem do dado |

Exemplo (`saida/dados_api.csv`):
```csv
moeda_base,moeda_cotada,nome_moeda,taxa,taxa_inversa,data_referencia,coletado_em_utc,fonte
USD,BRL,Brazilian Real,5.2027,0.19220789,2026-09-30,2026-10-01T13:03:05Z,Frankfurter API (Banco Central Europeu)
```

---

## 4. Arquitetura

O projeto combina **camadas** com **Arquitetura Hexagonal (Ports & Adapters)**,
seguindo a regra de dependência da **Clean Architecture**: as camadas externas
dependem do domínio, nunca o contrário.

```
teste-btime/
├── README.md
├── requirements.txt
├── config.py                  ← URLs, timeouts, User-Agents, caminhos (sem números mágicos)
├── pipeline.py                ← CASO DE USO: coleta → formatação → armazenamento + CLI comum
│
├── dominio/                   ← NÚCLEO: não depende de nenhuma biblioteca externa
│   └── cotacao.py               entidade Cotacao, ResultadoColeta, porta ColetorCotacoes, exceções
│
├── coleta/                    ← CAMADA 1: só busca o dado bruto (adaptadores da porta)
│   ├── http_client.py           cliente HTTP resiliente (retry, backoff, UA, timeouts)
│   ├── scraper.py               Script 1: ScraperXRates (BeautifulSoup + fallback Selenium)
│   └── api_client.py            Script 2: ClienteApiCambio (Frankfurter + reserva)
│
├── formatacao/                ← CAMADA 2: só padroniza
│   └── formatter.py             bruto → Cotacao → linhas do CSV (mesmo formato p/ as duas fontes)
│
├── armazenamento/             ← CAMADA 3: só salva
│   └── csv_writer.py            gravação atômica do CSV
│
├── main_scraping.py           ← ORQUESTRA o Script 1: ScraperXRates → pipeline
├── main_api.py                ← ORQUESTRA o Script 2: ClienteApiCambio → pipeline
│
├── tests/                     ← testes offline de todas as camadas
└── saida/
    ├── dados_scraping.csv
    └── dados_api.csv
```

### Fluxo

```
            main_scraping.py                      main_api.py
                   │  (injeta o adaptador)              │
                   ▼                                    ▼
            ScraperXRates ─┐                ┌─ ClienteApiCambio
                           └── ColetorCotacoes ─┘   ← porta (interface do domínio)
                                     │ ResultadoColeta (dado bruto)
                                     ▼
                            formatter.formatar()      → list[Cotacao]
                                     │
                                     ▼
                         formatter.para_linhas_csv()  → list[dict]
                                     │
                                     ▼
                           csv_writer.salvar_csv()    → saida/*.csv
```

### Decisões e princípios aplicados

- **Responsabilidade única (SRP):** cada camada faz uma coisa. O scraper não
  converte tipos, o formatter não acessa a rede e o writer não conhece câmbio.
- **Porta e adaptadores:** `ColetorCotacoes` é a porta. `ScraperXRates` e
  `ClienteApiCambio` são adaptadores intercambiáveis. Adicionar uma nova fonte
  (ex.: Banco Central do Brasil) é só criar uma classe nova, sem mexer em
  formatação nem em armazenamento.
- **Injeção de dependência:** os `main_*.py` são a "raiz de composição", ou seja,
  o único lugar que escolhe as implementações. O `ClienteHttp` também é injetado,
  o que permite testar tudo sem rede.
- **Fluxo único (DRY):** os dois scripts usam o mesmo `pipeline.executar_coleta`.
  Só muda o coletor.
- **Exceções de domínio** (`BloqueioDetectado`, `EstruturaInesperada`,
  `DadosVazios`) permitem reagir a cada tipo de falha de forma específica.

---

## 5. Robustez e tratamento de bloqueios

### Script 1 — Web Scraping
| Problema | Estratégia |
|---|---|
| Ética / permissão | Consulta o `robots.txt` antes de acessar e aborta se for proibido |
| Rate limiting (429) e instabilidade (5xx) | Até 4 tentativas com **backoff exponencial + jitter**, respeitando o `Retry-After` |
| Bloqueio por assinatura de robô (403) | **Rotação de User-Agent** a cada tentativa e cabeçalhos de navegador real |
| Padrão de acesso robótico | **Atraso aleatório** de 1 a 3 s antes de cada requisição |
| Bloqueio "disfarçado" (HTTP 200 com captcha ou desafio) | Detecta marcadores no HTML e trata como bloqueio |
| Bloqueio persistente ou conteúdo via JavaScript | **Fallback automático para Selenium** (Chrome headless, com sinais de automação reduzidos) |
| Mudança de layout do site | Seletor principal e um seletor reserva. Se a tabela sumir, gera `EstruturaInesperada` com mensagem clara |
| Linha malformada | É descartada com log, sem derrubar a coleta inteira |
| Servidor lento | Timeouts explícitos (conexão 5 s, leitura 20 s) |

### Script 2 — API
| Problema | Estratégia |
|---|---|
| API fora do ar | **Failover** automático para uma segunda API |
| Erros transitórios | Mesmo `ClienteHttp` com retry, backoff e timeout |
| Mudança de contrato | Valida campos e tipos do JSON antes de usar |
| Erro no corpo com HTTP 200 | Verifica `result == "success"` (API reserva) |
| Dado complementar indisponível | A falha ao buscar os nomes das moedas não interrompe a coleta |

### Comum
- **Escrita atômica do CSV:** grava num arquivo temporário e só então
  substitui o destino. Uma falha nunca deixa um CSV corrompido ou pela metade.
- **Falhou, não sobrescreve:** se a coleta falha, o CSV anterior é mantido.
- **Validação dos dados:** taxas vazias, zero, negativas ou não numéricas são
  descartadas. Duplicatas são removidas e o resultado sai ordenado.

---

## 6. Observações sobre os dados

- **As fontes não são idênticas.** O x-rates publica taxas de mercado
  atualizadas ao longo do dia (cerca de 50 moedas). O BCE publica uma taxa
  oficial de referência por dia útil, por volta das 16h CET (cerca de 30 moedas).
  Por isso pode haver pequenas diferenças, como BRL 5.18 x 5.20, e moedas que
  só aparecem em uma das fontes.
- **`data_referencia`:** na API é a data oficial informada pela fonte. No
  scraping é a data da coleta, porque o carimbo de data exibido pelo x-rates
  estava inconsistente durante o desenvolvimento ("Jan 01, 2026"). Esse carimbo
  é registrado apenas nos metadados internos e não vai para o CSV.
- **Fins de semana e feriados:** o BCE não publica nesses dias, então a API
  devolve a última data útil.
