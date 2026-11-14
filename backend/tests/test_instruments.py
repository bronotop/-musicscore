from __future__ import annotations

from app.instruments import REGISTRY


def test_catalog_has_core_and_extra_instruments():
    ids = {profile.id for profile in REGISTRY.all()}
    assert {"vocals", "piano", "drums", "bass", "guitar", "other"} <= ids
    assert {"erhu", "guzheng", "pipa", "dizi", "sitar", "koto", "synth_lead"} <= ids
    assert len(REGISTRY) >= 50


def test_resolve_english_chinese_and_muscriptor_labels():
    assert REGISTRY.resolve("Erhu").id == "erhu"
    assert REGISTRY.resolve("二胡").id == "erhu"
    assert REGISTRY.resolve("muscriptor_baritone sax").id == "baritone_sax"
    assert REGISTRY.resolve("synth pad").id == "synth_pad"
    assert REGISTRY.resolve("viola").clef == "alto"
    assert REGISTRY.resolve("violoncello").id == "cello"  # conservative substring match


def test_resolve_program_and_unknown_label():
    assert REGISTRY.resolve(None, 110).id == "erhu"
    assert REGISTRY.resolve("program_99", 99).id == "program_99"
    assert REGISTRY.resolve("program_99", 99).name_en == "Other (program 99)"
    unknown = REGISTRY.resolve("something weird", 99, default=True)
    assert unknown.source == "unknown"
    assert unknown.gm_program == 99
    assert unknown.clef == "treble"


def test_profiles_carry_notation_metadata():
    trumpet = REGISTRY.resolve("trumpet")
    assert trumpet is not None and trumpet.transpose == 2
    cello = REGISTRY.resolve("cello")
    assert cello is not None and cello.clef == "bass"
    guitar = REGISTRY.resolve("guitar")
    assert guitar is not None and guitar.clef == "treble8vb"
    synth = REGISTRY.resolve("synth_bass")
    assert synth is not None and synth.monophonic
