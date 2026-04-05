/**
 * API client hooks for communicating with the Stream Clipper backend.
 */

function resolveApiBase() {
  if (typeof window !== 'undefined') {
    const fromDesktop = window.streamClipperDesktop?.apiBase;
    if (typeof fromDesktop === 'string' && fromDesktop.trim()) {
      return fromDesktop.trim().replace(/\/+$/, '');
    }
  }

  const fromEnv = import.meta.env?.VITE_API_BASE;
  if (typeof fromEnv === 'string' && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/+$/, '');
  }

  return '/api/v1';
}

const API_BASE = resolveApiBase();

function normalizeSourceUrl(sourceType, sourceUrl) {
  if (typeof sourceUrl !== 'string') return sourceUrl;
  const raw = sourceUrl.trim();
  if (!raw) return raw;

  if (sourceType === 'bili_vod') {
    const bv = raw.match(/^(BV[a-zA-Z0-9]+)$/);
    if (bv) return `https://www.bilibili.com/video/${bv[1]}`;
    if (!/^https?:\/\//i.test(raw) && raw.includes('bilibili.com')) {
      return `https://${raw.replace(/^\/+/, '')}`;
    }
  }

  if (sourceType === 'bili_live') {
    if (/^\d+$/.test(raw)) return `https://live.bilibili.com/${raw}`;
    if (!/^https?:\/\//i.test(raw) && raw.includes('live.bilibili.com')) {
      return `https://${raw.replace(/^\/+/, '')}`;
    }
  }

  if ((sourceType === 'web_vod' || sourceType === 'web_live') && !/^https?:\/\//i.test(raw)) {
    if (/[A-Za-z0-9.-]+\.[A-Za-z]{2,}/.test(raw)) {
      const withScheme = `https://${raw.replace(/^\/+/, '')}`;
      const m = withScheme.match(/^https?:\/\/(?:www\.)?douyin\.com\/jingxuan\?.*?\bmodal_id=(\d{8,32})\b/i);
      if (m) return `https://www.douyin.com/video/${m[1]}`;
      return withScheme;
    }
  }
  if (sourceType === 'web_vod' || sourceType === 'web_live') {
    const m = raw.match(/^https?:\/\/(?:www\.)?douyin\.com\/jingxuan\?.*?\bmodal_id=(\d{8,32})\b/i);
    if (m) return `https://www.douyin.com/video/${m[1]}`;
  }

  return raw;
}

async function request(path, options = {}) {
  const token = localStorage.getItem('token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const rawBody = await res.text();

  if (!res.ok) {
    let detail = rawBody;
    try {
      if (rawBody) {
        const data = JSON.parse(rawBody);
        detail = data?.detail || JSON.stringify(data);
      }
    } catch {
      // keep plain-text detail
    }
    if (!detail || !String(detail).trim()) {
      detail = res.statusText || '服务器内部错误';
    }
    const err = new Error(`${res.status}: ${detail}`);
    err.status = res.status;
    err.detail = detail;
    throw err;
  }

  // 204 No Content or empty body
  if (!rawBody) {
    return {};
  }

  try {
    return JSON.parse(rawBody);
  } catch {
    return { raw: rawBody };
  }
}

export const api = {
  getPublicSiteConfig: () => request('/public/site-config'),

  submitLead: (payload) =>
    request('/public/leads', {
      method: 'POST',
      body: JSON.stringify(payload ?? {}),
    }),

  // Auth
  register: (email, password) =>
    request('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  login: (email, password) =>
    request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  // Jobs
  createJob: (sourceType, sourceUrl, options = {}) => {
    const normalizedUrl = normalizeSourceUrl(sourceType, sourceUrl);
    const topN = Number.parseInt(String(options.topN ?? 10), 10);
    const clipDuration = Number.parseFloat(String(options.clipDuration ?? 45));
    const requestedDuration = Number.parseInt(String(options.duration ?? NaN), 10);
    const defaultDuration = sourceType === 'bili_live' || sourceType === 'web_live' ? 180 : 1800;
    const outputDir = typeof options.outputDir === 'string' ? options.outputDir.trim() : '';
    const rawS3Key = typeof options.rawS3Key === 'string' ? options.rawS3Key.trim() : '';
    const candidateMultiplier = Number.parseInt(String(options.candidateMultiplier ?? 3), 10);
    const feedbackModelPath = typeof options.feedbackModelPath === 'string' ? options.feedbackModelPath.trim() : '';
    const llmModel = typeof options.llmModel === 'string' ? options.llmModel.trim() : '';
    const llmMaxCandidates = Number.parseInt(String(options.llmMaxCandidates ?? 20), 10);
    const llmScoreWeight = Number.parseFloat(String(options.llmScoreWeight ?? 0.65));
    const llmTimeoutSec = Number.parseFloat(String(options.llmTimeoutSec ?? 30));
    const boundaryProfilePath = typeof options.boundaryProfilePath === 'string' ? options.boundaryProfilePath.trim() : '';
    const halfPeakRatio = Number.parseFloat(String(options.halfPeakRatio ?? 0.5));
    const normalizedClipDuration = Number.isFinite(clipDuration)
      ? Math.min(3600, Math.max(5, clipDuration))
      : 45;
    const payload = {
      source_type: sourceType,
      source_url: normalizedUrl,
      top_n: Number.isFinite(topN) ? topN : 10,
      clip_duration: normalizedClipDuration,
      model_size: options.modelSize || 'tiny',
      language: options.language || 'zh',
      duration: Number.isFinite(requestedDuration) && requestedDuration > 0 ? requestedDuration : defaultDuration,
      viral_rank: options.viralRank || false,
      candidate_multiplier: Number.isFinite(candidateMultiplier) ? candidateMultiplier : 3,
      feedback_rank: options.feedbackRank !== false,
      boundary_adaptation: options.boundaryAdaptation !== false,
      adaptive_padding: options.adaptivePadding !== false,
      half_peak_ratio: Number.isFinite(halfPeakRatio) ? halfPeakRatio : 0.5,
    };
    if (outputDir) {
      payload.output_dir = outputDir;
    }
    if (rawS3Key) {
      payload.raw_s3_key = rawS3Key;
    }
    if (feedbackModelPath) {
      payload.feedback_model_path = feedbackModelPath;
    }
    if (typeof options.llmRerank === 'boolean') {
      payload.llm_rerank = options.llmRerank;
    }
    if (llmModel) {
      payload.llm_model = llmModel;
    }
    if (Number.isFinite(llmMaxCandidates)) {
      payload.llm_max_candidates = llmMaxCandidates;
    }
    if (Number.isFinite(llmScoreWeight)) {
      payload.llm_score_weight = llmScoreWeight;
    }
    if (Number.isFinite(llmTimeoutSec)) {
      payload.llm_timeout_sec = llmTimeoutSec;
    }
    if (boundaryProfilePath) {
      payload.boundary_profile_path = boundaryProfilePath;
    }
    return request('/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  createLocalJob: (file, options = {}, onProgress) => new Promise((resolve, reject) => {
    const formData = new FormData();
    const topN = Number.parseInt(String(options.topN ?? 10), 10);
    const clipDuration = Number.parseFloat(String(options.clipDuration ?? 45));
    const outputDir = typeof options.outputDir === 'string' ? options.outputDir.trim() : '';
    const candidateMultiplier = Number.parseInt(String(options.candidateMultiplier ?? 3), 10);
    const feedbackModelPath = typeof options.feedbackModelPath === 'string' ? options.feedbackModelPath.trim() : '';
    const llmModel = typeof options.llmModel === 'string' ? options.llmModel.trim() : '';
    const llmMaxCandidates = Number.parseInt(String(options.llmMaxCandidates ?? 20), 10);
    const llmScoreWeight = Number.parseFloat(String(options.llmScoreWeight ?? 0.65));
    const llmTimeoutSec = Number.parseFloat(String(options.llmTimeoutSec ?? 30));
    const boundaryProfilePath = typeof options.boundaryProfilePath === 'string' ? options.boundaryProfilePath.trim() : '';
    const halfPeakRatio = Number.parseFloat(String(options.halfPeakRatio ?? 0.5));
    formData.append('source_type', 'local');
    formData.append('top_n', String(Number.isFinite(topN) ? topN : 10));
    const normalizedClipDuration = Number.isFinite(clipDuration)
      ? Math.min(3600, Math.max(5, clipDuration))
      : 45;
    formData.append('clip_duration', String(normalizedClipDuration));
    formData.append('candidate_multiplier', String(Number.isFinite(candidateMultiplier) ? candidateMultiplier : 3));
    formData.append('feedback_rank', String(options.feedbackRank !== false));
    if (typeof options.llmRerank === 'boolean') {
      formData.append('llm_rerank', String(options.llmRerank));
    }
    formData.append('boundary_adaptation', String(options.boundaryAdaptation !== false));
    formData.append('adaptive_padding', String(options.adaptivePadding !== false));
    formData.append('half_peak_ratio', String(Number.isFinite(halfPeakRatio) ? halfPeakRatio : 0.5));
    formData.append('model_size', options.modelSize || 'tiny');
    formData.append('language', options.language || 'zh');
    if (outputDir) {
      formData.append('output_dir', outputDir);
    }
    if (feedbackModelPath) {
      formData.append('feedback_model_path', feedbackModelPath);
    }
    if (llmModel) {
      formData.append('llm_model', llmModel);
    }
    if (Number.isFinite(llmMaxCandidates)) {
      formData.append('llm_max_candidates', String(llmMaxCandidates));
    }
    if (Number.isFinite(llmScoreWeight)) {
      formData.append('llm_score_weight', String(llmScoreWeight));
    }
    if (Number.isFinite(llmTimeoutSec)) {
      formData.append('llm_timeout_sec', String(llmTimeoutSec));
    }
    if (boundaryProfilePath) {
      formData.append('boundary_profile_path', boundaryProfilePath);
    }
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    const token = localStorage.getItem('token');
    xhr.open('POST', `${API_BASE}/jobs`);
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(e.loaded / e.total);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new Error('响应数据格式无效'));
        }
      } else {
        let detail = (xhr.responseText || '').trim();
        try {
          if (detail) {
            const data = JSON.parse(detail);
            detail = data?.detail || JSON.stringify(data);
          }
        } catch {
          // keep plain-text detail
        }
        const fallbackStatuses = new Set([404, 405, 415, 422, 501]);
        if (fallbackStatuses.has(xhr.status)) {
          (async () => {
            try {
              const s3Key = await api.uploadFile(file, onProgress);
              const job = await api.createJob('local', null, {
                ...options,
                rawS3Key: s3Key,
              });
              resolve(job);
            } catch (err) {
              reject(err instanceof Error ? err : new Error('本地任务回退创建失败'));
            }
          })();
          return;
        }
        reject(new Error(`创建本地任务失败: ${xhr.status}${detail ? `: ${detail}` : ''}`));
      }
    };
    xhr.onerror = () => reject(new Error('创建本地任务失败'));
    xhr.send(formData);
  }),

  getJob: (jobId) => request(`/jobs/${jobId}`),
  listJobs: (page = 1) => request(`/jobs?page=${page}`),
  cleanupJobSource: (jobId) =>
    request(`/jobs/${jobId}/cleanup-source`, { method: 'POST' }),
  cleanupUnselectedClips: (jobId, keepClipIds) =>
    request(`/jobs/${jobId}/cleanup-unselected-clips`, {
      method: 'POST',
      body: JSON.stringify({ keep_clip_ids: Array.isArray(keepClipIds) ? keepClipIds : [] }),
    }),
  pickOutputDirectory: (current = '') =>
    request(`/system/select-output-dir${current ? `?current=${encodeURIComponent(current)}` : ''}`),

  // SSE progress stream
  streamProgress: (jobId, onMessage) => {
    const url = `${API_BASE}/jobs/${jobId}/stream`;
    const eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch {
        onMessage({ raw: event.data });
      }
    };

    eventSource.onerror = () => {
      onMessage({
        type: 'stream_error',
        text: '进度流已断开，正在回退到轮询模式...',
      });
      eventSource.close();
    };

    return () => eventSource.close();
  },

  // Clips
  listClips: (page = 1, sortBy = 'created_at') =>
    request(`/clips?page=${page}&sort_by=${sortBy}`),

  getClip: (clipId) => request(`/clips/${clipId}`),

  deleteClip: (clipId) =>
    request(`/clips/${clipId}`, { method: 'DELETE' }),

  adjustClip: (clipId, clipStart, clipEnd, note = '', opts = {}) =>
    request(`/clips/${clipId}/adjust`, {
      method: 'POST',
      body: JSON.stringify({
        clip_start: clipStart,
        clip_end: clipEnd,
        note,
        fast_preview: opts.fastPreview === true,
      }),
      signal: opts.signal,
    }),

  submitClipFeedback: (clipId, rating, note = '') =>
    request(`/clips/${clipId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ rating, note }),
    }),
  retrainFeedbackModel: (payload = {}) =>
    request('/feedback/retrain', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Upload
  getUploadUrl: () =>
    request('/upload/presign', { method: 'POST' }),

  uploadFile: async (file, onProgress) => {
    const { upload_url, upload_fields, s3_key } = await api.getUploadUrl();
    const formData = new FormData();
    Object.entries(upload_fields).forEach(([k, v]) => formData.append(k, v));
    formData.append('file', file);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', upload_url);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(e.loaded / e.total);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(s3_key);
        } else {
          reject(new Error(`上传失败: ${xhr.status}`));
        }
      };
      xhr.onerror = () => reject(new Error('上传失败'));
      xhr.send(formData);
    });
  },
};
