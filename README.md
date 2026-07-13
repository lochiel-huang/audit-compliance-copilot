# Audit & Compliance Copilot

**AI-assisted anomaly detector for accounting vouchers.**
A two-layer system that combines a deterministic rule engine with an LLM judgment layer, keeping the human accountant in the decision loop.

🔗 **Live demo**: [audit-compliance-copilot-lochiel.streamlit.app](https://audit-compliance-copilot-lochiel.streamlit.app)

---

## The problem

During a back-office finance internship at a Hong Kong capital firm, I watched accountants review monthly vouchers by covering their desks with sticky notes — one color for "missing document," another for "amount looks off." This workflow doesn't scale, produces inconsistent audit trails, and misses semantic anomalies (e.g. "a domestic travel expense filed by a person on overseas assignment") that no rule set can express in code.

This project explores what it takes to automate that review responsibly — not by replacing the accountant, but by redistributing where their attention goes.

---

## Architecture

```
Voucher (JSON)
      │
      ▼
┌─────────────────────────────────────────────────────┐
│ Layer 1 — Deterministic Rule Engine                 │
│   • 7 rules: document sufficiency, source-system    │
│     risk, metadata completeness, audit trail        │
│   • Whitelist for system-generated entries          │
│     (depreciation, FX revaluation, internal xfers)  │
│   • Output: rule ID + severity + reasoning          │
└─────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────┐
│ Layer 2 — LLM Judgment (DeepSeek via function call) │
│   • Semantic-level checks the rules can't perform   │
│   • Guardrails: schema constraints, calibrated      │
│     prompt, temperature=0                           │
│   • Output: structured verdict                      │
│     (clean / suspicious / concerning)               │
└─────────────────────────────────────────────────────┘
      │
      ▼
  Human accountant reviews flagged cases
```

---

## Evaluation results

On a synthetic dataset of **100 vouchers** with **30 injected anomalies** across 6 categories:

| Metric | Value | Meaning |
| :--- | :---: | :--- |
| Rule engine recall | **100%** | Every injected anomaly caught by the rules |
| LLM API success rate | **100%** | Guardrails prevented all malformed outputs |
| Rule × LLM verdict concordance | **100%** | Both layers agree on which vouchers need review |
| Flagged rate | **30%** | Real-world compliance systems target 20–35% |

---

## Prompt engineering iteration

The current v3 prompt is the result of three iterations, each documented as a learning artifact:

| Version | Suspicious rate | TP (rule + LLM agree) | LLM_DISMISS | Learning |
| :--- | :---: | :---: | :---: | :--- |
| v1 (initial) | 77% | 26 | 0 | Alert fatigue — the LLM found problems everywhere. |
| v2 (over-corrected) | 7% | 7 | 23 | Over-corrected — the LLM ignored real rule flags. |
| v3 (current) | 30% | 30 | 0 | Balanced — rule engine sync + calibrated defaults. |

The iteration process itself is the most important artifact of this project. It taught me that **prompt engineering is a product-design problem, not a parameter-tuning problem** — you're not tuning a model, you're expressing your product philosophy through language.

---

## Key design principles

- **Human-in-the-loop.** The system redistributes where human judgment goes, not replaces it. Every LLM action recommendation requires human confirmation.
- **Transparent reasoning.** Every flag carries either a rule ID (deterministic) or LLM natural-language reasoning (probabilistic) — no black-box verdicts.
- **Pluggable LLM provider.** The project was originally built for the Anthropic API but migrated to DeepSeek mid-project when payment channels required switching. Only client initialization changed; the schema, rules, and downstream consumers were untouched.
- **No real data.** All voucher samples in this repo are synthetically generated. See `src/data_generator.py`.

---

## Stack

- **Language**: Python 3.12+
- **Data modeling**: Pydantic v2
- **LLM**: DeepSeek (via OpenAI-compatible SDK, `function_calling`)
- **UI**: Streamlit
- **Deployment**: Streamlit Community Cloud
- **Version control**: Git + GitHub

---

## Running locally

```bash
# 1. Clone and install
git clone https://github.com/lochiel-huang/audit-compliance-copilot.git
cd audit-compliance-copilot
python -m venv .venv
.venv\Scripts\activate       # Windows PowerShell
# source .venv/bin/activate   # Mac / Linux
pip install -r requirements.txt

# 2. Add your DeepSeek API key to .env in the project root
echo DEEPSEEK_API_KEY=sk-your-key-here > .env

# 3. Generate synthetic data
python src/data_generator.py

# 4. Run rule engine + LLM evaluation
python src/rules.py
python src/evaluate_full.py

# 5. Launch the Streamlit UI
streamlit run src/app.py
```

---

## Project structure

```
audit-compliance-copilot/
├── src/
│   ├── schema.py            # Pydantic models mirroring Yonyou NC/U8 voucher structure
│   ├── data_generator.py    # Synthetic voucher generator with 6 anomaly types
│   ├── rules.py             # Layer 1: 7-rule deterministic engine
│   ├── llm_reviewer.py      # Layer 2: LLM judgment via DeepSeek + function calling
│   ├── evaluate_full.py     # Full-dataset evaluation with concordance metrics
│   └── app.py               # Streamlit UI (Dashboard + Voucher Review + About)
├── data/
│   ├── sample_vouchers.json    # 100 synthetic vouchers
│   └── full_evaluation.json    # Rule + LLM results for all vouchers
├── docs/
│   └── voucher_structure_notes.md
├── requirements.txt
├── SETUP.md
└── README.md
```

---

## Context

Built independently over one intensive development day (July 2026) as an exploration of AI-assisted compliance workflows. Informed by observations from two internships: securities compliance (Huafu International, Personal Account Dealing review) and back-office finance operations.

The public dashboard, the evaluation numbers, the three-iteration prompt history, and every design tradeoff visible in the codebase are the actual artifacts of that day's work — nothing is retrofitted for presentation.
