class PCMProcessor extends AudioWorkletProcessor {
  process(inputs) {
    if (inputs.length > 0 && inputs[0].length > 0) {
      this.port.postMessage(new Float32Array(inputs[0][0]));
    }
    return true;
  }
}
registerProcessor("pcm-recorder-processor", PCMProcessor);
