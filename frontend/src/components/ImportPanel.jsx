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
    <div className="min-h-full w-full overflow-y-auto p-4 md:p-8">
      <div className="mx-auto flex w-full max-w-[1380px] flex-col gap-5">
        <section className="surface-panel overflow-hidden px-5 py-5 md:px-8 md:py-7">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_320px] xl:items-center">
            <div>
              <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
                新建项目
              </div>
              <h1 className="max-w-2xl text-4xl font-extrabold tracking-[-0.05em] text-text-primary md:text-5xl">
                从本地文件、在线视频或直播间开始。
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-text-secondary">
                页面保持简洁：选择来源、设置必要参数，然后生成可直接复核的片段。
              </p>
            </div>
            <div className="rounded-[26px] border border-white/8 bg-[#12263c] p-5">
              <ImportIllustration />
            </div>
          </div>
        </section>

        <section className="surface-panel p-5 md:p-6">
            <div className="mb-5 flex flex-wrap gap-2 rounded-full bg-[#0d1d2f] p-1">
              {TABS.map((tab) => {
                const Icon = tab.icon;
                const active = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => {
                      setActiveTab(tab.id);
                      setError('');
                    }}
                    className={`inline-flex cursor-pointer items-center gap-2 rounded-full px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.12em] transition-colors ${
                      active
                        ? 'bg-[#2b3949] text-text-primary shadow-sm'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    <Icon size={14} />
                    {tab.label}
                  </button>
                );
              })}
            </div>

            <div className="grid gap-5 xl:grid-cols-2 xl:items-start">
              <div className="flex flex-col gap-5 xl:min-h-[520px]">
                {activeTab === 'upload' ? (
                  <div
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragOver(true);
                    }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                    className={`relative min-h-[520px] cursor-pointer rounded-[24px] border border-dashed p-8 transition-colors ${
                      dragOver
                        ? 'border-accent bg-accent/8'
                        : file
                          ? 'border-success/40 bg-[#eef8f3]'
                          : 'border-white/10 bg-[#0b1c2d] hover:border-accent/55 hover:bg-[#11253a]'
                    }`}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="video/*"
                      className="hidden"
                      onChange={(e) => handleFile(e.target.files[0])}
                    />
                    <div className="flex h-full flex-col items-center justify-center gap-4 py-10 text-center">
                      <div className="flex h-16 w-16 items-center justify-center rounded-3xl bg-[#1b2d43] shadow-sm">
                        {file ? <Film size={24} className="text-success" /> : <Upload size={24} className="text-accent" />}
                      </div>
                      <div>
                        <div className="text-lg font-semibold text-text-primary">
                          {file ? file.name : '将视频拖拽到这里'}
                        </div>
                        <div className="mt-2 text-sm text-text-secondary">
                          {file ? '已准备好处理，点击可替换文件。' : '或点击选择本地 MP4 / MKV / AVI 文件。'}
                        </div>
                      </div>

                      {uploading && (
                        <div className="w-full max-w-xs">
                          <div className="h-2 overflow-hidden rounded-full bg-[#20364f]">
                            <div
                              className="h-full rounded-full bg-accent transition-all duration-300"
                              style={{ width: `${uploadProgress * 100}%` }}
                            />
                          </div>
                          <div className="mt-2 text-xs font-mono text-text-muted">
                            上传中 {Math.round(uploadProgress * 100)}%
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="min-h-[520px] rounded-[24px] border border-white/8 bg-[#12263c] p-4">
                    <div className={`rounded-[18px] border px-4 py-5 transition-colors ${urlFocused ? 'border-accent bg-[#142b43]' : 'border-white/10 bg-[#102338]'}`}>
                      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">
                        {activeTab === 'live' ? '直播来源' : '视频来源'}
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="text"
                          value={url}
                          onFocus={() => setUrlFocused(true)}
                          onBlur={() => setUrlFocused(false)}
                          onChange={(e) => {
                            setUrl(e.target.value);
                            setError('');
                          }}
                          placeholder={activeTab === 'live'
                            ? '粘贴直播链接（B站 / 抖音 / 油管 等）'
                            : '粘贴视频链接（B站 / 油管 / 抖音 / 西瓜 / 微博 / 小红书）'}
                          className="flex-1 bg-transparent text-base text-text-primary outline-none placeholder:text-text-muted"
                        />
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1a3047]">
                          {urlStatus === 'loading' && <Loader2 size={15} className="animate-spin text-text-muted" />}
                          {urlStatus === 'valid' && <CheckCircle2 size={15} className="text-success" />}
                          {urlStatus === 'invalid' && <AlertTriangle size={15} className="text-danger" />}
                        </div>
                      </div>
                    </div>

                    {urlPreview && (
                      <div className="mt-4 rounded-[18px] border border-white/8 bg-[#14293f] p-4">
                        <div className="text-sm font-semibold text-text-primary">{urlPreview.title}</div>
                        <div className="mt-1 text-sm text-text-secondary">{urlPreview.subtitle}</div>
                        {urlPreview.meta && <div className="mt-2 text-xs text-text-muted">{urlPreview.meta}</div>}
                      </div>
                    )}
                  </div>
                )}

                {error && (
                  <div className="rounded-[18px] border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
                    {error}
                  </div>
                )}
              </div>

              <div className="space-y-5">
                <div className="rounded-[24px] border border-white/8 bg-[#12283e] p-5">
                  <div className="section-eyebrow mb-5">参数</div>
                  <div className={`grid gap-4 ${activeTab === 'live' ? 'md:grid-cols-3' : 'md:grid-cols-2'}`}>
                    <Field label="片段数" hint={PARAM_HINT}>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={topN}
                        onChange={(e) => {
                          setTopN(e.target.value);
                          localStorage.setItem('top_n', e.target.value);
                        }}
                        className="bento-input font-mono"
                      />
                    </Field>

                    <Field label="片段时长（秒）" hint={PARAM_HINT}>
                      <input
                        type="number"
                        min={5}
                        max={3600}
                        value={clipDuration}
                        onChange={(e) => {
                          setClipDuration(e.target.value);
                          localStorage.setItem('clip_duration', e.target.value);
                        }}
                        className="bento-input font-mono"
                      />
                    </Field>

                    {activeTab === 'live' && (
                      <Field label="录制时长（秒）">
                        <input
                          type="number"
                          min={30}
                          max={43200}
                          value={liveDuration}
                          onChange={(e) => {
                            setLiveDuration(e.target.value);
                            localStorage.setItem('live_duration', e.target.value);
                          }}
                          className="bento-input font-mono"
                        />
                      </Field>
                    )}
                  </div>

                  <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_auto]">
                    <Field label="输出目录（可选）">
                      <input
                        type="text"
                        value={outputDir}
                        onChange={(e) => {
                          setOutputDir(e.target.value);
                          localStorage.setItem('output_dir', e.target.value);
                        }}
                        placeholder="D:\\clips\\project-a"
                        className="bento-input font-mono"
                      />
                    </Field>
                    <button
                      type="button"
                      onClick={handlePickOutputDir}
                      disabled={selectingDir}
                      className={`btn-secondary mt-[26px] rounded-2xl px-4 py-3 text-sm ${selectingDir ? 'opacity-60' : ''}`}
                    >
                      {selectingDir ? <Loader2 size={16} className="animate-spin" /> : <FolderOpen size={16} />}
                      浏览
                    </button>
                  </div>
                </div>

                <div className="rounded-[24px] border border-white/8 bg-[#152b42] px-5 py-5">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-2xl bg-warm/10 text-warm">
                      <Zap size={16} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-text-primary">极速模式</div>
                      <div className="mt-1 text-sm text-text-secondary leading-6">
                        使用更轻量的排序逻辑与更少的精修步骤，加快处理速度。
                      </div>
                    </div>
                    <Toggle
                      checked={speedBoost}
                      onChange={(checked) => {
                        setSpeedBoost(checked);
                        localStorage.setItem('speed_boost', checked ? '1' : '0');
                      }}
                    />
                  </div>
                </div>

                <div className="rounded-[24px] border border-white/8 bg-[#102338] p-5 xl:mt-auto">
                  <div className="text-sm text-text-muted leading-6">
                    {activeTab === 'live'
                      ? '直播模式会先录制，再自动进入同一套高光提取流程。'
                      : '任务完成后，生成片段会直接进入复核工作区。'}
                  </div>
                  <button
                    onClick={handleStart}
                    disabled={!canStart || uploading || submitting}
                    className="btn-warm mt-5 w-full rounded-full px-6 py-3 text-sm"
                  >
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
      <label className="mb-2 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-muted">
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
      <span className="pointer-events-none absolute bottom-[130%] left-1/2 z-20 w-48 -translate-x-1/2 rounded-xl border border-white/8 bg-[#1a314a] px-2.5 py-2 text-[10px] leading-4 text-text-secondary opacity-0 shadow-sm transition-opacity group-hover:opacity-100">
        {text}
      </span>
    </span>
  );
}

function ImportIllustration() {
  return (
    <svg viewBox="0 0 320 200" className="h-auto w-full text-[#7faed2]" fill="none" aria-hidden>
      <rect x="18" y="22" width="284" height="156" rx="28" fill="#10253a" stroke="#28425e" />
      <rect x="42" y="46" width="236" height="108" rx="20" fill="#163049" stroke="#28425e" />
      <rect x="68" y="76" width="88" height="48" rx="18" fill="#7faed2" opacity="0.18" />
      <rect x="170" y="76" width="66" height="12" rx="6" fill="#c7d9ea" />
      <rect x="170" y="96" width="84" height="10" rx="5" fill="#d7e5f2" />
      <rect x="170" y="115" width="54" height="10" rx="5" fill="#edd8bc" />
      <path d="M110 62v44" stroke="#7faed2" strokeWidth="8" strokeLinecap="round" />
      <path d="M92 80l18-18 18 18" stroke="#7faed2" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="272" cy="46" r="18" fill="#f5eadb" />
      <circle cx="50" cy="158" r="10" fill="#e6f0f8" />
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
