(function () {

    "use strict";


    // ============================================================
    // HELPERS
    // ============================================================

    const $ = (id) =>
        document.getElementById(id);


    const cameraVideo =
        $("cameraVideo");

    const feed =
        $("videoFeed");

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

    const voiceToggle =
        $("voiceToggle");

    const alarmFlash =
        $("alarmFlash");

    const statusCard =
        $("statusCard");


    let cameraStream = null;

    let running = false;

    let processing = false;

    let polling = null;

    let lastFrameTime = 0;

    const FRAME_INTERVAL = 180;


    // ============================================================
    // AUDIO
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

                const p =
                    audio.play();

                if (p) {

                    p.then(() => {

                        audio.pause();

                        audio.currentTime = 0;

                        audio.muted = false;

                    }).catch(() => {

                        audio.muted = false;

                    });

                }

            } catch (e) {

                audio.muted = false;

            }

        });

    }


    function playAlertSound(state) {

        if (!alarmToggle.checked) {

            stopAllAudio();

            return;

        }


        if (!state.alert_active) {

            stopAllAudio();

            return;

        }


        let desired = null;


        const type =
            state.alert_type || "";


        if (
            type.includes("CRITICAL")
        ) {

            desired =
                sndCritical;

        }

        else if (
            type.includes("SIDE_LOOK")
        ) {

            desired =
                sndSideLook;

        }

        else if (
            type.includes("FACE")
        ) {

            desired =
                sndFaceCovered;

        }

        else {

            desired =
                sndDrowsiness;

        }


        if (desired === currentSound) {

            return;

        }


        stopAllAudio();


        if (desired) {

            try {

                desired.loop = true;

                desired.currentTime = 0;

                desired.play()
                    .catch(() => {});

                currentSound =
                    desired;

            } catch (e) {}

        }


        if (alarmFlash) {

            alarmFlash.classList.add("on");

        }

    }


    alarmToggle.addEventListener(
        "change",
        function () {

            if (!alarmToggle.checked) {

                stopAllAudio();

            }

        }
    );


    // ============================================================
    // BROWSER CAMERA
    // ============================================================

    async function openBrowserCamera() {

        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia
        ) {

            throw new Error(
                "Your browser does not support camera access."
            );

        }


        const stream =
            await navigator.mediaDevices.getUserMedia({

                video: {

                    facingMode: "user",

                    width: {
                        ideal: 640
                    },

                    height: {
                        ideal: 480
                    }

                },

                audio: false

            });


        cameraStream =
            stream;


        cameraVideo.srcObject =
            stream;


        await cameraVideo.play();

    }


    function closeBrowserCamera() {

        if (!cameraStream) {

            return;

        }


        cameraStream
            .getTracks()
            .forEach(
                track => track.stop()
            );


        cameraStream = null;

        cameraVideo.srcObject =
            null;

    }


    // ============================================================
    // START
    // ============================================================

    startBtn.addEventListener(
        "click",
        async function () {

            startBtn.disabled =
                true;


            try {

                unlockAudio();


                // FIRST browser permission
                await openBrowserCamera();


                // THEN tell Flask that browser camera session started
                const response =
                    await fetch(
                        "/api/camera/start",
                        {
                            method: "POST"
                        }
                    );


                const result =
                    await response.json();


                if (!result.ok) {

                    throw new Error(
                        result.error ||
                        "Could not start detection."
                    );

                }


                running = true;


                cameraVideo.style.display =
                    "block";


                feed.style.display =
                    "none";


                placeholder.style.display =
                    "none";


                stopBtn.disabled =
                    false;


                startBtn.disabled =
                    true;


                startProcessing();


            }

            catch (error) {

                closeBrowserCamera();


                alert(
                    "Could not open the camera.\n\n" +
                    error.message +
                    "\n\n" +
                    "Please allow camera permission in your browser."
                );


                startBtn.disabled =
                    false;

            }

        }
    );


    // ============================================================
    // STOP
    // ============================================================

    stopBtn.addEventListener(
        "click",
        async function () {

            running = false;


            stopProcessing();


            closeBrowserCamera();


            try {

                await fetch(
                    "/api/camera/stop",
                    {
                        method: "POST"
                    }
                );

            } catch (e) {}


            cameraVideo.style.display =
                "none";


            feed.style.display =
                "none";


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


            stopAllAudio();


            try {

                window.speechSynthesis.cancel();

            } catch (e) {}


            await showSessionSummary();


            resetMonitor();

        }
    );


    // ============================================================
    // RESET
    // ============================================================

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


    // ============================================================
    // FRAME PROCESSING
    // ============================================================

    const captureCanvas =
        document.createElement(
            "canvas"
        );


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
            FRAME_INTERVAL
        ) {

            return;

        }


        lastFrameTime =
            now;


        processing =
            true;


        try {

            const width =
                Math.min(
                    cameraVideo.videoWidth,
                    640
                );


            const height =
                Math.round(
                    cameraVideo.videoHeight *
                    (width /
                    cameraVideo.videoWidth)
                );


            captureCanvas.width =
                width;

            captureCanvas.height =
                height;


            const ctx =
                captureCanvas.getContext(
                    "2d"
                );


            // Don't mirror here.
            // Backend mirrors frame.
            ctx.drawImage(
                cameraVideo,
                0,
                0,
                width,
                height
            );


            const blob =
                await new Promise(
                    resolve =>
                        captureCanvas.toBlob(
                            resolve,
                            "image/jpeg",
                            0.70
                        )
                );


            if (!blob) {

                return;

            }


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

                return;

            }


            const result =
                await response.json();


            if (!result.ok) {

                console.warn(
                    result.error
                );

                return;

            }


            const state =
                result.state;


            if (result.image) {

                feed.src =
                    result.image;

            }


            if (state) {

                updateUI(state);

            }

        }

        catch (error) {

            console.warn(
                "Frame processing error:",
                error
            );

        }

        finally {

            processing =
                false;

        }

    }


    function startProcessing() {

        stopProcessing();


        polling =
            setInterval(
                processBrowserFrame,
                50
            );

    }


    function stopProcessing() {

        if (polling) {

            clearInterval(
                polling
            );

            polling = null;

        }

    }


    // ============================================================
    // UI UPDATE
    // ============================================================

    function updateUI(s) {

        if (!s) return;


        $("mEar").textContent =
            fmt(s.ear);


        $("mMar").textContent =
            fmt(s.mar);


        $("mPitch").textContent =
            s.pitch != null
                ? Number(s.pitch).toFixed(0) + "°"
                : "-";


        $("mYaw").textContent =
            s.yaw != null
                ? Number(s.yaw).toFixed(0) + "°"
                : "-";


        $("mPerclos").textContent =
            s.perclos != null
                ? (
                    Number(s.perclos) *
                    100
                ).toFixed(0) + "%"
                : "-";


        $("mCnn").textContent =
            s.cnn_closed_prob != null
                ? Number(
                    s.cnn_closed_prob
                ).toFixed(2)
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


        updateMonitor(
            s
        );


        updateSafety(
            s
        );


        updateMobile(
            s
        );


        playAlertSound(
            s
        );


        maybeSpeak(
            s
        );


        updateBreak(
            s
        );


        updateCharts(
            s
        );

    }


    // ============================================================
    // STATUS
    // ============================================================

    function setLevel(
        level,
        text,
        score
    ) {

        statusCard.className =
            "card status-card level-" +
            level;


        $("statusText").textContent =
            text;


        $("scoreNum").textContent =
            Math.round(
                score
            );


        const fill =
            $("scoreFill");


        fill.style.width =
            Math.min(
                Number(score) || 0,
                100
            ) + "%";


        if (
            level === "drowsy"
        ) {

            fill.style.background =
                "#ef4444";

        }

        else if (
            level === "warning"
        ) {

            fill.style.background =
                "#f59e0b";

        }

        else {

            fill.style.background =
                "#22c55e";

        }

    }


    // ============================================================
    // MONITOR
    // ============================================================

    function pill(
        element,
        text,
        state
    ) {

        if (!element) return;


        element.textContent =
            text;


        element.className =
            "pill st-" +
            state;

    }


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

        }

        else {

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

        }

        else if (
            s.level ===
            "WARNING"
        ) {

            pill(
                $("stDrowsy"),
                "Warning",
                "warn"
            );

        }

        else {

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


        const attention =
            s.attention;


        if (
            attention ===
            "left"
        ) {

            pill(
                $("stAttention"),
                "Looking LEFT",
                "alert"
            );

        }

        else if (
            attention ===
            "right"
        ) {

            pill(
                $("stAttention"),
                "Looking RIGHT",
                "alert"
            );

        }

        else if (
            attention ===
            "no_face"
            ||
            !face
        ) {

            pill(
                $("stAttention"),
                "–",
                "idle"
            );

        }

        else {

            pill(
                $("stAttention"),
                "Forward",
                "normal"
            );

        }


        if (!face) {

            pill(
                $("stGlasses"),
                "–",
                "idle"
            );

        }

        else {

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


        const coverage =
            s.face_coverage;


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
                coverage
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
            attention != null
        ) {

            $("attNum").textContent =
                Math.round(
                    attention
                );


            $("attFill").style.width =
                Math.max(
                    0,
                    Math.min(
                        100,
                        attention
                    )
                ) + "%";


            $("attFill").style.background =
                scoreColor(
                    attention
                );

        }


        if (
            safety != null
        ) {

            $("safeNum").textContent =
                Math.round(
                    safety
                );


            $("safeFill").style.width =
                Math.max(
                    0,
                    Math.min(
                        100,
                        safety
                    )
                ) + "%";


            $("safeFill").style.background =
                scoreColor(
                    safety
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


        if (
            s.distraction_active
        ) {

            const duration =
                Number(
                    s.distraction_duration ||
                    0
                ).toFixed(1);


            pill(
                $("stDistract"),
                duration + "s",
                s.distraction_alert
                    ? "alert"
                    : "warn"
            );

        }

        else {

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


        const trend =
            s.fatigue_trend;


        if (
            trend ===
            "INCREASING"
        ) {

            pill(
                $("stFatigue"),
                "Rising ↑",
                "alert"
            );

        }

        else if (
            trend ===
            "DECREASING"
        ) {

            pill(
                $("stFatigue"),
                "Easing ↓",
                "normal"
            );

        }

        else if (
            trend ===
            "STABLE"
        ) {

            pill(
                $("stFatigue"),
                "Stable →",
                "normal"
            );

        }

        else {

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
            s.video_storage != null
        ) {

            $("videoStorage").textContent =
                s.video_storage
                    ? "ON"
                    : "OFF";

        }


        if (
            s.camera_processing
        ) {

            $("camProc").textContent =
                s.camera_processing;

        }


        const n =
            s.notifications;


        if (!n) return;


        if (!n.enabled) {

            $("notifBadge").textContent =
                "OFF";

            $("notifBadge").className =
                "badge badge-off";

        }

        else if (
            n.configured
        ) {

            $("notifBadge").textContent =
                "READY";

            $("notifBadge").className =
                "badge badge-on";

        }

        else {

            $("notifBadge").textContent =
                "SIMULATED";

            $("notifBadge").className =
                "badge badge-warnb";

        }


        $("notifProvider").textContent =
            n.provider || "–";

    }


    // ============================================================
    // BREAK
    // ============================================================

    let breakDismissed =
        false;


    function updateBreak(s) {

        const banner =
            $("breakBanner");


        if (
            s.break_recommended &&
            !breakDismissed
        ) {

            $("breakText").textContent =
                s.break_text ||
                "Take a short break.";


            banner.classList.remove(
                "hidden"
            );

        }

        else if (
            !s.break_recommended
        ) {

            banner.classList.add(
                "hidden"
            );

            breakDismissed =
                false;

        }

    }


    $("breakDismiss").addEventListener(
        "click",
        function () {

            $("breakBanner")
                .classList
                .add("hidden");

            breakDismissed =
                true;

        }
    );


    // ============================================================
    // VOICE
    // ============================================================

    let lastVoiceKey =
        null;

    let lastVoiceAt =
        0;


    const VOICE_COOLDOWN =
        (window.VOICE_COOLDOWN || 8) *
        1000;


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
                1;


            utterance.volume =
                1;


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


    function updateCharts(s) {

        const time =
            new Date()
                .toLocaleTimeString();


        scoreHistory.push({
            x: time,
            y: Number(
                s.score || 0
            )
        });


        earHistory.push({
            x: time,
            y: Number(
                s.ear || 0
            )
        });


        marHistory.push({
            x: time,
            y: Number(
                s.mar || 0
            )
        });


        attentionHistory.push({
            x: time,
            y: Number(
                s.attention_score ||
                0
            )
        });


        safetyHistory.push({
            x: time,
            y: Number(
                s.safety_score ||
                0
            )
        });


        const MAX =
            60;


        if (
            scoreHistory.length >
            MAX
        ) {

            scoreHistory.shift();

        }


        if (
            earHistory.length >
            MAX
        ) {

            earHistory.shift();

        }


        if (
            marHistory.length >
            MAX
        ) {

            marHistory.shift();

        }


        if (
            attentionHistory.length >
            MAX
        ) {

            attentionHistory.shift();

        }


        if (
            safetyHistory.length >
            MAX
        ) {

            safetyHistory.shift();

        }


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

    }


    // ============================================================
    // SUMMARY
    // ============================================================

    const summaryModal =
        $("summaryModal");


    async function showSessionSummary() {

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


            body.innerHTML =
                "";


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

        }

        catch (e) {}

    }


    $("summaryClose").addEventListener(
        "click",
        function () {

            summaryModal.classList.add(
                "hidden"
            );

        }
    );


    $("exportCsvBtn").addEventListener(
        "click",
        function () {

            window.location =
                "/api/events/export?fmt=csv";

        }
    );


    $("exportJsonBtn").addEventListener(
        "click",
        function () {

            window.location =
                "/api/events/export?fmt=json";

        }
    );


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
            id =>
                pill(
                    $(id),
                    "–",
                    "idle"
                )
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


        $("attNum").textContent =
            "–";


        $("safeNum").textContent =
            "–";


        $("attFill").style.width =
            "0%";


        $("safeFill").style.width =
            "0%";


        $("breakBanner")
            .classList
            .add("hidden");

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


            const state =
                await response.json();


            updateMobile(
                state
            );

        }

        catch (e) {}

    }


    loadInitialState();


})();