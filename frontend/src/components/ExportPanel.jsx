import { useState } from 'react';
import {
  ArrowLeft,
  Download,
  Smartphone,
  Monitor,
  Square,
  CheckCircle2,
  Loader,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';
import Toggle from './Toggle';

const PLATFORMS = [
  { id: 'bilibili', name: '哔哩哔哩', aspect: '16:9', maxDuration: 600, desc: '横屏标准视频' },
  { id: 'tiktok', name: '抖音', aspect: '9:16', maxDuration: 60, desc: '竖屏短视频' },
  { id: 'youtube_shorts', name: '油管短视频', aspect: '9:16', maxDuration: 60, desc: '竖屏，最长 60 秒' },
  { id: 'custom', name: '自定义', aspect: '16:9', maxDuration: null, desc: '保持原始比例' },
];

const ASPECT_OPTIONS = [
  { id: '16:9', label: '16:9', icon: Monitor },
  { id: '9:16', label: '9:16', icon: Smartphone },
  { id: '1:1', label: '1:1', icon: Square },
];

export default function ExportPanel() {
  const { state, dispatch } = useAppStore();
  const [selectedPlatform, setSelectedPlatform] = useState(state.exportPlatform || 'bilibili');
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);
  const [aspect, setAspect] = useState('16:9');
  const [exportError, setExportError] = useState('');
  const [cleanupInfo, setCleanupInfo] = useState('');
  const [autoCleanupSource, setAutoCleanupSource] = useState(() => localStorage.getItem('auto_cleanup_source') !== '0');
  const [keepOnlySelected, setKeepOnlySelected] = useState(() => localStorage.getItem('keep_only_selected_clips') !== '0');

  const selectedClips = state.highlights.filter((h) => h.selected);
  const platform = PLATFORMS.find((p) => p.id === selectedPlatform);
  const totalDuration = Math.round(selectedClips.reduce((sum, c) => sum + (c.clipEnd - c.clipStart), 0));

  const downloadSingleClip = async (clip, idx) => {
    if (!clip.downloadUrl) return;
    const resp = await fetch(clip.downloadUrl, { credentials: 'include' });
    if (!resp.ok) {
      throw new Error(`下载失败（HTTP ${resp.status}）`);
    }
    const blob = await resp.blob();
    const objectUrl = URL.createObjectURL(blob);
    try {
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = clip.fileName || `clip_${String(idx + 1).padStart(2, '0')}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  };

  const triggerDownloads = async () => {
    const failed = [];
    for (let i = 0; i < selectedClips.length; i += 1) {
      const clip = selectedClips[i];
      try {
        // eslint-disable-next-line no-await-in-loop
        await downloadSingleClip(clip, i);
      } catch (err) {
        failed.push({ clip, err });
      }
    }
    return failed;
  };

  const handleExport = async () => {
    setExportError('');
    setCleanupInfo('');
    const downloadable = selectedClips.filter((c) => !!c.downloadUrl);
    if (downloadable.length === 0) {
      setExportError('当前任务没有可下载的片段。');
      return;
    }
    setExporting(true);
    const failed = await triggerDownloads();
    if (failed.length > 0) {
      setExportError(`有 ${failed.length} 个片段下载失败，请重试。`);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
    const cleanupMessages = [];

    if (autoCleanupSource && state.jobId) {
      try {
        const res = await api.cleanupJobSource(state.jobId);
        const freed = Number.isFinite(res?.freed_mb) ? res.freed_mb : 0;
        cleanupMessages.push(`源素材已自动清理（释放 ${freed} MB）。`);
      } catch (err) {
        cleanupMessages.push(`源素材清理已跳过：${err?.message || '清理请求失败'}`);
      }
    }

    if (keepOnlySelected && state.jobId && selectedClips.length > 0) {
      try {
        const res = await api.cleanupUnselectedClips(
          state.jobId,
          selectedClips.map((c) => c.id),
        );
        const removedCount = Number.isFinite(res?.removed_count) ? res.removed_count : 0;
        const freed = Number.isFinite(res?.freed_mb) ? res.freed_mb : 0;
        cleanupMessages.push(`未选片段已清理（删除 ${removedCount} 个，释放 ${freed} MB）。`);
        dispatch({ type: 'KEEP_ONLY_SELECTED_CLIPS' });
      } catch (err) {
        cleanupMessages.push(`未选片段清理已跳过：${err?.message || '清理请求失败'}`);
      }
    }

    if (cleanupMessages.length > 0) {
      setCleanupInfo(cleanupMessages.join(' '));
    }
    setExporting(false);
    setExported(true);
  };

  return (
    <div className="min-h-full w-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto flex w-full max-w-[1380px] flex-col gap-4">
        <section className="surface-panel overflow-hidden px-5 py-5 md:px-7 md:py-6">
          <div>
            <div className="mb-2 signal-label">导出</div>
            <h1 className="max-w-2xl text-3xl font-extrabold tracking-tight text-text-primary md:text-4xl">
              打包你保留的片段，并一键导出。
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-text-secondary">
              确认目标格式、下载已选片段，并可在导出后清理源素材。
            </p>
          </div>
        </section>

        <div className="grid gap-4">
          <section className="surface-panel p-5 md:p-6">
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <StatChip label="已选片段" value={`${selectedClips.length}`} />
                <StatChip label="总时长" value={`${totalDuration}秒`} />
                <StatChip label="格式" value={`${aspect} MP4`} />
              </div>
              <button
                onClick={() => dispatch({ type: 'SET_PHASE', payload: 'review' })}
                className="btn-secondary rounded-lg px-4 py-2 text-xs font-semibold"
              >
                <ArrowLeft size={14} />
                返回复核
              </button>
            </div>

            <div className="grid gap-5 xl:grid-cols-2 xl:items-start">
              <div className="space-y-4">
                <div className="rounded-xl border border-[var(--color-border)] bg-panel-strong p-5">
                  <div className="section-eyebrow mb-4">平台</div>
                  <div className="grid gap-2.5 sm:grid-cols-2">
                    {PLATFORMS.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => {
                          setSelectedPlatform(p.id);
                          setAspect(p.aspect);
                        }}
                        className={`rounded-xl border px-4 py-3.5 text-left transition-all duration-200 ${
                          selectedPlatform === p.id
                            ? 'card-active-accent bg-accent/4'
                            : 'border-[var(--color-border)] bg-black/15 hover:bg-bg-hover hover:border-[var(--color-border-active)]'
                        }`}
                      >
                        <div className="text-sm font-semibold text-text-primary">{p.name}</div>
                        <div className="mt-1 text-sm text-text-secondary">{p.desc}</div>
                        <div className="mt-2 text-xs font-mono text-text-muted">
                          {p.maxDuration ? `最长 ${p.maxDuration}秒` : '无固定时长限制'}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="rounded-xl border border-[var(--color-border)] bg-panel-strong p-5">
                  <div className="section-eyebrow mb-4">画面比例</div>
                  <div className="grid gap-2.5 sm:grid-cols-3">
                    {ASPECT_OPTIONS.map((opt) => (
                      <button
                        key={opt.id}
                        onClick={() => setAspect(opt.id)}
                        className={`inline-flex items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-semibold transition-colors ${
                          aspect === opt.id
                            ? 'border-accent/25 bg-accent/5 text-text-primary'
                            : 'border-[var(--color-border)] bg-black/15 text-text-secondary hover:bg-bg-hover'
                        }`}
                      >
                        <opt.icon size={15} />
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <aside className="flex flex-col gap-4">
                <div className="rounded-xl border border-[var(--color-border)] bg-panel-strong p-5">
                  <div className="mb-3 text-sm font-semibold text-text-primary">已选片段</div>
                  {selectedClips.length === 0 ? (
                    <div className="text-sm leading-6 text-text-muted">尚未选择片段。请回到复核页保留要导出的内容。</div>
                  ) : (
                    <div className="space-y-1.5">
                      {selectedClips.map((clip, idx) => {
                        const scorePercent = Math.round((clip.score || 0) * 100);
                        return (
                          <div key={clip.id} className="rounded-lg border border-[var(--color-border)] bg-black/20 px-3.5 py-2.5">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-sm font-semibold text-text-primary">
                                片段 {String(idx + 1).padStart(2, '0')}
                              </div>
                              <div className="text-xs font-mono text-text-muted">{scorePercent}</div>
                            </div>
                            <div className="mt-1 text-xs font-mono text-text-secondary">
                              {formatTime(clip.clipStart)} - {formatTime(clip.clipEnd)}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                <div className="rounded-xl border border-[var(--color-border)] bg-panel-strong p-5">
                  <div className="text-sm font-semibold text-text-primary">检查项</div>
                  <div className="mt-3 space-y-1.5">
                    <ChecklistItem done={selectedClips.length > 0} text="至少选择了一个片段" />
                    <ChecklistItem done={Boolean(platform)} text="已选择平台" />
                    <ChecklistItem done={Boolean(aspect)} text="已设置画面比例" />
                  </div>
                </div>

                <div className="rounded-xl border border-[var(--color-border)] bg-panel-strong p-5">
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-warm/8 text-warm">
                          <Trash2 size={15} />
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-text-primary">自动清理源素材</div>
                          <div className="mt-1 max-w-xl text-sm leading-6 text-text-secondary">
                            导出完成后删除缓存的源素材，生成片段会保留。
                          </div>
                        </div>
                      </div>
                      <Toggle
                        checked={autoCleanupSource}
                        onChange={(checked) => {
                          setAutoCleanupSource(checked);
                          localStorage.setItem('auto_cleanup_source', checked ? '1' : '0');
                        }}
                      />
                    </div>

                    <div className="h-px w-full bg-[var(--color-border)]" />

                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-warm/8 text-warm">
                          <Trash2 size={15} />
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-text-primary">仅保留已导出片段</div>
                          <div className="mt-1 max-w-xl text-sm leading-6 text-text-secondary">
                            导出后自动删除未勾选片段文件，避免目录里保留整批候选。
                          </div>
                        </div>
                      </div>
                      <Toggle
                        checked={keepOnlySelected}
                        onChange={(checked) => {
                          setKeepOnlySelected(checked);
                          localStorage.setItem('keep_only_selected_clips', checked ? '1' : '0');
                        }}
                      />
                    </div>
                  </div>
                </div>

                {exportError && (
                  <div className="rounded-xl border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger">
                    {exportError}
                  </div>
                )}

                {exported && (
                  <div className="rounded-xl border border-success/20 bg-success/5 px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-success/10 text-success">
                        <CheckCircle2 size={18} />
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-text-primary">导出完成</div>
                        <div className="text-sm text-text-secondary">你选择的片段已可下载。</div>
                      </div>
                    </div>
                    {cleanupInfo && <div className="mt-3 text-sm text-text-muted">{cleanupInfo}</div>}
                  </div>
                )}

                <button
                  onClick={handleExport}
                  disabled={exporting || selectedClips.length === 0}
                  className="btn-warm w-full rounded-xl px-6 py-3.5 text-sm xl:mt-auto"
                >
                  {exporting ? (
                    <>
                      <Loader size={15} className="animate-spin" />
                      导出中...
                    </>
                  ) : (
                    <>
                      <Download size={15} />
                      导出 {selectedClips.length} 个片段
                    </>
                  )}
                </button>
              </aside>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function StatChip({ label, value }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-panel-strong px-3 py-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">{label}</span>
      <span className="ml-2 text-xs font-mono text-text-primary">{value}</span>
    </div>
  );
}

function ChecklistItem({ done, text }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-black/15 px-3 py-2 text-sm text-text-secondary">
      <span className={`h-2 w-2 rounded-full ${done ? 'bg-success' : 'bg-text-muted'}`} />
      {text}
    </div>
  );
}

function formatTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, '0')}`;
}
