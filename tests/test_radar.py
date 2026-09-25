import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from radar import collect, score  # noqa: E402
from tests import make_fixtures  # noqa: E402

make_fixtures.gerar()
F = RAIZ / "tests" / "fixtures"
AGORA = make_fixtures.AGORA


def bruto():
    termos = collect.parse_trends((F / "trends.xml").read_text("utf-8"))
    noticias = []
    for f in (F / "news").glob("*.xml"):
        noticias += collect.parse_news(f.read_text("utf-8"), f.stem.replace("_", " "))
    videos = collect.parse_channel_feed((F / "channel.xml").read_text("utf-8"))
    return {"termos": termos, "noticias": noticias, "videos": videos}


def test_parsers():
    b = bruto()
    assert b["termos"][0]["trafego"] == 50_000
    assert b["termos"][0]["noticias"][0]["titulo"].startswith("Flamengo")
    assert all(" - Portal" not in n["titulo"] for n in b["noticias"])
    assert len(b["videos"]) == 2


def test_entidades_sem_falso_positivo():
    assert score.entidades("Vitória importante na rodada")["br"] == []
    assert score.entidades("Flamengo e Palmeiras empatam")["foco"] == ["Flamengo", "Palmeiras"]


def test_pontuacao_e_agrupamento():
    temas = score.pontuar(bruto(), {}, AGORA)
    nomes = [t["tema"] for t in temas]
    # Termo fora do futebol é descartado
    assert not any("Frente fria" in n for n in nomes)
    # As 4 manchetes da negociação do Flamengo viram um único tema
    fla = [t for t in temas if "Flamengo" in t["clubes"] and t["categoria"] == "Mercado da bola"]
    assert len(fla) == 1 and fla[0]["n_manchetes"] >= 4
    # Tema com busca no Google + clube foco fica no topo
    assert temas[0]["foco"] and temas[0]["trafego_google"] > 0
    # Tema já coberto pelo canal é sinalizado
    spfc = [t for t in temas if "São Paulo" in t["clubes"]]
    assert spfc and spfc[0]["ja_coberto"]
    for t in temas:
        assert 0 <= t["nota"] <= 100


def test_historico_reduz_aceleracao():
    b = bruto()
    t1 = score.pontuar(b, {}, AGORA)
    hist = {"2026-09-23": {t["assinatura"]: 20 for t in t1}}
    t2 = score.pontuar(b, hist, AGORA)
    a1 = {t["tema"]: t["sinais"]["aceleracao"] for t in t1}
    a2 = {t["tema"]: t["sinais"]["aceleracao"] for t in t2}
    assert all(a2[k] < a1[k] for k in a1)


def test_main_ponta_a_ponta(tmp_path):
    env = dict(os.environ, FIXTURES_DIR=str(F), AGORA=AGORA.isoformat(), DRY_RUN="1", OUT_DIR=str(tmp_path))
    r = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    dados = json.loads((tmp_path / "docs" / "data.json").read_text("utf-8"))
    assert dados["temas"] and dados["termos_futebol"]
    html = (tmp_path / "data" / "ultimo-email.html").read_text("utf-8")
    assert "Gancho" in html and "Grave primeiro" in html


def test_ruido_real_da_primeira_execucao():
    # Casos vistos na 1ª execução real (24/09/2026)
    assert not score.eh_futebol("Quaest: intenções de voto para o Senado na Bahia")
    assert score.entidades("Bahia vence o clássico e sobe na tabela")["br"] == ["Bahia"]
    assert score.espanhol("Con James a bordo, Nacional recibe a Millonarios")
    assert not score.espanhol("Flamengo recebe o Palmeiras no Maracanã")
    assert score.categoria("Golpe no governo") == "Notícia do dia"


def test_sem_efeito_corrente():
    base = [
        "Flamengo vence o Bahia no Maracanã",
        "Flamengo e Corinthians disputam final feminina",
        "Ingressos para final feminina entre Corinthians e Flamengo",
        "Corinthians atrasa parcelas de acordo com a União",
        "Palmeiras anuncia venda de ingressos para o clássico",
    ]
    noticias = [{"titulo": t, "fonte": f"F{i}", "url": "", "publicado": None, "busca": "x"}
                for i, t in enumerate(base)]
    grupos = score.agrupar(noticias)
    assert max(len(g["itens"]) for g in grupos) <= 2


def test_aderencia_rebaixa_tema_sem_ligacao():
    agora = AGORA
    ruido = {"termos": [{"termo": "costa rica x curacao", "trafego": 5000, "publicado": agora.isoformat(),
                         "noticias": [{"titulo": "Costa Rica x Curaçao: onde assistir ao vivo", "url": "", "fonte": "A"},
                                      {"titulo": "Costa Rica x Curaçao: escalações", "url": "", "fonte": "B"}]}],
             "noticias": [], "videos": []}
    b = bruto()
    b["termos"] += ruido["termos"]
    temas = score.pontuar(b, {}, agora)
    posicao = [t["tema"] for t in temas].index(next(t["tema"] for t in temas if "Costa Rica" in t["tema"]))
    assert posicao >= 3
