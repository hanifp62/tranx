import { transcribeShortClip } from './api';
import { isLocalE2EMode, type AuthSessionUser } from './firebase';

export interface DictationHandle {
  stop: () => void;
}

export function startVoiceDictation(params: {
  user: AuthSessionUser;
  onInterim: (text: string) => void;
  onLevels: (bars: number[]) => void;
  onDone: (finalText: string) => void;
  onError: (message: string) => void;
}): DictationHandle {
  if (isLocalE2EMode()) {
    params.onLevels([8, 16, 12, 18, 10]);
    params.onInterim('千早は小さく...');
    const timer = window.setTimeout(() => {
      params.onDone('千早は小さく笑った。');
    }, 350);
    return {
      stop: () => {
        window.clearTimeout(timer);
        params.onDone('千早は小さく笑った。');
      },
    };
  }

  const SpeechCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechCtor) {
    const rec = new SpeechCtor();
    rec.lang = 'ja-JP';
    rec.continuous = true;
    rec.interimResults = true;
    let accumulated = '';
    let finished = false;

    rec.onresult = (ev) => {
      let interim = '';
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
        const res = ev.results[i];
        if (res.isFinal) {
          accumulated += res[0].transcript;
        } else {
          interim += res[0].transcript;
        }
      }
      const combined = (accumulated + interim).trim();
      params.onInterim(combined);
      params.onLevels(
        combined.length % 2 === 0 ? [7, 15, 19, 12, 8] : [10, 18, 11, 16, 6]
      );
    };

    rec.onerror = (ev) => {
      if (finished) return;
      finished = true;
      params.onError(
        ev.error === 'not-allowed'
          ? 'Izin mikrofon ditolak peramban.'
          : `Dikte suara terhenti: ${ev.error}`
      );
    };

    rec.onend = () => {
      if (finished) return;
      finished = true;
      params.onDone(accumulated.trim());
    };

    rec.start();
    return {
      stop: () => {
        try {
          rec.stop();
        } catch {
          if (!finished) {
            finished = true;
            params.onDone(accumulated.trim());
          }
        }
      },
    };
  }

  /* Fallback: MediaRecorder -> POST /v1/speech:transcribe (<= 60s, <= 4 MB) */
  let mediaStream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  let rafId = 0;
  let audioCtx: AudioContext | null = null;
  const chunks: BlobPart[] = [];

  navigator.mediaDevices
    .getUserMedia({ audio: true })
    .then((stream) => {
      mediaStream = stream;
      audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);
      const freq = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        analyser.getByteFrequencyData(freq);
        const bars = [2, 5, 8, 11, 14].map((idx) =>
          Math.max(4, Math.min(20, Math.round((freq[idx] / 255) * 20)))
        );
        params.onLevels(bars);
        rafId = window.requestAnimationFrame(tick);
      };
      rafId = window.requestAnimationFrame(tick);

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/mp4';
      recorder = new MediaRecorder(stream, { mimeType });
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };
      recorder.onstop = async () => {
        window.cancelAnimationFrame(rafId);
        mediaStream?.getTracks().forEach((t) => t.stop());
        await audioCtx?.close().catch(() => {});
        try {
          const blob = new Blob(chunks, { type: mimeType });
          const transcript = await transcribeShortClip({
            user: params.user,
            blob,
            lang: 'ja-JP',
          });
          params.onDone(transcript);
        } catch (err) {
          params.onError(
            err instanceof Error ? err.message : 'Gagal mentranskripsi rekaman suara.'
          );
        }
      };
      recorder.start();
    })
    .catch(() => {
      params.onError('Mikrofon tidak dapat diakses pada perangkat ini.');
    });

  return {
    stop: () => {
      if (recorder && recorder.state !== 'inactive') {
        recorder.stop();
      } else {
        window.cancelAnimationFrame(rafId);
        mediaStream?.getTracks().forEach((t) => t.stop());
      }
    },
  };
}
