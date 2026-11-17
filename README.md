# music2score

<p align="center">
  <img src="assets/music2score-preview.png" width="140" alt="music2score icon">
</p>

<p align="center">
  <strong>本地全自动扒谱：音频 → 分轨 → 多轨 MIDI → MusicXML / SVG / PDF</strong>
</p>

<p align="center">
  <strong>使用模型：Demucs · Beat-This · GAME · faster-whisper · Transkun · ADTOF · Basic Pitch · MuScriptor · torchcrepe</strong><br>
  <strong>NC（Non-Commercial，非商用）— 仅限个人 / 研究 / 教育使用</strong>
</p>

<p align="center">
  <img alt="License: PolyForm Noncommercial 1.0.0" src="https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-red?style=flat-square">
  <img alt="Usage: non-commercial only" src="https://img.shields.io/badge/usage-non--commercial%20only-red?style=flat-square">
  <img alt="Model weights: NC only" src="https://img.shields.io/badge/weights-NC%20only-red?style=flat-square">
  <img alt="Platform: Windows 10/11" src="https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=flat-square">
</p>

<p align="center">
  <a href="docs/MODELS.md">模型与参数</a> ·
  <a href="docs/INSTRUMENTS.md">乐器支持</a> ·
  <a href="docs/MODEL_DOWNLOADS.md">模型下载</a> ·
  <a href="THIRD_PARTY_NOTICES.md">第三方许可</a> ·
  <a href="NOTICE">NOTICE</a>
</p>

---

> **模型使用与 NC（非商用）声明**
>
> 本项目使用 **Demucs、Beat-This、GAME、faster-whisper、Transkun、ADTOF、Basic Pitch、MuScriptor、torchcrepe**。
> **MuScriptor 权重为 CC BY-NC 4.0，ADTOF 权重为 CC BY-NC-SA 4.0；NC = Non-Commercial（非商用）。**
> **本仓库代码为 PolyForm Noncommercial 1.0.0，整体仅限个人、研究、教育等非商业用途；商业使用需另行获得授权。**
> 完整模型清单、出处与权重分发说明见 [模型与许可（必读）](#模型与许可必读) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

music2score 是一个跑在本地的 Web 应用：导入一首歌，自动分离人声/鼓/贝斯/吉他/钢琴/其他，
识别人声旋律与歌词，输出可编辑的多轨 MIDI，并生成 MusicXML、SVG 和 PDF 乐谱。
它把 Demucs、GAME、faster-whisper、Transkun、ADTOF、Basic Pitch、MuScriptor 等开源模型
串成一条可缓存、可回退的管线，面向个人研究与非商业使用。

> **结果是草稿级，不是出版级。** 量化、拍号/调号、声部划分、鼓谱语义、吉他弦位仍需要人工修正；
> 这是当前开源转录模型的共同上限。请只处理你有权处理的音乐。

## 一键下载（普通用户，推荐）

**Windows 10/11：** [下载 `music2score-windows-v0.1.0.zip`（含权重，约 1.59 GB）](https://github.com/bronotop/-musicscore/releases/download/v0.1.0-weights/music2score-windows-v0.1.0.zip)

解压后双击 **`启动音乐扒谱.bat`**。模型权重已包含在压缩包的 `runtime/models/` 中；
首次运行只会自动安装缺失的 Python 依赖（已安装的会跳过），不需要手动下载模型或使用命令行。

> PDF 导出需要额外安装 MuseScore 4；MusicXML 和 SVG 开箱即用。

- Release 页面：[v0.1.0-weights](https://github.com/bronotop/-musicscore/releases/tag/v0.1.0-weights)
- SHA256 与文件大小见 Release 页的 [manifest.json](https://github.com/bronotop/-musicscore/releases/download/v0.1.0-weights/manifest.json)。

## 模型与许可（必读）

**NC = Non-Commercial，非商用。** 本项目及随附权重**不得用于商业产品、商业服务或任何以盈利为目的的用途**。商业授权需单独联系。

| 模型 | 用途 | 许可 | 出处 |
|---|---|---|---|
| **Demucs** `htdemucs_ft` / `htdemucs_6s` | 人声/鼓/贝斯/吉他/钢琴/其他分轨 | 代码 MIT；权重按 Meta 上游条款（研究用途） | <https://github.com/facebookresearch/demucs> |
| **Beat-This** 1.1 | BPM、拍点、downbeat | MIT | <https://github.com/CPJKU/beat_this> |
| **GAME** 1.0.3 | 人声旋律（ONNX） | MIT | <https://github.com/openvpi/GAME> |
| **faster-whisper** + Whisper | 歌词词级时间戳 | MIT | <https://github.com/SYSTRAN/faster-whisper> |
| **Transkun** 2.0 | 钢琴转录 | MIT | <https://github.com/Yujia-Yan/Transkun> |
| **ADTOF-pytorch** | 鼓转录（5 类） | 代码 MIT；**权重 CC BY-NC-SA 4.0（NC，非商用）** | <https://github.com/xavriley/ADTOF-pytorch> |
| **Basic Pitch** 0.4 | 贝斯/吉他/其他复音转录 | Apache-2.0 | <https://github.com/spotify/basic-pitch> |
| **MuScriptor** 0.4 medium | 整曲混音额外乐器（35 西方类） | 代码 MIT；**权重 CC BY-NC 4.0（NC，非商用）** | <https://huggingface.co/MuScriptor/muscriptor-medium> |
| **torchcrepe** / librosa pYIN | 单音 f0 兜底 | MIT / ISC | <https://github.com/maxrmorrison/torchcrepe> |

**权重分发说明：**

- 权重是否随仓库、GitHub Release 或 Git LFS 提供由发布者决定；**无论哪种方式，都必须保留上表的模型名称、出处、许可证和 NC 声明**。
- GitHub 普通 Git 的单文件上限是 100 MB；MuScriptor `model.safetensors` 约 1.23 GB，faster-whisper `model.bin` 约 461 MB，必须使用 **GitHub Release 附件或 Git LFS**，不能直接 `git add`。
- 仓库提供了打包脚本：`powershell -File scripts\package_weights.ps1`，会在 `release-assets/` 生成按模型分组的 zip、`manifest.json` 和 Release 说明，然后按脚本提示执行 `gh release create`。如果权重在别处（例如原来的 `D:\models`），加 `-Source "D:\models"`。
- 如果你 fork 或再分发本项目，不得移除本表、`THIRD_PARTY_NOTICES.md` 和 `LICENSE` 中的署名与 NC 限制。
- 模型权重不属于本仓库代码许可；下载和使用即表示你同意各模型自己的许可条款。

## 功能

- **音源分离**：Demucs `htdemucs_ft`（快速 4 轨）/ `htdemucs_6s + htdemucs_ft` hybrid（质量 6 轨，
  含 guitar/piano）；质量档默认 `shifts=4`、`overlap=0.5`。
- **人声**：GAME 1.0.3 旋律识别 + Basic Pitch/torchcrepe 兜底；faster-whisper 词级歌词时间戳。
- **钢琴**：Transkun V2，自动大谱表与分手。
- **鼓**：ADTOF-pytorch 5 类鼓；无权重时回退 onset + 频谱分类。
- **贝斯/吉他/其他**：Basic Pitch ONNX 复音转录，按音域与复音上限清洗。
- **额外乐器（质量档）**：MuScriptor 整曲混音，35 个西方乐器类；按能量/密度/重复过滤。
- **独奏/单件模式**：跳过 Demucs，从 65 个乐器 profile 中选目标乐器，按其音域/复音/谱号转录。
- **乐谱**：music21 → MusicXML；Verovio SVG + 时间映射；MuseScore 4 CLI PDF；
  支持移调乐器、打击乐谱号、大谱表、分谱导出。
- **Web UI**：项目列表、上传/进度、分轨混音器、钢琴卷帘编辑、乐谱跟随播放、轨道控制台、右键删除项目。
- **CLI**：`doctor` 检查环境，`run` 跑完整管线，支持 `--mode solo --instrument ...`。

## 环境要求

- Windows 10/11
- 首次运行需要联网；完整依赖 + 核心模型约 8 GB 磁盘
- NVIDIA GPU 建议 8GB+ 显存；CPU 也能跑，但质量档会非常慢
- **普通用户不需要预先安装 Node.js**：前端 `frontend/dist` 已包含；Python 3.12 缺失时启动器会尝试用 winget 自动安装

> **平台支持：** 目前官方支持的是一键 **Windows 10/11** 版本。Linux / macOS 可以手动运行
> Python 后端（`python -m uvicorn app.main:app --app-dir backend`），但**没有一键脚本，
> 也未做完整验证**；遇到平台相关问题时请按“实验性支持”看待。

## 快速开始（一键运行）

1. 下载或克隆本仓库，解压到任意目录。
2. 双击 **`启动音乐扒谱.bat`**。
3. 首次运行会自动：
   - 检查 Python 3.12；缺失时尝试用 `winget` 自动安装；
   - 创建 `.venv`，安装 `requirements.txt`（约 5 GB）；
   - 用 `--no-deps` 安装 Basic Pitch（不拉 TensorFlow）；
   - 下载 Demucs / GAME / Whisper small 核心模型（约 1 GB）；
   - 启动服务并打开浏览器。
4. 首次安装可能需要 **10–30 分钟**，请保持启动窗口打开；之后启动只需几秒。

停止服务：关闭启动窗口，或双击 **`停止音乐扒谱.bat`**。

### 可选模型

- **MuScriptor**（额外乐器，35 类）：双击 **`下载MuScriptor模型.bat`**，约 1.2 GB。
  **权重为 CC BY-NC 4.0，仅限非商业使用。**
- 核心模型下载失败时，可双击 **`下载核心模型.bat`** 重试。
- 如果发布者在 GitHub Releases 上传了 `model-weights` 包，也可以下载后解压到
  `runtime/models/`；**MuScriptor / ADTOF 权重仍只限非商业使用**。

### 数据目录

默认数据、模型、缓存都在本目录下的 `runtime/`：

```
runtime/
├─ models/      模型权重
├─ data/projects/  扒谱项目
├─ cache/       阶段缓存
└─ logs/
```

**不会读取其他 music2score 安装的历史项目**；要迁移项目，把旧项目的文件夹复制到
`runtime/data/projects/` 即可。

### 复用已有环境（进阶）

如果本机已经有一套 `.venv` 和模型目录，不想重新安装，可在项目根目录创建
`launch.local.ps1`（已被 `.gitignore` 排除），写入：

```powershell
$env:MUSIC2SCORE_PYTHON = "D:\path\to\.venv\Scripts\python.exe"
$env:MUSIC2SCORE_HOME = "D:\path\to\music2score-home"
```

然后照常双击启动。也可以直接设置同名环境变量。

### GPU 加速（可选）

首次安装会检测 `nvidia-smi`：有 NVIDIA GPU 时自动安装 CUDA 12.8 版 PyTorch；
没有 GPU 或想强制 CPU 时：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Cpu
```

其他 CUDA 版本请先按 [pytorch.org](https://pytorch.org/get-started/locally/) 安装
`torch` / `torchvision` / `torchaudio`，再运行 `setup.ps1 -Cpu`（只跳过自动 CUDA 安装，
不会卸载你已装好的 PyTorch）。

### 手动启动（开发者/非 Windows）

> 普通用户不需要看这一节。前端 `frontend/dist` 已包含在仓库里，只有修改前端源码时才需要 Node.js。

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install --no-deps basic-pitch==0.4.0

# 只有修改前端源码时才需要：
# cd frontend && npm install && npm run build && cd ..

python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

前端开发模式：

```bash
cd frontend
npm run dev
# http://localhost:5173，/api 代理到 127.0.0.1:8010
```

## 使用

1. 上传 MP3/WAV/FLAC/M4A，选择 **快速** 或 **质量** 档。
2. 完整混音选 **整首分离**；只有一件乐器时选 **独奏 / 单一乐器** 并指定乐器。
3. 等待 `ingest → analyze → separate → transcribe → assemble → notate`。
4. 在页面中查看/编辑：
   - **分轨**：试听、静音、音量、下载 stems；
   - **钢琴卷帘**：增删音符、拖动音高/时值、力度、撤销/重做、置信度高亮；
   - **乐谱**：SVG 预览、缩放、跟随播放、点击音符跳转、分谱下载；
   - **轨道**：改配器/显示名、试听、跳转编辑、导出 MIDI/分谱、移除轨道（保留音频）。
5. 导出：
   - `midi/final/full.mid`（type-1，多轨，鼓 channel 9）
   - `midi/final/<track>.mid`（单轨）
   - `score/full.musicxml`、`score/parts/*.musicxml`
   - `score/full.svg-p*.svg`、`score/full.pdf`

### CLI

```powershell
$env:PYTHONPATH = "backend"

# 环境检查
.\.venv\Scripts\python.exe -m app.cli doctor

# 整首
.\.venv\Scripts\python.exe -m app.cli run "$HOME\Music\song.mp3" --preset quality

# 独奏/单件
.\.venv\Scripts\python.exe -m app.cli run "$HOME\Music\erhu.wav" `
  --mode solo --instrument erhu --preset fast
```

## 管线

```
ingest → analyze → separate → transcribe → assemble → notate
```

| 阶段 | 实现 | 说明 |
|---|---|---|
| ingest | ffmpeg（imageio-ffmpeg） | 解码为 44.1 kHz 立体声 WAV |
| analyze | Beat-This + chroma/Krumhansl | BPM、拍点、拍号、调性、节拍网格 |
| separate | audio-separator + Demucs | fast: `htdemucs_ft`；quality: `htdemucs_6s + htdemucs_ft` |
| transcribe | GAME / Transkun / ADTOF / Basic Pitch / MuScriptor | 分轨转录 + 质量档整曲额外乐器 |
| assemble | 量化 + 融合 + pretty_midi | 吸附节拍网格、复音/密度/置信度清洗、生成 `full.mid` |
| notate | music21 + Verovio + MuseScore | MusicXML、SVG、PDF、分谱、移调/谱号 |

阶段带缓存：输入文件 + 参数哈希决定是否跳过；`--force` 可重跑，`--only` 可只跑子集。
Web 任务在独立 worker 进程中运行，API 通过 `job.json` + WebSocket 推送进度。

## 模型细节

模型能力、参数、未启用项和“为什么某个乐器没有独立轨”的说明见
[docs/MODELS.md](docs/MODELS.md) 与 [docs/INSTRUMENTS.md](docs/INSTRUMENTS.md)。
模型清单、出处与 NC 许可的权威版本在本文开头的 [模型与许可（必读）](#模型与许可必读)，
第三方组件汇总见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 目录结构

```
backend/
  app/
    main.py                 FastAPI 入口 + 项目/任务 API
    worker.py               独立转录 worker
    config.py               MUSIC2SCORE_HOME / 模型与数据目录
    instruments/            65 个乐器 profile + 解析注册表
    models/adapters/        各模型适配器（统一 transcribe/separate 接口）
    pipeline/stages/        ingest/analyze/separate/transcribe/assemble/notate
    services/               量化、融合、记谱、音频、钢琴分手
  tests/                    pytest 测试
frontend/
  src/                      React + TypeScript UI
docs/                       模型、乐器、下载、阶段报告
scripts/                    启动、停止、安装、下载、评估脚本
assets/                     icon / preview
```

## 测试

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m pytest
```

测试使用临时 `MUSIC2SCORE_HOME`，不会读写真实模型或项目目录。
前端构建检查：

```powershell
cd frontend
npm run build
```

## 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `MUSIC2SCORE_HOME` | `<repo>/runtime` | 模型、项目、缓存、日志的根目录 |
| `MUSIC2SCORE_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `MUSIC2SCORE_PORT` | `8010` | 启动器首选端口，占用时自动顺延 |
| `MUSESCORE_PATH` | 自动查找 | MuseScore 4 可执行文件 |
| `MUSCRIPTOR_WEIGHTS` | 自动查找 | MuScriptor `model.safetensors` 路径 |
| `ADTOF_WEIGHTS` | 自动查找 | ADTOF 权重路径 |
| `LYRICS_MODEL` | `small` | `tiny/base/small/medium/large-v3` |
| `LYRICS_LANGUAGE` | 自动 | 例如 `zh` / `en` |
| `LYRICS_DEVICE` | `cpu` | `cpu` / `cuda` |

更多模型参数（`DEMUCS_SHIFTS`、`VOCAL_GAME_STEPS`、`MUSCRIPTOR_BEAM_SIZE` 等）见
[docs/MODELS.md](docs/MODELS.md)。

## 已知限制

- 自动乐谱是草稿：量化、拍号/调号、声部划分、鼓谱语义、吉他弦位仍需人工修正。
- Demucs 没有小提琴/大提琴/弦乐 stem；弦乐通常落在 `other`。
- MuScriptor 有 35 个西方类（含小提琴/中提琴/大提琴/低音提琴/弦乐群），
  但类别存在不等于一定输出；整曲推理可能把弦乐段判成管乐/合成铺底。
- ADTOF 只有 5 类鼓，没有 808/909/clap/rim 细分。
- 民族乐器没有专用分离/识别模型，只能做音高草稿 + 用户指定配器。
- MIDI 不含弯音/微分音；简谱/六线谱尚未实现。
- 歌词的 melisma、多音节对齐仍可能出错。

## 许可证与再分发

- **本仓库代码**：PolyForm Noncommercial License 1.0.0，仅限个人、研究、教育等非商业用途。
  商业使用需另行获得许可。完整文本见 [LICENSE](LICENSE)。
- **模型权重不属于本仓库代码许可**。如随仓库、GitHub Release 或 Git LFS 提供，仍按各自许可分发：
  - **MuScriptor 权重：CC BY-NC 4.0（NC，非商用）**；
  - **ADTOF 权重：CC BY-NC-SA 4.0（NC，非商用）**；
  - Demucs / GAME / Transkun / Basic Pitch / Whisper 等见 [模型与许可（必读）](#模型与许可必读)。
- 再分发时必须保留模型名称、出处、许可证和 NC 声明；不得移除 `THIRD_PARTY_NOTICES.md`。
- 第三方组件与许可证汇总见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；完整模型署名见 [NOTICE](NOTICE)。

**为什么代码用 PolyForm Noncommercial，而不是 MIT / CC BY-NC？**

- 本项目定位是个人/研究工具，且 MuScriptor、ADTOF 权重本身是 NC；用 PolyForm NC 可以保持
  “代码 + 权重都不商用”一致。
- **CC BY-NC 4.0 适合文档/内容，不适合软件**；软件的非商用授权用 PolyForm 更合适。
- 如果你希望**代码允许商业使用**，可以把 `LICENSE` 换成 MIT 或 Apache-2.0；但模型权重仍受
  MuScriptor / ADTOF 的 NC 许可限制，商用前必须替换或另行获得授权。

请勿提交测试音频或生成的项目数据；`.gitignore` 已默认排除。模型权重如随仓库提供，请使用 Git LFS 或 GitHub Release，并保留 NC 声明。

## 致谢

Demucs（Meta AI）、GAME（OpenVPI）、faster-whisper、Transkun、ADTOF、
Basic Pitch（Spotify）、MuScriptor、Beat-This、music21、Verovio、MuseScore、
以及所有开源模型与工具的作者。
