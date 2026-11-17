# CLAUDE.md

Projeto pequeno: monitor de retirada do iPhone Duo (Night Sky, 256GB/512GB) em Apple Stores de NYC.

- Código único em `monitor.py`, só biblioteca padrão do Python. Não adicionar dependências sem necessidade.
- Endpoint usado: `https://www.apple.com/shop/fulfillment-messages?pl=true&mts.0=regular&parts.N=<PART>&location=<ZIP>`.
  Estrutura relevante: `body.content.pickupMessage.stores[].partsAvailability[part].pickupDisplay == "available"`.
- Estoque dura menos de 4 minutos: latência do alerta é prioridade. Intervalo padrão 30s, backoff máximo 120s.
- Alerta abre `https://www.apple.com/shop/bag` (carrinho da Apple).
- `config.json` e `.last_seen.json` são locais e ficam fora do git.
- Antes de commitar: `python -m pytest -q tests`.
- Documentação em português, linguagem simples.
