# 模型使用与可调参数

本文记录 music2score 实际调用了哪些模型、用了哪些能力、还有哪些能力受模型本身限制。
最后更新：2026-11-14。

> **NC（Non-Commercial，非商用）声明**：MuScriptor 权重为 **CC BY-NC 4.0**，
> ADTOF 权重为 **CC BY-NC-SA 4.0**；本仓库代码为 **PolyForm Noncommercial 1.0.0**。
> 本项目、代码和上述权重均不得用于商业产品/商业服务。再分发时必须保留模型名称、出处、
> 许可证和 NC 声明。完整清单见 [README 的“模型与许可（必读）”](../README.md#模型与许可必读)
> 与 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 1. 模型清单

| 环节 | 模型 | 权重 | 当前用法 | 许可 |
|---|---|---|---|---|
| 音源分离（快速） | Demucs `htdemucs_ft` | 4 × 81 MB | 4 轨：vocals / drums / bass / other | 代码 MIT；权重研究用途 |
| 音源分离（质量） | Demucs `htdemucs_6s` + `htdemucs_ft` | 53 MB + 4 × 81 MB | hybrid：6s 出 guitar/piano，ft 覆盖核心 4 轨 | 代码 MIT；权重研究用途 |
| 节拍/拍号 | Beat-This 1.1.0 `final0` | 78 MB | BPM、拍点、downbeat | MIT |
| 人声旋律 | GAME 1.0.3 medium ONNX | 187 MB | D3PM 边界采样 + pitch estimator | MIT |
| 歌词 | faster-whisper 1.2.1 + Whisper small | 464 MB | 词级时间戳、VAD、语言检测 | MIT |
| 钢琴 | Transkun 2.0.1 | 54 MB | 复音钢琴转录 | MIT |
| 鼓 | ADTOF-pytorch 0.1.0 | 3.5 MB | 5 类鼓 | 代码 MIT；**权重 CC BY-NC-SA 4.0（NC）** |
| 贝斯/吉他/其他 | Basic Pitch 0.4.0 ONNX | 226 KB | 复音音高转录 | Apache-2.0 |
| 音高兜底 | torchcrepe `full` | 85 MB | 单音 f0 | MIT |
| 额外乐器（质量） | MuScriptor 0.4.0 medium | 1.1 GB | 整曲混音 35 类 | 代码 MIT；**权重 CC BY-NC 4.0（NC）** |

模型出处（官方仓库 / 权重页）：

- Demucs：<https://github.com/facebookresearch/demucs>
- Beat-This：<https://github.com/CPJKU/beat_this>
- GAME：<https://github.com/openvpi/GAME>
- faster-whisper：<https://github.com/SYSTRAN/faster-whisper>
- Transkun：<https://github.com/Yujia-Yan/Transkun>
- ADTOF-pytorch：<https://github.com/xavriley/ADTOF-pytorch>
- Basic Pitch：<https://github.com/spotify/basic-pitch>
- MuScriptor：<https://huggingface.co/MuScriptor/muscriptor-medium>
- torchcrepe：<https://github.com/maxrmorrison/torchcrepe>

调性识别是 chroma + Krumhansl 算法，不是神经网络；钢琴分手是启发式。

## 2. 已经用上的模型能力

质量档是“精度优先”：不限制耗时，分离、人声、歌词、MuScriptor 都使用更高参数。

- **Demucs**
  - 质量档使用 **hybrid 分离**：`htdemucs_6s` 提供 guitar/piano，`htdemucs_ft`
    覆盖 vocals/drums/bass/other，避免 6s 的核心轨质量损失。
  - 质量档默认 `shifts=4`、`overlap=0.5`（shift trick 平均多次随机偏移，提升分离质量，
    不考虑耗时）；快速档保持 `shifts=1`、`overlap=0.25`。
  - 可按需调 `segment_size`、`shifts`、`overlap`。
- **GAME**
  - 长音频按窗口切分并拼接，边界采样、presence threshold、语言条件都可调。
  - 与 Basic Pitch + torchcrepe/pyin 做稀疏度/覆盖率门控，避免静音轨塌缩。
- **faster-whisper**
  - `word_timestamps=True`、`vad_filter=True`、`beam_size=5`（快速）/8（质量）、
    `condition_on_previous_text=False`，并支持中英文自动检测。
- **ADTOF**
  - 使用官方 5 类阈值；支持逐类/统一阈值、fps 覆盖。
- **Basic Pitch**
  - ONNX 推理，启用 `melodia_trick`，支持按音域/最短时值/onset/frame 阈值调参。
- **MuScriptor**
  - 质量档整曲混音；支持 beam search、CFG、采样温度、prelude forcing、
    batch size、tempo 检测选项。
- **Transkun**
  - 使用打包的 `2.0.pt`，按 GPU/CPU 自动选设备。

## 3. 没有“榨干”的部分

| 项目 | 现状 | 限制/原因 |
|---|---|---|
| Demucs 分离轨数 | 4/6 轨 | 模型本身没有 violin/cello/strings stem；弦乐只能进 other |
| ADTOF 鼓类 | 5 类 | 没有 808/909/clap/rim 细分；需要 E-GMD/Omnizart 等新模型 |
| MuScriptor 类别 | 35 个西方类（含小提琴/中提琴/大提琴/低音提琴） | 0–33 + drums 共 35 组；没有中国民族乐器、没有 FX；synth bass 合并进 electric bass |
| MuScriptor 实际输出 | 按音色置信度选标签 | 类别存在 ≠ 一定出轨：整曲推理可能把弦乐段判成圆号/巴松/长笛/合成铺底；弱轨还会被重叠/密度/能量过滤 |
| MuScriptor 解码 | 质量档 `beam_size=3`，快速档 1 | 质量档用 3 路 beam 搜索，耗时更高；可继续调大 |
| GAME 采样步数 | 质量档 24 步、60s 窗口/30s hop；快速档 8 步、45s/43s | 质量档用更高步数和 50% 窗口重叠，显著增加人声耗时 |
| Basic Pitch 弯音 | `multiple_pitch_bends=False` | 当前 MIDI/乐谱没有弯音表示，开启后也无处落盘 |
| Transkun 分段 | 使用模型默认 segment size/hop | 未针对超长音频调优 |
| Whisper | small | 更大模型更准，但更慢、占空间 |
| 弦乐/民族乐器 | 无专用模型 | 只能音高草稿 + 配器/手工分轨 |

### MuScriptor 的 35 类完整清单

MuScriptor 的类别 ID 是模型内部的 program group，不能改；下面是 0.4.0 的
`MT3_FULL_PLUS` 全部 35 组（括号内是 GM program 组）：

| ID | 类别 | 中文 | ID | 类别 | 中文 |
|---|---|---|---|---|---|
| 0 | acoustic_piano | 原声钢琴 | 18 | orchestra_hit | 管弦重击 |
| 1 | electric_piano | 电钢琴 | 19 | trumpet | 小号 |
| 2 | chromatic_percussion | 键盘打击乐 | 20 | trombone | 长号 |
| 3 | organ | 风琴 | 21 | tuba | 大号 |
| 4 | acoustic_guitar | 原声吉他 | 22 | french_horn | 圆号 |
| 5 | clean_electric_guitar | 清音电吉他 | 23 | brass_section | 铜管群 |
| 6 | distorted_electric_guitar | 失真电吉他 | 24 | soprano_and_alto_sax | 高音/中音萨克斯 |
| 7 | acoustic_bass | 原声贝斯 | 25 | tenor_sax | 次中音萨克斯 |
| 8 | electric_bass | 电贝斯 | 26 | baritone_sax | 上低音萨克斯 |
| **9** | **violin** | **小提琴** | 27 | oboe | 双簧管 |
| **10** | **viola** | **中提琴** | 28 | english_horn | 英国管 |
| **11** | **cello** | **大提琴** | 29 | bassoon | 巴松 |
| **12** | **contrabass** | **低音提琴** | 30 | clarinet | 单簧管 |
| 13 | orchestral_harp | 竖琴 | 31 | flutes | 长笛 |
| 14 | timpani | 定音鼓 | 32 | synth_lead | 合成主音 |
| **15** | **string_ensemble** | **弦乐群** | 33 | synth_pad | 合成铺底 |
| 16 | synth_strings | 合成弦乐 | 36 | drums | 鼓 |
| 17 | voice | 人声 |  |  |  |

注意：**“类别存在”不等于“每次都会输出”**。MuScriptor 是整曲混音模型，
按音色置信度选择 program group；弦乐音色在密集混音里经常被判成圆号、巴松、
长笛或合成铺底。你的项目日志里如果看到
`muscriptor_mix` 的标签是这些乐器，而不是 violin，就是模型的预测结果，
不是程序把 violin 过滤掉了。

要稳定拿到小提琴轨，按可靠性排序：

1. **独奏模式**选 `violin`：跳过 Demucs，按小提琴音域/单音约束直接转录；
2. 用外部工具先分离出小提琴 stem，在「轨道」页上传并指定 `violin`；
3. 把 `other` 轨的乐器改成 `violin`（音频仍是 `other` stem，音符不重新转录）；
4. 用 `MUSCRIPTOR_STEM_MODE=1` 让 MuScriptor 在吉他/其他 stem 上跑（实验）；
5. 质量档整曲 MuScriptor 只有在模型自己判成 violin 时才会加这条轨。

> 强制让 MuScriptor 只输出弦乐（`instruments=["violin", ...]`）是可行的实验：
> 它会把 `other` 里的和声内容按音域拆成小提琴/中提琴/大提琴/低音提琴四声部。
> 但这是“弦乐改写”，不是可靠的小提琴识别；当前没有设为默认自动轨，避免把
> 合成铺底/管乐误标成弦乐。


## 4. 可调环境变量

### Demucs

- `DEMUCS_SHIFTS`：默认质量 4、快速 1。
- `DEMUCS_OVERLAP`：默认质量 0.5、快速 0.25。
- `DEMUCS_SEGMENT_SIZE`：默认 7.8 秒。

### MuScriptor

- `MUSCRIPTOR_BEAM_SIZE`：质量档默认 3，快速档 1；可继续调大。
- `MUSCRIPTOR_CFG_COEF`：默认 1.0。
- `MUSCRIPTOR_TEMPERATURE`：默认 1.0。
- `MUSCRIPTOR_USE_SAMPLING=1`：改用采样解码。
- `MUSCRIPTOR_PRELUDE_FORCING=0`：关闭 prelude forcing。
- `MUSCRIPTOR_NO_EOS_IS_OK=0`：要求 EOS。
- `MUSCRIPTOR_BATCH_SIZE`：正整数时覆盖 batch size。
- `MUSCRIPTOR_DETECT_TEMPO`：`best-effort` / `1` / `0`。
- `MUSCRIPTOR_STEM_MODE=1`：对吉他/其他启用 MuScriptor 分轨模式（实验）。
- `MUSCRIPTOR_SIZE` / `MUSCRIPTOR_WEIGHTS`：指定模型规格/权重。

### GAME

- `VOCAL_GAME_STEPS`：质量档默认 24，快速档 8。
- `VOCAL_GAME_T0`、`VOCAL_GAME_BOUNDARY_THRESHOLD`、
  `VOCAL_GAME_BOUNDARY_RADIUS`、`VOCAL_GAME_PRESENCE_THRESHOLD`。
- `VOCAL_GAME_WINDOW_SEC`、`VOCAL_GAME_HOP_SEC`。
- `VOCAL_GAME_LANGUAGE`：语言条件。
- `VOCAL_MELODY_MODE=auto/game/heuristic/basic`。

### ADTOF

- `ADTOF_THRESHOLDS=0.2,0.2,0.2,0.2,0.2`：5 类逐类阈值。
- `ADTOF_THRESHOLD`：统一阈值。
- `ADTOF_FPS`：默认 100。

### Transkun

- `TRANSKUN_SEGMENT_SIZE`：覆盖模型默认分段长度（秒）。
- `TRANSKUN_SEGMENT_HOP`：覆盖模型默认分段 hop（秒）。

### 歌词

- `LYRICS_MODEL=small|medium|large-v3`；质量档未指定时会自动选择已安装的最大模型。
- `LYRICS_LANGUAGE=zh|en|...`。
- `LYRICS_DEVICE=cpu|cuda`。
- `LYRICS_BEAM_SIZE`：质量档默认 8，快速档 5。

## 5. MIDI 导出

- `midi/final/full.mid`：type-1 MIDI，含 conductor track（tempo/拍号）与每个
  乐器一条 track；鼓轨使用 channel 9。
- `midi/final/<track>.mid`：单轨 MIDI；换乐器/改名/保存钢琴卷帘后会自动从
  `full.mid` 重新同步 program/name/notes。
- 测试覆盖：`backend/tests/test_midi_export.py`（mido + pretty_midi 解析、
  note-on 存在性、单轨与 full.mid 一致性）。
- 注意：MIDI 不包含弯音/微分音；这些需要后续扩展侧车或自定义导出。

## 6. 建议的下一步

1. 质量档已默认 `MUSCRIPTOR_BEAM_SIZE=3`、`VOCAL_GAME_STEPS=24`；若还想继续换精度，可试 4/32，用
   `scripts/quality_report.py` 对比音符数、复音和耗时，再决定是否设为默认。
2. 电子鼓需要新模型（E-GMD 微调或 Omnizart 13 类）。
3. 弦乐/民族乐器专用模型需要数据工程；当前只能独奏/手工分轨 + 配器。
4. Basic Pitch 弯音若要保留，需要 NoteEvent/MIDI 侧车/记谱三层一起改。
