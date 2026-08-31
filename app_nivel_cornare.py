import requests
import pandas as pd
import numpy as np
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Coordenadas por defecto (I.U. Pascual Bravo)
LAT_DEFECTO = 6.2766
LON_DEFECTO = -75.5901

API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"

LLAVE_FECHA = "level_date"
LLAVE_VALOR = "level"
CANDIDATOS_LAT = ["lat", "latitude", "latitud", "y"]
CANDIDATOS_LON = ["lng", "lon", "longitude", "longitud", "x"]

st.set_page_config(page_title="Nivel de estación — CORNARE", page_icon="🌊", layout="wide")

# ------------------------------------------------------------------
# Funciones de consulta
# ------------------------------------------------------------------
def obtener_metadatos_estacion(codigo_estacion, timeout=15):
    """Obtiene la información general de la estación (incluyendo latitud/longitud)."""
    url = f"{API_BASE_URL}/{codigo_estacion}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 200:
            return resp.json()
    except requests.exceptions.RequestException:
        pass
    return None

def obtener_serie_nivel(codigo_estacion, desde, hasta, calidad=1, timeout=30):
    url = f"{API_BASE_URL}/{codigo_estacion}/nivel"
    params = {"desde": desde, "hasta": hasta, "calidad": calidad}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except requests.exceptions.RequestException as e:
        return None, f"Error de red: {e}"

def obtener_todas_las_paginas(datos_json, timeout=30):
    registros = list(datos_json.get("values", []))
    siguiente_url = datos_json.get("next")
    while siguiente_url:
        try:
            resp = requests.get(siguiente_url, timeout=timeout, verify=False)
        except requests.exceptions.RequestException:
            break
        if resp.status_code != 200:
            break
        pagina = resp.json()
        registros.extend(pagina.get("values", []))
        siguiente_url = pagina.get("next")
    return registros

def extraer_coordenadas_dict(d):
    """Recorre recursivamente o busca latitud/longitud en un diccionario."""
    if not isinstance(d, dict):
        return None, None
    
    lat = next((d[k] for k in CANDIDATOS_LAT if k in d and d[k] is not None), None)
    lon = next((d[k] for k in CANDIDATOS_LON if k in d and d[k] is not None), None)
    
    # Si las coordenadas están dentro de un subobjeto como "location" o "geometry"
    if (lat is None or lon is None) and "location" in d and isinstance(d["location"], dict):
        return extraer_coordenadas_dict(d["location"])
    
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

# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
st.sidebar.header("Parámetros de tu consulta")
nombre_estudiante = st.sidebar.text_input("Nombre del estudiante", "Tu Nombre Aquí")
codigo_estacion = st.sidebar.text_input("Código de estación", "42")
fecha_desde = st.sidebar.date_input("Desde", pd.to_datetime("2026-08-23")).strftime("%Y-%m-%d")
fecha_hasta = st.sidebar.date_input("Hasta", pd.to_datetime("2026-08-30")).strftime("%Y-%m-%d")
calidad = st.sidebar.selectbox("Calidad", [1, 0], index=0, help="1 = solo datos validados")
consultar = st.sidebar.button("🔍 Consultar", type="primary")

st.title("🌊 Nivel de ríos y quebradas — CORNARE")
st.caption(f"Estudiante: **{nombre_estudiante}** · Estación: **{codigo_estacion}**")

# ------------------------------------------------------------------
# Procesamiento
# ------------------------------------------------------------------
if consultar:
    with st.spinner("Consultando metadatos y series de la API..."):
        # 1. Consultar metadatos para las coordenadas
        meta_json = obtener_metadatos_estacion(codigo_estacion)
        lat, lon = extraer_coordenadas_dict(meta_json)
        coords_reales = lat is not None and lon is not None

        if not coords_reales:
            lat, lon = LAT_DEFECTO, LON_DEFECTO

        # 2. Consultar serie de nivel
        datos_crudos, error = obtener_serie_nivel(codigo_estacion, fecha_desde, fecha_hasta, calidad)

    if error:
        st.error(f"❌ {error}")
    else:
        registros = obtener_todas_las_paginas(datos_crudos)

        if not registros:
            st.warning("No hay registros para esta estación y rango de fechas. Prueba otro código u otro rango.")
        else:
            df = pd.DataFrame(registros)
            df = df.rename(columns={LLAVE_FECHA: "fecha", LLAVE_VALOR: "nivel"})
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
            df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
            df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

            indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

            # Metrics
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Lecturas", len(df))
            col2.metric("Nivel promedio", f"{df['nivel'].mean():.2f}")
            col3.metric("Índice de calidad", f"{indice_calidad} / 100")
            col4.metric("Outliers detectados", n_outliers)

            # Serie
            st.subheader("Serie de nivel")
            st.line_chart(df.set_index("fecha")["nivel"])

            # Mapa
            st.subheader("Ubicación de la estación")
            if not coords_reales:
                st.caption("⚠️ La API no retornó coordenadas específicas para esta estación. Se muestra el punto predeterminado (Pascual Bravo).")
            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=12)

            # Tabla y descarga corregida
            with st.expander("Ver datos crudos"):
                st.dataframe(df, use_container_width=True)

            # Formato CSV adaptado a Excel (punto y coma como separador + codificación utf-8-sig)
            csv_data = df.to_csv(index=False, sep=";", decimal=".").encode("utf-8-sig")
            st.download_button(
                "⬇️ Descargar CSV (Formato Excel)",
                csv_data,
                file_name=f"nivel_estacion_{codigo_estacion}.csv",
                mime="text/csv"
            )
else:
    st.info("Ajusta los parámetros en el sidebar y presiona **Consultar**.")
