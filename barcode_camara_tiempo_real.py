"""
Lector de codigos de barra en tiempo real - maximo FPS.
Pipeline: captura -> preprocesamiento -> deteccion -> postprocesamiento
  - Validacion contra base de datos Excel (productos_db.xlsx)
  - Publicacion MQTT de cada deteccion (broker publico de prueba)
  - Metricas: FPS, nitidez, total detectados, tasa en DB / desconocidos
  - CSV de log con timestamp
Teclas: 'q' salir | 's' guardar frame
"""
import cv2
import numpy as np
import threading
import time
import os, sys
import csv
import json
from datetime import datetime

import pandas as pd
import paho.mqtt.client as mqtt

sys.stderr = open(os.devnull, 'w')
from pyzbar import pyzbar
sys.stderr = sys.__stderr__

# ══════════════════════════════════════════════════════════════════════════════
# BASE DE DATOS (Excel)
# ══════════════════════════════════════════════════════════════════════════════
DB_FILE = "productos_db.xlsx"

def cargar_db(path):
    try:
        df = pd.read_excel(path, dtype={'codigo_barras': str})
        db = {str(row['codigo_barras']).strip(): row.to_dict()
              for _, row in df.iterrows()}
        print(f"[DB] {len(db)} productos cargados desde {path}")
        return db
    except Exception as e:
        print(f"[DB] Error al cargar {path}: {e}")
        return {}

producto_db = cargar_db(DB_FILE)

def buscar_en_db(codigo):
    """Retorna el dict del producto o None si no esta en la DB."""
    return producto_db.get(str(codigo).strip())

# ══════════════════════════════════════════════════════════════════════════════
# MQTT
# ══════════════════════════════════════════════════════════════════════════════
MQTT_BROKER   = os.getenv("MQTT_BROKER",   "")
MQTT_PORT     = 8883
MQTT_USER     = os.getenv("MQTT_USER",     "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TOPIC    = "uner/tp2/barcode"
MQTT_TIMEOUT  = 5

mqtt_conectado = False
mqtt_client    = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id="uner_tp2_barcode")
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_client.tls_set()  # TLS por defecto (puerto 8883)

def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_conectado
    if reason_code == 0:
        mqtt_conectado = True
        print(f"[MQTT] Conectado a {MQTT_BROKER} | topic: {MQTT_TOPIC}")
    else:
        print(f"[MQTT] Conexion rechazada (codigo {reason_code})")

def on_disconnect(client, userdata, flags, reason_code, properties):
    global mqtt_conectado
    mqtt_conectado = False
    print("[MQTT] Desconectado")

mqtt_client.on_connect    = on_connect
mqtt_client.on_disconnect = on_disconnect

def conectar_mqtt():
    try:
        mqtt_client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
        time.sleep(MQTT_TIMEOUT)
        if not mqtt_conectado:
            print("[MQTT] No se pudo conectar al broker (sin internet?). Continuando sin MQTT.")
    except Exception as e:
        print(f"[MQTT] Error de conexion: {e}. Continuando sin MQTT.")

threading.Thread(target=conectar_mqtt, daemon=True).start()

def publicar_mqtt(codigo, tipo, producto):
    if not mqtt_conectado:
        return
    payload = {
        "timestamp": datetime.now().isoformat(),
        "codigo":    codigo,
        "tipo":      tipo,
        "en_db":     producto is not None,
        "producto":  producto.get("producto",  "DESCONOCIDO") if producto else "DESCONOCIDO",
        "categoria": producto.get("categoria", "")            if producto else "",
    }
    try:
        mqtt_client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# CSV LOG
# ══════════════════════════════════════════════════════════════════════════════
CSV_FILE = "barcodes_detectados.csv"
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(
            ["timestamp", "tipo", "codigo", "en_db", "producto", "categoria", "mqtt_ok"])
print(f"[LOG] Guardando en: {CSV_FILE}")

historial_pantalla = []
ultimos_guardados  = set()
lock_csv           = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# METRICAS
# ══════════════════════════════════════════════════════════════════════════════
metricas = {
    "total":       0,   # total de escaneos unicos guardados
    "en_db":       0,   # cuantos estaban en la base de datos
    "desconocidos":0,   # cuantos NO estaban
}
lock_metricas = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# GUARDADO (anti-duplicado 2s)
# ══════════════════════════════════════════════════════════════════════════════
def normalizar_tipo(tipo, codigo):
    if codigo.isdigit():
        if len(codigo) == 13: return "EAN-13"
        if len(codigo) ==  8: return "EAN-8"
    return tipo

def registrar_deteccion(tipo, codigo):
    tipo  = normalizar_tipo(tipo, codigo)
    clave = (tipo, codigo)
    with lock_csv:
        if clave in ultimos_guardados:
            return
        ultimos_guardados.add(clave)

    producto  = buscar_en_db(codigo)
    en_db     = producto is not None
    publicar_mqtt(codigo, tipo, producto)

    ts           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nombre_prod  = producto.get("producto",  "DESCONOCIDO") if producto else "DESCONOCIDO"
    categoria    = producto.get("categoria", "")            if producto else ""

    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(
            [ts, tipo, codigo, en_db, nombre_prod, categoria, mqtt_conectado])

    with lock_metricas:
        metricas["total"] += 1
        if en_db:
            metricas["en_db"] += 1
        else:
            metricas["desconocidos"] += 1

    linea_hist = {
        "hora":     ts[-8:],
        "codigo":   codigo,
        "tipo":     tipo,
        "en_db":    en_db,
        "producto": nombre_prod,
    }
    with lock_csv:
        historial_pantalla.append(linea_hist)
        if len(historial_pantalla) > 7:
            historial_pantalla.pop(0)

    estado = "EN DB" if en_db else "DESCONOCIDO"
    print(f"[SCAN] {tipo}: {codigo} -> {estado} | {nombre_prod}")

    def limpiar():
        time.sleep(2)
        with lock_csv:
            ultimos_guardados.discard(clave)
    threading.Thread(target=limpiar, daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
# CAMARA
# ══════════════════════════════════════════════════════════════════════════════
def detectar_camara():
    for idx in range(4):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                print(f"[CAM] Indice {idx}")
                return cap, idx
            cap.release()
    raise RuntimeError("No se encontro camara")

cap, cam_idx = detectar_camara()
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)
cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)

# ══════════════════════════════════════════════════════════════════════════════
# ESTADO COMPARTIDO
# ══════════════════════════════════════════════════════════════════════════════
frame_actual  = None
frame_display = None
resultado     = []
lock_cap      = threading.Lock()
lock_res      = threading.Lock()
corriendo     = True

# ══════════════════════════════════════════════════════════════════════════════
# HILO 1 — CAPTURA
# ══════════════════════════════════════════════════════════════════════════════
def hilo_captura():
    global frame_actual, frame_display, corriendo
    while corriendo:
        ret, f = cap.read()
        if not ret:
            continue
        with lock_cap:
            frame_actual  = f
            frame_display = f

threading.Thread(target=hilo_captura, daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
# HILO 2 — DECODE
# ══════════════════════════════════════════════════════════════════════════════
clahe        = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
kernel_sharp = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])

def hilo_decode():
    global frame_actual, resultado, corriendo
    ultimo_procesado = None
    while corriendo:
        with lock_cap:
            frame = frame_actual
        if frame is None or frame is ultimo_procesado:
            time.sleep(0.002)
            continue
        ultimo_procesado = frame

        gris     = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mejorada = clahe.apply(gris)
        alto, ancho = gris.shape
        encontrados = {}

        def intentar(img):
            for c in pyzbar.decode(img):
                datos = c.data.decode('utf-8', errors='replace')
                clave = (datos, c.type)
                if clave not in encontrados:
                    encontrados[clave] = c

        intentar(mejorada)
        if not encontrados:
            intentar(cv2.filter2D(mejorada, -1, kernel_sharp))
        if not encontrados:
            cx, cy = ancho // 2, alto // 2
            r    = min(cx, cy, 150)
            zoom = cv2.resize(gris[cy-r:cy+r, cx-r:cx+r],
                              None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            intentar(clahe.apply(zoom))
        if not encontrados:
            intentar(cv2.adaptiveThreshold(
                mejorada, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4))

        with lock_res:
            if encontrados:
                resultado = list(encontrados.values())
                for c in resultado:
                    registrar_deteccion(
                        c.type, c.data.decode('utf-8', errors='replace'))

threading.Thread(target=hilo_decode, daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS DE DIBUJO
# ══════════════════════════════════════════════════════════════════════════════
def txt(img, texto, x, y, escala=0.6, color=(220, 220, 220), grosor=1):
    cv2.putText(img, str(texto), (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, escala, color, grosor, cv2.LINE_AA)

def barra_porcentaje(panel, x, y, ancho, alto, pct, color_lleno, label=""):
    cv2.rectangle(panel, (x, y), (x + ancho, y + alto), (60, 60, 60), -1)
    lleno = int(ancho * min(pct, 1.0))
    if lleno > 0:
        cv2.rectangle(panel, (x, y), (x + lleno, y + alto), color_lleno, -1)
    cv2.rectangle(panel, (x, y), (x + ancho, y + alto), (90, 90, 90), 1)
    if label:
        txt(panel, label, x + ancho + 5, y + alto - 2, 0.45, (180, 180, 180))

# ══════════════════════════════════════════════════════════════════════════════
# LOOP PRINCIPAL — DISPLAY
# ══════════════════════════════════════════════════════════════════════════════
print("Corriendo. [q]=salir  [s]=guardar frame")

PANEL_W   = 320
fps_t     = time.time()
fps_count = 0
fps_val   = 0.0
frame_num = 0

while True:
    with lock_cap:
        display_frame = frame_display
    if display_frame is None:
        time.sleep(0.005)
        continue

    frame_num += 1
    fps_count += 1
    now = time.time()
    if now - fps_t >= 0.5:
        fps_val   = fps_count / (now - fps_t)
        fps_count = 0
        fps_t     = now

    camara = display_frame.copy()
    h, w   = camara.shape[:2]

    with lock_res:
        res = list(resultado)

    # Rectangulo guia en camara
    cv2.rectangle(camara, (w//4, h//4), (3*w//4, 3*h//4), (255, 200, 0), 1)

    # Poligono sobre barcode detectado
    for c in res:
        try:
            pts = np.array([[p.x, p.y] for p in c.polygon], dtype=np.int32)
            cv2.polylines(camara, [pts], True, (0, 255, 0), 3)
        except Exception:
            pass

    # ── PANEL DERECHO ─────────────────────────────────────────────────────────
    panel = np.full((h, PANEL_W, 3), (28, 28, 28), dtype=np.uint8)
    cv2.line(panel, (0, 0), (0, h), (70, 70, 70), 2)

    # Titulo
    cv2.rectangle(panel, (0, 0), (PANEL_W, 38), (20, 60, 100), -1)
    txt(panel, "LECTOR BARCODE  -  UNER", 8, 25, 0.55, (255, 255, 255), 1)

    # --- Estado sistema ---
    txt(panel, "SISTEMA", 10, 58, 0.45, (130, 130, 130))
    cv2.line(panel, (10, 63), (PANEL_W-10, 63), (55, 55, 55), 1)

    gris_nit  = cv2.cvtColor(display_frame, cv2.COLOR_BGR2GRAY)
    nit       = cv2.Laplacian(gris_nit, cv2.CV_64F).var()
    color_nit = (0, 220, 0) if nit > 100 else (0, 165, 255) if nit > 40 else (0, 0, 220)
    nit_label = 'OK' if nit > 100 else 'BORROSA' if nit < 40 else 'REGULAR'

    txt(panel, f"FPS:      {fps_val:.1f}",         10, 82,  0.58, (200, 220, 0))
    txt(panel, f"Nitidez:  {nit:.0f} {nit_label}", 10, 102, 0.58, color_nit)

    mqtt_color = (0, 220, 0) if mqtt_conectado else (0, 80, 200)
    mqtt_label = "ONLINE" if mqtt_conectado else "OFFLINE"
    txt(panel, f"MQTT:     {mqtt_label}",           10, 122, 0.58, mqtt_color)
    txt(panel, f"DB:       {len(producto_db)} prod",10, 142, 0.58, (180, 180, 180))

    # --- Ultimo detectado ---
    txt(panel, "ULTIMO DETECTADO", 10, 168, 0.45, (130, 130, 130))
    cv2.line(panel, (10, 173), (PANEL_W-10, 173), (55, 55, 55), 1)

    with lock_csv:
        hist = list(historial_pantalla)

    if hist:
        ultimo = hist[-1]
        en_db  = ultimo["en_db"]
        color_estado = (0, 220, 80) if en_db else (0, 80, 220)
        estado_txt   = "EN BASE DE DATOS" if en_db else "DESCONOCIDO"

        # Badge de estado
        cv2.rectangle(panel, (8, 180), (PANEL_W-8, 200), color_estado, -1)
        txt(panel, estado_txt, PANEL_W//2 - len(estado_txt)*5, 195, 0.55, (255,255,255), 2)

        txt(panel, ultimo["tipo"],   10, 220, 0.55, (100, 200, 255))
        # Codigo (con wrap si es largo)
        cod = ultimo["codigo"]
        partes = [cod[i:i+16] for i in range(0, len(cod), 16)]
        for i, p in enumerate(partes[:2]):
            txt(panel, p, 10, 244 + i*26, 0.85, (0, 255, 100), 2)

        # Nombre del producto
        nombre = ultimo["producto"]
        partes_n = [nombre[i:i+20] for i in range(0, len(nombre), 20)]
        for i, p in enumerate(partes_n[:2]):
            txt(panel, p, 10, 300 + i*20, 0.52, (200, 200, 200))
    else:
        txt(panel, "---", 10, 210, 0.8, (70, 70, 70))

    # --- Metricas ---
    txt(panel, "METRICAS", 10, 348, 0.45, (130, 130, 130))
    cv2.line(panel, (10, 353), (PANEL_W-10, 353), (55, 55, 55), 1)

    with lock_metricas:
        total = metricas["total"]
        en_db_m = metricas["en_db"]
        desc_m  = metricas["desconocidos"]

    pct_db   = en_db_m  / total if total > 0 else 0
    pct_desc = desc_m   / total if total > 0 else 0

    txt(panel, f"Total escaneados:  {total}", 10, 372, 0.55, (220, 220, 220))
    txt(panel, f"En DB:             {en_db_m}", 10, 392, 0.55, (0, 220, 80))
    barra_porcentaje(panel, 10, 398, 180, 8, pct_db, (0, 180, 60), f"{pct_db*100:.0f}%")
    txt(panel, f"Desconocidos:      {desc_m}", 10, 420, 0.55, (0, 100, 220))
    barra_porcentaje(panel, 10, 426, 180, 8, pct_desc, (0, 80, 200), f"{pct_desc*100:.0f}%")

    # --- Historial ---
    txt(panel, "HISTORIAL", 10, 452, 0.45, (130, 130, 130))
    cv2.line(panel, (10, 457), (PANEL_W-10, 457), (55, 55, 55), 1)

    for i, entry in enumerate(reversed(hist)):
        y_base = 475 + i * 34
        if y_base + 28 > h:
            break
        bg = (40, 40, 40) if i % 2 == 0 else (34, 34, 34)
        cv2.rectangle(panel, (5, y_base-14), (PANEL_W-5, y_base+18), bg, -1)
        dot_color = (0, 200, 70) if entry["en_db"] else (0, 70, 200)
        cv2.circle(panel, (14, y_base), 5, dot_color, -1)
        txt(panel, entry["hora"],   22, y_base,    0.42, (110, 110, 110))
        cod_corto = entry["codigo"][:18] + ("…" if len(entry["codigo"]) > 18 else "")
        txt(panel, cod_corto,       22, y_base+16, 0.50, (180, 255, 180) if entry["en_db"] else (180, 180, 255))

    # Linea inferior
    cv2.line(panel, (10, h-28), (PANEL_W-10, h-28), (55, 55, 55), 1)
    txt(panel, f"CSV: {CSV_FILE}", 8, h-12, 0.4, (100, 100, 100))

    ventana = np.hstack([camara, panel])
    cv2.imshow(f"Barcode Cam {cam_idx} - [q] salir", ventana)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('s'):
        cv2.imwrite(f"frame_{frame_num}.png", display_frame)
        print(f"[GUARDADO] frame_{frame_num}.png  nitidez={nit:.1f}")
        with lock_res:
            resultado = []

corriendo = False
mqtt_client.loop_stop()
cap.release()
cv2.destroyAllWindows()
print(f"\n[FIN] Total escaneados: {metricas['total']} | En DB: {metricas['en_db']} | Desconocidos: {metricas['desconocidos']}")
