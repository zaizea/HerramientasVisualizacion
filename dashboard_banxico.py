# Tablero del SIE de Banxico, con token
# Herramientas de Visualización · IDIA22X · Paarcial III
#
#     pip install -r requirements.txt
#     streamlit run dashboard_banxico.py
#
# EL TOKEN NO VA EN ESTE ARCHIVO.
# En tu equipo: crea la carpeta .streamlit y dentro un archivo secrets.toml
# con una sola línea:
#     banxico_token = "pega-aqui-tu-token"
# Al publicar: pega esa misma línea en la sección de secretos de la app.
# El archivo secrets.toml nunca se sube al repositorio.

import os
from datetime import date, datetime

import matplotlib.pyplot as plt
import pandas as pd
import requests
import seaborn as sns
import streamlit as st

# ─── Paleta del curso ──────────────────────────────────────────────────
GRIS = "#B9C3D1"
AZUL = "#1C4C9A"
ROJO = "#B2182B"
AZUL_POS = "#2166AC"
CUALI = ["#E69F00", "#56B4E9", "#009E73", "#0072B2"]
sns.set_theme(style="whitegrid")

SIE = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"

st.set_page_config(page_title="Tablero del SIE", layout="wide")


# ─── El token ──────────────────────────────────────────────────────────
def leer_token():
    try:
        if "banxico_token" in st.secrets:
            return str(st.secrets["banxico_token"]).strip()
    except Exception:
        pass  # todavía no existe el archivo de secretos
    if os.environ.get("BANXICO_TOKEN"):
        return os.environ["BANXICO_TOKEN"].strip()
    return None


TOKEN = leer_token()

# Se valida al leerlo: un token vacío produce el mismo error que una URL
# mal escrita, y sin esta revisión el problema aparece mucho después.
if TOKEN and len(TOKEN) < 32:
    st.error(f"El token tiene {len(TOKEN)} caracteres y deberían ser 64. "
             "Revisa que esté completo y sin comillas.")
    st.stop()

if not TOKEN:
    st.error("Falta el token del SIE.")
    st.markdown(
        "1. Pídelo gratis en "
        "https://www.banxico.org.mx/SieAPIRest/service/v1/token\n"
        "2. Crea la carpeta `.streamlit` junto a este archivo.\n"
        "3. Dentro, un archivo `secrets.toml` con la línea:\n"
        '   `banxico_token = "tu-token"`\n'
        "4. Vuelve a cargar esta página."
    )
    st.stop()


# ─── La consulta ───────────────────────────────────────────────────────
# El SIE acepta varias claves separadas por comas en la misma petición,
# así que un solo viaje trae todas las series del tablero.
@st.cache_data(ttl=3600, show_spinner=False)
def consultar(claves, inicio, fin, token):
    url = f"{SIE}/{','.join(claves)}/datos/{inicio}/{fin}"
    respuesta = requests.get(
        url,
        headers={
            "Bmx-Token": token,
            "Accept": "application/json",
            "User-Agent": "UPQ-IDIA224/1.0",
        },
        timeout=60,
    )

    if respuesta.status_code == 401:
        raise PermissionError("El token no fue aceptado.")
    if respuesta.status_code == 429:
        raise PermissionError("Demasiadas peticiones. Espera un momento.")
    respuesta.raise_for_status()

    # Un 200 no garantiza JSON: el SIE contesta con una página de error
    # y sigue siendo un 200 válido.
    tipo = respuesta.headers.get("Content-Type") or ""
    if "json" not in tipo:
        raise ValueError(f"El servidor no devolvió JSON sino {tipo}. "
                         "Suele ser el token o una clave inexistente.")

    tablas = []
    faltantes = {}

    for serie in respuesta.json()["bmx"]["series"]:
        if "datos" not in serie:          # la clave existe pero sin datos
            continue
        t = pd.DataFrame(serie["datos"])
        t["Fecha"] = pd.to_datetime(t.pop("fecha"), format="%d/%m/%Y")

        # El valor llega como texto; los días inhábiles traen "N/E"
        faltantes[serie["idSerie"]] = int((t["dato"] == "N/E").sum())
        t["Valor"] = pd.to_numeric(
            t.pop("dato").str.replace(",", "", regex=False), errors="coerce")

        t["Clave"] = serie["idSerie"]
        t["Serie"] = serie.get("titulo", serie["idSerie"])
        tablas.append(t)

    if not tablas:
        raise ValueError("Ninguna de las claves devolvió datos en ese rango.")

    df = pd.concat(tablas, ignore_index=True)
    df["Anio"] = df["Fecha"].dt.year
    df["Mes"] = df["Fecha"].dt.month
    return df, faltantes


# ─── Controles ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Qué consultar")
    texto = st.text_input(
        "Claves de las series", "SF43718",
        help="Sepáralas con comas. Búscalas en el catálogo del SIE. "
             "SF43718 es el tipo de cambio FIX.")
    inicio = st.date_input("Desde", date(2021, 1, 1))
    fin = st.date_input("Hasta", date(2025, 12, 31))
    suavizado = st.slider("Días de media móvil", 1, 90, 30)
    st.caption("Fuente: SIE, Banco de México")

claves = [c.strip().upper() for c in texto.split(",") if c.strip()]

if not claves:
    st.info("Escribe al menos una clave en el panel de la izquierda.")
    st.stop()
if inicio >= fin:
    st.error("La fecha inicial debe ser anterior a la final.")
    st.stop()

with st.spinner("Consultando el SIE..."):
    try:
        df, faltantes = consultar(tuple(claves), str(inicio), str(fin), TOKEN)
    except PermissionError as e:
        st.error(str(e))
        st.stop()
    except ValueError as e:
        st.warning(str(e))
        st.stop()
    except requests.exceptions.RequestException as e:
        st.error(f"No se pudo consultar el SIE: {e}")
        st.stop()

limpio = df.dropna(subset=["Valor"]).copy()
if limpio.empty:
    st.warning("No hay valores numéricos en ese rango.")
    st.stop()

# La serie de referencia para los indicadores es la primera que se pidió
principal = limpio[limpio["Clave"] == claves[0]].sort_values("Fecha").copy()
titulo_principal = principal["Serie"].iloc[0]


# ─── Encabezado e indicadores ──────────────────────────────────────────
st.title("Tablero de series del SIE")
# El título lo declara Banxico: confirma que la clave es la correcta.
st.caption(f"{titulo_principal} · del {inicio} al {fin} · "
           f"consultado el {datetime.now():%d/%m/%Y %H:%M}")

primero = principal["Valor"].iloc[0]
ultimo = principal["Valor"].iloc[-1]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Días con dato", len(principal))
c2.metric("Días inhábiles (N/E)", faltantes.get(claves[0], 0))
c3.metric("Último valor", f"{ultimo:,.4f}",
          delta=f"{(ultimo / primero - 1) * 100:+.1f} % en el periodo")
c4.metric("Mínimo y máximo",
          f"{principal['Valor'].min():,.2f} – {principal['Valor'].max():,.2f}")

st.divider()


# ─── Gráficas ──────────────────────────────────────────────────────────
izquierda, derecha = st.columns(2)

with izquierda:
    if len(claves) == 1:
        st.subheader("La serie y su tendencia")
        principal["Suave"] = principal["Valor"].rolling(suavizado).mean()

        fig, ax = plt.subplots(figsize=(6, 3.4))
        ax.plot(principal["Fecha"], principal["Valor"], color=GRIS,
                linewidth=0.9, label="Valor diario")
        ax.plot(principal["Fecha"], principal["Suave"], color=AZUL,
                linewidth=2, label=f"Media móvil {suavizado} días")
        ax.set_xlabel("Fecha")
        ax.set_ylabel("Valor de la serie")
        ax.legend(frameon=False)
        st.pyplot(fig)
    else:
        # Varias series van en escalas distintas: se normalizan a base 100
        # para que lo comparable sea el crecimiento, no el nivel.
        st.subheader("Comparación en base 100")
        limpio = limpio.sort_values("Fecha")
        limpio["Base100"] = (limpio.groupby("Clave")["Valor"]
                                   .transform(lambda s: s / s.iloc[0] * 100))

        fig, ax = plt.subplots(figsize=(6, 3.4))
        for i, clave in enumerate(claves):
            parte = limpio[limpio["Clave"] == clave]
            if parte.empty:
                continue
            ax.plot(parte["Fecha"], parte["Base100"],
                    color=CUALI[i % len(CUALI)], linewidth=1.8, label=clave)
        ax.axhline(100, color="gray", linewidth=0.8)
        ax.set_xlabel("Fecha")
        ax.set_ylabel("Índice base 100")
        ax.legend(frameon=False)
        st.pyplot(fig)

with derecha:
    st.subheader("Cambio de un mes a otro")
    # Para un precio, el valor del mes es el de cierre, no el promedio.
    mensual = (principal.set_index("Fecha")["Valor"].resample("ME").last())
    cambio = (mensual.pct_change() * 100).dropna()

    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.bar(cambio.index,
           cambio.values,
           color=[ROJO if v > 0 else AZUL_POS for v in cambio.values],
           width=20)
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_xlabel("Mes")
    ax.set_ylabel("Cambio respecto al mes anterior (%)")
    st.pyplot(fig)
    st.caption("Rojo: el valor subió. Azul: bajó. Para un tipo de cambio, "
               "subir significa que el peso se debilitó.")

abajo_izq, abajo_der = st.columns(2)
with abajo_izq:
    st.subheader("Qué tan movido estuvo cada año")
    principal["Variacion"] = principal["Valor"].pct_change() * 100
    porAnio = principal.dropna(subset=["Variacion"])

    fig, ax = plt.subplots(figsize=(6, 3.4))
    sns.boxplot(data=porAnio, x="Anio", y="Variacion", color=GRIS, ax=ax)
    ax.axhline(0, color=ROJO, linewidth=1, linestyle="--")
    ax.set_xlabel("Año")
    ax.set_ylabel("Variación diaria (%)")
    st.pyplot(fig)

with abajo_der:
    st.subheader("Qué tan común es un brinco fuerte")
    variacion = porAnio["Variacion"]   # variación diaria (%), ya calculada arriba
    brincos = int((variacion.abs() > 2).sum())
    pct = brincos / len(variacion) * 100

    fig, ax = plt.subplots(figsize=(6, 3.4))
    sns.histplot(variacion, bins=50, color=GRIS, ax=ax)
    ax.axvline(2, color=ROJO, linestyle="--", linewidth=1)
    ax.axvline(-2, color=ROJO, linestyle="--", linewidth=1)
    ax.set_xlabel("Variación diaria (%)")
    ax.set_ylabel("Número de días")
    st.pyplot(fig)
    st.caption(f"{brincos} de {len(variacion)} días ({pct:.1f} %) se movieron "
               "más de 2 %, hacia arriba o hacia abajo.")


# ─── Datos ─────────────────────────────────────────────────────────────
with st.expander("Ver y descargar los datos"):
    st.write("Días marcados como N/E por serie:", faltantes)
    st.dataframe(df)
    st.download_button(
        "Descargar CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"sie_{'_'.join(claves)}_{inicio}_{fin}.csv",
        mime="text/csv",
    )