import streamlit as st
import pandas as pd
import re
import io
import zipfile
from pypdf import PdfReader, PdfWriter
from collections import defaultdict

# --- Configuração Minimalista e Dark ---
st.set_page_config(page_title="Divisor de Comprovantes", page_icon="📄", layout="centered")

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
    # 1. Procura TODAS as ocorrências de palavras-chave (não só a primeira)
    matches = re.findall(r"(?:Valor\s+do\s+documento|Valor\s+pago|Valor\s+cobrado|Valor|Total(?:\s+a\s+pagar)?)[^\dR$]*R\$?\s*([\d\.,]+)", texto_pagina, re.IGNORECASE)
    
    valores_validos = []
    if matches:
        for v_str in matches:
            v = string_para_float(v_str)
            if v > 0:
                valores_validos.append(v)
    
    if valores_validos:
        return max(valores_validos) # Pega o maior valor encontrado (ignora campos de desconto zerados)
        
    # 2. Fallback: Qualquer valor na página com R$
    valores_encontrados = re.findall(r'R\$\s*([\d\.,]{3,})', texto_pagina)
    if valores_encontrados:
        valores_float = [string_para_float(v) for v in valores_encontrados]
        valores_validos = [v for v in valores_float if v > 0]
        if valores_validos: 
            return max(valores_validos)

    # 3. Fallback Extremo para comprovantes que não usam "R$" (Ex: Itaú)
    numeros_soltos = re.findall(r'\b\d{1,3}(?:\.\d{3})*,\d{2}\b', texto_pagina)
    if numeros_soltos:
        floats_soltos = [string_para_float(n) for n in numeros_soltos]
        floats_validos = [f for f in floats_soltos if f > 0]
        if floats_validos: 
            return max(floats_validos)

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
                
                # Identifica a coluna UF
                if 'UF' in df.columns:
                    df['UF'] = df['UF'].astype(str).str.strip().str.upper()
                else:
                    df['UF'] = ''

                df = df.dropna(subset=['NF', 'FILIAL'])
                df['FILIAL'] = df['FILIAL'].astype(str).str.strip().str.replace(' ', '_')
                df['NF'] = df['NF'].astype(str).str.strip()
                df['NOME_ARQUIVO'] = df['FILIAL'] + '_' + df['NF']

                valor_para_nomes = defaultdict(list)
                
                for _, row in df.iterrows():
                    nome_base = row['NOME_ARQUIVO']
                    uf = row['UF']
                    v1 = row['_v1']
                    v2 = row['_v2']
                    jr = row['_jr']
                    
                    # REGRA DE EXCEÇÃO: ALAGOAS (AL)
                    if uf == 'AL' and v2 > 0:
                        v1_chave = round(v1 + jr, 2)
                        v2_chave = round(v2, 2)
                        
                        if v1_chave > 0:
                            valor_para_nomes[v1_chave].append(f"{nome_base}_ICMS")
                        if v2_chave > 0:
                            valor_para_nomes[v2_chave].append(f"{nome_base}_FECP")
                            
                    else:
                        # REGRA PADRÃO
                        v_total = round(v1 + v2 + jr, 2)
                        if v_total > 0:
                            valor_para_nomes[v_total].append(nome_base)
                            
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
                            
                            pdf_buffer = io.BytesIO()
                            writer = PdfWriter()
                            writer.add_page(pagina)
                            writer.write(pdf_buffer)
                            
                            zip_file.writestr(f"{nome_arquivo_base}.pdf", pdf_buffer.getvalue())
                            nomes_encontrados += 1

                if nomes_encontrados > 0:
                    st.success(f"Sucesso! {nomes_encontrados} comprovantes foram separados.")
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
