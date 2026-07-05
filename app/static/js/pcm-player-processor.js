class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 24000 * 180;
    this.buffer = new Float32Array(this.bufferSize);
    this.writeIndex = 0; this.readIndex = 0;
    this.port.onmessage = (e) => {
      if (e.data.command === "endOfAudio") { this.readIndex = this.writeIndex; return; }
      const s = new Int16Array(e.data);
      for (let i = 0; i < s.length; i++) {
        this.buffer[this.writeIndex] = s[i] / 32768;
        this.writeIndex = (this.writeIndex + 1) % this.bufferSize;
        if (this.writeIndex === this.readIndex) this.readIndex = (this.readIndex + 1) % this.bufferSize;
      }
    };
  }
  process(_, outputs) {
    const out = outputs[0];
    for (let f = 0; f < out[0].length; f++) {
      out[0][f] = this.buffer[this.readIndex];
      if (out.length > 1) out[1][f] = this.buffer[this.readIndex];
      if (this.readIndex !== this.writeIndex) this.readIndex = (this.readIndex + 1) % this.bufferSize;
    }
    return true;
  }
}
registerProcessor("pcm-player-processor", PCMPlayerProcessor);
