// Runs on the audio thread, so a busy page cannot drop microphone frames. Converts whatever rate
// the browser captures at (usually 48 kHz) to the 16 kHz mono Int16 the server expects, and posts
// exactly 20 ms (320 samples) at a time.
//
// Downsampling averages the input samples each output sample spans (a box filter). That is a
// crude low-pass, but it keeps most of the aliasing out of the 0–8 kHz band a speech recogniser
// uses — plain decimation, which the Phase 3 test page used, folds everything above 8 kHz into it.

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 320;

class VaaniCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / TARGET_RATE;
    this.pending = [];
    this.position = 0;
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) this.pending.push(channel[i]);

    while (this.position + this.step <= this.pending.length) {
      const start = Math.floor(this.position);
      const end = Math.max(start + 1, Math.floor(this.position + this.step));
      let sum = 0;
      for (let j = start; j < end; j++) sum += this.pending[j];
      const sample = Math.max(-1, Math.min(1, sum / (end - start)));
      this.frame[this.filled++] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      if (this.filled === FRAME_SAMPLES) {
        this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
        this.frame = new Int16Array(FRAME_SAMPLES);
        this.filled = 0;
      }
      this.position += this.step;
    }

    const consumed = Math.floor(this.position);
    if (consumed > 0) {
      this.pending.splice(0, consumed);
      this.position -= consumed;
    }
    return true;
  }
}

registerProcessor("vaani-capture", VaaniCapture);
