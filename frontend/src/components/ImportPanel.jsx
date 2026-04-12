import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Upload,
  Link,
  Radio,
  ArrowRight,
  Film,
  CircleHelp,
  FolderOpen,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Zap,
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';
import Toggle from './Toggle';

const TABS = [
  { id: 'upload', icon: Upload, label: '本地上传' },
  { id: 'url', icon: Link, label: '在线视频' },
  { id: 'live', icon: Radio, label: '直播录制' },
];

const PARAM_HINT = '大多数场景下，30-60 秒是更实用的默认片段长度，便于复核和导出。';

export default function ImportPanel() {
  const { dispatch } = useAppStore();

  const [activeTab, setActiveTab] = useState('upload');
  const [dragOver, setDragOver] = useState(false);
  const [url, setUrl] = useState('');
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState('');

  const [topN, setTopN] = useState(() => localStorage.getItem('top_n') || '10');
  const [clipDuration, setClipDuration] = useState(() => localStorage.getItem('clip_duration') || '45');
  const [liveDuration, setLiveDuration] = useState(() => localStorage.getItem('live_duration') || '1800');
  const [outputDir, setOutputDir] = useState(() => localStorage.getItem('output_dir') || '');
  const [speedBoost, setSpeedBoost] = useState(() => localStorage.getItem('speed_boost') !== '0');
  const [selectingDir, setSelectingDir] = useState(false);

  const [urlFocused, setUrlFocused] = useState(false);
  const [urlStatus, setUrlStatus] = useState('idle');
  const [urlPreview, setUrlPreview] = useState(null);

  const fileInputRef = useRef(null);

  const handleFile = useCallback((nextFile) => {
    if (nextFile && nextFile.type.startsWith('video/')) {
      setFile(nextFile);
      setError('');
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files[0]);
  }, [handleFile]);

  useEffect(() => {
    if (activeTab === 'upload') {
      setUrlStatus('idle');
      setUrlPreview(null);
      return undefined;
    }

    const trimmed = url.trim();
    if (!trimmed) {
      setUrlStatus('idle');
      setUrlPreview(null);
      return undefined;
    }

    const isValid = activeTab === 'live' ? isLikelyLiveInput(trimmed) : isLikelyVodInput(trimmed);
    if (!isValid) {
      setUrlStatus('invalid');
      setUrlPreview(null);
      return undefined;
    }

    const controller = new AbortController();
    setUrlStatus('loading');

    const timer = setTimeout(async () => {
      try {
        if (activeTab === 'url') {
          const preview = isBilibiliVodInput(trimmed)
            ? await fetchVodPreview(trimmed, controller.signal)
            : buildGenericPreview(trimmed, 'vod');
          setUrlPreview(preview);
          setUrlStatus('valid');
        } else {
          const preview = isBilibiliLiveInput(trimmed)
            ? await fetchLivePreview(trimmed, controller.signal)
            : buildGenericPreview(trimmed, 'live');
          setUrlPreview(preview);
          setUrlStatus('valid');
        }
      } catch {
        if (activeTab === 'url') {
          setUrlPreview(buildGenericPreview(trimmed, 'vod'));
          setUrlStatus('valid');
        } else {
          setUrlPreview(buildGenericPreview(trimmed, 'live'));
          setUrlStatus('valid');
        }
      }
    }, 360);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [activeTab, url]);

  const handleStart = async () => {
    setError('');

    const parsedTopN = Number.parseInt(topN, 10);
    const parsedClipDuration = Number.parseFloat(clipDuration);
    const parsedLiveDuration = Number.parseInt(liveDuration, 10);

    if (!Number.isFinite(parsedTopN) || parsedTopN < 1 || parsedTopN > 50) {
      setError('片段数量必须在 1 到 50 之间。');
      return;
    }

    if (!Number.isFinite(parsedClipDuration) || parsedClipDuration < 5 || parsedClipDuration > 3600) {
      setError('片段时长必须在 5 到 3600 秒之间。');
      return;
    }

    if (
      activeTab === 'live'
      && (!Number.isFinite(parsedLiveDuration) || parsedLiveDuration < 30 || parsedLiveDuration > 43200)
    ) {
      setError('直播录制时长必须在 30 到 43200 秒之间。');
      return;
    }

    if (activeTab !== 'upload' && urlStatus === 'invalid') {
      setError('链接格式无效，请检查后重试。');
      return;
    }

    const options = {
      topN: parsedTopN,
      clipDuration: parsedClipDuration,
      modelSize: 'tiny',
    };

    if (speedBoost) {
      options.candidateMultiplier = 1;
      options.feedbackRank = false;
      options.boundaryAdaptation = false;
      options.adaptivePadding = false;
      options.llmRerank = false;
    } else {
      options.candidateMultiplier = 2;
      options.feedbackRank = true;
      options.boundaryAdaptation = true;
      options.adaptivePadding = true;
      options.llmRerank = false;
    }

    if (activeTab === 'live') {
      options.duration = parsedLiveDuration;
    }
    if (outputDir.trim()) {
      options.outputDir = outputDir.trim();
    }

    if (activeTab === 'upload' && file) {
      setUploading(true);
      try {
        const job = await api.createLocalJob(file, options, setUploadProgress);
        dispatch({ type: 'START_JOB', payload: { jobId: job.job_id } });
      } catch (err) {
        setError(err?.message || '上传失败');
      } finally {
        setUploading(false);
      }
      return;
    }

    if (!url.trim()) return;

    setSubmitting(true);
    try {
      const sourceType = resolveSourceType(activeTab, url.trim());
      const job = await api.createJob(sourceType, url.trim(), options);
      if (!job?.job_id) throw new Error('未返回 job_id');
      dispatch({ type: 'START_JOB', payload: { jobId: job.job_id } });
    } catch (err) {
      const detail = String(err?.detail || err?.message || '');
      if (
        detail.includes('source_type')
        && detail.includes('bili_vod')
        && detail.includes('bili_live')
        && !detail.includes('web_vod')
        && (detail.includes('400') || detail.startsWith('source_type'))
      ) {
        setError('后端仍在运行旧版 API，请重启后端以启用网页视频/网页直播来源（web_vod / web_live）。');
      } else {
        setError(err?.message || '任务创建失败');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const canStart = (activeTab === 'upload' && file) || (activeTab !== 'upload' && url.trim() && urlStatus !== 'invalid');

  const handlePickOutputDir = async () => {
    setError('');
    setSelectingDir(true);
    try {
      const res = await api.pickOutputDirectory(outputDir.trim());
      const selected = typeof res?.selected === 'string' ? res.selected : '';
      if (selected) {
        setOutputDir(selected);
        localStorage.setItem('output_dir', selected);
      }
    } catch (err) {
      setError(err?.message || '无法打开文件夹选择器');
    } finally {
      setSelectingDir(false);
    }
  };

  return (
    <div className="min-h-full w-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto flex w-full max-w-[1380px] flex-col gap-4">

        {/* Hero */}
        <section className="surface-panel overflow-hidden px-6 py-6 md:px-10 md:py-8">
          <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_240px] xl:items-center">
            <div>
              <div className="mb-3 flex items-center gap-2.5">
                <div className="h-1.5 w-1.5 rounded-full bg-accent" />
                <span className="signal-label">新建项目</span>
              </div>
              <h1 className="signal-heading max-w-xl text-4xl md:text-5xl">
                从文件、视频<br className="hidden md:block" />或直播
                <span className="text-accent"> 开始剪辑</span>
              </h1>
              <p className="mt-4 max-w-lg text-sm leading-7 text-text-secondary">
                选择输入来源，配置参数，一键生成可直接复核的高光片段。
              </p>
            </div>
            <div className="hidden xl:block">
              <ImportIllustration />
            </div>
          </div>
        </section>

        {/* Input Panel */}
        <section className="surface-panel p-5 md:p-6">

          {/* Tab Bar */}
          <div className="mb-6 flex gap-1 rounded-xl border border-[var(--color-border)] bg-black/30 p-1">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => { setActiveTab(tab.id); setError(''); }}
                  className={`tab-signal flex-1 ${active ? 'tab-signal-active' : ''}`}
                >
                  <Icon size={14} />
                  {tab.label}
                </button>
              );
            })}
          </div>

          <div className="grid gap-5 xl:grid-cols-2 xl:items-start">

            {/* Left: Input area */}
            <div className="flex flex-col gap-4 xl:min-h-[520px]">
              {activeTab === 'upload' ? (
                <div
                  onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className="relative min-h-[520px] cursor-pointer rounded-2xl border-2 border-dashed p-6 transition-all duration-300"
                  style={{
                    background: file ? 'rgba(62, 196, 126, 0.03)' : dragOver ? 'rgba(124, 109, 238, 0.04)' : 'rgba(0, 0, 0, 0.2)',
                    borderColor: file
                      ? 'rgba(62, 196, 126, 0.3)'
                      : dragOver
                        ? 'rgba(124, 109, 238, 0.4)'
                        : 'var(--color-border)',
                  }}
                >
                  <input ref={fileInputRef} type="file" accept="video/*" className="hidden" onChange={(e) => handleFile(e.target.files[0])} />

                  <div className="flex h-full flex-col items-center justify-center gap-4 py-10 text-center">
                    <div
                      className="flex h-14 w-14 items-center justify-center rounded-2xl transition-all duration-300"
                      style={{
                        background: file ? 'rgba(62, 196, 126, 0.08)' : 'var(--color-accent-dim)',
                        border: `1px solid ${file ? 'rgba(62, 196, 126, 0.2)' : 'rgba(124, 109, 238, 0.15)'}`,
                      }}
                    >
                      {file
                        ? <Film size={22} className="text-success" />
                        : <Upload size={22} className="text-accent" />}
                    </div>
                    <div>
                      <div className="text-base font-semibold text-text-primary">
                        {file ? file.name : '将视频拖拽到这里'}
                      </div>
                      <div className="mt-1.5 text-sm text-text-secondary">
                        {file ? '已就绪 — 点击可替换文件' : '或点击选择 MP4 / MKV / AVI'}
                      </div>
                    </div>
                    {uploading && (
                      <div className="w-full max-w-xs">
                        <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
                          <div className="progress-shimmer h-full rounded-full transition-[width] duration-300" style={{ width: `${uploadProgress * 100}%` }} />
                        </div>
                        <div className="mt-2 font-mono text-xs text-text-muted">上传中 {Math.round(uploadProgress * 100)}%</div>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="min-h-[520px] rounded-2xl border border-[var(--color-border)] bg-black/20 p-5">
                  <div
                    className="rounded-xl p-4 transition-all duration-200"
                    style={{
                      background: urlFocused ? 'rgba(124, 109, 238, 0.03)' : 'rgba(0, 0, 0, 0.25)',
                      border: `1px solid ${urlFocused ? 'rgba(124, 109, 238, 0.25)' : 'var(--color-border)'}`,
                    }}
                  >
                    <div className="signal-label mb-3">{activeTab === 'live' ? '直播来源' : '视频来源'}</div>
                    <div className="flex items-center gap-3">
                      <input
                        type="text" value={url}
                        onFocus={() => setUrlFocused(true)} onBlur={() => setUrlFocused(false)}
                        onChange={(e) => { setUrl(e.target.value); setError(''); }}
                        placeholder={activeTab === 'live' ? '粘贴直播链接（B站 / 抖音 / 油管 等）' : '粘贴视频链接（B站 / 油管 / 抖音 / 西瓜 / 微博 / 小红书）'}
                        className="flex-1 bg-transparent text-sm text-text-primary outline-none placeholder:text-text-muted font-mono"
                        style={{ caretColor: 'var(--color-accent)' }}
                      />
                      <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--color-border)] bg-black/20">
                        {urlStatus === 'loading' && <Loader2 size={13} className="animate-spin text-text-muted" />}
                        {urlStatus === 'valid' && <CheckCircle2 size={13} className="text-success" />}
                        {urlStatus === 'invalid' && <AlertTriangle size={13} className="text-danger" />}
                      </div>
                    </div>
                  </div>
                  {urlPreview && (
                    <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-black/25 p-4">
                      <div className="text-sm font-semibold text-text-primary">{urlPreview.title}</div>
                      <div className="mt-1 text-sm text-text-secondary">{urlPreview.subtitle}</div>
                      {urlPreview.meta && <div className="mt-2 font-mono text-xs text-text-muted">{urlPreview.meta}</div>}
                    </div>
                  )}
                </div>
              )}

              {error && (
                <div className="rounded-xl border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger">
                  {error}
                </div>
              )}
            </div>

            {/* Right: Params */}
            <div className="flex flex-col gap-4">

              {/* Params card */}
              <div className="rounded-2xl border border-[var(--color-border)] bg-black/25 p-5">
                <div className="mb-5 section-eyebrow">参数配置</div>
                <div className={`grid gap-4 ${activeTab === 'live' ? 'md:grid-cols-3' : 'md:grid-cols-2'}`}>
                  <Field label="片段数" hint={PARAM_HINT}>
                    <input type="number" min={1} max={50} value={topN}
                      onChange={(e) => { setTopN(e.target.value); localStorage.setItem('top_n', e.target.value); }}
                      className="bento-input font-mono" />
                  </Field>
                  <Field label="片段时长（秒）" hint={PARAM_HINT}>
                    <input type="number" min={5} max={3600} value={clipDuration}
                      onChange={(e) => { setClipDuration(e.target.value); localStorage.setItem('clip_duration', e.target.value); }}
                      className="bento-input font-mono" />
                  </Field>
                  {activeTab === 'live' && (
                    <Field label="录制时长（秒）">
                      <input type="number" min={30} max={43200} value={liveDuration}
                        onChange={(e) => { setLiveDuration(e.target.value); localStorage.setItem('live_duration', e.target.value); }}
                        className="bento-input font-mono" />
                    </Field>
                  )}
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                  <Field label="输出目录（可选）">
                    <input type="text" value={outputDir}
                      onChange={(e) => { setOutputDir(e.target.value); localStorage.setItem('output_dir', e.target.value); }}
                      placeholder="D:\clips\project-a" className="bento-input font-mono" />
                  </Field>
                  <button type="button" onClick={handlePickOutputDir} disabled={selectingDir}
                    className={`btn-secondary mt-[26px] rounded-xl px-4 py-3 text-sm ${selectingDir ? 'opacity-60' : ''}`}>
                    {selectingDir ? <Loader2 size={15} className="animate-spin" /> : <FolderOpen size={15} />}
                    浏览
                  </button>
                </div>
              </div>

              {/* Speed boost */}
              <div className="rounded-2xl border border-[var(--color-border)] bg-black/20 p-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-warm-dim"
                    style={{ border: '1px solid rgba(212, 151, 90, 0.12)' }}>
                    <Zap size={15} className="text-warm" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-bold text-text-primary">极速模式</div>
                    <div className="mt-0.5 text-xs leading-5 text-text-secondary">轻量排序逻辑，减少精修步骤</div>
                  </div>
                  <Toggle checked={speedBoost} onChange={(checked) => { setSpeedBoost(checked); localStorage.setItem('speed_boost', checked ? '1' : '0'); }} />
                </div>
              </div>

              {/* CTA */}
              <div className="rounded-2xl border border-[var(--color-border)] bg-black/25 p-5">
                <div className="mb-4 flex items-center gap-2 text-xs text-text-muted">
                  <div
                    className="h-1.5 w-1.5 rounded-full transition-all duration-300"
                    style={{
                      background: canStart && !uploading && !submitting ? 'var(--color-warm)' : 'var(--color-text-muted)',
                    }}
                  />
                  {activeTab === 'live' ? '直播模式：先录制，再自动运行高光提取。' : '任务完成后片段直接进入复核工作区。'}
                </div>
                <button onClick={handleStart} disabled={!canStart || uploading || submitting}
                  className="btn-warm w-full rounded-xl px-6 py-3.5 text-sm">
                  {uploading || submitting ? '处理中...' : '生成高光片段'}
                  <ArrowRight size={16} />
                </button>
              </div>

            </div>
          </div>
        </section>

      </div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="mb-2 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        {label}
        {hint ? <HintIcon text={hint} /> : null}
      </label>
      {children}
    </div>
  );
}

function HintIcon({ text }) {
  return (
    <span className="group relative inline-flex items-center">
      <CircleHelp size={12} className="text-text-muted" />
      <span className="pointer-events-none absolute bottom-[130%] left-1/2 z-20 w-48 -translate-x-1/2 rounded-xl border border-[var(--color-border)] bg-panel-strong px-2.5 py-2 text-[10px] leading-4 text-text-secondary opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
        {text}
      </span>
    </span>
  );
}

function ImportIllustration() {
  return (
    <svg viewBox="0 0 240 180" className="h-auto w-full opacity-60" fill="none" aria-hidden>
      {/* Minimal abstract waveform */}
      <rect x="16" y="20" width="208" height="140" rx="16" fill="rgba(124,109,238,0.04)" stroke="rgba(124,109,238,0.1)" strokeWidth="1" />
      {[0,1,2,3,4,5,6,7,8,9].map((i) => {
        const heights = [20,35,25,48,38,55,30,42,22,50];
        const h = heights[i];
        const x = 32 + i * 20;
        const y = 90 - h / 2;
        return (
          <rect key={i} x={x} y={y} width="10" height={h} rx="3"
            fill={i === 5 || i === 4 ? 'rgba(124,109,238,0.5)' : 'rgba(124,109,238,0.15)'}
          />
        );
      })}
      <path d="M186 72v28" stroke="rgba(124,109,238,0.4)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M176 82l10-10 10 10" stroke="rgba(124,109,238,0.4)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function extractBvid(raw) {
  const match = String(raw).match(/BV[0-9A-Za-z]{10}/i);
  return match ? match[0].toUpperCase() : null;
}

function extractRoomId(raw) {
  const text = String(raw).trim();
  if (/^\d+$/.test(text)) return text;
  const match = text.match(/live\.bilibili\.com\/(\d+)/i);
  return match ? match[1] : null;
}

function toHttpUrl(raw) {
  const text = String(raw || '').trim();
  if (!text) return '';
  if (/^https?:\/\//i.test(text)) return text;
  if (/[A-Za-z0-9.-]+\.[A-Za-z]{2,}/.test(text)) return `https://${text.replace(/^\/+/, '')}`;
  return text;
}

function getHostname(raw) {
  try {
    const normalized = toHttpUrl(raw);
    const u = new URL(normalized);
    return u.hostname.toLowerCase();
  } catch {
    return '';
  }
}

function isBilibiliVodInput(raw) {
  const text = String(raw).trim();
  if (!text) return false;
  return Boolean(extractBvid(text) || /bilibili\.com\/video\//i.test(text));
}

function isBilibiliLiveInput(raw) {
  const text = String(raw).trim();
  if (!text) return false;
  return Boolean(extractRoomId(text) || /live\.bilibili\.com/i.test(text));
}

function isLikelyVodInput(raw) {
  const text = String(raw).trim();
  if (!text) return false;
  if (isBilibiliVodInput(text)) return true;
  const host = getHostname(text);
  return Boolean(host);
}

function isLikelyLiveInput(raw) {
  const text = String(raw).trim();
  if (!text) return false;
  if (isBilibiliLiveInput(text)) return true;
  const host = getHostname(text);
  return Boolean(host && /live|douyin|youtube|youtu\.be|weibo|xigua|xiaohongshu|xhs|bilibili/.test(host));
}

function resolveSourceType(activeTab, raw) {
  if (activeTab === 'live') {
    return isBilibiliLiveInput(raw) ? 'bili_live' : 'web_live';
  }
  return isBilibiliVodInput(raw) ? 'bili_vod' : 'web_vod';
}

function buildGenericPreview(raw, mode) {
  const host = getHostname(raw);
  const site = host ? host.replace(/^www\./, '') : '在线来源';
  return {
    title: mode === 'live' ? `直播来源（${site}）` : `视频来源（${site}）`,
    subtitle: raw,
    cover: null,
    meta: mode === 'live'
      ? '将按当前设置的时长使用 yt-dlp 录制直播。'
      : '将先通过 yt-dlp 下载视频，再进入剪辑流程。',
  };
}

async function fetchVodPreview(raw, signal) {
  const bvid = extractBvid(raw);
  if (!bvid) {
    return {
      title: '哔哩哔哩视频',
      subtitle: raw,
      cover: null,
      meta: '',
    };
  }

  const res = await fetch(`https://api.bilibili.com/x/web-interface/view?bvid=${encodeURIComponent(bvid)}`, { signal });
  if (!res.ok) throw new Error('预览获取失败');
  const json = await res.json();
  const d = json?.data;
  if (!d) throw new Error('预览数据无效');

  return {
    title: d.title || `哔哩哔哩视频 ${bvid}`,
    subtitle: d.owner?.name ? `UP主：${d.owner.name}` : bvid,
    cover: d.pic || null,
    meta: d.duration ? `时长 ${formatDuration(d.duration)} - ${bvid}` : bvid,
  };
}

async function fetchLivePreview(raw, signal) {
  const roomId = extractRoomId(raw);
  if (!roomId) {
    return {
      title: '哔哩哔哩直播',
      subtitle: raw,
      cover: null,
      meta: '',
    };
  }

  const res = await fetch(`https://api.live.bilibili.com/room/v1/Room/get_info?room_id=${encodeURIComponent(roomId)}`, { signal });
  if (!res.ok) throw new Error('预览获取失败');
  const json = await res.json();
  const d = json?.data;
  if (!d) throw new Error('预览数据无效');

  return {
    title: d.title || `直播间 ${roomId}`,
    subtitle: d.uname ? `主播：${d.uname}` : `房间 ${roomId}`,
    cover: d.user_cover || d.keyframe || null,
    meta: d.live_status === 1 ? '正在直播' : '当前未开播',
  };
}

function formatDuration(seconds) {
  const s = Number(seconds) || 0;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  return `${m}:${String(sec).padStart(2, '0')}`;
}
