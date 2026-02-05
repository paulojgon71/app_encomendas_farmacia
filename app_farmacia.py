import streamlit as st
import pdfplumber
import pandas as pd
import math
import io

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Gestor de Encomendas Universal", layout="wide", page_icon="💊")

# --- BARRA LATERAL (CONFIGURAÇÕES) ---
with st.sidebar:
    st.header("⚙️ Configuração da Encomenda")
    
    # 1. Definição do Período de Análise (A CORREÇÃO ESTÁ AQUI)
    st.subheader("📅 Dados do PDF")
    meses_historico = st.number_input(
        "O PDF tem vendas de quantos meses?", 
        min_value=1, 
        value=1, 
        help="Se tirou um mapa de 3 meses, coloque 3 aqui para o cálculo da média ficar correto."
    )

    st.divider()

    # 2. Definição do Objetivo
    st.subheader("📦 Objetivo de Stock")
    meses_stock = st.number_input("Meses de Stock a cobrir:", min_value=1, value=1, step=1)
    
    st.divider()
    
    # 3. Definição da Campanha
    st.subheader("🎁 Campanhas / Condições")
    ativar_campanha = st.checkbox("Ativar Campanha de Quantidade (Mix)?", value=False)
    
    rule_buy = 10
    rule_offer = 3
    
    if ativar_campanha:
        col1, col2 = st.columns(2)
        with col1:
            rule_buy = st.number_input("Compra", min_value=1, value=10)
        with col2:
            rule_offer = st.number_input("Oferta", min_value=0, value=3)
        st.info(f"Regra: Compra {rule_buy}, Oferece {rule_offer}")

# --- FUNÇÕES ---

def clean_numbers(value):
    """Converte valores do PDF para números. Trata células com múltiplas linhas."""
    if not value: return 0
    try:
        # Pega apenas na primeira linha caso haja valores sobrepostos (ex: "2\n3")
        val_str = str(value).split('\n')[0]
        clean_val = val_str.strip().replace('€', '').replace(' ', '').replace(',', '.')
        return float(clean_val)
    except ValueError:
        return 0

def extract_data_from_pdf(file):
    """Lê o PDF e procura as colunas de Vendas e Stock automaticamente."""
    all_rows = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_table()
            if tables:
                all_rows.extend(tables)
    
    if not all_rows: return None

    df = pd.DataFrame(all_rows)
    
    # Procura cabeçalhos
    header_idx = -1
    col_map = {'desc': -1, 'vendas': -1, 'stock': -1}
    
    # Varre as primeiras 15 linhas à procura do cabeçalho
    for i, row in df.head(15).iterrows():
        row_str = [str(c).lower() if c else "" for c in row]
        
        has_desc = any("descri" in s for s in row_str)
        # Procura "Tot. Ven." ou "Vendas"
        has_vendas = any(("tot" in s and "ven" in s) for s in row_str)
        has_exist = any("exist" in s for s in row_str)

        if has_desc and has_vendas:
            header_idx = i
            for col_i, val in enumerate(row_str):
                if "descri" in val: col_map['desc'] = col_i
                if "tot" in val and "ven" in val: col_map['vendas'] = col_i
                if "exist" in val: col_map['stock'] = col_i
            break
    
    if header_idx == -1 or col_map['vendas'] == -1:
        st.error("Não foi possível encontrar a coluna 'Tot. Ven.' no PDF.")
        return None

    # Cria o DataFrame limpo
    df_clean = df.iloc[header_idx+1:].copy()
    df_clean = df_clean.iloc[:, [col_map['desc'], col_map['vendas'], col_map['stock']]]
    df_clean.columns = ['Descricao', 'Vendas', 'Stock']
    
    return df_clean

def calculate_order(df, meses_hist, meses_target, use_campaign, buy_qty, offer_qty):
    # Limpar números
    df['Vendas'] = df['Vendas'].apply(clean_numbers)
    df['Stock'] = df['Stock'].apply(clean_numbers)
    
    # Remover linhas vazias ou totais
    df = df[ (df['Vendas'] > 0) | (df['Stock'] > 0) ].copy()

    # --- LÓGICA CORRIGIDA ---
    # 1. Calcular Venda Média Mensal
    df['Venda_Media_Mensal'] = df['Vendas'] / meses_hist
    
    # 2. Calcular Necessidade para o futuro
    df['Necessidade_Estrita'] = (df['Venda_Media_Mensal'] * meses_target) - df['Stock']
    df['Necessidade_Estrita'] = df['Necessidade_Estrita'].apply(lambda x: x if x > 0 else 0)
    
    # Arredondar a necessidade para cima (não pedimos 1.5 caixas)
    df['Necessidade_Arredondada'] = df['Necessidade_Estrita'].apply(math.ceil)
    
    total_need = df['Necessidade_Arredondada'].sum()
    df['Encomenda_Final'] = df['Necessidade_Arredondada']
    
    # 3. Campanha
    missing_units = 0
    total_offers = 0
    
    if use_campaign and total_need > 0:
        target_buy = math.ceil(total_need / buy_qty) * buy_qty
        if target_buy == 0: target_buy = buy_qty
            
        missing_units = target_buy - total_need
        total_offers = int((target_buy / buy_qty) * offer_qty)
        
        if missing_units > 0:
            df = df.sort_values(by='Vendas', ascending=False)
            if not df.empty:
                df.iloc[0, df.columns.get_loc('Encomenda_Final')] += missing_units
        
        total_enc = target_buy
    else:
        total_enc = total_need

    return df, total_enc, total_offers, missing_units

# --- INTERFACE ---

st.title("💊 Gestor de Encomendas Universal")

uploaded_file = st.file_uploader("📂 Arraste o PDF de Vendas aqui", type="pdf")

if uploaded_file is not None:
    df_raw = extract_data_from_pdf(uploaded_file)
    
    if df_raw is not None:
        df_final, total, ofertas, extra = calculate_order(
            df_raw, 
            meses_historico, 
            meses_stock, 
            ativar_campanha, 
            rule_buy, 
            rule_offer
        )
        
        # Métricas
        col1, col2, col3 = st.columns(3)
        col1.metric("Média Vendas/Mês (Global)", f"{df_final['Venda_Media_Mensal'].sum():.1f}")
        col2.metric("Total a Encomendar", f"{int(total)}")
        if ativar_campanha:
            col3.metric("Ofertas", f"{ofertas}")
            
        if extra > 0:
            st.info(f"Foram adicionadas {int(extra)} unidades para fechar a campanha.")

        # Tabela
        st.subheader("Sugestão Detalhada")
        st.dataframe(
            df_final[df_final['Encomenda_Final'] > 0][['Descricao', 'Vendas', 'Stock', 'Venda_Media_Mensal', 'Encomenda_Final']],
            use_container_width=True
        )
        
        # Excel
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_final[df_final['Encomenda_Final'] > 0].to_excel(writer, index=False)
            
        st.download_button("📥 Baixar Excel", buffer.getvalue(), "encomenda.xlsx")
