#!/usr/bin/env python3
"""Utilities Daily News Radar: coleta -> filtra -> classifica -> agrupa -> docs/data/news.json"""
import html, json, os, pathlib, re, sys, urllib.parse, datetime as dt
from email.utils import parsedate_to_datetime
import feedparser, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG, OUT = ROOT / "config", ROOT / "docs" / "data"
UA = "UtilitiesRadar/1.0 (uso pessoal; RSS publico)"
TZ = dt.timezone(dt.timedelta(hours=-3))
HORAS = 36
TIER = {"oficial": 1, "ri": 2, "wire": 3, "especializada": 4, "geral": 5}
TEMAS = ["Regulação", "M&A", "Concessões", "Tarifas", "Leilões", "Capex", "Resultados",
         "Governança", "Dívida/Rating", "Dividendos", "Commodities", "Macro"]
POR_QUE = {
    "Regulação": "Mudança de regra pode alterar receita permitida, custos regulatórios ou risco setorial.",
    "Tarifas": "Tarifa e reajuste afetam receita, margem e geração de caixa das concessionárias.",
    "Leilões": "Leilões definem novas receitas contratadas, capex e competição entre players.",
    "Concessões": "Concessões definem prazo, receita e obrigações de investimento (renovação/caducidade).",
    "M&A": "Transações podem mudar portfólio, alavancagem, sinergias e a avaliação da empresa.",
    "Capex": "Capex altera necessidade de caixa, endividamento e crescimento da base de ativos.",
    "Resultados": "Resultado/guidance move estimativas de EBITDA, lucro e a percepção da tese.",
    "Dívida/Rating": "Custo/perfil da dívida e rating afetam despesa financeira e capacidade de investir.",
    "Dividendos": "Política de proventos influencia o retorno ao acionista e a atratividade da tese.",
    "Governança": "Mudanças de gestão/controle podem alterar estratégia e percepção de risco.",
    "Commodities": "Preços de petróleo/gás/energia afetam receita e custos de geradoras e petroleiras.",
    "Macro": "Juros, inflação e câmbio afetam custo de capital, indexação de receita e dívida."}
STOP = set("para como mais sobre pela pelo pelos com dos das uma nos nas que por após ante entre este esta isso the and for with from over after into".split())
PAYWALL = {"Valor Econômico", "Bloomberg", "Financial Times", "Folha", "O Globo", "Estadão", "Reuters"}

def load(n): return yaml.safe_load((CFG / n).read_text(encoding="utf-8"))
def rx(p): return re.compile(p, re.I)
def clean(s): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
def toks(t): return {w for w in re.findall(r"[a-zà-ú0-9]{4,}", t.lower()) if w not in STOP}

def gnews(q):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})

def queries(srcs, cos):
    kw = {"pt": "(energia OR elétrica OR saneamento OR petróleo OR gás OR Sabesp OR Eletrobras OR Petrobras)",
          "en": "(Brazil (power OR utility OR electricity OR oil OR gas OR Petrobras OR Eletrobras))", "todos": ""}
    for s in srcs:
        yield "fonte", s["nome"], f"site:{s['dominio']} {kw[s['idioma']]} when:2d".replace("  ", " ")
    for c in cos:
        yield "empresa", c["nome"], f"({c['busca']}) when:2d"

def fetch(url):
    return feedparser.parse(os.environ.get("RADAR_OFFLINE") or url, agent=UA)

def when(e):
    for k in ("published", "updated"):
        if e.get(k):
            try:
                d = parsedate_to_datetime(e[k])
                return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).astimezone(TZ)
            except Exception: pass

def main():
    srcs, cos, R = load("sources.yml")["fontes"], load("companies.yml")["empresas"], load("rules.yml")
    now = dt.datetime.now(TZ)
    by_name = {s["nome"].lower(): s for s in srcs}
    setor_rx = {k: rx(v) for k, v in R["setores"].items()}
    cat_rx = {k: (v[0], rx(v[1])) for k, v in R["categorias"].items()}
    alta_rx, pos_rx, neg_rx = rx(R["termos_alta"]), rx(R["impacto_positivo"]), rx(R["impacto_negativo"])
    co_rx = [(c, rx(r"\b(" + "|".join(re.escape(a) for a in c["apelidos"]) + r")\b")) for c in cos]
    raw, report = {}, []
    for kind, name, q in queries(srcs, cos):
        try:
            f = fetch(gnews(q)); n = len(f.entries)
            if n == 0 and f.get("bozo") and not os.environ.get("RADAR_OFFLINE"):
                raise RuntimeError(str(f.get("bozo_exception"))[:100])
            report.append({"consulta": name, "tipo": kind, "itens": n, "erro": None})
        except Exception as ex:
            report.append({"consulta": name, "tipo": kind, "itens": 0, "erro": str(ex)[:120]}); continue
        for e in f.entries:
            d = when(e)
            if d and (now - d).total_seconds() > HORAS * 3600: continue
            titulo = clean(e.get("title", ""))
            veic = clean((e.get("source") or {}).get("title", "")) or (name if kind == "fonte" else "")
            if veic and titulo.endswith(" - " + veic): titulo = titulo[: -len(veic) - 3]
            link = e.get("link", "")
            if not titulo or not link: continue
            resumo = clean(e.get("summary", ""))
            if len(resumo) < 40 or resumo.lower().startswith(titulo.lower()[:40]): resumo = ""
            s = by_name.get(veic.lower())
            tipo = s["tipo"] if s else ("oficial" if re.search(r"gov\.br|\.leg\.br|\.jus\.br", link) else "geral")
            raw.setdefault(link, dict(titulo=titulo, link=link, veiculo=veic or "Não identificado na fonte",
                                      tipo=tipo, data=d.isoformat() if d else None, resumo=resumo))
    itens = []
    for it in raw.values():
        txt = it["titulo"] + " " + it["resumo"]
        setores = [k for k, r in setor_rx.items() if r.search(txt)]
        emp = [c for c, r in co_rx if r.search(txt)]
        for c in emp:
            if c["setor"] not in setores: setores.append(c["setor"])
        if not setores and not emp: continue
        it.update(setores=setores, empresas=[c["nome"] for c in emp], tickers=[c["ticker"] for c in emp if c["ticker"]],
                  cats={k: w for k, (w, r) in cat_rx.items() if r.search(txt)}, tk=toks(it["titulo"]),
                  alta=bool(alta_rx.search(txt)))
        itens.append(it)
    eventos = []
    for it in sorted(itens, key=lambda x: TIER[x["tipo"]]):
        for ev in eventos:
            a, b = it["tk"], ev["tk"]
            if a and b and len(a & b) / len(a | b) >= 0.45:
                ev["itens"].append(it); ev["tk"] |= a; break
        else: eventos.append({"tk": set(it["tk"]), "itens": [it]})
    out = []
    for ev in eventos:
        its = ev["itens"]; lead = its[0]
        txt = " ".join(i["titulo"] + " " + i["resumo"] for i in its)
        cats = {}
        for i in its:
            for k, w in i["cats"].items(): cats[k] = max(w, cats.get(k, 0))
        emp = sorted({e for i in its for e in i["empresas"]})
        prim = next((i for i in its if i["tipo"] in ("oficial", "ri")), None)
        score = (sum(cats.values()) + 2 * len(emp[:3]) + 3 * any(i["alta"] for i in its)
                 + (3 if prim else 0) + min(len(its) - 1, 3) + (1 if lead["tipo"] == "wire" else 0))
        rel = "alta" if score >= 9 else "media" if score >= 5 else "baixa"
        if not cats and not emp: rel = "baixa"
        p, n = bool(pos_rx.search(txt)), bool(neg_rx.search(txt))
        temas = sorted(cats, key=lambda k: TEMAS.index(k) if k in TEMAS else 99)
        out.append({
            "titulo": lead["titulo"], "data": max((i["data"] for i in its if i["data"]), default=None),
            "relevancia": rel, "score": score, "setores": sorted({s for i in its for s in i["setores"]}),
            "categorias": temas, "empresas": emp, "tickers": sorted({t for i in its for t in i["tickers"]}),
            "impacto": "Positivo" if p and not n else "Negativo" if n and not p else "Incerto",
            "resumo": next((i["resumo"] for i in its if i["resumo"]), "") or "Não identificado na fonte (apenas manchete disponível).",
            "por_que": " ".join(POR_QUE[t] for t in temas[:2]) or "Não identificado na fonte.",
            "paywall": any(i["veiculo"] in PAYWALL for i in its),
            "fonte_primaria": {"nome": prim["veiculo"], "link": prim["link"]} if prim else None,
            "fontes": [{"nome": i["veiculo"], "link": i["link"]} for i in its]})
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    out.sort(key=lambda e: (ordem[e["relevancia"]], -e["score"]))
    prio = lambda e: min([TEMAS.index(t) for t in e["categorias"]] or [99])
    hoje = sorted((i for i, e in enumerate(out) if e["relevancia"] != "baixa"),
                  key=lambda i: (ordem[out[i]["relevancia"]], prio(out[i]), -out[i]["score"]))[:10]
    payload = {"gerado_em": now.isoformat(), "eventos": out, "o_que_mudou": hoje, "coleta": report,
               "empresas": [{"nome": c["nome"], "ticker": c["ticker"]} for c in cos]}
    (OUT / "history").mkdir(parents=True, exist_ok=True)
    s = json.dumps(payload, ensure_ascii=False, indent=1)
    (OUT / "news.json").write_text(s, encoding="utf-8")
    (OUT / "history" / f"{now:%Y-%m-%d}.json").write_text(s, encoding="utf-8")
    ok = sum(1 for r in report if not r["erro"])
    print(f"consultas ok: {ok}/{len(report)} | eventos: {len(out)} | alta: {sum(e['relevancia']=='alta' for e in out)}")
    if ok == 0 and not os.environ.get("RADAR_OFFLINE"): sys.exit(1)

if __name__ == "__main__": main()
