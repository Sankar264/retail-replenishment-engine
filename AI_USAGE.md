# AI usage disclosure

This project was built inside the 72-hour challenge window under its rules: AI tools are allowed, the work is my own, and I am ready to
explain every part. Prompt history is in [`prompts/`](prompts/). A map from each requirement to its evidence is in
[`REVIEWER_GUIDE.md`](REVIEWER_GUIDE.md).

## 1. Project timeline (from the git history)

| When | Commit | What happened |
|---|---|---|
| Day 1-2 (about 30 Oct) | `Retail replenishment engine: generator, forecasting, replenishment, tests` | First working version: seeded generator, forecasting with temporal holdout, reorder policy and recommendations, labelled anomalies, validation, tests |
| Day 3, overnight (31 Oct) | `Improve replenishment pipeline and anomaly detection` | Improvements to the pipeline and the anomaly detectors |
| Day 3 (1 Nov) | `Fix review items C01-C12: fail-closed validation, order-value reconciliation, lead-time validity, ...` | Review-driven corrections |
| Day 3 (1 Nov) | `Wire validation gates, staged publish, new checks` | Final review pass: gates wired into `run()`, staged publish, new validation checks, all 49 tests passing |
| Day 3 (1 Nov) | `Remove nested repo copy` | Repository cleanup |
| Day 3 (1 Nov) | Documentation commit | AI usage disclosure, prompt history, reviewer guide, README limitations |

## 2. Tools used

| Tool | Used for | When |
|---|---|---|
| Claude (claude.ai) | Final review against the brief and FAQ; debugging failing tests; patching `src/pipeline.py` and `src/validate.py`; git recovery; drafting documentation | 1 Nov 2026 |

The prompts I sent to Claude are recorded in `prompts/01_claude_repo_review_and_fixes.md`.

## 3. How I worked with AI

I used AI as a reviewer, debugger and drafting assistant. On each issue the loop was:
1. Run the code or tests myself and read the real output.
2. Ask the AI to explain or fix a specific failure, usually by sharing a screenshot of the error.
3. Apply the change in my own repository.
4. Re-run the tests and the pipeline to confirm the result before moving on.

## 4. Where AI accelerated my work

- **Requirement review.** Checking the repo against the brief, FAQ and submission guidelines. This surfaced the missing prompt history, the unpushed commit and the nested duplicate repository.
- **Debugging.** Finding why 9 tests in `tests/test_corrections.py` failed: `run()` in `src/pipeline.py` did not call the validation-gate and publish helpers that already existed, and `datetime`, `timezone` and `shutil` were not imported.
- **Git recovery.** Restoring a deleted test file, resolving a rejected push, finishing an interrupted rebase and removing an accidentally committed nested repository.
- **Documentation drafts.** This disclosure, the README limitations section and the reviewer guide.

## 5. Where I relied on AI heavily

- The `run()` / `_run_stage()` split in `src/pipeline.py`: staged output, publish only after both validation gates pass, run ledger, failed-attempt diagnostics, archive of earlier runs, clean-baseline snapshot, exit code 2 on gate failure, and N/A rendering of missing metrics in the HTML report.
- Three new checks in `src/validate.py`: range checks on supplier pack size, MOQ and unit cost; `reconcile.order_value=qty*unit_cost`; and `reconcile.policy_id_points_to_same_store_sku`.

## 6. What I personally ran and validated

Each item below was run on my machine, and the results appeared in my terminal.
- `python -m pytest -q`: **49 passed**. Before the fixes, 9 of 49 failed.
- `python -m src.pipeline --scale starter --seed 20261022 --out data/starter`: completes with 25 labelled anomalies, every detector at precision and recall 1.00.
- `python -m src.reproduce --scale starter`: 44 files compared, row counts and checksums identical across two runs.
- Found that the project existed as two copies, kept one as the source of truth, resolved a rejected push by finishing a git rebase, and removed the nested duplicate from GitHub.
- Re-checked the GitHub page in my browser after each push.

## 7. Design decisions I can explain

- **Stockout censoring.** A day is excluded from training and evaluation when `stockout_flag=1`, or when sales are zero and the shelf was empty. Treating stockouts as zero demand would bias forecasts low.
- **Forecast method.** Segment-aware hybrid: SES for smooth and erratic demand, Croston-SBA for intermittent and lumpy demand, a cohort blend for new SKUs. Evaluated on a temporal holdout, with a test showing future sales do not leak into the forecast.
- **Replenishment.** Safety stock `z * sqrt(L*sigma_d^2 + d^2*sigma_L^2)`, reorder point `d*L + SS`, order-up-to `d*(L+R) + SS`, then pack size, MOQ and capacity headroom, with reason-coded exceptions.
- **Clean baseline first.** The baseline must pass validation with 0 violations before five labelled anomalies are injected, so injected rows never silently corrupt other rows. Labels live only in `ground_truth/`.
- **Fail-closed publishing.** Output is built in a staging directory and published only if the validation gates pass. A failed run never replaces earlier outputs, and every attempt is logged in `run_ledger.jsonl`.

## 8. Scope of this disclosure

- The prompt history covers the Claude conversation described above. Claude's replies are not included.
- Limitations of the solution are listed in the README under "Limitations and next steps".
