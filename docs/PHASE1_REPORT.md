# Phase 1 报告：模型补强

日期：2026-10-31
硬件：RTX 4060 Laptop（8 GB 显存）
状态：MuScriptor、ADTOF、Basic Pitch（ONNX）、GAME 人声旋律（ONNX）、歌词、
乐器注册表/独奏模式/轨管理、大谱表、鼓谱与编辑器增量优化已接入；
专用民族乐器模型 / 和弦识别仍待完成。

## 1. 本阶段完成内容

### 1.1 MuScriptor（整首混音多乐器转录）

- 安装 `muscriptor==0.4.0` 到项目 venv（Python 3.12）。
- 权重：`muscriptor-medium`（307M 参数，1,228,144,472 字节）放在
  `runtime\models\muscriptor\muscriptor-medium\`，附 `config.json`
  （dim 1024 / heads 16 / layers 24 / card 1395）。
- 适配器 `backend/app/models/adapters/muscriptor.py`：
  - 自动查找本地权重，支持 `MUSCRIPTOR_WEIGHTS` / `MUSCRIPTOR_SIZE`；
  - 缺 `config.json` 时自动补写；
  - 进程内缓存模型，避免每个声部重复加载；
  - 用 `ExportOptions(quantize=True)` 输出 MIDI；
  - 分轨模式可通过 `MUSCRIPTOR_STEM_MODE=1` 打开（默认关闭，因为分轨输入不稳定）。
- **正确用法：整首混音转录**。quality 档会额外跑一次 MuScriptor 整首混音，
  将其识别出的非核心乐器（铜管/木管/弦乐/合成器等）作为额外声部合并进总谱。
  核心声部（人声/鼓/贝斯/吉他/钢琴）仍由专业分轨模型负责，避免重复。

实测（20 s 真实片段）：

| 项目 | 结果 |
|---|---|
| MuScriptor 整首混音 | 295 个音符，生成耗时约 45 s |
| 额外声部 | trumpet 3、french horn 11、tenor sax 8、baritone sax 56、bassoon 78、synth pad 31 |
| 最终总谱 | **10 个声部**，576 个音符，8 页 SVG |
| 峰值显存 | 约 2.3 GB |

实测（32 s 合成流行）：

| 项目 | 结果 |
|---|---|
| 分轨模式（吉他约束） | 174 音（约束成功时）；约束失败时回退“无约束 + 音域过滤” 43 音 |
| 分轨模式（other） | 0–85 音，**不稳定**；低于 10 音时回退 pitch |
| 整首混音 | 约 23–28 s，输出多乐器 MIDI |

结论：MuScriptor 在整首混音上明显更可靠；分轨输入会出现“0 音符/乐器误判”，
因此默认只把它用于整首混音融合，分轨仍走专业模型。

### 1.2 ADTOF（鼓转录）

- 使用 `xavriley/ADTOF-pytorch`（只依赖 torch/librosa/pretty_midi），
  clone 到 `runtime\vendor\ADTOF-pytorch`，权重 3.6 MB 随仓库提供。
- 以 editable 方式安装 `adtof-pytorch==0.1.0`（`--no-deps`）。
- 输出音高已经是 GM：35（kick）、38（snare）、47（tom）、42（hi-hat）、49（crash）。
- 实测：
  - 32 s 合成鼓：**0.93 s**，153 音，峰值显存 0.08 GB；
  - 20 s 真实片段：184 音（原来 onset 兜底为 83–111 音）。
- 保留原 onset 兜底，ADTOF 不可用时自动回退。

### 1.3 融合后的 quality 管线

真实片段（20 s，6-stem 分离 + 分轨转录 + MuScriptor 整首混音）：

| 声部 | 模型 | 音符 |
|---|---|---|
| vocals | pitch 兜底 | 75 |
| drums | ADTOF-pytorch | 184 |
| guitar | pitch 兜底 | 59 |
| piano | Transkun | 71 |
| trumpet | MuScriptor（整首混音） | 3 |
| french horn | MuScriptor | 11 |
| tenor sax | MuScriptor | 8 |
| baritone sax | MuScriptor | 56 |
| bassoon | MuScriptor | 78 |
| synth pad | MuScriptor | 31 |

- 总音符：576
- 总谱：10 个 MusicXML part，8 页 SVG
- 转录阶段：60.7 s（其中 MuScriptor 约 45 s）；assemble 0.05 s；notate 1.8 s

合成流行（32 s）：

- 6 条分轨、6 个声部（vocals 69、drums 153、bass 25、guitar 75、piano 107、other 49）
- 整首混音 MuScriptor 有时会再补充额外声部；若其输出为 0 则自动跳过。
- 2026-11-07 重跑（Basic Pitch ONNX 已启用）：vocals 72、drums 153、
  bass 58、guitar 120、piano 105、other 121；置信度 0.24–1.0，
  可用于卷帘低置信高亮。
- 2026-11-07 人声旋律增强：GAME-1.0.3-medium ONNX（MIT）已接入；
  `VOCAL_MELODY_MODE=auto` 在 GAME 结果过稀时回退 Basic Pitch + torchcrepe
  旋律线选择。synth-pop-adtof 基线（协调者口径）72 音/最大复音 3/重叠 5.6%/
  置信度 0.53/F#2–C5；新路径 36 音/复音 1/重叠 0%/置信度 0.554/A3–D5，
  <100 ms 碎片 27→6（同一复音口径复测）；f0 有声帧覆盖 55.9%→51.8%，
  说明主要旋律轮廓保留。demucs 人声轨本身近静音（峰值 0.002），仅验证
  回退路径（17 音/复音 1）。

### 1.5 PDF 乐谱

- 使用你下载的官方 `MuseScore-Studio-4.7.6.261022093-x86_64.msi`
  （128.8 MB），通过 `msiexec /a` 解压到
  `runtime\vendor\MuseScore4`，**未修改系统、无需管理员权限**。
- `find_musescore()` 自动识别该路径；MuseScore 4.7.6 CLI 可用。
- `render_pdf()` 增加 `-f`（force），否则 CLI 可能直接失败。
- 实测：
  - 6 声部项目：**6 页 / 93 KB**，`pdf_mode=full`；
  - 10 声部项目：**9 页 / 122 KB 全谱**，111.11 BPM、4/4，
    10 个声部（Voice、Drum Kit、Acoustic Guitar、Piano、Trumpet、French Horn、
    Tenor Sax、Baritone Sax、Bassoon、Synth Pad），`pdf_mode=full`；
  - 根因：MuseScore 4.7.6 在 music21 **首次序列化**的 10 声部 MusicXML 上崩溃
    （0xC0000005）；将 MusicXML 重新解析并重写（normalize）后即可正常渲染。
- 同时按乐器修正谱号（鼓=Percussion、吉他=Treble 8vb、巴松/贝斯=Bass 等）
  和声部名称（Voice、Drum Kit、Trumpet 等）。
- 回退链：**归一化 MusicXML 全谱 → MIDI 导入全谱 → 分谱合并**；
  前两级都能出全谱，分谱合并只作为极端兜底。
- MIDI 导入回退可能使用 MuseScore 自己的速度/拍号解释；
  归一化路径保留 111.11 BPM / 4/4。

### 1.6 钢琴卷帘编辑

已从只读预览升级为可编辑画布：

- 选轨：按 vocals/drums/bass/guitar/piano/other/muscriptor_* 切换。
- 视窗：`−/+` 缩放、滑杆横向滚动、滚轮滚动、Ctrl+滚轮缩放。
- 编辑：
  - 双击空白添加音符（默认 1/16 时值）；
  - 拖动音符移动时间/音高；
  - 拖右边缘改时值；
  - Delete/Backspace 删除选中音符；
  - 显示选中音符的 MIDI/起始/时值。
- 保存：`PUT /api/projects/{id}/midi/final/full.mid` 写入编辑后的 MIDI，
  重建 `tracks.json`，再 `POST /api/projects/{id}/render` 以 `--only notate`
  重跑记谱；WebSocket 常驻，进度与完成后详情刷新无需重新选项目。
- 乐谱预览用 `job.updated_at` 做缓存失效，重绘后自动刷新 SVG。

实测（32 s 合成流行）：

- 在 vocals 轨双击添加 MIDI 53、5.74 s、0.16 s 的音符；
- 保存后 `notes=479`、vocals `70`，乐谱重新生成；
- 通过 API 恢复原始 MIDI 后回到 `478` / vocals `69`；
- 前后端 build 与 18 项单元测试通过。

编辑器的已知限制：暂无框选、编辑光标与乐谱小节的逐拍同步；
力度/多选/撤销栈/置信度高亮已在 1.7 中补齐。

### 1.7 增量优化（2026-11-07）

- **钢琴大谱表**：`_expand_piano_grand_staff()` 将钢琴拆成上下两个
  `PartStaff`，导出为单个 MusicXML 声部（`<staves>2</staves>`），
  MuseScore 自动绘制大括号；分谱也只生成一个钢琴文件。
- **鼓谱可读性**：解析 MIDI 时保留 GM 鼓音高（否则 music21 会把所有鼓
  折叠成同一位置），再映射为打击乐记谱：kick=F4、snare=C5、
  hi-hat=G5、crash=A5，镲片使用 x/三角/菱形符头，鼓谱号固定。
- **MuScriptor 额外声部过滤**：按音符数/密度/能量丢弃噪声声部，
  与核心声部或彼此重复度 ≥70% 的声部去重，同名声部合并；
  铜管/木管等单音乐器每个起音只保留一个音，超长音符截到 4 拍。
- **钢琴卷帘**：力度滑杆（多选批量）、Shift 多选、Ctrl+A 全选、
  方向键微调、`[`/`]` 改时值、80 步撤销/重做栈（Ctrl+Z/Y）、
  `midi/final/confidence.json` 低置信高亮（蓝/橙/红）。
- **乐谱跟随播放**：Verovio 生成 `full.timemap.json`，前端内嵌全部 SVG
  页面，播放原曲 `source.wav` 时高亮当前音符并自动滚动。
- **歌词**：faster-whisper（`models/faster-whisper/small`）词级转写，
  `midi/model/vocals.lyrics.json` 侧车；记谱时按时间重叠写入
  MusicXML `<lyric>`，中文按字分配到重叠音符。
- 新增测试覆盖大谱表、鼓谱、歌词、MuScriptor 过滤；
  32 s 合成流行实测：8 声部、10 页全谱、卷帘 76 音符；
  英文/中文 TTS 人声实测：15 个词/字按时间写入 MusicXML 并正常渲染。
- 仍未完成：ROSVOT 对比、更细的换气/多语种音素对齐、和弦识别、框选与逐拍光标同步。

### 1.8 质量增量（2026-11-07 第二轮）

- **模型融合/置信度过滤**（`backend/app/services/fusion.py`）：量化前按乐器
  过滤低置信短碎片、同音/八度重复、局部密度和复音上限；MuScriptor 只作
  同音证据加权，不重新加入核心乐器。支持 `M2S_FUSION_*` 环境变量。
  synth-pop 实测：总音符 629→548，vocals 复音 3→1、bass 2→1、
  guitar 7→4、other 5→4；置信度均值上升，piano/drums 保持不变。
- **歌词 melisma/音节**：`_apply_lyrics` 改为按绝对时间槽对齐；英文用
  `pyphen` 拆音节并写 `syllabic=begin/middle/end`，拆不出时首音符写词、
  后续留空；中文/日文按字分配；多词不再挤在同一音符。
  英文 TTS 实测 `transcription` 正确拆成 `tran-scrip-tion`。
- **钢琴自适应分手**：`piano_hands.choose_split_pitch()` 在音域明显双峰时
  自动选分界（保守限制 48–72，否则回退中央 C）；demucs 钢琴实测分界
  从 60 调到 53，谱面更符合低音伴奏。
- **鼓谱**：新增 GM 60–81 打击乐映射；velocity ≤40 的音符加 ghost note 括号。
- **GAME 接入后的最终 synth-pop**：总音符 629→528；vocals 72→36
  （复音 3→1，GAME 稀疏回退 Basic Pitch+melody），bass 58→31、
  guitar 120→94、other 121→109；piano 105、drums 153 不变。
  demucs 项目最终 564 音（旧基线缺少 Basic Pitch 的 bass/other，不可直接对比），
  9 页全谱。
- 测试：62 项通过（vocals 16、fusion 11、lyrics 7、piano 4、drum ghost 1，
  其余为原有/集成测试）。

### 1.9 其他乐器 Phase 1（乐器注册表/独奏/轨管理）

- **乐器注册表**：`backend/app/instruments/catalog.yaml` + `registry.py`，65 个
  profile；包含核心 6 类、MuScriptor Western 类、二胡/古筝/琵琶/笛/箫/笙/
  唢呐/扬琴/古琴/西塔尔/日本筝/三味线/塔布拉/乌德等民族类，以及
  synth lead/pad/bass、电子鼓、FX。字段含中英文名、别名、GM program、音域、
  复音/单音、谱号、移调、记谱类型和偏好模型。
- **独奏模式**：上传时选择“独奏 / 单一乐器”；`separate` 跳过 Demucs，
  直接复制原音频为对应 stem；`solo.py` 按 profile 路由：
  - 单音乐器：pitch/torchcrepe；
  - 复音乐器：Basic Pitch + 音域/复音过滤；
  - 打击乐：ADTOF。
  CLI：`--mode solo --instrument erhu`。
- **动态轨/手工分轨**：`transcribe` 扫描 `stems/*.wav`，`assemble` 扫描
  `midi/model/*.mid`；任何注册表乐器都可成为独立轨。额外轨写独立
  `midi/final/<track>.mid`，`tracks.json` 增加 `instrument_id`、`display_name`、
  `source`、`midi`、`clef`、`transpose`。
- **合成器/电音**：MuScriptor `synth_lead/pad/strings` 通过注册表映射；
  synth bass 可把 bass 轨改配器为 Synth Bass；FX（`notation=none`）跳过，
  不写成音高。
- **记谱**：`notation.py` 用注册表输出声部名、谱号（treble/bass/alto/
  percussion/treble8vb/bass8vb/grand）和移调；钢琴/大谱表逻辑泛化；
  未知 program 显示 `Other (program N)`。
- **API/UI**：`GET /api/instruments`；`PATCH /tracks/{index}` 改配器/改名/删除；
  `POST /stems` 上传手工分轨；UploadPanel 支持独奏模式；新增“轨道”页。
- **验证**：合成二胡素材 7/7 音（F1 1.0）、合成主音 F1 0.8、古筝 recall 0.75
  （泛音导致 precision 偏低）；手工上传 erhu+guzheng 生成 2 声部；
  110 项测试通过，前端 build 通过。
- **边界**：MuScriptor 无民族类，民族乐器只是“音高草稿 + 用户指定配器”；
  完整混音中的民族乐器没有可靠分离；电子鼓细分音色、六线谱/简谱/微分音
  仍需后续模型/导出器。

## 2. 工程改动

- `backend/app/models/adapters/muscriptor.py`：新适配器。
- `backend/app/models/adapters/drums.py`：ADTOF-pytorch 优先，原 onset 兜底。
- `backend/app/models/adapters/general.py`：MuScriptor 分轨模式改为显式开关；
  吉他“约束失败 → 无约束 + 音域过滤”；“other”低音符数回退。
- `backend/app/pipeline/stages/transcribe.py`：quality 档增加整首混音 MuScriptor 转录。
- `backend/app/pipeline/stages/assemble.py`：过滤 MuScriptor 核心乐器族，
  将其余乐器作为额外声部加入 `full.mid` / `tracks.json` / 总谱；
  新增能量/密度/重复度过滤、单音乐器去和弦、超长音符截断。
- `backend/app/models/adapters/lyrics.py`：faster-whisper 词级歌词适配器。
- `backend/app/models/adapters/game.py`：GAME 1.0.3 ONNX 适配器（D3PM 边界采样、
  峰值归一化、长音频窗口拼接）。
- `backend/app/models/adapters/melody.py`：torchcrepe/pyin f0 引导的旋律线选择、
  单音化、颤音/碎片合并与最短时值/最大跳进门限。
- `backend/app/models/adapters/vocals.py`：`VOCAL_MELODY_MODE=auto/game/heuristic/basic`
  与 GAME→heuristic 失败/稀疏回退。
- `scripts/download_game.py`：GAME 权重下载与 SHA-256 校验脚本。
- `backend/app/services/fusion.py`：置信度/复音/密度/八度重复融合。
- `backend/app/services/piano_hands.py`：钢琴自适应分手。
- `scripts/quality_report.py`：音符数/复音/置信度/歌词/页数对比报告。
- `backend/app/instruments/{catalog.yaml,registry.py}`：65 个乐器 profile 与解析。
- `backend/app/models/adapters/solo.py`：独奏/单乐器 profile 路由。
- `backend/app/pipeline/stages/separate.py`：solo 模式跳过分离、复制源音频。
- `backend/app/pipeline/stages/transcribe.py`：动态 stems、solo/extra 路由。
- `backend/app/pipeline/stages/assemble.py`：动态 model MIDI、每轨 MIDI 与
  `tracks.json` 元数据（instrument_id/display_name/source/midi/clef/transpose）。
- `backend/app/services/fusion.py`：注册表 profile → FusionProfile。
- `scripts/make_instrument_fixtures.py`、`scripts/eval_instruments.py`：独奏
  二胡/古筝/合成器测试素材与音高 F1 评估。
- `backend/app/services/notation.py`：大谱表、GM 鼓谱映射、歌词写入、
  超长音符保护、SVG timemap 输出、分谱合组导出。
- `backend/app/pipeline/stages/transcribe.py`：歌词侧车与置信度侧车。
- `backend/app/pipeline/stages/notate.py`：读取歌词、输出 timemap。
- `doctor` 与 Web UI 增加 MuScriptor 权重、ADTOF、歌词模型状态。
- `backend/app/main.py`：新增 MIDI 保存、重绘、原曲播放接口，WebSocket 常驻。
- `frontend/src/components/PianoRoll.tsx`：可编辑钢琴卷帘（撤销栈/多选/力度/置信度）。
- `frontend/src/components/ScoreView.tsx`：内嵌 SVG + 播放跟随高亮。
- `scripts/fetch_muscriptor_mirror.py`：代理 + 多线程分块下载镜像权重。
- `README.md`、`models/DOWNLOAD_THESE.md` 更新。

## 3. 已知问题

1. MuScriptor 分轨输入不稳定：同一输入可能输出 0 音或不同乐器组合。
   默认走整首混音；分轨模式仅作实验开关。
2. MuScriptor 的乐器分类在低质量素材上可能误判（如把伴奏识别成 bassoon/french horn）。
   已加入能量/密度/重复过滤与单音乐器去和弦；极端素材仍可能残留少量错误声部。
3. 权重来自非 gated 镜像 `BEDO97/muscriptor-medium`。本地 SHA256：
   `06b4b2def88a2833978c1b74030b100bc35fc2cc718c3b2001bda6c164c4ab31`
   （官方 LFS 哈希未获取到，建议后续用官方 gated 仓库复核）。
4. Basic Pitch 已通过 ONNX 运行（`pip install --no-deps basic-pitch`），
   不依赖 TensorFlow；贝斯/吉他优先使用它，失败再回退 pitch。
5. 歌词已用 faster-whisper 做词级对齐，并支持英文 pyphen 音节（syllabic）
   与中文按字分配；更细的换气/多语种音素对齐、ROSVOT 对比仍未接入。
6. MuseScore 4.7.6 已解压并启用 PDF；10 声部首次 MusicXML 序列化会触发
   MuseScore 崩溃，已通过 normalize 修复，输出 9 页全谱。
   分谱合集/MIDI 导入仅作为极端兜底。
7. 钢琴已拆为大谱表并支持自适应分手；鼓谱已按 GM 映射、扩展 GM 60–81、
   低力度 ghost note 括号；记谱已按注册表输出中提琴/大提琴/吉他等谱号与
   降 B/降 E 移调；钢琴卷帘已支持力度、多选、撤销栈和置信度高亮；
   播放时乐谱跟随已可用，但编辑光标尚未逐拍同步。
8. 人声 GAME 权重为 `GAME-1.0.3-medium-onnx`（MIT，OpenVPI），位于
   `runtime\models\game\GAME-1.0.3-medium-onnx\`；ONNX Runtime CPU
   推理 32 s 约 8–12 s，PyTorch 参考实现 32 s 峰值显存约 430 MB。当前
   venv 的 onnxruntime 为 CPU 版；安装 onnxruntime-gpu 后适配器会自动尝试
   CUDA provider。
9. `transcribe`/`assemble` 的缓存参数已包含模式、乐器、动态 stems 和
   `VOCAL_MELODY_MODE`；切换模式会自动失效，不需要手动清 cache。
10. 乐器注册表/独奏模式/轨管理已接入，但 MuScriptor 没有民族乐器类别；
    民族乐器只能做“音高草稿 + 用户指定配器”，完整混音中的民族乐器没有
    可靠分离；电子鼓 808/909/clap/rim 细分、六线谱/简谱/微分音仍待后续
    模型或自定义导出器。

## 4. 复现

```powershell
$env:MUSIC2SCORE_HOME = (Join-Path $PWD "runtime")
$env:PYTHONPATH="backend"

# 检查
.\.venv\Scripts\python.exe -m app.cli doctor

# 完整 quality（6-stem + 分轨 + MuScriptor 整首混音）
.\.venv\Scripts\python.exe -m app.cli run "歌曲.mp3" --preset quality

# 只重跑转录/合并/记谱（分轨已存在时）
.\.venv\Scripts\python.exe -m app.cli run "歌曲.mp3" --preset quality `
  --project-id <id> --only transcribe,assemble,notate --force
```
