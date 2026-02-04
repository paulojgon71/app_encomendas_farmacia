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

def extract_data_from_pdf(file):
    """Extrai tabelas do PDF e tenta normalizar as colunas comuns em SPharm/Glintt."""
    all_data = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_table()
            if tables:
                for row in tables:
                    # Filtra linhas vazias ou cabeçalhos repetidos
                    if row and row[0] and "Código" not in str(row[0]):
                        all_data.append(row)
    
    if all_data:
        df = pd.DataFrame(all_data)
        
        # TENTATIVA DE DETEÇÃO INTELIGENTE DE COLUNAS
        # A maioria dos softwares de farmácia (SPharm) exporta: 
        # Col 1: Descrição, Col 6: Tot. Ven., Col 7: Exist. (baseado no PDF Tecnilor)
        # Vamos tentar ser flexíveis.
        
        try:
            # Pega nas colunas essenciais. 
            # NOTA: Se usares PDFs de outros softwares que não o SPharm, 
            # os índices [1, 6, 7] podem ter de ser ajustados.
            df_clean = df.iloc[:, [1, 6, 7]].copy() 
            df_clean.columns = ['Descricao', 'Vendas', 'Stock']
            return df_clean
        except:
            st.error("Erro na estrutura do PDF. O ficheiro deve ser um 'Mapa de Evolução de Vendas' padrão (SPharm).")
            return None
    return None

def clean_numbers(value):
    """Limpa formatação de números (ex: '2\n3' -> 2)."""
    if not value: return 0
    try:
        clean_val = str(value).replace('\n', '').strip().replace(',', '.')
        # Tenta converter para float primeiro (caso haja preços misturados) e depois int
        return int(float(clean_val))
    except ValueError:
        return 0

def calculate_order(df, months, use_campaign, buy_qty, offer_qty):
    """Calcula a encomenda baseada nas configurações do utilizador."""
    
    # Limpeza de dados
    df['Vendas'] = df['Vendas'].apply(clean_numbers)
    df['Stock'] = df['Stock'].apply(clean_numbers)
    
    # 1. Cálculo da Necessidade Real
    # (Vendas Médias * Meses Desejados) - Stock Atual
    df['Necessidade_Estrita'] = (df['Vendas'] * months) - df['Stock']
    df['Necessidade_Estrita'] = df['Necessidade_Estrita'].apply(lambda x: x if x > 0 else 0)
    
    total_need = df['Necessidade_Estrita'].sum()
    df['Encomenda_Final'] = df['Necessidade_Estrita'] # Começa igual à estrita
    
    missing_units = 0
    total_offers = 0
    
    # 2. Aplicação de Campanha (Se ativa)
    if use_campaign and total_need > 0:
        # Arredonda para o múltiplo de "buy_qty" superior
        # Ex: Se compra 10, e preciso de 12, tenho de pedir 20.
        target_buy = math.ceil(total_need / buy_qty) * buy_qty
        
        # Se a necessidade for 0, não força compra
        if target_buy == 0 and total_need > 0:
            target_buy = buy_qty # Força pelo menos um patamar se houver necessidade mínima
            
        missing_units = target_buy - total_need
        
        # Calcula quantas ofertas recebe
        total_offers = int((target_buy / buy_qty) * offer_qty)
        
        # Adiciona as unidades em falta aos produtos mais vendidos
        if missing_units > 0:
            df = df.sort_values(by='Vendas', ascending=False)
            # Adiciona tudo ao primeiro (podes mudar lógica para distribuir)
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
        
    if df_raw is not None:
        # Processamento
        df_final, total_pedir, ofertas, adicionados = calculate_order(
            df_raw, 
            meses_stock, 
            ativar_campanha, 
            rule_buy, 
            rule_offer
        )
        
        # --- DASHBOARD DE RESULTADOS ---
        st.markdown("### 📊 Resumo da Encomenda")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total a Pagar (un)", f"{total_pedir}", delta=f"+{adicionados} ajustados" if adicionados > 0 else None)
        col2.metric("Ofertas (un)", f"{ofertas}", delta_color="normal")
        col3.metric("Total Recebido", f"{total_pedir + ofertas}")
        col4.metric("Cobertura Estimada", f"{meses_stock} Mês(es)")
        
        # --- TABELA ---
        st.subheader("Detalhe dos Produtos")
        
        # Filtra para mostrar apenas o que vai ser encomendado
        df_display = df_final[df_final['Encomenda_Final'] > 0].copy()
        
        if df_display.empty:
            st.warning("Com base no stock atual, não é necessário encomendar nada!")
        else:
            # Formatação visual
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
