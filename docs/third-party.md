# Third-party fingerprint snapshot

This application uses [ModelTrace](https://github.com/xqy2006/ModelTrace) under the **MIT license**. Copyright and permission notices are preserved verbatim in [`threeparty/modeltrace_vendor/LICENSE`](../threeparty/modeltrace_vendor/LICENSE).

The maintained snapshot contains the unmodified fingerprint core, unified candidate bank, fixed challenge data, license, and an [`UPSTREAM.json`](../threeparty/modeltrace_vendor/UPSTREAM.json) provenance manifest. The manifest records the source URL, snapshot date, and SHA-256 hashes. The available source archive did not establish a Git commit, so `commit` is explicitly `null`; content hashes identify the exact retained artifacts. Runtime verifies those hashes before accepting fingerprint tasks.

The loaded bank currently includes **18 candidates in GPT and Claude families**. The UI derives the displayed list from the actual bank. The method combines nuisance-projected Hellinger features (75%) and ordered-block sequence features (25%), then calibrates probabilities for one, two, or three accepted outputs. Its closed candidate set cannot establish that an unknown model is one of those candidates. A high probability is relative to that set, not proof of provider identity or general model quality.

Three fixed Chinese challenges are versioned with the snapshot: **直觉选择·294 项**, **逐项选择·311 项**, and **快速取值·329 项**. Users may view and select them but not edit the text. Our application owns calls, concurrency, scheduling, persistence, and cancellation. It does not load ModelTrace's frontend, HTTP server, account services, or automatic extra-attempt loop. There is exactly one call per selected challenge.

An output is accepted according to the pinned core's numeric parsing and minimum-length rules. Incomplete selected challenges suppress identity alerts. Results retain bank version, diagnostics, candidate probabilities, and actual child responses. Tests exercise calibration counts 1–3 and incomplete/refusal handling.

## Upgrade procedure

1. Obtain and inspect an intended upstream version. Keep its license and identify a commit when verifiable.
2. Replace only the required core/bank/challenges and update the provenance checksums together. Do not silently change the fixed challenge prompts within an existing snapshot identifier.
3. Run fingerprint result-contract tests, known archived-output comparisons, and the full application/browser tests affected by the change.
4. Review candidate additions/removals, calibration changes, supported output shapes, and interpretation before deployment. Preserve old run snapshots and outputs.

No runtime download or automatic upstream tracking occurs. Ordinary Python and frontend dependencies are installed by package managers and are not copied into `threeparty/`.
