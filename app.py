import streamlit as st
import pandas as pd
import re
import io
import zipfile
from pypdf import PdfReader, PdfWriter
from collections import defaultdict

# --- Configuração Minimalista e Dark ---
st.set_page_config(page_title="Divisor de Comprovantes", page_icon="📄", layout="centered")

# Esconde o menu padrão e o rodapé para deixar com menos elementos e mais limpo
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

st.title("📄 Divisor de Comprovantes")
st.write("Faça o upload do PDF e da planilha para separar os comprovantes automaticamente.")

# --- Funções Auxiliares ---
def string_para_float(valor_str):
    if pd.isna(valor_str): return 0.0
    if isinstance(valor_str, (int, float)): return float(valor_str)
    
    v = str(valor_str).strip().replace('R$', '').replace(' ', '').replace('\xa0', '')
    if not v: return 0.0
    
    if ',' in v and '.' in v: v = v.replace('.', '').replace(',', '.')
    elif ',' in v: v = v.replace(',', '.')
    
    try: return round(float(v), 2)
    except ValueError: return 0.0

def extrair_valor_do_texto(texto_pagina):
    match = re.search(r"(?:Valor\s+do\s+documento|Valor\s+pago|Valor|Total(?:\s+a\s+pagar)?)[^\dR$]*R\$?\s*([\d\.,]+)", texto_pagina, re.IGNORECASE)
    if match: 
        v = string_para_float(match.group(1))
        if v > 0: return v
        
    valores_encontrados = re.findall(r'R\$\s*([\d\.,]{3,})', texto_pagina)
    if valores_encontrados:
        valores_float = [string_para_float(v) for v in valores_encontrados]
        valores_validos = [v for v in valores_float if v > 0]
        if valores_validos: return max(valores_validos)
    return None

# --- Upload dos Arquivos ---
pdf_file = st.file_uploader("1. Selecione o PDF dos Comprovantes", type=["pdf"])
excel_file = st.file_uploader("2. Selecione a Planilha (Excel)", type=["xlsx", "xls"])

if pdf_file and excel_file:
    if st.button("Processar Comprovantes"):
        with st.spinner("Lendo planilha e cruzando dados..."):
            
            # --- 1. LER PLANILHA ---
            try:
                df = pd.read_excel(excel_file, sheet_name="Comprovantes")
                df.columns = df.columns.str.strip().str.upper()
                
                df['_v1'] = df['VALOR 1'].apply(string_para_float) if 'VALOR 1' in df.columns else 0.0
                df['_v2'] = df['VALOR 2'].apply(string_para_float) if 'VALOR 2' in df.columns else 0.0
                df['_jr'] = df['JUROS/MULTA'].apply(string_para_float) if 'JUROS/MULTA' in df.columns else 0.0
                
                df['VALOR_CHAVE'] = (df['_v1'] + df['_v2'] + df['_jr']).round(2)
                df = df[df['VALOR_CHAVE'] > 0].copy()
                df = df.dropna(subset=['NF', 'FILIAL'])
                
                df['FILIAL'] = df['FILIAL'].astype(str).str.strip().str.replace(' ', '_')
                df['NF'] = df['NF'].astype(str).str.strip()
                df['NOME_ARQUIVO'] = df['FILIAL'] + '_' + df['NF']

               valor_para_nomes = defaultdict(list)

for _, row in df.iterrows():

    uf = str(row.get('UF', '')).strip().upper()
    nome_arquivo = row['NOME_ARQUIVO']

    # REGRA ESPECIAL PARA ALAGOAS
    if uf == 'AL':

        # Busca separadamente o Valor 1
        if row['_v1'] > 0:
            valor_para_nomes[round(row['_v1'], 2)].append(
                f"{nome_arquivo}_VALOR1"
            )

        # Busca separadamente o Valor 2
        if row['_v2'] > 0:
            valor_para_nomes[round(row['_v2'], 2)].append(
                f"{nome_arquivo}_VALOR2"
            )

        # Se existir só juros/multa
        if row['_jr'] > 0 and row['_v1'] == 0 and row['_v2'] == 0:
            valor_para_nomes[round(row['_jr'], 2)].append(
                f"{nome_arquivo}_JUROS"
            )

    # TODOS OS OUTROS ESTADOS (mantém regra atual)
    else:
        valor_para_nomes[row['VALOR_CHAVE']].append(
            nome_arquivo
        )
                    
            except Exception as e:
                st.error(f"Erro ao ler a planilha. Verifique as colunas. Detalhe: {e}")
                st.stop()

            # --- 2. PROCESSAR PDF NA MEMÓRIA E CRIAR ZIP ---
            try:
                reader = PdfReader(pdf_file)
                zip_buffer = io.BytesIO()
                nomes_encontrados = 0
                
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                    for pagina in reader.pages:
                        texto = pagina.extract_text()
                        if not texto: continue
                        
                        valor_chave = extrair_valor_do_texto(texto)
                        
                        if valor_chave is not None and valor_chave in valor_para_nomes and len(valor_para_nomes[valor_chave]) > 0:
                            nome_arquivo_base = valor_para_nomes[valor_chave].pop(0)
                            
                            # Escreve o PDF individual na memória
                            pdf_buffer = io.BytesIO()
                            writer = PdfWriter()
                            writer.add_page(pagina)
                            writer.write(pdf_buffer)
                            
                            # Salva o PDF dentro do ZIP
                            zip_file.writestr(f"{nome_arquivo_base}.pdf", pdf_buffer.getvalue())
                            nomes_encontrados += 1

                if nomes_encontrados > 0:
                    st.success(f"Sucesso! {nomes_encontrados} comprovantes foram separados.")
                    
                    # Botão de Download do arquivo ZIP
                    st.download_button(
                        label="📦 Baixar Arquivo ZIP",
                        data=zip_buffer.getvalue(),
                        file_name="comprovantes_separados.zip",
                        mime="application/zip"
                    )
                else:
                    st.warning("Nenhum comprovante da planilha foi encontrado no PDF.")
                    
            except Exception as e:
                st.error(f"Erro ao processar o PDF: {e}")
