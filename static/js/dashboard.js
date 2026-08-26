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
    // CAMERA
    // ============================================================

    let cameraVideo = $("cameraVideo");

    if (!cameraVideo) {

        cameraVideo = document.createElement("video");

        cameraVideo.id = "cameraVideo";

        document.body.appendChild(cameraVideo);
    }

    cameraVideo.autoplay = true;
    cameraVideo.playsInline = true;
    cameraVideo.muted = true;

    cameraVideo.style.width = "100%";
    cameraVideo.style.height = "100%";
    cameraVideo.style.objectFit = "cover";
    cameraVideo.style.display = "none";


    let cameraStream = null;

    let running = false;

    let processing = false;

    let processingTimer = null;

    let lastFrameTime = 0;


    // ============================================================
    // PERFORMANCE
    // ============================================================

    /*
     * IMPORTANT:
     *
     * Camera = LIVE locally
     *
     * AI = background server processing
     *
     * Isse camera Render ke inference se block nahi hoga.
     */

    const AI_INTERVAL = 700;

    const AI_WIDTH = 320;

    const JPEG_QUALITY = 0.45;


    // ============================================================
    // CANVAS
    // ============================================================

    const captureCanvas =
        document.createElement("canvas");

    const canvasContext =
        captureCanvas.getContext("2d");


    // ============================================================
    // AUDIO ELEMENTS
    // ============================================================

    const sndDrowsiness =
        $("sndDrowsiness");

    const sndSideLook =
        $("sndSideLook");

    const sndFaceCovered =
        $("sndFaceCovered");

    const sndCritical =
        $("sndCritical");


    let currentSound = null;

    let audioContext = null;

    let alarmOscillator = null;

    let alarmGain = null;

    let alarmInterval = null;


    // ============================================================
    // WEB AUDIO UNLOCK
    // ============================================================

    function initAudio() {

        try {

            if (!audioContext) {

                audioContext =
                    new (
                        window.AudioContext ||
                        window.webkitAudioContext
                    )();
            }


            if (
                audioContext.state ===
                "suspended"
            ) {

                audioContext.resume();
            }

        } catch (e) {

            console.warn(
                "Audio initialization failed:",
                e
            );
        }
    }


    // ============================================================
    // FALLBACK ALARM
    // ============================================================

    function startFallbackAlarm(
        critical = false
    ) {

        stopFallbackAlarm();


        try {

            initAudio();

            if (!audioContext) {
                return;
            }


            const playBeep = () => {

                if (
                    !audioContext ||
                    audioContext.state ===
                    "suspended"
                ) {

                    return;
                }


                const oscillator =
                    audioContext.createOscillator();

                const gain =
                    audioContext.createGain();


                oscillator.type =
                    "square";


                oscillator.frequency.value =
                    critical
                        ? 950
                        : 650;


                gain.gain.setValueAtTime(
                    0.0001,
                    audioContext.currentTime
                );


                gain.gain.exponentialRampToValueAtTime(
                    0.12,
                    audioContext.currentTime + 0.02
                );


                gain.gain.exponentialRampToValueAtTime(
                    0.0001,
                    audioContext.currentTime + 0.22
                );


                oscillator.connect(gain);

                gain.connect(
                    audioContext.destination
                );


                oscillator.start();

                oscillator.stop(
                    audioContext.currentTime +
                    0.25
                );
            };


            playBeep();


            alarmInterval =
                setInterval(
                    playBeep,
                    critical
                        ? 450
                        : 750
                );

        } catch (e) {

            console.warn(
                "Fallback alarm failed:",
                e
            );
        }
    }


    function stopFallbackAlarm() {

        if (alarmInterval) {

            clearInterval(
                alarmInterval
            );

            alarmInterval = null;
        }


        try {

            if (alarmOscillator) {

                alarmOscillator.stop();

                alarmOscillator = null;
            }

        } catch (e) {}
    }


    // ============================================================
    // STOP ALL AUDIO
    // ============================================================

    function stopAllAudio() {

        [
            sndDrowsiness,
            sndSideLook,
            sndFaceCovered,
            sndCritical
        ].forEach(
            (audio) => {

                if (!audio) {
                    return;
                }

                try {

                    audio.pause();

                    audio.currentTime = 0;

                } catch (e) {}
            }
        );


        currentSound = null;


        stopFallbackAlarm();


        if (alarmFlash) {

            alarmFlash.classList.remove(
                "on",
                "warn",
                "crit"
            );
        }
    }


    // ============================================================
    // PLAY ALERT
    // ============================================================

    function playAlertSound(state) {

        if (
            !alarmToggle ||
            !alarmToggle.checked
        ) {

            stopAllAudio();

            return;
        }


        if (
            !state ||
            !state.alert_active
        ) {

            stopAllAudio();

            return;
        }


        const type =
            String(
                state.alert_type || ""
            ).toUpperCase();


        let desired = null;


        if (
            type.includes("CRITICAL")
        ) {

            desired =
                sndCritical;

        } else if (
            type.includes("SIDE_LOOK")
        ) {

            desired =
                sndSideLook;

        } else if (
            type.includes("FACE") ||
            type.includes("COVERED")
        ) {

            desired =
                sndFaceCovered;

        } else {

            desired =
                sndDrowsiness;
        }


        // --------------------------------------------------------
        // Flash
        // --------------------------------------------------------

        if (alarmFlash) {

            alarmFlash.classList.add(
                "on"
            );


            alarmFlash.classList.toggle(
                "warn",
                type.includes("SIDE_LOOK")
            );


            alarmFlash.classList.toggle(
                "crit",
                type.includes("CRITICAL")
            );
        }


        // --------------------------------------------------------
        // Try existing audio
        // --------------------------------------------------------

        if (
            desired &&
            desired !== currentSound
        ) {

            try {

                stopAllAudio();

                desired.loop = true;

                desired.currentTime = 0;

                const promise =
                    desired.play();


                if (
                    promise &&
                    promise.catch
                ) {

                    promise.catch(
                        () => {}
                    );
                }


                currentSound =
                    desired;


                return;

            } catch (e) {}
        }


        // --------------------------------------------------------
        // FALLBACK WEB AUDIO
        // --------------------------------------------------------

        if (
            !currentSound
        ) {

            startFallbackAlarm(
                type.includes("CRITICAL")
            );
        }
    }


    // ============================================================
    // AUDIO TOGGLE
    // ============================================================

    if (alarmToggle) {

        alarmToggle.addEventListener(
            "change",
            function () {

                initAudio();


                if (
                    !alarmToggle.checked
                ) {

                    stopAllAudio();
                }
            }
        );
    }


    // ============================================================
    // OPEN CAMERA
    // ============================================================

    async function openBrowserCamera() {

        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia
        ) {

            throw new Error(
                "Camera API is not supported."
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
                        ideal: 20,
                        max: 30
                    }
                },

                audio: false
            });


        cameraStream =
            stream;


        cameraVideo.srcObject =
            stream;


        await cameraVideo.play();


        cameraVideo.style.display =
            "block";


        // --------------------------------------------------------
        // HIDE OLD SERVER IMAGE
        // --------------------------------------------------------

        if (feed) {

            feed.style.display =
                "none";

            feed.removeAttribute(
                "src"
            );
        }


        if (placeholder) {

            placeholder.style.display =
                "none";
        }
    }


    // ============================================================
    // CLOSE CAMERA
    // ============================================================

    function closeBrowserCamera() {

        if (cameraStream) {

            cameraStream
                .getTracks()
                .forEach(
                    (track) => {

                        try {

                            track.stop();

                        } catch (e) {}
                    }
                );

            cameraStream = null;
        }


        if (cameraVideo) {

            try {

                cameraVideo.pause();

            } catch (e) {}


            cameraVideo.srcObject =
                null;


            cameraVideo.style.display =
                "none";
        }
    }


    // ============================================================
    // START
    // ============================================================

    if (startBtn) {

        startBtn.addEventListener(
            "click",
            async function () {

                if (running) {
                    return;
                }


                startBtn.disabled =
                    true;


                try {

                    // User gesture audio unlock.
                    initAudio();


                    // Browser camera.
                    await openBrowserCamera();


                    // Backend session.
                    const response =
                        await fetch(
                            "/api/camera/start",
                            {
                                method: "POST",
                                headers: {
                                    "Accept":
                                        "application/json"
                                }
                            }
                        );


                    const result =
                        await response.json();


                    if (
                        !response.ok ||
                        !result.ok
                    ) {

                        throw new Error(
                            result.error ||
                            "Detection pipeline could not start."
                        );
                    }


                    running =
                        true;


                    processing =
                        false;


                    lastFrameTime =
                        0;


                    if (stopBtn) {

                        stopBtn.disabled =
                            false;
                    }


                    startBtn.disabled =
                        true;


                    // ------------------------------------------------
                    // Start AI background processing
                    // ------------------------------------------------

                    startProcessing();


                } catch (error) {

                    console.error(
                        "START ERROR:",
                        error
                    );


                    running =
                        false;


                    stopProcessing();

                    closeBrowserCamera();

                    stopAllAudio();


                    if (placeholder) {

                        placeholder.style.display =
                            "block";

                        const p =
                            placeholder.querySelector("p");

                        if (p) {

                            p.textContent =
                                "Camera stopped";
                        }
                    }


                    if (stopBtn) {

                        stopBtn.disabled =
                            true;
                    }


                    startBtn.disabled =
                        false;


                    alert(
                        "Could not start camera.\n\n" +
                        error.message
                    );
                }
            }
        );
    }


    // ============================================================
    // STOP
    // ============================================================

    if (stopBtn) {

        stopBtn.addEventListener(
            "click",
            async function () {

                running =
                    false;


                processing =
                    false;


                stopProcessing();

                closeBrowserCamera();

                stopAllAudio();


                try {

                    await fetch(
                        "/api/camera/stop",
                        {
                            method: "POST"
                        }
                    );

                } catch (e) {}


                if (placeholder) {

                    placeholder.style.display =
                        "block";

                    const p =
                        placeholder.querySelector("p");

                    if (p) {

                        p.textContent =
                            "Camera stopped";
                    }
                }


                if (stopBtn) {

                    stopBtn.disabled =
                        true;
                }


                if (startBtn) {

                    startBtn.disabled =
                        false;
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
                            method: "POST"
                        }
                    );

                } catch (e) {}

            }
        );
    }


    // ============================================================
    // SEND FRAME TO SERVER
    // ============================================================

    async function processBrowserFrame() {

        if (!running) {
            return;
        }


        if (processing) {
            return;
        }


        if (
            !cameraVideo.videoWidth ||
            !cameraVideo.videoHeight
        ) {

            return;
        }


        const now =
            Date.now();


        if (
            now - lastFrameTime <
            AI_INTERVAL
        ) {

            return;
        }


        lastFrameTime =
            now;


        processing =
            true;


        try {

            // --------------------------------------------------------
            // VERY SMALL AI FRAME
            // --------------------------------------------------------

            const width =
                Math.min(
                    cameraVideo.videoWidth,
                    AI_WIDTH
                );


            const height =
                Math.round(
                    cameraVideo.videoHeight *
                    (
                        width /
                        cameraVideo.videoWidth
                    )
                );


            captureCanvas.width =
                width;


            captureCanvas.height =
                height;


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
                            JPEG_QUALITY
                        );
                    }
                );


            if (!blob) {
                return;
            }


            const formData =
                new FormData();


            formData.append(
                "frame",
                blob,
                "frame.jpg"
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
                    "AI server error:",
                    response.status
                );

                return;
            }


            const result =
                await response.json();


            if (!result.ok) {

                console.warn(
                    "AI error:",
                    result.error
                );

                return;
            }


            // --------------------------------------------------------
            // LIVE AI READING
            // --------------------------------------------------------

            if (result.state) {

                updateUI(
                    result.state
                );
            }


        } catch (error) {

            console.warn(
                "AI frame error:",
                error
            );

        } finally {

            processing =
                false;
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
                100
            );
    }


    function stopProcessing() {

        if (processingTimer) {

            clearInterval(
                processingTimer
            );

            processingTimer =
                null;
        }
    }


    // ============================================================
    // UI
    // ============================================================

    function updateUI(s) {

        if (!s) {
            return;
        }


        // ========================================================
        // METRICS
        // ========================================================

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
                    ? Number(
                        s.pitch
                    ).toFixed(0) + "°"
                    : "-";
        }


        if ($("mYaw")) {

            $("mYaw").textContent =
                s.yaw != null
                    ? Number(
                        s.yaw
                    ).toFixed(0) + "°"
                    : "-";
        }


        if ($("mPerclos")) {

            $("mPerclos").textContent =
                s.perclos != null
                    ? (
                        Number(
                            s.perclos
                        ) * 100
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


        // ========================================================
        // COUNTERS
        // ========================================================

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


        // ========================================================
        // STATUS
        // ========================================================

        const level =
            String(
                s.level || "ALERT"
            ).toLowerCase();


        setLevel(
            level,
            s.status_text || "-",
            s.score || 0
        );


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
        }
    }


    // ============================================================
    // PILL
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


        if (s.drowsiness) {

            pill(
                $("stDrowsy"),
                "ALERT",
                "alert"
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


        if (
            s.attention ===
            "left"
        ) {

            pill(
                $("stAttention"),
                "Looking LEFT",
                "alert"
            );

        } else if (
            s.attention ===
            "right"
        ) {

            pill(
                $("stAttention"),
                "Looking RIGHT",
                "alert"
            );

        } else if (!face) {

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


        pill(
            $("stGlasses"),
            !face
                ? "–"
                : s.sunglasses_detected
                    ? "Detected"
                    : "Not detected",
            !face
                ? "idle"
                : s.sunglasses_detected
                    ? "warn"
                    : "normal"
        );


        const coverage =
            s.face_coverage;


        if (
            coverage ===
            "covered"
        ) {

            pill(
                $("stCoverage"),
                "COVERED",
                "alert"
            );

        } else if (
            coverage ===
            "partial"
        ) {

            pill(
                $("stCoverage"),
                "Partially covered",
                "warn"
            );

        } else if (
            coverage ===
            "clear"
        ) {

            pill(
                $("stCoverage"),
                "Clear",
                "normal"
            );

        } else {

            pill(
                $("stCoverage"),
                "–",
                "idle"
            );
        }
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

        if (
            s.attention_score != null
        ) {

            const v =
                Number(
                    s.attention_score
                );


            if ($("attNum")) {

                $("attNum").textContent =
                    Math.round(v);
            }


            if ($("attFill")) {

                $("attFill").style.width =
                    Math.max(
                        0,
                        Math.min(
                            100,
                            v
                        )
                    ) + "%";

                $("attFill").style.background =
                    scoreColor(v);
            }
        }


        if (
            s.safety_score != null
        ) {

            const v =
                Number(
                    s.safety_score
                );


            if ($("safeNum")) {

                $("safeNum").textContent =
                    Math.round(v);
            }


            if ($("safeFill")) {

                $("safeFill").style.width =
                    Math.max(
                        0,
                        Math.min(
                            100,
                            v
                        )
                    ) + "%";

                $("safeFill").style.background =
                    scoreColor(v);
            }
        }


        if (s.risk_level) {

            pill(
                $("riskPill"),
                "RISK " +
                    s.risk_level,
                s.risk_level ===
                    "LOW"
                    ? "normal"
                    : s.risk_level ===
                        "MEDIUM"
                        ? "warn"
                        : "alert"
            );
        }


        if (
            s.distraction_active
        ) {

            pill(
                $("stDistract"),
                Number(
                    s.distraction_duration ||
                    0
                ).toFixed(1) + "s",
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


        if (
            s.fatigue_trend ===
            "INCREASING"
        ) {

            pill(
                $("stFatigue"),
                "Rising ↑",
                "alert"
            );

        } else if (
            s.fatigue_trend ===
            "DECREASING"
        ) {

            pill(
                $("stFatigue"),
                "Easing ↓",
                "normal"
            );

        } else if (
            s.fatigue_trend ===
            "STABLE"
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


        if ($("notifProvider")) {

            $("notifProvider").textContent =
                n.provider || "–";
        }


        if ($("notifBadge")) {

            if (!n.enabled) {

                $("notifBadge").textContent =
                    "OFF";

            } else if (
                n.configured
            ) {

                $("notifBadge").textContent =
                    "READY";

            } else {

                $("notifBadge").textContent =
                    "SIMULATED";
            }
        }
    }


    // ============================================================
    // BREAK
    // ============================================================

    let breakDismissed =
        false;


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

        } else {

            banner.classList.add(
                "hidden"
            );
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


                breakDismissed =
                    true;
            }
        );
    }


    // ============================================================
    // VOICE
    // ============================================================

    let lastVoiceKey =
        null;

    let lastVoiceAt =
        0;


    function maybeSpeak(s) {

        if (
            !voiceToggle ||
            !voiceToggle.checked
        ) {

            return;
        }


        if (
            !window.speechSynthesis
        ) {

            return;
        }


        if (
            !s.voice_key ||
            !s.voice_text
        ) {

            return;
        }


        const now =
            Date.now();


        if (
            s.voice_key ===
                lastVoiceKey &&
            now - lastVoiceAt <
                8000
        ) {

            return;
        }


        lastVoiceKey =
            s.voice_key;


        lastVoiceAt =
            now;


        try {

            window.speechSynthesis.cancel();


            const utterance =
                new SpeechSynthesisUtterance(
                    s.voice_text
                );


            utterance.rate =
                1.0;


            utterance.volume =
                1.0;


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


    const MAX_POINTS =
        40;


    function pushHistory(
        array,
        value
    ) {

        if (
            value == null
        ) {

            return;
        }


        array.push({

            x:
                new Date()
                    .toLocaleTimeString(),

            y:
                Number(value)
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


        if (
            window.scoreChart
        ) {

            window.scoreChart.data.labels =
                scoreHistory.map(
                    p => p.x
                );


            window.scoreChart
                .data
                .datasets[0]
                .data =
                scoreHistory.map(
                    p => p.y
                );


            window.scoreChart.update(
                "none"
            );
        }


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

                    const cell =
                        document.createElement(
                            "div"
                        );


                    cell.className =
                        "summary-cell";


                    cell.innerHTML =
                        `
                        <div class="sc-num">
                            ${sum[key] ?? "–"}
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


    // ============================================================
    // EXPORT
    // ============================================================

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


        scoreHistory = [];

        earHistory = [];

        marHistory = [];

        attentionHistory = [];

        safetyHistory = [];

        breakDismissed =
            false;

        lastVoiceKey =
            null;
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


            updateMobile(
                state
            );

        } catch (e) {

            console.warn(
                "Initial state error:",
                e
            );
        }
    }


    loadInitialState();

})();