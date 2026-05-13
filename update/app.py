"""
Met het Oog op Morgen – Podcast Samenvatter
Flask webapplicatie + scheduler
"""

import os, json, threading, logging, smtplib, tempfile, re
from datetime import datetime
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Flask, render_template, request, jsonify, Response
import feedparser
import requests as req_lib
import anthropic

# ── Optionele Whisper import ──────────────────────────────────────────────────
try:
    import whisper as whisper_lib
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CONFIG_FILE = Path("config.json")
RSS_URL     = "https://podcast.npo.nl/feed/met-het-oog-op-morgen.xml"

# ── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {
        "claude_api_key": "",
        "email_afzender": "",
        "email_wachtwoord": "",
        "email_ontvanger": "",
        "whisper_model": "base",
        "schedule_time": "07:00",
        "schedule_enabled": False,
    }

def save_config(data: dict):
    CONFIG_FILE.write_text(json.dumps(data, indent=2))

# ── Globals voor log-streaming ────────────────────────────────────────────────
run_log: list[str] = []
run_running = False

def emit(msg: str):
    ts  = datetime.now().strftime("%H:%M:%S")
    run_log.append(f"[{ts}] {msg}")
    log.info(msg)

# ── Kern-pipeline ─────────────────────────────────────────────────────────────

def haal_nieuwste_aflevering():
    emit("📡 RSS-feed ophalen …")
    feed  = feedparser.parse(RSS_URL)
    items = [e for e in feed.entries if e.get("enclosures")]
    if not items:
        raise RuntimeError("Geen afleveringen met audio gevonden.")
    n = items[0]
    return n.enclosures[0].href, n.title, n.get("published", ""), n.get("summary", "")

def download_audio(url: str, pad: Path):
    emit("⬇️ Audio downloaden …")
    with req_lib.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(pad, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
    emit(f"   Opgeslagen ({pad.stat().st_size // 1024} KB)")

def transcribeer(audiopad: Path, model_naam: str) -> str:
    if not WHISPER_AVAILABLE:
        raise RuntimeError("openai-whisper is niet geïnstalleerd. Voer 'pip install openai-whisper' uit.")
    emit(f"🔊 Transcriberen met Whisper ({model_naam}) …")
    model  = whisper_lib.load_model(model_naam)
    result = model.transcribe(str(audiopad), language="nl", verbose=False)
    emit(f"   Transcriptie klaar ({len(result['text'])} tekens)")
    return result["text"]

SYSTEEM_PROMPT = """
Je bent een redacteur die luisteraars helpt om 'Met het Oog op Morgen' snel te begrijpen.
Analyseer de transcriptie en geef een gestructureerde samenvatting in het Nederlands.

Gebruik ALTIJD dit vaste formaat (Markdown):

## 🎙️ Met het Oog op Morgen – {DATUM}

**Presentator:** [naam]

---

### Gesprekken & onderwerpen

Voor elk gesprek / segment:

**[Naam gast of 'Nieuwsoverzicht']** – *[functie/context gast, of leeg]*
- [punt 1]
- [punt 2]
- [punt 3]
- [punt 4]
- [punt 5]

---

### 📰 Samenvatting in één alinea
[Kort overzicht van de gehele aflevering in 3-4 zinnen]
""".strip()

def maak_samenvatting(transcriptie: str, titel: str, datum: str, api_key: str) -> str:
    emit("🤖 Samenvatting genereren via Claude …")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=SYSTEEM_PROMPT,
        messages=[{"role": "user", "content":
            f"Transcriptie van '{titel}' ({datum}):\n\n"
            f"<transcriptie>\n{transcriptie[:30000]}\n</transcriptie>\n\n"
            f"Maak de samenvatting. Vervang {{DATUM}} door: {datum}."}],
    )
    emit("   Samenvatting ontvangen.")
    return msg.content[0].text

def _inline_md(t):
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         t)
    return t

def md_naar_html(md: str) -> str:
    regels = []
    in_lijst = False
    for r in md.splitlines():
        if r.startswith("## "):
            if in_lijst: regels.append("</ul>"); in_lijst = False
            regels.append(f'<h2>{r[3:]}</h2>')
        elif r.startswith("### "):
            if in_lijst: regels.append("</ul>"); in_lijst = False
            regels.append(f'<h3>{r[4:]}</h3>')
        elif r.startswith("- "):
            if not in_lijst: regels.append("<ul>"); in_lijst = True
            regels.append(f'<li>{_inline_md(r[2:])}</li>')
        elif r.startswith("---"):
            if in_lijst: regels.append("</ul>"); in_lijst = False
            regels.append("<hr>")
        elif r.strip() == "":
            if in_lijst: regels.append("</ul>"); in_lijst = False
            regels.append("")
        else:
            if in_lijst: regels.append("</ul>"); in_lijst = False
            regels.append(f'<p>{_inline_md(r)}</p>')
    if in_lijst: regels.append("</ul>")
    return "\n".join(regels)

def stuur_email(samenvatting_md: str, datum_str: str, cfg: dict):
    emit("📧 E-mail versturen …")
    html = f"""<html><body style="font-family:Georgia,serif;max-width:680px;margin:auto;color:#1a1a1a;padding:24px">
    {md_naar_html(samenvatting_md)}
    <hr><p style="font-size:.75em;color:#888">Automatisch gegenereerd op {datetime.now().strftime('%d-%m-%Y %H:%M')}</p>
    </body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🎙️ Met het Oog op Morgen – {datum_str}"
    msg["From"]    = cfg["email_afzender"]
    msg["To"]      = cfg["email_ontvanger"]
    msg.attach(MIMEText(samenvatting_md, "plain",  "utf-8"))
    msg.attach(MIMEText(html,            "html",   "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(cfg["email_afzender"], cfg["email_wachtwoord"])
        s.sendmail(cfg["email_afzender"], cfg["email_ontvanger"], msg.as_string())
    emit(f"   ✅ Verstuurd naar {cfg['email_ontvanger']}")

def run_pipeline(cfg: dict):
    global run_running
    run_running = True
    run_log.clear()
    try:
        audio_url, titel, datum, _ = haal_nieuwste_aflevering()
        with tempfile.TemporaryDirectory() as tmp:
            audiopad = Path(tmp) / "aflevering.mp3"
            download_audio(audio_url, audiopad)
            transcriptie = transcribeer(audiopad, cfg["whisper_model"])
        samenvatting = maak_samenvatting(transcriptie, titel, datum, cfg["claude_api_key"])
        stuur_email(samenvatting, datum, cfg)
        emit("🏁 Pipeline voltooid!")
    except Exception as e:
        emit(f"❌ Fout: {e}")
    finally:
        run_running = False

# ── Scheduler ─────────────────────────────────────────────────────────────────
import schedule, time

def start_scheduler():
    def job():
        cfg = load_config()
        if cfg.get("schedule_enabled"):
            emit("⏰ Geplande uitvoering gestart.")
            threading.Thread(target=run_pipeline, args=(cfg,), daemon=True).start()

    def loop():
        while True:
            cfg = load_config()
            schedule.clear()
            if cfg.get("schedule_enabled") and cfg.get("schedule_time"):
                schedule.every().day.at(cfg["schedule_time"]).do(job)
            schedule.run_pending()
            time.sleep(30)

    threading.Thread(target=loop, daemon=True).start()

# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    cfg = load_config()
    return render_template("index.html", cfg=cfg, whisper_ok=WHISPER_AVAILABLE)

@app.route("/save_config", methods=["POST"])
def save_config_route():
    data = request.json
    existing = load_config()
    existing.update(data)
    save_config(existing)
    return jsonify({"ok": True})

@app.route("/run_now", methods=["POST"])
def run_now():
    global run_running
    if run_running:
        return jsonify({"ok": False, "msg": "Al bezig!"})
    cfg = load_config()
    threading.Thread(target=run_pipeline, args=(cfg,), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/log_stream")
def log_stream():
    def generate():
        seen = 0
        while True:
            while seen < len(run_log):
                yield f"data: {run_log[seen]}\n\n"
                seen += 1
            if not run_running and seen >= len(run_log) and seen > 0:
                yield "data: __done__\n\n"
                return
            time.sleep(0.5)
    return Response(generate(), mimetype="text/event-stream")

@app.route("/status")
def status():
    return jsonify({"running": run_running, "log": run_log[-20:]})

if __name__ == "__main__":
    start_scheduler()
    app.run(host="0.0.0.0", port=5000, debug=False)
