import cv2
import time
import json
import paho.mqtt.client as mqtt
from flask import Flask, render_template, Response, redirect
from threading import Thread
from ultralytics import YOLO
from gpiozero import Servo
from gpiozero.pins.lgpio import LGPIOFactory
import sys

import DetectPlates
import DetectChars
from OpticalCharacterRecognition import check_if_string_in_file, ocr_vietnamese_plate

factory = LGPIOFactory()
servo = Servo(12, pin_factory=factory, min_pulse_width=0.5/1000, max_pulse_width=2.5/1000)

def set_angle(angle):
    val = (angle / 90) - 1
    servo.value = val
    time.sleep(0.5)
    servo.value = None

set_angle(90)

sys.modules['imghdr'] = object()
try:
    import bidi
    from bidi import wrapper
    bidi.get_display = wrapper.get_display
except:
    pass
    
model = YOLO('best.pt')

THINGSBOARD_HOST = "demo.thingsboard.io"
ACCESS_TOKEN = "klk3AZg0vQdXkUDCyYdj"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
client.username_pw_set(ACCESS_TOKEN)
try:
    client.connect(THINGSBOARD_HOST, 1883, 60)
    client.loop_start()
except:
    pass

app = Flask(__name__)
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

def gen_frames():
    last_text = ""
    frame_skip = 2 
    count = 0

    while True:
        while True:
            grabbed = cap.grab()
            if not grabbed:
                break
            ret, frame = cap.retrieve()
            if ret:
                break
                
        if not ret or frame is None: 
            time.sleep(0.01)
            continue

        count += 1
        if count % frame_skip == 0:
            listOfPossiblePlates = DetectPlates.detectPlatesInScene(frame)

            if listOfPossiblePlates:
                listOfPossiblePlates.sort(key=lambda p: len(p.strChars), reverse=True)
                licPlate = listOfPossiblePlates[0] 
                
                if licPlate.imgPlate is not None:
                    resized_plate = cv2.resize(licPlate.imgPlate, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    text = ocr_vietnamese_plate(resized_plate)
                else:
                    text = ""
                
                if text and text != last_text and len(text) >= 7:
                    is_valid = check_if_string_in_file('./Database.txt', text)
                    status_str = "Registered" if is_valid else "Not Registered"
                    
                    if is_valid:
                        print(f"Plate is Registered: {text} -> OPEN GATE!")
                        
                        set_angle(180) 
                        
                        telemetry = {
                            "plate": text,
                            "status": status_str,
                            "gate": "Open"
                        }
                        try:
                            client.publish("v1/devices/me/telemetry", json.dumps(telemetry), qos=1)
                        except:
                            pass
                        print(f"ThingsBoard Update (Authorized): {telemetry}")
                        
                        time.sleep(7)
                        set_angle(90)
                        
                    else:
                        print(f"License Plate is not registered: {text}")
                    
                    last_text = text

                if licPlate.rrLocationOfPlateInScene is not None:
                    p2fRectPoints = cv2.boxPoints(licPlate.rrLocationOfPlateInScene)
                    p2fRectPoints = p2fRectPoints.astype(int)
                    for i in range(4):
                        cv2.line(frame, tuple(p2fRectPoints[i]), tuple(p2fRectPoints[(i + 1) % 4]), (0, 0, 255), 2)

        if last_text:
            cv2.putText(frame, f"Plate: {last_text}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        
        time.sleep(0.05)

@app.route('/')
def index():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_flask():
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        cap.release()
        cv2.destroyAllWindows()
