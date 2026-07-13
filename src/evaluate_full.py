"""
Full evaluation — run rules + LLM on the entire voucher dataset and compute
the three metrics that answer 'is this system trustworthy enough to demo':

  1. LLM success rate:
     % of vouchers where the LLM returned a valid structured assessment.
     This measures the two-layer guardrail (schema + prompt + temperature=0).

  2. Rule × LLM agreement:
     Confusion matrix between rule-flag presence and LLM verdict.
     This shows whether Layer 2 is doing independent judgment or just parroting.

  3. LLM extra-detection rate:
     % of vouchers where rules found nothing but the LLM raised a concern.
     This is Layer 2's net contribution — what it adds beyond deterministic rules.

Results are saved to data/full_evaluation.json for post-hoc inspection.
"""
from __future__ import annotations
import sys
import json
import time
from pathlib import Path
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from schema import Voucher, Anomaly
from rules import review_voucher, load_vouchers
from llm_reviewer import review_with_llm


def _bucket(has_rule_flag: bool, llm_verdict: str) -> str:
    llm_flagged = llm_verdict in ("suspicious", "concerning")
    if not has_rule_flag and not llm_flagged:
        return "TN"          # both clean
    if has_rule_flag and llm_flagged:
        return "TP"          # both flag
    if not has_rule_flag and llm_flagged:
        return "LLM_EXTRA"   # LLM catches, rules miss
    return "LLM_DISMISS"     # rules flag, LLM dismisses


def _save(results, out_path):
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main():
    data_path = Path(__file__).parent.parent / "data" / "sample_vouchers.json"
    if not data_path.exists():
        print(f"ERROR: {data_path} not found. Run data_generator.py first.")
        return

    pairs = load_vouchers(data_path)
    total = len(pairs)

    print(f"Loaded {total} vouchers from {data_path.name}")
    print(f"Backend: DeepSeek (deepseek-chat)")
    print(f"Estimated cost: ~¥{total * 0.007:.2f}  (≈ US${total * 0.001:.2f})")
    print(f"Estimated time: {max(1, total * 4 // 60)}-{max(2, total * 8 // 60)} minutes")
    print(f"You can Ctrl+C at any time — partial results will still be saved.\n")

    results = []
    successes = 0
    failures = 0
    agreement = Counter()
    llm_verdicts = Counter()

    out_path = Path(__file__).parent.parent / "data" / "full_evaluation.json"
    start = time.time()

    try:
        for i, (v, injected) in enumerate(pairs, 1):
            anomalies = review_voucher(v)
            has_flag = len(anomalies) > 0
            elapsed = time.time() - start
            eta = elapsed / i * (total - i) if i > 1 else 0

            print(f"[{i:>3}/{total}] {v.voucher_id} rules={len(anomalies)} "
                  f"elapsed={elapsed:>4.0f}s eta={eta:>4.0f}s ",
                  end="", flush=True)

            try:
                a = review_with_llm(v, anomalies)
                successes += 1
                llm_verdicts[a.overall_assessment] += 1
                bucket = _bucket(has_flag, a.overall_assessment)
                agreement[bucket] += 1

                results.append({
                    "voucher_id": v.voucher_id,
                    "injected_anomaly": injected,
                    "rule_flags": [
                        {"rule_id": x.rule_id, "severity": x.severity, "title": x.title}
                        for x in anomalies
                    ],
                    "llm_assessment": a.model_dump(),
                    "bucket": bucket,
                    "success": True,
                })
                print(f"→ {a.overall_assessment:<11} [{bucket}]")

            except Exception as e:
                failures += 1
                results.append({
                    "voucher_id": v.voucher_id,
                    "injected_anomaly": injected,
                    "rule_flags": [
                        {"rule_id": x.rule_id, "severity": x.severity, "title": x.title}
                        for x in anomalies
                    ],
                    "llm_error": f"{type(e).__name__}: {e}",
                    "success": False,
                })
                print(f"→ ERROR: {type(e).__name__}")

            # Save every 10 to protect against Ctrl+C
            if i % 10 == 0:
                _save(results, out_path)

    except KeyboardInterrupt:
        print("\n\n[Interrupted — saving partial results...]")

    finally:
        _save(results, out_path)
        print(f"\nResults saved to {out_path}\n")

    # ---------- Summary ----------
    n_done = successes + failures
    total_calls = max(1, successes)  # avoid divide by zero

    print("=" * 72)
    print(f" Full Evaluation Summary — {n_done}/{total} vouchers processed")
    print("=" * 72)
    print(f" LLM success rate:  {successes}/{n_done} ({successes/max(1,n_done)*100:.1f}%)  "
          f"[{failures} errors]")
    print()

    print(f" LLM verdict distribution:")
    for verdict in ("clean", "suspicious", "concerning"):
        n = llm_verdicts[verdict]
        print(f"   {verdict:<12} {n:>4} ({n/total_calls*100:5.1f}%)")
    print()

    print(f" Rule × LLM agreement (of {successes} successful LLM calls):")
    print(f"   TN  both clean:               {agreement['TN']:>4} ({agreement['TN']/total_calls*100:5.1f}%)")
    print(f"   TP  both flag issue:          {agreement['TP']:>4} ({agreement['TP']/total_calls*100:5.1f}%)")
    print(f"   +   LLM catches (rules miss): {agreement['LLM_EXTRA']:>4} ({agreement['LLM_EXTRA']/total_calls*100:5.1f}%)")
    print(f"   −   LLM dismisses rule flag:  {agreement['LLM_DISMISS']:>4} ({agreement['LLM_DISMISS']/total_calls*100:5.1f}%)")
    print()

    total_agree = agreement['TN'] + agreement['TP']
    print(f" Overall rule-LLM concordance: {total_agree}/{total_calls} ({total_agree/total_calls*100:.1f}%)")
    print(f" LLM net addition (extra catches): {agreement['LLM_EXTRA']/total_calls*100:.1f}%")
    print("=" * 72)
    print()
    print(" How to read:")
    print("   High LLM success rate = guardrails work.")
    print("   High TN + TP = layers agree = system consistent.")
    print("   'LLM catches' > 0 = Layer 2 adds value beyond deterministic rules.")
    print("   'LLM dismisses' cases are worth eyeballing in full_evaluation.json.")


if __name__ == "__main__":
    main()
