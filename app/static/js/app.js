const log = (r, t) => {
  const p = document.getElementById("transcript");
  p.textContent += `\n[${r}] ${t}`;
  p.scrollTop = p.scrollHeight;
};

document.getElementById("callme").onclick = async () => {
  const r = await fetch("/api/call-me", { method: "POST" });
  log("system", r.ok ? "Calling your mobile…" : "Call failed (are you logged in?)");
};

document.getElementById("talk").onclick = async () => {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/talk`);
  ws.binaryType = "arraybuffer";

  const recCtx = new AudioContext({ sampleRate: 16000 });
  await recCtx.audioWorklet.addModule("/static/js/pcm-recorder-processor.js");
  const playCtx = new AudioContext({ sampleRate: 24000 });
  await playCtx.audioWorklet.addModule("/static/js/pcm-player-processor.js");
  const player = new AudioWorkletNode(playCtx, "pcm-player-processor");
  player.connect(playCtx.destination);

  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      const m = JSON.parse(e.data);
      if (m.type === "interrupt") player.port.postMessage({ command: "endOfAudio" });
      else if (m.type === "transcript") log(m.role, m.text);
    } else {
      player.port.postMessage(e.data);   // 24kHz PCM ArrayBuffer
    }
  };

  const mic = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
  const src = recCtx.createMediaStreamSource(mic);
  const rec = new AudioWorkletNode(recCtx, "pcm-recorder-processor");
  src.connect(rec);
  rec.port.onmessage = (ev) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    const f = ev.data, pcm = new Int16Array(f.length);
    for (let i = 0; i < f.length; i++) pcm[i] = Math.max(-1, Math.min(1, f[i])) * 0x7fff;
    ws.send(pcm.buffer);
  };
  log("system", "Connected — start speaking.");
};
