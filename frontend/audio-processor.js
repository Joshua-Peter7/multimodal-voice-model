/**
 * audio-processor.js - AudioWorklet for streaming audio to WebSocket
 * This runs in a separate thread for better performance
 */
class AudioProcessorWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.port.onmessage = (e) => {
      if (e.data.command === 'start') {
        // Worklet started
      } else if (e.data.command === 'stop') {
        // Worklet stopping
      }
    };
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channelData = input[0];
      // Convert float32 to int16
      const int16Data = this.float32ToInt16(channelData);
      // Send to main thread
      this.port.postMessage({ type: 'audio', data: int16Data });
    }
    return true; // Keep processing
  }

  float32ToInt16(float32Array) {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16Array;
  }
}

registerProcessor('audio-processor', AudioProcessorWorklet);
