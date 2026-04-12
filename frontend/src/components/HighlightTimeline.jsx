import { useRef, useState, useCallback, useEffect } from 'react';
import { Scissors, GitMerge, ZoomIn, ZoomOut } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';

export default function HighlightTimeline() {
  const { state, dispatch } = useAppStore();
  const containerRef = useRef(null);
  const rafRef = useRef(null);
  const latestMouseEventRef = useRef(null);
  const saveTimerRef = useRef(null);
  const saveAbortRef = useRef(null);
  const draftBoundsRef = useRef({});

  const [zoom, setZoom] = useState(1);
  const [dragging, setDragging] = useState(null);
  const [draftBounds, setDraftBounds] = useState({});
  const [savingClipId, setSavingClipId] = useState('');
  const [saveError, setSaveError] = useState('');

  const duration = state.videoDuration || estimateDuration(state.highlights);
  const pxPerSecond = zoom * 2;
  const totalWidth = Math.max(duration * pxPerSecond, 600);
  const maxDanmaku = Math.max(1, ...state.highlights.map((h) => h.danmakuCount));

  const formatTime = (s) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  const pxToTime = useCallback(
    (px) => Math.max(0, Math.min(duration, px / pxPerSecond)),
    [duration, pxPerSecond]
  );

  useEffect(() => {
    draftBoundsRef.current = draftBounds;
  }, [draftBounds]);

  useEffect(() => {
    setDraftBounds((prev) => {
      const ids = new Set(state.highlights.map((h) => h.id));
      const next = {};
      Object.entries(prev).forEach(([id, bounds]) => {
        if (ids.has(id)) {
          next[id] = bounds;
        }
      });
      return next;
    });
  }, [state.highlights]);

  const applyDragFromMouseEvent = useCallback((mouseEvent, dragState) => {
    if (!mouseEvent || !dragState || !containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const scrollOffset = containerRef.current.scrollLeft;
    const x = mouseEvent.clientX - rect.left + scrollOffset;
    const time = pxToTime(x);

    const clip = state.highlights.find((h) => h.id === dragState.clipId);
    if (!clip) return;
    const draft = draftBoundsRef.current[dragState.clipId];
    const currentStart = draft?.clipStart ?? clip.clipStart;
    const currentEnd = draft?.clipEnd ?? clip.clipEnd;

    if (dragState.edge === 'start') {
      const nextStart = Math.max(0, Math.min(time, currentEnd - 2));
      if (Math.abs(nextStart - currentStart) > 0.03) {
        setDraftBounds((prev) => ({
          ...prev,
          [dragState.clipId]: { clipStart: nextStart, clipEnd: currentEnd },
        }));
      }
      return;
    }

    const nextEnd = Math.min(duration, Math.max(time, currentStart + 2));
    if (Math.abs(nextEnd - currentEnd) > 0.03) {
      setDraftBounds((prev) => ({
        ...prev,
        [dragState.clipId]: { clipStart: currentStart, clipEnd: nextEnd },
      }));
    }
  }, [duration, pxToTime, state.highlights]);

  const performSave = useCallback(async (payload) => {
    setSavingClipId(payload.clipId);
    setSaveError('');

    if (saveAbortRef.current) {
      saveAbortRef.current.abort();
    }

    const controller = new AbortController();
    saveAbortRef.current = controller;

    try {
      const res = await api.adjustClip(
        payload.clipId,
        payload.clipStart,
        payload.clipEnd,
        '',
        { signal: controller.signal, fastPreview: true }
      );
      if (res?.clip) {
        dispatch({ type: 'SYNC_CLIP_FROM_API', payload: { id: payload.clipId, ...res.clip } });
      }
      if (res?.warning) {
        dispatch({ type: 'ADD_LOG', payload: { level: 'warning', text: res.warning } });
      }
    } catch (err) {
      if (err?.name !== 'AbortError') {
        dispatch({
          type: 'UPDATE_CLIP_BOUNDS',
          payload: {
            id: payload.clipId,
            clipStart: payload.originStart,
            clipEnd: payload.originEnd,
          },
        });
        const message = err?.message || '保存片段调整失败';
        setSaveError(message);
        dispatch({ type: 'ADD_LOG', payload: { level: 'error', text: message } });
      }
    } finally {
      setSavingClipId('');
    }
  }, [dispatch]);

  const scheduleSave = useCallback((payload) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => performSave(payload), 220);
  }, [performSave]);

  const handleMouseDown = useCallback((e, clipId, edge) => {
    e.preventDefault();
    e.stopPropagation();
    const clip = state.highlights.find((h) => h.id === clipId);
    if (!clip) return;

    setSaveError('');
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setDragging({ clipId, edge, originStart: clip.clipStart, originEnd: clip.clipEnd });
  }, [state.highlights]);

  const handleMouseMove = useCallback((e) => {
    if (!dragging) return;

    latestMouseEventRef.current = e;
    if (rafRef.current) return;

    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      applyDragFromMouseEvent(latestMouseEventRef.current, dragging);
    });
  }, [applyDragFromMouseEvent, dragging]);

  const handleMouseUp = useCallback(() => {
    if (!dragging) return;

    const drag = dragging;
    setDragging(null);

    const draft = draftBoundsRef.current[drag.clipId];
    const finalStart = draft?.clipStart ?? drag.originStart;
    const finalEnd = draft?.clipEnd ?? drag.originEnd;

    setDraftBounds((prev) => {
      if (!(drag.clipId in prev)) return prev;
      const next = { ...prev };
      delete next[drag.clipId];
      return next;
    });

    const changed =
      Math.abs(finalStart - drag.originStart) > 0.05
      || Math.abs(finalEnd - drag.originEnd) > 0.05;

    if (!changed) return;

    dispatch({
      type: 'UPDATE_CLIP_BOUNDS',
      payload: { id: drag.clipId, clipStart: finalStart, clipEnd: finalEnd },
    });

    scheduleSave({
      clipId: drag.clipId,
      clipStart: finalStart,
      clipEnd: finalEnd,
      originStart: drag.originStart,
      originEnd: drag.originEnd,
    });
  }, [dispatch, dragging, scheduleSave]);

  useEffect(() => {
    if (!dragging) return undefined;

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [dragging, handleMouseMove, handleMouseUp]);

  useEffect(() => () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    if (saveAbortRef.current) saveAbortRef.current.abort();
  }, []);

  const handleSplit = () => {
    const clip = state.highlights.find((h) => h.id === state.selectedClipId);
    if (!clip) return;
    dispatch({ type: 'SPLIT_CLIP', payload: { id: clip.id, splitTime: (clip.clipStart + clip.clipEnd) / 2 } });
  };

  const handleMerge = () => {
    const idx = state.highlights.findIndex((h) => h.id === state.selectedClipId);
    if (idx < 0 || idx >= state.highlights.length - 1) return;
    dispatch({ type: 'MERGE_CLIPS', payload: [state.highlights[idx].id, state.highlights[idx + 1].id] });
  };

  return (
    <div className="flex w-full flex-col">
      <div className="mb-4 flex items-center justify-between gap-3 border-b border-[var(--color-border)] pb-3">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="panel-accent">
            <span className="text-xs font-semibold text-text-primary">时间轴</span>
          </div>
          <button
            onClick={handleSplit}
            disabled={!state.selectedClipId}
            className="timeline-btn"
          >
            <Scissors size={12} />
            拆分
          </button>
          <button
            onClick={handleMerge}
            disabled={!state.selectedClipId}
            className="timeline-btn"
          >
            <GitMerge size={12} />
            合并
          </button>
          {savingClipId && <span className="text-xs text-warm animate-pulse">保存中...</span>}
        </div>

        <div className="flex items-center gap-1 rounded-lg border border-[var(--color-border)] bg-panel-strong px-2 py-1">
          <button
            onClick={() => setZoom((z) => Math.max(0.5, z - 0.5))}
            className="cursor-pointer rounded p-1 text-text-muted transition-colors hover:bg-white/5 hover:text-text-primary"
          >
            <ZoomOut size={13} />
          </button>
          <span className="w-8 text-center text-xs font-mono text-text-secondary">{zoom}x</span>
          <button
            onClick={() => setZoom((z) => Math.min(10, z + 0.5))}
            className="cursor-pointer rounded p-1 text-text-muted transition-colors hover:bg-white/5 hover:text-text-primary"
          >
            <ZoomIn size={13} />
          </button>
        </div>
      </div>

      <div ref={containerRef} className="scrollbar-hide relative h-[260px] overflow-x-auto overflow-y-hidden rounded-xl border border-[var(--color-border)] bg-black/25">
        <div className="relative h-full" style={{ width: totalWidth }}>
          <div className="absolute inset-0 border-b border-[var(--color-border)]">
            {Array.from({ length: Math.ceil(duration / timeStep(zoom)) }, (_, i) => {
              const t = i * timeStep(zoom);
              return (
                <div key={i} className="absolute top-2 flex flex-col items-center" style={{ left: t * pxPerSecond }}>
                  <div className="mb-1 h-2 w-px bg-white/8" />
                  <span className="select-none text-[10px] font-mono text-text-muted">{formatTime(t)}</span>
                </div>
              );
            })}
          </div>

          <div className="pointer-events-none absolute top-10 bottom-0 left-0 right-0 opacity-40">
            {state.highlights.map((clip) => {
              const density = clip.danmakuCount / maxDanmaku;
              return (
                <div
                  key={`density-${clip.id}`}
                  className="absolute bottom-0"
                  style={{ left: clip.clipStart * pxPerSecond, width: (clip.clipEnd - clip.clipStart) * pxPerSecond }}
                >
                  <div
                    className="w-full rounded-t-sm"
                    style={{
                      height: `${Math.max(10, density * 100)}%`,
                      background: density > 0.6 ? 'var(--color-warm)' : 'rgba(124, 109, 238, 0.25)',
                    }}
                  />
                </div>
              );
            })}
          </div>

          <div className="absolute top-10 bottom-0 left-0 right-0">
            {state.highlights.map((clip) => {
              const bounds = draftBounds[clip.id] || { clipStart: clip.clipStart, clipEnd: clip.clipEnd };
              const left = bounds.clipStart * pxPerSecond;
              const width = (bounds.clipEnd - bounds.clipStart) * pxPerSecond;
              const isSelected = clip.id === state.selectedClipId;

              return (
                <div
                  key={`region-${clip.id}`}
                  className={`absolute top-2 bottom-2 transition-all cursor-pointer rounded-lg border group ${
                    isSelected
                        ? 'z-20 border-warm/30 bg-warm/8'
                        : 'border-[var(--color-border)] bg-panel-strong/80 hover:bg-bg-hover'
                  }`}
                  style={{ left, width: Math.max(width, 24) }}
                  onClick={() => dispatch({ type: 'SELECT_CLIP', payload: clip.id })}
                >
                  <div className={`absolute inset-x-3 top-1.5 truncate text-[9px] font-mono ${isSelected ? 'text-warm' : 'text-text-muted'}`}>
                    {Math.round(clip.score * 100)}分
                  </div>

                  <div
                    className="absolute left-0 top-0 bottom-0 w-3 cursor-col-resize z-30 flex items-center justify-center"
                    onMouseDown={(e) => handleMouseDown(e, clip.id, 'start')}
                  >
                    <div className={`h-8 w-[2px] rounded-full transition-all ${isSelected ? 'bg-warm' : 'bg-white/20'}`} />
                  </div>

                  <div
                    className="absolute right-0 top-0 bottom-0 w-3 cursor-col-resize z-30 flex items-center justify-center"
                    onMouseDown={(e) => handleMouseDown(e, clip.id, 'end')}
                  >
                    <div className={`h-8 w-[2px] rounded-full transition-all ${isSelected ? 'bg-warm' : 'bg-white/20'}`} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {saveError && (
        <div className="mt-3 text-xs text-danger">{saveError}</div>
      )}
    </div>
  );
}

function estimateDuration(highlights) {
  if (highlights.length === 0) return 300;
  return Math.max(...highlights.map((h) => h.clipEnd)) * 1.1;
}

function timeStep(zoom) {
  if (zoom >= 5) return 5;
  if (zoom >= 2) return 10;
  if (zoom >= 1) return 30;
  return 60;
}
