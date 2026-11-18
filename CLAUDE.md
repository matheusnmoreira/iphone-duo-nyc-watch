# CLAUDE.md

Projeto pequeno: monitor de retirada do iPhone Duo (Night Sky, 256GB/512GB) em Apple Stores de NYC.

- Código único em `monitor.py`, só biblioteca padrão do Python. Não adicionar dependências sem necessidade.
- Endpoint usado: `https://www.apple.com/shop/retail/pickup-message?parts.N=<PART>&location=<ZIP>` (o `fulfillment-messages` devolve HTTP 541 para servidores do GitHub).
  Estrutura relevante: `body.stores[].partsAvailability[part].pickupDisplay == "available"`.
- Requisições à Apple via `curl` (o urllib do Python leva 541). Modelos: MK1F4LL/A (256GB Night Sky), MK1H4LL/A (512GB Night Sky). Só lojas de Manhattan e Brooklyn (state NY, city "New York" ou "Brooklyn").
- Estoque dura menos de 4 minutos: latência do alerta é prioridade. Intervalo padrão 60s, só das 07:00 às 22:00 de Nova York, backoff máximo 120s.
- Execução contínua: cada ciclo do GitHub Actions dura ~5h45, aguarda fora da janela e dispara o próximo ciclo sozinho (workflow_dispatch via GITHUB_TOKEN). O cron é só rede de segurança.
- Alerta abre `https://www.apple.com/shop/bag` (carrinho da Apple).
- `config.json` e `.last_seen.json` são locais e ficam fora do git.
- Antes de commitar: `python -m pytest -q tests`.
- Documentação em português, linguagem simples.
