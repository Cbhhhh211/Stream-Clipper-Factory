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
        <Play size={40} strokeWidth={1.2} />
        <p className="text-xs font-semibold uppercase tracking-[0.16em]">请选择一个片段进行复核</p>
      </div>
    );
  }

  const scorePercent = Math.round((selectedClip.score || 0) * 100);

  return (
    <div className="flex h-full w-full flex-col gap-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">预览</div>
          <div className="mt-1 text-2xl font-extrabold tracking-[-0.04em] text-text-primary">
            {formatTime(selectedClip.clipStart)} - {formatTime(selectedClip.clipEnd)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge label="评分" value={scorePercent} />
          {selectedClip.contentHook && <Badge label="钩子" value="是" tone="warm" />}
          <button
            onClick={() => dispatch({ type: 'TOGGLE_CLIP', payload: selectedClip.id })}
            className="btn-secondary rounded-full px-4 py-2.5 text-sm"
          >
            {selectedClip.selected ? <Check size={14} /> : <Square size={14} />}
            {selectedClip.selected ? '已选择' : '选择'}
          </button>
        </div>
      </div>

      <div className="relative min-h-[320px] flex-1 overflow-hidden rounded-[22px] border border-white/8 bg-[#12263c]">
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

      <div className="rounded-[22px] border border-white/8 bg-[#12283e] p-4">
        {(selectedClip.contentTags?.length > 0 || selectedClip.topKeywords?.length > 0) && (
          <div className="mb-3 flex flex-wrap gap-2">
            {(selectedClip.contentTags?.length ? selectedClip.contentTags : selectedClip.topKeywords || []).slice(0, 4).map((tag) => (
              <span key={tag} className="rounded-full border border-white/8 bg-[#1a314a] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary">
                {tag}
              </span>
            ))}
          </div>
        )}
        {selectedClip.contentSummary && (
          <p className="mb-4 text-sm leading-7 text-text-secondary">
            {selectedClip.contentSummary}
          </p>
        )}

        <div
          className="h-2 cursor-pointer overflow-hidden rounded-full bg-[#20364f]"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            if (!videoRef.current || duration <= 0) return;
            videoRef.current.currentTime = ((e.clientX - rect.left) / rect.width) * duration;
          }}
        >
          <div
            className="h-full rounded-full bg-[linear-gradient(90deg,#7faed2_0%,#d2a163_100%)] transition-all duration-200"
            style={{ width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%` }}
          />
        </div>

        <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlay}
              className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-white"
            >
              {playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" className="ml-0.5" />}
            </button>
            <button
              onClick={() => setMuted(!muted)}
              className="btn-secondary rounded-full px-3 py-2 text-xs"
            >
              {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              {muted ? '静音' : '声音'}
            </button>
            <button
              onClick={() => videoRef.current?.requestFullscreen()}
              className="btn-secondary rounded-full px-3 py-2 text-xs"
            >
              <Maximize2 size={14} />
              全屏
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {FEEDBACK_OPTIONS.map((opt) => {
              const active = selectedClip.feedback === opt.key;
              const key = `${selectedClip.id}:${opt.key}`;
              return (
                <button
                  key={opt.key}
                  onClick={() => submitFeedback(selectedClip.id, opt.key, selectedClip.feedback)}
                  disabled={submittingKey === key}
                  className={`rounded-full border px-3 py-2 text-xs font-semibold ${
                    active
                      ? 'border-accent/45 bg-accent/10 text-accent'
                      : 'border-white/8 bg-[#1a314a] text-text-secondary'
                  }`}
                >
                  <span className="inline-flex items-center gap-1.5">
                    <opt.icon size={13} />
                    {opt.label}
                  </span>
                </button>
              );
            })}
            <span className="rounded-full border border-white/8 bg-[#1a314a] px-3 py-2 text-xs font-mono text-text-secondary">
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
    ? 'border-warm/25 bg-warm/10 text-warm'
    : 'border-accent/25 bg-accent/10 text-accent';

  return (
    <div className={`rounded-full border px-3 py-2 ${toneClass}`}>
      <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-current/70">{label}</span>
      <span className="ml-2 text-xs font-bold text-current">{value}</span>
    </div>
  );
}
