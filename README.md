<div align="center">

# 📦 Vision Artificial — Lector de Códigos de Barras en Tiempo Real

**Sistema de visión artificial para detección y gestión de productos en entornos logísticos**

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.x-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)](https://opencv.org/)
[![Flask](https://img.shields.io/badge/Flask-Web%20Server-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![MQTT](https://img.shields.io/badge/MQTT-IoT%20Protocol-660066?style=for-the-badge&logo=eclipsemosquitto&logoColor=white)](https://mqtt.org/)

*Desarrollado en el marco de una práctica profesional en Andreani Grupo Logístico*

</div>

---

## 📋 Descripción

Sistema de lectura de códigos de barras en tiempo real mediante cámara web, con arquitectura multi-hilo, dashboard web en vivo y publicación de eventos vía MQTT. Integra detección óptica con OpenCV/pyzbar y reconocimiento de texto por OCR como fallback para códigos postales y etiquetas dañadas.

---

## ✨ Características principales

| Característica | Detalle |
|---|---|
| 🎯 **Detección en tiempo real** | Pipeline multi-hilo: captura → procesamiento → visualización |
| 📷 **Multi-formato** | EAN-13, EAN-8, QR y otros formatos vía pyzbar |
| 🔍 **Fallback OCR** | EasyOCR en español/inglés para códigos no reconocidos ópticamente |
| 🌐 **Dashboard web** | Transmisión de frames y detecciones vía Flask + Socket.IO |
| 📡 **MQTT** | Publicación de eventos en tiempo real a broker configurable |
| 💾 **Logging CSV** | Registro timestamped de cada detección con datos del producto |
| 📊 **Base de datos Excel** | Validación de productos contra catálogo `.xlsx` con pandas |
| 📈 **Métricas live** | FPS, nitidez de imagen (varianza Laplaciana), tasa de detección |

---

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                  barcode_camara_tiempo_real.py           │
│                                                          │
│  Thread 1: Captura ──► Thread 2: Detección ──► Thread 3: Display
│              │                  │                        │
│           OpenCV             pyzbar                   Métricas
│                             EasyOCR                   OpenCV UI
│                                │                        │
│                    ┌───────────┴──────────┐             │
│                    ▼                      ▼             │
│              MQTT Broker          Flask Server ◄────────┘
│                                   (app.py :5000)
│                                        │
│                                   Browser Dashboard
└─────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tecnologías utilizadas

- **OpenCV** — captura de video y preprocesamiento de imagen (CLAHE, sharpening, umbralización adaptativa)
- **pyzbar** — decodificación de códigos de barras y QR
- **EasyOCR** — reconocimiento óptico de caracteres como fallback
- **Flask + Flask-SocketIO** — servidor web y transmisión en tiempo real al navegador
- **paho-mqtt** — publicación de eventos a broker MQTT
- **pandas** — manejo de base de datos en Excel
- **Threading** — arquitectura concurrente de 3 hilos

---

## 🚀 Instalación y uso

### Requisitos

```bash
pip install opencv-python pyzbar easyocr flask flask-socketio pandas paho-mqtt openpyxl requests
```

### Configuración

Copiar `.env.example` a `.env` y configurar:

```env
MQTT_BROKER=<ip_del_broker>
MQTT_PORT=1883
MQTT_TOPIC=andreani/detecciones
```

### Ejecución

```bash
# 1. Iniciar primero el servidor web
python app.py

# 2. En otra terminal, iniciar el lector de cámara
python barcode_camara_tiempo_real.py
```

Abrir el navegador en `http://localhost:5000` para ver el dashboard en tiempo real.

---

## 📁 Estructura del proyecto

```
Vision-Artificial-Andreani/
├── app.py                          # Servidor Flask + Socket.IO
├── barcode_camara_tiempo_real.py   # Lector de cámara multi-hilo
├── dashboard.html                  # Interfaz web en tiempo real
├── productos_db.xlsx               # Base de datos de productos
├── .env.example                    # Plantilla de configuración
└── docs/
    ├── Informe_TP_N2.pdf
    └── Tp_2_Sistemas_Mecatronicos_II.pdf
```

---

## 🎓 Contexto académico

Proyecto desarrollado como **Trabajo Práctico N°2** de la materia *Sistemas Mecatrónicos II* en la [Universidad Nacional de Entre Ríos (UNER)](https://www.uner.edu.ar/), en el marco de una práctica en **Andreani Grupo Logístico**.

---

<div align="center">

**Autor:** [Tadeo Mendelevich](https://github.com/tadeomendelevich)  
*Ingeniería en Sistemas de Información — UNER*

</div>
