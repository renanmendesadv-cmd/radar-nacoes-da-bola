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

from . import agenda, buscas, collect, config as C, report, score

RAIZ = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("radar")


def _fixtures(pasta: Path) -> dict:
    termos = collect.parse_trends((pasta / "trends.xml").read_text("utf-8")) if (pasta / "trends.xml").exists() else []
    noticias = []
    for f in sorted((pasta / "news").glob("*.xml")):
        noticias += collect.parse_news(f.read_text("utf-8"), f.stem.replace("_", " "))
    videos = collect.parse_channel_feed((pasta / "channel.xml").read_text("utf-8")) if (pasta / "channel.xml").exists() else []
    extra = {}
    if (pasta / "agenda.json").exists():
        extra["eventos"] = json.loads((pasta / "agenda.json").read_text("utf-8"))
    if (pasta / "sugestoes.json").exists():
        extra["sugestoes_fixas"] = json.loads((pasta / "sugestoes.json").read_text("utf-8"))
    return {**extra, "termos": termos, "noticias": noticias, "videos": videos, "channel_id": "fixture",
            "status": {"Google Trends": len(termos), "Google News": len(noticias), "Canal (RSS YouTube)": len(videos)}}


def main() -> int:
    # OUT_DIR permite rodar testes sem sobrescrever o painel real.
    base = Path(os.environ["OUT_DIR"]) if os.environ.get("OUT_DIR") else RAIZ
    DOCS, DADOS = base / "docs", base / "data"
    HIST = DADOS / "historico.json"
    agora = datetime.fromisoformat(os.environ["AGORA"]) if os.environ.get("AGORA") else datetime.now(timezone.utc)
    hoje = agora.astimezone(ZoneInfo("America/Sao_Paulo")).date().isoformat()
    ESTADO = DADOS / "estado.json"
    estado = json.loads(ESTADO.read_text("utf-8")) if ESTADO.exists() else {}
    agendado = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    # Horários reserva: se a execução agendada de hoje já rodou, as seguintes não fazem nada.
    if agendado and estado.get("ultima_agendada") == hoje:
        log.info("A execução agendada de hoje já rodou (%s). Nada a fazer neste horário reserva.", hoje)
        return 0
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

    # Busca do torcedor: 1ª passada acha os temas; depois consultamos o autocompletar do Google
    # para os clubes e para os nomes que mais aparecem nas pautas, e pontuamos de novo.
    temas = score.pontuar(bruto, historico, agora)
    nomes = []
    for t in temas[: C.NOMES_POR_EXECUCAO * 2]:
        n = buscas.nome_chave([m["titulo"] for m in t["manchetes"]] or [t["tema"]])
        if n and n.lower() not in [x.lower() for x in nomes]:
            nomes.append(n)
    sementes = C.BUSCAS_TORCEDOR + nomes[: C.NOMES_POR_EXECUCAO]
    if fixtures:
        bruto["sugestoes"] = {k: v for k, v in bruto.get("sugestoes_fixas", {}).items()}
    else:
        bruto["sugestoes"] = buscas.coletar(sementes)
    bruto["status"]["Buscas do torcedor"] = sum(1 for v in bruto["sugestoes"].values() if v)
    temas = score.pontuar(bruto, historico, agora)

    # Agenda: ESPN + jogos citados nas manchetes.
    eventos = bruto.get("eventos") if fixtures else agenda.coletar_espn()
    bruto["status"]["Agenda (ESPN)"] = len(eventos or [])
    jogos = agenda.montar_agenda(eventos or [], agora)
    titulos = [n["titulo"] for n in bruto["noticias"]]
    jogos["na_midia"] = agenda.sem_repetir(agenda.jogos_na_midia(titulos), jogos)
    local = agora.astimezone(ZoneInfo("America/Sao_Paulo"))
    dados = {
        "gerado_em": agora.isoformat(),
        "data_br": local.strftime("%d/%m/%Y %H:%M"),
        "status": bruto["status"],
        "canal_id": bruto.get("channel_id"),
        "videos_recentes": bruto["videos"][:10],
        "termos_futebol": [t["termo"] for t in bruto["termos"] if score.termo_de_futebol(t)],
        "pesos": C.PESOS,
        "agenda": jogos,
        "buscas_torcedor": {k: buscas.especificas(k, v)[:6] for k, v in bruto["sugestoes"].items()
                            if k in C.BUSCAS_TORCEDOR},
        "temas": temas[: C.TOP_PAINEL],
    }
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), "utf-8")
    DADOS.mkdir(parents=True, exist_ok=True)
    HIST.write_text(json.dumps(score.atualizar_historico(historico, temas, agora), ensure_ascii=False, indent=1), "utf-8")
    log.info("%d temas pontuados; top: %s", len(temas), temas[0]["tema"] if temas else "-")
    if agendado:
        estado["ultima_agendada"] = hoje
    estado["ultima_execucao"] = agora.isoformat()
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), "utf-8")

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
    estado["ultimo_email"] = agora.isoformat()
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
