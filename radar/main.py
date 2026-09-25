"""Ponto de entrada: python -m radar.main

Variáveis de ambiente (no GitHub, cadastre as sensíveis em Settings > Secrets):
  CHANNEL_HANDLE  @ do canal (padrão: @nacoesdabola)
  CHANNEL_ID      opcional; ID UC... do canal, se a descoberta automática falhar
  EMAIL_TO        destinatários separados por vírgula            (Secret)
  SMTP_USER       conta que envia (ex.: um Gmail do projeto)     (Secret)
  SMTP_PASS       senha de app dessa conta                       (Secret)
  SMTP_HOST       padrão smtp.gmail.com
  SMTP_PORT       padrão 465
  PANEL_URL       link do painel (GitHub Pages)
  DRY_RUN=1       gera tudo, mas não envia e-mail
  FIXTURES_DIR    lê XMLs locais em vez da internet (testes)
  OUT_DIR         pasta de saída alternativa (testes)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import collect, config as C, report, score

RAIZ = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("radar")


def _fixtures(pasta: Path) -> dict:
    termos = collect.parse_trends((pasta / "trends.xml").read_text("utf-8")) if (pasta / "trends.xml").exists() else []
    noticias = []
    for f in sorted((pasta / "news").glob("*.xml")):
        noticias += collect.parse_news(f.read_text("utf-8"), f.stem.replace("_", " "))
    videos = collect.parse_channel_feed((pasta / "channel.xml").read_text("utf-8")) if (pasta / "channel.xml").exists() else []
    return {"termos": termos, "noticias": noticias, "videos": videos, "channel_id": "fixture",
            "status": {"Google Trends": len(termos), "Google News": len(noticias), "Canal (RSS YouTube)": len(videos)}}


def main() -> int:
    # OUT_DIR permite rodar testes sem sobrescrever o painel real.
    base = Path(os.environ["OUT_DIR"]) if os.environ.get("OUT_DIR") else RAIZ
    DOCS, DADOS = base / "docs", base / "data"
    HIST = DADOS / "historico.json"
    agora = datetime.fromisoformat(os.environ["AGORA"]) if os.environ.get("AGORA") else datetime.now(timezone.utc)
    fixtures = os.environ.get("FIXTURES_DIR")
    if fixtures:
        bruto = _fixtures(Path(fixtures))
    else:
        bruto = collect.coletar(C.BUSCAS_NEWS, os.environ.get("CHANNEL_HANDLE", "@nacoesdabola"),
                                os.environ.get("CHANNEL_ID") or None)
    log.info("Coleta: %s", bruto["status"])

    if not bruto["termos"] and not bruto["noticias"]:
        log.error("Nenhuma fonte respondeu. Mantendo o painel anterior e encerrando com erro.")
        return 1

    historico = json.loads(HIST.read_text("utf-8")) if HIST.exists() else {}
    temas = score.pontuar(bruto, historico, agora)
    local = agora.astimezone(ZoneInfo("America/Sao_Paulo"))
    dados = {
        "gerado_em": agora.isoformat(),
        "data_br": local.strftime("%d/%m/%Y %H:%M"),
        "status": bruto["status"],
        "canal_id": bruto.get("channel_id"),
        "videos_recentes": bruto["videos"][:10],
        "termos_futebol": [t["termo"] for t in bruto["termos"]
                           if score.eh_futebol(t["termo"] + " " + " ".join(n["titulo"] for n in t["noticias"]))],
        "pesos": C.PESOS,
        "temas": temas[: C.TOP_PAINEL],
    }
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), "utf-8")
    DADOS.mkdir(parents=True, exist_ok=True)
    HIST.write_text(json.dumps(score.atualizar_historico(historico, temas, agora), ensure_ascii=False, indent=1), "utf-8")
    log.info("%d temas pontuados; top: %s", len(temas), temas[0]["tema"] if temas else "-")

    assunto, corpo, texto = report.montar_email(dados, C.TOP_EMAIL, os.environ.get("PANEL_URL"))
    (DADOS / "ultimo-email.html").write_text(corpo, "utf-8")

    if os.environ.get("DRY_RUN") == "1":
        log.info("DRY_RUN: e-mail não enviado. Prévia em data/ultimo-email.html")
        return 0
    para = [e.strip() for e in os.environ.get("EMAIL_TO", "").split(",") if e.strip()]
    if not (para and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS")):
        log.warning("Secrets de e-mail ausentes: painel atualizado, e-mail não enviado.")
        return 0
    try:
        report.enviar(assunto, corpo, texto, host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
                      porta=int(os.environ.get("SMTP_PORT", "465")), usuario=os.environ["SMTP_USER"],
                      senha=os.environ["SMTP_PASS"], para=para)
    except Exception as e:  # noqa: BLE001 - falha de e-mail não pode derrubar o painel
        log.error("Falha ao enviar e-mail: %s", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
