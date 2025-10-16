import streamlit as st
import pandas as pd
import json
from pathlib import Path

# ===================== CONFIG BÁSICA =====================
st.set_page_config(page_title="Painel de Bônus - LOG (T3)", layout="wide")
st.title("🚀 Painel de Bônus Trimestral - LOG")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# ===================== MAPA DE SUPERVISORES =====================
SUPERVISORES_CIDADES = {
    "MARTA OLIVEIRA COSTA RAMOS": {"SÃO LUÍS": 0.10, "CAROLINA": 0.10},
    "ELEILSON DE SOUSA ADELINO": {
        "TIMON": 0.0666,
        "PRESIDENTE DUTRA": 0.0666,
        "AÇAILÂNDIA": 0.0666
    }
}

# ===================== CARREGAMENTO ======================
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

try:
    PESOS = load_json(DATA_DIR / "pesos_log.json")
    INDICADORES = load_json(DATA_DIR / "empresa_indicadores_log.json")
except Exception as e:
    st.error(f"Erro ao carregar JSONs: {e}")
    st.stop()

MESES = ["TRIMESTRE", "JULHO", "AGOSTO", "SETEMBRO"]
filtro_mes = st.radio("📅 Selecione o mês:", MESES, horizontal=True)

def ler_planilha(mes: str) -> pd.DataFrame:
    return pd.read_excel(DATA_DIR / "RESUMO PARA PAINEL - LOG.xlsx", sheet_name=mes)

def up(x):
    return "" if pd.isna(x) else str(x).strip().upper()

def texto_obs(valor):
    if pd.isna(valor):
        return ""
    s = str(valor).strip()
    if s.lower() in ["none", "nan", ""]:
        return ""
    return s

def int_safe(x):
    try:
        return int(float(x))
    except Exception:
        return 0

# ===================== REGRAS (por mês) ==================
LIMITE_TOTAL = 7
LIMITE_GRAVES = 5

def pct_qualidade_vistoriador(erros_total, erros_graves):
    et = 0 if pd.isna(erros_total) else float(erros_total)
    eg = 0 if pd.isna(erros_graves) else float(erros_graves)
    total_ok = et <= LIMITE_TOTAL
    graves_ok = eg <= LIMITE_GRAVES
    if total_ok and graves_ok:
        return 1.0
    if (not total_ok and graves_ok) or (total_ok and not graves_ok):
        return 0.5
    return 0.0

def elegivel(valor_meta, obs):
    obs_u = up(obs)
    if pd.isna(valor_meta) or float(valor_meta) == 0:
        return False, "Sem elegibilidade no mês"
    if "LICEN" in obs_u:
        return False, "Licença no mês"
    return True, ""

# ===================== CÁLCULO MENSAL ====================
def calcula_mes(df_mes, nome_mes):
    ind_mes = INDICADORES[nome_mes]
    df = df_mes.copy()
    df["_FUNCAO_UP"] = df["FUNÇÃO"].apply(up)
    df["_CIDADE_UP"] = df["CIDADE"].apply(up)
    df["_NOME_UP"]   = df["NOME"].apply(up)

    def calcula_recebido(row):
        func = up(row["FUNÇÃO"])
        cidade = up(row["CIDADE"])
        nome  = up(row.get("NOME", ""))
        obs = row.get("OBSERVAÇÃO", "")
        valor_meta = row.get("VALOR MENSAL META", 0)

        ok, motivo = elegivel(valor_meta, obs)
        perdeu_itens = []

        if not ok:
            return pd.Series({
                "MES": nome_mes, "META": 0.0, "RECEBIDO": 0.0, "PERDA": 0.0, "%": 0.0,
                "_badge": motivo, "_obs": texto_obs(obs), "perdeu_itens": perdeu_itens
            })

        metainfo = PESOS.get(func, {})
        total_func = float(metainfo.get("total", valor_meta))
        itens = metainfo.get("metas", {})

        recebido, perdas = 0.0, 0.0

        for item, peso in itens.items():
            parcela = total_func * float(peso)

            # PRODUÇÃO — regra especial
            if item.startswith("Produção"):
                if func == "SUPERVISOR" and nome in SUPERVISORES_CIDADES:
                    cidades_resp = SUPERVISORES_CIDADES[nome]
                    base_soma = sum(cidades_resp.values()) or 1.0
                    perda_total, perdas_cidades = 0.0, []
                    for cid, peso_cid in cidades_resp.items():
                        bateu = ind_mes["producao_por_cidade"].get(cid, True)
                        parcela_cid = parcela * (peso_cid / base_soma)
                        if not bateu:
                            perda_total += parcela_cid
                            perdas_cidades.append(cid)
                    recebido += parcela - perda_total
                    perdas += perda_total
                    if perdas_cidades:
                        perdeu_itens.append("Produção – " + ", ".join(perdas_cidades))
                else:
                    bateu_prod = ind_mes["producao_por_cidade"].get(cidade, True)
                    if bateu_prod:
                        recebido += parcela
                    else:
                        perdas += parcela
                        perdeu_itens.append("Produção – " + cidade.title())
                continue

            # QUALIDADE
            if item == "Qualidade":
                if func == "VISTORIADOR":
                    et = int_safe(row.get("ERROS TOTAL", 0))
                    eg = int_safe(row.get("ERROS GG", 0))
                    frac = pct_qualidade_vistoriador(et, eg)
                    if frac == 1.0:
                        recebido += parcela
                        perdeu_itens.append(f"Qualidade (100%) — erros: {et} | graves: {eg}")
                    elif frac == 0.5:
                        recebido += parcela * 0.5
                        perdas += parcela * 0.5
                        perdeu_itens.append(f"Qualidade (50%) — erros: {et} | graves: {eg}")
                    else:
                        perdas += parcela
                        perdeu_itens.append(f"Qualidade (0%) — erros: {et} | graves: {eg}")
                else:
                    if not ind_mes["qualidade"]:
                        perdas += parcela
                        perdeu_itens.append("Qualidade")
                    else:
                        recebido += parcela
                continue

            # LUCRATIVIDADE
            if item == "Lucratividade":
                if ind_mes["financeiro"]:
                    recebido += parcela
                else:
                    perdas += parcela
                    perdeu_itens.append("Lucratividade")
                continue

            # demais itens
            recebido += parcela

        meta = total_func
        perc = 0 if meta == 0 else (recebido / meta) * 100
        return pd.Series({
            "MES": nome_mes, "META": meta, "RECEBIDO": recebido, "PERDA": perdas,
            "%": perc, "_badge": "", "_obs": texto_obs(obs), "perdeu_itens": perdeu_itens
        })

    calc = df.apply(calcula_recebido, axis=1)
    return pd.concat([df.reset_index(drop=True), calc], axis=1)

# ===================== LEITURA MÚLTIPLA =====================
if filtro_mes == "TRIMESTRE":
    df_j, df_a, df_s = [ler_planilha(m) for m in ["JULHO", "AGOSTO", "SETEMBRO"]]
    st.success("✅ Planilhas carregadas com sucesso!")
    dados_full = pd.concat([
        calcula_mes(df_j, "JULHO"),
        calcula_mes(df_a, "AGOSTO"),
        calcula_mes(df_s, "SETEMBRO")
    ], ignore_index=True)

    group_cols = ["CIDADE", "NOME", "FUNÇÃO", "DATA DE ADMISSÃO", "TEMPO DE CASA"]
    agg = dados_full.groupby(group_cols, dropna=False).agg({
        "META": "sum", "RECEBIDO": "sum", "PERDA": "sum",
        "_obs": lambda x: ", ".join({s for s in x if s}),
        "_badge": lambda x: " / ".join({s for s in x if s})
    }).reset_index()
    agg["%"] = agg.apply(lambda r: 0 if r["META"] == 0 else (r["RECEBIDO"]/r["META"])*100, axis=1)
    perdas_pessoa = (
        dados_full.assign(_lost=lambda d: d.apply(
            lambda r: [f"{it} ({r['MES']})" for it in r["perdeu_itens"]],
            axis=1))
        .groupby(group_cols, dropna=False)["_lost"]
        .sum()
        .apply(lambda L: ", ".join(sorted(set(L))))
        .reset_index()
        .rename(columns={"_lost": "INDICADORES_NAO_ENTREGUES"})
    )
    dados_calc = agg.merge(perdas_pessoa, on=group_cols, how="left").fillna("")
else:
    df_mes = ler_planilha(filtro_mes)
    st.success(f"✅ Planilha de {filtro_mes} carregada!")
    dados_calc = calcula_mes(df_mes, filtro_mes)
    dados_calc["INDICADORES_NAO_ENTREGUES"] = dados_calc["perdeu_itens"].apply(
        lambda L: ", ".join(L) if isinstance(L, list) and L else ""
    )

# ===================== FILTROS =====================
st.markdown("### 🔎 Filtros")
col1, col2, col3, col4 = st.columns(4)
with col1:
    filtro_nome = st.text_input("Buscar por nome (contém)", "")
with col2:
    funcoes_validas = [f for f in dados_calc["FUNÇÃO"].dropna().unique() if up(f) in PESOS.keys()]
    filtro_funcao = st.selectbox("Função", ["Todas"] + sorted(funcoes_validas))
with col3:
    cidades = ["Todas"] + sorted(dados_calc["CIDADE"].dropna().unique())
    filtro_cidade = st.selectbox("Cidade", cidades)
with col4:
    tempos = ["Todos"] + sorted(dados_calc["TEMPO DE CASA"].dropna().unique())
    filtro_tempo = st.selectbox("Tempo de casa", tempos)

dados_view = dados_calc.copy()
if filtro_nome:
    dados_view = dados_view[dados_view["NOME"].str.contains(filtro_nome, case=False, na=False)]
if filtro_funcao != "Todas":
    dados_view = dados_view[dados_view["FUNÇÃO"] == filtro_funcao]
if filtro_cidade != "Todas":
    dados_view = dados_view[dados_view["CIDADE"] == filtro_cidade]
if filtro_tempo != "Todos":
    dados_view = dados_view[dados_view["TEMPO DE CASA"] == filtro_tempo]

# ===================== RESUMO =====================
st.markdown("### 📊 Resumo Geral")
colA, colB, colC = st.columns(3)
with colA: st.success(f"💰 Total possível: R$ {dados_view['META'].sum():,.2f}")
with colB: st.info(f"📈 Recebido: R$ {dados_view['RECEBIDO'].sum():,.2f}")
with colC: st.error(f"📉 Deixou de ganhar: R$ {dados_view['PERDA'].sum():,.2f}")

# ===================== CARDS =====================
st.markdown("### 👥 Colaboradores")
cols = st.columns(3)
dados_view = dados_view.sort_values(by="%", ascending=False)

for idx, row in dados_view.iterrows():
    pct = float(row["%"])
    meta = float(row["META"])
    recebido = float(row["RECEBIDO"])
    perdido = float(row["PERDA"])
    badge = row.get("_badge", "")
    obs_txt = texto_obs(row.get("_obs", ""))
    perdidos_txt = texto_obs(row.get("INDICADORES_NAO_ENTREGUES", ""))

    bg = "#f9f9f9" if not badge else "#eeeeee"
    with cols[idx % 3]:
        st.markdown(f"""
        <div style="border:1px solid #ccc;padding:16px;border-radius:12px;margin-bottom:12px;background:{bg}">
            <h4>{row['NOME'].title()}</h4>
            <p><strong>{row['FUNÇÃO']}</strong> — {row['CIDADE']}</p>
            <p><strong>Meta {'Trimestral' if filtro_mes=='TRIMESTRE' else 'Mensal'}:</strong> R$ {meta:,.2f}<br>
            <strong>Recebido:</strong> R$ {recebido:,.2f}<br>
            <strong>Deixou de ganhar:</strong> R$ {perdido:,.2f}<br>
            <strong>Cumprimento:</strong> {pct:.1f}%</p>
            <div style="height: 10px; background: #ddd; border-radius: 5px;">
                <div style="width:{pct:.1f}%; background:black; height:100%;"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if badge:
            st.caption(f"⚠️ {badge}")
        if obs_txt:
            st.caption(f"🗒️ {obs_txt}")
        if perdidos_txt and "100%" not in perdidos_txt:
            st.caption(f"🔻 Indicadores não entregues: {perdidos_txt}")