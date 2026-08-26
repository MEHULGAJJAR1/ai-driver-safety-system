(function () {
    "use strict";

    // ============================================================
    // HELPERS
    // ============================================================

    const $ = (id) => document.getElementById(id);

    const feed = $("videoFeed");
    const placeholder = $("videoPlaceholder");

    const startBtn = $("startBtn");
    const stopBtn = $("stopBtn");
    const resetBtn = $("resetBtn");

    const alarmToggle = $("alarmToggle");
    const voiceToggle = $("voiceToggle");

    const alarmFlash = $("alarmFlash");
    const statusCard = $("statusCard");

    // ============================================================
    // BROWSER CAMERA VIDEO
    // ============================================================
    // dashboard.html mein cameraVideo nahi tha.
    // Isliye hidden video element automatically create kar rahe hain.

    let cameraVideo = $("cameraVideo");

    if (!cameraVideo) {
        cameraVideo = document.createElement("video");

        cameraVideo.id = "cameraVideo";

        cameraVideo.autoplay = true;
        cameraVideo.playsInline = true;
        cameraVideo.muted = true;

        cameraVideo.style.display = "none";
        cameraVideo.style.position = "absolute";
        cameraVideo.style.width = "1px";
        cameraVideo.style.height = "1px";
        cameraVideo.style.opacity = "0";
        cameraVideo.style.pointerEvents = "none";

        document.body.appendChild(cameraVideo);
    }

    let cameraStream = null;
    let running = false;
    let processing = false;
    let processingTimer = null;

    let lastFrameTime = 0;

    // Render Free ke liye 5-6 FPS enough hai
    const FRAME_INTERVAL = 180;

    // ============================================================
    // AUDIO
    // ============================================================

    const sndDrowsiness = $("sndDrowsiness");
    const sndSideLook = $("sndSideLook");
    const sndFaceCovered = $("sndFaceCovered");
    const sndCritical = $("sndCritical");

    let currentSound = null;

    function stopAllAudio() {

        [
            sndDrowsiness,
            sndSideLook,
            sndFaceCovered,
            sndCritical
        ].forEach((audio) => {

            if (!audio) return;

            try {
                audio.pause();
                audio.currentTime = 0;
            } catch (e) {}
        });

        currentSound = null;

        if (alarmFlash) {
            alarmFlash.classList.remove(
                "on",
                "warn",
                "crit"
            );
        }
    }

    function unlockAudio() {

        [
            sndDrowsiness,
            sndSideLook,
            sndFaceCovered,
            sndCritical
        ].forEach((audio) => {

            if (!audio) return;

            try {

                audio.muted = true;

                const promise = audio.play();

                if (promise && promise.then) {

                    promise
                        .then(() => {

                            audio.pause();
                            audio.currentTime = 0;
                            audio.muted = false;

                        })
                        .catch(() => {

                            audio.muted = false;

                        });

                }

            } catch (e) {

                audio.muted = false;

            }
        });
    }

    function playAlertSound(state) {

        if (!alarmToggle || !alarmToggle.checked) {
            stopAllAudio();
            return;
        }

        if (!state || !state.alert_active) {
            stopAllAudio();
            return;
        }

        let desired = null;

        const type = String(
            state.alert_type || ""
        ).toUpperCase();

        if (type.includes("CRITICAL")) {

            desired = sndCritical;

        } else if (type.includes("SIDE_LOOK")) {

            desired = sndSideLook;

        } else if (
            type.includes("FACE") ||
            type.includes("COVERED")
        ) {

            desired = sndFaceCovered;

        } else {

            desired = sndDrowsiness;
        }

        if (!desired) {
            stopAllAudio();
            return;
        }

        if (desired === currentSound) {
            return;
        }

        stopAllAudio();

        try {

            desired.loop = true;
            desired.currentTime = 0;

            const promise = desired.play();

            if (promise && promise.catch) {
                promise.catch(() => {});
            }

            currentSound = desired;

        } catch (e) {}

        if (alarmFlash) {

            alarmFlash.classList.add("on");

            alarmFlash.classList.toggle(
                "warn",
                type.includes("SIDE_LOOK")
            );

            alarmFlash.classList.toggle(
                "crit",
                type.includes("CRITICAL")
            );
        }
    }

    if (alarmToggle) {

        alarmToggle.addEventListener(
            "change",
            function () {

                if (!alarmToggle.checked) {
                    stopAllAudio();
                }

            }
        );
    }

    // ============================================================
    // BROWSER CAMERA
    // ============================================================

    async function openBrowserCamera() {

        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia
        ) {

            throw new Error(
                "Camera access is not supported by this browser."
            );
        }

        // HTTPS required.
        if (
            location.protocol !== "https:" &&
            location.hostname !== "localhost" &&
            location.hostname !== "127.0.0.1"
        ) {

            throw new Error(
                "Camera requires HTTPS. Open the Render HTTPS URL."
            );
        }

        const stream =
            await navigator.mediaDevices.getUserMedia({

                video: {
                    facingMode: "user",

                    width: {
                        ideal: 640,
                        max: 1280
                    },

                    height: {
                        ideal: 480,
                        max: 720
                    },

                    frameRate: {
                        ideal: 15,
                        max: 24
                    }
                },

                audio: false
            });

        cameraStream = stream;

        cameraVideo.srcObject = stream;

        cameraVideo.muted = true;
        cameraVideo.playsInline = true;
        cameraVideo.autoplay = true;

        await cameraVideo.play();
    }

    function closeBrowserCamera() {

        if (cameraStream) {

            cameraStream
                .getTracks()
                .forEach((track) => {

                    try {
                        track.stop();
                    } catch (e) {}

                });

            cameraStream = null;
        }

        if (cameraVideo) {

            try {
                cameraVideo.pause();
            } catch (e) {}

            cameraVideo.srcObject = null;
        }
    }

    // ============================================================
    // START CAMERA
    // ============================================================

    if (startBtn) {

        startBtn.addEventListener(
            "click",
            async function () {

                if (running) {
                    return;
                }

                startBtn.disabled = true;

                try {

                    // Browser user gesture -> unlock alarm audio
                    unlockAudio();

                    // IMPORTANT:
                    // Camera is opened on USER'S laptop/mobile.
                    // Render server camera is NOT used.
                    await openBrowserCamera();

                    // Tell Flask to start browser mode.
                    const response =
                        await fetch(
                            "/api/camera/start",
                            {
                                method: "POST",
                                headers: {
                                    "Accept": "application/json"
                                }
                            }
                        );

                    if (!response.ok) {

                        throw new Error(
                            "Server camera session could not be started."
                        );
                    }

                    const result =
                        await response.json();

                    if (!result.ok) {

                        throw new Error(
                            result.error ||
                            "Drowsiness detection pipeline could not be loaded."
                        );
                    }

                    running = true;
                    lastFrameTime = 0;

                    // Actual browser camera stays hidden.
                    cameraVideo.style.display = "none";

                    // Processed frame appears here.
                    if (feed) {
                        feed.style.display = "block";
                    }

                    if (placeholder) {
                        placeholder.style.display = "none";
                    }

                    if (stopBtn) {
                        stopBtn.disabled = false;
                    }

                    startBtn.disabled = true;

                    startProcessing();

                } catch (error) {

                    console.error(
                        "Camera start error:",
                        error
                    );

                    running = false;

                    stopProcessing();
                    closeBrowserCamera();
                    stopAllAudio();

                    if (placeholder) {
                        placeholder.style.display = "block";

                        const p =
                            placeholder.querySelector("p");

                        if (p) {
                            p.textContent = "Camera stopped";
                        }
                    }

                    if (feed) {
                        feed.style.display = "none";
                        feed.removeAttribute("src");
                    }

                    if (stopBtn) {
                        stopBtn.disabled = true;
                    }

                    startBtn.disabled = false;

                    alert(
                        "Could not open the camera.\n\n" +
                        error.message +
                        "\n\n" +
                        "Please allow camera permission in Chrome."
                    );
                }
            }
        );
    }

    // ============================================================
    // STOP CAMERA
    // ============================================================

    if (stopBtn) {

        stopBtn.addEventListener(
            "click",
            async function () {

                running = false;

                stopProcessing();

                closeBrowserCamera();

                stopAllAudio();

                try {

                    await fetch(
                        "/api/camera/stop",
                        {
                            method: "POST",
                            headers: {
                                "Accept": "application/json"
                            }
                        }
                    );

                } catch (e) {}

                if (feed) {

                    feed.style.display = "none";
                    feed.removeAttribute("src");
                }

                if (placeholder) {

                    placeholder.style.display = "block";

                    const p =
                        placeholder.querySelector("p");

                    if (p) {
                        p.textContent = "Camera stopped";
                    }
                }

                if (stopBtn) {
                    stopBtn.disabled = true;
                }

                if (startBtn) {
                    startBtn.disabled = false;
                }

                try {

                    if (
                        window.speechSynthesis
                    ) {

                        window.speechSynthesis.cancel();
                    }

                } catch (e) {}

                await showSessionSummary();

                resetMonitor();
            }
        );
    }

    // ============================================================
    // RESET
    // ============================================================

    if (resetBtn) {

        resetBtn.addEventListener(
            "click",
            async function () {

                try {

                    await fetch(
                        "/api/camera/reset",
                        {
                            method: "POST",
                            headers: {
                                "Accept": "application/json"
                            }
                        }
                    );

                } catch (e) {}

            }
        );
    }

    // ============================================================
    // FRAME CAPTURE
    // ============================================================

    const captureCanvas =
        document.createElement("canvas");

    const canvasContext =
        captureCanvas.getContext("2d", {
            willReadFrequently: false
        });

    // ============================================================
    // SEND BROWSER FRAME TO FLASK
    // ============================================================

    async function processBrowserFrame() {

        if (!running) {
            return;
        }

        if (processing) {
            return;
        }

        if (!cameraVideo) {
            return;
        }

        if (
            !cameraVideo.videoWidth ||
            !cameraVideo.videoHeight
        ) {
            return;
        }

        const now = Date.now();

        if (
            now - lastFrameTime <
            FRAME_INTERVAL
        ) {
            return;
        }

        lastFrameTime = now;

        processing = true;

        try {

            // Keep frame small for Render Free.
            const width =
                Math.min(
                    cameraVideo.videoWidth,
                    640
                );

            const height =
                Math.round(
                    cameraVideo.videoHeight *
                    (
                        width /
                        cameraVideo.videoWidth
                    )
                );

            captureCanvas.width = width;
            captureCanvas.height = height;

            canvasContext.drawImage(
                cameraVideo,
                0,
                0,
                width,
                height
            );

            const blob =
                await new Promise(
                    (resolve) => {

                        captureCanvas.toBlob(
                            resolve,
                            "image/jpeg",
                            0.65
                        );

                    }
                );

            if (!blob) {
                return;
            }

            // ====================================================
            // IMPORTANT
            // Send multipart JPEG to Flask.
            // app.py should pass it to:
            // camera.process_browser_frame(...)
            // ====================================================

            const formData =
                new FormData();

            formData.append(
                "frame",
                blob,
                "camera.jpg"
            );

            const response =
                await fetch(
                    "/api/process_frame",
                    {
                        method: "POST",
                        body: formData
                    }
                );

            if (!response.ok) {

                console.warn(
                    "Frame API HTTP error:",
                    response.status
                );

                return;
            }

            const result =
                await response.json();

            if (!result.ok) {

                console.warn(
                    "Frame processing error:",
                    result.error
                );

                return;
            }

            // ====================================================
            // PROCESSED IMAGE
            // ====================================================

            if (
                result.image &&
                feed
            ) {

                // Backend can return:
                // data:image/jpeg;base64,...
                // OR plain base64.

                let imageSrc =
                    result.image;

                if (
                    !String(imageSrc)
                        .startsWith("data:")
                ) {

                    imageSrc =
                        "data:image/jpeg;base64," +
                        imageSrc;
                }

                feed.src =
                    imageSrc;
            }

            // ====================================================
            // STATE
            // ====================================================

            if (result.state) {

                updateUI(
                    result.state
                );
            }

        } catch (error) {

            console.warn(
                "Browser frame processing error:",
                error
            );

        } finally {

            processing = false;
        }
    }

    // ============================================================
    // PROCESSING LOOP
    // ============================================================

    function startProcessing() {

        stopProcessing();

        processingTimer =
            setInterval(
                processBrowserFrame,
                50
            );
    }

    function stopProcessing() {

        if (processingTimer) {

            clearInterval(
                processingTimer
            );

            processingTimer = null;
        }
    }

    // ============================================================
    // UI UPDATE
    // ============================================================

    function updateUI(s) {

        if (!s) {
            return;
        }

        // --------------------------------------------------------
        // Metrics
        // --------------------------------------------------------

        if ($("mEar")) {
            $("mEar").textContent =
                fmt(s.ear);
        }

        if ($("mMar")) {
            $("mMar").textContent =
                fmt(s.mar);
        }

        if ($("mPitch")) {

            $("mPitch").textContent =
                s.pitch != null
                    ? Number(s.pitch).toFixed(0) + "°"
                    : "-";
        }

        if ($("mYaw")) {

            $("mYaw").textContent =
                s.yaw != null
                    ? Number(s.yaw).toFixed(0) + "°"
                    : "-";
        }

        if ($("mPerclos")) {

            $("mPerclos").textContent =
                s.perclos != null
                    ? (
                        Number(s.perclos) * 100
                    ).toFixed(0) + "%"
                    : "-";
        }

        if ($("mCnn")) {

            $("mCnn").textContent =
                s.cnn_closed_prob != null
                    ? Number(
                        s.cnn_closed_prob
                    ).toFixed(2)
                    : "n/a";
        }

        // --------------------------------------------------------
        // Counters
        // --------------------------------------------------------

        if ($("cBlink")) {
            $("cBlink").textContent =
                s.blink_count || 0;
        }

        if ($("cYawn")) {
            $("cYawn").textContent =
                s.yawn_count || 0;
        }

        if ($("cNod")) {
            $("cNod").textContent =
                s.nod_count || 0;
        }

        if ($("cDrowsy")) {
            $("cDrowsy").textContent =
                s.drowsy_events || 0;
        }

        // --------------------------------------------------------
        // Status
        // --------------------------------------------------------

        const level =
            String(
                s.level || "ALERT"
            ).toLowerCase();

        setLevel(
            level,
            s.status_text || "-",
            s.score || 0
        );

        // --------------------------------------------------------
        // Panels
        // --------------------------------------------------------

        updateMonitor(s);
        updateSafety(s);
        updateMobile(s);

        playAlertSound(s);

        maybeSpeak(s);

        updateBreak(s);

        updateCharts(s);
    }

    // ============================================================
    // STATUS
    // ============================================================

    function setLevel(
        level,
        text,
        score
    ) {

        if (!statusCard) {
            return;
        }

        statusCard.className =
            "card status-card level-" +
            level;

        if ($("statusText")) {

            $("statusText").textContent =
                text;
        }

        if ($("scoreNum")) {

            $("scoreNum").textContent =
                Math.round(
                    Number(score) || 0
                );
        }

        const fill =
            $("scoreFill");

        if (fill) {

            const value =
                Math.max(
                    0,
                    Math.min(
                        Number(score) || 0,
                        100
                    )
                );

            fill.style.width =
                value + "%";

            if (level === "drowsy") {

                fill.style.background =
                    "#ef4444";

            } else if (
                level === "warning"
            ) {

                fill.style.background =
                    "#f59e0b";

            } else {

                fill.style.background =
                    "#22c55e";
            }
        }
    }

    // ============================================================
    // PILLS
    // ============================================================

    function pill(
        element,
        text,
        state
    ) {

        if (!element) {
            return;
        }

        element.textContent =
            text;

        element.className =
            "pill st-" +
            state;
    }

    // ============================================================
    // MONITOR
    // ============================================================

    function updateMonitor(s) {

        const face =
            !!s.face_detected;

        pill(
            $("stFace"),
            face
                ? "Detected"
                : "Not detected",
            face
                ? "normal"
                : "alert"
        );

        // Eyes
        if (!face) {

            pill(
                $("stEyes"),
                "–",
                "idle"
            );

        } else {

            pill(
                $("stEyes"),
                s.eyes_closed
                    ? "Closed"
                    : "Open",
                s.eyes_closed
                    ? "warn"
                    : "normal"
            );
        }

        // Drowsiness
        if (s.drowsiness) {

            pill(
                $("stDrowsy"),
                "ALERT",
                "alert"
            );

        } else if (
            String(s.level || "")
                .toUpperCase() ===
            "WARNING"
        ) {

            pill(
                $("stDrowsy"),
                "Warning",
                "warn"
            );

        } else {

            pill(
                $("stDrowsy"),
                face
                    ? "Normal"
                    : "–",
                face
                    ? "normal"
                    : "idle"
            );
        }

        // Attention
        const attention =
            s.attention;

        if (
            attention === "left"
        ) {

            pill(
                $("stAttention"),
                "Looking LEFT",
                "alert"
            );

        } else if (
            attention === "right"
        ) {

            pill(
                $("stAttention"),
                "Looking RIGHT",
                "alert"
            );

        } else if (
            attention === "no_face" ||
            !face
        ) {

            pill(
                $("stAttention"),
                "–",
                "idle"
            );

        } else {

            pill(
                $("stAttention"),
                "Forward",
                "normal"
            );
        }

        // Sunglasses
        if (!face) {

            pill(
                $("stGlasses"),
                "–",
                "idle"
            );

        } else {

            pill(
                $("stGlasses"),
                s.sunglasses_detected
                    ? "Detected"
                    : "Not detected",
                s.sunglasses_detected
                    ? "warn"
                    : "normal"
            );
        }

        // Face coverage
        const coverageMap = {

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

        const item =
            coverageMap[
                s.face_coverage
            ] || [
                "–",
                "idle"
            ];

        pill(
            $("stCoverage"),
            item[0],
            item[1]
        );
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

        const attention =
            s.attention_score;

        const safety =
            s.safety_score;

        if (
            attention != null &&
            $("attNum") &&
            $("attFill")
        ) {

            $("attNum").textContent =
                Math.round(attention);

            $("attFill").style.width =
                Math.max(
                    0,
                    Math.min(
                        100,
                        Number(attention)
                    )
                ) + "%";

            $("attFill").style.background =
                scoreColor(
                    Number(attention)
                );
        }

        if (
            safety != null &&
            $("safeNum") &&
            $("safeFill")
        ) {

            $("safeNum").textContent =
                Math.round(safety);

            $("safeFill").style.width =
                Math.max(
                    0,
                    Math.min(
                        100,
                        Number(safety)
                    )
                ) + "%";

            $("safeFill").style.background =
                scoreColor(
                    Number(safety)
                );
        }

        const risk =
            s.risk_level;

        if (risk) {

            pill(
                $("riskPill"),
                "RISK " + risk,
                risk === "LOW"
                    ? "normal"
                    : risk === "MEDIUM"
                        ? "warn"
                        : "alert"
            );
        }

        // Distraction
        if (
            s.distraction_active
        ) {

            const duration =
                Number(
                    s.distraction_duration || 0
                ).toFixed(1);

            pill(
                $("stDistract"),
                duration + "s",
                s.distraction_alert
                    ? "alert"
                    : "warn"
            );

        } else {

            pill(
                $("stDistract"),
                s.face_detected
                    ? "None"
                    : "–",
                s.face_detected
                    ? "normal"
                    : "idle"
            );
        }

        // Fatigue
        const trend =
            s.fatigue_trend;

        if (
            trend === "INCREASING"
        ) {

            pill(
                $("stFatigue"),
                "Rising ↑",
                "alert"
            );

        } else if (
            trend === "DECREASING"
        ) {

            pill(
                $("stFatigue"),
                "Easing ↓",
                "normal"
            );

        } else if (
            trend === "STABLE"
        ) {

            pill(
                $("stFatigue"),
                "Stable →",
                "normal"
            );

        } else {

            pill(
                $("stFatigue"),
                "–",
                "idle"
            );
        }
    }

    // ============================================================
    // MOBILE
    // ============================================================

    function updateMobile(s) {

        if (
            s.video_storage != null &&
            $("videoStorage")
        ) {

            $("videoStorage").textContent =
                s.video_storage
                    ? "ON"
                    : "OFF";
        }

        if (
            s.camera_processing &&
            $("camProc")
        ) {

            $("camProc").textContent =
                s.camera_processing;
        }

        const n =
            s.notifications;

        if (!n) {
            return;
        }

        if (
            !$("notifBadge")
        ) {
            return;
        }

        if (!n.enabled) {

            $("notifBadge").textContent =
                "OFF";

            $("notifBadge").className =
                "badge badge-off";

        } else if (
            n.configured
        ) {

            $("notifBadge").textContent =
                "READY";

            $("notifBadge").className =
                "badge badge-on";

        } else {

            $("notifBadge").textContent =
                "SIMULATED";

            $("notifBadge").className =
                "badge badge-warnb";
        }

        if ($("notifProvider")) {

            $("notifProvider").textContent =
                n.provider || "–";
        }
    }

    // ============================================================
    // BREAK
    // ============================================================

    let breakDismissed = false;

    function updateBreak(s) {

        const banner =
            $("breakBanner");

        if (!banner) {
            return;
        }

        if (
            s.break_recommended &&
            !breakDismissed
        ) {

            if ($("breakText")) {

                $("breakText").textContent =
                    s.break_text ||
                    "Take a short break.";
            }

            banner.classList.remove(
                "hidden"
            );

        } else if (
            !s.break_recommended
        ) {

            banner.classList.add(
                "hidden"
            );

            breakDismissed = false;
        }
    }

    const breakDismiss =
        $("breakDismiss");

    if (breakDismiss) {

        breakDismiss.addEventListener(
            "click",
            function () {

                const banner =
                    $("breakBanner");

                if (banner) {

                    banner.classList.add(
                        "hidden"
                    );
                }

                breakDismissed = true;
            }
        );
    }

    // ============================================================
    // VOICE
    // ============================================================

    let lastVoiceKey = null;
    let lastVoiceAt = 0;

    const VOICE_COOLDOWN =
        (
            window.VOICE_COOLDOWN ||
            8
        ) * 1000;

    function maybeSpeak(s) {

        if (
            !voiceToggle ||
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

        if (
            !key ||
            !text
        ) {
            return;
        }

        const now =
            Date.now();

        if (
            key === lastVoiceKey &&
            now - lastVoiceAt <
            VOICE_COOLDOWN
        ) {
            return;
        }

        lastVoiceKey = key;
        lastVoiceAt = now;

        try {

            const utterance =
                new SpeechSynthesisUtterance(
                    text
                );

            utterance.rate = 1.02;
            utterance.pitch = 1;
            utterance.volume = 1;

            window.speechSynthesis.cancel();

            window.speechSynthesis.speak(
                utterance
            );

        } catch (e) {}
    }

    // ============================================================
    // CHARTS
    // ============================================================

    let scoreHistory = [];
    let earHistory = [];
    let marHistory = [];
    let attentionHistory = [];
    let safetyHistory = [];

    const MAX_POINTS = 60;

    function pushHistory(
        array,
        value
    ) {

        array.push({
            x: new Date()
                .toLocaleTimeString(),
            y: Number(value || 0)
        });

        if (
            array.length >
            MAX_POINTS
        ) {

            array.shift();
        }
    }

    function updateCharts(s) {

        pushHistory(
            scoreHistory,
            s.score
        );

        pushHistory(
            earHistory,
            s.ear
        );

        pushHistory(
            marHistory,
            s.mar
        );

        pushHistory(
            attentionHistory,
            s.attention_score
        );

        pushHistory(
            safetyHistory,
            s.safety_score
        );

        // Score chart
        if (
            window.scoreChart
        ) {

            window.scoreChart.data.labels =
                scoreHistory.map(
                    p => p.x
                );

            window.scoreChart.data.datasets[0].data =
                scoreHistory.map(
                    p => p.y
                );

            window.scoreChart.update(
                "none"
            );
        }

        // EAR / MAR chart
        if (
            window.earMarChart
        ) {

            window.earMarChart.data.labels =
                earHistory.map(
                    p => p.x
                );

            if (
                window.earMarChart
                    .data
                    .datasets
                    .length >= 2
            ) {

                window.earMarChart
                    .data
                    .datasets[0]
                    .data =
                    earHistory.map(
                        p => p.y
                    );

                window.earMarChart
                    .data
                    .datasets[1]
                    .data =
                    marHistory.map(
                        p => p.y
                    );
            }

            window.earMarChart.update(
                "none"
            );
        }

        // Safety chart
        if (
            window.safetyChart
        ) {

            window.safetyChart.data.labels =
                attentionHistory.map(
                    p => p.x
                );

            if (
                window.safetyChart
                    .data
                    .datasets
                    .length >= 2
            ) {

                window.safetyChart
                    .data
                    .datasets[0]
                    .data =
                    attentionHistory.map(
                        p => p.y
                    );

                window.safetyChart
                    .data
                    .datasets[1]
                    .data =
                    safetyHistory.map(
                        p => p.y
                    );
            }

            window.safetyChart.update(
                "none"
            );
        }
    }

    // ============================================================
    // SESSION SUMMARY
    // ============================================================

    const summaryModal =
        $("summaryModal");

    async function showSessionSummary() {

        if (!summaryModal) {
            return;
        }

        try {

            const response =
                await fetch(
                    "/api/session/summary"
                );

            const sum =
                await response.json();

            if (
                !sum ||
                !sum.duration_seconds
            ) {
                return;
            }

            const body =
                $("summaryBody");

            if (!body) {
                return;
            }

            body.innerHTML = "";

            const rows = [

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

            rows.forEach(
                ([key, label]) => {

                    const value =
                        sum[key] ??
                        "–";

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

                    body.appendChild(
                        cell
                    );
                }
            );

            summaryModal.classList.remove(
                "hidden"
            );

        } catch (e) {

            console.warn(
                "Summary error:",
                e
            );
        }
    }

    const summaryClose =
        $("summaryClose");

    if (summaryClose) {

        summaryClose.addEventListener(
            "click",
            function () {

                summaryModal.classList.add(
                    "hidden"
                );
            }
        );
    }

    const exportCsvBtn =
        $("exportCsvBtn");

    if (exportCsvBtn) {

        exportCsvBtn.addEventListener(
            "click",
            function () {

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
            function () {

                window.location =
                    "/api/events/export?fmt=json";
            }
        );
    }

    // ============================================================
    // RESET UI
    // ============================================================

    function resetMonitor() {

        [
            "stFace",
            "stEyes",
            "stDrowsy",
            "stAttention",
            "stGlasses",
            "stCoverage"
        ].forEach(
            (id) => {

                pill(
                    $(id),
                    "–",
                    "idle"
                );
            }
        );

        pill(
            $("riskPill"),
            "RISK –",
            "idle"
        );

        pill(
            $("stDistract"),
            "–",
            "idle"
        );

        pill(
            $("stFatigue"),
            "–",
            "idle"
        );

        if ($("attNum")) {
            $("attNum").textContent =
                "–";
        }

        if ($("safeNum")) {
            $("safeNum").textContent =
                "–";
        }

        if ($("attFill")) {
            $("attFill").style.width =
                "0%";
        }

        if ($("safeFill")) {
            $("safeFill").style.width =
                "0%";
        }

        if ($("breakBanner")) {

            $("breakBanner")
                .classList
                .add("hidden");
        }

        breakDismissed = false;
        lastVoiceKey = null;

        scoreHistory = [];
        earHistory = [];
        marHistory = [];
        attentionHistory = [];
        safetyHistory = [];
    }

    // ============================================================
    // INITIAL STATE
    // ============================================================

    async function loadInitialState() {

        try {

            const response =
                await fetch(
                    "/api/state"
                );

            if (!response.ok) {
                return;
            }

            const state =
                await response.json();

            updateMobile(state);

        } catch (e) {

            console.warn(
                "Initial state error:",
                e
            );
        }
    }

    loadInitialState();

})();