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
        res = cli.dados("videos", part="snippet,contentDetails,statistics,liveStreamingDetails",
                        id=",".join(ids[i:i + 50]))
        for v in res.get("items", []):
            videos.append({
                "id": v["id"], "titulo": v["snippet"]["title"], "publicado": v["snippet"]["publishedAt"],
                "duracao_s": _duracao_s(v["contentDetails"].get("duration")),
                "live": "liveStreamingDetails" in v,
                "views_total": int(v.get("statistics", {}).get("viewCount", 0) or 0),
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


def analisar(bruto: dict, fatores_anteriores: dict | None = None, gerado_em: str | None = None) -> dict:
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
    rel["monetizacao"] = monetizacao(bruto, rel)
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


def monetizacao(bruto: dict, rel: dict) -> dict:
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
    # Ritmo de horas: a janela de 12 meses é móvel; para chegar a 4.000 h e ficar, o canal precisa
    # manter cerca de 333 h por mês (Shorts não contam).
    min28 = sum(float(f.get("minutos") or 0) for f in rel["formatos"] if f["formato"] != "Shorts")
    ritmo = round(min28 / 60 / 28 * 30)
    return {
        "views_28d": round(total28), "media_diaria": round(total28 / 28), "tendencia_pct": round(100 * tend, 1),
        "previsao_views_30d": previsao, "rpm_referencia": C.RPM_REFERENCIA, "estimativa_rs": cenarios,
        "serie_diaria": [{"dia": d["day"], "views": int(float(d["views"]))} for d in dias],
        "elegibilidade": {"inscritos": inscritos, "horas_12m": round(horas), "shorts_90d": round(shorts90) if shorts90 is not None else None,
                          "meta_inscritos": C.YPP_INSCRITOS, "meta_horas": C.YPP_HORAS_12M, "meta_shorts": C.YPP_SHORTS_90D,
                          "horas_mes_ritmo": ritmo, "horas_mes_necessarias": round(C.YPP_HORAS_12M / 12),
                          "cumpre": inscritos >= C.YPP_INSCRITOS and (horas >= C.YPP_HORAS_12M or (shorts90 or 0) >= C.YPP_SHORTS_90D)},
    }


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
