# Third-party notices

> **NC = Non-Commercial（非商用）.** MuScriptor weights are **CC BY-NC 4.0**;
> ADTOF weights are **CC BY-NC-SA 4.0**. The project code is PolyForm
> Noncommercial 1.0.0. None of these may be used for a commercial product or
> commercial service without separate permission.

This repository's source code does not grant rights to any third-party model
weights or binaries. If weights are distributed alongside a repository,
GitHub Release, or Git LFS, they remain under the licenses below and must keep
their attribution and NC terms.

## Model weights

| Model | Used for | License / terms | Source |
|---|---|---|---|
| Demucs `htdemucs_ft`, `htdemucs_6s` | vocal / drum / bass / guitar / piano / other separation | Code MIT; weights subject to the upstream Meta terms (research use) | <https://github.com/facebookresearch/demucs> |
| Beat-This | BPM, beats, downbeats | MIT | <https://github.com/CPJKU/beat_this> |
| GAME 1.0.3 | vocal melody (ONNX) | MIT | <https://github.com/openvpi/GAME> |
| Transkun 2.0 | piano transcription | MIT | <https://github.com/Yujia-Yan/Transkun> |
| ADTOF-pytorch | drum transcription | Code MIT; weights **CC BY-NC-SA 4.0** (non-commercial) | <https://github.com/xavriley/ADTOF-pytorch> |
| Basic Pitch 0.4 | bass / guitar / other polyphonic transcription | Apache-2.0 | <https://github.com/spotify/basic-pitch> |
| MuScriptor 0.4 medium | full-mix extra instruments | Code MIT; weights **CC BY-NC 4.0** (non-commercial) | <https://huggingface.co/MuScriptor/muscriptor-medium> |
| faster-whisper / Whisper | lyrics | MIT | <https://github.com/SYSTRAN/faster-whisper> |
| torchcrepe | monophonic f0 fallback | MIT | <https://github.com/maxrmorrison/torchcrepe> |

If you redistribute model weights, you must keep the model name, source,
license, and NC statement intact. Do not use MuScriptor or ADTOF weights for
commercial purposes. Demucs checkpoints should be obtained from the upstream
project; review its terms before redistribution. Users are responsible for
complying with each model's license.

## Libraries and tools

| Component | License |
|---|---|
| PyTorch / torchaudio / torchvision | BSD-3-Clause |
| FastAPI / Starlette / Uvicorn | MIT / BSD-3-Clause |
| React / Vite / Tone.js | MIT |
| NumPy / SciPy | BSD-3-Clause |
| librosa | ISC |
| soundfile | BSD-3-Clause |
| pretty_midi / mido | MIT |
| music21 | BSD-3-Clause |
| Verovio | LGPL-3.0 |
| audio-separator | MIT |
| ffmpeg (via `imageio-ffmpeg`) | LGPL/GPL depending on the build |
| MuseScore (optional PDF renderer) | GPL-3.0; not bundled |

Other transitive dependencies keep their own licenses. If you redistribute a
built application or a bundled environment, review the license of every
component you ship.
