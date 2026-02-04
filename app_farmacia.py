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
    
    # 1. Definição de Meses de Stock
    meses_stock = st.number_input("Meses de Stock a cobrir:", min_value=1, value=1, step=1)
    
    st.divider()
    
    # 2. Definição da Campanha
    st.subheader("🎁 Campanhas / Condições")
    ativar_campanha = st.checkbox("Ativar Campanha de Quantidade (Mix)?", value=False)
    
    rule_buy = 10
    rule_offer = 3
    
    if ativar_campanha:
        col1, col2 = st.columns(2)
        with col1:
            rule_buy = st.number_input("Compra", min_value=1, value=10, help="Qtd necessária para ganhar oferta")
        with col2:
            rule_offer = st.number_input("Oferta", min_value=0, value=3, help="Qtd oferecida")
        st.info(f"Regra ativa: Compra {rule_buy}, Oferece {rule_offer}")
    else:
        st.write("Modo: Reposição Simples (Sem ofertas calculadas)")

# --- CORPO PRINCIPAL ---
st.title("💊 Gestor de Encomendas Universal")
st.markdown(f"""
Esta aplicação gera sugestões de encomenda baseadas no PDF 'Mapa de Evolução de Vendas'.
**Laboratório atual:** {'Campanha Ativa' if ativar_campanha else 'Genérico / Sem Campanha'}
""")

# --- FUNÇÕES ---

def clean_numbers(value):
    """
    Limpa formatação de números.
    Trata casos onde linhas coladas aparecem como '3\n2' (pega no primeiro valor para segurança).
    """
    if not value: return 0
    try:
        # Se houver quebras de linha (linhas coladas), assume o primeiro valor
        val_str = str(value).split('\n')[0]
        
        clean_val = val_str.strip().replace('€', '').replace(' ', '').replace(',', '.')
        return float(clean_val) # Usa float para prevenir erros com decimais, depois converte-se
    except ValueError:
        return 0

def extract_data_from_pdf(file):
    """
    Extrai tabelas e procura dinamicamente as colunas certas pelo nome do cabeçalho.
    """
    all_rows = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_table()
            if tables:
                all_rows.extend(tables)
    
    if not all_rows:
        return None

    df = pd.DataFrame(all_rows)
    
    # 1. Procurar a linha de cabeçalho
    # Vamos varrer as primeiras 10 linhas à procura de palavras-chave
    header_idx = -1
    col_map = {'desc': -1, 'vendas': -1, 'stock': -1}
    
    for i, row in df.head(10).iterrows():
        # Converte tudo para minúsculas para facilitar a procura
        row_str = [str(c).lower() if c else "" for c in row]
        
        # Verifica se esta linha parece ser o cabeçalho (tem 'descri' e 'tot' e 'ven')
        # A verificação é flexível para apanhar "Tot. Ven.", "Tot Ven", etc.
        has_desc = any("descri" in s for s in row_str)
        has_vendas = any(("tot" in s and "ven" in s) for s in row_str)
        has_exist = any("exist" in s for s in row_str)

        if has_desc and has_vendas:
            header_idx = i
            # Agora mapeamos os índices das colunas
            for col_i, val in enumerate(row_str):
                if "descri" in val: col_map['desc'] = col_i
                if "tot" in val and "ven" in val: col_map['vendas'] = col_i
                if "exist" in val: col_map['stock'] = col_i
            break
    
    # Se não encontrarmos o cabeçalho, tentamos o fallback antigo (posições fixas)
    if header_idx == -1 or col_map['vendas'] == -1:
        st.warning("Aviso: Cabeçalhos não detetados automaticamente. A tentar posições padrão...")
        try:
             df_clean = df.iloc[:, [1, 6, 7]].copy() # Tenta 1, 6, 7
             df_clean.columns = ['Descricao', 'Vendas', 'Stock']
             # Remove a primeira linha se tiver texto
             return df_clean[1:]
        except:
            st.error("Erro crítico: Não foi possível ler as colunas do PDF.")
            return None

    # 2. Cortar o DF a partir do cabeçalho e selecionar colunas certas
    df_clean = df.iloc[header_idx+1:].copy()
    
    # Seleciona apenas as colunas que identificámos
    df_clean = df_clean.iloc[:, [col_map['desc'], col_map['vendas'], col_map['stock']]]
    df_clean.columns = ['Descricao', 'Vendas', 'Stock']
    
    return df_clean

def calculate_order(df, months, use_campaign, buy_qty, offer_qty):
    """Calcula a encomenda."""
    
    # Limpeza de dados
    df['Vendas'] = df['Vendas'].apply(clean_numbers)
    df['Stock'] = df['Stock'].apply(clean_numbers)
    
    # Filtrar produtos inválidos (Vendas 0 e Stock 0 geralmente são lixo de formatação)
    df = df[ (df['Vendas'] > 0) | (df['Stock'] > 0) ].copy()

    # 1. Cálculo da Necessidade Real
    df['Necessidade_Estrita'] = (df['Vendas'] * months) - df['Stock']
    df['Necessidade_Estrita'] = df['Necessidade_Estrita'].apply(lambda x: x if x > 0 else 0)
    
    total_need = df['Necessidade_Estrita'].sum()
    df['Encomenda_Final'] = df['Necessidade_Estrita']
    
    missing_units = 0
    total_offers = 0
    
    # 2. Aplicação de Campanha
    if use_campaign and total_need > 0:
        target_buy = math.ceil(total_need / buy_qty) * buy_qty
        
        # Garante patamar mínimo se houver necessidade
        if target_buy == 0 and total_need > 0:
            target_buy = buy_qty
            
        missing_units = target_buy - total_need
        total_offers = int((target_buy / buy_qty) * offer_qty)
        
        if missing_units > 0:
            # Ordena por vendas para adicionar stock aos produtos que mais rodam
            df = df.sort_values(by='Vendas', ascending=False)
            # Adiciona ao primeiro produto da lista
            if not df.empty:
                df.iloc[0, df.columns.get_loc('Encomenda_Final')] += missing_units
            
        total_enc = target_buy
    else:
        total_enc = total_need

    return df, total_enc, total_offers, missing_units

# --- INTERFACE DE UPLOAD ---

uploaded_file = st.file_uploader("📂 Arraste o PDF de Vendas aqui", type="pdf")

if uploaded_file is not None:
    with st.spinner('A processar dados...'):
        df_raw = extract_data_from_pdf(uploaded_file)
        
    if df_raw is not None and not df_raw.empty:
        # Processamento
        df_final, total_pedir, ofertas, adicionados = calculate_order(
            df_raw, 
            meses_stock, 
            ativar_campanha, 
            rule_buy, 
            rule_offer
        )
        
        # --- DASHBOARD ---
        st.markdown("### 📊 Resumo da Encomenda")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total a Pagar (un)", f"{int(total_pedir)}")
        col2.metric("Ofertas (un)", f"{ofertas}")
        col3.metric("Total Recebido", f"{int(total_pedir + ofertas)}")
        col4.metric("Cobertura", f"{meses_stock} Mês(es)")
        
        # Aviso se o sistema adicionou unidades
        if adicionados > 0:
            st.info(f"💡 Foram adicionadas **{int(adicionados)} unidades** para atingir o patamar da campanha e ganhar as ofertas.")

        # --- TABELA ---
        st.subheader("Detalhe dos Produtos")
        
        df_display = df_final[df_final['Encomenda_Final'] > 0].copy()
        
        if df_display.empty:
            st.warning("Com base no stock atual, não é necessário encomendar nada! (Verifique se selecionou meses suficientes)")
        else:
            st.dataframe(
                df_display[['Descricao', 'Vendas', 'Stock', 'Necessidade_Estrita', 'Encomenda_Final']], 
                use_container_width=True,
                hide_index=True
            )
            
            # --- EXPORTAÇÃO ---
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False, sheet_name='Encomenda')
                
            st.download_button(
                label="📥 Download Excel para Laboratório",
                data=buffer.getvalue(),
                file_name=f"Encomenda_{'Campanha' if ativar_campanha else 'Simples'}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.error("Não foi possível extrair dados válidos do PDF.")
