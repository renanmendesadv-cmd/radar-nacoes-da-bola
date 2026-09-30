"""Raio-X semanal do canal: o que rende no próprio canal (YouTube Analytics API, só leitura).

Credenciais (Secrets do GitHub), criadas uma vez pelo dono do canal:
  YT_CLIENT_ID, YT_CLIENT_SECRET  cliente OAuth do Google Cloud (app em "Em produção")
  YT_REFRESH_TOKEN                gerado no login único, com os escopos só de leitura abaixo

Sem essas credenciais o Raio-X é pulado e o radar diário segue igual.

O que sai daqui:
- formatos que rendem (Shorts, vídeos longos, lives);
- temas que rendem, usando as mesmas categorias do radar;
- retenção: onde o público sai dos vídeos longos e lives;
- origens de tráfego; melhor dia e horário de publicação; vídeos que trouxeram inscritos;
- fatores por categoria, que ajustam automaticamente a nota das pautas do radar.

Para comparar vídeos de idades diferentes de forma justa, a métrica principal é
"views nos 7 primeiros dias" (V7) de cada vídeo.
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from . import config as C
from .score import categoria, entidades, norm

log = logging.getLogger("radar")

ESCOPOS = ["https://www.googleapis.com/auth/yt-analytics.readonly",
           "https://www.googleapis.com/auth/youtube.readonly"]
# Opcional: receita real (RPM, CPM, receita por vídeo). Só funciona se o dono do canal autorizar
# também este escopo; sem ele, o radar segue com o RPM de referência.
ESCOPO_RECEITA = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DATA = "https://www.googleapis.com/youtube/v3"
REPORTS = "https://youtubeanalytics.googleapis.com/v2/reports"
BR = ZoneInfo("America/Sao_Paulo")

ORIGENS = {
    "YT_SEARCH": "Busca do YouTube", "RELATED_VIDEO": "Vídeos sugeridos", "SUGGESTED": "Vídeos sugeridos",
    "SUBSCRIBER": "Página inicial e inscrições", "BROWSE": "Página inicial e inscrições",
    "SHORTS": "Feed de Shorts", "EXT_URL": "Sites e apps externos", "NOTIFICATION": "Notificações",
    "NO_LINK_OTHER": "Acesso direto ou desconhecido", "PLAYLIST": "Playlists", "YT_CHANNEL": "Página do canal",
    "CHANNEL": "Página do canal", "YT_OTHER_PAGE": "Outras páginas do YouTube", "END_SCREEN": "Tela final",
    "ANNOTATION": "Cards e anotações", "CAMPAIGN_CARD": "Cards e anotações", "HASHTAGS": "Hashtags",
    "LIVE_REDIRECT": "Redirecionamento de live", "SOUND_PAGE": "Página de som", "VIDEO_REMIXES": "Remixes",
    "ADVERTISING": "Anúncios", "PRODUCT_PAGE": "Página de produto", "SHORTS_CONTENT_LINKS": "Links em Shorts",
    "IMMERSIVE_LIVE": "Live imersiva", "NO_LINK_EMBEDDED": "Vídeo incorporado em sites",
}
FORMATOS = {"shorts": "Shorts", "videoOnDemand": "Vídeos longos", "liveStream": "Lives"}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
FAIXAS = [(0, 6, "madrugada (0h–6h)"), (6, 12, "manhã (6h–12h)"), (12, 18, "tarde (12h–18h)"),
          (18, 24, "noite (18h–24h)")]


class ErroAnalytics(Exception):
    pass


# ---------------------------------------------------------------- acesso (rede)

def token_de_acesso(client_id: str, client_secret: str, refresh_token: str, post=requests.post) -> str:
    try:
        r = post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret,
                                  "refresh_token": refresh_token, "grant_type": "refresh_token"}, timeout=20)
    except requests.RequestException as e:
        raise ErroAnalytics(f"falha de rede ao renovar o acesso ({type(e).__name__})") from None
    if r.status_code != 200:
        try:
            erro = r.json().get("error", "")
        except ValueError:
            erro = ""
        dica = (" O login expirou ou foi revogado: gere um novo YT_REFRESH_TOKEN (README, seção Raio-X)."
                if erro == "invalid_grant" else "")
        raise ErroAnalytics(f"Google recusou a renovação do acesso (HTTP {r.status_code} {erro}).{dica}")
    return r.json()["access_token"]


class Cliente:
    def __init__(self, token: str, get=requests.get):
        self.h = {"Authorization": f"Bearer {token}"}
        self.get = get

    def _pedir(self, url: str, params: dict) -> dict:
        try:
            r = self.get(url, params=params, headers=self.h, timeout=30)
        except requests.RequestException as e:
            raise ErroAnalytics(f"falha de rede ({type(e).__name__})") from None
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", "")
            except ValueError:
                msg = r.text[:160]
            raise ErroAnalytics(f"HTTP {r.status_code}: {msg[:200]}")
        return r.json()

    def dados(self, recurso: str, **params) -> dict:
        return self._pedir(f"{DATA}/{recurso}", params)

    def relatorio(self, inicio: date, fim: date, metrics: str, **extra) -> list[dict]:
        res = self._pedir(REPORTS, {"ids": "channel==MINE", "startDate": inicio.isoformat(),
                                    "endDate": fim.isoformat(), "metrics": metrics, **extra})
        nomes = [c["name"] for c in res.get("columnHeaders", [])]
        return [dict(zip(nomes, linha)) for linha in res.get("rows", []) or []]


def _duracao_s(iso: str) -> int:
    """'PT1H2M3S' -> 3723."""
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def coletar(cli: Cliente, agora: datetime) -> dict:
    """Busca tudo o que o Raio-X precisa. ~50 chamadas, bem abaixo da cota gratuita."""
    hoje = agora.astimezone(BR).date()
    fim = hoje - timedelta(days=3)  # o Analytics leva 2 a 3 dias para fechar os números
    ini28 = fim - timedelta(days=27)
    ini_janela = fim - timedelta(days=C.RAIOX_DIAS - 1)

    canal = (cli.dados("channels", part="snippet,contentDetails,statistics", mine="true").get("items") or [None])[0]
    if not canal:
        raise ErroAnalytics("a conta autorizada não tem canal no YouTube (no login, escolha a conta do canal)")
    uploads = canal["contentDetails"]["relatedPlaylists"]["uploads"]

    ids, pagina = [], None
    limite = datetime.combine(ini_janela, datetime.min.time(), BR)
    for _ in range(6):
        p = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
        if pagina:
            p["pageToken"] = pagina
        res = cli.dados("playlistItems", **p)
        velhos = False
        for it in res.get("items", []):
            pub = it["contentDetails"].get("videoPublishedAt")
            if pub and datetime.fromisoformat(pub.replace("Z", "+00:00")) < limite:
                velhos = True
                continue
            ids.append(it["contentDetails"]["videoId"])
        pagina = res.get("nextPageToken")
        if velhos or not pagina:
            break

    videos = []
    for i in range(0, len(ids), 50):
        res = cli.dados("videos", part="snippet,contentDetails,statistics,liveStreamingDetails,status",
                        id=",".join(ids[i:i + 50]))
        for v in res.get("items", []):
            videos.append({
                "id": v["id"], "titulo": v["snippet"]["title"], "publicado": v["snippet"]["publishedAt"],
                "duracao_s": _duracao_s(v["contentDetails"].get("duration")),
                "live": "liveStreamingDetails" in v,
                "views_total": int(v.get("statistics", {}).get("viewCount", 0) or 0),
                "privacidade": (v.get("status") or {}).get("privacyStatus", "public"),
            })

    bruto = {"canal": {"id": canal["id"], "nome": canal["snippet"]["title"],
                       "inscritos": int(canal.get("statistics", {}).get("subscriberCount", 0) or 0)},
             "periodo": {"inicio": ini28.isoformat(), "fim": fim.isoformat(), "janela_inicio": ini_janela.isoformat()},
             "videos": videos}

    metr = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained"
    bruto["por_video"] = cli.relatorio(ini_janela, fim, metr, dimensions="video", sort="-views", maxResults=200)
    bruto["trafego"] = cli.relatorio(ini28, fim, "views,estimatedMinutesWatched",
                                     dimensions="insightTrafficSourceType", sort="-views")
    try:
        bruto["formatos"] = cli.relatorio(ini28, fim, "views,estimatedMinutesWatched,subscribersGained,averageViewDuration",
                                          dimensions="creatorContentType")
    except ErroAnalytics as e:  # dimensão nova: se a API recusar, o radar classifica pela duração
        log.info("Analytics sem creatorContentType (%s); formatos pela duração do vídeo.", e)
        bruto["formatos"] = None
    # Monetização: views por dia (tendência), horas assistidas em 12 meses e views de Shorts em 90 dias.
    bruto["dias28"] = cli.relatorio(ini28, fim, "views,estimatedMinutesWatched", dimensions="day", sort="day")
    # Requisitos do Programa de Parcerias: horas públicas de 12 meses, vídeo a vídeo (só vídeos que
    # continuam públicos e não são Shorts contam), e a curva diária de 365 dias (janela móvel).
    ini365 = fim - timedelta(days=364)
    bruto["dias365"] = cli.relatorio(ini365, fim, "estimatedMinutesWatched,views", dimensions="day", sort="day")
    bruto["min_video_12m"] = cli.relatorio(ini365, fim, "estimatedMinutesWatched,views", dimensions="video",
                                           sort="-estimatedMinutesWatched", maxResults=200)
    ids12 = [r["video"] for r in bruto["min_video_12m"]]
    status12 = {}
    for i in range(0, len(ids12), 50):
        res = cli.dados("videos", part="status,contentDetails,liveStreamingDetails", id=",".join(ids12[i:i + 50]))
        for v in res.get("items", []):
            status12[v["id"]] = {"privacidade": (v.get("status") or {}).get("privacyStatus", "public"),
                                 "duracao_s": _duracao_s((v.get("contentDetails") or {}).get("duration")),
                                 "live": "liveStreamingDetails" in v}
    bruto["status_video_12m"] = status12
    # Último envio público (atividade: canais parados por 6 meses podem perder a monetização).
    bruto["ultimo_envio"] = max((v["publicado"] for v in videos if v.get("privacidade", "public") == "public"), default=None)
    try:
        bruto["ano_formatos"] = cli.relatorio(fim - timedelta(days=364), fim, "views,estimatedMinutesWatched",
                                              dimensions="creatorContentType")
        bruto["shorts90"] = cli.relatorio(fim - timedelta(days=89), fim, "views", dimensions="creatorContentType")
    except ErroAnalytics as e:
        log.info("Analytics sem creatorContentType para 12 meses (%s); horas estimadas no total.", e)
        bruto["ano_formatos"] = None
        bruto["ano_total"] = cli.relatorio(fim - timedelta(days=364), fim, "views,estimatedMinutesWatched")
    sem_ini = fim - timedelta(days=6)
    bruto["semana"] = cli.relatorio(sem_ini, fim, "views,estimatedMinutesWatched,subscribersGained,subscribersLost")
    bruto["semana_anterior"] = cli.relatorio(sem_ini - timedelta(days=7), sem_ini - timedelta(days=1),
                                             "views,estimatedMinutesWatched,subscribersGained,subscribersLost")

    # V7: views nos 7 primeiros dias de cada vídeo com pelo menos 7 dias fechados.
    v7 = {}
    elegiveis = [v for v in videos
                 if datetime.fromisoformat(v["publicado"].replace("Z", "+00:00")).astimezone(BR).date()
                 <= fim - timedelta(days=6)][: C.RAIOX_MAX_VIDEOS]
    for v in elegiveis:
        d0 = datetime.fromisoformat(v["publicado"].replace("Z", "+00:00")).astimezone(BR).date()
        linhas = cli.relatorio(d0, d0 + timedelta(days=6), "views,subscribersGained,averageViewPercentage",
                               filters=f"video=={v['id']}")
        if linhas:
            v7[v["id"]] = linhas[0]
    bruto["v7"] = v7

    # Retenção dos vídeos longos/lives mais vistos no período.
    por_id = {v["id"]: v for v in videos}
    longos = [p["video"] for p in bruto["por_video"]
              if p["video"] in por_id and (por_id[p["video"]]["live"] or por_id[p["video"]]["duracao_s"] > 180)][:5]
    ret = {}
    for vid in longos:
        d0 = datetime.fromisoformat(por_id[vid]["publicado"].replace("Z", "+00:00")).astimezone(BR).date()
        try:
            ret[vid] = cli.relatorio(max(d0, ini_janela), fim, "audienceWatchRatio",
                                     dimensions="elapsedVideoTimeRatio", filters=f"video=={vid}")
        except ErroAnalytics as e:
            log.info("Retenção indisponível para %s: %s", vid, e)
    bruto["retencao"] = ret
    # Perfil do público (para patrocinadores). Só vai no e-mail, nunca no painel público.
    publico = {}
    for nome, metr, extra in [
        ("idade_genero", "viewerPercentage", {"dimensions": "ageGroup,gender"}),
        ("paises", "views,estimatedMinutesWatched", {"dimensions": "country", "sort": "-views", "maxResults": 10}),
        ("aparelhos", "views,estimatedMinutesWatched", {"dimensions": "deviceType", "sort": "-views"}),
        ("inscritos_x_nao", "views,estimatedMinutesWatched", {"dimensions": "subscribedStatus"}),
    ]:
        try:
            publico[nome] = cli.relatorio(fim - timedelta(days=89), fim, metr, **extra)
        except ErroAnalytics as e:
            log.info("Analytics sem %s (%s).", nome, e)
    bruto["publico"] = publico

    # Receita real: precisa do escopo yt-analytics-monetary.readonly. Sem ele o YouTube responde 403.
    metr_rec = "estimatedRevenue,estimatedAdRevenue,cpm,playbackBasedCpm,adImpressions,monetizedPlaybacks"
    try:
        bruto["receita"] = {
            "total": cli.relatorio(ini28, fim, metr_rec + ",views", currency="BRL"),
            "por_video": cli.relatorio(ini28, fim, "estimatedRevenue,views", dimensions="video",
                                       sort="-estimatedRevenue", maxResults=50, currency="BRL"),
            "mes_anterior": cli.relatorio(ini28 - timedelta(days=28), ini28 - timedelta(days=1),
                                          "estimatedRevenue,views", currency="BRL"),
        }
    except ErroAnalytics as e:
        bruto["receita"] = None
        log.info("Receita real indisponível (%s). Usando RPM de referência.",
                 "falta autorizar o escopo de receita" if "403" in str(e) else e)
    return bruto


# ---------------------------------------------------------------- análise (sem rede)

CONFRONTO = __import__("re").compile(r"^[a-z0-9 .'-]{2,40}\s+x\s+[a-z0-9 .'-]{2,40}(\s+-\s+.*)?$")


def tipo_do_video(titulo: str) -> str:
    """"BOCA JUNIORS X SÃO PAULO - JOGO DE IDA" -> Transmissão de jogo; "SAI PRO JOGO #215" -> programa."""
    import re
    n = " ".join(norm(titulo.replace("#", " ")).split())
    for nome, chaves in C.TIPOS_CONTEUDO:
        for k in chaves:
            if k == "confronto":
                if "/" not in titulo and CONFRONTO.match(n):
                    return nome
            elif k == "multitemas":
                if titulo.count("/") >= 2:
                    return nome
            elif re.search(r"(?<![a-z0-9])" + re.escape(k), n):
                return nome
    return "Outros"


def formato_do_video(v: dict) -> str:
    if v.get("live"):
        return "Lives"
    # O YouTube aceita Shorts de até 3 min; sem a proporção da tela, a duração é a melhor pista.
    return "Shorts" if 0 < v.get("duracao_s", 0) <= 180 else "Vídeos longos"


def _mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _mediana(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def _variacao(atual: float, antes: float) -> float | None:
    return round(100 * (atual - antes) / antes, 1) if antes else None


def analisar_retencao(pontos: list[dict], duracao_s: int) -> dict | None:
    """pontos: [{"elapsedVideoTimeRatio": 0.01, "audienceWatchRatio": 1.2}, ...]"""
    pts = sorted((float(p["elapsedVideoTimeRatio"]), float(p["audienceWatchRatio"])) for p in pontos)
    if len(pts) < 5 or not duracao_s:
        return None
    # A curva pode passar de 1 no começo (gente voltando trechos); normalizamos pelo 1º ponto.
    base = pts[0][1] or 1.0
    curva = [(x, min(1.0, y / base)) for x, y in pts]
    metade = next((x for x, y in curva if y < 0.5), None)
    def em(seg):
        alvo = seg / duracao_s
        return min(curva, key=lambda p: abs(p[0] - alvo))[1]
    # Maior queda depois da abertura (a saída dos primeiros 30 s já aparece em "fica_30s"),
    # medida pela inclinação (pontos perdidos por trecho do vídeo) e sem os 10% finais,
    # onde a saída é natural (tela final).
    abertura = min(0.5, 30 / duracao_s)
    trechos = [(curva[i][1] - curva[i + 1][1], curva[i][0], curva[i + 1][0]) for i in range(len(curva) - 1)
               if curva[i][0] >= abertura and curva[i][0] < 0.9 and curva[i + 1][0] > curva[i][0]]
    maior = max(trechos, key=lambda t: t[0] / (t[2] - t[1]), default=(0, 0, 0))
    return {
        # O YouTube mede a curva a cada ~1% do vídeo: numa live de 2 h isso dá 1 min e pouco,
        # e "quanto fica após 30 s" não pode ser medido com essa precisão.
        "fica_30s": round(100 * em(30)) if duracao_s > 60 and pts[0][0] * duracao_s <= 30 else None,
        "metade_sai_em": _mmss(metade * duracao_s) if metade is not None else None,
        "metade_sai_pct": round(100 * metade) if metade is not None else None,
        "maior_queda": {"de": _mmss(maior[1] * duracao_s), "ate": _mmss(maior[2] * duracao_s),
                        "pontos": round(100 * maior[0])} if maior[0] > 0 else None,
        "chega_ao_fim": round(100 * curva[-1][1]),
    }


def _fatores(grupos: dict[str, list[float]], mediana_geral: float, anteriores: dict) -> dict:
    """Fator por categoria: raiz do índice de desempenho, limitado e suavizado com a semana anterior."""
    fatores = {}
    for cat in C.CATEGORIAS:
        vals = grupos.get(cat, [])
        antigo = anteriores.get(cat, 1.0)
        if len(vals) < C.RAIOX_MIN_VIDEOS_CATEGORIA or not mediana_geral:
            fatores[cat] = round(antigo, 3)
            continue
        indice = _mediana(vals) / mediana_geral
        novo = max(C.FATOR_CATEGORIA_MIN, min(C.FATOR_CATEGORIA_MAX, indice ** 0.5))
        fatores[cat] = round(0.5 * antigo + 0.5 * novo, 3)  # muda aos poucos, semana a semana
    return fatores


def analisar(bruto: dict, fatores_anteriores: dict | None = None, gerado_em: str | None = None,
             alcance_hist: dict | None = None, alcance_erro: str | None = None) -> dict:
    videos = {v["id"]: dict(v) for v in bruto["videos"]}
    for vid, v in videos.items():
        v["formato"] = formato_do_video(v)
        v["tipo"] = tipo_do_video(v["titulo"])
        v["categoria"] = categoria(v["titulo"])
        if v["categoria"] == "Notícia do dia" and v["tipo"] in C.TIPOS_DE_JOGO:
            v["categoria"] = "Jogo e resultado"
        e = entidades(v["titulo"])
        v["clubes"] = e["foco"] + e["br"]
        pub = datetime.fromisoformat(v["publicado"].replace("Z", "+00:00")).astimezone(BR)
        v["dia_semana"], v["hora"] = pub.weekday(), pub.hour
        v["publicado_br"] = pub.strftime("%d/%m %H:%M")
        v["url"] = f"https://www.youtube.com/watch?v={vid}"
        l7 = bruto.get("v7", {}).get(vid)
        v["v7"] = int(l7["views"]) if l7 else None
        v["inscritos7"] = int(l7.get("subscribersGained", 0)) if l7 else None
    for p in bruto.get("por_video", []):
        if p["video"] in videos:
            videos[p["video"]].update({"views_periodo": int(p["views"]), "inscritos_periodo": int(p["subscribersGained"]),
                                       "pct_assistido": round(float(p["averageViewPercentage"]), 1),
                                       "duracao_media_s": int(p["averageViewDuration"])})
    com_v7 = [v for v in videos.values() if v["v7"] is not None]
    mediana_geral = _mediana([v["v7"] for v in com_v7])

    # Formatos
    por_fmt = defaultdict(list)
    for v in com_v7:
        por_fmt[v["formato"]].append(v)
    total_fmt = {}
    if bruto.get("formatos"):
        soma = sum(float(f["views"]) for f in bruto["formatos"]) or 1
        for f in bruto["formatos"]:
            nome = FORMATOS.get(f["creatorContentType"])
            if nome:
                total_fmt[nome] = {"views": int(f["views"]), "pct_views": round(100 * float(f["views"]) / soma, 1),
                                   "inscritos": int(f["subscribersGained"]),
                                   "minutos": int(float(f["estimatedMinutesWatched"]))}
    else:
        soma = sum(v.get("views_periodo", 0) for v in videos.values()) or 1
        for v in videos.values():
            t = total_fmt.setdefault(v["formato"], {"views": 0, "pct_views": 0, "inscritos": 0, "minutos": None})
            t["views"] += v.get("views_periodo", 0)
            t["inscritos"] += v.get("inscritos_periodo", 0)
        for t in total_fmt.values():
            t["pct_views"] = round(100 * t["views"] / soma, 1)
    formatos = []
    for nome in ["Shorts", "Vídeos longos", "Lives"]:
        vs = por_fmt.get(nome, [])
        if not vs and nome not in total_fmt:
            continue
        pct = [v["pct_assistido"] for v in vs if v.get("pct_assistido") is not None]
        formatos.append({"formato": nome, "n_videos": len(vs), "mediana_v7": round(_mediana([v["v7"] for v in vs])),
                         "indice": round(_mediana([v["v7"] for v in vs]) / mediana_geral, 2) if vs and mediana_geral else None,
                         "pct_assistido": round(_mediana(pct), 1) if pct else None, **total_fmt.get(nome, {})})

    # Temas (mesmas categorias do radar), tipos de conteúdo e clubes
    por_cat, por_clube, por_tipo = defaultdict(list), defaultdict(list), defaultdict(list)
    for v in com_v7:
        por_cat[v["categoria"]].append(v["v7"])
        por_tipo[v["tipo"]].append(v)
        for c in v["clubes"] or ["Sem clube"]:
            por_clube[c].append(v["v7"])
    def ranking(g):
        return sorted(({"nome": k, "n_videos": len(x), "mediana_v7": round(_mediana(x)),
                        "indice": round(_mediana(x) / mediana_geral, 2) if mediana_geral else None}
                       for k, x in g.items() if len(x) >= C.RAIOX_MIN_VIDEOS_CATEGORIA),
                      key=lambda r: -(r["indice"] or 0))
    temas = ranking(por_cat)
    tipos = sorted(({"nome": k, "n_videos": len(vs), "mediana_v7": round(_mediana([v["v7"] for v in vs])),
                     "indice": round(_mediana([v["v7"] for v in vs]) / mediana_geral, 2) if mediana_geral else None,
                     "inscritos7": sum(v["inscritos7"] or 0 for v in vs),
                     "exemplo": vs[0]["titulo"]}
                    for k, vs in por_tipo.items()), key=lambda r: -(r["indice"] or 0))
    clubes = ranking(por_clube)
    fatores = _fatores(por_cat, mediana_geral, fatores_anteriores or {})

    # Retenção
    retencao = []
    for vid, pts in (bruto.get("retencao") or {}).items():
        v = videos.get(vid)
        r = analisar_retencao(pts, v["duracao_s"]) if v else None
        if r:
            retencao.append({"titulo": v["titulo"], "url": v["url"], "formato": v["formato"],
                             "duracao": _mmss(v["duracao_s"]), "pct_assistido": v.get("pct_assistido"), **r})

    # Tráfego
    trafego_soma = defaultdict(int)
    for t in bruto.get("trafego", []):
        trafego_soma[ORIGENS.get(t["insightTrafficSourceType"], t["insightTrafficSourceType"].title())] += int(t["views"])
    tot = sum(trafego_soma.values()) or 1
    trafego = [{"origem": k, "views": q, "pct": round(100 * q / tot, 1)}
               for k, q in sorted(trafego_soma.items(), key=lambda kv: -kv[1])][:8]

    # Melhor dia e horário (mediana de V7 por grupo, mínimo 2 vídeos)
    def melhor(chave_fn, nomes_fn):
        g = defaultdict(list)
        for v in com_v7:
            g[chave_fn(v)].append(v["v7"])
        linhas = [{"quando": nomes_fn(k), "n_videos": len(x), "mediana_v7": round(_mediana(x)),
                   "indice": round(_mediana(x) / mediana_geral, 2) if mediana_geral else None}
                  for k, x in g.items() if len(x) >= C.RAIOX_MIN_VIDEOS_CATEGORIA]
        return sorted(linhas, key=lambda r: -(r["indice"] or 0))
    faixa = lambda h: next(n for a, b, n in FAIXAS if a <= h < b)  # noqa: E731
    dias = melhor(lambda v: v["dia_semana"], lambda k: DIAS[k])
    horarios = melhor(lambda v: faixa(v["hora"]), lambda k: k)

    inscritos = sorted((v for v in videos.values() if v.get("inscritos_periodo")),
                       key=lambda v: -v["inscritos_periodo"])[:5]
    inscritos = [{"titulo": v["titulo"], "url": v["url"], "formato": v["formato"], "inscritos": v["inscritos_periodo"],
                  "views": v.get("views_periodo", 0)} for v in inscritos]

    def soma(linhas, k):
        return int(float(linhas[0][k])) if linhas else 0
    s, a = bruto.get("semana", []), bruto.get("semana_anterior", [])
    resumo = {k: {"atual": soma(s, m), "anterior": soma(a, m), "variacao": _variacao(soma(s, m), soma(a, m))}
              for k, m in [("views", "views"), ("minutos", "estimatedMinutesWatched"),
                           ("inscritos_ganhos", "subscribersGained"), ("inscritos_perdidos", "subscribersLost")]}

    top_v7 = sorted(com_v7, key=lambda v: -v["v7"])[:5]
    rel = {
        "gerado_em": gerado_em, "canal": bruto["canal"], "periodo": bruto["periodo"],
        "n_videos": len(videos), "n_videos_v7": len(com_v7), "mediana_v7": round(mediana_geral),
        "resumo_semana": resumo, "formatos": formatos, "tipos": tipos, "temas": temas, "clubes": clubes[:8],
        "retencao": retencao, "trafego": trafego, "melhores_dias": dias, "melhores_horarios": horarios,
        "videos_inscritos": inscritos,
        "top_v7": [{"titulo": v["titulo"], "url": v["url"], "formato": v["formato"], "categoria": v["categoria"],
                    "v7": v["v7"], "publicado": v["publicado_br"]} for v in top_v7],
        "fatores_categoria": fatores,
    }
    rel["publico"] = resumo_publico(bruto.get("publico") or {})
    if alcance_hist is not None:
        from . import alcance
        rel["alcance"] = alcance.resumo(alcance_hist, videos, bruto["periodo"]["fim"], tipo_do_video, lambda v: v["formato"])
    elif alcance_erro:
        rel["alcance"] = {"erro": alcance_erro}
    rel["monetizacao"] = monetizacao(bruto, rel, videos)
    rel["requisitos"] = requisitos(bruto, rel, videos)
    if rel["requisitos"].get("horas_publicas") is not None:
        rel["monetizacao"]["elegibilidade"]["horas_12m"] = rel["requisitos"]["horas_publicas"]
    rel["recomendacoes"] = recomendacoes(rel)
    return rel


def _tendencia(dias: list[dict]) -> float:
    """Variação esperada para os próximos 30 dias, pela reta das views diárias (limitada a ±30%)."""
    ys = [float(d["views"]) for d in dias]
    if len(ys) < 14 or not sum(ys):
        return 0.0
    n = len(ys)
    xm, ym = (n - 1) / 2, sum(ys) / n
    inclinacao = sum((i - xm) * (y - ym) for i, y in enumerate(ys)) / sum((i - xm) ** 2 for i in range(n))
    # Diferença entre o meio dos próximos 30 dias e a média atual, em proporção da média.
    variacao = inclinacao * ((n - 1) - xm + 15.5) / ym if ym else 0.0
    return max(-0.3, min(0.3, variacao))


IDADES = {"age13-17": "13–17", "age18-24": "18–24", "age25-34": "25–34", "age35-44": "35–44",
          "age45-54": "45–54", "age55-64": "55–64", "age65-": "65+"}
GENEROS = {"male": "homens", "female": "mulheres", "user_specified": "outro"}
APARELHOS = {"MOBILE": "celular", "DESKTOP": "computador", "TV": "TV", "TABLET": "tablet", "GAME_CONSOLE": "videogame"}


def resumo_publico(p: dict) -> dict:
    """Perfil do público dos últimos 90 dias: idade, gênero, países, aparelhos, inscritos."""
    out = {}
    ig = p.get("idade_genero") or []
    if ig:
        idades, generos = defaultdict(float), defaultdict(float)
        for r in ig:
            idades[IDADES.get(r["ageGroup"], r["ageGroup"])] += float(r["viewerPercentage"])
            generos[GENEROS.get(r["gender"], r["gender"])] += float(r["viewerPercentage"])
        out["idades"] = [{"faixa": k, "pct": round(v, 1)} for k, v in sorted(idades.items())]
        out["generos"] = [{"genero": k, "pct": round(v, 1)} for k, v in sorted(generos.items(), key=lambda kv: -kv[1])]
    def partes(linhas, chave, nomes=None):
        tot = sum(float(r["views"]) for r in linhas) or 1
        return [{"nome": (nomes or {}).get(r[chave], r[chave]), "pct": round(100 * float(r["views"]) / tot, 1)} for r in linhas]
    if p.get("paises"):
        out["paises"] = partes(p["paises"], "country")[:6]
    if p.get("aparelhos"):
        out["aparelhos"] = partes(p["aparelhos"], "deviceType", APARELHOS)
    if p.get("inscritos_x_nao"):
        nomes = {"SUBSCRIBED": "inscritos", "UNSUBSCRIBED": "não inscritos"}
        out["inscritos_x_nao"] = partes(p["inscritos_x_nao"], "subscribedStatus", nomes)
    return out


def monetizacao(bruto: dict, rel: dict, videos: dict | None = None) -> dict:
    """Base para a estimativa de 30 dias: views previstas por formato + elegibilidade ao Programa de Parcerias.
    Os reais saem no painel (aba Monetização), onde o RPM pode ser ajustado."""
    fmts = {f["formato"]: f for f in rel["formatos"]}
    dias = bruto.get("dias28") or []
    total28 = sum(float(d["views"]) for d in dias) or sum(f.get("views", 0) for f in rel["formatos"])
    tend = _tendencia(dias)
    soma_fmt = sum(fmts.get(k, {}).get("views", 0) for k in C.RPM_REFERENCIA) or 1
    previsao = {}
    for nome in C.RPM_REFERENCIA:
        parte = fmts.get(nome, {}).get("views", 0) / soma_fmt
        previsao[nome] = round(total28 / 28 * 30 * (1 + tend) * parte)
    cenarios = {c: round(sum(previsao[k] / 1000 * C.RPM_REFERENCIA[k][i] for k in previsao), 2)
                for i, c in enumerate(("pessimista", "provavel", "otimista"))}
    # Horas públicas de vídeos longos e lives em 12 meses (Shorts não contam para o Programa de Parcerias).
    if bruto.get("ano_formatos"):
        horas = sum(float(f["estimatedMinutesWatched"]) for f in bruto["ano_formatos"]
                    if f["creatorContentType"] != "shorts") / 60
        shorts90 = sum(float(f["views"]) for f in bruto.get("shorts90") or [] if f["creatorContentType"] == "shorts")
    else:
        horas = sum(float(f["estimatedMinutesWatched"]) for f in bruto.get("ano_total") or []) / 60
        shorts90 = None
    inscritos = rel["canal"].get("inscritos", 0)
    # Receita real (se o escopo de receita foi autorizado): RPM real por formato substitui a referência.
    real = None
    rec = bruto.get("receita")
    if rec and rec.get("total"):
        t = rec["total"][0]
        receita28 = float(t.get("estimatedRevenue") or 0)
        views_t = float(t.get("views") or 0) or total28
        rpm_fmt = {}
        por_fmt = defaultdict(lambda: [0.0, 0.0])
        for r in rec.get("por_video") or []:
            v = (videos or {}).get(r["video"])
            f = v["formato"] if v else None
            if f:
                por_fmt[f][0] += float(r["estimatedRevenue"] or 0)
                por_fmt[f][1] += float(r["views"] or 0)
        for f, (rs, vw) in por_fmt.items():
            if vw >= 500:
                rpm_fmt[f] = round(1000 * rs / vw, 2)
        rpm_geral = round(1000 * receita28 / views_t, 2) if views_t else None
        ant = float((rec.get("mes_anterior") or [{}])[0].get("estimatedRevenue") or 0)
        real = {"receita_28d": round(receita28, 2), "receita_28d_anterior": round(ant, 2),
                "rpm_geral": rpm_geral, "rpm_por_formato": rpm_fmt,
                "cpm": round(float(t.get("cpm") or 0), 2), "cpm_por_reproducao": round(float(t.get("playbackBasedCpm") or 0), 2),
                "impressoes_anuncio": int(float(t.get("adImpressions") or 0)),
                "reproducoes_monetizadas": int(float(t.get("monetizedPlaybacks") or 0)),
                "pct_monetizadas": round(100 * float(t.get("monetizedPlaybacks") or 0) / views_t, 1) if views_t else None,
                "top_videos": [{"titulo": (videos or {}).get(r["video"], {}).get("titulo", r["video"]),
                                "receita": round(float(r["estimatedRevenue"] or 0), 2), "views": int(float(r["views"] or 0))}
                               for r in (rec.get("por_video") or [])[:5]]}
        rpm_usado = {f: (rpm_fmt.get(f) or rpm_geral or C.RPM_REFERENCIA[f][1]) for f in C.RPM_REFERENCIA}
        real["estimativa_30d"] = round(sum(previsao[f] / 1000 * rpm_usado[f] for f in previsao), 2)
    # Ritmo de horas: a janela de 12 meses é móvel; para chegar a 4.000 h e ficar, o canal precisa
    # manter cerca de 333 h por mês (Shorts não contam).
    min28 = sum(float(f.get("minutos") or 0) for f in rel["formatos"] if f["formato"] != "Shorts")
    ritmo = round(min28 / 60 / 28 * 30)
    return {
        "receita_real": real,
        "views_28d": round(total28), "media_diaria": round(total28 / 28), "tendencia_pct": round(100 * tend, 1),
        "previsao_views_30d": previsao, "rpm_referencia": C.RPM_REFERENCIA, "estimativa_rs": cenarios,
        "serie_diaria": [{"dia": d["day"], "views": int(float(d["views"]))} for d in dias],
        "elegibilidade": {"inscritos": inscritos, "horas_12m": round(horas), "shorts_90d": round(shorts90) if shorts90 is not None else None,
                          "meta_inscritos": C.YPP_INSCRITOS, "meta_horas": C.YPP_HORAS_12M, "meta_shorts": C.YPP_SHORTS_90D,
                          "horas_mes_ritmo": ritmo, "horas_mes_necessarias": round(C.YPP_HORAS_12M / 12),
                          "monetizado": C.CANAL_MONETIZADO,
                          "cumpre": C.CANAL_MONETIZADO or inscritos >= C.YPP_INSCRITOS and (horas >= C.YPP_HORAS_12M or (shorts90 or 0) >= C.YPP_SHORTS_90D)},
    }


def _mil(n) -> str:
    """12345 -> '12.345' (separador de milhar brasileiro, sem mexer no resto do texto)."""
    return f"{int(round(n)):,}".replace(",", ".")


def _curto(st: dict) -> bool:
    return not st.get("live") and 0 < (st.get("duracao_s") or 0) <= 180


def requisitos(bruto: dict, rel: dict, videos: dict) -> dict:
    """Checklist do Programa de Parcerias: o que dá para medir (com valor atual e meta) e o que
    precisa ser conferido no YouTube Studio. Status: "ok", "abaixo", "risco" (ok hoje, mas cai
    abaixo em 30 dias) ou "conferir"."""
    fim = date.fromisoformat(bruto["periodo"]["fim"])
    monetizado = C.CANAL_MONETIZADO
    itens = []

    def item(chave, nome, atual, meta, ok, nivel, texto, acao=None, status=None):
        itens.append({"id": chave, "nome": nome, "atual": atual, "meta": meta, "nivel": nivel,
                      "status": status or ("ok" if ok else "abaixo"), "texto": texto, "acao": acao})

    inscritos = rel["canal"].get("inscritos", 0)

    # Horas públicas de 12 meses (vídeos longos e lives que continuam públicos).
    horas = mes = None
    min12 = bruto.get("min_video_12m")
    if min12 is not None:
        st = bruto.get("status_video_12m") or {}
        tot_min = sum(float(r["estimatedMinutesWatched"]) for r in min12) or 1
        pub_min = sum(float(r["estimatedMinutesWatched"]) for r in min12
                      if r["video"] in st and st[r["video"]]["privacidade"] == "public" and not _curto(st[r["video"]]))
        fracao = pub_min / tot_min
        horas = round(pub_min / 60)
        dias = bruto.get("dias365") or []
        saem = sum(float(d["estimatedMinutesWatched"]) for d in dias[:30]) / 60 * fracao
        entram = sum(float(d["estimatedMinutesWatched"]) for d in dias[-28:]) / 60 * fracao / 28 * 30
        proj = round(horas - saem + entram)
        por_mes = defaultdict(float)
        for d in dias:
            por_mes[d["day"][:7]] += float(d["estimatedMinutesWatched"]) / 60 * fracao
        mes = {"por_mes": [{"mes": k, "horas": round(v)} for k, v in sorted(por_mes.items())],
               "saem_30d": round(saem), "entram_30d": round(entram), "projecao_30d": proj,
               "fora_da_conta": round((tot_min - pub_min) / 60)}
        meta = C.YPP_HORAS_12M
        status = "ok" if horas >= meta and proj >= meta else ("risco" if horas >= meta else "abaixo")
        falta = max(0, meta - horas)
        texto = (f"{_mil(horas)} h públicas nos últimos 12 meses (vídeos longos e lives; Shorts, privados e apagados não contam). "
                 f"Nos próximos 30 dias saem da conta ~{_mil(saem)} h e entram ~{_mil(entram)} h no ritmo atual: "
                 f"projeção de {_mil(proj)} h.")
        acao = (None if status == "ok" else
                f"Faltam {_mil(falta)} h. Lives longas e vídeos longos contam; "
                f"seriam uns {_mil(falta / 12)} h a mais por mês durante um ano.")
        item("horas_12m", "Horas assistidas públicas (12 meses)", horas, meta, horas >= meta, "anúncios", texto, acao, status)

    item("inscritos", "Inscritos", inscritos, C.YPP_INSCRITOS, inscritos >= C.YPP_INSCRITOS, "anúncios",
         f"{_mil(inscritos)} inscritos.")
    shorts90 = None
    if bruto.get("shorts90") is not None:
        shorts90 = round(sum(float(f["views"]) for f in bruto["shorts90"] if f["creatorContentType"] == "shorts"))
        item("shorts_90d", "Alternativa às horas: views de Shorts (90 dias)", shorts90, C.YPP_SHORTS_90D,
             shorts90 >= C.YPP_SHORTS_90D, "anúncios",
             "Caminho alternativo às 4.000 h. Basta cumprir um dos dois.", None,
             "ok" if shorts90 >= C.YPP_SHORTS_90D else ("ok" if horas and horas >= C.YPP_HORAS_12M else "abaixo"))

    # Nível inicial (Super Chat, membros, Shopping).
    envios90 = sum(1 for v in videos.values() if v.get("privacidade", "public") == "public"
                   and datetime.fromisoformat(v["publicado"].replace("Z", "+00:00")).astimezone(BR).date() >= fim - timedelta(days=89))
    ok_ini = (inscritos >= C.YPP_INICIAL_INSCRITOS and envios90 >= C.YPP_INICIAL_ENVIOS_90D
              and ((horas or 0) >= C.YPP_INICIAL_HORAS or (shorts90 or 0) >= C.YPP_INICIAL_SHORTS))
    item("nivel_inicial", "Nível inicial (Super Chat, membros, Shopping)", None, None, ok_ini, "Supers e membros",
         f"{_mil(inscritos)} de {_mil(C.YPP_INICIAL_INSCRITOS)} inscritos, {envios90} de {C.YPP_INICIAL_ENVIOS_90D} envios públicos em 90 dias e "
         f"{_mil(horas) if horas is not None else '?'} de {_mil(C.YPP_INICIAL_HORAS)} h (ou {_mil(C.YPP_INICIAL_SHORTS)} views de Shorts em 90 dias).")

    # Atividade: o que pode tirar a monetização de quem já está no programa.
    ult = bruto.get("ultimo_envio")
    # Atividade conta até hoje (o Analytics fecha com 3 dias de atraso, os envios não).
    hoje = (datetime.fromisoformat(rel["gerado_em"]).astimezone(BR).date() if rel.get("gerado_em")
            else fim + timedelta(days=3))
    if ult:
        parado = max(0, (hoje - datetime.fromisoformat(ult.replace("Z", "+00:00")).astimezone(BR).date()).days)
    else:
        parado = 90
    item("atividade", "Canal ativo (envios públicos)", parado, C.YPP_DIAS_INATIVIDADE, parado < C.YPP_DIAS_INATIVIDADE - 30,
         "manter a monetização",
         ((f"Último envio público há {parado} dias." if parado else "Último envio público: hoje.") if ult else "Nenhum envio público nos últimos 90 dias.") +
         f" Canais sem envios por {C.YPP_DIAS_INATIVIDADE // 30} meses podem ter a monetização revisada.",
         None if parado < C.YPP_DIAS_INATIVIDADE - 30 else "Publique algo (vídeo, live ou Short) para manter o canal ativo.",
         "ok" if parado < C.YPP_DIAS_INATIVIDADE - 30 else ("risco" if parado < C.YPP_DIAS_INATIVIDADE else "abaixo"))

    # Itens que a API não informa: conferir no Studio.
    for chave, nome, texto in [
        ("advertencias", "Sem advertências das Diretrizes da Comunidade nem de direitos autorais",
         "YouTube Studio > Conteúdo/Status do canal. Atenção nas transmissões de jogo: imagem ou áudio da TV geram reivindicação."),
        ("adsense", "AdSense para YouTube ativo e vinculado", "YouTube Studio > Ganhar dinheiro > AdSense."),
        ("dois_fatores", "Verificação em duas etapas na conta Google", "myaccount.google.com > Segurança."),
        ("politicas", "Políticas de monetização (conteúdo reutilizado, adequado para anunciantes)",
         "YouTube Studio > Ganhar dinheiro mostra se há algum problema."),
    ]:
        item(chave, nome, None, None, True, "manter a monetização", texto, None, "conferir")

    # Horas e Shorts são caminhos alternativos; e se as horas já estão abaixo, o nível inicial cai pelo
    # mesmo motivo: um aviso só para a mesma causa.
    horas_abaixo = any(i["id"] == "horas_12m" and i["status"] != "ok" for i in itens)
    medidos = [i for i in itens if i["status"] in ("abaixo", "risco") and i["id"] != "shorts_90d"
               and not (i["id"] == "nivel_inicial" and horas_abaixo)]
    return {"monetizado": monetizado, "itens": itens, "horas_publicas": horas, "horas": mes,
            "pendencias": [i["nome"] for i in medidos],
            "resumo": ("Todos os requisitos medidos estão atingidos." if not medidos else
                       f"{len(medidos)} requisito(s) medido(s) abaixo da meta: " + "; ".join(i["nome"] for i in medidos) + "."),
            "nota": ("O canal já está no Programa de Parcerias: requisitos de entrada abaixo da meta não tiram a monetização, "
                     "mas indicam queda de audiência. O que pode tirar é inatividade, advertências ou violação de políticas."
                     if monetizado else "")}


def recomendacoes(rel: dict) -> list[str]:
    """Frases curtas, em linguagem de editor, tiradas dos números acima."""
    r = _Frases()
    fmts = [f for f in rel["formatos"] if f.get("indice")]
    if len(fmts) >= 2:
        best = max(fmts, key=lambda f: f["indice"])
        r.append(f"{best['formato']} rendem mais: nos 7 primeiros dias, fazem {best['indice']:.1f}x as views "
                 f"de um vídeo típico do canal ({best['n_videos']} vídeos analisados).")
    ins = [f for f in rel["formatos"] if f.get("inscritos")]
    if ins:
        best = max(ins, key=lambda f: f["inscritos"])
        r.append(f"Quem mais traz inscritos: {best['formato']} ({best['inscritos']} nas últimas 4 semanas).")
    tipos = [t for t in rel.get("tipos", [])
             if t["n_videos"] >= C.RAIOX_MIN_VIDEOS_CATEGORIA and t["indice"] and t["nome"] != "Outros"]
    if len(tipos) >= 2:
        best, pior = tipos[0], tipos[-1]
        r.append(f"Tipo de conteúdo que mais rende: {best['nome']} ({best['indice']:.1f}x a mediana, {best['n_videos']} vídeos); "
                 f"o que menos rende: {pior['nome']} ({pior['indice']:.1f}x).")
    temas = [t for t in rel["temas"] if t["nome"] in C.CATEGORIAS]  # sem "Notícia do dia"
    if temas:
        t = temas[0]
        if t["indice"] and t["indice"] > 1.1:
            r.append(f"Tema que mais rende: {t['nome']} ({t['indice']:.1f}x a mediana). O radar já dá peso maior a ele.")
        fraco = temas[-1]
        if fraco["indice"] and fraco["indice"] < 0.8 and fraco is not t:
            r.append(f"Tema que menos rende: {fraco['nome']} ({fraco['indice']:.1f}x). Vale buscar outro ângulo ou formato.")
    cedo = [x for x in rel["retencao"] if x.get("fica_30s") is not None and x["fica_30s"] < 60]
    if cedo:
        r.append(f"Em {len(cedo)} de {len(rel['retencao'])} vídeos longos, mais de 40% sai antes dos 30 s: "
                 "comece pelo lance ou pela opinião forte, sem introdução.")
    a = rel.get("alcance") or {}
    if a.get("ctr"):
        r.append(f"Taxa de cliques das miniaturas: {a['ctr']:.1f}% em {a['impressoes']:,} impressões nas últimas 4 semanas "
                 "(a maioria dos canais fica entre 2% e 10%).".replace(",", "."))
        tipos_ctr = [t for t in a.get("por_tipo") or [] if t["nome"] != "Outros"]
        if len(tipos_ctr) >= 2:
            r.append(f"Miniatura que mais atrai cliques: {tipos_ctr[0]['nome']} ({tipos_ctr[0]['ctr']:.1f}%); "
                     f"a que menos atrai: {tipos_ctr[-1]['nome']} ({tipos_ctr[-1]['ctr']:.1f}%). Copie o estilo da primeira.")
        baixos = [x for x in a.get("piores", []) if x["ctr"] < 0.7 * a["ctr"] and (x.get("pct_assistido") or 0) > 0]
        if baixos:
            r.append(f"\"{baixos[0]['titulo'][:60]}\" foi muito mostrado, mas pouco clicado ({baixos[0]['ctr']:.1f}%): "
                     "troque a miniatura e o título (o YouTube Studio permite testar até 3 miniaturas).")
    if rel["trafego"]:
        o = rel["trafego"][0]
        r.append(f"Maior origem de público: {o['origem']} ({o['pct']:.0f}% das views).")
        busca = next((x for x in rel["trafego"] if x["origem"] == "Busca do YouTube"), None)
        if busca and busca["pct"] >= 15:
            r.append("A busca pesa bastante: use no título os termos que o torcedor pesquisa (veja o radar diário).")
    if rel["melhores_dias"] and (rel["melhores_dias"][0]["indice"] or 0) >= 1.2:
        d = rel["melhores_dias"][0]
        h = (rel["melhores_horarios"][0]["quando"]
             if rel["melhores_horarios"] and (rel["melhores_horarios"][0]["indice"] or 0) >= 1.2 else None)
        r.append(f"Melhor momento para publicar: {d['quando']}" + (f", {h}" if h else "") +
                 " (mediana de views nos 7 primeiros dias).")
    return list(r)


class _Frases(list):
    """Lista que troca o ponto decimal por vírgula ("2.6x" -> "2,6x")."""
    def append(self, frase: str) -> None:
        import re
        super().append(re.sub(r"(\d)\.(\d)", r"\1,\2", frase))
