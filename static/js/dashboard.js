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
    // BROWSER CAMERA
    // ============================================================
    //
    // IMPORTANT:
    //
    // Browser camera is shown DIRECTLY on screen.
    //
    // Backend receives JPEG frames only for AI analysis.
    //
    // We DO NOT display backend result.image.
    //
    // This removes the visible camera delay.
    //
    // ============================================================

    let cameraVideo = $("cameraVideo");

    if (!cameraVideo) {

        cameraVideo = document.createElement("video");

        cameraVideo.id = "cameraVideo";

        cameraVideo.autoplay = true;
        cameraVideo.playsInline = true;
        cameraVideo.muted = true;

        // --------------------------------------------------------
        // Put camera inside the same container as videoFeed.
        // This is important for correct sizing/positioning.
        // --------------------------------------------------------

        const videoContainer =
            feed && feed.parentElement
                ? feed.parentElement
                : document.body;

        try {
            videoContainer.style.position = "relative";
            videoContainer.style.overflow = "hidden";
        } catch (e) {}

        cameraVideo.style.position = "absolute";
        cameraVideo.style.top = "0";
        cameraVideo.style.left = "0";

        cameraVideo.style.width = "100%";
        cameraVideo.style.height = "100%";

        cameraVideo.style.objectFit = "cover";

        cameraVideo.style.display = "none";

        cameraVideo.style.zIndex = "2";

        cameraVideo.style.borderRadius = "12px";

        cameraVideo.style.background = "#000";

        cameraVideo.style.pointerEvents = "none";

        videoContainer.appendChild(cameraVideo);
    }


    let cameraStream = null;

    let running = false;

    let processing = false;

    let processingTimer = null;

    let lastFrameTime = 0;


    // ============================================================
    // BACKEND ANALYSIS RATE
    // ============================================================
    //
    // Camera itself is NOT limited to this.
    //
    // Browser camera remains smooth.
    //
    // Only AI analysis requests are limited.
    //
    // 300ms = approximately 3.3 analysis FPS.
    //
    // This is safer for Render Free than sending every frame.
    //
    // ============================================================

    const FRAME_INTERVAL = 300;


    // ============================================================
    // AUDIO
    // ============================================================

    const sndDrowsiness = $("sndDrowsiness");
    const sndSideLook = $("sndSideLook");
    const sndFaceCovered = $("sndFaceCovered");
    const sndCritical = $("sndCritical");

    let currentSound = null;


    // ============================================================
    // STOP ALL AUDIO
    // ============================================================

    function stopAllAudio() {

        [
            sndDrowsiness,
            sndSideLook,
            sndFaceCovered,
            sndCritical
        ].forEach((audio) => {

            if (!audio) {
                return;
            }

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


    // ============================================================
    // AUDIO UNLOCK
    // ============================================================

    function unlockAudio() {

        [
            sndDrowsiness,
            sndSideLook,
            sndFaceCovered,
            sndCritical
        ].forEach((audio) => {

            if (!audio) {
                return;
            }

            try {

                audio.muted = true;

                const promise =
                    audio.play();

                if (
                    promise &&
                    promise.then
                ) {

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

                try {

                    audio.muted = false;

                } catch (err) {}
            }
        });
    }


    // ============================================================
    // PLAY ALERT SOUND
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

        let desired = null;

        const type =
            String(
                state.alert_type || ""
            ).toUpperCase();


        // --------------------------------------------------------
        // CRITICAL
        // --------------------------------------------------------

        if (
            type.includes("CRITICAL")
        ) {

            desired =
                sndCritical;

        }


        // --------------------------------------------------------
        // SIDE LOOK
        // --------------------------------------------------------

        else if (
            type.includes("SIDE_LOOK")
        ) {

            desired =
                sndSideLook;

        }


        // --------------------------------------------------------
        // FACE COVERED
        // --------------------------------------------------------

        else if (
            type.includes("FACE") ||
            type.includes("COVERED")
        ) {

            desired =
                sndFaceCovered;

        }


        // --------------------------------------------------------
        // NORMAL DROWSINESS
        // --------------------------------------------------------

        else {

            desired =
                sndDrowsiness;
        }


        if (!desired) {

            stopAllAudio();

            return;
        }


        // Same sound already playing.
        if (
            desired === currentSound
        ) {

            return;
        }


        stopAllAudio();


        try {

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

        } catch (e) {}


        // --------------------------------------------------------
        // VISUAL FLASH
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
    }


    // ============================================================
    // AUDIO TOGGLE
    // ============================================================

    if (alarmToggle) {

        alarmToggle.addEventListener(
            "change",
            function () {

                if (
                    !alarmToggle.checked
                ) {

                    stopAllAudio();
                }
            }
        );
    }


    // ============================================================
    // OPEN BROWSER CAMERA
    // ============================================================

    async function openBrowserCamera() {

        console.log(
            "[CAMERA] Opening browser camera..."
        );


        // --------------------------------------------------------
        // CAMERA API CHECK
        // --------------------------------------------------------

        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia
        ) {

            throw new Error(
                "Camera API is not supported by this browser/context."
            );
        }


        // --------------------------------------------------------
        // SECURE CONTEXT CHECK
        //
        // Allowed:
        //
        // https://
        // http://localhost
        // http://127.0.0.1
        //
        // NOT allowed:
        //
        // http://192.168.x.x
        //
        // --------------------------------------------------------

        if (
            location.protocol !== "https:" &&
            location.hostname !== "localhost" &&
            location.hostname !== "127.0.0.1"
        ) {

            throw new Error(
                "Camera requires HTTPS.\n\n" +
                "For local testing use:\n" +
                "http://127.0.0.1:5001\n\n" +
                "For deployment use your Render HTTPS URL."
            );
        }


        // --------------------------------------------------------
        // REQUEST CAMERA
        // --------------------------------------------------------

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
                        ideal: 24,
                        max: 30
                    }
                },

                audio: false
            });


        // --------------------------------------------------------
        // SAVE STREAM
        // --------------------------------------------------------

        cameraStream =
            stream;


        cameraVideo.srcObject =
            stream;


        cameraVideo.muted =
            true;

        cameraVideo.playsInline =
            true;

        cameraVideo.autoplay =
            true;


        // --------------------------------------------------------
        // WAIT FOR CAMERA
        // --------------------------------------------------------

        await new Promise(
            (resolve, reject) => {

                let finished = false;


                const finish =
                    () => {

                        if (finished) {
                            return;
                        }

                        finished = true;

                        clearTimeout(
                            timeout
                        );

                        resolve();
                    };


                const fail =
                    (error) => {

                        if (finished) {
                            return;
                        }

                        finished = true;

                        clearTimeout(
                            timeout
                        );

                        reject(error);
                    };


                const timeout =
                    setTimeout(
                        () => {

                            fail(
                                new Error(
                                    "Camera video did not start."
                                )
                            );

                        },
                        10000
                    );


                cameraVideo.onloadedmetadata =
                    finish;


                cameraVideo.oncanplay =
                    finish;


                cameraVideo.onerror =
                    () => {

                        fail(
                            new Error(
                                "Browser camera video error."
                            )
                        );
                    };


                if (
                    cameraVideo.readyState >= 1
                ) {

                    finish();
                }
            }
        );


        // --------------------------------------------------------
        // PLAY
        // --------------------------------------------------------

        await cameraVideo.play();


        console.log(
            "[CAMERA] Started:",
            cameraVideo.videoWidth,
            "x",
            cameraVideo.videoHeight
        );
    }


    // ============================================================
    // CLOSE BROWSER CAMERA
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

            cameraStream =
                null;
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
    // START CAMERA
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

                    console.log(
                        "[CAMERA] Start button clicked."
                    );


                    // ------------------------------------------------
                    // UNLOCK AUDIO
                    // ------------------------------------------------

                    unlockAudio();


                    // ------------------------------------------------
                    // OPEN BROWSER CAMERA
                    // ------------------------------------------------

                    await openBrowserCamera();


                    // ------------------------------------------------
                    // START SERVER SESSION
                    // ------------------------------------------------

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


                    if (!response.ok) {

                        throw new Error(
                            "Server camera session could not be started. HTTP " +
                            response.status
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


                    // ------------------------------------------------
                    // RUNNING
                    // ------------------------------------------------

                    running =
                        true;

                    lastFrameTime =
                        0;

                    processing =
                        false;


                    // =================================================
                    // IMPORTANT:
                    //
                    // SHOW RAW BROWSER CAMERA.
                    //
                    // DO NOT SHOW BACKEND PROCESSED JPEG.
                    //
                    // This is what removes visible camera delay.
                    // =================================================

                    if (cameraVideo) {

                        cameraVideo.style.display =
                            "block";
                    }


                    // Backend processed image is hidden.
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


                    if (stopBtn) {

                        stopBtn.disabled =
                            false;
                    }


                    startBtn.disabled =
                        true;


                    console.log(
                        "[CAMERA] Detection pipeline started."
                    );


                    // ------------------------------------------------
                    // START BACKEND ANALYSIS LOOP
                    // ------------------------------------------------

                    startProcessing();

                } catch (error) {

                    console.error(
                        "[CAMERA] Start error:",
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
                            placeholder.querySelector(
                                "p"
                            );


                        if (p) {

                            p.textContent =
                                "Camera stopped";
                        }
                    }


                    if (feed) {

                        feed.style.display =
                            "none";

                        feed.removeAttribute(
                            "src"
                        );
                    }


                    if (stopBtn) {

                        stopBtn.disabled =
                            true;
                    }


                    startBtn.disabled =
                        false;


                    alert(
                        "Could not start camera.\n\n" +
                        error.message +
                        "\n\n" +
                        "For local testing use:\n" +
                        "http://127.0.0.1:5001"
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

                console.log(
                    "[CAMERA] Stop button clicked."
                );


                running =
                    false;


                stopProcessing();


                closeBrowserCamera();


                stopAllAudio();


                // ------------------------------------------------
                // STOP SERVER SESSION
                // ------------------------------------------------

                try {

                    await fetch(
                        "/api/camera/stop",
                        {
                            method: "POST",

                            headers: {
                                "Accept":
                                    "application/json"
                            }
                        }
                    );

                } catch (e) {

                    console.warn(
                        "[CAMERA] Server stop error:",
                        e
                    );
                }


                // ------------------------------------------------
                // HIDE VIDEO
                // ------------------------------------------------

                if (cameraVideo) {

                    cameraVideo.style.display =
                        "none";
                }


                if (feed) {

                    feed.style.display =
                        "none";

                    feed.removeAttribute(
                        "src"
                    );
                }


                if (placeholder) {

                    placeholder.style.display =
                        "block";


                    const p =
                        placeholder.querySelector(
                            "p"
                        );


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


                // ------------------------------------------------
                // STOP VOICE
                // ------------------------------------------------

                try {

                    if (
                        window.speechSynthesis
                    ) {

                        window.speechSynthesis.cancel();
                    }

                } catch (e) {}


                // ------------------------------------------------
                // SESSION SUMMARY
                // ------------------------------------------------

                await showSessionSummary();


                // ------------------------------------------------
                // RESET UI
                // ------------------------------------------------

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
                                "Accept":
                                    "application/json"
                            }
                        }
                    );

                } catch (e) {

                    console.warn(
                        "[RESET] Server reset error:",
                        e
                    );
                }


                resetMonitor();
            }
        );
    }


    // ============================================================
    // FRAME CAPTURE CANVAS
    // ============================================================

    const captureCanvas =
        document.createElement(
            "canvas"
        );


    const canvasContext =
        captureCanvas.getContext(
            "2d",
            {
                willReadFrequently:
                    false
            }
        );


    // ============================================================
    // PROCESS BROWSER FRAME
    // ============================================================
    //
    // IMPORTANT:
    //
    // This function sends a frame to backend.
    //
    // It DOES NOT replace the visible camera.
    //
    // Camera remains smooth because cameraVideo plays directly.
    //
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

            // --------------------------------------------------------
            // SMALL FRAME FOR SERVER
            // --------------------------------------------------------

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


            // --------------------------------------------------------
            // JPEG
            // --------------------------------------------------------

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


            // --------------------------------------------------------
            // FORM DATA
            // --------------------------------------------------------

            const formData =
                new FormData();


            formData.append(
                "frame",
                blob,
                "camera.jpg"
            );


            // --------------------------------------------------------
            // SEND TO FLASK
            // --------------------------------------------------------

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
                    "[FRAME] HTTP error:",
                    response.status
                );

                return;
            }


            const result =
                await response.json();


            if (!result.ok) {

                console.warn(
                    "[FRAME] Backend error:",
                    result.error
                );

                return;
            }


            // ========================================================
            // IMPORTANT
            //
            // DO NOT DO:
            //
            // feed.src = result.image
            //
            // That causes visible camera delay.
            //
            // The browser camera is already displayed directly.
            // ========================================================


            // --------------------------------------------------------
            // UPDATE LIVE AI STATE
            // --------------------------------------------------------

            if (result.state) {

                updateUI(
                    result.state
                );
            }

        } catch (error) {

            console.warn(
                "[FRAME] Processing error:",
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
                50
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
    // FORMAT
    // ============================================================

    function fmt(value) {

        if (
            value === null ||
            value === undefined ||
            Number.isNaN(
                Number(value)
            )
        ) {

            return "-";
        }


        return Number(value)
            .toFixed(3);
    }


    // ============================================================
    // UI UPDATE
    // ============================================================

    function updateUI(s) {

        if (!s) {
            return;
        }


        // --------------------------------------------------------
        // METRICS
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
                    ? Number(s.pitch)
                        .toFixed(0) + "°"
                    : "-";
        }


        if ($("mYaw")) {

            $("mYaw").textContent =
                s.yaw != null
                    ? Number(s.yaw)
                        .toFixed(0) + "°"
                    : "-";
        }


        if ($("mPerclos")) {

            $("mPerclos").textContent =
                s.perclos != null
                    ? (
                        Number(s.perclos) *
                        100
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
        // COUNTERS
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
        // STATUS
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
        // MONITOR
        // --------------------------------------------------------

        updateMonitor(s);


        // --------------------------------------------------------
        // SAFETY
        // --------------------------------------------------------

        updateSafety(s);


        // --------------------------------------------------------
        // MOBILE
        // --------------------------------------------------------

        updateMobile(s);


        // --------------------------------------------------------
        // AUDIO
        // --------------------------------------------------------

        playAlertSound(s);


        // --------------------------------------------------------
        // VOICE
        // --------------------------------------------------------

        maybeSpeak(s);


        // --------------------------------------------------------
        // BREAK
        // --------------------------------------------------------

        updateBreak(s);


        // --------------------------------------------------------
        // CHARTS
        // --------------------------------------------------------

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


            if (
                level === "drowsy"
            ) {

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
    // REAL-TIME MONITOR
    // ============================================================

    function updateMonitor(s) {

        const face =
            !!s.face_detected;


        // --------------------------------------------------------
        // FACE
        // --------------------------------------------------------

        pill(
            $("stFace"),
            face
                ? "Detected"
                : "Not detected",
            face
                ? "normal"
                : "alert"
        );


        // --------------------------------------------------------
        // EYES
        // --------------------------------------------------------

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


        // --------------------------------------------------------
        // DROWSINESS
        // --------------------------------------------------------

        if (s.drowsiness) {

            pill(
                $("stDrowsy"),
                "ALERT",
                "alert"
            );

        } else if (
            String(
                s.level || ""
            ).toUpperCase() ===
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


        // --------------------------------------------------------
        // ATTENTION
        // --------------------------------------------------------

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


        // --------------------------------------------------------
        // SUNGLASSES
        // --------------------------------------------------------

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


        // --------------------------------------------------------
        // FACE COVERAGE
        // --------------------------------------------------------

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


        // --------------------------------------------------------
        // ATTENTION SCORE
        // --------------------------------------------------------

        if (
            attention != null &&
            $("attNum") &&
            $("attFill")
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
                        Number(attention)
                    )
                ) + "%";


            $("attFill").style.background =
                scoreColor(
                    Number(attention)
                );
        }


        // --------------------------------------------------------
        // SAFETY SCORE
        // --------------------------------------------------------

        if (
            safety != null &&
            $("safeNum") &&
            $("safeFill")
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
                        Number(safety)
                    )
                ) + "%";


            $("safeFill").style.background =
                scoreColor(
                    Number(safety)
                );
        }


        // --------------------------------------------------------
        // RISK
        // --------------------------------------------------------

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


        // --------------------------------------------------------
        // DISTRACTION
        // --------------------------------------------------------

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


        // --------------------------------------------------------
        // FATIGUE
        // --------------------------------------------------------

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


        if (!$("notifBadge")) {
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

        } else if (
            !s.break_recommended
        ) {

            banner.classList.add(
                "hidden"
            );


            breakDismissed =
                false;
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

    let scoreHistory =
        [];

    let earHistory =
        [];

    let marHistory =
        [];

    let attentionHistory =
        [];

    let safetyHistory =
        [];


    const MAX_POINTS =
        60;


    function pushHistory(
        array,
        value
    ) {

        array.push({

            x:
                new Date()
                    .toLocaleTimeString(),

            y:
                Number(value || 0)
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


        // --------------------------------------------------------
        // SCORE
        // --------------------------------------------------------

        if (
            window.scoreChart
        ) {

            window.scoreChart.data.labels =
                scoreHistory.map(
                    p => p.x
                );


            if (
                window.scoreChart
                    .data
                    .datasets
                    .length
            ) {

                window.scoreChart
                    .data
                    .datasets[0]
                    .data =
                    scoreHistory.map(
                        p => p.y
                    );
            }


            window.scoreChart.update(
                "none"
            );
        }


        // --------------------------------------------------------
        // EAR / MAR
        // --------------------------------------------------------

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


        // --------------------------------------------------------
        // SAFETY
        // --------------------------------------------------------

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


    // ============================================================
    // SUMMARY CLOSE
    // ============================================================

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
    // EXPORT CSV
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


    // ============================================================
    // EXPORT JSON
    // ============================================================

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


        breakDismissed =
            false;


        lastVoiceKey =
            null;


        scoreHistory =
            [];


        earHistory =
            [];


        marHistory =
            [];


        attentionHistory =
            [];


        safetyHistory =
            [];
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


    // ============================================================
    // START INITIAL STATE
    // ============================================================

    loadInitialState();

})();