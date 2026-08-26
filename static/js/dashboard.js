/* dashboard.js - live webcam monitoring, metrics, charts and multi-alert audio.
 *
 * Audio model (Features 1/2/4): the backend AlertManager decides the single
 * active `alert_type` + `alert_sound`. The browser plays ONLY that one sound
 * (looped) and switches/stops it on transitions - so two alarms never overlap
 * and we never call play() on every frame.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const feed = $("videoFeed");
  const placeholder = $("videoPlaceholder");
  const startBtn = $("startBtn");
  const stopBtn = $("stopBtn");
  const resetBtn = $("resetBtn");
  const alarmToggle = $("alarmToggle");
  const alarmFlash = $("alarmFlash");
  const statusCard = $("statusCard");

  // status-panel pills
  const stFace = $("stFace");
  const stEyes = $("stEyes");
  const stDrowsy = $("stDrowsy");
  const stAttention = $("stAttention");
  const stGlasses = $("stGlasses");
  const stCoverage = $("stCoverage");
  const activeAlert = $("activeAlert");

  // safety panel + mobile + misc (Features 6-20)
  const voiceToggle = $("voiceToggle");
  const riskPill = $("riskPill");
  const attNum = $("attNum");
  const attFill = $("attFill");
  const safeNum = $("safeNum");
  const safeFill = $("safeFill");
  const stDistract = $("stDistract");
  const stFatigue = $("stFatigue");
  const notifBadge = $("notifBadge");
  const notifProvider = $("notifProvider");
  const videoStorage = $("videoStorage");
  const notifResult = $("notifResult");
  const testNotifyBtn = $("testNotifyBtn");
  const breakBanner = $("breakBanner");
  const breakTextEl = $("breakText");
  const breakDismiss = $("breakDismiss");
  const summaryModal = $("summaryModal");
  const summaryBody = $("summaryBody");

  if (voiceToggle) voiceToggle.checked = !!window.VOICE_ENABLED;
  const VOICE_COOLDOWN = (window.VOICE_COOLDOWN || 8) * 1000;
  let lastVoiceKey = null;
  let lastVoiceAt = 0;
  let breakDismissed = false;

  // audio elements, keyed by filename via window.ALARM_SOUNDS
  const SOUNDS = {};
  Object.keys(window.ALARM_SOUNDS || {}).forEach((file) => {
    SOUNDS[file] = $(window.ALARM_SOUNDS[file]);
  });
  const allAudio = Object.values(SOUNDS).filter(Boolean);

  let polling = null;
  let currentSound = null;   // filename currently playing (or null)
  const MAX_POINTS = 60;

  // ---------- charts ----------
  const lineOpts = (yMax) => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: { ticks: { color: "#98a2b3", maxTicksLimit: 6 }, grid: { color: "#232a33" } },
      y: { min: 0, max: yMax, ticks: { color: "#98a2b3" }, grid: { color: "#232a33" } },
    },
    plugins: { legend: { labels: { color: "#cbd5e1" } } },
  });

  const scoreChart = new Chart($("scoreChart"), {
    type: "line",
    data: { labels: [], datasets: [{
      label: "Drowsiness score", data: [],
      borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,.15)",
      fill: true, tension: .3, pointRadius: 0, borderWidth: 2,
    }]},
    options: lineOpts(100),
  });

  const earMarChart = new Chart($("earMarChart"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "EAR", data: [], borderColor: "#22c55e", tension: .3, pointRadius: 0, borderWidth: 2 },
      { label: "MAR", data: [], borderColor: "#f59e0b", tension: .3, pointRadius: 0, borderWidth: 2 },
    ]},
    options: lineOpts(1),
  });

  const safetyChart = new Chart($("safetyChart"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "Attention", data: [], borderColor: "#22c55e",
        backgroundColor: "rgba(34,197,94,.12)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 },
      { label: "Safety", data: [], borderColor: "#3b82f6",
        backgroundColor: "rgba(59,130,246,.12)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 },
    ]},
    options: lineOpts(100),
  });

  const distChart = new Chart($("distChart"), {
    type: "doughnut",
    data: {
      labels: ["Forward", "Left", "Right", "Down", "No face"],
      datasets: [{
        data: [0, 0, 0, 0, 0],
        backgroundColor: ["#22c55e", "#f59e0b", "#eab308", "#a855f7", "#64748b"],
        borderColor: "#171b22", borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "right", labels: { color: "#cbd5e1", boxWidth: 12 } } },
    },
  });

  function pushPoint(chart, label, values) {
    chart.data.labels.push(label);
    values.forEach((v, i) => chart.data.datasets[i].data.push(v));
    if (chart.data.labels.length > MAX_POINTS) {
      chart.data.labels.shift();
      chart.data.datasets.forEach((d) => d.data.shift());
    }
    chart.update("none");
  }

  // ---------- camera control ----------
  async function cameraAction(action) {
    const r = await fetch(`/api/camera/${action}`, { method: "POST" });
    return r.json();
  }

  // Browsers only allow audio to play after a user gesture. "Start Camera"
  // is that gesture: prime each clip (muted play->pause) so later programmatic
  // play() calls are permitted.
  function unlockAudio() {
    allAudio.forEach((a) => {
      try {
        a.muted = true;
        const p = a.play();
        if (p && p.then) p.then(() => { a.pause(); a.currentTime = 0; a.muted = false; })
                          .catch(() => { a.muted = false; });
        else { a.pause(); a.currentTime = 0; a.muted = false; }
      } catch (e) { a.muted = false; }
    });
  }

  startBtn.addEventListener("click", async () => {
    startBtn.disabled = true;
    unlockAudio();
    const res = await cameraAction("start");
    if (!res.ok) {
      alert("Could not open the camera.\n\n" +
            "Make sure a webcam is connected and not used by another app. " +
            "You can also change CAMERA_INDEX in config.py.");
      startBtn.disabled = false;
      return;
    }
    feed.src = "/video_feed?" + Date.now();
    feed.style.display = "block";
    placeholder.style.display = "none";
    stopBtn.disabled = false;
    startPolling();
  });

  stopBtn.addEventListener("click", async () => {
    await cameraAction("stop");
    feed.style.display = "none";
    feed.src = "";
    placeholder.style.display = "block";
    placeholder.querySelector("p").textContent = "Camera stopped";
    stopBtn.disabled = true;
    startBtn.disabled = false;
    stopPolling();
    setLevel("alert", "Idle", 0);
    stopAllAudio();
    try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) {}
    await showSessionSummary();
    resetMonitor();
  });

  resetBtn.addEventListener("click", () => cameraAction("reset"));

  // If the user unchecks the alarm while one is sounding, stop it immediately.
  alarmToggle.addEventListener("change", () => {
    if (!alarmToggle.checked) stopAllAudio();
  });

  // ---------- mobile push test (Feature 18/19) ----------
  if (testNotifyBtn) testNotifyBtn.addEventListener("click", async () => {
    testNotifyBtn.disabled = true;
    notifResult.textContent = "Sending…";
    try {
      const r = await (await fetch("/api/notify/test", { method: "POST" })).json();
      if (r.ok && r.provider === "fcm")
        notifResult.textContent = "✓ Sent to your device (" + r.detail + ")";
      else if (r.ok)
        notifResult.textContent = "✓ Simulated (no Firebase configured). " +
          "See docs/FCM_SETUP.md to enable real push.";
      else
        notifResult.textContent = "✗ " + (r.detail || "failed");
    } catch (e) {
      notifResult.textContent = "✗ request failed";
    }
    testNotifyBtn.disabled = false;
  });

  // ---------- session summary modal (Feature 16) ----------
  const SUMMARY_ROWS = [
    ["duration_hms", "Session length"],
    ["avg_attention_score", "Avg attention"],
    ["final_safety_score", "Final safety"],
    ["final_risk_level", "Final risk"],
    ["drowsiness_events", "Drowsy events"],
    ["yawn_count", "Yawns"],
    ["left_look_events", "Left glances"],
    ["right_look_events", "Right glances"],
    ["face_covered_events", "Face covered"],
    ["total_distraction_hms", "Time distracted"],
  ];

  async function showSessionSummary() {
    let sum;
    try { sum = await (await fetch("/api/session/summary")).json(); }
    catch (e) { return; }
    if (!sum || !sum.duration_seconds) return;   // nothing meaningful to show
    summaryBody.innerHTML = "";
    SUMMARY_ROWS.forEach(([k, label]) => {
      let v = sum[k];
      if (v === undefined || v === null) v = "–";
      const cell = document.createElement("div");
      cell.className = "summary-cell";
      cell.innerHTML = `<div class="sc-num">${v}</div><div class="sc-lbl">${label}</div>`;
      summaryBody.appendChild(cell);
    });
    summaryModal.classList.remove("hidden");
  }

  const summaryClose = $("summaryClose");
  if (summaryClose) summaryClose.addEventListener("click",
    () => summaryModal.classList.add("hidden"));
  const exportCsvBtn = $("exportCsvBtn");
  const exportJsonBtn = $("exportJsonBtn");
  if (exportCsvBtn) exportCsvBtn.addEventListener("click",
    () => { window.location = "/api/events/export?fmt=csv"; });
  if (exportJsonBtn) exportJsonBtn.addEventListener("click",
    () => { window.location = "/api/events/export?fmt=json"; });

  // ---------- polling ----------
  function startPolling() {
    if (polling) return;
    polling = setInterval(updateState, 400);
  }
  function stopPolling() {
    clearInterval(polling);
    polling = null;
  }

  async function updateState() {
    let s;
    try { s = await (await fetch("/api/state")).json(); }
    catch (e) { return; }
    if (!s) return;

    $("mEar").textContent = fmt(s.ear);
    $("mMar").textContent = fmt(s.mar);
    $("mPitch").textContent = s.pitch != null ? s.pitch.toFixed(0) + "°" : "-";
    $("mYaw").textContent = s.yaw != null ? s.yaw.toFixed(0) + "°" : "-";
    $("mPerclos").textContent = s.perclos != null ? (s.perclos * 100).toFixed(0) + "%" : "-";
    $("mCnn").textContent = s.cnn_closed_prob != null ? s.cnn_closed_prob.toFixed(2) : "n/a";

    $("cBlink").textContent = s.blink_count || 0;
    $("cYawn").textContent = s.yawn_count || 0;
    $("cNod").textContent = s.nod_count || 0;
    $("cDrowsy").textContent = s.drowsy_events || 0;

    const level = (s.level || "ALERT").toLowerCase();
    setLevel(level, s.status_text || "-", s.score || 0);

    updateMonitor(s);
    updateAudio(s);
    updateSafety(s);
    updateMobile(s);
    updateBreak(s);
    maybeSpeak(s);

    const t = new Date().toLocaleTimeString().split(" ")[0];
    pushPoint(scoreChart, t, [s.score || 0]);
    pushPoint(earMarChart, t, [s.ear || 0, s.mar || 0]);
    if (s.attention_score != null || s.safety_score != null) {
      pushPoint(safetyChart, t, [s.attention_score || 0, s.safety_score || 0]);
    }
    updateDistribution(s.attention_distribution);
  }

  function setLevel(level, text, score) {
    statusCard.className = "card status-card level-" + level;
    $("statusText").textContent = text;
    $("scoreNum").textContent = Math.round(score);
    const fill = $("scoreFill");
    fill.style.width = Math.min(score, 100) + "%";
    fill.style.background = level === "drowsy" ? "#ef4444"
                          : level === "warning" ? "#f59e0b" : "#22c55e";
  }

  // ---------- real-time monitoring panel ----------
  function pill(el, text, state) {
    if (!el) return;
    el.textContent = text;
    el.className = "pill st-" + state;
  }

  function updateMonitor(s) {
    const faceOn = !!s.face_detected;

    // Face
    pill(stFace, faceOn ? "Detected" : "Not detected", faceOn ? "normal" : "alert");

    // Eyes
    if (!faceOn) pill(stEyes, "–", "idle");
    else pill(stEyes, s.eyes_closed ? "Closed" : "Open", s.eyes_closed ? "warn" : "normal");

    // Drowsiness
    if (s.drowsiness) pill(stDrowsy, "ALERT", "alert");
    else if ((s.level || "") === "WARNING") pill(stDrowsy, "Warning", "warn");
    else pill(stDrowsy, faceOn ? "Normal" : "–", faceOn ? "normal" : "idle");

    // Attention (side-way looking)
    const att = s.attention;
    if (att === "left") pill(stAttention, "Looking LEFT", "alert");
    else if (att === "right") pill(stAttention, "Looking RIGHT", "alert");
    else if (att === "no_face" || !faceOn) pill(stAttention, "–", "idle");
    else pill(stAttention, "Forward", "normal");

    // Sunglasses (status only)
    if (!faceOn) pill(stGlasses, "–", "idle");
    else pill(stGlasses, s.sunglasses_detected ? "Detected" : "Not detected",
              s.sunglasses_detected ? "warn" : "normal");

    // Face coverage
    const covMap = {
      clear: ["Clear", "normal"],
      partial: ["Partially covered", "warn"],
      covered: ["COVERED", "alert"],
      none: ["Not visible", "alert"],
    };
    const cm = covMap[s.face_coverage] || ["–", "idle"];
    pill(stCoverage, cm[0], cm[1]);

    // Active-alert chip in the panel header
    if (s.alert_label) {
      activeAlert.textContent = s.alert_label;
      activeAlert.classList.remove("hidden");
      const high = s.face_covered || s.drowsiness;
      activeAlert.className = "active-alert " + (high ? "aa-alert" : "aa-warn");
    } else {
      activeAlert.classList.add("hidden");
    }
  }

  function resetMonitor() {
    [stFace, stEyes, stDrowsy, stAttention, stGlasses, stCoverage]
      .forEach((el) => pill(el, "–", "idle"));
    activeAlert.classList.add("hidden");
    pill(riskPill, "RISK –", "idle");
    pill(stDistract, "–", "idle");
    pill(stFatigue, "–", "idle");
    if (attNum) attNum.textContent = "–";
    if (safeNum) safeNum.textContent = "–";
    if (attFill) attFill.style.width = "0%";
    if (safeFill) safeFill.style.width = "0%";
    if (breakBanner) breakBanner.classList.add("hidden");
    breakDismissed = false;
    lastVoiceKey = null;
  }

  // ---------- driver-safety panel (Features 6-9, 15) ----------
  function scoreColor(v) {
    return v >= 75 ? "#22c55e" : v >= 45 ? "#f59e0b" : "#ef4444";
  }
  function bandState(v) {
    return v >= 75 ? "normal" : v >= 45 ? "warn" : "alert";
  }

  function updateSafety(s) {
    const att = s.attention_score;
    const safe = s.safety_score;
    if (att != null) {
      attNum.textContent = Math.round(att);
      attFill.style.width = Math.max(0, Math.min(att, 100)) + "%";
      attFill.style.background = scoreColor(att);
    }
    if (safe != null) {
      safeNum.textContent = Math.round(safe);
      safeFill.style.width = Math.max(0, Math.min(safe, 100)) + "%";
      safeFill.style.background = scoreColor(safe);
    }
    const risk = s.risk_level || null;
    if (risk) {
      const rs = risk === "LOW" ? "normal" : risk === "MEDIUM" ? "warn" : "alert";
      pill(riskPill, "RISK " + risk, rs);
    }
    // distraction timer
    if (s.distraction_active) {
      const d = (s.distraction_duration || 0).toFixed(1) + "s";
      pill(stDistract, d, s.distraction_alert ? "alert" : "warn");
    } else {
      pill(stDistract, s.face_detected ? "None" : "–", s.face_detected ? "normal" : "idle");
    }
    // fatigue trend
    const ft = s.fatigue_trend;
    if (ft === "INCREASING") pill(stFatigue, "Rising ↑", "alert");
    else if (ft === "DECREASING") pill(stFatigue, "Easing ↓", "normal");
    else if (ft === "STABLE") pill(stFatigue, "Stable →", "normal");
    else pill(stFatigue, "–", "idle");
  }

  function updateDistribution(dist) {
    if (!dist) return;
    distChart.data.datasets[0].data = [
      dist.forward || 0, dist.left || 0, dist.right || 0,
      dist.down || 0, dist.none || 0,
    ];
    distChart.update("none");
  }

  // ---------- mobile-alerts / privacy card (Features 18, 20) ----------
  function updateMobile(s) {
    if (s.video_storage != null && videoStorage)
      videoStorage.textContent = s.video_storage ? "ON" : "OFF";
    if (s.camera_processing && $("camProc"))
      $("camProc").textContent = s.camera_processing;
    const n = s.notifications;
    if (n && notifBadge) {
      if (!n.enabled) { notifBadge.textContent = "OFF"; notifBadge.className = "badge badge-off"; }
      else if (n.configured) { notifBadge.textContent = "READY"; notifBadge.className = "badge badge-on"; }
      else { notifBadge.textContent = "SIMULATED"; notifBadge.className = "badge badge-warnb"; }
      if (notifProvider) notifProvider.textContent = n.provider || "–";
    }
  }

  // ---------- break recommendation (Feature 12) ----------
  function updateBreak(s) {
    if (s.break_recommended && !breakDismissed) {
      breakTextEl.textContent = s.break_text || "Take a short break.";
      breakBanner.classList.remove("hidden");
    } else if (!s.break_recommended) {
      breakBanner.classList.add("hidden");
      breakDismissed = false;   // re-arm for the next episode
    }
  }
  if (breakDismiss) breakDismiss.addEventListener("click", () => {
    breakBanner.classList.add("hidden");
    breakDismissed = true;
  });

  // ---------- voice warnings (Feature 11) via Web Speech API ----------
  function maybeSpeak(s) {
    if (!voiceToggle || !voiceToggle.checked) return;
    if (!("speechSynthesis" in window)) return;
    const key = s.voice_key, text = s.voice_text;
    if (!key || !text) { if (!s.alert_active) lastVoiceKey = null; return; }
    const now = Date.now();
    if (key === lastVoiceKey && (now - lastVoiceAt) < VOICE_COOLDOWN) return;
    lastVoiceKey = key;
    lastVoiceAt = now;
    try {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.02; u.pitch = 1.0; u.volume = 1.0;
      window.speechSynthesis.cancel();   // never overlap voices
      window.speechSynthesis.speak(u);
    } catch (e) { /* speech unavailable */ }
  }

  // ---------- alert audio (single active sound, driven by AlertManager) ----------
  function stopAllAudio() {
    allAudio.forEach((a) => { try { a.pause(); a.currentTime = 0; } catch (e) {} });
    currentSound = null;
    alarmFlash.classList.remove("on", "warn");
  }

  function updateAudio(s) {
    const desired = (alarmToggle.checked && s.alert_active) ? s.alert_sound : null;

    if (desired === currentSound) {
      // same alert still active -> the looped clip keeps playing; nothing to do.
      return;
    }
    // stop the previous sound
    if (currentSound && SOUNDS[currentSound]) {
      try { SOUNDS[currentSound].pause(); SOUNDS[currentSound].currentTime = 0; } catch (e) {}
    }
    // start the new one (if any)
    if (desired && SOUNDS[desired]) {
      try { SOUNDS[desired].currentTime = 0; SOUNDS[desired].play().catch(() => {}); } catch (e) {}
    }
    currentSound = desired;

    // visual flash: red for high-severity, amber tint for side-look
    if (desired) {
      alarmFlash.classList.add("on");
      alarmFlash.classList.toggle("warn",
        (s.alert_type || "").indexOf("SIDE_LOOK") === 0);
      alarmFlash.classList.toggle("crit", (s.escalation_level || 0) >= 3);
    } else {
      alarmFlash.classList.remove("on", "warn", "crit");
    }
  }

  function fmt(v) { return (v === null || v === undefined) ? "-" : Number(v).toFixed(2); }

  // populate privacy + mobile-alerts card on load (before camera start)
  (async () => {
    try { updateMobile(await (await fetch("/api/state")).json()); }
    catch (e) { /* server not ready yet */ }
  })();
})();
