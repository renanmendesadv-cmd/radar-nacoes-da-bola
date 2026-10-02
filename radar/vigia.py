"""Vigia de hora em hora: assunto ligado ao canal bombando no YouTube -> aviso no celular e no painel.

Roda pelo .github/workflows/vigia.yml das 8h às 22h (Brasília). Sem busca no YouTube: usa a lista
"Em alta" de Esportes e as estatísticas atuais dos vídeos que o radar da manhã já encontrou
para as pautas do dia (~2 a 6 unidades da cota por conferência).

Além dos critérios dos alertas da manhã, mede quantas views cada vídeo ganhou desde a conferência
anterior (guardada no cache do GitHub Actions, fora do repositório): um vídeo ganhando
config.VIGIA_GANHO_HORA views por hora também dispara.

Arquivos gravados (só quando sai aviso novo):
- docs/alertas.json: avisos das últimas 24 h, lidos pelo painel a cada 5 minutos;
- data/vigia.json: vídeos já avisados e quantos avisos saíram por dia.
O radar da manhã não escreve nesses arquivos e o vigia não escreve nos do radar: os dois
nunca disputam o mesmo arquivo no Git.

Variáveis: YOUTUBE_API_KEY, NTFY_TOPICO (Secret), PANEL_URL, VIGIA_TESTE=1 (só manda a notificação
de teste), VIGIA_FORCAR=1 (roda fora do horário), AGORA, OUT_DIR, VIGIA_CACHE (testes).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import avisos, config as C, tendencias, youtube

log = logging.getLogger("radar")
RAIZ = Path(__file__).resolve().parent.parent
SP = ZoneInfo("America/Sao_Paulo")


def _ler(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text("utf-8")) if caminho.exists() else padrao
    except ValueError:
        return padrao


def _gravar(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1), "utf-8")


def ganho_por_hora(videos: list[dict], foto: dict, agora: datetime) -> dict:
    """Marca em cada vídeo as views ganhas por hora desde a conferência anterior e devolve a nova foto.

    Só compara com fotos de 15 min a 3 h atrás: intervalo curto demais exagera, longo demais dilui."""
    nova = {}
    for v in videos:
        ant = foto.get(v["id"])
        if ant:
            horas = (agora - datetime.fromisoformat(ant["em"])).total_seconds() / 3600
            if 0.25 <= horas <= 3 and v["views"] >= ant["views"]:
                v["ganho_hora"] = round((v["views"] - ant["views"]) / horas)
        nova[v["id"]] = {"views": v["views"], "em": agora.isoformat()}
    # Fotos de vídeos que sumiram das listas ficam por 1 dia (podem voltar ao "Em alta").
    limite = (agora - timedelta(days=1)).isoformat()
    for k, x in foto.items():
        if k not in nova and x.get("em", "") >= limite:
            nova[k] = x
    return nova


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    base = Path(os.environ["OUT_DIR"]) if os.environ.get("OUT_DIR") else RAIZ
    DOCS, DADOS = base / "docs", base / "data"
    CACHE = Path(os.environ.get("VIGIA_CACHE") or (RAIZ / ".vigia" / "fotos.json"))
    agora = datetime.fromisoformat(os.environ["AGORA"]) if os.environ.get("AGORA") else datetime.now(timezone.utc)
    local = agora.astimezone(SP)
    hoje = local.date().isoformat()
    painel = os.environ.get("PANEL_URL")
    topico = (os.environ.get("NTFY_TOPICO") or "").strip()
    servidor = os.environ.get("NTFY_SERVIDOR") or C.NTFY_SERVIDOR

    if os.environ.get("VIGIA_TESTE"):
        if not topico:
            log.error("Secret NTFY_TOPICO não cadastrado: cadastre em Settings > Secrets and variables > Actions.")
            return 2
        ok = avisos.teste(topico, painel, servidor)
        log.info("Notificação de teste %s.", "enviada" if ok else "NÃO enviada")
        return 0 if ok else 2

    if not (C.VIGIA_HORA_INICIO <= local.hour <= C.VIGIA_HORA_FIM) and not os.environ.get("VIGIA_FORCAR"):
        log.info("Fora do horário do vigia (%dh às %dh). Nada a fazer.", C.VIGIA_HORA_INICIO, C.VIGIA_HORA_FIM)
        return 0
    chave = os.environ.get("YOUTUBE_API_KEY")
    if not chave:
        log.info("YOUTUBE_API_KEY ausente: vigia desligado.")
        return 0

    dados = _ler(DOCS / "data.json", {})
    do_dia = bool(dados.get("gerado_em")) and datetime.fromisoformat(dados["gerado_em"]).astimezone(SP).date().isoformat() == hoje
    temas = dados.get("temas", []) if do_dia else []  # pautas de ontem não servem de referência
    vig = _ler(DADOS / "vigia.json", {})
    enviados = vig.get("enviados", {})
    avisos_manha = len(dados.get("alertas") or []) if do_dia else 0
    restam = C.VIGIA_MAX_AVISOS_DIA - avisos_manha - enviados.get(hoje, 0)
    if restam <= 0:
        log.info("Limite de %d avisos por dia já atingido.", C.VIGIA_MAX_AVISOS_DIA)
        return 0

    get = _GET_TESTE or youtube.requests.get
    ids = [v["id"] for t in temas for v in (t.get("youtube") or {}).get("amostra", [])]
    try:
        frescos = youtube.videos_por_id(ids, chave, get=get) if ids else {}
        em_alta = youtube.em_alta_esportes(chave, get=get)
    except youtube.CotaEsgotada:
        log.warning("Cota diária do YouTube esgotada: o vigia volta amanhã.")
        return 0
    except RuntimeError as e:
        log.warning("YouTube: %s", e)
        return 0

    # Atualiza a amostra das pautas com os números de agora e mede o ganho desde a última conferência.
    for t in temas:
        y = t.get("youtube") or {}
        if y.get("amostra"):
            y["amostra"] = [dict(v, **{k: frescos[v["id"]][k] for k in ("views", "likes", "comentarios")})
                            if v["id"] in frescos else v for v in y["amostra"]]
    todos = [v for t in temas for v in (t.get("youtube") or {}).get("amostra", [])] + em_alta
    foto = ganho_por_hora(todos, _ler(CACHE, {}), agora)
    _gravar(CACHE, foto)

    estado = _ler(DADOS / "estado.json", {})
    limite_dias = (agora.date() - timedelta(days=C.ALERTA_REPETIR_APOS_DIAS)).isoformat()
    proprios = {k: d for k, d in (vig.get("avisados") or {}).items() if d >= limite_dias}
    est = {"alertas": dict(proprios)}
    desempenho = _ler(DOCS / "desempenho.json", None)
    alertas = tendencias.detectar(temas, em_alta, agora, DADOS / "youtube-base.json", est, desempenho,
                                  dados.get("canal_id"), gravar_base=False,
                                  avisados_extra=estado.get("alertas") or {}, limite=restam)
    if not alertas:
        log.info("Nenhum assunto novo bombando nesta conferência.")
        return 0

    avisos.anexar_gancho(alertas, temas, hoje)
    codigo = 0
    for a in alertas:
        a["avisado_em"] = agora.isoformat()
        a["pelo_vigia"] = True
        if topico:
            a["celular"] = avisos.enviar(avisos.mensagem(a, painel), topico, servidor)
            if not a["celular"]:
                codigo = 2
        else:
            log.info("NTFY_TOPICO não cadastrado: alerta só no painel.")
        log.info("Alerta: %s (%sx, ganho/h %s)", a["tema"], a["velocidade"], a.get("ganho_hora"))

    # Grava só quando há aviso novo (o painel e o Git não mudam nas conferências sem novidade).
    enviados = {d: n for d, n in enviados.items() if d >= limite_dias}
    enviados[hoje] = enviados.get(hoje, 0) + len(alertas)
    _gravar(DADOS / "vigia.json", {"avisados": est["alertas"], "enviados": enviados})
    corte = (agora - timedelta(hours=24)).isoformat()
    antigos = [a for a in _ler(DOCS / "alertas.json", {}).get("alertas", []) if a.get("avisado_em", "") >= corte]
    _gravar(DOCS / "alertas.json", {"atualizado_em": agora.isoformat(), "alertas": alertas + antigos})
    return codigo


_GET_TESTE = None  # os testes trocam por uma função que lê fixtures


if __name__ == "__main__":
    if os.environ.get("FIXTURES_DIR"):
        from .main import _get_fixture
        f = Path(os.environ["FIXTURES_DIR"]) / "youtube.json"
        _GET_TESTE = _get_fixture(json.loads(f.read_text("utf-8")))
    sys.exit(main())
