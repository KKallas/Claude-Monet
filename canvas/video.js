// A video written picture by picture: H.264 by the browser's own encoder (WebCodecs), in an MP4 (mp4-muxer). Each
// picture is given its place in time, so the video plays at its own rate however slowly it was drawn.
import { Muxer, ArrayBufferTarget } from 'mp4-muxer';

// H.264 High, then Main, then Baseline; level 5.1 holds up to 4096 x 2304
const CODECS = ['avc1.640033', 'avc1.4d0033', 'avc1.42e033', 'avc1.640028', 'avc1.42e028'];

export const canWrite = () => typeof VideoEncoder === 'function' && typeof VideoFrame === 'function';

/** A writer for pictures of `width` x `height` (even) at `fps`, or null where this browser cannot write H.264. */
export async function videoWriter({ width, height, fps, bitrate = 12_000_000 }) {
  if (!canWrite()) return null;
  let config = null;
  for (const codec of CODECS) {
    const c = { codec, width, height, bitrate, framerate: fps, avc: { format: 'avc' } };
    try { if ((await VideoEncoder.isConfigSupported(c)).supported) { config = c; break; } } catch { /* not this one */ }
  }
  if (!config) return null;
  const target = new ArrayBufferTarget();
  const muxer = new Muxer({ target, video: { codec: 'avc', width, height, frameRate: fps }, fastStart: 'in-memory' });
  let failed = null;
  const encoder = new VideoEncoder({ output: (chunk, meta) => muxer.addVideoChunk(chunk, meta), error: (e) => { failed = e; } });
  encoder.configure(config);
  const us = 1e6 / fps;
  return {
    /** The picture now on `source` (a canvas) as the video's picture `i`. */
    add(source, i) {
      if (failed) throw failed;
      const frame = new VideoFrame(source, { timestamp: Math.round(i * us), duration: Math.round(us) });
      encoder.encode(frame, { keyFrame: i % Math.max(1, Math.round(fps * 2)) === 0 });
      frame.close();
    },
    /** Pictures given but not written yet: wait while there are many. */
    get backlog() { return encoder.encodeQueueSize; },
    async finish() {
      await encoder.flush();
      if (failed) throw failed;
      muxer.finalize();
      encoder.close();
      return new Blob([target.buffer], { type: 'video/mp4' });
    },
    cancel() { try { encoder.close(); } catch { /* closed */ } },
  };
}
