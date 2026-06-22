# Gateway: Raspberry Pi 3 Model B+ BLE-to-HTTP Bridge

## What it does

Listens for BLE advertisements from SheepDog occupancy sensors (XIAO nRF52840), detects state changes, and POSTs JSON to the iPad running Bird Dog on the lot WiFi.

## Setup

```bash
ssh <pi-user>@<pi-hostname>.local

sudo apt update && sudo apt install -y python3-pip
pip3 install -r requirements.txt --break-system-packages
```

## Run

```bash
python3 gateway.py --target http://<iPad-IP>:8080/api/occupancy
```

## JSON payload format

```json
{
  "sensorId": "occ-001",
  "type": "occupancy",
  "payload": "occupied",
  "rssi": -42,
  "timestamp": "2026-06-09T14:30:00+00:00"
}
```

## Run as a service (optional, for demo day)

```bash
sudo tee /etc/systemd/system/sheepdog-gw.service << 'EOF'
[Unit]
Description=SheepDog BLE Gateway
After=network.target bluetooth.target

[Service]
ExecStart=/usr/bin/python3 /home/<pi-user>/gateway.py --target http://<iPad-IP>:8080/api/occupancy
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable sheepdog-gw
sudo systemctl start sheepdog-gw
```

## Networking

The Pi connects to WiFi networks in priority order. Configure networks for your deployment:
- Personal hotspot — for development/SSH
- Campus WiFi — for lot deployment
- Home/lab network — for bench testing

Add networks: `sudo nmcli device wifi connect "SSID" password 'password'`

SSH: `ssh <pi-user>@<pi-hostname>.local`
