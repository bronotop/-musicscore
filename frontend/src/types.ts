export interface ProjectSummary {
  project_id: string;
  title: string;
  source: string;
  created_at: string;
  status: string;
  progress: number;
}

export interface TrackInfo {
  stem: string;
  program: number;
  is_drum: boolean;
  notes: number;
  instrument_id?: string;
  display_name?: string;
  source?: string;
  clef?: string;
  transpose?: number;
  midi?: string;
  audio?: string | null;
  confidence?: number;
  model?: string;
}

export interface InstrumentProfile {
  id: string;
  name_en: string;
  name_zh: string;
  display_name: string;
  family: string;
  gm_program: number;
  range: [number, number];
  clef: string;
  transpose: number;
  notation: string;
  aliases?: string[];
  models?: string[];
  max_polyphony?: number;
  monophonic?: boolean;
  source?: string;
}

export interface JobState {
  status: string;
  stage?: string | null;
  index?: number;
  total?: number;
  progress?: number;
  message?: string;
  updated_at?: string;
  started_at?: string;
  finished_at?: string;
  cached?: boolean;
  summary?: Record<string, any>;
}

export interface Analysis {
  bpm?: number;
  key?: string;
  time_signature?: string;
  beats?: number[];
  downbeats?: number[];
  beat_source?: string;
}

export interface ProjectDetail {
  project: {
    project_id: string;
    title: string;
    original_filename: string;
    preset: string;
    created_at: string;
    mode?: string;
    instrument_id?: string | null;
    manual_stems?: string[];
  };
  job: JobState;
  analysis: Analysis;
  run: any;
  tracks: TrackInfo[];
  stems: string[];
  manual_stems?: string[];
  files: string[];
  source_audio?: string;
}

export interface DoctorInfo {
  home: string;
  python: string;
  free_space_gb: number;
  ffmpeg: string;
  musescore: string;
  packages: Record<string, boolean>;
  torch: string | null;
  cuda: boolean;
  gpu: string | null;
  muscriptor_weights?: string;
  lyrics_model?: string;
  game_model?: string;
}
