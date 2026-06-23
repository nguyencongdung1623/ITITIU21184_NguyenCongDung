import time
import json
import paho.mqtt.client as mqtt
import serial
import board
import busio
from adafruit_ens160 import ENS160
from gpiozero import DigitalInputDevice, LED, OutputDevice

# GPIO
GAS_PIN     = 16
FLAME_PIN   = 17
BUZZER_PIN  = 18
PIR_PIN     = 27
LED_PIN     = 22
FAN_PIN     = 23
PMS_PORT    = "/dev/serial0"
AQI_THRES   = 1
PM25_THRES  = 20
TVOC_THRES  = 400   
ECO2_THRES  = 1000

# MQTT ThingsBoard
MQTT_SERVER = "demo.thingsboard.io"
MQTT_PORT   = 1883
TOKEN       = "klk3AZg0vQdXkUDCyYdj"

# Outputs setup
buzzer = OutputDevice(BUZZER_PIN, initial_value=False)
led    = LED(LED_PIN, initial_value=False)
fan    = OutputDevice(FAN_PIN, initial_value=False)

# Inputs setup
gas_sensor   = DigitalInputDevice(GAS_PIN, pull_up=None, active_state=False)
flame_sensor = DigitalInputDevice(FLAME_PIN, pull_up=None, active_state=False)
pir_sensor   = DigitalInputDevice(PIR_PIN, pull_up=None, active_state=True)

# Commu hardware
try:
    pms = serial.Serial(PMS_PORT, 9600, timeout=1)
except Exception as e:
    print(f"Warning: Cannot open Serial Port {PMS_PORT}. Error: {e}")
    pms = None

try:
    i2c = busio.I2C(board.SCL, board.SDA)
    ens = ENS160(i2c)
except Exception as e:
    print(f"Warning: Cannot initialize I2C for ENS160. Error: {e}")
    ens = None

# MQTT Client
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(TOKEN)
try:
    client.connect(MQTT_SERVER, MQTT_PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"Warning: MQTT Connection failed: {e}")

pm25 = 0

def read_pms7003():
    global pm25
    if pms is None: return False
    try:
        if pms.in_waiting >= 32:
            start_byte = pms.read(1)
            if start_byte == b'\x42':
                data = pms.read(31) 
                if len(data) == 31 and data[0] == 0x4d: 
                    full_data = b'\x42' + data
                    checksum = sum(full_data[:30])
                    res_checksum = (full_data[30] << 8) | full_data[31]
                    
                    if checksum == res_checksum:
                        pm25 = (full_data[10] << 8) | full_data[11]
                        return True
        elif pms.in_waiting > 100: 
            pms.reset_input_buffer()
    except Exception as e:
        print(f"PMS Error: {e}")
    return False

def get_air_status(aqi, tvoc, eco2, pm25):
    if aqi >= 5 or tvoc > 2200 or eco2 > 1800 or pm25 > 150:
        return "Hazardous!"
    elif aqi == 4 or tvoc > 660 or eco2 > 1500 or pm25 > 55:
        return "Poor"
    elif aqi == 3 or tvoc > 220 or eco2 > 800 or pm25 > 35:
        return "Moderate"
    elif aqi == 2 or tvoc > 65 or eco2 > 600 or pm25 > 12:
        return "Good"
    else:
        return "Excellent"

print("System Running...")

try:
    while True:
        gas_detected   = gas_sensor.value
        flame_detected = flame_sensor.value
        motion         = pir_sensor.value

        read_pms7003()
        
        try:
            if ens:
                aqi  = int(ens.AQI)
                tvoc = int(ens.TVOC)
                eco2 = int(ens.eCO2)
            else:
                aqi, tvoc, eco2 = 1, 450, 400
        except:
            aqi, tvoc, eco2 = 1, 450, 400

        alert = (gas_detected == 1 or flame_detected == 1)
        fire_msg = "Safe"
        
        if alert:
            buzzer.on()
            time.sleep(0.1)
            buzzer.off()
            time.sleep(0.1)
            
            if gas_detected == 1 and flame_detected == 1:
                fire_msg = "Gas and Fire Detected!"
            elif gas_detected == 1:
                fire_msg = "Gas Detected!"
            else:
                fire_msg = "Fire Detected!"
        else:
            buzzer.off() 
            
        air_msg = get_air_status(aqi, tvoc, eco2, pm25)    

        if motion == 1: 
            led.on() 
        else: 
            led.off()

        fan_on = (aqi >= AQI_THRES or pm25 >= PM25_THRES or tvoc >= TVOC_THRES or eco2 >= ECO2_THRES)
        if fan_on: 
            fan.on()
        else: 
            fan.off()

        payload = {
            "fire_status": alert,
            "fire_message": fire_msg,
            "air_message": air_msg,
            "gas": int(gas_detected),
            "flame": int(flame_detected),
            "aqi": int(aqi),
            "tvoc": int(tvoc), 
            "eco2": int(eco2),            
            "pm25": int(pm25),
            "fan": fan_on
        }

        try:
            client.publish("v1/devices/me/telemetry", json.dumps(payload))
        except Exception as e:
            print(f"MQTT Publish Error: {e}")
            
        gas_status = "GAS!" if gas_detected == 1 else "Safe"
        flame_status = "FIRE!" if flame_detected == 1 else "Safe"
        motion_status = "True" if motion == 1 else "None"
        fan_status = "ON" if fan_on else "OFF"

        print(f"Fire: {flame_status:<6} | "
              f"Gas: {gas_status:<6} | "
              f"Motion: {motion_status:<4} | "
              f"Air: {air_msg:<10} | "
              f"Fan: {fan_status}")

        if alert:
            time.sleep(0.5)
        else:
            time.sleep(1)

except KeyboardInterrupt:
    print("Stop Running...")
    if client.is_connected():
        client.disconnect()
