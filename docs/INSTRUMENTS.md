# 乐器支持与“其他乐器”使用说明

## 1. 现在支持什么

### 核心六轨（自动分离 + 专用/通用模型）

| 声部 | 模型 | 说明 |
|---|---|---|
| 人声 | GAME 1.0.3 ONNX → Basic Pitch + f0 旋律线 | 支持歌词 |
| 钢琴 | Transkun V2 | 大谱表、自适应分手 |
| 鼓 | ADTOF-pytorch | 5 类鼓（kick/snare/hi-hat/tom/cymbal） |
| 贝斯 | Basic Pitch → pitch | 单音 |
| 吉他 | Basic Pitch → pitch | 普通五线谱（暂无六线谱） |
| 其他 | Basic Pitch → pitch | 复音兜底，不分类 |

### 额外乐器（quality 档 MuScriptor 整首混音）

MuScriptor 0.4.0 只有 35 个西方 GM/MT3 类：

- 键盘：piano、electric piano、chromatic percussion、organ（含手风琴/口琴）
- 吉他/贝斯：acoustic/clean/distorted guitar、acoustic/electric bass
- 弦乐：violin、viola、cello、contrabass、harp、string ensemble、synth strings
- 管乐：trumpet、trombone、tuba、french horn、brass section、saxes、oboe、english horn、bassoon、clarinet、flutes
- 合成器：`synth_lead`、`synth_pad`、`synth_strings`
- 人声/鼓：voice、drums

**没有** erhu、guzheng、pipa、dizi、sheng、suona、yangqin、sitar、koto、shamisen、tabla、oud 等民族乐器类；synth bass 被合并到 electric bass；没有 FX 类；电子鼓只有通用 drum 类。

## 2. 导入的音乐里有“其他乐器”会怎样

1. 完整混音先过 Demucs 6 轨；民族乐器/合成器通常落在 `other`，或在分离时泄漏到相近声部。
2. quality 档会用 MuScriptor 整首混音再找额外声部：
   - 属于 35 个西方类的 → 可能生成独立轨（如 flute/trumpet/synth pad）。
   - 不属于的 → 可能被误判成相近类，或落成 `program_N` / `Other`。
   - 稀疏、低能量、与核心轨重复的额外轨会被过滤。
3. 记谱层会使用乐器注册表里的英文名/谱号/移调；未知类显示 `Other (program N)`，不会伪造民族乐器名称。
4. **民族乐器在完整混音里没有可靠分离/识别模型**；这是模型能力边界，不是参数问题。

### 为什么小提琴常常没有独立轨？

- Demucs 6 轨分离里没有弦乐 stem，小提琴的音频会先进入 `other`，也可能泄漏到
  `guitar`/`piano`。
- MuScriptor 的 35 个类别里确实有 `violin`、`viola`、`cello`、`contrabass`、
  `string_ensemble`、`synth_strings`，但它是在**整首混音**上按音色分类，不是
  “先分离小提琴再识别”。
- 流行/电子编曲里的弦乐经常是合成弦乐或铺底音色，容易被判成 `synth_pad`/
  `synth_lead`；太轻、太稀疏或与核心轨重复的额外轨会被过滤，`program_N` 则显示为
  `Other (program N)`。
- 补救：在“轨道”页把 `other`/`synth_pad`/`synth_lead` 改配器为小提琴或弦乐群；
  需要可靠音高时，用独奏模式或手工上传小提琴分轨重新转录。

## 3. 推荐做法

### A. 独奏/单件乐器录音（最可靠）

上传时选择“独奏 / 单一乐器”，再选乐器（如二胡、古筝、笛子、合成主音）：

- 跳过 Demucs，直接把原音频当作该乐器的 stem。
- 按注册表音域/复音/单音属性转录：
  - 单音乐器：pitch/torchcrepe 旋律线；
  - 复音乐器：Basic Pitch + 音域/复音过滤；
  - 打击乐：ADTOF。
- 谱号/移调/声部名来自注册表。

CLI：

```powershell
$env:MUSIC2SCORE_HOME = (Join-Path $PWD "runtime")
$env:PYTHONPATH="backend"
.\.venv\Scripts\python.exe -m app.cli run "erhu.wav" `
  --mode solo --instrument erhu --preset fast
```

### B. 完整混音里已知有某件乐器

1. 先按完整混音跑完。
2. 在“轨道”页找到 `Other` 或未知轨，改配器为实际乐器（如 Guzheng）。
3. 改完只重跑记谱；音高仍是 `other` 的通用转录结果，不会变成专用民族模型。
4. 如果手里有该乐器的单独分轨，用“上传分轨”指定乐器，会重新转录该轨并并入总谱。

### C. 合成电音

- `synth lead/pad/strings` 会作为额外轨保留。
- synth bass 走 bass 轨 + Basic Pitch；可在轨道页改配器为 Synth Bass。
- FX 是非音高事件，不应当成音符轨；当前会跳过 `notation=none` 的 FX。

## 4. 乐器注册表

`backend/app/instruments/catalog.yaml` 是唯一数据源，字段：

- `id`、`name_en`、`name_zh`、`aliases`
- `family`、`gm_program`、`range`、`max_polyphony`、`monophonic`
- `clef`（treble/bass/alto/percussion/treble8vb/bass8vb/grand）
- `transpose`（实音→写谱半音数，降 B 小号=+2）
- `notation`（staff/percussion/none）
- `models`（偏好模型，元数据）

加新乐器只需在 YAML 增加 profile；UI 下拉、轨元数据、谱号/移调会自动使用。民族类乐器（二胡等）目前是“音高草稿”配置，不代表已有专用识别模型。

## 5. 测试素材与评估

```powershell
.\.venv\Scripts\python.exe scripts\make_instrument_fixtures.py `
  --out runtime\data\fixtures

.\.venv\Scripts\python.exe scripts\eval_instruments.py `
  --fixtures runtime\data\fixtures `
  --project runtime\data\projects\solo-erhu --instrument erhu
```

当前合成素材结果：二胡 7/7 音（F1 1.0）、合成主音 F1 0.8、古筝 recall 0.75（复音泛音导致 precision 偏低）。这些是管线回归，不是真实录音精度承诺。

## 6. 已知限制

- 没有公开的、音符级标注的民族乐器音频数据集；短期不能训练出可靠专用模型。
- 完整混音中的民族乐器无法可靠分离；优先独奏/手工分轨。
- 12-TET：微分音、滑音、揉弦只能近似；暂无六线谱/简谱。
- 电子鼓 808/909/clap/rim 需要新的鼓模型（ADTOF 只有 5 类）；当前可改配器/编辑音符，但不能自动识别细分音色。
- 非商用权重（MuScriptor/ADTOF 等）仅个人/研究使用。
