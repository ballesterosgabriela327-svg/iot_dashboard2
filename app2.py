import time
from datetime import datetime, timedelta, timezone
 
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from influxdb_client import InfluxDBClient
 
# ---------------------------
# CONFIG
# ---------------------------
st.set_page_config(page_title="IoT Dashboard", layout="wide")
 
URL = "https://us-east-1-1.aws.cloud2.influxdata.com"
ORG = "miguelcmo"
BUCKET = "iot_telemetry_data"
 
# El token se lee de los secrets de Streamlit (Settings → Secrets: INFLUX_TOKEN = "...")
try:
    TOKEN = st.secrets["INFLUX_TOKEN"]
except Exception:
    TOKEN = st.sidebar.text_input("Token de InfluxDB", type="password")
 
COLORS = {"temperature": "#EF553B", "humidity": "#1F77B4"}
FILL = {"temperature": "rgba(239,85,59,0.2)", "humidity": "rgba(31,119,180,0.2)"}
LABELS = {"temperature": "Temperatura (°C)", "humidity": "Humedad (%)"}
 
# ---------------------------
# SIDEBAR: CONTROLES
# ---------------------------
st.sidebar.header("⚙️ Configuración")
 
modo_rango = st.sidebar.radio("Tipo de rango", ["Relativo", "Personalizado"], horizontal=True)
if modo_rango == "Relativo":
    rango = st.sidebar.selectbox(
        "Rango de tiempo",
        ["-1h", "-6h", "-12h", "-24h", "-3d", "-7d"],
        index=3,
    )
    start, stop = rango, "now()"
else:
    hoy = datetime.now().date()
    fechas = st.sidebar.date_input("Fechas", (hoy - timedelta(days=1), hoy))
    if isinstance(fechas, tuple) and len(fechas) == 2:
        f_ini = datetime.combine(fechas[0], datetime.min.time()) + timedelta(hours=5)  # Bogotá → UTC
        f_fin = datetime.combine(fechas[1], datetime.max.time()) + timedelta(hours=5)
        start = f_ini.strftime("%Y-%m-%dT%H:%M:%SZ")
        stop = f_fin.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        st.sidebar.info("Selecciona fecha inicial y final.")
        st.stop()
 
variables = st.sidebar.multiselect(
    "Variables a mostrar",
    ["temperature", "humidity"],
    default=["temperature", "humidity"],
    format_func=lambda v: LABELS[v],
)
 
st.sidebar.subheader("📐 Procesamiento")
intervalo = st.sidebar.select_slider(
    "Intervalo de promedio", ["1min", "5min", "10min", "15min", "30min", "1h"], value="10min"
)
ventana_movil = st.sidebar.slider("Ventana de media móvil (muestras)", 1, 50, 10)
 
st.sidebar.subheader("🚨 Umbrales de alerta")
t_min, t_max = st.sidebar.slider("Temperatura aceptable (°C)", 0.0, 50.0, (18.0, 28.0), 0.5)
h_min, h_max = st.sidebar.slider("Humedad aceptable (%)", 0.0, 100.0, (40.0, 70.0), 1.0)
 
st.sidebar.subheader("🔄 Actualización")
refresh = st.sidebar.slider("Auto-refresh (segundos, 0 = apagado)", 0, 60, 0)
if st.sidebar.button("Recargar datos ahora"):
    st.cache_data.clear()
 
# ---------------------------
# DATOS
# ---------------------------
@st.cache_data(ttl=10)
def load_data(start, stop, token):
    with InfluxDBClient(url=URL, token=token, org=ORG) as client:
        query = f'''
        from(bucket: "{BUCKET}")
          |> range(start: {start}, stop: {stop})
          |> filter(fn: (r) => r["_field"] == "temperature" or r["_field"] == "humidity")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "temperature", "humidity"])
        '''
        result = client.query_api().query_data_frame(query)
 
    df = pd.concat(result) if isinstance(result, list) else result
    if df.empty:
        return df
 
    df["_time"] = pd.to_datetime(df["_time"]).dt.tz_convert("America/Bogota")
    for c in ["temperature", "humidity"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["temperature", "humidity"]).sort_values("_time").reset_index(drop=True)
 
 
def punto_rocio(t, h):
    """Fórmula de Magnus (a=17.27, b=237.7)."""
    a, b = 17.27, 237.7
    alpha = (a * t) / (b + t) + np.log(h / 100.0)
    return (b * alpha) / (a - alpha)
 
 
# ---------------------------
# ENCABEZADO
# ---------------------------
st.title("🌡️ IoT Telemetry Dashboard")
st.markdown("Monitoreo de temperatura y humedad — datos desde InfluxDB Cloud")
 
if not TOKEN:
    st.warning("Ingresa el token de InfluxDB para cargar los datos.")
    st.stop()
 
if not variables:
    st.warning("Selecciona al menos una variable en la barra lateral.")
    st.stop()
 
try:
    df = load_data(start, stop, TOKEN)
except Exception as e:
    st.error(f"Error consultando InfluxDB: {e}")
    st.stop()
 
if df.empty:
    st.warning("No hay datos disponibles en este rango de tiempo.")
    st.stop()
 
df["dew_point"] = punto_rocio(df["temperature"], df["humidity"])
ultimo = df.iloc[-1]
 
# ---------------------------
# MÉTRICAS CON DELTA
# ---------------------------
hace_1h = df[df["_time"] <= ultimo["_time"] - pd.Timedelta(hours=1)]
ref = hace_1h.iloc[-1] if not hace_1h.empty else df.iloc[0]
 
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🌡️ Temp actual", f"{ultimo['temperature']:.2f} °C",
          f"{ultimo['temperature'] - ref['temperature']:+.2f} °C vs 1 h")
c2.metric("💧 Humedad actual", f"{ultimo['humidity']:.2f} %",
          f"{ultimo['humidity'] - ref['humidity']:+.2f} % vs 1 h")
c3.metric("📊 Temp promedio", f"{df['temperature'].mean():.2f} °C")
c4.metric("📊 Humedad promedio", f"{df['humidity'].mean():.2f} %")
c5.metric("🌫️ Punto de rocío", f"{ultimo['dew_point']:.2f} °C")
 
st.caption(f"Última lectura: {ultimo['_time']:%Y-%m-%d %H:%M:%S} · {len(df):,} registros")
 
# ---------------------------
# ALERTAS
# ---------------------------
fuera_t = df[(df["temperature"] < t_min) | (df["temperature"] > t_max)]
fuera_h = df[(df["humidity"] < h_min) | (df["humidity"] > h_max)]
 
a1, a2 = st.columns(2)
if t_min <= ultimo["temperature"] <= t_max:
    a1.success(f"Temperatura dentro del rango ({t_min}–{t_max} °C)")
else:
    a1.error(f"Temperatura fuera del rango ({t_min}–{t_max} °C)")
if h_min <= ultimo["humidity"] <= h_max:
    a2.success(f"Humedad dentro del rango ({h_min}–{h_max} %)")
else:
    a2.error(f"Humedad fuera del rango ({h_min}–{h_max} %)")
 
# ---------------------------
# PESTAÑAS
# ---------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📈 Series de tiempo", "🎛️ Indicadores", "📊 Distribución", "🔗 Correlación", "📋 Datos"]
)
 
# --- TAB 1: Series de tiempo ---
with tab1:
    mostrar_movil = st.checkbox("Superponer media móvil", value=True)
 
    fig = make_subplots(
        rows=len(variables), cols=1, shared_xaxes=True, vertical_spacing=0.06,
        subplot_titles=[LABELS[v] for v in variables],
    )
    limites = {"temperature": (t_min, t_max), "humidity": (h_min, h_max)}
 
    for i, v in enumerate(variables, start=1):
        fig.add_trace(go.Scatter(x=df["_time"], y=df[v], name=LABELS[v], mode="lines",
                                 line=dict(color=COLORS[v], width=1), opacity=0.6), row=i, col=1)
        if mostrar_movil:
            fig.add_trace(go.Scatter(x=df["_time"], y=df[v].rolling(ventana_movil).mean(),
                                     name=f"{LABELS[v]} (media móvil)", mode="lines",
                                     line=dict(color=COLORS[v], width=2.5)), row=i, col=1)
        lo, hi = limites[v]
        fig.add_hrect(y0=lo, y1=hi, fillcolor="green", opacity=0.08, line_width=0, row=i, col=1)
 
    fig.update_layout(height=320 * len(variables), hovermode="x unified",
                      legend=dict(orientation="h", y=1.08))
    fig.update_xaxes(rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
 
    st.subheader(f"⏱️ Promedio cada {intervalo}")
    df_res = (df.set_index("_time")[variables].resample(intervalo)
                .agg(["mean", "min", "max"]).dropna())
 
    fig2 = go.Figure()
    for v in variables:
        fig2.add_trace(go.Scatter(x=df_res.index, y=df_res[(v, "max")], mode="lines",
                                  line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig2.add_trace(go.Scatter(x=df_res.index, y=df_res[(v, "min")], mode="lines",
                                  line=dict(width=0), fill="tonexty",
                                  fillcolor=FILL[v], name=f"{LABELS[v]} (mín–máx)"))
        fig2.add_trace(go.Scatter(x=df_res.index, y=df_res[(v, "mean")], mode="lines",
                                  line=dict(color=COLORS[v], width=2), name=f"{LABELS[v]} (promedio)"))
    fig2.update_layout(height=400, hovermode="x unified")
    st.plotly_chart(fig2, use_container_width=True)
 
# --- TAB 2: Indicadores tipo gauge ---
with tab2:
    g1, g2 = st.columns(2)
 
    def gauge(valor, titulo, rango, lo, hi, color, sufijo):
        return go.Figure(go.Indicator(
            mode="gauge+number+delta", value=valor,
            delta={"reference": float((lo + hi) / 2)},
            number={"suffix": sufijo},
            title={"text": titulo},
            gauge={"axis": {"range": rango}, "bar": {"color": color},
                   "steps": [{"range": [rango[0], lo], "color": "rgba(239,85,59,0.25)"},
                             {"range": [lo, hi], "color": "rgba(0,180,0,0.25)"},
                             {"range": [hi, rango[1]], "color": "rgba(239,85,59,0.25)"}]},
        )).update_layout(height=320)
 
    g1.plotly_chart(gauge(ultimo["temperature"], "Temperatura", [0, 50], t_min, t_max,
                          COLORS["temperature"], " °C"), use_container_width=True)
    g2.plotly_chart(gauge(ultimo["humidity"], "Humedad", [0, 100], h_min, h_max,
                          COLORS["humidity"], " %"), use_container_width=True)
 
    st.markdown("**Porcentaje del tiempo fuera de rango**")
    p1, p2 = st.columns(2)
    p1.metric("Temperatura", f"{100 * len(fuera_t) / len(df):.1f} %", f"{len(fuera_t)} lecturas",
              delta_color="off")
    p2.metric("Humedad", f"{100 * len(fuera_h) / len(df):.1f} %", f"{len(fuera_h)} lecturas",
              delta_color="off")
 
    st.markdown("**Promedio por hora del día**")
    por_hora = df.assign(hora=df["_time"].dt.hour).groupby("hora")[variables].mean().reset_index()
    fig_h = px.bar(por_hora.melt(id_vars="hora"), x="hora", y="value", color="variable",
                   barmode="group", color_discrete_map=COLORS,
                   labels={"hora": "Hora del día", "value": "Valor"})
    st.plotly_chart(fig_h, use_container_width=True)
 
# --- TAB 3: Distribución ---
with tab3:
    bins = st.slider("Número de intervalos del histograma", 10, 100, 40)
    cols = st.columns(len(variables))
    for col, v in zip(cols, variables):
        fig_d = px.histogram(df, x=v, nbins=bins, marginal="box",
                             color_discrete_sequence=[COLORS[v]], labels={v: LABELS[v]})
        col.plotly_chart(fig_d, use_container_width=True)
 
    st.markdown("**Estadística descriptiva**")
    st.dataframe(df[variables + ["dew_point"]].describe().T.style.format("{:.2f}"),
                 use_container_width=True)
 
# --- TAB 4: Correlación ---
with tab4:
    color_por = st.radio("Colorear puntos por", ["Hora del día", "Ninguno"], horizontal=True)
    color_arg = df["_time"].dt.hour if color_por == "Hora del día" else None
    fig_c = px.scatter(df, x="temperature", y="humidity", color=color_arg,
                       opacity=0.6,
                       labels={"temperature": LABELS["temperature"], "humidity": LABELS["humidity"],
                               "color": "Hora"})
    st.plotly_chart(fig_c, use_container_width=True)
    r = df["temperature"].corr(df["humidity"])
    st.metric("Coeficiente de correlación de Pearson (r)", f"{r:.3f}")
 
# --- TAB 5: Datos crudos y descarga ---
with tab5:
    n = st.number_input("Filas a mostrar (últimas)", 10, len(df), min(50, len(df)), step=10)
    solo_alertas = st.checkbox("Mostrar solo lecturas fuera de rango")
    tabla = pd.concat([fuera_t, fuera_h]).drop_duplicates().sort_values("_time") if solo_alertas else df
    st.dataframe(tabla.tail(int(n)), use_container_width=True)
 
    st.download_button("⬇️ Descargar CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name="iot_telemetry.csv", mime="text/csv")
 
# ---------------------------
# AUTO REFRESH
# ---------------------------
if refresh > 0:
    time.sleep(refresh)
    st.cache_data.clear()
    st.rerun()
 
