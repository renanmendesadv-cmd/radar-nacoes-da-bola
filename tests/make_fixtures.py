"""Gera XMLs de DEMONSTRAÇÃO no formato real das fontes (Trends, News, YouTube).

As manchetes são fictícias e genéricas: servem só para testar o radar e mostrar
o layout do painel. Nenhuma delas é notícia real.
"""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

AGORA = datetime(2026, 9, 24, 11, 0, tzinfo=timezone.utc)
PASTA = Path(__file__).parent / "fixtures"

NEWS = {
    "Flamengo": [
        ("Flamengo abre negociação por meia do futebol europeu", "Portal A", 2),
        ("Flamengo faz proposta por meia que joga na Europa", "Portal B", 3),
        ("Diretoria do Flamengo confirma negociação por meia europeu", "Portal C", 5),
        ("Meia europeu na mira do Flamengo: veja valores da negociação", "Portal D", 1),
        ("Flamengo treina com time reserva antes do clássico", "Portal E", 20),
    ],
    "Corinthians": [
        ("Corinthians: torcida protesta no CT após derrota e cobra diretoria", "Portal A", 1),
        ("Protesto da torcida do Corinthians no CT pressiona diretoria", "Portal B", 2),
        ("Crise no Corinthians: protesto no CT e cobrança à diretoria", "Portal F", 4),
        ("Corinthians: presidente responde protesto da torcida", "Portal C", 3),
    ],
    "São Paulo FC": [
        ("São Paulo FC perde titular por lesão e terá desfalque no clássico", "Portal A", 6),
        ("Lesão tira titular do São Paulo FC do clássico", "Portal B", 9),
        ("São Paulo FC confirma desfalque por lesão para o clássico", "Portal D", 12),
    ],
    "Palmeiras": [
        ("Palmeiras reclama de pênalti não marcado e critica arbitragem do VAR", "Portal A", 3),
        ("VAR: Palmeiras pede áudio da arbitragem após pênalti não marcado", "Portal C", 2),
        ("Pênalti não marcado revolta Palmeiras; clube critica arbitragem", "Portal E", 5),
        ("Arbitragem: comissão da CBF analisa pênalti não marcado contra o Palmeiras", "Portal F", 1),
        ("Palmeiras x Estudiantes: onde assistir e horário", "Portal B", 7),
        ("Palmeiras x Estudiantes: escalações do jogo da Libertadores", "Portal G", 8),
    ],
    "Brasileirão": [
        ("Brasileirão: tabela esquenta na briga pelo título na reta final", "Portal B", 30),
        ("Reta final do Brasileirão: briga pelo título e contra o rebaixamento", "Portal D", 26),
    ],
    "Champions League": [
        ("Champions League: brasileiro marca e decide na rodada europeia", "Portal G", 10),
        ("Brasileiro decide na Champions League com gol no fim", "Portal H", 8),
    ],
}

TRENDS = [
    ("flamengo", "50K+", ["Flamengo faz proposta por meia que joga na Europa"]),
    ("palmeiras var", "20K+", ["VAR: Palmeiras pede áudio da arbitragem após pênalti não marcado"]),
    ("corinthians protesto", "10K+", ["Protesto da torcida do Corinthians no CT pressiona diretoria"]),
    ("previsão do tempo", "100K+", ["Frente fria chega ao Sudeste"]),
]

CANAL = [("AO VIVO: São Paulo FC x rival, pré-jogo e desfalque por lesão", 20),
         ("Live de debate da rodada do Brasileirão", 44)]


AGENDA = [
    {"id": "1", "data": "2026-09-23T23:00Z", "liga": "Brazilian Serie A", "casa": "Flamengo", "fora": "Bahia",
     "placar_casa": 2, "placar_fora": 1, "estado": "post", "clube": "Flamengo"},
    {"id": "2", "data": "2026-09-25T22:00Z", "liga": "CONMEBOL Libertadores", "casa": "Palmeiras",
     "fora": "Estudiantes", "placar_casa": None, "placar_fora": None, "estado": "pre", "clube": "Palmeiras"},
    {"id": "3", "data": "2026-08-10T22:00Z", "liga": "CONMEBOL Libertadores", "casa": "Corinthians",
     "fora": "Antigo", "placar_casa": None, "placar_fora": None, "estado": "pre", "clube": "Corinthians"},
    {"id": "4", "data": "2026-10-20T22:00Z", "liga": "Brazilian Serie A", "casa": "Santos",
     "fora": "Corinthians", "placar_casa": None, "placar_fora": None, "estado": "pre", "clube": "Corinthians"},
]

SUGESTOES = {
    "flamengo": ["flamengo x", "flamengo hoje", "flamengo meia europeu", "flamengo x bahia"],
    "são paulo fc": ["são paulo fc lesão titular", "são paulo fc hoje"],
    "palmeiras": ["palmeiras x estudiantes", "palmeiras hoje"],
    # Sementes genéricas: só no painel. "série b" não pode casar com a pauta do Corinthians.
    "brasileirão": ["brasileirão série b", "brasileirão protesto torcida"],
    "seleção brasileira": ["seleção brasileira de voleibol feminino", "seleção brasileira convocação"],
    # Plano B da agenda: "corinthians x" revela o próximo adversário.
    "corinthians x": ["corinthians x rival fc", "corinthians x rival fc onde assistir", "corinthians x antigo resultado"],
}

# Respostas fictícias da YouTube Data API (search.list e videos.list).
YOUTUBE = {
    "search": {"*": {"items": [{"id": {"videoId": "vid00000001"}}, {"id": {"videoId": "vid00000002"}},
                               {"id": {"videoId": "vid00000003"}}]}},
    "videos": {"items": [
        {"id": "vid00000001", "snippet": {"title": "Flamengo: negociação com meia europeu, veja", "description": "",
                                          "channelTitle": "Canal Demo A", "channelId": "UCdemoA", "publishedAt": "2026-09-24T01:00:00Z"},
         "statistics": {"viewCount": "180000"}},
        {"id": "vid00000002", "snippet": {"title": "Meia europeu no Flamengo? Análise da proposta", "description": "",
                                          "channelTitle": "Canal Demo B", "channelId": "UCdemoB", "publishedAt": "2026-09-23T20:00:00Z"},
         "statistics": {"viewCount": "42000"}},
        {"id": "vid00000003", "snippet": {"title": "Receita de bolo de cenoura", "description": "",
                                          "channelTitle": "Canal Demo C", "channelId": "UCdemoC", "publishedAt": "2026-09-23T10:00:00Z"},
         "statistics": {"viewCount": "999999"}},
    ]},
}


def _analytics():
    """Dados fictícios no formato que radar.analytics.coletar() devolve."""
    videos, por_video, v7 = [], [], {}
    modelos = [  # (título, dias atrás, hora UTC, duração s, live, views 7 dias, inscritos)
        ("Corinthians: a crise na diretoria explicada", 10, 22, 480, False, 9000, 40),
        ("Polêmica no clássico: o que ninguém contou", 17, 22, 540, False, 12000, 55),
        ("Crise no São Paulo: protesto da torcida", 24, 22, 600, False, 8000, 30),
        ("Foi pênalti? Arbitragem do VAR no Palmeiras", 12, 15, 45, False, 20000, 80),
        ("VAR anula gol do Flamengo: foi certo?", 19, 15, 50, False, 15000, 60),
        ("Arbitragem polêmica no Brasileirão", 26, 15, 40, False, 18000, 70),
        ("Flamengo vence e sobe na tabela", 11, 1, 3600, True, 3000, 10),
        ("Corinthians empata e decepciona", 18, 1, 3500, True, 2500, 8),
        ("Palmeiras perde e torcida cobra", 25, 1, 3400, True, 2800, 9),
        ("Proposta do Flamengo por atacante europeu", 13, 12, 300, False, 6000, 20),
        ("Palmeiras negocia reforço para 2027", 20, 12, 320, False, 5000, 15),
        ("São Paulo acerta renovação de titular", 27, 12, 280, False, 4000, 12),
        ("PALMEIRAS  X  RIVAL - 30ª RODADA", 8, 23, 7200, True, 3500, 12),
        ("SAI PRO JOGO #300", 9, 23, 5400, True, 1500, 3),
        ("SAI PRO JOGO #301", 16, 23, 5400, True, 1700, 4),
        ("SAI PRO JOGO #302", 23, 23, 5400, True, 1600, 3),
    ]
    for i, (t, dias, hora, dur, live, views7, ins) in enumerate(modelos):
        vid = f"canal{i:06d}"
        pub = (AGORA - timedelta(days=dias)).replace(hour=hora, minute=0)
        videos.append({"id": vid, "titulo": t, "publicado": pub.isoformat().replace("+00:00", "Z"),
                       "duracao_s": dur, "live": live, "views_total": views7 * 2})
        v7[vid] = {"views": views7, "subscribersGained": ins, "averageViewPercentage": 40.0}
        por_video.append({"video": vid, "views": views7 * 2, "estimatedMinutesWatched": views7, "averageViewDuration": dur // 3,
                          "averageViewPercentage": 35.0 if dur > 180 else 80.0, "subscribersGained": ins * 2})
    curva = [{"elapsedVideoTimeRatio": x / 100, "audienceWatchRatio": y}
             for x, y in [(1, 1.0), (5, 0.62), (10, 0.55), (20, 0.5), (30, 0.46), (50, 0.4), (70, 0.33), (100, 0.2)]]
    return {
        "canal": {"id": "UCdemo", "nome": "Canal de demonstração", "inscritos": 10000},
        "periodo": {"inicio": "2026-08-25", "fim": "2026-09-21", "janela_inicio": "2026-06-24"},
        "videos": videos, "por_video": por_video, "v7": v7,
        "trafego": [{"insightTrafficSourceType": "SHORTS", "views": 50000, "estimatedMinutesWatched": 9000},
                    {"insightTrafficSourceType": "YT_SEARCH", "views": 30000, "estimatedMinutesWatched": 12000},
                    {"insightTrafficSourceType": "SUBSCRIBER", "views": 20000, "estimatedMinutesWatched": 15000}],
        "formatos": [{"creatorContentType": "shorts", "views": 60000, "estimatedMinutesWatched": 5000, "subscribersGained": 300, "averageViewDuration": 35},
                     {"creatorContentType": "videoOnDemand", "views": 30000, "estimatedMinutesWatched": 40000, "subscribersGained": 150, "averageViewDuration": 200},
                     {"creatorContentType": "liveStream", "views": 10000, "estimatedMinutesWatched": 60000, "subscribersGained": 40, "averageViewDuration": 900}],
        "semana": [{"views": 30000, "estimatedMinutesWatched": 20000, "subscribersGained": 120, "subscribersLost": 20}],
        "semana_anterior": [{"views": 25000, "estimatedMinutesWatched": 18000, "subscribersGained": 100, "subscribersLost": 25}],
        "retencao": {"canal000000": curva, "canal000001": curva},
        # Views por dia crescendo de 3.000 a 3.540 (tendência de alta) e dados de 12 meses / 90 dias.
        "dias28": [{"day": f"2026-08-{25 + i:02d}" if i < 7 else f"2026-09-{i - 6:02d}", "views": 3000 + 20 * i,
                    "estimatedMinutesWatched": 2000} for i in range(28)],
        "ano_formatos": [{"creatorContentType": "shorts", "views": 500000, "estimatedMinutesWatched": 60000},
                         {"creatorContentType": "videoOnDemand", "views": 200000, "estimatedMinutesWatched": 150000},
                         {"creatorContentType": "liveStream", "views": 80000, "estimatedMinutesWatched": 180000}],
        "shorts90": [{"creatorContentType": "shorts", "views": 150000}],
        "publico": {
            "idade_genero": [{"ageGroup": "age18-24", "gender": "male", "viewerPercentage": 20},
                             {"ageGroup": "age25-34", "gender": "male", "viewerPercentage": 45},
                             {"ageGroup": "age35-44", "gender": "male", "viewerPercentage": 25},
                             {"ageGroup": "age25-34", "gender": "female", "viewerPercentage": 10}],
            "paises": [{"country": "BR", "views": 9000, "estimatedMinutesWatched": 1}, {"country": "PT", "views": 1000, "estimatedMinutesWatched": 1}],
            "aparelhos": [{"deviceType": "MOBILE", "views": 7000, "estimatedMinutesWatched": 1}, {"deviceType": "TV", "views": 3000, "estimatedMinutesWatched": 1}],
            "inscritos_x_nao": [{"subscribedStatus": "SUBSCRIBED", "views": 8000, "estimatedMinutesWatched": 1},
                                {"subscribedStatus": "UNSUBSCRIBED", "views": 2000, "estimatedMinutesWatched": 1}],
        },
        "receita": {
            "total": [{"estimatedRevenue": 300.0, "estimatedAdRevenue": 250.0, "cpm": 9.5, "playbackBasedCpm": 8.0,
                       "adImpressions": 40000, "monetizedPlaybacks": 30000, "views": 100000}],
            "por_video": [{"video": f"canal{i:06d}", "estimatedRevenue": 10.0 + i, "views": 5000} for i in range(12)],
            "mes_anterior": [{"estimatedRevenue": 240.0, "views": 90000}],
        },
    }


def _alcance():
    """Histórico fictício do relatório de alcance: CTR maior em Shorts, menor nas lives do programa."""
    ctr = {0: .04, 1: .04, 2: .04, 3: .08, 4: .08, 5: .08, 6: .02, 7: .02, 8: .02, 9: .04, 10: .04, 11: .04,
           12: .03, 13: .01, 14: .01, 15: .01}
    return {"ativado_em": "2026-09-01T00:00:00+00:00",
            "dias": {"2026-09-15": {f"canal{i:06d}": [5000, 5000 * c] for i, c in ctr.items()}}}


def _item(titulo, fonte, horas):
    d = format_datetime(AGORA - timedelta(hours=horas))
    return (f"<item><title>{escape(titulo)} - {escape(fonte)}</title><link>https://news.google.com/</link>"
            f"<pubDate>{d}</pubDate><source url=\"https://example.com\">{escape(fonte)}</source></item>")


def gerar():
    (PASTA / "news").mkdir(parents=True, exist_ok=True)
    for busca, itens in NEWS.items():
        corpo = "".join(_item(*i) for i in itens)
        (PASTA / "news" / f"{busca.replace(' ', '_')}.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>{corpo}</channel></rss>', "utf-8")
    itens = []
    for termo, traf, noticias in TRENDS:
        ni = "".join(f"<ht:news_item><ht:news_item_title>{escape(n)}</ht:news_item_title>"
                     f"<ht:news_item_url>https://news.google.com/</ht:news_item_url>"
                     f"<ht:news_item_source>Portal Z</ht:news_item_source></ht:news_item>" for n in noticias)
        itens.append(f"<item><title>{escape(termo)}</title><ht:approx_traffic>{traf}</ht:approx_traffic>"
                     f"<pubDate>{format_datetime(AGORA - timedelta(hours=2))}</pubDate>{ni}</item>")
    (PASTA / "trends.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">'
        f'<channel>{"".join(itens)}</channel></rss>', "utf-8")
    import json
    (PASTA / "agenda.json").write_text(json.dumps(AGENDA), "utf-8")
    (PASTA / "sugestoes.json").write_text(json.dumps(SUGESTOES, ensure_ascii=False), "utf-8")
    (PASTA / "youtube.json").write_text(json.dumps(YOUTUBE, ensure_ascii=False), "utf-8")
    (PASTA / "analytics.json").write_text(json.dumps(_analytics(), ensure_ascii=False), "utf-8")
    (PASTA / "alcance.json").write_text(json.dumps(_alcance(), ensure_ascii=False), "utf-8")
    entries = "".join(
        f"<entry><title>{escape(t)}</title><link rel=\"alternate\" href=\"https://www.youtube.com/@nacoesdabola\"/>"
        f"<published>{(AGORA - timedelta(hours=h)).isoformat()}</published></entry>" for t, h in CANAL)
    (PASTA / "channel.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>', "utf-8")


if __name__ == "__main__":
    gerar()
