# Met het Oog op Morgen – Podcast Samenvatter

Een kleine webapplicatie die elke ochtend automatisch de nieuwste aflevering
van *Met het Oog op Morgen* transcribeert en een samenvatting per e-mail stuurt.

## Vereisten

- Python 3.10+
- ffmpeg (voor Whisper)
- Een Anthropic API-sleutel
- Een Gmail-account met app-wachtwoord

## Installatie

```bash
# 1. Kopieer de map naar je server en ga erin
cd oog_op_morgen_webapp

# 2. (Optioneel) Virtuele omgeving
python3 -m venv venv
source venv/bin/activate     # Linux/Mac
venv\Scripts\activate        # Windows

# 3. Installeer packages
pip install -r requirements.txt

# 4. Installeer ffmpeg (eenmalig)
# Ubuntu/Debian:
sudo apt install ffmpeg
# Mac (Homebrew):
brew install ffmpeg
# Windows: https://ffmpeg.org/download.html

# 5. Start de app
python app.py
```

De interface is nu bereikbaar op **http://jouwserver:5000**

## Gebruik

1. Open de webinterface.
2. Vul je API-sleutel, Gmail-adres, app-wachtwoord en ontvanger in.
3. Sla op.
4. Klik op **Nu uitvoeren** om te testen.
5. Zet de schakelaar op **Automatische planning** en kies een tijdstip.

## Productie (optioneel)

Voor een stabielere opzet op een Linux-server:

```bash
pip install gunicorn

# Start met gunicorn (4 workers)
gunicorn -w 1 -b 0.0.0.0:5000 app:app
```

> Gebruik 1 worker zodat de interne scheduler en log-streaming correct werken.

Met **nginx** als reverse proxy:

```nginx
server {
    listen 80;
    server_name jouwdomein.nl;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection keep-alive;
        proxy_read_timeout 300s;   # nodig voor SSE log-stream
    }
}
```

## Gmail app-wachtwoord aanmaken

1. Ga naar [myaccount.google.com](https://myaccount.google.com)
2. Beveiliging → Tweestapsverificatie (zet aan als dat nog niet zo is)
3. App-wachtwoorden → kies "E-mail" + apparaattype
4. Gebruik het gegenereerde 16-cijferige wachtwoord in de webinterface.

## Mapstructuur

```
oog_op_morgen_webapp/
├── app.py              ← Flask backend + pipeline
├── requirements.txt
├── README.md
├── config.json         ← wordt automatisch aangemaakt bij opslaan
└── templates/
    └── index.html      ← webinterface
```
