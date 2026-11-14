# Contributing

Thanks for taking a look. This project is a personal/research tool released
under a non-commercial license, so please keep contributions compatible with
that intent.

## Ground rules

- **Never commit test audio, generated projects, logs, cookies, or API
  tokens.** Model weights may be distributed only through Git LFS or a GitHub
  Release, with the model names, sources, licenses, and NC terms kept intact.
  `.gitignore` covers the common cases; check `git status` before committing.
- MuScriptor and ADTOF weights are non-commercial. Do not use them, or this
  project, for a commercial product or service.
- Keep the pipeline usable without optional models: every adapter should have a
  fallback or a clear skip path.
- Windows is the primary target. Cross-platform changes are welcome, but say
  which platform you tested.

## Development setup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Manual:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install --no-deps basic-pitch==0.4.0
cd frontend && npm install && npm run build && cd ..
```

## Checks

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m pytest

cd frontend
npm run build
```

Tests use a temporary `MUSIC2SCORE_HOME` and do not need model weights.
Optional integration tests are skipped when the corresponding model or tool is
missing.

## Pull requests

- Keep changes focused; describe the user-visible behavior and the verification
  you ran.
- Add or update tests for pipeline/API/notation changes.
- If you change model parameters, update `docs/MODELS.md`.
- If you add an instrument, update `backend/app/instruments/catalog.yaml` and
  `docs/INSTRUMENTS.md`.
- Do not reformat unrelated files.
