/*
 * dashboard.js
 *
 * Supports:
 *
 * LOCAL:
 *   OpenCV webcam -> /video_feed
 *
 * PRODUCTION:
 *   Browser/mobile camera -> getUserMedia()
 *   -> /api/camera/frame
 *   -> existing Flask AI pipeline
 */

(function () {

  "use strict";


  // ============================================================
  // ELEMENTS
  // ============================================================

  const $ = (id) =>
    document.getElementById(id);

  const feed =
    $("videoFeed");

  const browserCamera =
    $("browserCamera");

  const placeholder =
    $("videoPlaceholder");

  const startBtn =
    $("startBtn");

  const stopBtn =
    $("stopBtn");

  const resetBtn =
    $("resetBtn");

  const alarmToggle =
    $("alarmToggle");

  const alarmFlash =
    $("alarmFlash");

  const statusCard =
    $("statusCard");

  const cameraModeBadge =
    $("cameraModeBadge");


  const stFace =
    $("stFace");

  const stEyes =
    $("stEyes");

  const stDrowsy =
    $("stDrowsy");

  const stAttention =
    $("stAttention");

  const stGlasses =
    $("stGlasses");

  const stCoverage =
    $("stCoverage");

  const activeAlert =
    $("activeAlert");


  const voiceToggle =
    $("voiceToggle");

  const riskPill =
    $("riskPill");

  const attNum =
    $("attNum");

  const attFill =
    $("attFill");

  const safeNum =
    $("safeNum");

  const safeFill =
    $("safeFill");

  const stDistract =
    $("stDistract");

  const stFatigue =
    $("stFatigue");

  const notifBadge =
    $("notifBadge");

  const notifProvider =
    $("notifProvider");

  const videoStorage =
    $("videoStorage");

  const notifResult =
    $("notifResult");

  const testNotifyBtn =
    $("testNotifyBtn");

  const breakBanner =
    $("breakBanner");

  const breakTextEl =
    $("breakText");

  const breakDismiss =
    $("breakDismiss");

  const summaryModal =
    $("summaryModal");

  const summaryBody =
    $("summaryBody");


  // ============================================================
  // CAMERA STATE
  // ============================================================

  let mediaStream = null;

  let cameraRunning = false;

  let frameTimer = null;

  let processingFrame = false;

  let polling = null;

  let currentSound = null;

  const MAX_POINTS = 60;

  const FRAME_INTERVAL =
    180;


  // ============================================================
  // VOICE
  // ============================================================

  if (voiceToggle) {

    voiceToggle.checked =
      !!window.VOICE_ENABLED;

  }

  const VOICE_COOLDOWN =
    (window.VOICE_COOLDOWN || 8)
    * 1000;

  let lastVoiceKey = null;

  let lastVoiceAt = 0;

  let breakDismissed = false;


  // ============================================================
  // AUDIO
  // ============================================================

  const SOUNDS = {};

  Object.keys(
    window.ALARM_SOUNDS || {}
  ).forEach(
    (file) => {

      SOUNDS[file] =
        $(
          window.ALARM_SOUNDS[file]
        );

    }
  );

  const allAudio =
    Object.values(SOUNDS)
      .filter(Boolean);


  // ============================================================
  // CHARTS
  // ============================================================

  const lineOpts = (yMax) => ({

    responsive: true,

    maintainAspectRatio: false,

    animation: false,

    scales: {

      x: {
        ticks: {
          color: "#98a2b3",
          maxTicksLimit: 6
        },

        grid: {
          color: "#232a33"
        }
      },

      y: {
        min: 0,
        max: yMax,

        ticks: {
          color: "#98a2b3"
        },

        grid: {
          color: "#232a33"
        }
      }

    },

    plugins: {

      legend: {
        labels: {
          color: "#cbd5e1"
        }
      }

    }

  });


  const scoreChart =
    new Chart(
      $("scoreChart"),
      {
        type: "line",

        data: {
          labels: [],

          datasets: [{
            label:
              "Drowsiness score",

            data: [],

            borderColor:
              "#3b82f6",

            backgroundColor:
              "rgba(59,130,246,.15)",

            fill: true,

            tension: .3,

            pointRadius: 0,

            borderWidth: 2
          }]
        },

        options:
          lineOpts(100)
      }
    );


  const earMarChart =
    new Chart(
      $("earMarChart"),
      {
        type: "line",

        data: {

          labels: [],

          datasets: [

            {
              label: "EAR",

              data: [],

              borderColor:
                "#22c55e",

              tension: .3,

              pointRadius: 0,

              borderWidth: 2
            },

            {
              label: "MAR",

              data: [],

              borderColor:
                "#f59e0b",

              tension: .3,

              pointRadius: 0,

              borderWidth: 2
            }

          ]

        },

        options:
          lineOpts(1)
      }
    );


  const safetyChart =
    new Chart(
      $("safetyChart"),
      {
        type: "line",

        data: {

          labels: [],

          datasets: [

            {
              label: "Attention",

              data: [],

              borderColor:
                "#22c55e",

              backgroundColor:
                "rgba(34,197,94,.12)",

              fill: true,

              tension: .3,

              pointRadius: 0,

              borderWidth: 2
            },

            {
              label: "Safety",

              data: [],

              borderColor:
                "#3b82f6",

              backgroundColor:
                "rgba(59,130,246,.12)",

              fill: true,

              tension: .3,

              pointRadius: 0,

              borderWidth: 2
            }

          ]

        },

        options:
          lineOpts(100)
      }
    );


  const distChart =
    new Chart(
      $("distChart"),
      {

        type: "doughnut",

        data: {

          labels: [
            "Forward",
            "Left",
            "Right",
            "Down",
            "No face"
          ],

          datasets: [{

            data: [
              0, 0, 0, 0, 0
            ],

            backgroundColor: [
              "#22c55e",
              "#f59e0b",
              "#eab308",
              "#a855f7",
              "#64748b"
            ],

            borderColor:
              "#171b22",

            borderWidth: 2

          }]

        },

        options: {

          responsive: true,

          maintainAspectRatio: false,

          plugins: {

            legend: {

              position: "right",

              labels: {
                color:
                  "#cbd5e1",

                boxWidth: 12
              }

            }

          }

        }

      }
    );


  function pushPoint(
    chart,
    label,
    values
  ) {

    chart.data.labels.push(
      label
    );

    values.forEach(
      (v, i) => {

        chart
          .data
          .datasets[i]
          .data
          .push(v);

      }
    );

    if (
      chart.data.labels.length
      > MAX_POINTS
    ) {

      chart.data.labels.shift();

      chart.data.datasets
        .forEach(
          (d) =>
            d.data.shift()
        );

    }

    chart.update("none");
  }


  // ============================================================
  // AUDIO UNLOCK
  // ============================================================

  function unlockAudio() {

    allAudio.forEach(
      (a) => {

        try {

          a.muted = true;

          const p = a.play();

          if (
            p &&
            p.then
          ) {

            p.then(
              () => {

                a.pause();

                a.currentTime = 0;

                a.muted = false;

              }
            ).catch(
              () => {

                a.muted = false;

              }
            );

          }

        } catch (e) {

          a.muted = false;

        }

      }
    );
  }


  // ============================================================
  // CAMERA API
  // ============================================================

  async function cameraAction(
    action
  ) {

    const response =
      await fetch(
        `/api/camera/${action}`,
        {
          method: "POST"
        }
      );

    return response.json();
  }


  // ============================================================
  // BROWSER CAMERA
  // ============================================================

  async function startBrowserCamera() {

    if (
      !navigator.mediaDevices ||
      !navigator.mediaDevices.getUserMedia
    ) {

      throw new Error(
        "Camera API is not supported by this browser."
      );

    }


    // Request front camera.
    mediaStream =
      await navigator.mediaDevices
        .getUserMedia({

          video: {

            facingMode: {
              ideal: "user"
            },

            width: {
              ideal: 640
            },

            height: {
              ideal: 480
            },

            frameRate: {
              ideal: 15,
              max: 20
            }

          },

          audio: false

        });


    browserCamera.srcObject =
      mediaStream;

    browserCamera.style.display =
      "block";

    feed.style.display =
      "none";

    placeholder.style.display =
      "none";


    await browserCamera.play();


    const result =
      await fetch(
        "/api/camera/browser/start",
        {
          method: "POST"
        }
      );

    const data =
      await result.json();


    if (!data.ok) {

      stopBrowserCamera();

      throw new Error(
        data.error ||
        "Could not start AI pipeline."
      );

    }


    cameraRunning = true;

    updateCameraBadge(
      "MOBILE CAMERA"
    );


    startFrameLoop();

    startPolling();

  }


  // ============================================================
  // CAPTURE FRAME
  // ============================================================

  function captureFrame() {

    if (
      !browserCamera.videoWidth ||
      !browserCamera.videoHeight
    ) {
      return null;
    }


    const canvas =
      document.createElement(
        "canvas"
      );

    canvas.width =
      Math.min(
        browserCamera.videoWidth,
        640
      );

    canvas.height =
      Math.round(
        canvas.width *
        browserCamera.videoHeight /
        browserCamera.videoWidth
      );


    const ctx =
      canvas.getContext(
        "2d"
      );


    ctx.drawImage(
      browserCamera,
      0,
      0,
      canvas.width,
      canvas.height
    );


    return canvas.toDataURL(
      "image/jpeg",
      0.70
    );

  }


  // ============================================================
  // SEND FRAME TO FLASK
  // ============================================================

  async function sendFrame() {

    if (
      !cameraRunning ||
      processingFrame
    ) {
      return;
    }

    if (
      browserCamera.readyState
      < 2
    ) {
      return;
    }


    const image =
      captureFrame();

    if (!image) {
      return;
    }


    processingFrame = true;


    try {

      const response =
        await fetch(
          "/api/camera/frame",
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json"
            },

            body: JSON.stringify({
              image: image
            })
          }
        );


      const data =
        await response.json();


      if (!data.ok) {

        console.warn(
          "Frame processing failed:",
          data.error
        );

        return;
      }


      // Display processed AI frame.
      if (data.frame) {

        feed.src =
          "data:image/jpeg;base64,"
          + data.frame;

        feed.style.display =
          "block";

      }


      if (data.state) {

        updateState(
          data.state
        );

      }

    } catch (error) {

      console.warn(
        "Camera frame request failed:",
        error
      );

    } finally {

      processingFrame = false;

    }

  }


  // ============================================================
  // FRAME LOOP
  // ============================================================

  function startFrameLoop() {

    stopFrameLoop();

    frameTimer =
      setInterval(
        sendFrame,
        FRAME_INTERVAL
      );

  }


  function stopFrameLoop() {

    if (frameTimer) {

      clearInterval(
        frameTimer
      );

      frameTimer = null;

    }

  }


  // ============================================================
  // STOP BROWSER CAMERA
  // ============================================================

  function stopBrowserCamera() {

    stopFrameLoop();

    cameraRunning = false;

    processingFrame = false;


    if (mediaStream) {

      mediaStream
        .getTracks()
        .forEach(
          (track) =>
            track.stop()
        );

      mediaStream = null;

    }


    browserCamera.srcObject =
      null;

    browserCamera.style.display =
      "none";

    feed.style.display =
      "none";

    feed.src = "";


    updateCameraBadge(
      "CAMERA OFF"
    );

  }


  // ============================================================
  // CAMERA BADGE
  // ============================================================

  function updateCameraBadge(
    text
  ) {

    if (!cameraModeBadge) {
      return;
    }

    cameraModeBadge.textContent =
      text;

    if (
      text === "CAMERA OFF"
    ) {

      cameraModeBadge.className =
        "badge badge-off";

    } else {

      cameraModeBadge.className =
        "badge badge-on";

    }

  }


  // ============================================================
  // START BUTTON
  // ============================================================

  startBtn.addEventListener(
    "click",
    async () => {

      startBtn.disabled = true;

      unlockAudio();


      try {

        if (
          window.PRODUCTION
          ||
          window.BROWSER_CAMERA_ENABLED
        ) {

          await startBrowserCamera();

        } else {

          const res =
            await cameraAction(
              "start"
            );


          if (!res.ok) {

            throw new Error(
              res.error ||
              "Could not open local camera."
            );

          }


          feed.src =
            "/video_feed?"
            + Date.now();

          feed.style.display =
            "block";

          placeholder.style.display =
            "none";

          stopBtn.disabled =
            false;

          cameraRunning =
            true;

          updateCameraBadge(
            "LOCAL CAMERA"
          );

          startPolling();

        }


        stopBtn.disabled =
          false;

      } catch (error) {

        console.error(
          error
        );

        alert(
          "Could not open the camera.\n\n"
          + error.message
          + "\n\n"
          + "Please allow camera permission "
          + "and make sure you are using HTTPS."
        );

        startBtn.disabled =
          false;

        stopBtn.disabled =
          true;

        stopBrowserCamera();

      }

    }
  );


  // ============================================================
  // STOP
  // ============================================================

  stopBtn.addEventListener(
    "click",
    async () => {

      stopBrowserCamera();

      try {

        await cameraAction(
          "stop"
        );

      } catch (e) {}


      feed.style.display =
        "none";

      feed.src = "";

      placeholder.style.display =
        "block";

      placeholder.querySelector(
        "p"
      ).textContent =
        "Camera stopped";


      stopBtn.disabled =
        true;

      startBtn.disabled =
        false;


      stopPolling();

      setLevel(
        "alert",
        "Idle",
        0
      );

      stopAllAudio();


      try {

        if (
          window.speechSynthesis
        ) {

          window.speechSynthesis.cancel();

        }

      } catch (e) {}


      await showSessionSummary();

      resetMonitor();

      updateCameraBadge(
        "CAMERA OFF"
      );

    }
  );


  // ============================================================
  // RESET
  // ============================================================

  resetBtn.addEventListener(
    "click",
    async () => {

      try {

        await cameraAction(
          "reset"
        );

      } catch (e) {}

      resetMonitor();

    }
  );


  // ============================================================
  // ALARM TOGGLE
  // ============================================================

  alarmToggle.addEventListener(
    "change",
    () => {

      if (
        !alarmToggle.checked
      ) {

        stopAllAudio();

      }

    }
  );


  // ============================================================
  // POLLING
  // ============================================================

  function startPolling() {

    if (polling) {
      return;
    }

    polling =
      setInterval(
        async () => {

          // Browser frame already provides
          // state, but polling keeps
          // prediction / notifications /
          // server-side values fresh.

          try {

            const response =
              await fetch(
                "/api/state"
              );

            const state =
              await response.json();

            if (
              !processingFrame
              && state
            ) {

              updateState(
                state
              );

            }

          } catch (e) {}

        },
        1000
      );

  }


  function stopPolling() {

    if (polling) {

      clearInterval(
        polling
      );

      polling = null;

    }

  }


  // ============================================================
  // STATE
  // ============================================================

  function updateState(s) {

    if (!s) {
      return;
    }


    $("mEar").textContent =
      fmt(s.ear);

    $("mMar").textContent =
      fmt(s.mar);

    $("mPitch").textContent =
      s.pitch != null
        ? s.pitch.toFixed(0) + "°"
        : "-";

    $("mYaw").textContent =
      s.yaw != null
        ? s.yaw.toFixed(0) + "°"
        : "-";

    $("mPerclos").textContent =
      s.perclos != null
        ? (
            s.perclos * 100
          ).toFixed(0)
          + "%"
        : "-";

    $("mCnn").textContent =
      s.cnn_closed_prob != null
        ? s.cnn_closed_prob.toFixed(2)
        : "n/a";


    $("cBlink").textContent =
      s.blink_count || 0;

    $("cYawn").textContent =
      s.yawn_count || 0;

    $("cNod").textContent =
      s.nod_count || 0;

    $("cDrowsy").textContent =
      s.drowsy_events || 0;


    const level =
      (
        s.level ||
        "ALERT"
      ).toLowerCase();


    setLevel(
      level,
      s.status_text || "-",
      s.score || 0
    );


    updateMonitor(s);

    updateAudio(s);

    updateSafety(s);

    updateMobile(s);

    updateBreak(s);

    maybeSpeak(s);


    const t =
      new Date()
        .toLocaleTimeString()
        .split(" ")[0];


    pushPoint(
      scoreChart,
      t,
      [s.score || 0]
    );


    pushPoint(
      earMarChart,
      t,
      [
        s.ear || 0,
        s.mar || 0
      ]
    );


    if (
      s.attention_score != null
      ||
      s.safety_score != null
    ) {

      pushPoint(
        safetyChart,
        t,
        [
          s.attention_score || 0,
          s.safety_score || 0
        ]
      );

    }


    updateDistribution(
      s.attention_distribution
    );

  }


  // ============================================================
  // LEVEL
  // ============================================================

  function setLevel(
    level,
    text,
    score
  ) {

    statusCard.className =
      "card status-card level-"
      + level;


    $("statusText").textContent =
      text;


    $("scoreNum").textContent =
      Math.round(score);


    const fill =
      $("scoreFill");


    fill.style.width =
      Math.min(
        score,
        100
      )
      + "%";


    fill.style.background =
      level === "drowsy"
        ? "#ef4444"
        : level === "warning"
        ? "#f59e0b"
        : "#22c55e";

  }


  // ============================================================
  // MONITOR
  // ============================================================

  function pill(
    el,
    text,
    state
  ) {

    if (!el) {
      return;
    }

    el.textContent =
      text;

    el.className =
      "pill st-"
      + state;

  }


  function updateMonitor(s) {

    const faceOn =
      !!s.face_detected;


    pill(
      stFace,
      faceOn
        ? "Detected"
        : "Not detected",
      faceOn
        ? "normal"
        : "alert"
    );


    if (!faceOn) {

      pill(
        stEyes,
        "–",
        "idle"
      );

    } else {

      pill(
        stEyes,
        s.eyes_closed
          ? "Closed"
          : "Open",
        s.eyes_closed
          ? "warn"
          : "normal"
      );

    }


    if (s.drowsiness) {

      pill(
        stDrowsy,
        "ALERT",
        "alert"
      );

    } else if (
      (s.level || "")
      === "WARNING"
    ) {

      pill(
        stDrowsy,
        "Warning",
        "warn"
      );

    } else {

      pill(
        stDrowsy,
        faceOn
          ? "Normal"
          : "–",
        faceOn
          ? "normal"
          : "idle"
      );

    }


    const att =
      s.attention;


    if (att === "left") {

      pill(
        stAttention,
        "Looking LEFT",
        "alert"
      );

    } else if (
      att === "right"
    ) {

      pill(
        stAttention,
        "Looking RIGHT",
        "alert"
      );

    } else if (
      att === "no_face"
      ||
      !faceOn
    ) {

      pill(
        stAttention,
        "–",
        "idle"
      );

    } else {

      pill(
        stAttention,
        "Forward",
        "normal"
      );

    }


    if (!faceOn) {

      pill(
        stGlasses,
        "–",
        "idle"
      );

    } else {

      pill(
        stGlasses,
        s.sunglasses_detected
          ? "Detected"
          : "Not detected",
        s.sunglasses_detected
          ? "warn"
          : "normal"
      );

    }


    const covMap = {

      clear: [
        "Clear",
        "normal"
      ],

      partial: [
        "Partially covered",
        "warn"
      ],

      covered: [
        "COVERED",
        "alert"
      ],

      none: [
        "Not visible",
        "alert"
      ]

    };


    const cm =
      covMap[
        s.face_coverage
      ]
      ||
      ["–", "idle"];


    pill(
      stCoverage,
      cm[0],
      cm[1]
    );


    if (s.alert_label) {

      activeAlert.textContent =
        s.alert_label;

      activeAlert.classList.remove(
        "hidden"
      );

      const high =
        s.face_covered
        ||
        s.drowsiness;

      activeAlert.className =
        "active-alert "
        +
        (
          high
            ? "aa-alert"
            : "aa-warn"
        );

    } else {

      activeAlert.classList.add(
        "hidden"
      );

    }

  }


  // ============================================================
  // RESET MONITOR
  // ============================================================

  function resetMonitor() {

    [
      stFace,
      stEyes,
      stDrowsy,
      stAttention,
      stGlasses,
      stCoverage
    ].forEach(
      (el) =>
        pill(
          el,
          "–",
          "idle"
        )
    );


    activeAlert.classList.add(
      "hidden"
    );


    pill(
      riskPill,
      "RISK –",
      "idle"
    );


    pill(
      stDistract,
      "–",
      "idle"
    );


    pill(
      stFatigue,
      "–",
      "idle"
    );


    if (attNum)
      attNum.textContent =
        "–";


    if (safeNum)
      safeNum.textContent =
        "–";


    if (attFill)
      attFill.style.width =
        "0%";


    if (safeFill)
      safeFill.style.width =
        "0%";


    if (breakBanner)
      breakBanner.classList.add(
        "hidden"
      );


    breakDismissed =
      false;

    lastVoiceKey =
      null;

  }


  // ============================================================
  // SAFETY
  // ============================================================

  function scoreColor(v) {

    return v >= 75
      ? "#22c55e"
      : v >= 45
      ? "#f59e0b"
      : "#ef4444";

  }


  function updateSafety(s) {

    const att =
      s.attention_score;

    const safe =
      s.safety_score;


    if (att != null) {

      attNum.textContent =
        Math.round(att);

      attFill.style.width =
        Math.max(
          0,
          Math.min(
            att,
            100
          )
        )
        + "%";

      attFill.style.background =
        scoreColor(att);

    }


    if (safe != null) {

      safeNum.textContent =
        Math.round(safe);

      safeFill.style.width =
        Math.max(
          0,
          Math.min(
            safe,
            100
          )
        )
        + "%";

      safeFill.style.background =
        scoreColor(safe);

    }


    const risk =
      s.risk_level
      || null;


    if (risk) {

      const rs =
        risk === "LOW"
          ? "normal"
          : risk === "MEDIUM"
          ? "warn"
          : "alert";


      pill(
        riskPill,
        "RISK " + risk,
        rs
      );

    }


    if (s.distraction_active) {

      const d =
        (
          s.distraction_duration
          || 0
        ).toFixed(1)
        + "s";


      pill(
        stDistract,
        d,
        s.distraction_alert
          ? "alert"
          : "warn"
      );

    } else {

      pill(
        stDistract,
        s.face_detected
          ? "None"
          : "–",
        s.face_detected
          ? "normal"
          : "idle"
      );

    }


    const ft =
      s.fatigue_trend;


    if (
      ft === "INCREASING"
    ) {

      pill(
        stFatigue,
        "Rising ↑",
        "alert"
      );

    } else if (
      ft === "DECREASING"
    ) {

      pill(
        stFatigue,
        "Easing ↓",
        "normal"
      );

    } else if (
      ft === "STABLE"
    ) {

      pill(
        stFatigue,
        "Stable →",
        "normal"
      );

    } else {

      pill(
        stFatigue,
        "–",
        "idle"
      );

    }

  }


  // ============================================================
  // DISTRIBUTION
  // ============================================================

  function updateDistribution(
    dist
  ) {

    if (!dist) {
      return;
    }


    distChart
      .data
      .datasets[0]
      .data = [

        dist.forward || 0,

        dist.left || 0,

        dist.right || 0,

        dist.down || 0,

        dist.none || 0

      ];


    distChart.update(
      "none"
    );

  }


  // ============================================================
  // MOBILE / PRIVACY
  // ============================================================

  function updateMobile(s) {

    if (
      s.video_storage != null
      &&
      videoStorage
    ) {

      videoStorage.textContent =
        s.video_storage
          ? "ON"
          : "OFF";

    }


    if (
      s.camera_processing
      &&
      $("camProc")
    ) {

      $("camProc").textContent =
        s.camera_processing;

    }


    const n =
      s.notifications;


    if (
      n
      &&
      notifBadge
    ) {

      if (!n.enabled) {

        notifBadge.textContent =
          "OFF";

        notifBadge.className =
          "badge badge-off";

      } else if (
        n.configured
      ) {

        notifBadge.textContent =
          "READY";

        notifBadge.className =
          "badge badge-on";

      } else {

        notifBadge.textContent =
          "SIMULATED";

        notifBadge.className =
          "badge badge-warnb";

      }


      if (notifProvider) {

        notifProvider.textContent =
          n.provider || "–";

      }

    }

  }


  // ============================================================
  // BREAK
  // ============================================================

  function updateBreak(s) {

    if (
      s.break_recommended
      &&
      !breakDismissed
    ) {

      breakTextEl.textContent =
        s.break_text
        ||
        "Take a short break.";

      breakBanner.classList.remove(
        "hidden"
      );

    } else if (
      !s.break_recommended
    ) {

      breakBanner.classList.add(
        "hidden"
      );

      breakDismissed =
        false;

    }

  }


  if (breakDismiss) {

    breakDismiss.addEventListener(
      "click",
      () => {

        breakBanner.classList.add(
          "hidden"
        );

        breakDismissed =
          true;

      }
    );

  }


  // ============================================================
  // VOICE
  // ============================================================

  function maybeSpeak(s) {

    if (
      !voiceToggle
      ||
      !voiceToggle.checked
    ) {
      return;
    }


    if (
      !("speechSynthesis" in window)
    ) {
      return;
    }


    const key =
      s.voice_key;

    const text =
      s.voice_text;


    if (!key || !text) {

      if (!s.alert_active) {

        lastVoiceKey =
          null;

      }

      return;

    }


    const now =
      Date.now();


    if (
      key === lastVoiceKey
      &&
      (
        now
        -
        lastVoiceAt
      )
      <
      VOICE_COOLDOWN
    ) {

      return;

    }


    lastVoiceKey =
      key;

    lastVoiceAt =
      now;


    try {

      const utterance =
        new SpeechSynthesisUtterance(
          text
        );

      utterance.rate =
        1.02;

      utterance.pitch =
        1.0;

      utterance.volume =
        1.0;


      window.speechSynthesis.cancel();

      window.speechSynthesis.speak(
        utterance
      );

    } catch (e) {}

  }


  // ============================================================
  // ALERT AUDIO
  // ============================================================

  function stopAllAudio() {

    allAudio.forEach(
      (a) => {

        try {

          a.pause();

          a.currentTime =
            0;

        } catch (e) {}

      }
    );


    currentSound =
      null;


    alarmFlash.classList.remove(
      "on",
      "warn",
      "crit"
    );

  }


  function updateAudio(s) {

    const desired =
      (
        alarmToggle.checked
        &&
        s.alert_active
      )
      ? s.alert_sound
      : null;


    if (
      desired === currentSound
    ) {

      return;

    }


    if (
      currentSound
      &&
      SOUNDS[currentSound]
    ) {

      try {

        SOUNDS[currentSound].pause();

        SOUNDS[currentSound].currentTime =
          0;

      } catch (e) {}

    }


    if (
      desired
      &&
      SOUNDS[desired]
    ) {

      try {

        SOUNDS[desired].currentTime =
          0;

        SOUNDS[desired]
          .play()
          .catch(
            () => {}
          );

      } catch (e) {}

    }


    currentSound =
      desired;


    if (desired) {

      alarmFlash.classList.add(
        "on"
      );

      alarmFlash.classList.toggle(
        "warn",
        (
          s.alert_type
          || ""
        ).indexOf(
          "SIDE_LOOK"
        ) === 0
      );

      alarmFlash.classList.toggle(
        "crit",
        (
          s.escalation_level
          || 0
        ) >= 3
      );

    } else {

      alarmFlash.classList.remove(
        "on",
        "warn",
        "crit"
      );

    }

  }


  // ============================================================
  // NOTIFICATION TEST
  // ============================================================

  if (testNotifyBtn) {

    testNotifyBtn.addEventListener(
      "click",
      async () => {

        testNotifyBtn.disabled =
          true;

        notifResult.textContent =
          "Sending…";


        try {

          const response =
            await fetch(
              "/api/notify/test",
              {
                method: "POST"
              }
            );


          const r =
            await response.json();


          if (
            r.ok
            &&
            r.provider === "fcm"
          ) {

            notifResult.textContent =
              "✓ Sent to your device ("
              + r.detail
              + ")";

          } else if (
            r.ok
          ) {

            notifResult.textContent =
              "✓ Simulated notification.";

          } else {

            notifResult.textContent =
              "✗ "
              + (
                r.detail
                ||
                "failed"
              );

          }

        } catch (e) {

          notifResult.textContent =
            "✗ request failed";

        }


        testNotifyBtn.disabled =
          false;

      }
    );

  }


  // ============================================================
  // SESSION SUMMARY
  // ============================================================

  const SUMMARY_ROWS = [

    [
      "duration_hms",
      "Session length"
    ],

    [
      "avg_attention_score",
      "Avg attention"
    ],

    [
      "final_safety_score",
      "Final safety"
    ],

    [
      "final_risk_level",
      "Final risk"
    ],

    [
      "drowsiness_events",
      "Drowsy events"
    ],

    [
      "yawn_count",
      "Yawns"
    ],

    [
      "left_look_events",
      "Left glances"
    ],

    [
      "right_look_events",
      "Right glances"
    ],

    [
      "face_covered_events",
      "Face covered"
    ],

    [
      "total_distraction_hms",
      "Time distracted"
    ]

  ];


  async function showSessionSummary() {

    let sum;

    try {

      sum =
        await (
          await fetch(
            "/api/session/summary"
          )
        ).json();

    } catch (e) {

      return;

    }


    if (
      !sum
      ||
      !sum.duration_seconds
    ) {

      return;

    }


    summaryBody.innerHTML =
      "";


    SUMMARY_ROWS.forEach(
      ([key, label]) => {

        let value =
          sum[key];


        if (
          value === undefined
          ||
          value === null
        ) {

          value =
            "–";

        }


        const cell =
          document.createElement(
            "div"
          );


        cell.className =
          "summary-cell";


        cell.innerHTML =
          `
          <div class="sc-num">
            ${value}
          </div>
          <div class="sc-lbl">
            ${label}
          </div>
          `;


        summaryBody.appendChild(
          cell
        );

      }
    );


    summaryModal.classList.remove(
      "hidden"
    );

  }


  const summaryClose =
    $("summaryClose");


  if (summaryClose) {

    summaryClose.addEventListener(
      "click",
      () =>
        summaryModal.classList.add(
          "hidden"
        )
    );

  }


  const exportCsvBtn =
    $("exportCsvBtn");


  if (exportCsvBtn) {

    exportCsvBtn.addEventListener(
      "click",
      () => {

        window.location =
          "/api/events/export?fmt=csv";

      }
    );

  }


  const exportJsonBtn =
    $("exportJsonBtn");


  if (exportJsonBtn) {

    exportJsonBtn.addEventListener(
      "click",
      () => {

        window.location =
          "/api/events/export?fmt=json";

      }
    );

  }


  // ============================================================
  // FORMAT
  // ============================================================

  function fmt(v) {

    return (
      v === null
      ||
      v === undefined
    )
      ? "-"
      : Number(v).toFixed(2);

  }


  // ============================================================
  // INITIAL STATE
  // ============================================================

  (async () => {

    try {

      const response =
        await fetch(
          "/api/state"
        );

      const state =
        await response.json();

      updateMobile(
        state
      );

      updateCameraBadge(
        "CAMERA OFF"
      );

    } catch (e) {}

  })();


})();