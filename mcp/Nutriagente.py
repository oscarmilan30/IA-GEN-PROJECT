# -*- coding: utf-8 -*-
# Nutriagente.py
# Archivo 3 — Agente NutriAgente
# Ejecutar directamente para pruebas en terminal: python Nutriagente.py
# Para la interfaz web: streamlit run app_nutriagente.py

# ── Instalaciones (ejecutar una sola vez) ─────────────────────────────
# %pip install langchain-anthropic langgraph langchain-community -q
# %pip install llama-index llama-index-embeddings-cohere -q
# %pip install sqlalchemy pyodbc python-dotenv openpyxl -q
# %pip install langchain -q

# ── Imports ───────────────────────────────────────────────────────────
import warnings
warnings.filterwarnings("ignore")

import os
import json
import re
import calendar
import random
import time
from datetime import date
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine, text
from langchain_community.chat_message_histories import SQLChatMessageHistory
from llama_index.core import StorageContext, load_index_from_storage
from llama_index.embeddings.cohere import CohereEmbedding
from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
from pydantic import BaseModel, Field, field_validator
import openpyxl

print("Librerías importadas ✓")

# ── Credenciales ───────────────────────────────────────────────────────
# Rutas configurables por variable de entorno (para nube) o rutas locales por defecto
CARPETA_CONN    = os.getenv("CARPETA_CONN",    r"C:\Users\milu_\ricardo palma ia\Proyecto NutriAgente\Conexiones")
CARPETA_BDC     = os.getenv("CARPETA_BDC",     r"C:\Users\milu_\ricardo palma ia\Proyecto NutriAgente\Base_Conocimiento")
CARPETA_FUENTES = os.getenv("CARPETA_FUENTES", r"C:\Users\milu_\ricardo palma ia\Proyecto NutriAgente\Fuentes")
CARPETA_IDX     = os.getenv("CARPETA_IDX",     r"C:\Users\milu_\ricardo palma ia\Proyecto NutriAgente\Base_Conocimiento\indice_platos")

# Cargar .env si existe (local). En la nube las vars vienen del entorno directamente.
_env_path = os.path.join(CARPETA_CONN, ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)

os.environ["LANGCHAIN_ENDPOINT"]   = "https://api.smith.langchain.com"
os.environ["LANGCHAIN_API_KEY"]    = os.getenv("LANGSMITH_API_KEY")
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"]    = os.getenv("LANGCHAIN_PROJECT", "NutriAgente")
print("LangSmith configurado ✓")

os.environ["ANTHROPIC_API_KEY"] = os.getenv("ANTHROPIC_API_KEY")
assert os.getenv("ANTHROPIC_API_KEY"), "Falta ANTHROPIC_API_KEY en .env"
print("Claude API key cargada ✓")

COHERE_API_KEY = os.getenv("COHERE_API_KEY")
assert COHERE_API_KEY, "Falta COHERE_API_KEY en .env"
print("Cohere API key cargada ✓")

SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_STRING")
assert SQL_CONNECTION_STRING, "Falta SQL_CONNECTION_STRING en .env"
print("Azure SQL connection string cargada ✓")

# ── Clientes ──────────────────────────────────────────────────────────

# Claude Haiku — LLM del agente
llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
print("Claude Haiku iniciado ✓")

# LlamaIndex — cargar índice de platos desde disco (vectorizado en Archivo 2)
embed_query = CohereEmbedding(
    cohere_api_key=COHERE_API_KEY,
    model_name="embed-multilingual-v3.0",
    input_type="search_query",
)
storage_context = StorageContext.from_defaults(persist_dir=CARPETA_IDX)
indice_platos = load_index_from_storage(storage_context, embed_model=embed_query)
print("Índice LlamaIndex cargado ✓")

# Azure SQL — memoria persistente
def _conectar_azure_sql():
    try:
        engine = create_engine(SQL_CONNECTION_STRING)
        SQLChatMessageHistory(session_id="__conn_test__", connection=engine)
        print("Azure SQL conectado ✓")
        print(f"  Servidor: serverfutbol.database.windows.net")
        print(f"  Base de datos: nutriagente_db")
        return engine, True
    except Exception as e:
        print(f"Azure SQL no disponible ({e}) → usando solo MemorySaver")
        return None, False

SQL_ENGINE, SQL_DISPONIBLE = _conectar_azure_sql()

# ── Semáforo + ejemplos few-shot ──────────────────────────────────────
with open(os.path.join(CARPETA_BDC, "reglas_semaforo.json"), encoding="utf-8") as f:
    reglas_semaforo = json.load(f)
print(f"Reglas semáforo cargadas: {list(reglas_semaforo.keys())} ✓")

EXCEL_PLANTILLA = os.path.join(CARPETA_FUENTES, "PLANTILLA SEMAFORO DE ALIMENTOS.xlsx")
DIMENSIONES = ["Energía", "Carbohidratos", "Proteína", "Grasas", "Fibra", "Sodio"]

ejemplos_fewshot = []
if os.path.exists(EXCEL_PLANTILLA):
    wb = openpyxl.load_workbook(EXCEL_PLANTILLA, data_only=True)
    for hoja in wb.sheetnames:
        ws = wb[hoja]
        for row in ws.iter_rows(values_only=True):
            nombre = row[1]
            valores = row[2:8]
            if not nombre or nombre in DIMENSIONES:
                continue
            if not any(v in ("V", "A", "R") for v in valores):
                continue
            semaforo = {
                dim: (val if val in ("V", "A", "R") else "N/A")
                for dim, val in zip(DIMENSIONES, valores)
            }
            ejemplos_fewshot.append({"plato": str(nombre).strip(), "semaforo": semaforo})
    print(f"Ejemplos few-shot cargados: {len(ejemplos_fewshot)} platos ✓")
else:
    print("⚠️  Excel de plantilla no encontrado → ejemplos few-shot vacíos (modo nube)")

# ── Funciones auxiliares ──────────────────────────────────────────────
def normalizar(texto: str) -> str:
    """Minúsculas + sin tildes + sin puntuación + sin espacios extra."""
    texto = texto.lower().strip()
    for a, b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),
                 ('ü','u'),('ñ','n')]:
        texto = texto.replace(a, b)
    texto = re.sub(r'[^a-z0-9\s]', ' ', texto)
    return re.sub(r'\s+', ' ', texto).strip()

# ── Herramienta 1: buscar_platos ──────────────────────────────────────
class BuscarPlatosInput(BaseModel):
    consulta: str = Field(description="Nombre o descripción del plato a buscar. Acepta errores de tipeo y variantes.")
    top: int      = Field(default=5, description="Número de resultados a retornar")

    @field_validator("consulta")
    def limpiar_consulta(cls, v):
        return normalizar(v)

    @field_validator("top")
    def top_valido(cls, v):
        return max(1, min(v, 10))

@tool(args_schema=BuscarPlatosInput)
def buscar_platos(consulta: str, top: int = 5) -> str:
    """
    Busca platos en la base de conocimiento de la cafetería usando búsqueda semántica
    (Cohere + LlamaIndex). Tolera errores de tipeo, tildes y variantes de lenguaje.
    Se usa siempre antes de semaforizar o registrar un plato para verificar si ya existe.
    Un score > 0.85 indica que el plato probablemente ya existe.
    """
    retriever = indice_platos.as_retriever(
        similarity_top_k=top,
        embed_model=embed_query,
    )
    nodos = retriever.retrieve(consulta)

    if not nodos:
        return f"No se encontraron platos similares a '{consulta}'."

    lineas = [f"Platos más similares a '{consulta}':\n"]
    for n in nodos:
        m = n.metadata
        if not m.get("nombre"):
            continue
        score = round(n.score, 3)
        alerta = " ← MUY SIMILAR" if score > 0.85 else ""
        lineas.append(
            f"  [{score}] {m['nombre']} | {m.get('rol','')} | {m.get('insumo','')} | {m.get('turno','')}{alerta}"
        )
    return "\n".join(lineas) if len(lineas) > 1 else f"No se encontraron platos similares a '{consulta}'."

print("Tool 'buscar_platos' definida ✓")

# ── Herramienta 2: semaforizar_plato ─────────────────────────────────
class SemaforizarInput(BaseModel):
    nombre_plato: str = Field(description="Nombre del plato a semaforizar")
    descripcion: str  = Field(default="", description="Descripción adicional: ingredientes o preparación")

    @field_validator("nombre_plato")
    def limpiar_nombre(cls, v):
        return v.strip()

@tool(args_schema=SemaforizarInput)
def semaforizar_plato(nombre_plato: str, descripcion: str = "") -> str:
    """
    Clasifica un plato en las 6 dimensiones nutricionales (Energía, Carbohidratos,
    Proteína, Grasas, Fibra, Sodio) usando V=Verde, A=Ámbar, R=Rojo.
    Usa las reglas del semáforo nutricional y ejemplos reales del encargado.
    Llama después de buscar_platos para confirmar que el plato existe.
    """
    ICON = {"V": "🟢", "A": "🟡", "R": "🔴", "N/A": "⚪"}

    ejemplos_texto = "\n".join([
        f"  Plato: {ej['plato']}\n"
        f"  Semáforo: {json.dumps(ej['semaforo'], ensure_ascii=False)}"
        for ej in ejemplos_fewshot
    ])
    reglas_texto = "\n".join([
        f"{dim}:\n  Verde: {crit['verde']}\n  Ámbar: {crit['ambar']}\n  Rojo: {crit['rojo']}"
        for dim, crit in reglas_semaforo.items()
    ])

    prompt = f"""Eres nutricionista experto en alimentación de trabajadores de planta industrial.
Clasifica el plato en cada dimensión usando SOLO V, A o R.
GUÍATE ESTRICTAMENTE de los ejemplos reales. Si el plato es similar a uno del ejemplo,
replica su clasificación. Si no hay ejemplo similar, aplica las reglas con criterio estricto:
en caso de duda entre dos valores, elige el MÁS RESTRICTIVO (ej: duda entre V y A → usa A).

REGLAS:
{reglas_texto}

EJEMPLOS REALES DEL ENCARGADO — síguelos al pie de la letra:
{ejemplos_texto}

Plato: {nombre_plato}
{('Descripción: ' + descripcion) if descripcion else ''}

Responde SOLO con JSON válido, sin texto adicional:
{{"Energía": "?", "Carbohidratos": "?", "Proteína": "?", "Grasas": "?", "Fibra": "?", "Sodio": "?"}}"""

    resp = llm.invoke(prompt)
    texto = resp.content.strip()
    match = re.search(r'\{[^}]+\}', texto, re.DOTALL)
    if not match:
        return "No se pudo clasificar el plato. Intenta con más descripción."
    semaforo = json.loads(match.group())
    semaforo = {k: (v if v in ("V", "A", "R") else "A") for k, v in semaforo.items()}

    dims_short = ["Energía", "Carboh.", "Proteína", "Grasas", "Fibra", "Sodio"]
    dim_keys   = ["Energía", "Carbohidratos", "Proteína", "Grasas", "Fibra", "Sodio"]
    header_row = " · ".join(dims_short)
    icon_parts = []
    for lbl, key in zip(dims_short, dim_keys):
        w = len(lbl); ico = ICON.get(semaforo.get(key, "A"), "🟡")
        left = (w - 2) // 2; right = w - 2 - left
        icon_parts.append(" " * left + ico + " " * right)
    icon_row = "   ".join(icon_parts)

    lineas = [
        f"\n{'='*55}",
        f"  SEMÁFORO NUTRICIONAL — {nombre_plato}",
        f"{'='*55}",
        f"  {header_row}",
        f"  {icon_row}",
        f"",
    ]
    for dim, val in semaforo.items():
        lineas.append(f"  {dim:15} → {ICON.get(val,'🟡')} {val}")
    lineas.append(f"{'='*55}")
    lineas.append(json.dumps(semaforo, ensure_ascii=False))
    return "\n".join(lineas)

print("Tool 'semaforizar_plato' definida ✓")

# ── Herramienta 3: registrar_plato_nuevo ─────────────────────────────
class RegistrarPlatoInput(BaseModel):
    nombre: str  = Field(description="Nombre del plato nuevo")
    insumo: str  = Field(description="Insumo principal: Res, Pollo, Cerdo, Pescado, Vegetariano, etc.")
    rol: str     = Field(description="Rol del plato: Fondo, Sopa, Ensalada, Entrada, Postre, Refresco, Cereal")
    turno: str   = Field(description="Turno: Desayuno, Almuerzo o Amanecida")
    guarniciones: str = Field(default="", description="Guarniciones opcionales")

    @field_validator("nombre", "insumo", "rol", "turno")
    def no_vacio(cls, v):
        if not v.strip():
            raise ValueError("El campo no puede estar vacío")
        return v.strip()

    @field_validator("guarniciones")
    def normalizar_guarniciones(cls, v):
        if not v.strip():
            return ""
        if "," not in v:
            return ", ".join(v.strip().split())
        return ", ".join(p.strip() for p in v.split(",") if p.strip())

@tool(args_schema=RegistrarPlatoInput)
def registrar_plato_nuevo(nombre: str, insumo: str, rol: str,
                          turno: str, guarniciones: str = "") -> str:
    """
    Registra un plato nuevo en el catálogo: guarda en Azure SQL (platos_nuevos),
    indexa en LlamaIndex y cachea su semáforo en cache_semaforo.
    IMPORTANTE: Llama primero a buscar_platos. Si score > 0.75, avisa al encargado
    que el plato probablemente ya existe y pide confirmación antes de llamar esta tool.
    """
    def safe_char(val):
        return val if val in ("V", "A", "R") else "?"

    DIMS = ["Energía", "Carbohidratos", "Proteína", "Grasas", "Fibra", "Sodio"]

    # 1. Verificación de duplicado con LlamaIndex
    nombre_norm = normalizar(nombre)
    retriever_dup = indice_platos.as_retriever(similarity_top_k=3, embed_model=embed_query)
    similares = retriever_dup.retrieve(nombre_norm)
    if similares and similares[0].score > 0.75:
        top = similares[0]
        score = round(top.score, 3)
        nivel = "MUY SIMILAR" if score > 0.85 else "SIMILAR"
        nombre_top = top.metadata.get("nombre", "desconocido")
        rol_top = top.metadata.get("rol", "")
        return (
            f"⚠️  PLATO {nivel} ENCONTRADO (score: {score}):\n"
            f"  → {nombre_top} ({rol_top})\n\n"
            f"  ¿Confirmas que '{nombre}' es un plato diferente y deseas registrarlo?\n"
            f"  (Responde 'sí, registrar' para confirmar)"
        )

    # 2. Guardar en Azure SQL (platos_nuevos)
    if SQL_DISPONIBLE:
        with SQL_ENGINE.connect() as conn:
            conn.execute(text("""
                INSERT INTO platos_nuevos (nombre, insumo, rol, turno, guarniciones)
                VALUES (:nombre, :insumo, :rol, :turno, :guarniciones)
            """), {
                "nombre": nombre, "insumo": insumo,
                "rol": rol, "turno": turno,
                "guarniciones": guarniciones
            })
            conn.commit()

    # 3. Clasificar semáforo y guardar en cache_semaforo
    resultado = semaforizar_plato.invoke({"nombre_plato": nombre})
    semaforo = {}
    for linea in reversed(resultado.strip().split("\n")):
        try:
            semaforo = json.loads(linea)
            break
        except Exception:
            continue
    if not semaforo:
        semaforo = {d: "A" for d in DIMS}

    if SQL_DISPONIBLE:
        with SQL_ENGINE.connect() as conn:
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM cache_semaforo WHERE nombre = :nombre)
                INSERT INTO cache_semaforo
                    (nombre, energia, carbohidratos, proteina, grasas, fibra, sodio)
                VALUES (:nombre, :energia, :carboh, :proteina, :grasas, :fibra, :sodio)
            """), {
                "nombre":   nombre,
                "energia":  safe_char(semaforo.get("Energía","?")),
                "carboh":   safe_char(semaforo.get("Carbohidratos","?")),
                "proteina": safe_char(semaforo.get("Proteína","?")),
                "grasas":   safe_char(semaforo.get("Grasas","?")),
                "fibra":    safe_char(semaforo.get("Fibra","?")),
                "sodio":    safe_char(semaforo.get("Sodio","?")),
            })
            conn.commit()

    # 4. Indexar en LlamaIndex (índice local)
    from llama_index.core import Document as LlamaDocument
    texto_nuevo = (
        f"Plato: {nombre}\nInsumo: {insumo}\nRol: {rol}\n"
        f"Turno: {turno}\nGuarniciones: {guarniciones}"
    )
    doc_nuevo = LlamaDocument(
        text=texto_nuevo,
        metadata={"nombre": nombre, "insumo": insumo, "rol": rol,
                  "turno": turno, "fuente": "registro_encargado"}
    )
    indice_platos.insert(doc_nuevo)
    indice_platos.storage_context.persist(persist_dir=CARPETA_IDX)

    ICON = {"V": "🟢", "A": "🟡", "R": "🔴"}
    icon_line = "  ".join(ICON.get(semaforo.get(d,"?"), "⚪") for d in DIMS)

    return (
        f"\n{'='*55}\n"
        f"  ✅ PLATO REGISTRADO EXITOSAMENTE\n"
        f"{'='*55}\n"
        f"  Nombre:       {nombre}\n"
        f"  Insumo:       {insumo}\n"
        f"  Rol:          {rol}\n"
        f"  Turno:        {turno}\n"
        f"  Guarniciones: {guarniciones or 'ninguna'}\n"
        f"  Semáforo:     {icon_line}\n"
        f"                Energía · Carboh · Proteína · Grasas · Fibra · Sodio\n"
        f"  Guardado en:  SQL (platos_nuevos) + cache_semaforo + LlamaIndex (local)\n"
        f"{'='*55}"
    )

print("Tool 'registrar_plato_nuevo' definida ✓")

# ── Herramienta 4: generar_menu_mes ──────────────────────────────────
class GenerarMenuMesInput(BaseModel):
    mes:     int  = Field(default=0, description="Mes (1-12). Si es 0, usa el mes siguiente al actual.")
    anio:    int  = Field(default=0, description="Año. Si es 0, usa el año actual.")
    forzado: bool = Field(default=False, description="Si True, elimina y regenera aunque ya exista un menú para ese mes.")

    @field_validator("mes")
    def mes_valido(cls, v):
        if v != 0 and not 1 <= v <= 12:
            raise ValueError("Mes debe estar entre 1 y 12")
        return v

@tool(args_schema=GenerarMenuMesInput)
def generar_menu_mes(mes: int = 0, anio: int = 0, forzado: bool = False) -> str:
    """
    Genera y guarda el menú mensual completo para todos los días del mes.
    Estructura: Desayuno (cereal) + Almuerzo (sopa + fondo + postre + refresco)
    + Amanecida (sopa + fondo). Respeta 60/30/10 por dimensión en los fondos.
    Usa cache SQL para no re-clasificar platos ya conocidos.
    """
    if not SQL_DISPONIBLE:
        return "❌ Azure SQL no disponible."

    hoy = date.today()
    if anio == 0: anio = hoy.year
    if mes  == 0:
        if hoy.month == 12:
            mes  = 1
            anio = hoy.year + 1   # Enero del año siguiente
        else:
            mes  = hoy.month + 1  # Mes siguiente al actual

    ICON  = {"V": "🟢", "A": "🟡", "R": "🔴", "?": "⚪"}
    DIMS  = ["Energía", "Carbohidratos", "Proteína", "Grasas", "Fibra", "Sodio"]
    TARGET = {"V": 0.60, "A": 0.30, "R": 0.10}
    MAX_REP = 4

    SLOTS = [
        ("Desayuno",          "Desayuno",  ["Cereal"],          False),
        ("Almuerzo_Sopa",     "Almuerzo",  ["Sopa", "Entrada"], False),
        ("Almuerzo_Fondo",    "Almuerzo",  ["Fondo", "Dieta"],  True),
        ("Almuerzo_Postre",   "Almuerzo",  ["Postre"],          False),
        ("Almuerzo_Refresco", "Almuerzo",  ["Refresco"],        False),
        ("Amanecida_Sopa",    "Amanecida", ["Sopa"],            False),
        ("Amanecida_Fondo",   "Amanecida", ["Fondo"],           True),
    ]

    def safe_char(val):
        return val if val in ("V", "A", "R") else "?"

    # 1. Cargar cache desde SQL
    with SQL_ENGINE.connect() as conn:
        rows = conn.execute(text(
            "SELECT nombre, energia, carbohidratos, proteina, grasas, fibra, sodio FROM cache_semaforo"
        )).fetchall()
    cache_semaforo = {}
    for row in rows:
        cache_semaforo[row[0]] = {
            "Energía": row[1], "Carbohidratos": row[2],
            "Proteína": row[3], "Grasas": row[4],
            "Fibra": row[5], "Sodio": row[6],
        }
    print(f"  Cache SQL: {len(cache_semaforo)} platos clasificados.")

    # 2. Cargar catálogo desde platos_kb.json
    print("  Cargando platos desde catálogo local...")
    with open(os.path.join(CARPETA_BDC, "platos_kb.json"), encoding="utf-8") as _f:
        _platos_raw = json.load(_f)
    catalogo = [
        {"nombre": p["nombre"], "rol": p.get("rol","Fondo"),
         "turno": p.get("turno","Almuerzo")}
        for p in _platos_raw
    ]
    print(f"  {len(catalogo)} platos en el catálogo.")
    if not catalogo:
        return "❌ No hay platos en el catálogo."

    # 3. Los platos sin cache usan "A" como semáforo temporal.
    #    La clasificación real ocurre DESPUÉS de armar el menú (solo ~50 platos únicos).
    print(f"  Platos en cache: {len(cache_semaforo)} / {len(catalogo)} (resto usa 'A' temporal)")

    # 4. Agrupar candidatos por slot
    candidatos_slot = {}
    for slot_nombre, turno_idx, roles_validos, _ in SLOTS:
        candidatos_slot[slot_nombre] = [
            {
                "nombre":   p["nombre"],
                "semaforo": cache_semaforo.get(p["nombre"], {d: "A" for d in DIMS})
            }
            for p in catalogo
            if p["turno"] == turno_idx and p["rol"] in roles_validos
        ]
        if not candidatos_slot[slot_nombre]:
            candidatos_slot[slot_nombre] = [
                {"nombre": p["nombre"],
                 "semaforo": cache_semaforo.get(p["nombre"], {d: "A" for d in DIMS})}
                for p in catalogo if p["turno"] == turno_idx
            ] or [{"nombre": "Sin plato", "semaforo": {d: "A" for d in DIMS}}]

    # 5. Función greedy
    def elegir_plato(candidatos, conteos, dia):
        mejor, mejor_score = None, float("inf")
        random.shuffle(candidatos)
        for c in candidatos:
            score = 0.0
            for dim in DIMS:
                val = c["semaforo"].get(dim, "A")
                for color in ["V", "A", "R"]:
                    nuevo = conteos[dim][color] + (1 if color == val else 0)
                    score += (nuevo / dia - TARGET[color]) ** 2
            if score < mejor_score:
                mejor_score, mejor = score, c
        return mejor

    # 6. Generar plan día por día
    dias_mes = calendar.monthrange(anio, mes)[1]
    plan = {}
    platos_usados_por_dia = {d: set() for d in range(1, dias_mes + 1)}

    for slot_nombre, _, _, usar_greedy in SLOTS:
        candidatos  = candidatos_slot[slot_nombre]
        conteos     = {dim: {"V": 0, "A": 0, "R": 0} for dim in DIMS}
        ultimo      = None
        conteo_plato = {}

        for dia in range(1, dias_mes + 1):
            disponibles = [
                c for c in candidatos
                if c["nombre"] != ultimo
                and c["nombre"] not in platos_usados_por_dia[dia]
                and conteo_plato.get(c["nombre"], 0) < MAX_REP
            ]
            if not disponibles:
                disponibles = [
                    c for c in candidatos
                    if c["nombre"] != ultimo
                    and c["nombre"] not in platos_usados_por_dia[dia]
                ] or candidatos

            elegido = elegir_plato(disponibles, conteos, dia) if usar_greedy \
                      else (random.choice(disponibles) if disponibles else candidatos[0])

            plan[(dia, slot_nombre)] = elegido
            ultimo = elegido["nombre"]
            platos_usados_por_dia[dia].add(elegido["nombre"])
            conteo_plato[elegido["nombre"]] = conteo_plato.get(elegido["nombre"], 0) + 1
            if usar_greedy:
                for dim in DIMS:
                    val = elegido["semaforo"].get(dim, "A")
                    if val in conteos[dim]:
                        conteos[dim][val] += 1

    # 6b. Clasificar SOLO los platos que quedaron en el menú (~50 únicos)
    nombres_usados = {item["nombre"] for item in plan.values()}
    nuevos_en_menu = [n for n in nombres_usados if n not in cache_semaforo]
    print(f"  Clasificando {len(nuevos_en_menu)} platos nuevos del menú generado...")
    with SQL_ENGINE.connect() as conn_cache:
        for nombre in nuevos_en_menu:
            resultado = semaforizar_plato.invoke({"nombre_plato": nombre})
            semaforo = {}
            for linea in reversed(resultado.strip().split("\n")):
                try:
                    semaforo = json.loads(linea)
                    break
                except Exception:
                    continue
            if not semaforo:
                semaforo = {d: "A" for d in DIMS}
            cache_semaforo[nombre] = semaforo
            # Actualizar semáforo en el plan ya generado
            plan_actualizado = {k: v for k, v in plan.items() if v["nombre"] == nombre}
            for k in plan_actualizado:
                plan[k]["semaforo"] = semaforo
            conn_cache.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM cache_semaforo WHERE nombre = :nombre)
                INSERT INTO cache_semaforo
                    (nombre, energia, carbohidratos, proteina, grasas, fibra, sodio)
                VALUES (:nombre, :energia, :carboh, :proteina, :grasas, :fibra, :sodio)
            """), {
                "nombre":   nombre,
                "energia":  safe_char(semaforo.get("Energía","A")),
                "carboh":   safe_char(semaforo.get("Carbohidratos","A")),
                "proteina": safe_char(semaforo.get("Proteína","A")),
                "grasas":   safe_char(semaforo.get("Grasas","A")),
                "fibra":    safe_char(semaforo.get("Fibra","A")),
                "sodio":    safe_char(semaforo.get("Sodio","A")),
            })
        conn_cache.commit()
    print(f"  ✅ {len(nuevos_en_menu)} platos clasificados y guardados en cache.")

    # 7. Guardar en Azure SQL
    mes_nombre = ["","Enero","Febrero","Marzo","Abril","Mayo","Junio",
                  "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"][mes]
    with SQL_ENGINE.connect() as conn:
        # Verificar si ya existe un menú para este mes/año
        existente = conn.execute(text("""
            SELECT COUNT(*) FROM menus_diarios
            WHERE YEAR(fecha) = :anio AND MONTH(fecha) = :mes
        """), {"anio": anio, "mes": mes}).scalar()
        if existente and existente > 0 and not forzado:
            return (
                f"⚠️ Ya existe un menú para {mes_nombre} {anio} ({existente} registros).\n"
                f"Si deseas regenerarlo, confirma con: 'regenerar menú {mes_nombre} {anio} forzado'."
            )
        conn.execute(text("""
            DELETE FROM menus_diarios
            WHERE YEAR(fecha) = :anio AND MONTH(fecha) = :mes
        """), {"anio": anio, "mes": mes})
        for (dia, slot), item in plan.items():
            s = item["semaforo"]
            conn.execute(text("""
                INSERT INTO menus_diarios
                    (fecha, turno, plato_nombre, energia, carbohidratos, proteina, grasas, fibra, sodio)
                VALUES (:fecha, :turno, :plato, :energia, :carboh, :proteina, :grasas, :fibra, :sodio)
            """), {
                "fecha":    date(anio, mes, dia), "turno": slot,
                "plato":    item["nombre"],
                "energia":  safe_char(s.get("Energía","?")),
                "carboh":   safe_char(s.get("Carbohidratos","?")),
                "proteina": safe_char(s.get("Proteína","?")),
                "grasas":   safe_char(s.get("Grasas","?")),
                "fibra":    safe_char(s.get("Fibra","?")),
                "sodio":    safe_char(s.get("Sodio","?")),
            })
        conn.commit()

    # 8. Resumen
    DIMS_CORTO  = ["Energía", "Carboh.", "Proteína", "Grasas", "Fibra", "Sodio"]
    header_dims = " · ".join(DIMS_CORTO)
    conteo_total = {"V": 0, "A": 0, "R": 0}

    DISPLAY = [
        ("Desayuno",          "Desayuno",   True),
        ("Almuerzo_Sopa",     "  Sopa",     True),
        ("Almuerzo_Fondo",    "  Fondo",    True),
        ("Almuerzo_Postre",   "  Postre",   True),
        ("Almuerzo_Refresco", "  Refresco", True),
        ("Amanecida_Sopa",    "Amanecer S", True),
        ("Amanecida_Fondo",   "Amanecer F", True),
    ]

    lineas = [f"\n{'='*65}", f"  MENÚ {mes_nombre.upper()} {anio}", f"{'='*65}"]
    dias_semana = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]

    for dia in range(1, dias_mes + 1):
        dow = dias_semana[date(anio, mes, dia).weekday()]
        lineas.append(f"\n  DÍA {dia:02d} — {dow}")
        seccion_actual = None
        for slot, etiqueta, mostrar_semaforo in DISPLAY:
            item = plan.get((dia, slot))
            if not item: continue
            if slot == "Almuerzo_Sopa" and seccion_actual != "Almuerzo":
                lineas.append("  ── Almuerzo ──────────────────────────────")
                seccion_actual = "Almuerzo"
            elif slot == "Amanecida_Sopa" and seccion_actual != "Amanecida":
                lineas.append("  ── Amanecida ─────────────────────────────")
                seccion_actual = "Amanecida"
            elif slot == "Desayuno":
                lineas.append("  ── Desayuno ──────────────────────────────")
                seccion_actual = "Desayuno"
            lineas.append(f"  {etiqueta:12} {item['nombre']}")
            if mostrar_semaforo:
                s = item["semaforo"]
                icon_parts = []
                for lbl, key in zip(DIMS_CORTO, DIMS):
                    w = len(lbl); ico = ICON.get(s.get(key,"?"), "⚪")
                    left = (w-2)//2; right = w-2-left
                    icon_parts.append(" "*left + ico + " "*right)
                    val = s.get(key,"?")
                    if val in conteo_total: conteo_total[val] += 1
                lineas.append(f"               {header_dims}")
                lineas.append(f"               {'   '.join(icon_parts)}")

    total = sum(conteo_total.values())
    pct = lambda k: round(conteo_total[k]/total*100) if total else 0
    lineas += [
        f"\n{'='*65}",
        f"  RESUMEN FONDOS DEL MES (Almuerzo + Amanecida)",
        f"  🟢 Verde : {conteo_total['V']:>3} ({pct('V')}%)",
        f"  🟡 Ámbar : {conteo_total['A']:>3} ({pct('A')}%)",
        f"  🔴 Rojo  : {conteo_total['R']:>3} ({pct('R')}%)",
        f"{'='*65}",
        f"  ✅ Guardado en Azure SQL (menus_diarios)",
        f"{'='*65}",
    ]
    return "\n".join(lineas)

print("Tool 'generar_menu_mes' definida ✓")

# ── Herramienta 5: obtener_menu_mes ──────────────────────────────────
class ObtenerMenuMesInput(BaseModel):
    mes: int        = Field(default=0, description="Mes (1-12). Si es 0, usa el mes siguiente al actual.")
    anio: int       = Field(default=0, description="Año. Si es 0, usa el año actual.")
    dia_inicio: int = Field(default=0, description="Día de inicio del rango (1-31). Si es 0, muestra el mes completo.")
    dia_fin: int    = Field(default=0, description="Día de fin del rango (1-31). Si es 0, usa el mismo que dia_inicio.")

    @field_validator("mes")
    def mes_valido(cls, v):
        if v != 0 and not 1 <= v <= 12:
            raise ValueError("Mes debe estar entre 1 y 12")
        return v

    @field_validator("dia_inicio", "dia_fin")
    def dia_valido(cls, v):
        if v != 0 and not 1 <= v <= 31:
            raise ValueError("Día debe estar entre 1 y 31")
        return v

@tool(args_schema=ObtenerMenuMesInput)
def obtener_menu_mes(mes: int = 0, anio: int = 0,
                     dia_inicio: int = 0, dia_fin: int = 0) -> str:
    """
    Muestra el menú guardado en Azure SQL con semáforo nutricional por plato.
    Permite consultar: todo el mes, un día específico o un rango de días.
    """
    if not SQL_DISPONIBLE:
        return "❌ Azure SQL no disponible."

    hoy = date.today()
    if anio == 0: anio = hoy.year
    if mes  == 0:
        if hoy.month == 12:
            mes  = 1
            anio = hoy.year + 1   # Enero del año siguiente
        else:
            mes  = hoy.month + 1  # Mes siguiente al actual

    ICON       = {"V": "🟢", "A": "🟡", "R": "🔴", "?": "⚪"}
    DIMS       = ["Energía", "Carbohidratos", "Proteína", "Grasas", "Fibra", "Sodio"]
    DIMS_CORTO = ["Energía", "Carboh.", "Proteína", "Grasas", "Fibra", "Sodio"]
    mes_nombre = ["","Enero","Febrero","Marzo","Abril","Mayo","Junio",
                  "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"][mes]

    es_rango = dia_inicio > 0
    if es_rango:
        dia_fin_real = dia_fin if dia_fin >= dia_inicio else dia_inicio
        query  = """
            SELECT fecha, turno, plato_nombre,
                   energia, carbohidratos, proteina, grasas, fibra, sodio
            FROM menus_diarios
            WHERE YEAR(fecha) = :anio AND MONTH(fecha) = :mes
              AND DAY(fecha) BETWEEN :di AND :df
            ORDER BY fecha, turno
        """
        params = {"anio": anio, "mes": mes, "di": dia_inicio, "df": dia_fin_real}
    else:
        query  = """
            SELECT fecha, turno, plato_nombre,
                   energia, carbohidratos, proteina, grasas, fibra, sodio
            FROM menus_diarios
            WHERE YEAR(fecha) = :anio AND MONTH(fecha) = :mes
            ORDER BY fecha, turno
        """
        params = {"anio": anio, "mes": mes}

    with SQL_ENGINE.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    if not rows:
        rango_txt = f"días {dia_inicio} al {dia_fin_real} de " if es_rango else ""
        return (f"⚠️ No hay menú guardado para {rango_txt}{mes_nombre} {anio}.\n"
                f"  Llama a generar_menu_mes para crear el menú del mes.")

    plan = {}
    for row in rows:
        d = row[0].day; slot = row[1]
        plan.setdefault(d, {})[slot] = {
            "nombre": row[2],
            "semaforo": {
                "Energía": row[3], "Carbohidratos": row[4],
                "Proteína": row[5], "Grasas": row[6],
                "Fibra": row[7], "Sodio": row[8],
            }
        }

    dias_semana = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
    header_dims = " · ".join(DIMS_CORTO)
    DISPLAY = [
        ("Desayuno",          "Desayuno",   True),
        ("Almuerzo_Sopa",     "  Sopa",     True),
        ("Almuerzo_Fondo",    "  Fondo",    True),
        ("Almuerzo_Postre",   "  Postre",   True),
        ("Almuerzo_Refresco", "  Refresco", True),
        ("Amanecida_Sopa",    "Amanecer S", True),
        ("Amanecida_Fondo",   "Amanecer F", True),
    ]
    conteo_total = {"V": 0, "A": 0, "R": 0}

    if es_rango and dia_inicio == dia_fin_real:
        titulo = f"DÍA {dia_inicio:02d} — {mes_nombre.upper()} {anio}"
    elif es_rango:
        titulo = f"MENÚ {mes_nombre.upper()} {anio} — DÍAS {dia_inicio} AL {dia_fin_real}"
    else:
        titulo = f"MENÚ {mes_nombre.upper()} {anio} — COMPLETO"

    lineas = [f"\n{'='*65}", f"  {titulo}", f"{'='*65}"]

    for d in sorted(plan.keys()):
        dow = dias_semana[date(anio, mes, d).weekday()]
        lineas.append(f"\n  DÍA {d:02d} — {dow}")
        seccion_actual = None
        for slot, etiqueta, _ in DISPLAY:
            item = plan[d].get(slot)
            if not item: continue
            if slot == "Desayuno" and seccion_actual != "Desayuno":
                lineas.append("  ── Desayuno ──────────────────────────────")
                seccion_actual = "Desayuno"
            elif slot == "Almuerzo_Sopa" and seccion_actual != "Almuerzo":
                lineas.append("  ── Almuerzo ──────────────────────────────")
                seccion_actual = "Almuerzo"
            elif slot == "Amanecida_Sopa" and seccion_actual != "Amanecida":
                lineas.append("  ── Amanecida ─────────────────────────────")
                seccion_actual = "Amanecida"
            lineas.append(f"  {etiqueta:12} {item['nombre']}")
            s = item["semaforo"]
            icon_parts = []
            for lbl, key in zip(DIMS_CORTO, DIMS):
                w = len(lbl); ico = ICON.get(s.get(key, "?"), "⚪")
                left = (w-2)//2; right = w-2-left
                icon_parts.append(" "*left + ico + " "*right)
                val = s.get(key, "?")
                if val in conteo_total: conteo_total[val] += 1
            lineas.append(f"               {header_dims}")
            lineas.append(f"               {'   '.join(icon_parts)}")

    total = sum(conteo_total.values())
    pct = lambda k: round(conteo_total[k]/total*100) if total else 0
    lineas += [
        f"\n{'='*65}",
        f"  RESUMEN SEMÁFORO DEL PERÍODO",
        f"  🟢 Verde : {conteo_total['V']:>3} ({pct('V')}%)",
        f"  🟡 Ámbar : {conteo_total['A']:>3} ({pct('A')}%)",
        f"  🔴 Rojo  : {conteo_total['R']:>3} ({pct('R')}%)",
        f"{'='*65}",
    ]
    return "\n".join(lineas)

print("Tool 'obtener_menu_mes' definida ✓")

# ── Herramienta 6: modificar_dia_menu ────────────────────────────────
class ModificarDiaMenuInput(BaseModel):
    dia: int   = Field(description="Día del mes (1-31)")
    mes: int   = Field(default=0, description="Mes (1-12). Si es 0, usa el mes siguiente al actual.")
    anio: int  = Field(default=0, description="Año. Si es 0, usa el año actual.")
    turno: str = Field(description="Slot: Desayuno, Almuerzo_Sopa, Almuerzo_Fondo, Almuerzo_Postre, Almuerzo_Refresco, Amanecida_Sopa, Amanecida_Fondo")
    plato_nuevo: str = Field(description="Nombre exacto del plato de reemplazo (debe existir en el catálogo)")

    @field_validator("dia")
    def dia_valido(cls, v):
        if not 1 <= v <= 31:
            raise ValueError("Día debe estar entre 1 y 31")
        return v

    @field_validator("mes")
    def mes_valido(cls, v):
        if v != 0 and not 1 <= v <= 12:
            raise ValueError("Mes debe estar entre 1 y 12")
        return v

    @field_validator("turno")
    def turno_valido(cls, v):
        validos = {"Desayuno", "Almuerzo_Sopa", "Almuerzo_Fondo",
                   "Almuerzo_Postre", "Almuerzo_Refresco",
                   "Amanecida_Sopa", "Amanecida_Fondo"}
        if v not in validos:
            raise ValueError(f"Turno debe ser uno de: {', '.join(sorted(validos))}")
        return v

@tool(args_schema=ModificarDiaMenuInput)
def modificar_dia_menu(dia: int, turno: str, plato_nuevo: str,
                       mes: int = 0, anio: int = 0) -> str:
    """
    Cambia un plato específico de un día del menú mensual en Azure SQL.
    El plato de reemplazo debe existir en el catálogo.
    """
    if not SQL_DISPONIBLE:
        return "❌ Azure SQL no disponible."

    hoy = date.today()
    if anio == 0: anio = hoy.year
    if mes  == 0:
        if hoy.month == 12:
            mes  = 1
            anio = hoy.year + 1   # Enero del año siguiente
        else:
            mes  = hoy.month + 1  # Mes siguiente al actual

    DIMS = ["Energía", "Carbohidratos", "Proteína", "Grasas", "Fibra", "Sodio"]
    ICON = {"V": "🟢", "A": "🟡", "R": "🔴", "?": "⚪"}

    def safe_char(val):
        return val if val in ("V", "A", "R") else "?"

    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        return f"❌ Fecha inválida: día {dia} no existe en {mes}/{anio}."

    with SQL_ENGINE.connect() as conn:
        existe = conn.execute(text("""
            SELECT COUNT(*) FROM menus_diarios
            WHERE fecha = :fecha AND turno = :turno
        """), {"fecha": fecha, "turno": turno}).scalar()

    if not existe:
        return (f"❌ No hay registro para día {dia} slot '{turno}' en {mes}/{anio}.\n"
                f"  Verifica con obtener_menu_mes que el mes esté generado.")

    with SQL_ENGINE.connect() as conn:
        row = conn.execute(text("""
            SELECT energia, carbohidratos, proteina, grasas, fibra, sodio
            FROM cache_semaforo WHERE nombre = :nombre
        """), {"nombre": plato_nuevo}).fetchone()

    if not row:
        return (
            f"⚠️ '{plato_nuevo}' no está en el catálogo.\n\n"
            f"  Para usarlo en el menú, primero regístralo:\n"
            f"  → Usa registrar_plato_nuevo con nombre, insumo, rol y turno.\n"
            f"  Luego vuelve a llamar modificar_dia_menu."
        )

    semaforo = {
        "Energía": row[0], "Carbohidratos": row[1],
        "Proteína": row[2], "Grasas": row[3],
        "Fibra": row[4], "Sodio": row[5],
    }

    with SQL_ENGINE.connect() as conn:
        anterior = conn.execute(text("""
            SELECT plato_nombre FROM menus_diarios
            WHERE fecha = :fecha AND turno = :turno
        """), {"fecha": fecha, "turno": turno}).scalar()

        conn.execute(text("""
            UPDATE menus_diarios
            SET plato_nombre   = :plato,
                energia        = :energia,
                carbohidratos  = :carboh,
                proteina       = :proteina,
                grasas         = :grasas,
                fibra          = :fibra,
                sodio          = :sodio,
                fecha_registro = GETDATE()
            WHERE fecha = :fecha AND turno = :turno
        """), {
            "plato":    plato_nuevo,
            "energia":  safe_char(semaforo.get("Energía","?")),
            "carboh":   safe_char(semaforo.get("Carbohidratos","?")),
            "proteina": safe_char(semaforo.get("Proteína","?")),
            "grasas":   safe_char(semaforo.get("Grasas","?")),
            "fibra":    safe_char(semaforo.get("Fibra","?")),
            "sodio":    safe_char(semaforo.get("Sodio","?")),
            "fecha":    fecha,
            "turno":    turno,
        })
        conn.commit()

    dias_semana = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
    dow = dias_semana[fecha.weekday()]
    icon_line = "  ".join(ICON.get(semaforo.get(d,"?"), "⚪") for d in DIMS)

    return (
        f"\n{'='*55}\n"
        f"  ✅ MENÚ ACTUALIZADO\n"
        f"{'='*55}\n"
        f"  Fecha:    {dia:02d}/{mes:02d}/{anio} ({dow})\n"
        f"  Slot:     {turno}\n"
        f"  Antes:    {anterior}\n"
        f"  Ahora:    {plato_nuevo}\n"
        f"  Semáforo: {icon_line}\n"
        f"            Energía · Carboh · Proteína · Grasas · Fibra · Sodio\n"
        f"{'='*55}"
    )

print("Tool 'modificar_dia_menu' definida ✓")

# ── NutriAgente (clase principal) ─────────────────────────────────────
SYSTEM_PROMPT = """Eres NutriAgente, el asistente inteligente del encargado del comedor de una planta de alimentos.

ESTRUCTURA DEL MENÚ:
- Desayuno: 1 cereal o bebida caliente
- Almuerzo: sopa + fondo + postre + refresco
- Amanecida (turno nocturno): sopa + fondo

REGLAS DEL SEMÁFORO:
- Meta mensual: 60% 🟢 Verde / 30% 🟡 Ámbar / 10% 🔴 Rojo
- Dimensiones: Energía, Carbohidratos, Proteína, Grasas, Fibra, Sodio
- El semáforo aplica a TODOS los platos (desayuno, sopa, fondo, postre, refresco)

TUS HERRAMIENTAS Y CUÁNDO USARLAS:
1. buscar_platos → cuando el encargado pregunte si un plato existe o antes de registrar uno nuevo
2. semaforizar_plato → para clasificar nutricionalmente un plato específico
3. registrar_plato_nuevo → agregar plato al catálogo (llama a buscar_platos primero)
4. generar_menu_mes → crear el menú automático del mes completo
5. obtener_menu_mes → ver el menú guardado en SQL (día, rango de días o mes completo)
6. modificar_dia_menu → cambiar un plato de un día específico

FLUJOS IMPORTANTES:
- Ver menú → SIEMPRE usa obtener_menu_mes
- "día 5" → dia_inicio=5, dia_fin=0
- "primera semana" → dia_inicio=1, dia_fin=7
- "segunda semana" → dia_inicio=8, dia_fin=14
- "tercera semana" → dia_inicio=15, dia_fin=21
- "cuarta semana" → dia_inicio=22, dia_fin=28
- Si no especifica año, usa el año del menú guardado (generalmente el siguiente al actual)
- Si no especifica mes, asume el mes siguiente al actual
- Cambiar plato de un día → modificar_dia_menu; si el plato no está en catálogo, registrar_plato_nuevo primero
- Antes de registrar plato nuevo, llama a buscar_platos para detectar duplicados

FORMATO AL CLASIFICAR UN PLATO:
Energía 🟢 | Carbohidratos 🟡 | Proteína 🟢 | Grasas 🟢 | Fibra 🔴 | Sodio 🟢

FUERA DE DOMINIO:
Si el encargado pregunta algo que no tiene que ver con el menú, platos, nutrición
o gestión del comedor, responde amablemente que solo puedes ayudar con esos temas.

TONO: amigable, directo y profesional. Responde siempre en español."""


TOOLS_CON_SALIDA_DIRECTA = {"obtener_menu_mes", "generar_menu_mes", "modificar_dia_menu"}


class AgenteNutri:
    def __init__(self, thread_id: str = "encargado-1"):
        self.thread_id = thread_id
        self.config    = {"configurable": {"thread_id": thread_id}}

        checkpointer = MemorySaver()
        self.agent = create_agent(
            model=llm,
            tools=[
                buscar_platos,
                semaforizar_plato,
                registrar_plato_nuevo,
                generar_menu_mes,
                obtener_menu_mes,
                modificar_dia_menu,
            ],
            checkpointer=checkpointer,
            system_prompt=SYSTEM_PROMPT,
        )

        # Restaurar historial previo desde Azure SQL
        if SQL_DISPONIBLE:
            try:
                with SQL_ENGINE.connect() as conn:
                    rows = conn.execute(text("""
                        SELECT rol, contenido FROM historial_chat
                        WHERE thread_id = :tid
                        ORDER BY fecha
                    """), {"tid": thread_id}).fetchall()

                if rows:
                    mensajes_previos = [
                        HumanMessage(content=c) if r == "human"
                        else AIMessage(content=c)
                        for r, c in rows
                    ]
                    self.agent.invoke({"messages": mensajes_previos}, self.config)
                    print(f"[{thread_id}] {len(rows)} mensajes restaurados desde SQL ✓")
                else:
                    print(f"[{thread_id}] Nueva sesión — sin historial previo.")
            except Exception as e:
                print(f"[{thread_id}] Sin historial SQL ({e}) → MemorySaver como fallback.")

    def _guardar_historial(self, rol: str, contenido: str):
        if not SQL_DISPONIBLE:
            return
        try:
            with SQL_ENGINE.connect() as conn:
                conn.execute(text("""
                    INSERT INTO historial_chat (rol, contenido, thread_id)
                    VALUES (:rol, :contenido, :tid)
                """), {"rol": rol, "contenido": contenido, "tid": self.thread_id})
                conn.commit()
        except Exception:
            pass

    def chat(self, texto: str) -> str:
        print(f"\n{'─'*60}")
        print(f"Encargado   : {texto}")
        print(f"{'─'*60}")

        self._guardar_historial("human", texto)

        resultado = self.agent.invoke(
            {"messages": [HumanMessage(content=texto)]},
            self.config,
        )

        messages = resultado["messages"]

        last_human_idx = 0
        for i, msg in enumerate(messages):
            if isinstance(msg, HumanMessage):
                last_human_idx = i

        recent_messages = messages[last_human_idx:]
        respuesta = None
        for msg in reversed(recent_messages):
            if isinstance(msg, ToolMessage):
                if msg.name in TOOLS_CON_SALIDA_DIRECTA:
                    respuesta = msg.content
                else:
                    respuesta = None
                break

        if not respuesta:
            respuesta = messages[-1].content

        if isinstance(respuesta, list):
            respuesta = " ".join(
                b["text"] for b in respuesta if b.get("type") == "text"
            )

        self._guardar_historial("ai", respuesta)
        print(f"NutriAgente : {respuesta}")
        return respuesta


# ── EJECUCIÓN DIRECTA (pruebas en terminal) ───────────────────────────
# Solo se ejecuta con: python Nutriagente.py
# La app Streamlit importa este módulo sin ejecutar las pruebas.
if __name__ == "__main__":
    agente = AgenteNutri(thread_id="encargado-1")
    print("NutriAgente listo ✓")
    print(f"  SQL : {'historial_chat activo' if SQL_DISPONIBLE else 'no disponible → MemorySaver'}")
    print("="*60)

    print(agente.chat("dame las dimensiones de este plato: Pollo al sillao c/papa y arroz"))
    print(agente.chat("quiero ver el menu del dia dos de octubre"))
    print(agente.chat("califica los nutrientes de este plato: Lomo Saltado"))
    print(agente.chat("podemos modificar el postre de la fecha que te consulte por keke de vainilla"))
    print(agente.chat("dame el menu del dos de octubre"))
    print(agente.chat("necesito que me des un resumen de la conquista española a peru para la tarea de mi hijo"))
