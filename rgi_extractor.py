# rgi_extractor.py
import argparse
import base64
import json
import os
import re
import sys
import tempfile
from typing import List, Dict, Any
from dotenv import load_dotenv
import re
from collections import Counter

NUM_M_RGX = re.compile(
    r"(?<!\d)"
    r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:\.\d+)?)"
    r"\s*m(?:²|2)?\b",
    re.IGNORECASE
)

def _to_float_pt(num_str: str) -> float | None:
    s = num_str.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except:
        return None

def extract_measures_meters(text: str) -> list[float]:
    """Extrai números seguidos de 'm', 'm²' etc. e devolve em metros (float)."""
    if not text:
        return []
    vals = []
    for m in NUM_M_RGX.finditer(text):
        v = _to_float_pt(m.group(1))
        if v is not None:
            vals.append(v)
    return vals

def infer_area_from_texts(*texts: str) -> float | None:
    """
    Heurística simples:
    - se existirem exatamente 2 medidas diferentes -> multiplica (retângulo).
    - se existirem 3-4 medidas, pega as 2 mais frequentes/distintas e multiplica.
    - caso contrário, não infere.
    """
    measures = []
    for t in texts:
        measures.extend(extract_measures_meters(t))
    measures = [round(v, 4) for v in measures if v > 0]
    if len(measures) < 2:
        return None
    # agrupa por valor aproximado
    freq = Counter(measures)
    # duas mais comuns
    distinct = sorted(freq.keys(), key=lambda x: (-freq[x], -x))
    if len(distinct) >= 2:
        a, b = distinct[0], distinct[1]
        area = a * b
        # ignora valores absurdos
        if 0 < area < 1e6:
            return round(area, 2)
    return None

# OpenAI
try:
    from openai import OpenAI
    OAI_AVAILABLE = True
except Exception:
    OAI_AVAILABLE = False

# Pillow (para compressão)
try:
    from PIL import Image, ImageOps, ImageFilter
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# ===================== LIMITES E AJUSTES DE PAYLOAD =====================
MAX_IMAGES_PER_CALL = 2          # Envia 2 páginas por request
TARGET_WIDTH_PX = 1600           # Redimensiona largura máx.
JPEG_QUALITY = 80                # Qualidade JPEG
LIGHT_WIDTH_PX = 1200            # Retry mais leve
LIGHT_JPEG_QUALITY = 70

# ================= JSON SCHEMA (rico e flexível) =================
RGI_JSON_SCHEMA = {
    "name": "rgi_schema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "document_metadata": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "matricula": {"type": "string"},
                    "ficha": {"type": "string"},
                    "cartorio": {"type": "string"},
                    "oficio": {"type": "string"},
                    "cidade": {"type": "string"},
                    "uf": {"type": "string"},
                    "cnm": {"type": "string"},
                    "paginas_processadas": {"type": "integer"},
                    "observacoes": {"type": "string"}
                }
            },
            "imovel": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    # Texto bruto fiel (mantido)
                    "descricao": {"type": "string"},

                    # Identificação / tipologia da unidade
                    "identificacao": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "tipo": {"type": "string"},                 # ex.: apartamento, loja, sala, casa
                            "unidade": {"type": "string"},              # nº da unidade (ex.: 402)
                            "bloco_torre": {"type": "string"},          # ex.: Bloco B, Torre Sul
                            "pavimento": {"type": "string"},            # ex.: 4º andar
                            "edificio_condominio": {"type": "string"}   # nome do prédio/condomínio, se houver
                        }
                    },

                    # Localização super detalhada
                    "localizacao": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "logradouro": {"type": "string"},
                            "numero": {"type": "string"},
                            "complemento": {"type": "string"},          # ex.: apto 402, loja A
                            "bairro": {"type": "string"},
                            "distrito": {"type": "string"},
                            "cidade": {"type": "string"},
                            "uf": {"type": "string"},
                            "cep": {"type": "string"},
                            "lote": {"type": "string"},
                            "quadra": {"type": "string"},
                            "loteamento": {"type": "string"},
                            "ponto_referencia": {"type": "string"}
                        }
                    },

                    # Áreas e frações (mantém string original e número em m²)
                    "areas": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "area_privativa_str": {"type": "string"},
                            "area_privativa_m2": {"type": "number"},
                            "area_total_str": {"type": "string"},
                            "area_total_m2": {"type": "number"},
                            "area_terreno_str": {"type": "string"},
                            "area_terreno_m2": {"type": "number"},
                            "fracao_ideal_str": {"type": "string"},     # ex.: 0,0123; 12,34%; 1/81
                            "fracao_ideal_num": {"type": "number"}      # normalizado (decimal, ex.: 0.1234)
                        }
                    },

                    # Configurações internas / dependências
                    "dependencias": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "quartos": {"type": "integer"},
                            "suites": {"type": "integer"},
                            "banheiros": {"type": "integer"},
                            "lavabos": {"type": "integer"},
                            "salas": {"type": "integer"},
                            "cozinha": {"type": "boolean"},
                            "area_servico": {"type": "boolean"},
                            "dependencia_empregada": {"type": "boolean"},
                            "outros": {"type": "string"}                # livre: varanda, escritório, mezanino etc.
                        }
                    },

                    # Vagas de garagem (quantidade, tipo e identificação)
                    "vagas_garagem": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "quantidade": {"type": "integer"},
                            "tipo": {"type": "string"},                  # autônoma, vinculada, indeterminada, presa, rotativa
                            "identificacoes": {                          # lista de marcações quando existir (ex.: vaga 12-B)
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        }
                    },

                    # Outras características úteis
                    "caracteristicas": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "posicao": {"type": "string"},               # frente, fundos, lateral
                            "orientacao_solar": {"type": "string"},      # norte, sul, etc.
                            "vista": {"type": "string"},
                            "estado_conservacao": {"type": "string"},    # novo, bom, regular…
                            "padrao_construtivo": {"type": "string"},    # baixo, médio, alto
                            "ano_construcao": {"type": "string"},
                            "elevadores": {"type": "string"},
                            "ocupacao": {"type": "string"},              # ocupado, desocupado (se constar)
                            "uso": {"type": "string"},                   # residencial, comercial, misto
                            "inscricao_municipal": {"type": "string"}    # IPTU/inscrição predial
                        }
                    },

                    # Confrontações (como texto contínuo; se quiser, pode virar array no futuro)
                    "confrontacoes": {"type": "string"}
                }
            },
            "proprietarios": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "nome": {"type": "string"},
                        "cpf": {"type": "string"},
                        "rg": {"type": "string"},
                        "nacionalidade": {"type": "string"},
                        "estado_civil": {"type": "string"},
                        "profissao": {"type": "string"},
                        "regime_de_bens": {"type": "string"},
                        "conjuge": {"type": "string"},
                        "quota_fracao": {"type": "string"},
                        "observacoes": {"type": "string"}
                    }
                }
            },
            "registros": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "numero": {"type": "string"},   # R-3-..., AV-5-...
                        "tipo": {"type": "string"},
                        "data": {"type": "string"},
                        "detalhes": {"type": "string"}, # descrição do ato
                        "pessoas_envolvidas": {         # nome correto
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "nome": {"type":"string"},
                                    "relacao": {"type":"string"},  # herdeira, cônjuge, inventariante etc.
                                    "cpf": {"type":"string"}
                                }
                            }
                        },
                        # compat com versões antigas que geraram "pessoas_envovidas" (erro de digitação)
                        "pessoas_envovidas": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "nome": {"type":"string"},
                                    "relacao": {"type":"string"},
                                    "cpf": {"type":"string"}
                                }
                            }
                        },
                        "valores": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "rotulo": {"type":"string"},
                                    "moeda": {"type":"string"},   # BRL / CR$
                                    "valor_str": {"type":"string"},
                                    "valor_num": {"type":"number"}
                                }
                            }
                        }
                    }
                }
            },
            "valores_mencionados": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "moeda": {"type": "string"},
                        "valor_str": {"type": "string"},
                        "valor_num": {"type": "number"},
                        "contexto": {"type": "string"},
                        "pagina": {"type": "integer"}
                    }
                }
            },
            "selos_e_custas": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "itbi": { "type": "string" },
                    "guias": { "type": "array", "items": {"type":"string"} },
                    "selos": { "type": "array", "items": {"type":"string"} },
                    "custas": { "type": "string" }
                }
            },
            "referencias": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "pagina": {"type": "integer"},
                        "trecho": {"type": "string"}
                    }
                }
            },
            "confidence": {
                "type": "object",
                "additionalProperties": True
            }
        }
    },
    "strict": False
}

# ================= PROMPT =================
# PROMPT_INSTRUCTIONS = """Você é um extrator jurídico rigoroso para registros de imóveis brasileiros.
# Extraia o conteúdo das imagens e preencha SOMENTE o JSON conforme o schema, sem chaves extras.

# Diretrizes:
# - NÃO invente. Se algo não estiver visível, omita o campo.
# - Datas: dd/mm/aaaa quando claro.
# - CPFs: somente dígitos.
# - 'imovel.descricao': transcrever fielmente o parágrafo “IMÓVEL - ...”.
# - 'proprietarios': liste todos os proprietários com dados que estiverem visíveis (RG/CPF/estado civil/regime/quotas etc.).
# - 'registros': para cada ato (R-*/AV-*):
#   • 'numero', 'tipo', 'data' (se houver) e 'detalhes' com uma descrição clara do que foi averbado/registrado.
#   • 'pessoas_envolvidas': relacione pessoas citadas no ato (ex.: herdeira, cônjuge, inventariante, ex-cônjuge).
#   • 'valores': todos os valores que pertençam a ESSE ato (avaliado, ITBI, imposto de transmissão, valor fiscal etc.).
# - 'valores_mencionados': todos os valores ao longo do documento, com moeda, valor_str, valor_num, contexto e página.
# - 'selos_e_custas': selos, guias e custas como texto simples.
# - 'referencias': pequenos trechos que justifiquem campos críticos (matrícula, unidade, proprietários e atos relevantes).
# - O documento pode variar: preencha apenas o que estiver legível.
# """
PROMPT_INSTRUCTIONS = """Você é um extrator jurídico rigoroso para registros de imóveis brasileiros.
Extraia o conteúdo das imagens e preencha SOMENTE o JSON conforme o schema, sem chaves extras.

Princípios:
- NÃO invente. Se algo não estiver visível, omita o campo.
- Datas: dd/mm/aaaa quando claro. CPFs: somente dígitos.
- Documento pode variar: preencha apenas o que estiver legível.

Priorize as CARACTERÍSTICAS DO IMÓVEL:
1) 'imovel.descricao': transcreva fielmente o parágrafo “IMÓVEL - ...”.
2) 'imovel.identificacao': tipo (apartamento, loja, sala, casa etc.), número da unidade, bloco/torre, pavimento, nome do edifício/condomínio.
3) 'imovel.localizacao': logradouro, número, complemento (ex.: apto 402), bairro, cidade, UF, CEP, lote/quadra/loteamento se constarem.
4) 'imovel.areas':
   - Se encontrar “área privativa”, “área útil”, “área real” → preencha 'area_privativa_str' e 'area_privativa_m2' (número em m²).
   - “área total”/“área construída” idem em 'area_total_*'.
   - “fração ideal” (pode vir como 1/xx, 12,34%, 0,1234) → mantenha original em 'fracao_ideal_str' e normalize em 'fracao_ideal_num' (decimal).
   - Sempre manter a forma original em *_str.
   - Quando o documento listar apenas medidas lineares (ex.: frente/largura/comprimento em metros), calcule a área em m² **apenas se** houver evidência clara para um retângulo (duas medidas predominantes). Caso contrário, omita.
5) 'imovel.dependencias': conte quantidades quando aparecerem: quartos, suítes, banheiros, lavabos, salas. Campos booleanos para cozinha/área de serviço/dpe.
6) 'imovel.vagas_garagem': informe 'quantidade' quando explícita; 'tipo' (autônoma, vinculada, indeterminada, presa, rotativa); 'identificacoes' como lista quando houver vaga “12-B”, “G2-145” etc.
7) 'imovel.caracteristicas': posicao (frente/fundos/lateral), orientação solar, vista, estado de conservação, padrão construtivo, ano de construção, elevadores, ocupação (ocupado/desocupado), uso (residencial/comercial), inscrição municipal (IPTU).
8) 'imovel.confrontacoes': se houver, como texto corrido.

Registros e valores:
- 'proprietarios': liste todos os proprietários com dados visíveis (RG/CPF/estado civil/regime/quotas etc.).
- 'registros': para cada ato (R-*/AV-*):
  • 'numero', 'tipo', 'data' (se houver) e 'detalhes' com descrição clara.
  • 'pessoas_envolvidas': cite nome + relação (ex.: herdeira, cônjuge, inventariante).
  • 'valores': associe valores ao ato quando fizer sentido (avaliado, ITBI, imposto de transmissão, valor fiscal).
- 'valores_mencionados': liste todos os valores ao longo do documento com moeda, valor_str, valor_num, contexto e página.
- 'selos_e_custas': registre guias, selos e custas em texto simples.
- 'referencias': pequenos trechos (citações) que justifiquem campos críticos (matrícula, unidade, áreas, vagas etc.).

Observações:
- Números de área devem estar em m² (ponto decimal), mantendo também a forma original em *_str.
- Se não ficar claro se um número é privativa vs total, preencha só o campo *_str correspondente e deixe o *_m2 vazio.
"""

# ================= Helpers =================
def _get_api_key():
    load_dotenv()
    return os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_CREDENTIALS")

def encode_image_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def compress_to_jpeg(src_path: str, target_width: int = TARGET_WIDTH_PX, quality: int = JPEG_QUALITY) -> str:
    if not PIL_AVAILABLE:
        # Sem Pillow, retorna o próprio arquivo (vai funcionar se já for JPEG pequeno)
        return src_path
    img = Image.open(src_path).convert("RGB")
    w, h = img.size
    if w > target_width:
        new_h = int(h * (target_width / float(w)))
        img = img.resize((target_width, new_h), Image.LANCZOS)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img.save(tmp.name, format="JPEG", optimize=True, quality=quality)
    return tmp.name

def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i+size]

# ================= OpenAI: batched + retry leve =================
def extract_with_openai(image_paths: List[str], model: str = "gpt-4o-mini") -> Dict[str, Any]:
    if not OAI_AVAILABLE:
        raise RuntimeError("SDK da OpenAI não encontrado. `pip install openai`.")
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("Defina OPENAI_API_KEY no .env ou no ambiente.")
    client = OpenAI(api_key=api_key)

    merged: Dict[str, Any] = {
        "document_metadata": {"paginas_processadas": 0},
        "imovel": {},
        "proprietarios": [],
        "registros": [],
        "valores_mencionados": [],
        "selos_e_custas": {"guias": [], "selos": []},
        "referencias": [],
        "confidence": {}
    }

    total_pages = 0

    for batch in chunked(list(enumerate(image_paths, start=1)), MAX_IMAGES_PER_CALL):
        content = [{"type": "text", "text": PROMPT_INSTRUCTIONS}]
        # compress normal
        for page_num, path in batch:
            jpg_path = compress_to_jpeg(path, TARGET_WIDTH_PX, JPEG_QUALITY)
            with open(jpg_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            content.append({"type": "text", "text": f"Página {page_num}:"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

        # def _call(payload):
        #     return client.chat.completions.create(
        #         model=model,
        #         messages=[{"role": "user", "content": payload}],
        #         response_format={"type": "json_schema", "json_schema": RGI_JSON_SCHEMA},
        #         temperature=0
        #     )

        def _call(payload):  # solução para incluir o GPT-5
            # Monta os parâmetros comuns
            params = {
                "model": model,
                "messages": [{"role": "user", "content": payload}],
                "response_format": {"type": "json_schema", "json_schema": RGI_JSON_SCHEMA},
                # "max_tokens": 4096,  # opcional: inclua se quiser limitar
            }
            # Só adiciona temperature para a família gpt-4o
            if "gpt-4o" in model.lower():
                params["temperature"] = 0

            return client.chat.completions.create(**params)
        
        try:
            resp = _call(content)
        except Exception:
            # retry leve
            light_content = [{"type": "text", "text": PROMPT_INSTRUCTIONS}]
            for page_num, path in batch:
                jpg_path = compress_to_jpeg(path, LIGHT_WIDTH_PX, LIGHT_JPEG_QUALITY)
                with open(jpg_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                light_content.append({"type": "text", "text": f"Página {page_num}:"})
                light_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            resp = _call(light_content)

        data = json.loads(resp.choices[0].message.content or "{}")

        # merge metadata
        md = data.get("document_metadata") or {}
        merged["document_metadata"] = {
            **merged.get("document_metadata", {}),
            **{k: v for k, v in md.items() if v not in (None, "", [], {})}
        }

        # merge arrays
        def _extend(key):
            merged[key] = (merged.get(key) or []) + (data.get(key) or [])
        for arr_key in ["proprietarios", "registros", "valores_mencionados", "referencias"]:
            _extend(arr_key)

        # selos/custas
        sc_dst = merged.get("selos_e_custas") or {"guias": [], "selos": []}
        sc_src = data.get("selos_e_custas") or {}
        for k in ["guias", "selos"]:
            sc_dst[k] = (sc_dst.get(k) or []) + (sc_src.get(k) or [])
        if sc_src.get("itbi") and not sc_dst.get("itbi"):
            sc_dst["itbi"] = sc_src["itbi"]
        if sc_src.get("custas") and not sc_dst.get("custas"):
            sc_dst["custas"] = sc_src["custas"]
        merged["selos_e_custas"] = sc_dst

        # imóvel
        im_dst = merged.get("imovel") or {}
        im_src = data.get("imovel") or {}
        for k, v in im_src.items():
            if v and (not im_dst.get(k)):
                im_dst[k] = v
        merged["imovel"] = im_dst

        total_pages += len(batch)

    merged["document_metadata"]["paginas_processadas"] = total_pages

    # compat: mover "pessoas_envovidas" -> "pessoas_envolvidas" dentro de cada registro
    fixed_regs = []
    for r in merged.get("registros", []) or []:
        if "pessoas_envovidas" in r and "pessoas_envolvidas" not in r:
            r["pessoas_envolvidas"] = r.get("pessoas_envovidas") or []
            r.pop("pessoas_envovidas", None)
        fixed_regs.append(r)
    merged["registros"] = fixed_regs
    # --- Pós-processamento: inferir áreas quando possível ---
    conf = merged.get("confidence") or {}
    conf.setdefault("derived", {})

    imv = merged.get("imovel") or {}
    areas = imv.get("areas") or {}
    desc = (imv.get("descricao") or "") + " "
    conf_txt = (imv.get("confrontacoes") or "") + " "
    dim_txt = (imv.get("dimensoes") or "") + " "  # se você tiver esse campo

    # tenta inferir área total se não houver
    if not areas.get("area_total_m2"):
        inferred_total = infer_area_from_texts(desc, conf_txt, dim_txt)
        if inferred_total:
            areas["area_total_m2"] = inferred_total
            if not areas.get("area_total_str"):
                areas["area_total_str"] = f"{inferred_total:.2f} m² (inferido)"
            conf["derived"].setdefault("areas", {})["area_total_m2"] = "inferido a partir de medidas lineares no texto"

    # tenta inferir área de terreno se não houver (usa confrontações e dimensões com prioridade)
    if not areas.get("area_terreno_m2"):
        inferred_terr = infer_area_from_texts(conf_txt, dim_txt)
        if inferred_terr:
            areas["area_terreno_m2"] = inferred_terr
            if not areas.get("area_terreno_str"):
                areas["area_terreno_str"] = f"{inferred_terr:.2f} m² (inferido)"
            conf["derived"].setdefault("areas", {})["area_terreno_m2"] = "inferido a partir de confrontações/dimensões"

    # escreve de volta
    imv["areas"] = areas
    merged["imovel"] = imv
    merged["confidence"] = conf

    return merged

def extract_from_images(image_paths: List[str], provider: str = "openai", model: str = "gpt-4o-mini") -> Dict[str, Any]:
    # No momento, só OpenAI está implementado aqui
    if provider != "openai":
        raise RuntimeError("Somente provider='openai' está disponível nesta versão.")
    return extract_with_openai(image_paths, model=model)

# ================ CLI opcional ================
def main():
    ap = argparse.ArgumentParser(description="Extrator de RGI (JPG/PNG → JSON).")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--out", default="-")
    args = ap.parse_args()

    data = extract_from_images(sorted(args.paths), provider="openai", model=args.model)

    # normalização simples: CPF só dígitos
    for p in data.get("proprietarios", []) or []:
        if p.get("cpf"):
            p["cpf"] = re.sub(r"\D", "", p["cpf"])

    if args.out == "-":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[ok] JSON salvo em: {args.out}")

if __name__ == "__main__":
    main()
