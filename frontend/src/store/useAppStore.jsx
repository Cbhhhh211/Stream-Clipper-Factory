/* eslint-disable react-refresh/only-export-components */
/**
 * Global application state using React context + useReducer.
 *
 * Phases: "import" → "processing" → "review" → "export"
 */

import { createContext, useContext, useReducer } from 'react';

function absolutizeApiRelativeUrl(value) {
  if (typeof value !== 'string' || !value.startsWith('/')) return value;
  if (typeof window === 'undefined') return value;

  const desktopBase = window.streamClipperDesktop?.apiBase;
  const envBase = import.meta?.env?.VITE_API_BASE;
  const base = (typeof desktopBase === 'string' && desktopBase.trim())
    ? desktopBase.trim()
    : (typeof envBase === 'string' && envBase.trim() ? envBase.trim() : '');

  if (!base || !/^https?:\/\//i.test(base)) return value;

  try {
    return new URL(value, base).toString();
  } catch {
    return value;
  }
}

const initialState = {
  // Current UI phase
  phase: 'import', // 'import' | 'processing' | 'review' | 'export'

  // Source
  source: null, // { type: 'local'|'bili_vod'|'bili_live'|'web_vod'|'web_live', file?, url?, name? }

  // Job
  jobId: null,
  jobStatus: null,
  progress: 0,
  currentStage: null,
  logs: [],

  // Results
  highlights: [],       // [{ id, clipStart, clipEnd, peakTime, score, danmakuCount, topKeywords, selected }]
  selectedClipId: null,
  videoUrl: null,        // presigned URL or local object URL
  videoDuration: 0,

  // Export
  exportFormat: '16:9',  // '16:9' | '9:16' | '1:1'
  exportPlatform: null,  // 'bilibili' | 'tiktok' | 'youtube_shorts'
};

function reducer(state, action) {
  switch (action.type) {
    case 'SET_PHASE':
      return { ...state, phase: action.payload };

    case 'SET_SOURCE':
      return { ...state, source: action.payload };

    case 'START_JOB':
      return {
        ...state,
        phase: 'processing',
        jobId: action.payload.jobId,
        jobStatus: 'queued',
        progress: 0,
        currentStage: null,
        logs: [],
      };

    case 'UPDATE_PROGRESS':
      return {
        ...state,
        progress: action.payload.progress,
        currentStage: action.payload.stage,
        jobStatus: 'processing',
      };

    case 'ADD_LOG':
      return {
        ...state,
        logs: [...state.logs.slice(-200), action.payload],
      };

    case 'JOB_COMPLETED':
      {
        const mappedHighlights = action.payload.highlights.map((h, i) => ({
          id: h.id || `clip-${i}`,
          clipStart: h.clip_start,
          clipEnd: h.clip_end,
          aiClipStart: h.ai_clip_start ?? h.clip_start,
          aiClipEnd: h.ai_clip_end ?? h.clip_end,
          peakTime: h.peak_time,
          score: h.highlight_score || h.score || 0,
          rankScore: h.rank_score ?? (h.highlight_score || h.score || 0),
          semanticScore: h.semantic_score ?? null,
          contentSummary: h.content_summary || h.transcript || '',
          contentTags: h.content_tags || [],
          contentHook: Boolean(h.content_hook),
          danmakuCount: h.danmaku_count || 0,
          topKeywords: h.top_keywords || [],
          fileName: h.file_name || null,
          downloadUrl: absolutizeApiRelativeUrl(h.download_url),
          thumbnailUrl: absolutizeApiRelativeUrl(h.thumbnail_url),
          feedback: h.feedback || null,
          adjustments: h.adjustments || 0,
          rankingSource: h.ranking_source || 'resonance',
          selected: true,
        }));
      return {
        ...state,
        phase: 'review',
        jobStatus: 'completed',
        progress: 1,
        highlights: mappedHighlights,
        selectedClipId: mappedHighlights[0]?.id || null,
        videoUrl: action.payload.videoUrl,
        videoDuration: action.payload.duration || 0,
      };
      }

    case 'JOB_FAILED':
      return {
        ...state,
        jobStatus: 'failed',
        logs: [...state.logs, { level: 'error', text: action.payload }],
      };

    case 'SELECT_CLIP':
      return { ...state, selectedClipId: action.payload };

    case 'TOGGLE_CLIP':
      return {
        ...state,
        highlights: state.highlights.map(h =>
          h.id === action.payload ? { ...h, selected: !h.selected } : h
        ),
      };

    case 'UPDATE_CLIP_BOUNDS':
      return {
        ...state,
        highlights: state.highlights.map(h =>
          h.id === action.payload.id
            ? { ...h, clipStart: action.payload.clipStart, clipEnd: action.payload.clipEnd }
            : h
        ),
      };

    case 'MERGE_CLIPS': {
      const [idA, idB] = action.payload;
      const a = state.highlights.find(h => h.id === idA);
      const b = state.highlights.find(h => h.id === idB);
      if (!a || !b) return state;
      const merged = {
        ...a,
        clipStart: Math.min(a.clipStart, b.clipStart),
        clipEnd: Math.max(a.clipEnd, b.clipEnd),
        score: Math.max(a.score, b.score),
        danmakuCount: a.danmakuCount + b.danmakuCount,
      };
      return {
        ...state,
        highlights: state.highlights
          .filter(h => h.id !== idB)
          .map(h => h.id === idA ? merged : h),
        selectedClipId: idA,
      };
    }

    case 'SPLIT_CLIP': {
      const { id, splitTime } = action.payload;
      const clip = state.highlights.find(h => h.id === id);
      if (!clip || splitTime <= clip.clipStart || splitTime >= clip.clipEnd) return state;

      const idx = state.highlights.findIndex(h => h.id === id);
      const clipA = { ...clip, clipEnd: splitTime };
      const clipB = {
        ...clip,
        id: `clip-split-${Date.now()}`,
        clipStart: splitTime,
        score: clip.score * 0.8,
      };
      const newHighlights = [...state.highlights];
      newHighlights.splice(idx, 1, clipA, clipB);
      return { ...state, highlights: newHighlights };
    }

    case 'REORDER_CLIPS':
      return { ...state, highlights: action.payload };

    case 'SET_CLIP_FEEDBACK':
      return {
        ...state,
        highlights: state.highlights.map(h =>
          h.id === action.payload.id ? { ...h, feedback: action.payload.feedback } : h
        ),
      };

    case 'SYNC_CLIP_FROM_API':
      return {
        ...state,
        highlights: state.highlights.map((h) => {
          if (h.id !== action.payload.id) return h;
          return {
            ...h,
            clipStart: action.payload.clip_start ?? h.clipStart,
            clipEnd: action.payload.clip_end ?? h.clipEnd,
            duration: action.payload.duration ?? (h.clipEnd - h.clipStart),
            fileName: action.payload.file_name ?? h.fileName ?? null,
            downloadUrl: action.payload.download_url
              ? absolutizeApiRelativeUrl(action.payload.download_url)
              : h.downloadUrl,
            aiClipStart: action.payload.ai_clip_start ?? h.aiClipStart,
            aiClipEnd: action.payload.ai_clip_end ?? h.aiClipEnd,
            adjustments: action.payload.adjustments ?? h.adjustments ?? 0,
            contentSummary: action.payload.content_summary ?? action.payload.transcript ?? h.contentSummary,
            contentTags: action.payload.content_tags ?? h.contentTags ?? [],
            semanticScore: action.payload.semantic_score ?? h.semanticScore ?? null,
            contentHook: action.payload.content_hook ?? h.contentHook ?? false,
            thumbnailUrl: action.payload.thumbnail_url
              ? absolutizeApiRelativeUrl(action.payload.thumbnail_url)
              : h.thumbnailUrl,
          };
        }),
      };

    case 'SET_EXPORT_FORMAT':
      return { ...state, exportFormat: action.payload };

    case 'SET_EXPORT_PLATFORM':
      return { ...state, exportPlatform: action.payload, phase: 'export' };

    case 'KEEP_ONLY_SELECTED_CLIPS': {
      const kept = state.highlights.filter((h) => h.selected);
      const selectedClipStillExists = kept.some((h) => h.id === state.selectedClipId);
      return {
        ...state,
        highlights: kept,
        selectedClipId: selectedClipStillExists ? state.selectedClipId : (kept[0]?.id || null),
      };
    }

    case 'RESET':
      return { ...initialState };

    default:
      return state;
  }
}

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  return (
    <AppContext.Provider value={{ state, dispatch }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppStore() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useAppStore 必须在 AppProvider 内使用');
  return ctx;
}
