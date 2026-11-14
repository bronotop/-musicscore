# Phase 0 技术验证报告

日期：2026-10-31
硬件：RTX 4060 Laptop（8 GB 显存）
状态：**通过**。全链路（分离 → 分轨转录 → 量化 → MIDI/MusicXML/SVG）已在 CPU 和 GPU 上跑通，Web 界面可用。

## 1. 验证目标

- 打通「音频 → 分离 → 分轨转录 → 量化 → MIDI/MusicXML/SVG」全链路。
- 确认各模型在本机可运行、显存/速度可接受。
- 找出精度与工程瓶颈，确定 Phase 1 的补强项。

## 2. 测试素材

| 素材 | 时长 | 用途 |
|---|---|---|
| `demucs-test.mp3`（Demucs 官方测试片段） | 20 s | 真实混音，验证分离与端到端 |
| `synth-pop.wav`（合成流行） | 32 s | 有 ground-truth 分轨，验证 6 个声部 |
| `synth-rock.wav`（合成摇滚） | 28 s | 验证鼓/贝斯/吉他/人声 |
| `synth-piano.wav`（合成钢琴） | 24 s | 验证钢琴转录 |

## 3. 环境

- Python 3.12.16（uv venv，`runtime\.venv`）
- **torch 2.9.1+cu128 / torchaudio 2.9.1+cu128 / torchvision 0.24.1+cu128**
- CUDA 可用：NVIDIA GeForce RTX 4060 Laptop，8.0 GB
- audio-separator 0.48.0
- transkun 2.0.1（setuptools 80.10.2 提供 pkg_resources）
- beat-this 1.1.0（权重 77.3 MB，已缓存）
- torchcrepe 0.0.24
- music21 / pretty_midi / librosa / soxr / verovio
- ffmpeg 7.1（imageio-ffmpeg，已暴露到 PATH）
- MuseScore 4 未安装（PDF 跳过，SVG 可用）

## 4. 性能结果

### 4.1 分离

| 模型 | 档位 | 设备 | 20 s 音频耗时 | 峰值显存 | 输出 |
|---|---|---|---|---|---|
| htdemucs_ft（4 模型 bag） | fast | CPU | 31–33 s | — | 4 轨 |
| htdemucs_ft（4 模型 bag） | fast | **GPU** | **7.5 s**（分离 5 s） | **1.29 GB** | 4 轨 |
| htdemucs_6s | quality | CPU | 12.3 s | — | 6 轨 |
| htdemucs_6s | quality | **GPU** | **3.7 s**（分离 2 s） | **0.60 GB** | 6 轨 |

关键修正：

1. `Separator` 必须显式设置 `demucs_params={"segment_size": 7.8, "shifts": 1, "overlap": 0.25}`；默认 `segment_size="Default"` 在 CPU 上慢 40 倍以上。
2. CPU 上必须关闭 `use_autocast`；bfloat16 模拟极慢。GPU 上自动开启。
3. 6-stem 模型使用官方 YAML（audio-separator 会校验并覆盖本地 YAML），权重 `5c90dfd2-34c22ccb.th` 的 MD5/SHA256 已校验。

### 4.2 节拍/调性（Beat-This）

- 20 s 音频：GPU **约 1–3 s**，111.1 BPM，4/4，C# minor，37 beats。
- 权重 77.3 MB，首次下载约 30 s，之后命中缓存。

### 4.3 转录

| 声部 | 模型 | 设备 | 结果 |
|---|---|---|---|
| 钢琴 | Transkun V2 | CPU | 32 s 合成钢琴 **22 s** |
| 钢琴 | Transkun V2 | **GPU** | 32 s 合成钢琴 **8.8 s** |
| 人声/贝斯/吉他 | pitch 兜底（torchcrepe） | CPU | 合成贝斯 25 音；较慢 |
| 贝斯 | pitch 兜底（torchcrepe） | **GPU** | 32 s 合成贝斯 **2.84 s**，峰值 2.6 GB |
| 鼓 | onset + 频谱质心兜底 | CPU | 20 s 真实片段 83–111 音；类别粗 |
| 其他 | pitch 兜底 | GPU | 复音素材会丢和弦 |

### 4.4 端到端（quality 档，6-stem）

| 素材 | 设备 | 总耗时 | 分轨 | 出谱声部 |
|---|---|---|---|---|
| `demucs-test.mp3`（20 s） | GPU | **18.7 s** | 6 | 4（vocals 77、drums 83、guitar 59、piano 71；bass/other 静音） |
| `synth-pop.wav`（32 s） | GPU | **21.9 s** | 6 | **6**（vocals 72、drums 102、bass 26、guitar 75、piano 109、other 54） |
| `synth-rock.wav`（28 s） | GPU | **20.5 s** | 6 | 5（vocals 52、drums 111、guitar 104、piano 45、other 98；bass 分离偏弱） |

同一条真实片段在 fast 档 CPU 上曾为 **108.5 s**；GPU + 6-stem 降到 **18.7 s**，约 5.8 倍加速，且多出 guitar/piano 两个声部。

### 4.5 记谱

- music21 生成 MusicXML（真实片段约 70 KB；合成流行 6 个 part）。
- Verovio 生成 SVG（约 216 KB）。
- MusicXML 可被 music21 重新解析；MuseScore PDF 因未安装而跳过。

### 4.6 Web 端

- FastAPI + 独立 worker 进程：上传 → 后台任务 → `job.json`/WebSocket 进度 → 完成。
- 已用 curl 验证：`/api/health`、`/api/projects`、上传、`/run`、`/job`、文件下载、静态前端托管。
- 前端：React + Vite + TypeScript，含项目列表、上传、进度、分轨同步播放、钢琴卷帘、SVG 乐谱预览、日志。
- `npm run build` 通过。
- **浏览器实测**（浏览器，`http://127.0.0.1:8010`）：
  - 首页、项目列表、GPU 状态卡正常；
  - 项目详情：BPM/调性、阶段进度、导出链接、分轨混音器正常；
  - 钢琴卷帘：成功加载 107 个音符并按轨道着色；
  - 乐谱：SVG 预览 + MusicXML/分谱下载链接正常；
  - 日志：完整管线日志正常显示。

## 5. 当前精度结论

- **可用**：分轨、节拍/BPM/调性、钢琴（独奏/清晰素材）、贝斯单音、人声旋律草稿、多声部 MusicXML 草稿。
- **草稿级**：鼓谱（类别少、无 ghost note/flam）、吉他/other（复音缺失）、自动量化后的乐谱、歌词。
- **缺失**：Basic Pitch、ADTOF、GAME、MuScriptor；Web 钢琴卷帘编辑；歌词对齐。
- 与调研一致：全自动「一键完美乐谱」不现实，产品价值在管线整合与编辑效率。

## 6. Phase 1 补强清单

1. 安装 Basic Pitch（`--no-deps` + TensorFlow 2.20）或使用其 ONNX 模型，替换 pitch 兜底，提升贝斯/吉他复音。
2. 引入 ADTOF（鼓）与 GAME/ROSVOT（人声），提升两类最弱声部。
3. MuScriptor：需 HuggingFace 登录并接受 CC BY-NC 4.0，作为吉他/other 的主模型。
4. 钢琴卷帘编辑、量化参数、置信度高亮、歌词对齐。
5. 用 10 首真实歌曲做人工修正耗时评估；加入 SDR/note-F1 回归。
6. 安装 MuseScore 4，启用 PDF；打包 `start.ps1` 为一键安装包。
7. 可选：ONNX Runtime GPU（MDX 模型加速）、BS-RoFormer 4/6-stem 质量档。

## 7. 复现命令

```powershell
$env:MUSIC2SCORE_HOME = (Join-Path $PWD "runtime")
$env:PYTHONPATH="backend"
.\.venv\Scripts\python.exe -m app.cli doctor
.\.venv\Scripts\python.exe -m app.cli run "runtime\data\test\demucs-test.mp3" --preset quality
```

Web 端：

```powershell
.\start.ps1
# 打开 http://127.0.0.1:8010
```
