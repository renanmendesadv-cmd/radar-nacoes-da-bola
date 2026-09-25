"""Coleta de fontes gratuitas, sem chave de API.

- Google Trends: RSS de buscas em alta no Brasil.
- Google News: RSS de busca, últimas 24 h, por termo.
- YouTube: RSS público do canal (últimos ~15 vídeos), para saber o que já foi coberto.

Toda falha de rede é registrada e ignorada: se uma fonte cair, o radar segue com as outras.
"""
from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

log = logging.getLogger("radar")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 RadarNacoesDaBola/1.0")

TRENDS_URL = "https://trends.google.com/trending/rss?geo=BR"
NEWS_URL = "https://news.google.com/rss/search?q={q}+when:1d&hl=pt-BR&gl=BR&ceid=BR:pt-419"
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"


def fetch(url: str, tentativas: int = 3, pausa: float = 2.0, insistir_404: bool = False) -> str | None:
    """GET com poucas tentativas e pausa crescente (respeita limites das fontes)."""
    for i in range(tentativas):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR"}, timeout=20)
            if r.status_code == 200:
                return r.text
            log.warning("HTTP %s em %s", r.status_code, url)
            if r.status_code in (404, 403) and not insistir_404:
                return None
        except requests.RequestException as e:
            log.warning("Falha de rede em %s: %s", url, e)
        time.sleep(pausa * (i + 1))
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, nome):
    for c in el:
        if _local(c.tag) == nome:
            return c
    return None


def _text(el, nome, padrao=""):
    c = _child(el, nome)
    return (c.text or "").strip() if c is not None and c.text else padrao


def _data(s: str) -> str | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def _trafego(s: str) -> int:
    """'2.000+' / '20K+' / '1M+' -> inteiro aproximado."""
    s = (s or "").upper().replace("+", "").replace(".", "").replace(",", "").strip()
    mult = 1
    if s.endswith("K"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def parse_trends(xml: str) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        log.warning("RSS do Trends inválido: %s", e)
        return []
    termos = []
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        noticias = []
        for c in item:
            if _local(c.tag) == "news_item":
                noticias.append({
                    "titulo": _text(c, "news_item_title"),
                    "url": _text(c, "news_item_url"),
                    "fonte": _text(c, "news_item_source"),
                })
        termos.append({
            "termo": _text(item, "title"),
            "trafego": _trafego(_text(item, "approx_traffic")),
            "publicado": _data(_text(item, "pubDate")),
            "noticias": noticias,
        })
    return termos


def parse_news(xml: str, busca: str) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        log.warning("RSS do News inválido (%s): %s", busca, e)
        return []
    itens = []
    for item in root.iter("item"):
        titulo = _text(item, "title")
        fonte = _text(item, "source")
        # O Google News anexa " - Fonte" ao título; removemos para comparar títulos.
        if fonte and titulo.endswith(" - " + fonte):
            titulo = titulo[: -len(" - " + fonte)]
        elif " - " in titulo and not fonte:
            titulo, fonte = titulo.rsplit(" - ", 1)
        itens.append({
            "titulo": titulo.strip(),
            "fonte": fonte.strip(),
            "url": _text(item, "link"),
            "publicado": _data(_text(item, "pubDate")),
            "busca": busca,
        })
    return itens


def resolve_channel_id(handle: str) -> str | None:
    """Descobre o ID (UC...) a partir do @ do canal, lendo a página pública."""
    html = fetch(f"https://www.youtube.com/{handle.lstrip('/')}")
    if not html:
        return None
    for padrao in (r'"channelId":"(UC[\w-]{22})"', r'"externalId":"(UC[\w-]{22})"',
                   r'channel/(UC[\w-]{22})'):
        m = re.search(padrao, html)
        if m:
            return m.group(1)
    return None


def parse_channel_feed(xml: str) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    videos = []
    for entry in root:
        if _local(entry.tag) != "entry":
            continue
        link = _child(entry, "link")
        videos.append({
            "titulo": _text(entry, "title"),
            "url": link.get("href", "") if link is not None else "",
            "publicado": _data(_text(entry, "published")),
        })
    return videos


def videos_da_pagina(handle: str) -> list[dict]:
    """Plano B: lê os títulos na página /videos do canal quando o RSS do YouTube falha
    (o feed às vezes responde 404/500 para servidores de nuvem)."""
    html = fetch(f"https://www.youtube.com/{handle.lstrip('/')}/videos")
    if not html:
        return []
    videos, vistos = [], set()
    padroes = [
        r'"videoId":"([\w-]{11})".{0,3000}?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"',
        r'"contentId":"([\w-]{11})".{0,3000}?"title":\{"content":"((?:[^"\\]|\\.)*)"',
    ]
    for padrao in padroes:
        for vid, titulo in re.findall(padrao, html):
            if vid in vistos:
                continue
            try:
                titulo = json.loads(f'"{titulo}"')
            except ValueError:
                pass
            vistos.add(vid)
            videos.append({"titulo": titulo, "url": f"https://www.youtube.com/watch?v={vid}", "publicado": None})
        if videos:
            break
    return videos[:15]


def coletar(buscas: list[str], handle: str | None, channel_id: str | None) -> dict:
    status = {}

    xml = fetch(TRENDS_URL)
    termos = parse_trends(xml) if xml else []
    status["Google Trends"] = len(termos)

    noticias = []
    for b in buscas:
        xml = fetch(NEWS_URL.format(q=quote_plus(b)))
        if xml:
            noticias.extend(parse_news(xml, b))
        time.sleep(1.0)  # educado com a fonte gratuita
    status["Google News"] = len(noticias)

    videos = []
    cid = channel_id or (resolve_channel_id(handle) if handle else None)
    if cid:
        xml = fetch(YT_FEED.format(cid=cid), insistir_404=True)
        videos = parse_channel_feed(xml) if xml else []
        if not videos:  # feed alternativo: playlist de uploads (UC... -> UU...)
            xml = fetch(YT_FEED.replace("channel_id", "playlist_id").format(cid="UU" + cid[2:]), insistir_404=True)
            videos = parse_channel_feed(xml) if xml else []
        log.info("Vídeos do canal via RSS: %d", len(videos))
    if not videos and handle:
        videos = videos_da_pagina(handle)
        log.info("Vídeos do canal via página: %d", len(videos))
    status["Canal (RSS YouTube)"] = len(videos)

    return {"termos": termos, "noticias": noticias, "videos": videos,
            "channel_id": cid, "status": status}
