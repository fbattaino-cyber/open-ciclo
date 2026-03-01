import ccxt
import pandas as pd
import pandas_ta as ta
import time
import os
from datetime import datetime
from dotenv import load_dotenv
import plotly.graph_objects as go

# --- CONFIGURAÇÃO INICIAL ---
load_dotenv()

def conectar_binance():
    exchange = ccxt.binance({
        'apiKey': os.getenv('API_KEY'),
        'secret': os.getenv('API_SECRET'),
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    # exchange.set_sandbox_mode(True) # Descomente para usar a Testnet (dinheiro fictício)
    return exchange

def obter_saldo_real(exchange, moeda='USDC'):
    try:
        balance = exchange.fetch_balance()
        return balance.get(moeda, {}).get('free', 0.0)
    except Exception as e:
        print(f"Erro ao obter saldo: {e}")
        return 0.0

def obter_dados_expert(exchange, par, tf):
    try:
        bars = exchange.fetch_ohlcv(par, timeframe=tf, limit=100)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')

        # Indicadores
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['vol_media'] = ta.sma(df['vol'], length=20)
        df['vol_buy'] = df.apply(lambda x: x['vol'] if x['close'] > x['open'] else 0, axis=1)
        df['vol_sell'] = df.apply(lambda x: x['vol'] if x['close'] < x['open'] else 0, axis=1)
        
        bb = ta.bbands(df['close'], length=20, std=2)
        df = pd.concat([df, bb], axis=1)
        
        # Mapeamento dinâmico das bandas (evita erro de nome de coluna)
        col_bbl = [c for c in df.columns if c.startswith("BBL")][0]
        col_bbu = [c for c in df.columns if c.startswith("BBU")][0]
        df["b_inf"] = df[col_bbl]
        df["b_sup"] = df[col_bbu]
        df['suporte_24'] = df['low'].rolling(window=24).min()
        
        return df
    except Exception as e:
        print(f"Erro ao buscar dados: {e}")
        return None

def criterios_entrada_ok(rsi, p_atual, b_inf, vol_buy, vol_sell, usar_rsi, usar_banda, usar_volume):
    condicoes = []
    if usar_rsi: condicoes.append(rsi < 40)
    if usar_banda: condicoes.append(p_atual <= b_inf)
    if usar_volume: condicoes.append(vol_buy > vol_sell)
    return all(condicoes) if condicoes else False

# --- PARÂMETROS DO ROBÔ ---
paridade = "BTC/USDC"
tf_usuario = "15m"
n_fatias = 5
lucro_alvo = 0.015  # 1.5%
recuo_padrao = 0.005 # 0.5%
usar_rsi, usar_banda, usar_volume = True, True, True

# ESTADO DO ROBÔ (Persistência básica)
posicao = False
preco_medio = 0.0
fatias_usadas = 0
max_price = 0.0
qtd_total = 0.0

exchange = conectar_binance()

print(f"🚀 Robô Iniciado | Par: {paridade} | Timeframe: {tf_usuario}")

# --- LOOP PRINCIPAL ---
while True:
    try:
        agora = datetime.now().strftime('%H:%M:%S')
        df = obter_dados_expert(exchange, paridade, tf_usuario)
        
        if df is None:
            time.sleep(30)
            continue

        # Dados da última vela fechada
        atual = df.iloc[-1]
        p_atual = atual['close']
        rsi = atual['rsi']
        vol_buy, vol_sell, vol_med = atual['vol_buy'], atual['vol_sell'], atual['vol_media']
        b_inf, b_sup = atual['b_inf'], atual['b_sup']
        suporte = atual['suporte_24']

        saldo_usdc = obter_saldo_real(exchange, 'USDC')

        # LÓGICA DE ENTRADA / COMPRA
        if not posicao and fatias_usadas < n_fatias:
            if criterios_entrada_ok(rsi, p_atual, b_inf, vol_buy, vol_sell, usar_rsi, usar_banda, usar_volume):
                valor_fatia = saldo_usdc / (n_fatias - fatias_usadas)
                qtd_compra = valor_fatia / p_atual
                
                print(f"[{agora}] 🛒 ENVIANDO ORDEM DE COMPRA: {qtd_compra:.6f} {paridade}")
                # ORDEM REAL:
                # order = exchange.create_market_buy_order(paridade, qtd_compra)
                
                # Simulação (para teste):
                posicao = True
                fatias_usadas += 1
                qtd_total += qtd_compra
                preco_medio = p_atual
                max_price = p_atual
                print(f"[{agora}] ✅ Compra executada. Preço Médio: {preco_medio}")

        # LÓGICA DE RECOMPRA (DCA)
        elif posicao and fatias_usadas < n_fatias:
            if p_atual <= suporte and rsi < 30:
                valor_fatia = saldo_usdc / (n_fatias - fatias_usadas)
                qtd_compra = valor_fatia / p_atual
                
                print(f"[{agora}] 📉 RECOMPRA (DCA) - Fatia {fatias_usadas+1}")
                # exchange.create_market_buy_order(paridade, qtd_compra)
                
                preco_medio = ((preco_medio * qtd_total) + (p_atual * qtd_compra)) / (qtd_total + qtd_compra)
                qtd_total += qtd_compra
                fatias_usadas += 1

        # LÓGICA DE SAÍDA / VENDA
        if posicao:
            lucro_atual = (p_atual - preco_medio) / preco_medio
            if p_atual > max_price: max_price = p_atual

            # Venda Clímax ou Trailing Stop
            venda_climax = (lucro_atual >= lucro_alvo and vol_buy > vol_med * 2 and p_atual >= b_sup)
            trailing_stop = (p_atual <= max_price * (1 - recuo_padrao))

            if venda_climax or trailing_stop:
                motivo = "CLÍMAX" if venda_climax else "TRAILING STOP"
                print(f"[{agora}] 💰 VENDA EXECUTADA ({motivo}): Lucro {lucro_atual*100:.2f}%")
                
                # ORDEM REAL:
                # exchange.create_market_sell_order(paridade, qtd_total)
                
                # Reset de estado
                posicao = False
                fatias_usadas = 0
                qtd_total = 0.0
                preco_medio = 0.0

        print(f"[{agora}] Preço: {p_atual:.2f} | RSI: {rsi:.1f} | Posicionado: {posicao}")
        
    except Exception as e:
        print(f"❌ ERRO NO CICLO: {e}")
    
    time.sleep(60) # Espera 1 minuto para o próximo ciclo