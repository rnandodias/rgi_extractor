# streamlit_app.py
import io
import json
import os
import tempfile
from packaging import version
import fitz  # PyMuPDF
import pandas as pd
import streamlit as st
from PIL import Image

SUPPORTS_CONTAINER = version.parse(st.__version__) >= version.parse("1.36.0")

from rgi_extractor import extract_from_images

st.set_page_config(page_title="Leitor de RGI — Koortimativa — Protótipo", layout="wide")

# ----------------- Utils -----------------
def show_img(col, path):
    img = Image.open(path)
    caption = os.path.basename(path)
    try:
        if SUPPORTS_CONTAINER:
            col.image(img, caption=caption, use_container_width=True)
        else:
            # versões antigas: usa o parâmetro antigo
            col.image(img, caption=caption, use_column_width=True)
    except TypeError:
        # caso extremo: faz fallback automático
        col.image(img, caption=caption, use_column_width=True)

def pdf_bytes_to_images(pdf_bytes, dpi=240):
    """Converte PDF (bytes) em arquivos PNG temporários e retorna os caminhos."""
    paths = []
    with tempfile.TemporaryDirectory() as tmpdir:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            tmp_png = os.path.join(tmpdir, f"page_{i:03d}.png")
            pix.save(tmp_png)
            # Copia para arquivo temporário persistente (delete=False)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as out:
                Image.open(tmp_png).save(out.name)
                paths.append(out.name)
    return paths

def metric_card(label, value):
    st.metric(label, value if (value not in (None, "", [], {})) else "—")

def reset_app():
    for k in ["uploaded_name", "image_paths", "data", "json_bytes"]:
        st.session_state.pop(k, None)
    st.rerun()

def tableify(arr, columns_order=None):
    if not arr:
        return None
    df = pd.DataFrame(arr)
    if columns_order:
        cols = [c for c in columns_order if c in df.columns]
        df = df[cols + [c for c in df.columns if c not in cols]]
    return df

# ----------------- Sidebar -----------------
with st.sidebar:
    st.header("Configurações")
    # modelos solicitados
    model = st.selectbox(
        "Modelo (OpenAI)",
        options=["gpt-4o", "gpt-4o-mini", "gpt-5", "gpt-5-mini"],
        index=0  # default: gpt-4o
    )
    dpi = st.slider("DPI (PDF → imagem)", min_value=120, max_value=300, value=240, step=20)
    show_pages = st.checkbox("Mostrar páginas renderizadas", value=True)
    st.divider()
    if st.button("🧹 Novo arquivo (limpar)", key="reset_sidebar"):
        reset_app()

st.title("📄 Leitor de RGI — Koortimativa — Protótipo")
st.caption("Envie o PDF do registro. O app converte as páginas para imagens e extrai as informações e cria um JSON estruturado.")

# ----------------- Upload -----------------
uploaded = st.file_uploader("Envie o documento em PDF", type=["pdf"])

if uploaded is not None and "uploaded_name" not in st.session_state:
    st.session_state.uploaded_name = uploaded.name

# ----------------- Process -----------------
if uploaded is not None and st.button("🔎 Extrair informações", type="primary"):
    try:
        with st.spinner("Convertendo PDF → imagens…"):
            st.session_state.image_paths = pdf_bytes_to_images(uploaded.read(), dpi=dpi)

        if show_pages:
            st.subheader("Páginas")
            cols = st.columns(2)
            for idx, p in enumerate(st.session_state.image_paths):
                # cols[idx % 2].image(Image.open(p), caption=os.path.basename(p), use_container_width=True)
                show_img(cols[idx % 2], p)

        with st.spinner("Executando extração…"):
            data = extract_from_images(st.session_state.image_paths, provider="openai", model=model)

        st.session_state.data = data
        st.session_state.json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        st.success("Extração concluída.")
    except Exception as e:
        st.error(
            "Falha ao processar com a API. Dicas: reduza o DPI, tente novamente ou divida em menos páginas. "
            "Detalhes técnicos abaixo."
        )
        st.exception(e)

# ----------------- Output -----------------
if "data" in st.session_state:
    data = st.session_state.data
    meta = data.get("document_metadata", {}) or {}
    imovel = data.get("imovel", {}) or {}
    proprietarios = data.get("proprietarios", []) or []
    registros = data.get("registros", []) or []
    valores_mencionados = data.get("valores_mencionados", []) or []

    # Resumo
    st.subheader("Resumo")
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Matrícula", meta.get("matricula"))
    with c2: metric_card("Cidade / UF", f"{meta.get('cidade','—')} / {meta.get('uf','—')}")
    with c3: metric_card("Páginas processadas", meta.get("paginas_processadas"))
    with c4: metric_card("Qtd. de registros", len(registros))

    # Descrição do imóvel
    st.subheader("Descrição do imóvel")
    if imovel.get("descricao"):
        st.write(imovel["descricao"])
    else:
        st.info("Descrição não encontrada.")

    # Proprietários
    st.subheader("Proprietários")
    df_prop = tableify(
        proprietarios,
        columns_order=["nome","cpf","rg","estado_civil","regime_de_bens","conjuge","quota_fracao","nacionalidade","profissao","observacoes"]
    )
    if df_prop is not None:
        st.dataframe(df_prop, use_container_width=True)
    else:
        st.info("Nenhum proprietário identificado.")

    # Registros / Averbações
    st.subheader("Registros / Averbações")
    if registros:
        for i, r in enumerate(registros, start=1):
            titulo = f"{i}. {r.get('numero','—')} • {r.get('tipo','—')} • {r.get('data','—')}"
            with st.expander(titulo, expanded=False):
                # Detalhes
                st.markdown(f"**Detalhes:** {r.get('detalhes','—')}")
                # Pessoas envolvidas (aceita ambos os nomes de chave)
                pessoas = r.get("pessoas_envolvidas") or r.get("pessoas_envovidas") or []
                if pessoas:
                    df_p = tableify(pessoas, ["nome","relacao","cpf"])
                    st.markdown("**Pessoas envolvidas:**")
                    st.dataframe(df_p, use_container_width=True)
                # Valores do ato
                if r.get("valores"):
                    df_v = tableify(r["valores"], ["rotulo","moeda","valor_str","valor_num"])
                    st.markdown("**Valores:**")
                    st.dataframe(df_v, use_container_width=True)
    else:
        st.info("Nenhum ato identificado.")

    # Valores mencionados (visão geral)
    st.subheader("Valores mencionados (geral)")
    df_vals = tableify(valores_mencionados, ["moeda","valor_str","valor_num","pagina","contexto"])
    if df_vals is not None:
        st.dataframe(df_vals, use_container_width=True)
    else:
        st.info("Nenhum valor identificado.")

    st.divider()
    # JSON + download
    st.subheader("JSON extraído")
    with st.expander("Visualizar JSON"):
        st.code(st.session_state.json_bytes.decode("utf-8"), language="json")
    st.download_button(
        "⬇️ Baixar JSON",
        data=st.session_state.json_bytes,
        file_name=f"{st.session_state.get('uploaded_name','extracao')}.json",
        mime="application/json",
        type="primary"
    )

    st.divider()
    if st.button("🧹 Novo arquivo (limpar)", key="reset_main"):
        reset_app()
