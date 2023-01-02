# The Things Stack to ThingsBoard Community connector

Publish uplinks from The Things Stack LoRaWAN Network Server to ThingsBoard Community Edition.

The ThingsBoard integration feature, where you can directly connect to TTS and consume uplinks, is only available for the ThingsBoard Professional Edition. For the ThingsBoard Community Edition we need a connector to convert uplinks to ThingsBoard data structure.

This python script connects with MQTT to The Things Stack applications and publishes uplinks to ThingsBoard HTTP API.

## Setup

Clone this repository and install the requieremnts:

```
# Git clone
git clone

# Install python requirements as user or use a python virtualenv
pip install --user -r requirements.txt
```

## Configuration

Copy the configuration example file `config-example.yaml` to `config.yaml` and open it with your preferred editor.

```yaml
tb_url: "http://127.0.0.1:8080"  # Full URL to the ThingsBoard installation.
tb_secrets_db: "secrets.db"  # Name or path to the SQLite DB file to store ThingsBoard device access keys.

tts_default_mqtt_broker: "eu1.cloud.thethings.network"  # The Things Stack MQTT hostname for all applications.
tts_default_mqtt_port: 8883  # The Things Stack MQTT port. 8883 is for SSL.
tts_reconnect_interval: 5  # Time in seconds to reconnect to The Things Stack MQTT broker after the connection was reset.

# List with The Things Stack applications linked to ThingsBoard device profiles.
tts_applications:
  # Default TTS MQTT broker address will be used.
  - tts_username: "TTS_MQTT_USERNAME"  # TTS application name and tanent: my-app@ttn
    tts_apikey: "TTS_MQTT_PASSWORD"  # TTS application api key for MQTT integration.
    tb_provision_device_key: "PROVISION_DEVICE_KEY"  # ThingsBoard device profile provision key.
    tb_provision_device_secret: "PROVISION_DEVICE_SECRET"  # ThingsBoard device profile provision secret.
  # Set different mqtt broker address.
  - tts_username: "TTS_MQTT_USERNAME"
    tts_apikey: "TTS_MQTT_PASSWORD"
    tts_mqtt_broker: "eu1.cloud.thethings.industries"  # Different MQTT broker for this TTS application, optinal.
    tb_provision_device_key: "PROVISION_DEVICE_KEY"
    tb_provision_device_secret: "PROVISION_DEVICE_SECRET"
```

## Run

Try a quick run by execute the `main.py` script:

```bash
python main.py
```

For production, use a process controll system like systemd or supervisor, etc.

### Systemd service file example

```
[Unit]
Description=The Things Stack ThingsBoard Connector
After=multi-user.target

[Service]
Type=simple
User=<username>
WorkingDirectory=/home/<username>/tts-thingsboard-connector
ExecStart=/usr/bin/python3 /home/<username>/tts-thingsboard-connector/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
