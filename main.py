import ccxt
import time
from datetime import datetime
from dotenv import load_dotenv
import os
import plotly.graph_objects as go

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Ciclo Infinito Expert", layout="wide")
load_dotenv()

# --- CONEXÃO BINANCE ---
@st.cache_resource
def conectar_binance():
    exchange = ccxt.binance({
        'apiKey': os.getenv('API_KEY'),
        'secret': os.getenv('API_SECRET'),
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    # exchange.set_sandbox_mode(True)  # se quiser testnet, ativa aqui
    return exchange

def obter_saldo_usdc():
    try:
        exchange = conectar_binance()
        balance = exchange.fetch_balance()
        return balance.get('USDC', {}).get('free', 0.0)
    except Exception:
        return 0.0

# --- ANÁLISE TÉCNICA ---
def obter_dados_expert(par, tf):
    exchange = conectar_binance()
    bars = exchange.fetch_ohlcv(par, timeframe=tf, limit=200)

    df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
    df['time'] = pd.to_datetime(df['time'], unit='ms')

    df['rsi'] = ta.rsi(df['close'], length=14)
    df['vol_media'] = ta.sma(df['vol'], length=20)

    df['vol_buy'] = df.apply(lambda x: x['vol'] if x['close'] > x['open'] else 0, axis=1)
    df['vol_sell'] = df.apply(lambda x: x['vol'] if x['close'] < x['open'] else 0, axis=1)

    bb = ta.bbands(df['close'], length=20, std=2)
    df = pd.concat([df, bb], axis=1)

    col_bbl = [c for c in df.columns if c.startswith("BBL")][0]
    col_bbu = [c for c in df.columns if c.startswith("BBU")][0]

    df["b_inf"] = df[col_bbl]
    df["b_sup"] = df[col_bbu]

    df['suporte_24'] = df['low'].rolling(window=24).min()

    return df, col_bbl, col_bbu

# --- CRITÉRIOS DE ENTRADA ---
def criterios_entrada_ok(rsi, p_atual, b_inf, vol_buy, vol_sell,
                         usar_rsi, usar_banda, usar_volume):
    condicoes = []
    if usar_rsi:
        condicoes.append(rsi < 40)
    if usar_banda:
        condicoes.append(p_atual <= b_inf)
    if usar_volume:
        condicoes.append(vol_buy > vol_sell)
    if not condicoes:
        return False
    return all(condicoes)

# --- ESTADO INICIAL ---
if 'posicao' not in st.session_state:
    st.session_state.posicao = False
if 'preco_medio' not in st.session_state:
    st.session_state.preco_medio = 0.0
if 'fatias_usadas' not in st.session_state:
    st.session_state.fatias_usadas = 0
if 'max_price' not in st.session_state:
    st.session_state.max_price = 0.0
if 'historico' not in st.session_state:
    st.session_state.historico = []
if 'operacoes' not in st.session_state:
    st.session_state.operacoes = []
if 'saldo' not in st.session_state:
    st.session_state.saldo = obter_saldo_usdc()
if 'qtd_total' not in st.session_state:
    st.session_state.qtd_total = 0.0

# --- PAINEL LATERAL ---
st.sidebar.header("🕹️ Configuração do Ciclo")

paridade = st.sidebar.selectbox(
    "Moeda",
    [
        "BTC/USDC", "ETH/USDC", "BNB/USDC", "SOL/USDC", "XRP/USDC",
        "ADA/USDC", "AVAX/USDC", "DOGE/USDC", "DOT/USDC", "TRX/USDC",
        "LINK/USDC", "MATIC/USDC", "ATOM/USDC", "LTC/USDC", "UNI/USDC",
        "XLM/USDC", "ETC/USDC", "FIL/USDC", "APT/USDC", "NEAR/USDC"
    ],
    index=0
)

tf_usuario = st.sidebar.selectbox("Tempo da Vela", ["15m", "30m", "1h"], index=0)
n_fatias = st.sidebar.slider("Máximo de Fatias (DCA)", 2, 12, 10)
lucro_alvo = st.sidebar.slider("Lucro Alvo Mínimo (%)", 0.5, 5.0, 1.5) / 100
recuo_padrao = st.sidebar.slider("Recuo Trailing (%)", 0.1, 2.0, 0.5) / 100

st.sidebar.subheader("🎯 Critérios de Entrada")
usar_rsi = st.sidebar.checkbox("RSI < 40", value=True)
usar_banda = st.sidebar.checkbox("Tocar Banda Inferior", value=True)
usar_volume = st.sidebar.checkbox("Volume Comprador > Vendedor", value=True)

status_active = st.sidebar.toggle("🚀 INICIAR ROBÔ")

# --- DADOS DE MERCADO ---
df, col_bbl, col_bbu = obter_dados_expert(paridade, tf_usuario)

p_atual = df['close'].iloc[-1]
rsi = df['rsi'].iloc[-1]
vol_buy = df['vol_buy'].iloc[-1]
vol_sell = df['vol_sell'].iloc[-1]
vol_med = df['vol_media'].iloc[-1]
b_inf = df["b_inf"].iloc[-1]
b_sup = df["b_sup"].iloc[-1]
suporte = df['suporte_24'].iloc[-1]

# --- CÁLCULO DAS FATIAS (BASEADO NO SALDO ATUAL) ---
if n_fatias > 0:
    valor_fatia_bruto = st.session_state.saldo / n_fatias
else:
    valor_fatia_bruto = 0.0

valor_fatia_liquido = valor_fatia_bruto * (1 - 0.003)  # taxa 0.3%

# --- TÍTULO E MÉTRICAS ---
st.title("🤖 Ciclo Infinito Expert — Binance USDC")

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Preço Atual", f"${p_atual:,.4f}")
c2.metric("RSI", f"{rsi:.1f}")
c3.metric("Volume Buy", f"{vol_buy:,.2f}")
c4.metric("Volume Sell", f"{vol_sell:,.2f}")
c5.metric("Fatias", f"{st.session_state.fatias_usadas}/{n_fatias}")
c6.metric("Saldo (USDC)", f"{st.session_state.saldo:,.2f}")

# --- PAINEL DE POSIÇÃO ---
st.subheader("📦 Posição Atual")

if st.session_state.posicao and st.session_state.qtd_total > 0:
    lucro_pct = ((p_atual - st.session_state.preco_medio) / st.session_state.preco_medio) * 100
    lucro_usd = (p_atual - st.session_state.preco_medio) * st.session_state.qtd_total

    cA, cB, cC, cD = st.columns(4)
    cA.metric("Preço Médio", f"${st.session_state.preco_medio:,.4f}")
    cB.metric("Qtd (moeda)", f"{st.session_state.qtd_total:.6f}")
    cC.metric("Lucro (%)", f"{lucro_pct:.2f}%")
    cD.metric("Lucro (USDC)", f"${lucro_usd:,.2f}")
else:
    st.info("Nenhuma posição aberta no momento.")

# --- VENDA FORÇADA AO DESLIGAR ---
if not status_active and st.session_state.posicao and st.session_state.qtd_total > 0:
    agora = datetime.now().strftime('%H:%M:%S')
    valor_venda = st.session_state.qtd_total * p_atual
    st.session_state.saldo += valor_venda

    st.session_state.historico.append(
        f"[{agora}] 🛑 VENDA MANUAL AO DESLIGAR — Preço: ${p_atual:.4f} | Valor: ${valor_venda:,.2f}"
    )
    st.session_state.operacoes.append({
        "time": df['time'].iloc[-1],
        "price": p_atual,
        "tipo": "venda",
        "descricao": "Venda ao desligar robô"
    })

    st.session_state.posicao = False
    st.session_state.fatias_usadas = 0
    st.session_state.preco_medio = 0.0
    st.session_state.max_price = 0.0
    st.session_state.qtd_total = 0.0

# --- LÓGICA DO ROBÔ ---
if status_active:
    agora = datetime.now().strftime('%H:%M:%S')

    # 1. ENTRADA AUTOMÁTICA AO ATIVAR (se não houver posição)
    if not st.session_state.posicao and st.session_state.fatias_usadas == 0:
        if valor_fatia_liquido > 0 and st.session_state.saldo >= valor_fatia_liquido:
            qtd = valor_fatia_liquido / p_atual
            st.session_state.saldo -= valor_fatia_liquido

            st.session_state.posicao = True
            st.session_state.preco_medio = p_atual
            st.session_state.fatias_usadas = 1
            st.session_state.max_price = p_atual
            st.session_state.qtd_total = qtd

            st.session_state.historico.append(
                f"[{agora}] 🛒 ENTRADA AUTOMÁTICA — Preço: ${p_atual:.4f} | Qtd: {qtd:.6f}"
            )
            st.session_state.operacoes.append({
                "time": df['time'].iloc[-1],
                "price": p_atual,
                "tipo": "compra",
                "descricao": "Entrada automática"
            })

    # 2. ENTRADA INICIAL COM CRITÉRIOS
    elif not st.session_state.posicao:
        if criterios_entrada_ok(
            rsi, p_atual, b_inf, vol_buy, vol_sell,
            usar_rsi, usar_banda, usar_volume
        ):
            if valor_fatia_liquido > 0 and st.session_state.saldo >= valor_fatia_liquido:
                qtd = valor_fatia_liquido / p_atual
                st.session_state.saldo -= valor_fatia_liquido

                st.session_state.posicao = True
                st.session_state.preco_medio = p_atual
                st.session_state.fatias_usadas = 1
                st.session_state.max_price = p_atual
                st.session_state.qtd_total = qtd

                st.session_state.historico.append(
                    f"[{agora}] 🛒 ENTRADA INICIAL (CRITÉRIOS) — Preço: ${p_atual:.4f} | Qtd: {qtd:.6f}"
                )
                st.session_state.operacoes.append({
                    "time": df['time'].iloc[-1],
                    "price": p_atual,
                    "tipo": "compra",
                    "descricao": "Entrada inicial"
                })

    # 3. RECOMPRAS (DCA)
    elif st.session_state.posicao and st.session_state.fatias_usadas < n_fatias:
        if p_atual <= suporte and rsi < 30 and vol_sell > vol_buy:
            if valor_fatia_liquido > 0 and st.session_state.saldo >= valor_fatia_liquido:
                qtd = valor_fatia_liquido / p_atual
                st.session_state.saldo -= valor_fatia_liquido

                qtd_antiga = st.session_state.qtd_total
                preco_antigo = st.session_state.preco_medio

                novo_qtd_total = qtd_antiga + qtd
                novo_preco_medio = (
                    (preco_antigo * qtd_antiga) + (p_atual * qtd)
                ) / novo_qtd_total

                st.session_state.qtd_total = novo_qtd_total
                st.session_state.preco_medio = novo_preco_medio
                st.session_state.fatias_usadas += 1

                st.session_state.historico.append(
                    f"[{agora}] 📉 RECOMPRA — Fatia {st.session_state.fatias_usadas} | "
                    f"Preço: ${p_atual:.4f} | Qtd: {qtd:.6f} | Médio: ${novo_preco_medio:.4f}"
                )
                st.session_state.operacoes.append({
                    "time": df['time'].iloc[-1],
                    "price": p_atual,
                    "tipo": "compra",
                    "descricao": f"Recompra fatia {st.session_state.fatias_usadas}"
                })

    # 4. SAÍDA (VENDA)
    if st.session_state.posicao and st.session_state.qtd_total > 0:
        lucro_real = (p_atual - st.session_state.preco_medio) / st.session_state.preco_medio
        lucro_pct = lucro_real * 100
        lucro_usd = (p_atual - st.session_state.preco_medio) * st.session_state.qtd_total

        # 4.1 VENDA POR CLÍMAX
        if lucro_real >= lucro_alvo and vol_buy > vol_med * 2 and p_atual >= b_sup:
            valor_venda = st.session_state.qtd_total * p_atual
            st.session_state.saldo += valor_venda

            st.session_state.historico.append(
                f"[{agora}] 💰 VENDA CLÍMAX — Lucro: {lucro_pct:.2f}% | "
                f"${lucro_usd:,.2f} | Valor: ${valor_venda:,.2f}"
            )
            st.session_state.operacoes.append({
                "time": df['time'].iloc[-1],
                "price": p_atual,
                "tipo": "venda",
                "descricao": "Venda clímax"
            })

            st.session_state.posicao = False
            st.session_state.fatias_usadas = 0
            st.session_state.preco_medio = 0.0
            st.session_state.max_price = 0.0
            st.session_state.qtd_total = 0.0
            st.balloons()

        else:
            # 4.2 TRAILING STOP
            if p_atual > st.session_state.max_price:
                st.session_state.max_price = p_atual

            recuo = 0.003 if vol_sell > vol_buy else recuo_padrao

            if p_atual <= st.session_state.max_price * (1 - recuo):
                valor_venda = st.session_state.qtd_total * p_atual
                st.session_state.saldo += valor_venda

                st.session_state.historico.append(
                    f"[{agora}] 💰 VENDA TRAILING — Lucro: {lucro_pct:.2f}% | "
                    f"${lucro_usd:,.2f} | Valor: ${valor_venda:,.2f}"
                )
                st.session_state.operacoes.append({
                    "time": df['time'].iloc[-1],
                    "price": p_atual,
                    "tipo": "venda",
                    "descricao": "Venda trailing"
                })

                st.session_state.posicao = False
                st.session_state.fatias_usadas = 0
                st.session_state.preco_medio = 0.0
                st.session_state.max_price = 0.0
                st.session_state.qtd_total = 0.0
                st.balloons()

# --- GRÁFICO PRINCIPAL ---
st.subheader("📈 Candlesticks, Bandas, Suporte/Resistência e Operações")

df_plot = df.set_index("time").tail(200)

fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=df_plot.index,
    open=df_plot["open"],
    high=df_plot["high"],
    low=df_plot["low"],
    close=df_plot["close"],
    name="Candles",
    increasing_line_color="#26A69A",
    decreasing_line_color="#EF5350",
    increasing_fillcolor="#26A69A",
    decreasing_fillcolor="#EF5350",
    opacity=0.9
))

fig.add_trace(go.Scatter(
    x=df_plot.index,
    y=df_plot[col_bbl],
    mode="lines",
    name="Banda Inferior",
    line=dict(color="#FFD54F", width=1, dash="dot")
))

fig.add_trace(go.Scatter(
    x=df_plot.index,
    y=df_plot[col_bbu],
    mode="lines",
    name="Banda Superior",
    line=dict(color="#FF8A65", width=1, dash="dot")
))

suporte_auto = df_plot["low"].tail(50).min()
resistencia_auto = df_plot["high"].tail(50).max()

fig.add_hline(
    y=suporte_auto,
    line=dict(color="#00E676", width=2, dash="dot"),
    annotation_text="Suporte",
    annotation_position="bottom right"
)

fig.add_hline(
    y=resistencia_auto,
    line=dict(color="#FF1744", width=2, dash="dot"),
    annotation_text="Resistência",
    annotation_position="top right"
)

if st.session_state.posicao and st.session_state.qtd_total > 0:
    preco_medio = st.session_state.preco_medio
    fig.add_trace(go.Scatter(
        x=df_plot.index,
        y=[preco_medio] * len(df_plot),
        mode="lines",
        name="Preço Médio",
        line=dict(color="#00E5FF", width=2, dash="dash")
    ))

df_ops = pd.DataFrame(st.session_state.operacoes)

if not df_ops.empty:
    compras = df_ops[df_ops["tipo"] == "compra"]
    vendas = df_ops[df_ops["tipo"] == "venda"]

    if not compras.empty:
        fig.add_trace(go.Scatter(
            x=compras["time"],
            y=compras["price"],
            mode="markers",
            name="Compras",
            marker=dict(symbol="triangle-up", size=14, color="#00FF00"),
            text=compras["descricao"],
            hovertemplate="Compra<br>Preço: %{y:.4f}<br>%{text}<extra></extra>"
        ))

    if not vendas.empty:
        fig.add_trace(go.Scatter(
            x=vendas["time"],
            y=vendas["price"],
            mode="markers",
            name="Vendas",
            marker=dict(symbol="triangle-down", size=14, color="#FF1744"),
            text=vendas["descricao"],
            hovertemplate="Venda<br>Preço: %{y:.4f}<br>%{text}<extra></extra>"
        ))

fig.update_layout(
    xaxis_title="Tempo",
    yaxis_title="Preço",
    template="plotly_dark",
    height=520,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    plot_bgcolor="#111111",
    paper_bgcolor="#111111"
)

st.plotly_chart(fig, use_container_width=True)

# --- GRÁFICO DE VOLUME ---
st.subheader("📊 Volume Buy/Sell")
st.bar_chart(
    df.set_index("time")[['vol_buy', 'vol_sell']].tail(100)
)

# --- HISTÓRICO ---
st.subheader("📜 Histórico")
for log in reversed(st.session_state.historico):
    st.info(log)

time.sleep(5)
st.rerun()
