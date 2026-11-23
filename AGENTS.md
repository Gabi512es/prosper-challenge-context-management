# Submission maintenance

This branch is the reviewed Prosper submission, based on the original starter.

- README.md contains setup and the exact builder/test-call workflow.
- solution.md summarizes architecture, mocks, measured versions and limitations.
- Active runtime for Scheduler v4: backend/v4/, interpreter v1.10, gpt-4o-2024-08-06.
- Keep v1.12 inactive; its recorded probe failed the adoption rule.
- V2 reference data is outside the editor agent directory. Never attribute frozen v2 measurements to v4.
- Do not change catalog facts, scenario expectations or booking/consent behavior to improve a result.
- Do not make paid model or speech requests without an estimate and explicit authorization.
- API keys belong only in ignored backend/.env; logs stay in ignored backend/logs/.
- make test is offline and disables opt-in paid integrations. Report skips accurately.
- Use synthetic identities for tests. Do not publish operational logs, private fixtures or machine paths.
- Do not add project time-spent or personal scheduling details to submission materials.
- Record substantive decisions in docs/decisions.md. Do not publish or move frozen refs without authorization.
