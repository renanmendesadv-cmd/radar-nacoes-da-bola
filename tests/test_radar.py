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


# ---------------------------------------------------------------- versão 8

def _rodar(tmp_path, **extra):
    env = dict(os.environ, FIXTURES_DIR=str(F), AGORA=AGORA.isoformat(), DRY_RUN="1", OUT_DIR=str(tmp_path), **extra)
    if "YOUTUBE_API_KEY" not in extra:
        env.pop("YOUTUBE_API_KEY", None)
    r = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=env, capture_output=True, text=True)
    return r, json.loads((tmp_path / "docs" / "data.json").read_text("utf-8")) if r.returncode in (0, 3) else None


def test_sementes_genericas_so_no_painel(tmp_path):
    r, d = _rodar(tmp_path)
    assert r.returncode == 0, r.stderr
    # "brasileirão protesto torcida" casaria com a pauta do protesto do Corinthians, mas a semente é só do painel.
    cor = next(t for t in d["temas"] if "Corinthians" in t["clubes"] and "rotest" in t["tema"])
    assert cor["busca_torcedor"] is None
    assert "brasileirão série b" in d["buscas_torcedor"]["brasileirão"]
    # Busca de outro esporte some do painel.
    assert d["buscas_torcedor"]["seleção brasileira"] == ["seleção brasileira convocação"]


def test_outros_esportes_nas_buscas():
    from radar import buscas
    assert buscas.especificas("seleção brasileira", ["seleção brasileira de voleibol masculino",
                                                     "seleção brasileira de futsal", "seleção brasileira convocação"]) \
        == ["seleção brasileira convocação"]
    assert score.outro_esporte("seleção brasileira de voleibol feminino")


def test_agenda_plano_b_pelas_buscas(tmp_path):
    r, d = _rodar(tmp_path)
    nb = d["agenda"]["nas_buscas"]
    jogos = [j["jogo"] for j in nb]
    assert "Corinthians x Rival" in jogos       # próximo jogo pelas buscas ("fc" é genérico)
    assert not any("Antigo" in j for j in jogos)                   # "resultado" = jogo já disputado
    assert not any("Estudiantes" in j for j in jogos)              # já veio da ESPN, não repete
    assert d["status"]["Agenda (buscas Google)"] == len(nb)
    sug = {"palmeiras": ["palmeiras x ldu quito", "palmeiras x ldu onde assistir", "palmeiras x santos resultado"]}
    j = agenda.jogos_das_buscas(sug, ["Palmeiras x LDU: onde assistir e escalações"])
    assert [x["jogo"] for x in j] == ["Palmeiras x LDU Quito"] and j[0]["confianca"] == "alta"


def test_espn_bloqueada_desiste_rapido(monkeypatch):
    chamadas = []

    def falso(url, **kw):
        chamadas.append(url)
        kw["info"]["status"] = 403
        return None
    monkeypatch.setattr(agenda, "fetch", falso)
    assert agenda.coletar_espn() == []
    assert len(chamadas) == 2  # um pedido por host, não 64


def test_youtube_sem_chave_nao_muda_nota(tmp_path):
    r, d = _rodar(tmp_path)
    assert d["status"]["YouTube (48 h)"] == "sem chave"
    assert all(t["sinais"]["youtube"] is None for t in d["temas"])
    # Sem YouTube, a conta equivale aos pesos antigos 30/30/20/20.
    s = {"busca": 0.5, "aceleracao": 0.8, "midia": 0.4, "aderencia": 1.0, "youtube": None}
    antigo = 100 * (0.3 * 0.5 + 0.3 * 0.8 + 0.2 * 0.4 + 0.2 * 1.0) * 1.0
    assert abs(score.nota_final(s, 1.0, False) - antigo) < 1e-9


def test_youtube_com_chave(tmp_path):
    r, d = _rodar(tmp_path, YOUTUBE_API_KEY="chave-de-teste")
    assert r.returncode == 0, r.stderr
    assert "chave-de-teste" not in r.stderr  # a chave nunca vai para o log
    fla = next(t for t in d["temas"] if "Flamengo" in t["clubes"] and t["categoria"] == "Mercado da bola")
    y = fla["youtube"]
    assert y["n_videos"] == 2 and y["views"] == 222000                # vídeo fora do assunto é descartado
    assert y["top"][0]["views"] == 180000 and fla["sinais"]["youtube"] > 0
    estado = json.loads((tmp_path / "data" / "estado.json").read_text("utf-8"))
    usadas = estado["youtube"]["buscas"]
    assert 0 < usadas <= 12
    # 2ª execução no mesmo dia: consultas repetidas vêm do cache, sem gastar cota.
    _rodar(tmp_path, YOUTUBE_API_KEY="chave-de-teste")
    estado = json.loads((tmp_path / "data" / "estado.json").read_text("utf-8"))
    assert estado["youtube"]["buscas"] == usadas


def test_youtube_limite_diario(tmp_path, monkeypatch):
    from radar import youtube, config as C
    temas = score.pontuar(bruto(), {}, AGORA)
    estado = {"youtube": {"dia": AGORA.astimezone(youtube.PACIFICO).date().isoformat(), "buscas": C.YT_BUSCAS_DIA}}
    youtube.enriquecer(temas, AGORA, "x", estado, tmp_path / "c.json", get=lambda *a, **k: 1 / 0)
    assert estado["youtube"]["buscas"] == C.YT_BUSCAS_DIA and all("youtube" not in t for t in temas)


def test_raiox_semanal(tmp_path):
    r, d = _rodar(tmp_path, RAIOX="1")
    assert r.returncode == 0, r.stderr
    rel = json.loads((tmp_path / "docs" / "desempenho.json").read_text("utf-8"))
    fmts = {f["formato"]: f for f in rel["formatos"]}
    assert set(fmts) == {"Shorts", "Vídeos longos", "Lives"}
    assert fmts["Shorts"]["indice"] > fmts["Lives"]["indice"]
    assert rel["temas"][0]["nome"] == "Arbitragem e VAR"
    f = rel["fatores_categoria"]
    assert f["Arbitragem e VAR"] > 1 > f["Jogo e resultado"]
    assert all(0.85 <= v <= 1.15 for v in f.values())
    assert rel["retencao"][0]["metade_sai_em"] and rel["retencao"][0]["maior_queda"]["de"] == "0:48"  # 10% a 20% de 8 min
    assert rel["retencao"][0]["fica_30s"] == 62
    assert rel["trafego"][0]["origem"] == "Feed de Shorts"
    assert rel["videos_inscritos"][0]["inscritos"] == 160
    assert rel["recomendacoes"]
    # Os fatores aprendidos já valem nas pautas do mesmo dia.
    assert d["fatores_categoria"] == f
    pesos = json.loads((tmp_path / "data" / "pesos-aprendidos.json").read_text("utf-8"))
    assert pesos["categorias"] == f
    html = (tmp_path / "data" / "ultimo-raiox.html").read_text("utf-8")
    assert "Onde o público sai" in html and "Formatos que rendem" in html


def test_raiox_sem_credenciais_nao_quebra(monkeypatch):
    from radar import main as M
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert M._raiox(AGORA, {}, None) == (None, None)


def test_raiox_token_revogado_avisa():
    from radar import analytics

    class R:
        status_code = 400

        def json(self):
            return {"error": "invalid_grant"}
    try:
        analytics.token_de_acesso("id", "segredo", "token", post=lambda *a, **k: R())
        assert False
    except analytics.ErroAnalytics as e:
        assert "YT_REFRESH_TOKEN" in str(e) and "segredo" not in str(e)


def test_fator_categoria_mexe_na_nota():
    b = bruto()
    t1 = score.pontuar(b, {}, AGORA)
    b["fatores_categoria"] = {"Mercado da bola": 1.15}
    t2 = score.pontuar(b, {}, AGORA)
    n1 = {t["tema"]: t["nota"] for t in t1}
    for t in t2:
        if t["categoria"] == "Mercado da bola":
            assert t["nota"] > n1[t["tema"]] or t["nota"] == 100
        else:
            assert t["nota"] == n1[t["tema"]]


def test_casos_reais_v8():
    # 29/09/2026: manchete com lista de clubes não confirma "Palmeiras x Vasco".
    sug = {"palmeiras x": ["palmeiras x ldu", "palmeiras x ldu onde assistir", "palmeiras x a", "palmeiras x b",
                           "palmeiras x c", "palmeiras x d", "palmeiras x e", "palmeiras x f", "palmeiras x g",
                           "palmeiras x vasco da gama"]}
    tit = ["Vencedor do prêmio Golden Boy foi oferecido a Santos, Botafogo, Flamengo, Palmeiras e Vasco"]
    jogos = [j["jogo"] for j in agenda.jogos_das_buscas(sug, tit)]
    assert "Palmeiras x Vasco" not in " ".join(jogos) and jogos[0].startswith("Palmeiras x Ldu")
    assert agenda._confronto("palmeiras x ldu onde assistir", "palmeiras", "ldu")
    assert agenda._confronto("flamengo enfrenta o estudiantes na libertadores", "flamengo", "estudiantes")
    # Jogo que a ESPN conhece (mesmo fora da janela de 7 dias) não repete.
    nb = [{"casa": "Palmeiras", "fora": "LDU", "manchetes": 0, "exemplo": None, "confianca": "média"}]
    ag = {"proximos": [], "resultados": [], "na_midia": []}
    assert agenda.unir_buscas(nb, ag, [{"casa": "LDU Quito", "fora": "Palmeiras"}]) == []
    # "Flamengo-PI" é outro clube.
    assert score.entidades("Flávio Araújo expõe atraso salarial do Flamengo-PI")["foco"] == []
    assert score.entidades("Atlético-MG vence o Flamengo")["foco"] == ["Flamengo"]
    assert score.entidades("Atlético-MG vence o Flamengo")["br"] == ["Atlético-MG"]


def test_tipos_de_conteudo_do_canal(tmp_path):
    from radar import analytics
    assert analytics.tipo_do_video("BOCA JUNIORS   X   SÃO PAULO - JOGO DE IDA") == "Transmissão de jogo"
    assert analytics.tipo_do_video("NORUEGA X PORTUGAL") == "Transmissão de jogo"
    assert analytics.tipo_do_video("SAI  PRO JOGO  # 215") == "Sai pro Jogo (programa)"
    assert analytics.tipo_do_video("FLU AFUNDA TIMÃO /VERDÃO PARA NAS MÃOS DE EX/TRICOLOR BATE INTER") == "Resenha multitemas"
    assert analytics.tipo_do_video("TOCA E  RECEBE - VC PERGUNTA  E NÓS RESPONDEMOS NA HORA") == "Perguntas do público"
    assert analytics.tipo_do_video("Flamengo vence e sobe na tabela") == "Outros"
    r, d = _rodar(tmp_path, RAIOX="1")
    rel = json.loads((tmp_path / "docs" / "desempenho.json").read_text("utf-8"))
    tipos = {t["nome"]: t for t in rel["tipos"]}
    assert tipos["Sai pro Jogo (programa)"]["n_videos"] == 3
    # Programa sem palavra de categoria conta como "Jogo e resultado" no ajuste de pesos.
    assert next(t for t in rel["temas"] if t["nome"] == "Jogo e resultado")["n_videos"] >= 6
    assert not any("mais rende: Outros" in x for x in rel["recomendacoes"])
    html = (tmp_path / "data" / "ultimo-raiox.html").read_text("utf-8")
    assert "Tipos de conteúdo" in html and "Clubes que rendem" in html


def test_videos_do_canal_pela_api():
    class R:
        def __init__(self, d, code=200):
            self._d, self.status_code = d, code

        def json(self):
            return self._d

    def get(url, params=None, **_):
        assert params["key"] == "k"
        if url.endswith("/channels"):
            assert params.get("forHandle") == "@canal"
            return R({"items": [{"id": "UCx", "contentDetails": {"relatedPlaylists": {"uploads": "UUx"}}}]})
        return R({"items": [{"snippet": {"title": "SAI PRO JOGO #219", "publishedAt": "2026-09-29T23:00:00Z",
                                         "resourceId": {"videoId": "abc"}}}]})
    videos, cid = collect.videos_pela_api("@canal", None, "k", get=get)
    assert cid == "UCx" and videos[0]["titulo"] == "SAI PRO JOGO #219" and videos[0]["url"].endswith("abc")
    assert collect.videos_pela_api("@canal", None, "k", get=lambda *a, **k: R({}, 403)) == ([], None)
