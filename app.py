"""
Servidor web - recibe frames y detecciones desde barcode_camara_tiempo_real.py
y los reenvía al navegador via Socket.IO.
Correr primero este script, luego barcode_camara_tiempo_real.py.
"""
from flask import Flask, request
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

@app.route('/')
def index():
    with open('dashboard.html', encoding='utf-8') as f:
        return f.read()

@app.route('/push_frame', methods=['POST'])
def push_frame():
    socketio.emit('frame', request.get_json())
    return '', 204

@app.route('/push_deteccion', methods=['POST'])
def push_deteccion():
    socketio.emit('deteccion', request.get_json())
    return '', 204

if __name__ == '__main__':
    print("[SERVER] http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False,
                 use_reloader=False, allow_unsafe_werkzeug=True)
