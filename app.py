"""
Servidor Flask + Socket.IO para el dashboard de barcode.
- Sirve dashboard.html en http://localhost:5000
- Stream de camara en /video (MJPEG)
- Emite evento 'deteccion' por Socket.IO cada vez que pyzbar detecta un codigo
"""
import cv2
import numpy as np
import threading
import time
import os, sys
import json
from datetime import datetime

import pandas as pd
import paho.mqtt.client as mqtt
from flask import Flask, Response, render_template_string
from flask_socketio import SocketIO

sys.stderr = open(os.devnull, 'w')
from pyzbar import pyzbar
sys.stderr = sys.__stderr__

# ══════════════════════════════════════════════════════════════════════════════
# FLASK + SOCKET.IO
# ══════════════════════════════════════════════════════════════════════════════
app    = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ══════════════════════════════════════════════════════════════════════════════
# BASE DE DATOS (Excel)
# ══════════════════════════════════════════════════════════════════════════════
DB_FILE = "productos_db.xlsx"

def cargar_db(path):
    try:
        df = pd.read_excel(path, dtype={'codigo_barras': str})
        db = {str(row['codigo_barras']).strip(): row.to_dict()
              for _, row in df.iterrows()}
        print(f"[DB] {len(db)} productos cargados")
        return db
    except Exception as e:
        print(f"[DB] Error: {e}")
        return {}

producto_db = cargar_db(DB_FILE)

def buscar_en_db(codigo):
    return producto_db.get(str(codigo).strip())

# ══════════════════════════════════════════════════════════════════════════════
# MQTT
# ══════════════════════════════════════════════════════════════════════════════
MQTT_BROKER   = os.getenv("MQTT_BROKER",   "")
MQTT_PORT     = 8883
MQTT_USER     = os.getenv("MQTT_USER",     "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TOPIC    = "uner/tp2/barcode"

mqtt_conectado = False
mqtt_client    = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="uner_tp2_flask")
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_client.tls_set()

def on_connect(client, userdata, flags, rc, props):
    global mqtt_conectado
    if rc == 0:
        mqtt_conectado = True
        print(f"[MQTT] Conectado | topic: {MQTT_TOPIC}")

def on_disconnect(client, userdata, flags, rc, props):
    global mqtt_conectado
    mqtt_conectado = False

mqtt_client.on_connect    = on_connect
mqtt_client.on_disconnect = on_disconnect

def conectar_mqtt():
    try:
        mqtt_client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"[MQTT] Error: {e}")

threading.Thread(target=conectar_mqtt, daemon=True).start()

def publicar_mqtt(payload):
    if not mqtt_conectado:
        return
    try:
        mqtt_client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
    except Exception:
        pass

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
frame_actual     = None
frame_con_overlay = None
lock_frame       = threading.Lock()
lock_res         = threading.Lock()
corriendo        = True
ultimos_guardados = set()
lock_dup          = threading.Lock()

metricas = {"total": 0, "en_db": 0, "desconocidos": 0}
lock_met  = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# HILO CAPTURA
# ══════════════════════════════════════════════════════════════════════════════
def hilo_captura():
    global frame_actual, corriendo
    while corriendo:
        ret, f = cap.read()
        if not ret:
            continue
        with lock_frame:
            frame_actual = f

threading.Thread(target=hilo_captura, daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
# HILO DECODE
# ══════════════════════════════════════════════════════════════════════════════
clahe        = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
kernel_sharp = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])

def normalizar_tipo(tipo, codigo):
    if codigo.isdigit():
        if len(codigo) == 13: return "EAN-13"
        if len(codigo) ==  8: return "EAN-8"
    return tipo

def registrar(tipo, codigo):
    tipo  = normalizar_tipo(tipo, codigo)
    clave = (tipo, codigo)
    with lock_dup:
        if clave in ultimos_guardados:
            return
        ultimos_guardados.add(clave)

    producto = buscar_en_db(codigo)
    en_db    = producto is not None
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "timestamp": ts,
        "codigo":    codigo,
        "tipo":      tipo,
        "en_db":     en_db,
        "producto":  producto.get("producto",  "DESCONOCIDO") if producto else "DESCONOCIDO",
        "categoria": producto.get("categoria", "")            if producto else "",
        "piston":    producto.get("piston",    None)          if producto else None,
        "cp":        producto.get("cp",        None)          if producto else None,
        "piston_nombre": producto.get("piston_nombre", "")   if producto else "",
    }

    publicar_mqtt(payload)
    socketio.emit("deteccion", payload)

    with lock_met:
        metricas["total"] += 1
        if en_db: metricas["en_db"] += 1
        else:     metricas["desconocidos"] += 1

    estado = "EN DB" if en_db else "DESCONOCIDO"
    print(f"[SCAN] {tipo}: {codigo} -> {estado} | {payload['producto']}")

    def limpiar():
        time.sleep(2)
        with lock_dup:
            ultimos_guardados.discard(clave)
    threading.Thread(target=limpiar, daemon=True).start()

def hilo_decode():
    global frame_actual, frame_con_overlay, corriendo
    ultimo_procesado = None
    while corriendo:
        with lock_frame:
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

        overlay = frame.copy()
        cv2.rectangle(overlay,
                      (ancho//4, alto//4), (3*ancho//4, 3*alto//4),
                      (255, 200, 0), 1)

        for c in encontrados.values():
            try:
                pts = np.array([[p.x, p.y] for p in c.polygon], dtype=np.int32)
                cv2.polylines(overlay, [pts], True, (0, 255, 0), 3)
            except Exception:
                pass
            registrar(c.type, c.data.decode('utf-8', errors='replace'))

        with lock_frame:
            frame_con_overlay = overlay

threading.Thread(target=hilo_decode, daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
# HILO VIDEO — emite frames por Socket.IO como base64
# ══════════════════════════════════════════════════════════════════════════════
import base64

def hilo_video():
    while corriendo:
        with lock_frame:
            frame = frame_con_overlay if frame_con_overlay is not None else frame_actual
        if frame is None:
            time.sleep(0.033)
            continue
        ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            b64 = base64.b64encode(buf).decode('utf-8')
            socketio.emit('frame', {'img': b64})
        time.sleep(0.05)  # ~20 FPS

threading.Thread(target=hilo_video, daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
# RUTAS FLASK
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/')
def index():
    with open('dashboard.html', encoding='utf-8') as f:
        return f.read()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("[SERVER] http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
