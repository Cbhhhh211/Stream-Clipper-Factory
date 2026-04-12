import { useRef, useState } from 'react';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize2,
  Check,
  Square,
  ThumbsUp,
  ThumbsDown,
  Minus,
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';

const FEEDBACK_OPTIONS = [
  { key: 'good', label: '好', icon: ThumbsUp },
  { key: 'average', label: '一般', icon: Minus },
  { key: 'bad', label: '差', icon: ThumbsDown },
];

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export default function ClipPreview() {
  const { state, dispatch } = useAppStore();
  const videoRef = useRef(null);

  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [submittingKey, setSubmittingKey] = useState('');

  const selectedClip = state.highlights.find((h) => h.id === state.selectedClipId);
  const clipUrl = selectedClip?.downloadUrl;

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (videoRef.current.paused) {
      videoRef.current.play();
    } else {
      videoRef.current.pause();
    }
  };

  const submitFeedback = async (clipId, rating, prevRating) => {
    setSubmittingKey(`${clipId}:${rating}`);
    dispatch({ type: 'SET_CLIP_FEEDBACK', payload: { id: clipId, feedback: rating } });
    try {
      await api.submitClipFeedback(clipId, rating);
    } catch {
      dispatch({ type: 'SET_CLIP_FEEDBACK', payload: { id: clipId, feedback: prevRating || null } });
    } finally {
      setSubmittingKey('');
    }
  };

  if (!selectedClip) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 text-text-muted">
        <Play size={36} strokeWidth={1.2} />
        <p className="text-xs font-medium">请选择一个片段进行复核</p>
      </div>
    );
  }

  const scorePercent = Math.round((selectedClip.score || 0) * 100);

  return (
    <div className="flex h-full w-full flex-col gap-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="signal-label">预览</div>
          <div className="mt-1 text-xl font-bold tracking-tight text-text-primary">
            {formatTime(selectedClip.clipStart)} - {formatTime(selectedClip.clipEnd)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge label="评分" value={scorePercent} />
          {selectedClip.contentHook && <Badge label="钩子" value="是" tone="warm" />}
          <button
            onClick={() => dispatch({ type: 'TOGGLE_CLIP', payload: selectedClip.id })}
            className="btn-secondary rounded-lg px-3.5 py-2 text-sm"
          >
            {selectedClip.selected ? <Check size={14} /> : <Square size={14} />}
            {selectedClip.selected ? '已选择' : '选择'}
          </button>
        </div>
      </div>

      <div className="relative min-h-[320px] flex-1 overflow-hidden rounded-xl border border-[var(--color-border)] bg-black/40">
        {clipUrl && (
          <video
            key={clipUrl}
            ref={videoRef}
            src={clipUrl}
            className="absolute inset-0 h-full w-full object-contain"
            onLoadedMetadata={() => setDuration(videoRef.current?.duration || 0)}
            onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime || 0)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            muted={muted}
          />
        )}
      </div>

      <div className="rounded-xl border border-[var(--color-border)] bg-panel-strong p-4">
        {(selectedClip.contentTags?.length > 0 || selectedClip.topKeywords?.length > 0) && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {(selectedClip.contentTags?.length ? selectedClip.contentTags : selectedClip.topKeywords || []).slice(0, 4).map((tag) => (
              <span key={tag} className="rounded-md border border-[var(--color-border)] bg-black/20 px-2 py-0.5 text-[10px] font-medium text-text-secondary">
                {tag}
              </span>
            ))}
          </div>
        )}
        {selectedClip.contentSummary && (
          <p className="mb-4 text-sm leading-6 text-text-secondary">
            {selectedClip.contentSummary}
          </p>
        )}

        <div
          className="h-1.5 cursor-pointer overflow-hidden rounded-full bg-white/5"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            if (!videoRef.current || duration <= 0) return;
            videoRef.current.currentTime = ((e.clientX - rect.left) / rect.width) * duration;
          }}
        >
          <div
            className="h-full rounded-full transition-all duration-200"
            style={{
              width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%`,
              background: 'linear-gradient(90deg, var(--color-accent), var(--color-warm))',
            }}
          />
        </div>

        <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlay}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-white transition-all hover:bg-accent-hover"
            >
              {playing ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" className="ml-0.5" />}
            </button>
            <button
              onClick={() => setMuted(!muted)}
              className="btn-secondary rounded-lg px-3 py-2 text-xs"
            >
              {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
            </button>
            <button
              onClick={() => videoRef.current?.requestFullscreen()}
              className="btn-secondary rounded-lg px-3 py-2 text-xs"
            >
              <Maximize2 size={13} />
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {FEEDBACK_OPTIONS.map((opt) => {
              const active = selectedClip.feedback === opt.key;
              const key = `${selectedClip.id}:${opt.key}`;
              return (
                <button
                  key={opt.key}
                  onClick={() => submitFeedback(selectedClip.id, opt.key, selectedClip.feedback)}
                  disabled={submittingKey === key}
                  className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all ${
                    active
                      ? 'border-accent/25 bg-accent/8 text-accent'
                      : 'border-[var(--color-border)] bg-black/20 text-text-secondary hover:text-text-primary'
                  }`}
                >
                  <span className="inline-flex items-center gap-1.5">
                    <opt.icon size={12} />
                    {opt.label}
                  </span>
                </button>
              );
            })}
            <span className="rounded-lg border border-[var(--color-border)] bg-black/20 px-2.5 py-1.5 text-xs font-mono text-text-muted">
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Badge({ label, value, tone = 'accent' }) {
  const toneClass = tone === 'warm'
    ? 'border-warm/15 bg-warm/6 text-warm'
    : 'border-accent/15 bg-accent/6 text-accent';

  return (
    <div className={`rounded-lg border px-2.5 py-1.5 ${toneClass}`}>
      <span className="text-[10px] font-medium text-current/60">{label}</span>
      <span className="ml-1.5 text-xs font-bold text-current">{value}</span>
    </div>
  );
}
