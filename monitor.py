#!/usr/bin/env python3
"""
iPhone Duo NYC Watch
Monitora a disponibilidade de retirada (Pickup) do iPhone Duo nas Apple Stores de Nova York
e avisa assim que algum modelo aparecer disponivel.

Uso:
    python monitor.py --discover          # descobre os codigos (part numbers) dos modelos
    python monitor.py --once              # faz uma checagem e sai
    python monitor.py                     # roda em loop, usando config.json

Sem dependencias externas: apenas biblioteca padrao do Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.json"
STATE_PATH = ROOT / ".last_seen.json"

FULFILLMENT_URL = "https://www.apple.com/shop/retail/pickup-message"  # o fulfillment-messages bloqueia servidores (HTTP 541)
DEFAULT_BUY_URL = "https://www.apple.com/shop/buy-iphone/iphone-duo"
DEFAULT_BAG_URL = "https://www.apple.com/shop/bag"  # carrinho da Apple
MIN_INTERVAL = 20  # segundos; abaixo disso a Apple tende a bloquear
MAX_BACKOFF = 120
IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"  # estoque dura poucos minutos: nunca esperar mais que 2 min

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": DEFAULT_BUY_URL,
}

PART_RE = re.compile(r"\b([A-Z0-9]{5}LL/A)\b")


# --------------------------------------------------------------------------- utilidades

def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def http_get(url: str, timeout: int = 20) -> str:
    # Usa curl quando disponivel: a Apple recusa (HTTP 541) a assinatura de conexao do urllib.
    if shutil.which("curl"):
        cmd = ["curl", "-sS", "--compressed", "-f", "--max-time", str(timeout)]
        for k, v in HEADERS.items():
            cmd += ["-H", f"{k}: {v}"]
        res = subprocess.run(cmd + [url], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"curl falhou: {res.stderr.strip()[:200]}")
        return res.stdout
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_config(path: Path) -> dict:
    if not path.exists() and IN_CI:
        path = EXAMPLE_CONFIG_PATH
    if not path.exists():
        sys.exit(
            f"Arquivo {path.name} nao encontrado. Copie {EXAMPLE_CONFIG_PATH.name} para "
            f"{path.name} e preencha os part numbers (use --discover para descobrir)."
        )
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("zip", "10001")
    cfg.setdefault("max_distance_miles", 15)
    cfg.setdefault("store_allowlist", [])
    cfg.setdefault("interval_seconds", 30)
    cfg.setdefault("title_must_include", [])
    cfg.setdefault("states", ["NY"])
    cfg.setdefault("cities", [])
    cfg.setdefault("active_hours", {})
    cfg.setdefault("title_must_include_any", [])
    cfg.setdefault("notify", {})
    cfg["interval_seconds"] = max(int(cfg["interval_seconds"]), MIN_INTERVAL)
    if os.environ.get("NTFY_TOPIC"):
        cfg["notify"]["ntfy_topic"] = os.environ["NTFY_TOPIC"]
    # Remove espacos, quebras de linha e caracteres invisiveis que vem junto ao colar no celular
    topic = cfg["notify"].get("ntfy_topic") or ""
    cfg["notify"]["ntfy_topic"] = re.sub(r"[^A-Za-z0-9_-]", "", topic)
    if IN_CI:  # na nuvem nao existe tela nem navegador
        cfg["notify"]["desktop"] = False
        cfg["notify"]["open_bag_in_browser"] = False
    cfg["parts"] = {k: v for k, v in (cfg.get("parts") or {}).items() if PART_RE.fullmatch(k)}
    return cfg


# --------------------------------------------------------------------------- descoberta

def discover_parts(buy_url: str) -> list[str]:
    """Le a pagina de compra e extrai os part numbers americanos (terminados em LL/A)."""
    html = http_get(buy_url)
    return sorted(set(PART_RE.findall(html)))


def title_matches(title: str, cfg: dict) -> bool:
    t = title.lower()
    must = [x.lower() for x in cfg.get("title_must_include", [])]
    any_ = [x.lower() for x in cfg.get("title_must_include_any", [])]
    return all(m in t for m in must) and (not any_ or any(a in t for a in any_))


def titles_for_parts(parts: list[str], zip_code: str) -> dict[str, str]:
    """Pergunta a Apple o nome comercial de cada part (ex.: 'iPhone Duo 256GB Night Sky')."""
    titles: dict[str, str] = {}
    for i in range(0, len(parts), 8):
        payload = json.loads(http_get(build_url(parts[i : i + 8], zip_code)))
        for store in _stores(payload):
            for part, info in (store.get("partsAvailability") or {}).items():
                t = info.get("messageTypes", {}).get("regular", {}).get("storePickupProductTitle")
                if t:
                    titles.setdefault(part, t)
        time.sleep(1)
    return titles


# --------------------------------------------------------------------------- checagem

@dataclass
class Hit:
    part: str
    product: str
    store: str
    store_number: str
    distance: str
    quote: str

    @property
    def key(self) -> str:
        return f"{self.part}@{self.store_number}"


def build_url(parts: list[str], zip_code: str) -> str:
    params: dict[str, str] = {"location": zip_code}
    for i, part in enumerate(parts):
        params[f"parts.{i}"] = part
    return f"{FULFILLMENT_URL}?{urllib.parse.urlencode(params)}"


def _distance(store: dict) -> float:
    raw = store.get("storedistance", store.get("storeDistance"))
    try:
        return float(raw)
    except (TypeError, ValueError):
        txt = str(store.get("storeDistanceWithUnit", ""))
        m = re.search(r"[\d.]+", txt)
        return float(m.group()) if m else 0.0


def _stores(payload: dict) -> list:
    body = payload.get("body", {})
    return body.get("stores") or body.get("content", {}).get("pickupMessage", {}).get("stores", []) or []


def parse_availability(payload: dict, cfg: dict) -> list[Hit]:
    """Transforma a resposta JSON da Apple em uma lista de lojas com estoque."""
    stores = _stores(payload)
    states = [x.upper() for x in cfg.get("states", [])]
    cities = [x.lower() for x in cfg.get("cities", [])]
    allow = [s.lower() for s in cfg.get("store_allowlist", [])]
    max_dist = float(cfg.get("max_distance_miles", 15))
    hits: list[Hit] = []

    for store in stores:
        name = store.get("storeName", "?")
        if allow and not any(a in name.lower() for a in allow):
            continue
        if not allow and _distance(store) > max_dist:
            continue
        if states and str(store.get("state", "")).upper() not in states:
            continue
        if cities and str(store.get("city", "")).lower() not in cities:
            continue
        for part, info in (store.get("partsAvailability") or {}).items():
            if part not in cfg["parts"]:
                continue
            if info.get("pickupDisplay") != "available":
                continue
            msg = info.get("messageTypes", {}).get("regular", {})
            title = msg.get("storePickupProductTitle") or cfg["parts"].get(part) or part
            if not title_matches(title, cfg):
                continue
            hits.append(
                Hit(
                    part=part,
                    product=title,
                    store=name,
                    store_number=store.get("storeNumber", ""),
                    distance=str(store.get("storeDistanceWithUnit", "")),
                    quote=info.get("pickupSearchQuote") or msg.get("storePickupQuote") or "",
                )
            )
    return hits


def check_once(cfg: dict) -> list[Hit]:
    parts = list(cfg["parts"].keys())
    hits: list[Hit] = []
    # A Apple aceita varios parts por chamada; dividimos em lotes de 8 por seguranca.
    for i in range(0, len(parts), 8):
        url = build_url(parts[i : i + 8], cfg["zip"])
        payload = json.loads(http_get(url))
        hits.extend(parse_availability(payload, cfg))
    return hits


# --------------------------------------------------------------------------- notificacoes

def notify(hits: list[Hit], cfg: dict) -> None:
    title = "iPhone Duo disponivel em NY!"
    lines = [f"{h.product} | {h.store} ({h.distance}) {h.quote}".strip() for h in hits]
    body = "\n".join(lines)
    buy = cfg.get("bag_url", DEFAULT_BAG_URL)

    for _ in range(5):  # bip insistente no terminal
        print("\a", end="", flush=True)
        time.sleep(0.3)
    log(f"*** {title} ***\n" + body)

    n = cfg.get("notify", {})
    if n.get("desktop", True):
        _desktop(title, body)
    if n.get("open_bag_in_browser", True):
        import webbrowser
        webbrowser.open(buy)  # abre o carrinho no computador na hora
    if n.get("ntfy_topic"):
        _safe(lambda: _ntfy(n["ntfy_topic"], title, body, buy), "ntfy")
    if n.get("telegram_bot_token") and n.get("telegram_chat_id"):
        _safe(
            lambda: _telegram(n["telegram_bot_token"], n["telegram_chat_id"], f"{title}\n{body}\n{buy}"),
            "Telegram",
        )


def _safe(fn, name: str) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        log(f"Falha ao enviar via {name}: {exc}")


def _desktop(title: str, body: str) -> None:
    system = platform.system()
    first = body.splitlines()[0] if body else ""
    try:
        if system == "Darwin":
            subprocess.run(
                ["osascript", "-e", f'display notification {json.dumps(first)} with title {json.dumps(title)} sound name "Glass"'],
                check=False,
            )
        elif system == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                f"$n.ShowBalloonTip(10000,{json.dumps(title)},{json.dumps(first)},'Info');Start-Sleep 11"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
        elif system == "Linux":
            subprocess.run(["notify-send", title, first], check=False)
    except FileNotFoundError:
        pass


def _ntfy(topic: str, title: str, body: str, click_url: str) -> None:
    req = urllib.request.Request(
        f"https://ntfy.sh/{urllib.parse.quote(topic)}",
        data=body.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": "urgent",
            "Tags": "iphone,rotating_light",
            "Click": click_url,
            "Actions": f"view, Abrir carrinho, {click_url}, clear=true",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15).read()


def _telegram(token: str, chat_id: str, text: str) -> None:
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15).read()


def push_info(cfg: dict, title: str, body: str, urgent: bool = False) -> None:
    topic = cfg.get("notify", {}).get("ntfy_topic")
    if not topic:
        return
    def _send():
        req = urllib.request.Request(
            f"https://ntfy.sh/{urllib.parse.quote(topic)}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "high" if urgent else "default", "Tags": "gear"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15).read()
    _safe(_send, "ntfy")


def ensure_parts(cfg: dict) -> None:
    """Se o config nao tem part numbers reais, descobre sozinho na pagina da Apple."""
    if cfg["parts"]:
        return
    log("Sem part numbers no config. Descobrindo automaticamente ...")
    parts = discover_parts(cfg.get("buy_url", DEFAULT_BUY_URL))
    titles = titles_for_parts(parts, cfg["zip"])
    cfg["parts"] = {p: t for p, t in titles.items() if title_matches(t, cfg)}
    for p, t in cfg["parts"].items():
        log(f"  monitorando {p}  {t}")
    if not cfg["parts"]:
        raise RuntimeError(f"nenhum modelo bateu com o filtro ({len(parts)} parts lidos, {len(titles)} com nome)")


def within_active_hours(cfg: dict, now: datetime | None = None) -> bool:
    """True se estamos dentro do horario configurado (ex.: 07:00 a 22:00 de Nova York)."""
    ah = cfg.get("active_hours") or {}
    if not ah:
        return True
    tz = ZoneInfo(ah.get("tz", "America/New_York"))
    now = (now or datetime.now(tz)).astimezone(tz)
    start = dtime.fromisoformat(ah.get("start", "00:00"))
    end = dtime.fromisoformat(ah.get("end", "23:59"))
    return start <= now.time() < end


# --------------------------------------------------------------------------- estado

def load_seen() -> set[str]:
    try:
        return set(json.loads(STATE_PATH.read_text()))
    except Exception:  # noqa: BLE001
        return set()


def save_seen(keys: set[str]) -> None:
    STATE_PATH.write_text(json.dumps(sorted(keys)))


# --------------------------------------------------------------------------- loop

def run(cfg: dict, once: bool, duration_minutes: float = 0) -> None:
    if not within_active_hours(cfg):
        log("Fora do horario de monitoramento. Encerrando.")
        return
    seen = load_seen()
    backoff = 0
    errors_in_row = 0
    deadline = time.time() + duration_minutes * 60 if duration_minutes else None
    for attempt in range(5):
        try:
            ensure_parts(cfg)
            break
        except Exception as exc:  # noqa: BLE001
            log(f"Falha na descoberta: {exc}")
            if attempt == 4:
                push_info(cfg, "Monitor iPhone Duo com problema",
                          f"Nao consegui identificar os modelos Night Sky 256/512GB: {exc}", urgent=True)
                sys.exit(1)
            time.sleep(30)
    if os.environ.get("ANNOUNCE_START") == "1":
        push_info(cfg, "Monitor iPhone Duo ligado",
                  f"Checando {len(cfg['parts'])} modelo(s) a cada {cfg['interval_seconds']}s.")
    log(
        f"Monitorando {len(cfg['parts'])} modelo(s) perto do ZIP {cfg['zip']} "
        f"a cada ~{cfg['interval_seconds']}s. Ctrl+C para parar."
    )
    while True:
        try:
            hits = check_once(cfg)
            backoff = 0
            errors_in_row = 0
            current = {h.key for h in hits}
            new = [h for h in hits if h.key not in seen]
            if new:
                notify(new, cfg)
            elif hits:
                log(f"Ainda disponivel em {len(current)} combinacao(oes) (ja avisado).")
            else:
                log("Nada disponivel para retirada nas lojas monitoradas.")
            seen = current  # se esgotar e voltar, avisa de novo
            save_seen(seen)
        except Exception as exc:  # noqa: BLE001
            backoff = min(backoff + 1, 6)
            errors_in_row += 1
            log(f"Erro na checagem ({exc}). Nova tentativa com espera maior (nivel {backoff}).")
            if errors_in_row == 10:
                push_info(cfg, "Monitor iPhone Duo com problema",
                          f"10 erros seguidos consultando a Apple. Ultimo: {exc}", urgent=True)
        if once or (deadline and time.time() >= deadline) or not within_active_hours(cfg):
            log("Fim do ciclo.")
            return
        wait = cfg["interval_seconds"] * (2 ** backoff if backoff else 1)
        time.sleep(min(wait, MAX_BACKOFF) + random.uniform(-2, 2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Monitor de retirada do iPhone Duo em NYC")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--once", action="store_true", help="faz uma checagem e sai")
    ap.add_argument("--discover", action="store_true", help="lista part numbers da pagina de compra")
    ap.add_argument("--buy-url", default=None, help="URL da pagina de compra (para --discover)")
    ap.add_argument("--duration-minutes", type=float, default=0, help="encerra apos N minutos (uso no GitHub Actions)")
    ap.add_argument("--write", action="store_true", help="com --discover: grava no config.json os parts que batem com o filtro")
    ap.add_argument("--test-notify", action="store_true", help="dispara uma notificacao de teste")
    args = ap.parse_args()

    if args.discover:
        url = args.buy_url or DEFAULT_BUY_URL
        log(f"Lendo {url} ...")
        parts = discover_parts(url)
        if not parts:
            log("Nenhum part number encontrado. Veja a secao 'Descobrir part numbers' no README.")
            return
        base = json.loads((args.config if args.config.exists() else EXAMPLE_CONFIG_PATH).read_text(encoding="utf-8"))
        log(f"{len(parts)} part numbers encontrados. Consultando nomes na Apple ...")
        titles = titles_for_parts(parts, base.get("zip", "10001"))
        chosen = {}
        for p in parts:
            t = titles.get(p, "(sem nome)")
            ok = p in titles and title_matches(t, base)
            print(f"{'>>' if ok else '  '} {p}  {t}")
            if ok:
                chosen[p] = t
        log(f"{len(chosen)} modelo(s) batem com o filtro (marcados com >>).")
        if args.write and chosen:
            base["parts"] = chosen
            args.config.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
            log(f"Gravado em {args.config.name}.")
        return

    cfg = load_config(args.config)
    if args.test_notify:
        notify([Hit("TESTE", "iPhone Duo (teste)", "Apple Fifth Avenue", "R095", "0.8 mi", "Today")], cfg)
        return
    try:
        run(cfg, args.once, args.duration_minutes)
    except KeyboardInterrupt:
        log("Encerrado.")


if __name__ == "__main__":
    main()
