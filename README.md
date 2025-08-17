# RGI Extractor — Streamlit

Protótipo que **lê PDFs de registros de imóveis**, converte cada página em imagem e extrai um **JSON estruturado** com:
- metadados (matrícula, cartório, cidade/UF…),
- **descrição completa do imóvel**,
- **proprietários** (campos ricos),
- **registros/averbações** (detalhes do ato, **pessoas envolvidas**, **valores**),
- **valores mencionados** ao longo do documento,
- selos/guia/custas e referências de trechos.

A extração usa a **API da OpenAI** com compressão e processamento em **lotes** para evitar erros de payload.

---

## ✨ Principais recursos
- Upload de **PDF** → conversão automática para imagens (PyMuPDF).
- UI em **Streamlit** com:
  - seletor de **modelo OpenAI** (`gpt-4o`, `gpt-4o-mini`, `gpt-5`, `gpt-5-mini`);
  - controle de **DPI** do PDF → imagem;
  - visualização opcional das páginas;
  - cards de resumo;
  - tabelas de proprietários, registros/valores e **download do JSON**;
  - botão **“🧹 Novo arquivo (limpar)”**.
- Back-end com:
  - **compressão JPEG + redimensionamento** e **lotes (2 páginas por chamada)**;
  - retry “leve” automático se a chamada falhar por tamanho;
  - schema JSON **flexível** (`strict=False`) e prompt reforçado.

---

## 🗂️ Estrutura do projeto
```
.
├─ rgi_extractor.py       # extrator (OpenAI + batching/compressão)
├─ streamlit_app.py       # app Streamlit
├─ requirements.txt
├─ .streamlit/
│  └─ config.toml         # (opcional) configs do Streamlit
├─ .gitignore
└─ README.md
```

---

## 🧰 Pré-requisitos
- Python 3.10+
- Conta na OpenAI + **chave de API** (salve como `OPENAI_API_KEY`)
- (Local) `pip install -r requirements.txt`

`requirements.txt`:
```txt
streamlit>=1.36
openai>=1.40
python-dotenv>=1.0
pillow>=10.0
pymupdf>=1.24.0
pandas>=2.2.0
```

---

## 🔐 Variáveis de ambiente
**Não** comite sua chave. Localmente, use um `.env` (que deve estar no `.gitignore`):

`.env`:
```
OPENAI_API_KEY=coloque_sua_chave_aqui
```

> Em produção (Streamlit Cloud/Spaces/etc.), configure **Secrets/Env Vars** na plataforma (ver seção de deploy).

---

## ▶️ Como rodar localmente

### 1) Criar e ativar o ambiente
```bash
# macOS/Linux
python -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate
```

### 2) Instalar dependências
```bash
pip install -r requirements.txt
```

### 3) Definir a chave da OpenAI
```bash
# macOS/Linux
echo "OPENAI_API_KEY=sk-..." > .env

# Windows (PowerShell)
Set-Content .env 'OPENAI_API_KEY=sk-...'
```

### 4) Rodar o app
```bash
streamlit run streamlit_app.py
```

Acesse o link que aparecer (geralmente `http://localhost:8501`).

---

## 💻 Uso
1. Faça **upload de um PDF**.
2. Escolha o **modelo** (padrão: `gpt-4o-mini`) e ajuste o **DPI** (220–240 costuma ser ótimo).
3. Clique em **“Extrair informações”**.
4. Veja os **cards**, **tabelas** e use **“⬇️ Baixar JSON”**.

> Dica: se o PDF for grande, reduza o DPI. O extrator também comprime e processa em lotes para evitar erros 400 de payload.

---

## ☁️ Deploy (Streamlit Community Cloud)

1. Suba o projeto no GitHub (veja a seção **Git** abaixo).
2. Acesse https://share.streamlit.io → **New app** → selecione o repositório.
3. **App file**: `streamlit_app.py` • **Branch**: `main`.
4. Em **Settings → Secrets**, adicione:
   ```
   OPENAI_API_KEY = "sk-..."
   ```
5. Clique em **Deploy**. Pronto! Você ganha uma URL pública para compartilhar.

**Config opcional** (`.streamlit/config.toml`):
```toml
[server]
maxUploadSize = 200
enableXsrfProtection = true
enableCORS = false

[theme]
primaryColor = "#1e88e5"
base = "light"
```
> `maxUploadSize` define o limite (em MB) de upload permitido pelo app.

---

## 🧭 Git — passo a passo

### Criar o repositório no GitHub
1. Vá em https://github.com/new
2. Defina um nome (ex.: `rgi-extractor-streamlit`) → Create repository.

### Inicializar e subir o projeto (terminal na pasta do projeto)
```bash
git init
git add .
git commit -m "Primeira versão do app"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/rgi-extractor-streamlit.git
git push -u origin main
```

> Depois, cada atualização é: `git add . && git commit -m "mensagem" && git push`.

**.gitignore** (essencial para não vazar segredos):
```
.venv/
.env
__pycache__/
.streamlit/secrets.toml
*.png
*.jpg
*.jpeg
```

---

## 🔄 Atualizações e versionamento

- Faça suas mudanças de código.
- Rode localmente para validar.
- `git add . && git commit -m "feat: ... / fix: ... / docs: ..."`
- `git push` → o Streamlit Cloud redeploya automaticamente (ou clique em “Rerun” no painel).
- Sugestão de mensagens:
  - `feat:` novas features
  - `fix:` correções
  - `chore:` manutenção
  - `docs:` README, docs

---

## 🆘 Troubleshooting

### 1) `BadRequestError 400` (“something went wrong reading your request”)
Geralmente é payload grande. Soluções:
- Reduza **DPI** no app (ex.: 200–240).
- O extrator já **comprime** e manda em **lotes de 2 páginas** com **retry leve**. Mesmo assim, PDFs muito pesados podem exigir DPI menor.

### 2) Modelos `gpt-5` / `gpt-5-mini` com erro de `temperature`
Esses modelos **não aceitam `temperature` ≠ 1**. O código ajusta a chamada para só enviar `temperature=0` com `gpt-4o`/`gpt-4o-mini`. Se você renomear modelos, mantenha a regra:
- se `"gpt-4o" in model.lower()` → incluir `temperature=0`;
- caso contrário, **não** enviar `temperature`.

### 3) `ModuleNotFoundError`
Cheque se o pacote está no `requirements.txt`, rode `pip install -r requirements.txt` e reinicie o app.

### 4) Tamanho de upload insuficiente
Aumente `maxUploadSize` em `.streamlit/config.toml`. Lembre que o Streamlit Cloud tem limites por plano.

### 5) Chave da OpenAI não lida
Local: seu `.env` precisa ter `OPENAI_API_KEY=...`.  
Cloud: configure **Secrets** com `OPENAI_API_KEY`.

---

## 🧩 JSON de saída (visão geral)
Estrutura (campos **opcionais**; o extrator **não inventa**):

- `document_metadata` → matrícula, cartório, cidade/UF, páginas processadas…
- `imovel` → **descricao** (texto completo “IMÓVEL - …”), endereço, fração ideal etc.
- `proprietarios[]` → nome, cpf, rg, estado civil, regime de bens, cônjuge, quota etc.
- `registros[]` → número (R-*/AV-*), tipo, data, **detalhes** (texto),  
  **pessoas_envolvidas[]** (nome, relação, cpf), **valores[]** (rótulo, moeda, valor_str, valor_num).
- `valores_mencionados[]` → valores percebidos no documento com contexto e página.
- `selos_e_custas` → guias/selos/custas como texto.
- `referencias[]` → trechos que justificam campos críticos.

> Observação: para compatibilidade, se vier `pessoas_envovidas` (typo), o código converte para `pessoas_envolvidas`.

---

## 📜 Licença / Avisos
- Uso educacional/demonstração. Verifique a base legal para processar documentos reais (LGPD).
- Adapte o schema/prompt conforme as **regras de negócio** da sua empresa.

---

## 🙋‍♂️ Suporte & melhorias
- Ajustar **mapeamentos de valores** (valor fiscal, avaliado, ITBI) para campos fixos?
- Exportar **CSV** de proprietários/registros?
- Tema customizado no Streamlit?

Abra uma issue ou mande um PR! 🚀
