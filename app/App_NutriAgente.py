# -*- coding: utf-8 -*-
# App_NutriAgente.py
# Interfaz Streamlit para NutriAgente — conectada al servidor MCP
#
# REQUISITO: el servidor MCP debe estar corriendo antes de abrir Streamlit:
#   conda activate jupyter312
#   cd "C:\Users\milu_\ricardo palma ia\Proyecto NutriAgente\Py"
#   python mcp_nutriagente_server.py
#
# Ejecutar Streamlit (en otra terminal):
#   streamlit run App_NutriAgente.py

import warnings
warnings.filterwarnings("ignore")

import logging
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)

import asyncio
import concurrent.futures
import json
import os
from datetime import date

import streamlit as st

# URL del servidor MCP (cambiar a Azure cuando se despliegue)
MCP_URL = os.getenv("MCP_URL", "http://localhost:8081/mcp")


# ══════════════════════════════════════════════════════════════════════
# HELPERS MCP
# ══════════════════════════════════════════════════════════════════════
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def _mcp_call(nombre_tool: str, args: dict) -> str:
    transport = StreamableHttpTransport(MCP_URL)
    async with Client(transport=transport) as client:
        resultado = await client.call_tool(nombre_tool, args)
        if resultado and resultado.content:
            return resultado.content[0].text
        return ""


def _run_async(coro):
    """Ejecuta una coroutine en un thread separado con su propio event loop.
    Evita conflictos con anyio (usado internamente por FastMCP)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result(timeout=60)


def mcp(nombre_tool: str, args: dict) -> str:
    try:
        return _run_async(_mcp_call(nombre_tool, args))
    except Exception as e:
        return f"Error al ejecutar {nombre_tool}: {str(e)}"


# ══════════════════════════════════════════════════════════════════════
# AGENTE MCP (creado una vez por sesión)
# ══════════════════════════════════════════════════════════════════════
@st.cache_resource
def crear_agente():
    from langchain_core.tools import tool
    from langchain_anthropic import ChatAnthropic
    from langchain.agents import create_agent
    from langgraph.checkpoint.memory import MemorySaver
    from dotenv import load_dotenv

    CARPETA_CONN = r"C:\Users\milu_\ricardo palma ia\Proyecto NutriAgente\Conexiones"
    load_dotenv(os.path.join(CARPETA_CONN, ".env"))

    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

    @tool
    def buscar_platos(consulta: str, top: int = 5) -> str:
        """Busca platos en la base de conocimiento nutricional."""
        return mcp("buscar_platos", {"consulta": consulta, "top": top})

    @tool
    def semaforizar_plato(nombre_plato: str, descripcion: str = "") -> str:
        """Clasifica un plato en 6 dimensiones nutricionales: V=Verde, A=Ambar, R=Rojo."""
        return mcp("semaforizar_plato", {"nombre_plato": nombre_plato, "descripcion": descripcion})

    @tool
    def registrar_plato_nuevo(nombre: str, insumo: str, rol: str, turno: str, guarniciones: str = "") -> str:
        """Registra un plato nuevo en el catalogo de la cafeteria."""
        return mcp("registrar_plato_nuevo", {"nombre": nombre, "insumo": insumo, "rol": rol, "turno": turno, "guarniciones": guarniciones})

    @tool
    def generar_menu_mes(mes: int = 0, anio: int = 0, forzado: bool = False) -> str:
        """Genera y guarda el menu mensual completo. Si ya existe menu para ese mes avisa al usuario.
        Usar forzado=True solo si el usuario confirma que quiere regenerar el menu existente."""
        return mcp("generar_menu_mes", {"mes": mes, "anio": anio, "forzado": forzado})

    @tool
    def obtener_menu_mes(mes: int = 0, anio: int = 0, dia_inicio: int = 0, dia_fin: int = 0) -> str:
        """Muestra el menu guardado con semaforo nutricional."""
        return mcp("obtener_menu_mes", {"mes": mes, "anio": anio, "dia_inicio": dia_inicio, "dia_fin": dia_fin})

    @tool
    def modificar_dia_menu(dia: int, turno: str, plato_nuevo: str, mes: int = 0, anio: int = 0) -> str:
        """Cambia un plato especifico de un dia del menu mensual."""
        return mcp("modificar_dia_menu", {"dia": dia, "turno": turno, "plato_nuevo": plato_nuevo, "mes": mes, "anio": anio})

    from datetime import date as _date
    _hoy = _date.today()
    SYSTEM_PROMPT = f"""Eres NutriAgente, asistente inteligente del encargado del comedor
de una planta de alimentos. Tienes acceso a herramientas para:
- Buscar platos en el catálogo (buscar_platos)
- Clasificar platos nutricionalmente con semáforo V/A/R (semaforizar_plato)
- Registrar platos nuevos en el catálogo (registrar_plato_nuevo)
- Generar el menú mensual completo (generar_menu_mes)
- Ver el menú guardado (obtener_menu_mes)
- Modificar un día del menú (modificar_dia_menu)

REGLAS IMPORTANTES:
- La fecha de hoy es {_hoy.strftime('%d/%m/%Y')} (mes={_hoy.month}, año={_hoy.year}).
- Cuando el usuario NO especifique el año, usa anio={_hoy.year} (año actual). NUNCA preguntes por el año si el usuario no lo indicó.
- Cuando el usuario NO especifique el mes, usa el mes siguiente al actual (mes {_hoy.month % 12 + 1}).
- Para generar_menu_mes: si la herramienta avisa que ya existe un menú, muestra el aviso al usuario y espera su confirmación antes de llamar con forzado=True.
- Para modificar_dia_menu: el parámetro 'turno' acepta variantes como "desayuno", "sopa", "fondo", "postre", "refresco", "amanecida sopa", "amanecida fondo".

Responde siempre en español de forma amigable y profesional."""

    return create_agent(
        model=llm,
        tools=[buscar_platos, semaforizar_plato, registrar_plato_nuevo,
               generar_menu_mes, obtener_menu_mes, modificar_dia_menu],
        checkpointer=MemorySaver(),
        system_prompt=SYSTEM_PROMPT,
    )


# ══════════════════════════════════════════════════════════════════════
# VERIFICAR SERVIDOR MCP AL INICIAR
# ══════════════════════════════════════════════════════════════════════
async def _verificar_servidor() -> bool:
    try:
        transport = StreamableHttpTransport(MCP_URL)
        async with Client(transport=transport) as client:
            tools = await client.list_tools()
            return len(tools) > 0
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE PÁGINA
# ══════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="NutriAgente", page_icon="🥗", layout="wide")

with st.sidebar:
    st.title("🥗 NutriAgente")
    st.caption("Asistente inteligente del comedor")
    st.divider()
    pagina = st.radio("Navegación", ["💬 Chat", "📅 Menú del Mes", "🚦 Semáforo"])
    st.divider()
    st.caption(f"MCP: `{MCP_URL}`")
    st.caption("Proyecto Módulo IV · LangChain + MCP")

try:
    servidor_ok = _run_async(_verificar_servidor())
except Exception:
    servidor_ok = False
if not servidor_ok:
    st.error(f"❌ Servidor MCP no disponible en `{MCP_URL}`")
    st.info("Ejecuta primero:\n```\nconda activate jupyter312\npython mcp_nutriagente_server.py\n```")
    st.stop()

with st.spinner("Conectando con NutriAgente MCP..."):
    try:
        agente_mcp = crear_agente()
    except Exception as e:
        st.error(f"Error al crear el agente: {e}")
        st.stop()


# ══════════════════════════════════════════════════════════════════════
# PÁGINA 1: CHAT
# ══════════════════════════════════════════════════════════════════════
if pagina == "💬 Chat":
    st.header("💬 Chat con NutriAgente")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread_id" not in st.session_state:
        import uuid
        st.session_state.thread_id = f"streamlit-{uuid.uuid4().hex[:8]}"

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Escribe tu consulta al encargado de nutrición..."):
        from langchain_core.messages import HumanMessage
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("NutriAgente está pensando..."):
                try:
                    config = {"configurable": {"thread_id": st.session_state.thread_id}}
                    resultado = agente_mcp.invoke(
                        {"messages": [HumanMessage(content=prompt)]},
                        config=config,
                    )
                    respuesta = resultado["messages"][-1].content
                except Exception as e:
                    respuesta = f"❌ Error: {e}"
                    # Resetear thread para evitar estado corrupto en la conversación
                    import uuid
                    st.session_state.thread_id = f"streamlit-{uuid.uuid4().hex[:8]}"
            st.markdown(respuesta)
            st.session_state.messages.append({"role": "assistant", "content": respuesta})

    if st.session_state.messages:
        if st.button("🗑️ Limpiar conversación"):
            st.session_state.messages = []
            st.rerun()


# ══════════════════════════════════════════════════════════════════════
# PÁGINA 2: MENÚ DEL MES
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📅 Menú del Mes":
    st.header("📅 Menú del Mes")

    hoy = date.today()
    col1, col2, col3 = st.columns(3)
    with col1:
        mes_sel = st.selectbox(
            "Mes", list(range(1, 13)),
            index=hoy.month % 12,
            format_func=lambda m: ["","Enero","Febrero","Marzo","Abril","Mayo","Junio",
                                    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"][m]
        )
    with col2:
        anio_sel = st.number_input("Año", min_value=2024, max_value=2030,
                                    value=hoy.year + (1 if hoy.month == 12 else 0))
    with col3:
        dia_sel = st.number_input("Día (0 = mes completo)", min_value=0, max_value=31, value=0)

    if st.button("🔍 Ver menú"):
        with st.spinner("Consultando menú..."):
            try:
                from sqlalchemy import create_engine, text as sqlt
                from collections import defaultdict

                conn_str = os.getenv("SQL_CONNECTION_STRING")
                if not conn_str:
                    st.error("SQL_CONNECTION_STRING no configurado en este container.")
                    st.stop()

                engine = create_engine(conn_str)

                if int(dia_sel) > 0:
                    q = """SELECT fecha,turno,plato_nombre,energia,carbohidratos,proteina,grasas,fibra,sodio
                           FROM menus_diarios
                           WHERE YEAR(fecha)=:anio AND MONTH(fecha)=:mes AND DAY(fecha)=:dia
                           ORDER BY turno"""
                    p = {"anio": int(anio_sel), "mes": mes_sel, "dia": int(dia_sel)}
                else:
                    q = """SELECT fecha,turno,plato_nombre,energia,carbohidratos,proteina,grasas,fibra,sodio
                           FROM menus_diarios
                           WHERE YEAR(fecha)=:anio AND MONTH(fecha)=:mes
                           ORDER BY fecha,turno"""
                    p = {"anio": int(anio_sel), "mes": mes_sel}

                with engine.connect() as conn:
                    rows = conn.execute(sqlt(q), p).fetchall()

                if not rows:
                    st.info("No hay menú guardado para ese período.")
                else:
                    ICON   = {"V":"🟢","A":"🟡","R":"🔴","?":"⚪"}
                    DIMS   = ["Energía","Carbohidratos","Proteína","Grasas","Fibra","Sodio"]
                    DIMS_C = ["Energía","Carboh.","Proteína","Grasas","Fibra","Sodio"]

                    plan = defaultdict(dict)
                    for row in rows:
                        plan[row[0].day][row[1]] = {
                            "nombre": row[2],
                            "semaforo": dict(zip(DIMS, [row[3],row[4],row[5],row[6],row[7],row[8]]))
                        }

                    dias_semana = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
                    ORDER  = ["Desayuno","Almuerzo_Sopa","Almuerzo_Fondo","Almuerzo_Postre",
                              "Almuerzo_Refresco","Amanecida_Sopa","Amanecida_Fondo"]
                    SECCION = {"Desayuno":"☀️ Desayuno","Almuerzo_Sopa":"🍽️ Almuerzo",
                               "Amanecida_Sopa":"🌙 Amanecida"}
                    conteo = {"V":0,"A":0,"R":0}

                    for d in sorted(plan.keys()):
                        dow = dias_semana[date(int(anio_sel), mes_sel, d).weekday()]
                        st.subheader(f"Día {d:02d} — {dow}")
                        sec_actual = None
                        tabla = []
                        for slot in ORDER:
                            item = plan[d].get(slot)
                            if not item: continue
                            sec_nueva = SECCION.get(slot)
                            if sec_nueva and sec_nueva != sec_actual:
                                if tabla:
                                    df_cols = ["Plato"] + DIMS_C
                                    st.table([dict(zip(df_cols, r)) for r in tabla])
                                    tabla = []
                                st.markdown(f"**{sec_nueva}**")
                                sec_actual = sec_nueva
                            s = item["semaforo"]
                            fila = [item["nombre"]]
                            for dim in DIMS:
                                v = s.get(dim,"?")
                                fila.append(ICON.get(v,"⚪"))
                                if v in conteo: conteo[v] += 1
                            tabla.append(fila)
                        if tabla:
                            df_cols = ["Plato"] + DIMS_C
                            st.table([dict(zip(df_cols, r)) for r in tabla])
                        st.divider()

                    total = sum(conteo.values()) or 1
                    st.subheader("Resumen del período")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("🟢 Verde", f"{conteo['V']}  ({round(conteo['V']/total*100)}%)")
                    c2.metric("🟡 Ámbar", f"{conteo['A']}  ({round(conteo['A']/total*100)}%)")
                    c3.metric("🔴 Rojo",  f"{conteo['R']}  ({round(conteo['R']/total*100)}%)")

            except Exception as e:
                st.error(f"Error al consultar el menú: {e}")


# ══════════════════════════════════════════════════════════════════════
# PÁGINA 3: SEMÁFORO
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🚦 Semáforo":
    st.header("🚦 Semáforo Nutricional")
    st.caption("Clasifica cualquier plato en Verde / Ámbar / Rojo por dimensión nutricional")

    nombre = st.text_input("Nombre del plato", placeholder="Ej: Lomo saltado con arroz y papas fritas")
    descripcion = st.text_area("Descripción adicional (opcional)",
                                placeholder="Ej: incluye fritura, base de arroz, guiso de res")

    if st.button("Clasificar plato 🔍"):
        if not nombre.strip():
            st.warning("Ingresa el nombre del plato.")
        else:
            DIMS = ["Energía","Carbohidratos","Proteína","Grasas","Fibra","Sodio"]
            ICON = {"V":"🟢","A":"🟡","R":"🔴"}

            with st.spinner("Clasificando vía MCP..."):
                try:
                    resultado = mcp("semaforizar_plato", {
                        "nombre_plato": nombre,
                        "descripcion": descripcion,
                    })
                    semaforo = {}
                    for linea in reversed(resultado.strip().split("\n")):
                        try:
                            semaforo = json.loads(linea)
                            break
                        except Exception:
                            continue
                    if not semaforo:
                        semaforo = {d: "A" for d in DIMS}
                except Exception as e:
                    st.error(f"Error al clasificar: {e}")
                    semaforo = {d: "A" for d in DIMS}

            st.subheader(f"Resultado: {nombre}")
            cols = st.columns(6)
            for i, dim in enumerate(DIMS):
                val = semaforo.get(dim, "A")
                icono = ICON.get(val, "⚪")
                label = {"V":"Verde","A":"Ámbar","R":"Rojo"}.get(val, "?")
                with cols[i]:
                    st.markdown(f"### {icono}")
                    st.markdown(f"**{dim}**")
                    st.caption(label)

            resumen = sum(1 for v in semaforo.values() if v == "V")
            st.divider()
            if resumen >= 4:
                st.success("✅ Plato con buena clasificación nutricional (mayoría Verde)")
            elif sum(1 for v in semaforo.values() if v == "R") >= 3:
                st.error("⚠️ Plato con alta proporción Rojo — considerar alternativas")
            else:
                st.info("ℹ️ Clasificación mixta — puede incluirse con balance mensual")
