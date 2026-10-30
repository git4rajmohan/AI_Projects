Languages: **English** | [日本語](README.ja.md)

# MaintAI Decision Platform

**From machine signals to explainable maintenance decisions.**

[Portfolio](../../README.md) | [User guide](MaintAI_Userguide.html)

MaintAI separates structured decision-making from generative explanation:
validated sensor readings and engineering rules feed the local TEV1 decision
model, deterministic policy decides the outcome, and an optional LLM explains
the evidence without overriding that outcome.

This is a local decision-support demonstration, not a machine controller,
failure predictor, or production safety system. All bundled readings are
synthetic. Thresholds require equipment-specific engineering validation.

## Demo Video

[![DecisionModeldemo](https://img.youtube.com/vi/tq8xiNg5_Zg/0.jpg)](https://youtu.be/tq8xiNg5_Zg)

## What it demonstrates

- Eight Streamlit pages: fleet dashboard, machine monitoring, decision workbench,
  machine registry, CSV import, maintenance history, model evaluation, settings.
- Per-machine, versioned temperature, vibration, and motor-load limits.
- CSV validation and quarantine reports for rejected readings.
- Separate model output, policy outcome, confidence, and human-review status.
- SQLite records for readings, decisions, inspections, and audit events.
- Labelled synthetic evaluation with accuracy, per-class metrics, and confusion
  matrix. Synthetic results are not production performance measurements.
- Grounded JSON explanations, with a labelled deterministic fallback when the
  explanation service is unavailable.

## Architecture

```text
CSV / synthetic readings -> validation -> engineering rules and trends
  -> TEV1 classification -> deterministic policy -> persisted decision
  -> grounded LLM explanation -> human inspection and review closure
```

Policy prioritizes invalid inputs, mandatory escalation, critical thresholds,
unavailable model output, and low-confidence or contradictory classifications
before accepting a model decision. An urgent action still requires human review.

**Stack:** Python, Streamlit, SQLite, Requests, Pydantic, Pandas, Plotly,
scikit-learn, python-dotenv, pytest, Ollama / Ollama Cloud.

The decision service uses **`POST /v1/systemone`**, a non-standard endpoint,
not `/api/chat`. Your local Ollama/model setup must provide it; pulling the
model alone does not establish endpoint compatibility. The generative service
uses `/api/chat`.

## Run locally (Windows PowerShell)

From this project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env locally. Set OLLAMA_API_KEY only if using Ollama Cloud.
ollama pull tev1:4b
.\.venv\Scripts\python.exe -m maintai.seed
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m streamlit run maintai\app.py --server.address 127.0.0.1
```

Open `http://localhost:8501`. Seed creates five demo machines and synthetic
readings; it leaves existing machines unchanged. Model availability varies.
For local explanations, set `LLM_MODEL` to an installed chat model and
`LLM_BASE_URL=http://localhost:11434`; no cloud key is needed.

### Five-minute walkthrough

1. In **Machine Monitoring**, select a machine and inspect readings and limits.
2. Run analysis, then inspect the model output and separate application
   decision in **Decision Workbench**.
3. Review the explanation, evidence, and any service-unavailability messages.
4. Record an inspection as an Engineer in **Maintenance History** and close
   the review. Verify the updated dashboard.
5. Run **Model Evaluation** for labelled synthetic policy measurements.

The bundled healthy, warning, and critical CSVs in [maintai/data](maintai/data)
can also be imported sequentially. Their fixed timestamps may now be stale:
use current timestamps for a live demo or expect data-review outcomes.

## Configuration and troubleshooting

Configuration is centralized in [config/settings.py](config/settings.py).
[.env.example](.env.example) documents hosts, model names, timeouts, confidence
and trend settings. Machine-specific limits are edited in Machine Registry;
the defaults are not universal engineering limits.

- **Missing imports:** run from this project directory and set `PYTHONPATH`
  as above.
- **Ollama unavailable:** start Ollama and use the Settings connection checks.
  Verify `/v1/systemone` support as well as the model name.
- **Cloud authentication failure:** check the local key and model selection;
  do not paste credentials into issues, screenshots, or logs.
- **No fleet data:** run `python -m maintai.seed` with synthetic data enabled.
- **Stale data:** generate fresh readings in Monitoring or import current
  readings; do not weaken freshness checks to make old samples look current.

## Tests

```powershell
$env:OLLAMA_API_KEY = "dummy-test-key"
$env:OLLAMA_CLOUD_MODEL = "test-model"
$env:RUN_LIVE_TESTS = "0"
.\.venv\Scripts\python.exe -m pytest tests -q
```

Run these in a separate terminal: the dummy values are for mocked tests, not
real inference. Default tests mock HTTP calls. Live smoke tests are opt-in with
`RUN_LIVE_TESTS=1` and require configured, reachable model services.

## Project layout

| Path | Purpose |
|---|---|
| [maintai](maintai) | Active application, eight pages, rules, policy, persistence, seed |
| [config](config) | Environment-based shared configuration |
| [services](services) | Model clients, result formatting, evaluation |
| [prompts](prompts) | Shared structured decision prompts |
| [tests](tests) | Offline regression and opt-in live checks |
| [oldbackup](oldbackup) | Original Decision + LLM Playground, retained as an archive |
| [MaintAI_Userguide.html](MaintAI_Userguide.html) | Standalone illustrated guide; download and open in a browser |

The archived playground compares LLM-only, TEV1 + LLM, and side-by-side modes.
To run it from this directory with the same `PYTHONPATH`:

```powershell
Set-Location oldbackup
..\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

## Credentials and safety

- Only an empty-key template is published. Keep real keys in the ignored local
  `.env` or environment variables.
- Environment variants, Streamlit secrets, private-key files, local databases,
  exports, virtual environments, and recordings are excluded from Git.
- Screenshots and development notes are not published with this copy.
- Demo role selection is **not authentication**. Keep the app on localhost;
  do not expose it to a network or connect it to actuators.
