# Setup — Day 1

## 1. Local environment (Cursor)
Extract this folder to `D:\projects\audit-compliance-copilot` (or wherever you keep code).

Open in Cursor.

## 2. Python environment
Open the terminal in Cursor (Ctrl+`) and run:

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows PowerShell
# or on Mac/Linux: source .venv/bin/activate

pip install -r requirements.txt
```

## 3. Verify the generator works
```bash
cd src
python data_generator.py
```

Expected output:
```
Generated 30 vouchers → .../data/sample_vouchers.json
  A1_MISSING_DOCS_EXPENSE: 3
  A2_MANUAL_ENTRY_LARGE: 3
  A3_MISSING_PERSONNEL_TRAVEL: 3
  A4_MISSING_PROJECT_TRAVEL: 3
  A5_MISSING_COUNTERPARTY: 3
  A6_VAGUE_SUMMARY_LARGE: 3
  CLEAN_OR_SYSTEM: 12
```
(Actual counts vary slightly depending on n.)

Open `data/sample_vouchers.json` to eyeball a few — check that they look like the real vouchers.

## 4. Initialize the git repo
```bash
git init
git add .
git commit -m "Day 1: schema + data generator"

# Create empty repo on GitHub named 'audit-compliance-copilot'
git remote add origin https://github.com/lochiel-huang/audit-compliance-copilot.git
git branch -M main
git push -u origin main
```

## 5. Anthropic API key (for next sprint)
Get an API key at https://console.anthropic.com/

Create `.env` in the project root (already gitignored):
```
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

## What's coming next
- `src/rules.py` — the deterministic rule engine (Sprint 2 weekend 7/18–19)
- `src/llm_reviewer.py` — Claude API judgment layer (Sprint 3)
- `src/app.py` — Streamlit UI (Sprint 3)
