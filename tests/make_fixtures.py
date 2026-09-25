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
    entries = "".join(
        f"<entry><title>{escape(t)}</title><link rel=\"alternate\" href=\"https://www.youtube.com/@nacoesdabola\"/>"
        f"<published>{(AGORA - timedelta(hours=h)).isoformat()}</published></entry>" for t, h in CANAL)
    (PASTA / "channel.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>', "utf-8")


if __name__ == "__main__":
    gerar()
