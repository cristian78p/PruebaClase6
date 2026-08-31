import requests
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuración inicial
st.set_page_config(
    page_title="Nivel de Rios y Quebradas - CORNARE",
    layout="wide"
)

# Parámetros fijos de la regla de negocio
NOMBRE_ESTUDIANTE = "Cristian Camilo Rey Beltrán"
CODIGO_ESTACION = "44"
FECHA_DESDE = "2026-08-15"
FECHA_HASTA = "2026-08-30"
CALIDAD = 1

LAT_DEFECTO = 6.2766
LON_DEFECTO = -75.5901
API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"

CANDIDATOS_LAT = ["lat", "latitude", "latitud", "y"]
CANDIDATOS_LON = ["lng", "lon", "longitude", "longitud", "x"]

# Funciones de consulta
@st.cache_data(ttl=600)
def obtener_metadatos_estacion(codigo_estacion):
    url = f"{API_BASE_URL}/{codigo_estacion}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

@st.cache_data(ttl=600)
def consultar_api_nivel(codigo_estacion, desde, hasta, calidad):
    url = f"{API_BASE_URL}/{codigo_estacion}/nivel"
    params = {"desde": desde, "hasta": hasta, "calidad": calidad}
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    
    registros = []
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=20, verify=False)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        
        data = resp.json()
        registros.extend(data.get("values", []))
        
        siguiente_url = data.get("next")
        while siguiente_url:
            r = requests.get(siguiente_url, headers=headers, timeout=20, verify=False)
            if r.status_code == 200:
                pag = r.json()
                registros.extend(pag.get("values", []))
                siguiente_url = pag.get("next")
            else:
                break
        return registros, None
    except Exception as e:
        return None, str(e)

def extraer_coordenadas(d):
    if not isinstance(d, dict):
        return None, None
    lat = next((d[k] for k in CANDIDATOS_LAT if k in d and d[k] is not None), None)
    lon = next((d[k] for k in CANDIDATOS_LON if k in d and d[k] is not None), None)
    
    if (lat is None or lon is None) and "location" in d and isinstance(d["location"], dict):
        return extraer_coordenadas(d["location"])
        
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            pass
    return None, None

def calcular_indice_calidad(df):
    if df.empty or len(df) < 2:
        return 0.0, 0, 0

    df_idx = df.set_index("fecha")
    frecuencia_tipica = df["fecha"].diff().dropna().mode()
    if len(frecuencia_tipica) == 0:
        return 0.0, 0, 0
    frecuencia_tipica = frecuencia_tipica[0]

    rango_completo = pd.date_range(start=df_idx.index.min(), end=df_idx.index.max(), freq=frecuencia_tipica)
    esperados = len(rango_completo)
    huecos = esperados - len(df_idx)
    completitud = max(0.0, 1 - (huecos / esperados)) if esperados > 0 else 0.0

    Q1, Q3 = df["nivel"].quantile(0.25), df["nivel"].quantile(0.75)
    IQR = Q3 - Q1
    lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
    es_outlier = (df["nivel"] < lim_inf) | (df["nivel"] > lim_sup) | (df["nivel"] < 0)
    proporcion_outliers = es_outlier.mean()

    indice = (completitud * 0.7 + (1 - proporcion_outliers) * 0.3) * 100
    return round(indice, 1), int(huecos), int(es_outlier.sum())

# Encabezado principal
st.title("Nivel de Rios y Quebradas - CORNARE")
st.write(f"Estudiante: {NOMBRE_ESTUDIANTE} | Estacion: {CODIGO_ESTACION} | Periodo: {FECHA_DESDE} al {FECHA_HASTA}")
st.divider()

# Consulta automatica
with st.spinner("Cargando informacion de la estacion..."):
    meta_json = obtener_metadatos_estacion(CODIGO_ESTACION)
    lat, lon = extraer_coordenadas(meta_json)
    coords_reales = lat is not None and lon is not None
    if not coords_reales:
        lat, lon = LAT_DEFECTO, LON_DEFECTO

    registros, error = consultar_api_nivel(CODIGO_ESTACION, FECHA_DESDE, FECHA_HASTA, CALIDAD)

if error:
    st.error(f"Error al conectar con la API: {error}")
elif not registros:
    st.warning("No se encontraron registros para la estacion y periodo especificados.")
else:
    df = pd.DataFrame(registros)
    df = df.rename(columns={"level_date": "fecha", "level": "nivel"})
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
    df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

    indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

    # Métricas principales
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Lecturas", f"{len(df):,}")
    m2.metric("Nivel Promedio", f"{df['nivel'].mean():.2f} m")
    m3.metric("Nivel Maximo", f"{df['nivel'].max():.2f} m")
    m4.metric("Indice Calidad", f"{indice_calidad} / 100")
    m5.metric("Outliers", n_outliers)

    st.write("")

    # Organizacion en pestañas
    tab_grafico, tab_mapa, tab_datos = st.tabs([
        "Serie Temporal", 
        "Ubicacion Geografica", 
        "Exportacion de Datos"
    ])

    with tab_grafico:
        st.subheader("Grafico Historico de Nivel")
        fig = px.line(
            df, 
            x="fecha", 
            y="nivel", 
            title=f"Estacion {CODIGO_ESTACION}",
            labels={"fecha": "Fecha y Hora", "nivel": "Nivel (m)"},
            template="plotly_white"
        )
        fig.update_traces(line_color="#1F77B4", line_width=2, fill="tozeroy", fillcolor="rgba(31, 119, 180, 0.1)")
        fig.update_layout(
            hovermode="x unified",
            margin=dict(l=20, r=20, t=40, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab_mapa:
        st.subheader("Ubicacion de la Estacion")
        if not coords_reales:
            st.info("Coordenadas específicas no retornadas por la API. Se presenta mapa predeterminado.")
        
        map_df = pd.DataFrame({"lat": [lat], "lon": [lon]})
        st.map(map_df, zoom=12)

    with tab_datos:
        st.subheader("Registros Obtenidos")
        col_tabla, col_descarga = st.columns([3, 1])
        
        with col_tabla:
            st.dataframe(df, use_container_width=True, height=350)
            
        with col_descarga:
            st.write("Descargar CSV optimizado para Excel:")
            csv_data = df.to_csv(index=False, sep=";", decimal=".").encode("utf-8-sig")
            st.download_button(
                label="Descargar CSV",
                data=csv_data,
                file_name=f"estacion_{CODIGO_ESTACION}_{FECHA_DESDE}_a_{FECHA_HASTA}.csv",
                mime="text/csv",
                use_container_width=True
            )
            st.write(f"- Huecos detectados: {huecos}")
            st.write(f"- Outliers detectados: {n_outliers}")
