# Model downloads

music2score 不会在首次运行时静默下载权重。把权重放到：

```
$MUSIC2SCORE_HOME/models/
```

默认 home 是 `<repository>/runtime`，所以默认路径是
`<repository>/runtime/models/`。如果想把模型放到其他盘，设置 `MUSIC2SCORE_HOME`。

> **NC（Non-Commercial，非商用）声明：** MuScriptor 权重是 **CC BY-NC 4.0**；
> ADTOF 权重是 **CC BY-NC-SA 4.0**。它们仅限个人/研究/教育等非商业用途。
> 如果你把权重随仓库、GitHub Release 或 Git LFS 再分发，必须保留模型名称、出处、
> 许可证和 NC 声明；不得用于商业产品/服务。详见
> [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。

## 0. 权重分发方式（可选）

如果你要把权重随公开仓库提供，按文件大小选择：

| 文件 | 大小 | 方式 |
|---|---|---|
| Demucs `.th`（单个） | 55–84 MB | 普通 Git 可以，但建议 LFS |
| faster-whisper `model.bin` | ~461 MB | **Git LFS 或 GitHub Release 附件** |
| MuScriptor `model.safetensors` | ~1.23 GB | **GitHub Release 附件（推荐）或 Git LFS** |
| GAME `.onnx`（单个） | < 100 MB | 普通 Git 或 LFS |

GitHub 普通 Git 的单文件上限是 **100 MB**；超过会被拒绝。Git LFS 免费额度只有
1 GB 存储 / 1 GB 月流量，2 GB+ 的完整权重通常需要 Release 附件或购买 LFS 数据包。

**推荐：GitHub Release 附件**

```powershell
# 先运行打包脚本：生成按模型分组的 zip、manifest.json、release-notes.md
powershell -ExecutionPolicy Bypass -File scripts\package_weights.ps1
# 权重不在 runtime/models 时：
#   ... -Source "D:\models"

# 然后按脚本输出的命令上传：
gh release create v0.1.0-weights ./release-assets/* `
  --title "music2score model weights v0.1.0" `
  --notes-file ./release-assets/release-notes.md
```

**备选：Git LFS**

```powershell
git lfs install
git lfs track "*.th" "*.onnx" "*.safetensors" "*.bin" "*.pt"
git add .gitattributes
# 注意：仓库默认 .gitignore 会忽略权重；需要为要跟踪的目录加例外，
# 或使用 git add -f，并在提交前用 git check-ignore 确认。
git add <weight-files>
git commit -m "Add non-commercial model weights"
```

无论用哪种方式，**不要移除 README / NOTICE / THIRD_PARTY_NOTICES 中的模型署名和 NC 声明**。

## 1. Demucs (required)

`audio-separator` can download `htdemucs_ft` / `htdemucs_6s` automatically on
first use. If your network to `dl.fbaipublicfiles.com` is slow, download these
files manually and keep the filenames:

| Purpose | URL | Save as |
|---|---|---|
| htdemucs 4-stem (84 MB) | <https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th> | `955717e8-8726e21a.th` |
| htdemucs_6s (55 MB) | <https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th> | `5c90dfd2-34c22ccb.th` |
| htdemucs_ft drums | <https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/f7e0c4bc-ba3fe64a.th> | `f7e0c4bc-ba3fe64a.th` |
| htdemucs_ft bass | <https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/d12395a8-e57c48e6.th> | `d12395a8-e57c48e6.th` |
| htdemucs_ft other | <https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/92cfc3b6-ef3bcb9c.th> | `92cfc3b6-ef3bcb9c.th` |
| htdemucs_ft vocals | <https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/04573f0d-f3cf25b2.th> | `04573f0d-f3cf25b2.th` |

Model YAML files (small):

- <https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/htdemucs.yaml>
- <https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/htdemucs_6s.yaml>
- <https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/htdemucs_ft.yaml>

Put the `.th` and `.yaml` files directly in `$MUSIC2SCORE_HOME/models/`.

## 2. MuScriptor (optional, quality preset)

MuScriptor adds extra instruments from the full mix (brass, winds, strings,
synths, ...). It is the largest optional download (~1.23 GB).

Official gated repository (requires Hugging Face login and accepting the
CC BY-NC 4.0 license):

- <https://huggingface.co/MuScriptor/muscriptor-medium>

Download:

- `model.safetensors`
- `config.json`

Layout:

```
$MUSIC2SCORE_HOME/models/muscriptor/muscriptor-medium/
├─ model.safetensors
└─ config.json
```

You can also point at any directory:

```powershell
$env:MUSCRIPTOR_WEIGHTS = "$HOME\models\muscriptor-medium"
```

Without weights, quality mode still runs and simply skips the extra-instrument
pass.

> Third-party mirror: the helper script in
> `scripts/fetch_muscriptor_mirror.py` defaults to the public mirror
> `BEDO97/muscriptor-medium`. It is convenient on restricted networks but is
> not controlled by the upstream authors. Prefer the official repository when
> you can access it.

## 3. GAME (optional, vocal melody)

GAME 1.0.3 medium ONNX (MIT, OpenVPI), ~180 MB:

- <https://github.com/openvpi/GAME/releases/download/v1.0.3/GAME-1.0.3-medium-onnx.zip>

Or use the helper:

```powershell
python scripts/download_game.py
```

Layout:

```
$MUSIC2SCORE_HOME/models/game/GAME-1.0.3-medium-onnx/
  config.json
  encoder.onnx
  segmenter.onnx
  estimator.onnx
```

`VOCAL_MELODY_MODE=auto` (default) prefers GAME on clean vocals and falls back
to Basic Pitch + f0 when the result is too sparse.

## 4. faster-whisper (optional, lyrics)

Lyrics need a CTranslate2 Whisper model. `small` (~462 MB) is a good default;
`tiny` is enough to test the pipeline.

Download these files from the official Hugging Face repository
(`Systran/faster-whisper-<size>`):

- `config.json`
- `model.bin`
- `tokenizer.json`
- `vocabulary.txt`

Layout:

```
$MUSIC2SCORE_HOME/models/faster-whisper/small/
  config.json
  model.bin
  tokenizer.json
  vocabulary.txt
```

Environment variables:

```powershell
$env:LYRICS_MODEL = "small"   # tiny / base / small / medium / large-v3
$env:LYRICS_LANGUAGE = "zh"   # optional; auto-detect by default
$env:LYRICS_DEVICE = "cpu"    # cuda requires cuBLAS
```

## 5. ADTOF (optional, drums)

Install from the upstream repository:

```powershell
pip install "https://github.com/xavriley/ADTOF-pytorch/archive/85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9.zip"
```

The package ships its 3.6 MB weights. If you already have a weight file:

```powershell
$env:ADTOF_WEIGHTS = "$HOME/models/adtof_frame_rnn_pytorch_weights.pth"
```

Without ADTOF, the drum track falls back to onset + spectral-centroid
classification (kick/snare/hat/crash only).

## 6. MuseScore (optional, PDF)

PDF export uses the MuseScore 4 CLI. Install MuseScore 4 from
<https://musescore.org/> and either add it to `PATH` or set:

```powershell
$env:MUSESCORE_PATH = "C:\Program Files\MuseScore 4\bin\MuseScore4.exe"
```

MusicXML and SVG export work without MuseScore.

## 7. Verify

```powershell
.\.venv\Scripts\python.exe -m app.cli doctor
```

`doctor` reports which models and optional tools were found, and which stages
will fall back.
