# WebApp (Ask → Chart inline)

This adds a simple web UI that lets you type a question and renders the chart inline.

## Install deps (one time)

Make sure you’re in your venv, then:

```bash
pip install -r requirements.txt
```

(`matplotlib` is required for chart generation.)

## Start

### Windows (PowerShell)

```powershell
.\start_webapp.ps1
```

### Linux/macOS

```bash
chmod +x start_webapp.sh
./start_webapp.sh
```

### Manual

```bash
python -m uvicorn src.webapp:app --host 0.0.0.0 --port 8012
```

## Use

Open:
- `http://localhost:8012`

Type a question like:
- `top 5 who consumed most hours in september`

The UI calls the mounted endpoint:
- `POST /api/ask-chart`

and renders the returned base64 PNG as an `<img>` inline.


