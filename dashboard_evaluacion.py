import os
from datetime import date, datetime

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import requests
import seaborn as sns
import streamlit as st

# ─── Paleta del curso ──────────────────────────────────────────────────
GRIS = "#B9C3D1"
AZUL = "#1C4C9A"
ROJO = "#B2182B"
sns.set_theme(style="whitegrid")

SIE = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"
SERIE = "SF43718"  # tipo de cambio FIX, pesos por dólar
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

st.set_page_config(page_title="Tipo de cambio FIX", layout="wide")


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

# Se valida al leerlo: un token incompleto da el mismo error que una URL mal
# escrita, y sin esta revisión el problema aparece mucho después.
if len(TOKEN) < 32:
    st.error(f"El token tiene {len(TOKEN)} caracteres y deberían ser 64. "
             "Revisa que esté completo y sin comillas.")
    st.stop()


# ─── La consulta ───────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def consultar(inicio, fin, token):
    url = f"{SIE}/{SERIE}/datos/{inicio}/{fin}"
    respuesta = requests.get(
        url,
        headers={
            "Bmx-Token": token,
            "Accept": "application/json",
            "User-Agent": "UPQ-IDIA222/1.0",
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

    serie = respuesta.json()["bmx"]["series"][0]
    if "datos" not in serie:
        raise ValueError("La serie no devolvió datos en ese rango.")

    t = pd.DataFrame(serie["datos"])
    t["Fecha"] = pd.to_datetime(t["fecha"], format="%d/%m/%Y")
    # El valor llega como texto; los días inhábiles traen "N/E"
    t["Valor"] = pd.to_numeric(
        t["dato"].str.replace(",", "", regex=False), errors="coerce")
    t = (t.dropna(subset=["Valor"])
          .sort_values("Fecha")
          .reset_index(drop=True))
    return t[["Fecha", "Valor"]], serie.get("titulo", SERIE)


# ─── Controles ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Qué consultar")
    inicio = st.date_input("Desde", date(2021, 1, 1))
    fin = st.date_input("Hasta", date.today())
    suavizado = st.slider("Días de media móvil", 5, 90, 30)
    umbral = st.slider("Brinco fuerte (% en un solo día)", 1.0, 5.0, 2.0, 0.5)

if inicio >= fin:
    st.error("La fecha inicial debe ser anterior a la final.")
    st.stop()

with st.spinner("Consultando el SIE..."):
    try:
        df, titulo = consultar(str(inicio), str(fin), TOKEN)
    except PermissionError as e:
        st.error(str(e))
        st.stop()
    except ValueError as e:
        st.warning(str(e))
        st.stop()
    except requests.exceptions.RequestException as e:
        st.error(f"No se pudo consultar el SIE: {e}")
        st.stop()

if len(df) < 30:
    st.warning("Hay muy pocos datos en ese rango. Amplía las fechas.")
    st.stop()

df = df.copy()
df["Media"] = df["Valor"].rolling(window=suavizado).mean()
df["Variacion"] = df["Valor"].pct_change() * 100   # variación diaria, en %
df["Anio"] = df["Fecha"].dt.year
df["Mes"] = df["Fecha"].dt.month
variacion = df["Variacion"].dropna()

# Los años a comparar dependen de los datos recibidos, por eso van aquí
anios = sorted(df["Anio"].unique().tolist())
with st.sidebar:
    st.subheader("Estabilidad entre años")
    anio_a = st.selectbox(
        "Año A", anios, index=anios.index(2021) if 2021 in anios else 0)
    anio_b = st.selectbox(
        "Año B", anios,
        index=anios.index(2025) if 2025 in anios else len(anios) - 1)
    st.caption("Fuente: SIE, Banco de México")

# Valor de hoy (el último dato) y el de hace tres años
hoy = df.iloc[-1]
previo = df[df["Fecha"] <= hoy["Fecha"] - pd.DateOffset(years=3)]
hace3 = previo.iloc[-1] if not previo.empty else None

por_mes = df.groupby("Mes")["Variacion"].std()
brincos = int((variacion.abs() > umbral).sum())
pct_brincos = brincos / len(variacion) * 100


# ─── Encabezado e indicadores ──────────────────────────────────────────
st.title("Tipo de cambio FIX: tablero para el área de compras")
# El título lo declara Banxico: confirma que la clave es la correcta.
st.caption(f"{titulo} · del {inicio} al {fin} · "
           f"consultado el {datetime.now():%d/%m/%Y %H:%M}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Último valor", f"{hoy['Valor']:,.2f}",
          delta=(f"{hoy['Valor'] - hace3['Valor']:+.2f} vs hace 3 años"
                 if hace3 is not None else None),
          delta_color="off")
c2.metric("Fecha del último dato", f"{hoy['Fecha']:%d/%m/%Y}")
c3.metric(f"Días con brinco de más de {umbral:g} %", f"{pct_brincos:.1f} %",
          help=f"{brincos} de {len(variacion)} días")
c4.metric("Mes con más movimiento", MESES[int(por_mes.idxmax()) - 1])

st.divider()


# ─── Necesidades 1 y 2 ─────────────────────────────────────────────────
izquierda, derecha = st.columns(2)

with izquierda:
    st.subheader("¿Más caro o más barato que hace 3 años?")
    if hace3 is None:
        st.info("Amplía el rango («Desde») para tener datos de hace 3 años.")
    else:
        tramo = df[df["Fecha"] >= hace3["Fecha"]]
        dif = hoy["Valor"] - hace3["Valor"]
        palabra = "más caro" if dif > 0 else "más barato"

        fig, ax = plt.subplots(figsize=(6, 3.4))
        ax.plot(tramo["Fecha"], tramo["Valor"], color=GRIS, linewidth=0.9,
                label="Valor diario")
        ax.plot(tramo["Fecha"], tramo["Media"], color=AZUL, linewidth=2,
                label=f"Media móvil {suavizado} días")
        ax.axhline(hace3["Valor"], color=ROJO, linestyle="--", linewidth=1,
                   label="Nivel de hace 3 años")
        ax.scatter([hace3["Fecha"], hoy["Fecha"]],
                   [hace3["Valor"], hoy["Valor"]], color=ROJO, zorder=5)
        # Pocas marcas en el eje de fechas, para que no se amontonen
        marcas = mdates.AutoDateLocator(minticks=3, maxticks=7)
        ax.xaxis.set_major_locator(marcas)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(marcas))
        ax.set_xlabel("Fecha")
        ax.set_ylabel("Pesos por dólar")
        ax.legend(frameon=False)
        st.pyplot(fig)
        st.caption(f"Hoy el dólar está {palabra} que hace 3 años: "
                   f"{hace3['Valor']:.2f} → {hoy['Valor']:.2f} pesos "
                   f"({dif:+.2f}).")

with derecha:
    st.subheader("¿En qué meses se mueve más?")
    colores = [AZUL if m == por_mes.idxmax() else GRIS for m in por_mes.index]

    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.bar([MESES[int(m) - 1] for m in por_mes.index], por_mes.values,
           color=colores)
    ax.set_xlabel("Mes del año")
    ax.set_ylabel("Movimiento diario (desv. est., %)")
    st.pyplot(fig)
    st.caption("En azul, el mes con más movimiento. Con pocos años de datos "
               "es una tendencia, no una regla segura.")


# ─── Necesidades 3 y 4 ─────────────────────────────────────────────────
abajo_izq, abajo_der = st.columns(2)

with abajo_izq:
    st.subheader("¿Qué tan común es un brinco fuerte?")

    fig, ax = plt.subplots(figsize=(6, 3.4))
    sns.histplot(variacion, bins=50, color=GRIS, ax=ax)
    ax.axvline(umbral, color=ROJO, linestyle="--", linewidth=1)
    ax.axvline(-umbral, color=ROJO, linestyle="--", linewidth=1)
    ax.set_xlabel("Variación diaria (%)")
    ax.set_ylabel("Número de días")
    st.pyplot(fig)
    st.caption(f"{brincos} de {len(variacion)} días ({pct_brincos:.1f} %) "
               f"se movieron más de {umbral:g} %, hacia arriba o hacia abajo.")

with abajo_der:
    st.subheader(f"¿Qué tan estable fue {anio_a} contra {anio_b}?")
    if anio_a == anio_b:
        st.info("Elige dos años distintos en el panel de la izquierda.")
    else:
        comp = df[df["Anio"].isin([anio_a, anio_b])].dropna(
            subset=["Variacion"])
        desv = comp.groupby("Anio")["Variacion"].std()

        fig, ax = plt.subplots(figsize=(6, 3.4))
        sns.boxplot(data=comp, x="Anio", y="Variacion", hue="Anio",
                    order=sorted([anio_a, anio_b]),
                    palette={anio_a: GRIS, anio_b: AZUL},
                    legend=False, ax=ax)
        ax.axhline(0, color=ROJO, linewidth=1, linestyle="--")
        ax.set_xlabel("Año")
        ax.set_ylabel("Variación diaria (%)")
        st.pyplot(fig)

        mas_estable = desv.idxmin()
        st.caption(f"Desviación estándar de la variación diaria: "
                   f"{anio_a} = {desv[anio_a]:.3f} %, "
                   f"{anio_b} = {desv[anio_b]:.3f} %. "
                   f"El año más estable fue {mas_estable}.")


# ─── Lo que estos datos no pueden responder ────────────────────────────
with st.expander("Lo que NO se puede responder con estos datos"):
    st.markdown(
        "- **¿Se mueve junto con las tasas de interés?** Estos datos solo "
        "traen el tipo de cambio. Haría falta otra serie, la de las tasas, "
        "del mismo periodo.\n"
        "- **¿Cuánto costará el dólar el mes que entra?** Una serie "
        "histórica muestra lo que ya pasó, no asegura lo que va a pasar.\n"
        "- **¿Cuánto dinero se perdió el año pasado?** Faltan los montos y "
        "las fechas de compra de la empresa; el tipo de cambio solo dice "
        "cuánto valía el dólar cada día."
    )


# ─── Datos ─────────────────────────────────────────────────────────────
with st.expander("Ver y descargar los datos"):
    st.dataframe(df[["Fecha", "Valor", "Variacion"]])
    st.download_button(
        "Descargar CSV",
        df[["Fecha", "Valor", "Variacion"]].to_csv(index=False).encode("utf-8"),
        file_name=f"tipo_cambio_fix_{inicio}_{fin}.csv",
        mime="text/csv",
    )