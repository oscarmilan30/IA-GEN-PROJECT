# -*- coding: utf-8 -*-
# mcp_nutriagente_server.py
# Servidor MCP de NutriAgente — expone los 6 tools via HTTP
#
# Ejecutar localmente:
#   pip install fastmcp -q
#   python mcp_nutriagente_server.py
#
# El servidor queda en: http://localhost:8080/mcp

import sys
import os

# ── Agregar carpeta Py al path para importar Nutriagente ──────────────
CARPETA_PY = r"C:\Users\milu_\ricardo palma ia\Proyecto NutriAgente\Py"
if CARPETA_PY not in sys.path:
    sys.path.insert(0, CARPETA_PY)

# ── Importar tools ya construidos en Nutriagente.py ───────────────────
# No duplicamos lógica: el servidor MCP es solo un wrapper HTTP
print("Cargando Nutriagente.py (puede tardar unos segundos)...")
import Nutriagente as nb
print("Nutriagente cargado ✓")

from fastmcp import FastMCP

mcp = FastMCP("nutriagente-tools")

# ══════════════════════════════════════════════════════════════════════
# Tool 1: buscar_platos
# ══════════════════════════════════════════════════════════════════════
@mcp.tool(description=(
    "Busca platos en la base de conocimiento de la cafetería usando búsqueda "
    "semántica (Cohere + LlamaIndex). Tolera errores de tipeo y variantes. "
    "Score > 0.85 indica que el plato probablemente ya existe."
))
async def buscar_platos(consulta: str, top: int = 5) -> str:
    return nb.buscar_platos.invoke({"consulta": consulta, "top": top})


# ══════════════════════════════════════════════════════════════════════
# Tool 2: semaforizar_plato
# ══════════════════════════════════════════════════════════════════════
@mcp.tool(description=(
    "Clasifica un plato en 6 dimensiones nutricionales (Energía, Carbohidratos, "
    "Proteína, Grasas, Fibra, Sodio) con V=Verde, A=Ámbar, R=Rojo. "
    "Usa reglas del nutricionista y ejemplos reales del encargado."
))
async def semaforizar_plato(nombre_plato: str, descripcion: str = "") -> str:
    return nb.semaforizar_plato.invoke({
        "nombre_plato": nombre_plato,
        "descripcion": descripcion,
    })


# ══════════════════════════════════════════════════════════════════════
# Tool 3: registrar_plato_nuevo
# ══════════════════════════════════════════════════════════════════════
@mcp.tool(description=(
    "Registra un plato nuevo en el catálogo: guarda en Azure SQL (platos_nuevos), "
    "indexa en LlamaIndex y cachea su semáforo. Llama primero a buscar_platos "
    "para evitar duplicados."
))
async def registrar_plato_nuevo(
    nombre: str,
    insumo: str,
    rol: str,
    turno: str,
    guarniciones: str = "",
) -> str:
    return nb.registrar_plato_nuevo.invoke({
        "nombre": nombre,
        "insumo": insumo,
        "rol": rol,
        "turno": turno,
        "guarniciones": guarniciones,
    })


# ══════════════════════════════════════════════════════════════════════
# Tool 4: generar_menu_mes
# ══════════════════════════════════════════════════════════════════════
@mcp.tool(description=(
    "Genera y guarda el menú mensual completo (Desayuno + Almuerzo + Amanecida) "
    "respetando la meta 60/30/10 por dimensión en los fondos. "
    "Si mes=0 usa el mes actual; si anio=0 usa el año actual. "
    "Si ya existe un menú para ese mes, devuelve una advertencia. "
    "Para regenerar un menú existente, pasar forzado=True."
))
async def generar_menu_mes(mes: int = 0, anio: int = 0, forzado: bool = False) -> str:
    return nb.generar_menu_mes.invoke({"mes": mes, "anio": anio, "forzado": forzado})


# ══════════════════════════════════════════════════════════════════════
# Tool 5: obtener_menu_mes
# ══════════════════════════════════════════════════════════════════════
@mcp.tool(description=(
    "Muestra el menú guardado en Azure SQL con semáforo nutricional. "
    "Permite consultar todo el mes, un día específico o un rango de días. "
    "dia_inicio=0 muestra el mes completo."
))
async def obtener_menu_mes(
    mes: int = 0,
    anio: int = 0,
    dia_inicio: int = 0,
    dia_fin: int = 0,
) -> str:
    return nb.obtener_menu_mes.invoke({
        "mes": mes,
        "anio": anio,
        "dia_inicio": dia_inicio,
        "dia_fin": dia_fin,
    })


# ══════════════════════════════════════════════════════════════════════
# Tool 6: modificar_dia_menu
# ══════════════════════════════════════════════════════════════════════
@mcp.tool(description=(
    "Cambia un plato específico de un día del menú mensual en Azure SQL. "
    "El plato de reemplazo debe existir en el catálogo (cache_semaforo). "
    "Slots válidos: Desayuno, Almuerzo_Sopa, Almuerzo_Fondo, Almuerzo_Postre, "
    "Almuerzo_Refresco, Amanecida_Sopa, Amanecida_Fondo."
))
async def modificar_dia_menu(
    dia: int,
    turno: str,
    plato_nuevo: str,
    mes: int = 0,
    anio: int = 0,
) -> str:
    # Normalizar turno: el agente puede pasar "desayuno" o "Desayuno" o "sopa"
    # El validador de Nutriagente.py exige mayúsculas exactas
    _turno_map = {
        "desayuno":         "Desayuno",
        "sopa":             "Almuerzo_Sopa",
        "almuerzo sopa":    "Almuerzo_Sopa",
        "almuerzo_sopa":    "Almuerzo_Sopa",
        "fondo":            "Almuerzo_Fondo",
        "almuerzo fondo":   "Almuerzo_Fondo",
        "almuerzo_fondo":   "Almuerzo_Fondo",
        "postre":           "Almuerzo_Postre",
        "almuerzo postre":  "Almuerzo_Postre",
        "almuerzo_postre":  "Almuerzo_Postre",
        "refresco":         "Almuerzo_Refresco",
        "almuerzo refresco":"Almuerzo_Refresco",
        "almuerzo_refresco":"Almuerzo_Refresco",
        "amanecida sopa":   "Amanecida_Sopa",
        "amanecida_sopa":   "Amanecida_Sopa",
        "amanecida fondo":  "Amanecida_Fondo",
        "amanecida_fondo":  "Amanecida_Fondo",
    }
    turno_norm = _turno_map.get(turno.lower().strip(), turno)

    return nb.modificar_dia_menu.invoke({
        "dia": dia,
        "turno": turno_norm,
        "plato_nuevo": plato_nuevo,
        "mes": mes,
        "anio": anio,
    })


# ══════════════════════════════════════════════════════════════════════
# Arrancar servidor
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("="*55)
    print("  NutriAgente MCP Server")
    print("  URL: http://localhost:8081/mcp")
    print("  Tools: buscar_platos, semaforizar_plato,")
    print("         registrar_plato_nuevo, generar_menu_mes,")
    print("         obtener_menu_mes, modificar_dia_menu")
    print("="*55)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081, stateless_http=True)
