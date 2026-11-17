# iPhone Duo NYC Watch

Monitora uma vez por minuto, das 7h às 22h de Nova York, a disponibilidade de **retirada na loja (Pickup)** do **iPhone Duo Night Sky 256GB ou 512GB** nas Apple Stores de Manhattan e Brooklyn e alerta na hora em que aparecer estoque.

Quando surgir estoque, o script:
1. Toca um bip insistente no terminal e mostra loja, modelo e prazo de retirada.
2. Abre **o seu carrinho da Apple** no navegador do computador.
3. Manda uma **notificação urgente no celular** (via ntfy), com botão "Abrir carrinho".
4. Opcional: mensagem no Telegram.

Sem dependências: só Python 3.9+.

## Rodar na nuvem, sem computador (GitHub Actions)

1. Repositório **público** (Actions é ilimitado e grátis em repositório público; no privado o limite de 2.000 min/mês acaba em ~1 dia e meio).
2. Em Settings > Secrets and variables > Actions, crie o secret `NTFY_TOPIC` com o nome do seu tópico ntfy.
3. Em Actions > iPhone Duo watch > Run workflow. Você recebe "Monitor iPhone Duo ligado" no celular.
4. Os modelos Night Sky 256/512GB são descobertos sozinhos. Se a Apple bloquear ou a descoberta falhar, chega um aviso de problema no celular.

## Setup rápido no computador (5 minutos)

```bash
# 1. Criar o config
cp config.example.json config.json

# 2. Descobrir e gravar automaticamente os part numbers Night Sky 256GB/512GB
python monitor.py --discover --write

# 3. Testar o alerta (deve tocar no computador e no celular)
python monitor.py --test-notify

# 4. Rodar
python monitor.py
```

## Alerta no celular (recomendado)

1. Instale o app **ntfy** (iOS ou Android).
2. No app, assine um tópico com nome difícil de adivinhar, por exemplo `duo-watch-<algo-aleatorio>`.
3. Coloque o mesmo nome em `notify.ntfy_topic` no `config.json`.
4. No iPhone, permita notificações críticas/urgentes do ntfy para tocar mesmo em silencioso.

## Configuração (`config.json`)

| Campo | O que faz |
|---|---|
| `zip` | CEP de referência. `10001` = Midtown Manhattan |
| `max_distance_miles` | Raio das lojas monitoradas (15 mi cobre Manhattan, Brooklyn e Queens) |
| `store_allowlist` | Se preenchido, monitora só essas lojas (ex.: `["Fifth Avenue", "SoHo"]`) e ignora o raio |
| `interval_seconds` | Intervalo entre checagens. Padrão 60 (uma por minuto). Mínimo 20 |
| `active_hours` | Janela diária de monitoramento no fuso de Nova York (padrão 07:00 a 22:00) |
| `states` / `cities` | Filtro de lojas. Padrão: estado `NY`, cidades `New York` (Manhattan) e `Brooklyn`. Para incluir Queens e Bronx, adicione `Elmhurst` e `Bronx` |
| `title_must_include` | Termos obrigatórios no nome do modelo (`Night Sky`) |
| `title_must_include_any` | Pelo menos um destes (`256GB`, `512GB`) |
| `parts` | Part numbers monitorados (preenchido pelo `--discover --write`) |
| `bag_url` | Link aberto no alerta (seu carrinho) |

## Descobrir part numbers manualmente

Se o `--discover` não encontrar nada (a Apple muda a página às vezes):
1. Abra a página de compra do iPhone Duo, escolha Night Sky + 256GB.
2. Clique em "Check availability" com o DevTools aberto (aba Network) e procure a chamada `fulfillment-messages`.
3. O parâmetro `parts.0` é o part number (formato `XXXXXLL/A`). Repita para 512GB.
4. Cole em `parts` no `config.json`.

Atenção: nos EUA pode haver part numbers diferentes para a versão desbloqueada e para operadoras. Monitore a versão que está no seu carrinho.

## Boas práticas

- Deixe o computador ligado e sem suspensão enquanto roda.
- Não reduza para menos de 20s: a Apple pode bloquear o IP temporariamente. Em caso de erro, o script espera no máximo 2 minutos antes de tentar de novo.
- O alerta dispara de novo se o estoque esgotar e voltar.

## Testes

```bash
python -m pytest -q tests
```
