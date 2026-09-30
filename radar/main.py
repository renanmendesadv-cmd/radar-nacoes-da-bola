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
  YOUTUBE_API_KEY chave da YouTube Data API v3: sinal "Força no YouTube"   (Secret, opcional)
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
                  OAuth só leitura do canal: Raio-X (painel diário,
                  e-mail e ajuste de pesos às segundas)               (Secrets, opcionais)
  RAIOX=1         faz hoje o Raio-X completo de segunda (e-mail + pesos)
  RAIOX_PAINEL=0  não publica o Raio-X no painel (só e-mail)
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

from . import agenda, analytics, buscas, collect, config as C, report, score, tendencias, youtube

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
            "status": {"Google Trends": len(termos), "Google News": len(noticias), "Vídeos do canal": len(videos)}}


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
    local = agora.astimezone(ZoneInfo("America/Sao_Paulo"))
    PESOS_APR = DADOS / "pesos-aprendidos.json"
    aprendidos = json.loads(PESOS_APR.read_text("utf-8")) if PESOS_APR.exists() else {}

    # Raio-X: todo dia atualiza a aba Desempenho do painel. Às segundas (ou com RAIOX=1) também
    # ajusta os pesos das categorias e manda o e-mail. Roda antes das pautas para que os pesos
    # novos já valham no mesmo dia.
    semanal = _dia_de_raiox(local, estado)
    raiox, erro_raiox = _raiox(agora, aprendidos.get("categorias", {}), fixtures)
    if raiox:
        if semanal:
            aprendidos = {"atualizado_em": agora.isoformat(), "base_videos": raiox["n_videos_v7"],
                          "categorias": raiox["fatores_categoria"]}
            DADOS.mkdir(parents=True, exist_ok=True)
            PESOS_APR.write_text(json.dumps(aprendidos, ensure_ascii=False, indent=1), "utf-8")
            estado["ultimo_raiox"] = local.date().isoformat()
        else:
            # Fora da segunda o painel mostra o peso que está valendo, não o que seria calculado hoje.
            raiox["fatores_categoria"] = {k: aprendidos.get("categorias", {}).get(k, 1.0) for k in C.CATEGORIAS}
        raiox["pesos_ajustados_em"] = aprendidos.get("atualizado_em")
        DOCS.mkdir(parents=True, exist_ok=True)
        publico = os.environ.get("RAIOX_PAINEL", "1") != "0"
        (DOCS / "desempenho.json").write_text(json.dumps(raiox if publico else {"oculto": True, "gerado_em": raiox["gerado_em"]},
                                                         ensure_ascii=False, indent=1), "utf-8")
    fatores = aprendidos.get("categorias", {})

    if fixtures:
        bruto = _fixtures(Path(fixtures))
    else:
        bruto = collect.coletar(C.BUSCAS_NEWS, os.environ.get("CHANNEL_HANDLE", "@nacoesdabola"),
                                os.environ.get("CHANNEL_ID") or None, os.environ.get("YOUTUBE_API_KEY") or None)
    log.info("Coleta: %s", bruto["status"])

    if not bruto["termos"] and not bruto["noticias"]:
        log.error("Nenhuma fonte respondeu. Mantendo o painel anterior e encerrando com erro.")
        return 1

    historico = json.loads(HIST.read_text("utf-8")) if HIST.exists() else {}
    bruto["fatores_categoria"] = fatores

    # Busca do torcedor: 1ª passada acha os temas; depois consultamos o autocompletar do Google
    # para os clubes e para os nomes que mais aparecem nas pautas, e pontuamos de novo.
    temas = score.pontuar(bruto, historico, agora)
    nomes = []
    for t in temas[: C.NOMES_POR_EXECUCAO * 2]:
        n = buscas.nome_chave([m["titulo"] for m in t["manchetes"]] or [t["tema"]])
        if n and n.lower() not in [x.lower() for x in nomes]:
            nomes.append(n)
    sementes = C.BUSCAS_TORCEDOR + list(C.SEMENTES_JOGO.values()) + nomes[: C.NOMES_POR_EXECUCAO]
    if fixtures:
        bruto["sugestoes"] = {k: v for k, v in bruto.get("sugestoes_fixas", {}).items()}
    else:
        bruto["sugestoes"] = buscas.coletar(sementes)
    bruto["status"]["Buscas do torcedor"] = sum(1 for v in bruto["sugestoes"].values() if v)
    temas = score.pontuar(bruto, historico, agora)

    # Força no YouTube: vídeos das últimas 48 h sobre as pautas do topo (se houver chave).
    if fixtures and (Path(fixtures) / "youtube.json").exists():
        yt_get = _get_fixture(json.loads((Path(fixtures) / "youtube.json").read_text("utf-8")))
    else:
        yt_get = youtube.requests.get
    bruto["status"]["YouTube (48 h)"] = youtube.enriquecer(
        temas, agora, os.environ.get("YOUTUBE_API_KEY"), estado, DADOS / "youtube-cache.json",
        fatores, bruto.get("channel_id"), get=yt_get)

    # Alertas de tendência: assuntos ligados ao canal bombando no YouTube (views/hora e engajamento).
    alertas = []
    chave_yt = os.environ.get("YOUTUBE_API_KEY")
    if chave_yt:
        try:
            em_alta = youtube.em_alta_esportes(chave_yt, get=yt_get)
        except (youtube.CotaEsgotada, RuntimeError) as e:
            log.warning("YouTube (Em alta): %s", e)
            em_alta = []
        desempenho = raiox
        if desempenho is None and (DOCS / "desempenho.json").exists():
            desempenho = json.loads((DOCS / "desempenho.json").read_text("utf-8"))
        alertas = tendencias.detectar(temas, em_alta, agora, DADOS / "youtube-base.json", estado, desempenho,
                                      bruto.get("channel_id"))
        bruto["status"]["Alertas de tendência"] = len(alertas) or "nenhum hoje"

    # Agenda: ESPN; se ela falhar, as buscas do Google ("palmeiras x ldu"); e os jogos citados nas manchetes.
    eventos = bruto.get("eventos") if fixtures else agenda.coletar_espn()
    bruto["status"]["Agenda (ESPN)"] = len(eventos or [])
    jogos = agenda.montar_agenda(eventos or [], agora)
    titulos = [n["titulo"] for n in bruto["noticias"]]
    jogos["na_midia"] = agenda.sem_repetir(agenda.jogos_na_midia(titulos), jogos)
    jogos["nas_buscas"] = agenda.unir_buscas(agenda.jogos_das_buscas(bruto["sugestoes"], titulos), jogos, eventos)
    bruto["status"]["Agenda (buscas Google)"] = len(jogos["nas_buscas"])
    dados = {
        "gerado_em": agora.isoformat(),
        "data_br": local.strftime("%d/%m/%Y %H:%M"),
        "status": bruto["status"],
        "canal_id": bruto.get("channel_id"),
        "videos_recentes": bruto["videos"][:10],
        "termos_futebol": [t["termo"] for t in bruto["termos"] if score.termo_de_futebol(t)],
        "pesos": C.PESOS,
        "fatores_categoria": fatores,
        "raiox_em": estado.get("ultimo_raiox"),
        "agenda": jogos,
        "buscas_torcedor": {k: buscas.especificas(k, v)[:6] for k, v in bruto["sugestoes"].items()
                            if k in C.BUSCAS_TORCEDOR},
        "alertas": alertas,
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

    painel = os.environ.get("PANEL_URL")
    emails = [report.montar_email(dados, C.TOP_EMAIL, painel)]
    (DADOS / "ultimo-email.html").write_text(emails[0][1], "utf-8")
    if raiox and semanal:
        emails.append(report.montar_email_raiox(raiox, painel))
        (DADOS / "ultimo-raiox.html").write_text(emails[1][1], "utf-8")
    codigo_final = 3 if erro_raiox else 0

    if os.environ.get("DRY_RUN") == "1":
        log.info("DRY_RUN: e-mail não enviado. Prévia em data/ultimo-email.html")
        return codigo_final
    para = [e.strip() for e in os.environ.get("EMAIL_TO", "").split(",") if e.strip()]
    if not (para and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS")):
        log.warning("Secrets de e-mail ausentes: painel atualizado, e-mail não enviado.")
        return codigo_final
    for assunto, corpo, texto in emails:
        try:
            report.enviar(assunto, corpo, texto, host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
                          porta=int(os.environ.get("SMTP_PORT", "465")), usuario=os.environ["SMTP_USER"],
                          senha=os.environ["SMTP_PASS"], para=para)
        except Exception as e:  # noqa: BLE001 - falha de e-mail não pode derrubar o painel
            log.error("Falha ao enviar e-mail: %s", e)
            return 2
    estado["ultimo_email"] = agora.isoformat()
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), "utf-8")
    return codigo_final


def _dia_de_raiox(local: datetime, estado: dict) -> bool:
    if os.environ.get("RAIOX") == "1":
        return True
    return local.weekday() == C.RAIOX_DIA_SEMANA and estado.get("ultimo_raiox") != local.date().isoformat()


def _raiox(agora: datetime, fatores_anteriores: dict, fixtures: str | None) -> tuple[dict | None, str | None]:
    """Devolve (relatório, erro). Sem credenciais: (None, None), o radar diário segue normal."""
    try:
        if fixtures:
            arq = Path(fixtures) / "analytics.json"
            if not arq.exists():
                return None, None
            bruto = json.loads(arq.read_text("utf-8"))
        else:
            cid, sec, ref = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
            if not (cid and sec and ref):
                log.info("Raio-X do canal: credenciais OAuth ausentes; pulando (veja o README).")
                return None, None
            cli = analytics.Cliente(analytics.token_de_acesso(cid, sec, ref))
            bruto = analytics.coletar(cli, agora)
        rel = analytics.analisar(bruto, fatores_anteriores, agora.isoformat())
        log.info("Raio-X: %d vídeos analisados; fatores %s", rel["n_videos_v7"], rel["fatores_categoria"])
        return rel, None
    except Exception as e:  # noqa: BLE001 - o Raio-X nunca derruba as pautas do dia
        log.error("Raio-X do canal falhou: %s", e)
        return None, str(e)


def _get_fixture(respostas: dict):
    """Imita requests.get para a API do YouTube nos testes: responde pela consulta ou pelo recurso."""
    class R:
        def __init__(self, dados):
            self.status_code, self._d, self.text = 200, dados, json.dumps(dados)

        def json(self):
            return self._d

    def get(url, params=None, **_):
        recurso = url.rsplit("/", 1)[-1]
        if recurso == "search":
            return R(respostas["search"].get(params.get("q"), respostas["search"].get("*", {"items": []})))
        return R(respostas[recurso])
    return get


if __name__ == "__main__":
    sys.exit(main())
