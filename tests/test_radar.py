import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from radar import agenda, collect, score  # noqa: E402
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
    nomes = [t["tema"] for t in temas]
    costa = [i for i, n in enumerate(nomes) if "Costa Rica" in n]
    assert not costa or costa[0] >= 3  # some ou fica atrás dos temas dos clubes do canal


def test_financas_e_reality_show():
    assert score.categoria("Corinthians atrasa parcelas de acordo com a União") == "Finanças e gestão"
    assert not score.eh_futebol("Enquete A Fazenda: Ana x João")


def test_outros_esportes_e_termos():
    assert score.outro_esporte("GANHAR FLA-FLU É NORMAL! O Sesc RJ Flamengo venceu o Fluminense na Copa SuperVôlei")
    assert not score.outro_esporte("Flamengo vence o Fluminense no Maracanã")
    celeb = {"termo": "solange gomes", "noticias": [{"titulo": "Solange Gomes fala sobre reality"},
                                                   {"titulo": "Solange Gomes posta foto"}]}
    assert not score.termo_de_futebol(celeb)
    assert score.termo_de_futebol({"termo": "flamengo x palmeiras", "noticias": []})


def test_horario_reserva_nao_repete(tmp_path):
    base = dict(os.environ, FIXTURES_DIR=str(F), AGORA=AGORA.isoformat(), OUT_DIR=str(tmp_path),
                GITHUB_EVENT_NAME="schedule", EMAIL_TO="", SMTP_USER="", SMTP_PASS="")
    r1 = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=base, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    estado = json.loads((tmp_path / "data" / "estado.json").read_text("utf-8"))
    assert estado["ultima_agendada"] == "2026-09-24"
    r2 = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=base, capture_output=True, text=True)
    assert r2.returncode == 0 and "horário reserva" in r2.stderr
    manual = dict(base, GITHUB_EVENT_NAME="workflow_dispatch")
    r3 = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=manual, capture_output=True, text=True)
    assert r3.returncode == 0 and "temas pontuados" in r3.stderr


def test_selecao_so_brasil():
    assert not score.entidades("Cabo Verde x Ruanda: arbitragem polêmica nas Eliminatórias")["selecao"]
    assert score.entidades("Seleção Brasileira enfrenta a Austrália")["selecao"]
    assert score.entidades("Seleção de Ancelotti: Brasil treina no Rio")["selecao"]
    ent = {"foco": [], "br": [], "selecao": False, "comp_br": False, "intl": ["x"]}
    assert score.nota_aderencia(ent, "Arbitragem e VAR") <= 0.4


def test_agenda_e_buscas_ponta_a_ponta(tmp_path):
    env = dict(os.environ, FIXTURES_DIR=str(F), AGORA=AGORA.isoformat(), DRY_RUN="1", OUT_DIR=str(tmp_path))
    r = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    d = json.loads((tmp_path / "docs" / "data.json").read_text("utf-8"))
    ag = d["agenda"]
    assert [e["id"] for e in ag["resultados"]] == ["1"]            # vitória de ontem
    assert "venceu" in ag["resultados"][0]["gancho"]
    assert [e["id"] for e in ag["proximos"]] == ["2"]               # só o jogo dentro de 7 dias
    assert ag["proximos"][0]["liga"] == "Libertadores"
    assert ag["na_midia"] == []  # Palmeiras x Estudiantes já veio da ESPN: não repete
    assert agenda.jogos_na_midia(["Palmeiras x Estudiantes: onde assistir", "Palmeiras x Estudiantes: escalações"])
    spfc = next(t for t in d["temas"] if "São Paulo" in t["clubes"])
    assert spfc["sinais"]["busca"] > 0 and "lesão" in spfc["busca_torcedor"]
    assert d["buscas_torcedor"]["flamengo"] == ["flamengo meia europeu", "flamengo x bahia"]
    html = (tmp_path / "data" / "ultimo-email.html").read_text("utf-8")
    assert "Estudiantes" in html
