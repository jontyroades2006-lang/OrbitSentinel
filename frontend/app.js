/* OrbitSentinel frontend
 * CesiumJS globe + control panels
 * Communicates with Flask API in backend/main.py
 */

"use strict";

const API_BASE = "";

// ============================================================
// STATE
// ============================================================

const state = {
    viewer: null,
    activeDataSource: null,

    primary: null,
    secondary: null,

    lastConjunction: null,

    whatIfMode: "altitude"
};


// ============================================================
// CESIUM VIEWER
// ============================================================

function initViewer() {

    const imageryProvider =
        new Cesium.TileMapServiceImageryProvider({
            url: Cesium.buildModuleUrl(
                "Assets/Textures/NaturalEarthII"
            )
        });

    const viewer = new Cesium.Viewer(
        "cesiumContainer",
        {
            imageryProvider: imageryProvider,

            baseLayerPicker: false,
            geocoder: false,
            homeButton: false,
            sceneModePicker: true,
            navigationHelpButton: false,

            animation: true,
            timeline: true,

            fullscreenButton: false,
            infoBox: false,
            selectionIndicator: true,

            shouldAnimate: true
        }
    );

    viewer.scene.globe.enableLighting = true;

    viewer.scene.skyAtmosphere.hueShift = -0.02;

    viewer.scene.backgroundColor =
        Cesium.Color.fromCssColorString("#070b12");

    viewer.camera.setView({
        destination:
            Cesium.Cartesian3.fromDegrees(
                0,
                20,
                22000000
            )
    });

    state.viewer = viewer;


    // --------------------------------------------------------
    // Globe click
    // --------------------------------------------------------

    const handler =
        new Cesium.ScreenSpaceEventHandler(
            viewer.scene.canvas
        );

    handler.setInputAction(
        (movement) => {

            const picked =
                viewer.scene.pick(
                    movement.position
                );

            if (
                Cesium.defined(picked) &&
                picked.id &&
                typeof picked.id.id === "string" &&
                picked.id.id.startsWith("sat-")
            ) {

                showQuickSelect(
                    picked.id,
                    movement.position
                );

            } else {

                hideQuickSelect();
            }

        },
        Cesium.ScreenSpaceEventType.LEFT_CLICK
    );

    return viewer;
}


// ============================================================
// LOAD CZML
// ============================================================

async function loadCzmlIntoViewer(
    czmlJson,
    flyTo = true
) {

    const viewer = state.viewer;

    const newSource =
        await Cesium.CzmlDataSource.load(
            czmlJson
        );


    if (state.activeDataSource) {

        viewer.dataSources.remove(
            state.activeDataSource,
            true
        );
    }


    await viewer.dataSources.add(
        newSource
    );

    state.activeDataSource =
        newSource;


    // --------------------------------------------------------
    // Update Cesium clock
    // --------------------------------------------------------

    if (newSource.clock) {

        viewer.clock.startTime =
            newSource.clock.startTime.clone();

        viewer.clock.stopTime =
            newSource.clock.stopTime.clone();

        viewer.clock.currentTime =
            newSource.clock.currentTime.clone();

        viewer.clock.multiplier =
            newSource.clock.multiplier;

        viewer.clock.clockRange =
            newSource.clock.clockRange;

        viewer.timeline.zoomTo(
            newSource.clock.startTime,
            newSource.clock.stopTime
        );
    }


    if (flyTo) {

        viewer.zoomTo(
            newSource
        ).catch(() => {});
    }


    return newSource;
}


// ============================================================
// API GET
// ============================================================

async function apiGet(path) {

    const response =
        await fetch(
            API_BASE + path
        );


    if (!response.ok) {

        const body =
            await response
                .json()
                .catch(() => ({}));

        throw new Error(
            body.error ||
            `Request failed (${response.status})`
        );
    }


    return response.json();
}


// ============================================================
// API POST
// ============================================================

async function apiPost(
    path,
    payload
) {

    const response =
        await fetch(
            API_BASE + path,
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify(payload)
            }
        );


    if (!response.ok) {

        const body =
            await response
                .json()
                .catch(() => ({}));

        throw new Error(
            body.error ||
            `Request failed (${response.status})`
        );
    }


    return response.json();
}


// ============================================================
// BACKEND STATUS
// ============================================================

function setBackendStatus(
    mode,
    text
) {

    const element =
        document.getElementById(
            "backendStatus"
        );

    if (!element) return;


    element.className =
        "status-pill " + mode;


    element.innerHTML =
        `<span class="dot"></span> ${text}`;
}


// ============================================================
// DEFAULT GLOBE VIEW
// ============================================================

async function loadDefaultCatalogView() {

    const czml =
        await apiGet(
            "/api/catalog/czml?hours=3&step_seconds=60"
        );


    await loadCzmlIntoViewer(
        czml,
        true
    );


    hideAlertCard();
    hideWhatIfPanel();
}


// ============================================================
// SEARCH
// ============================================================

function statusChipHtml(status) {

    const valid =
        [
            "active",
            "inactive",
            "debris"
        ];


    const cls =
        valid.includes(status)
            ? status
            : "unknown";


    return `
        <span class="status-chip ${cls}">
            ${status}
        </span>
    `;
}


async function doSearch() {

    const input =
        document.getElementById(
            "searchInput"
        );

    if (!input) return;


    const query =
        input.value.trim();


    try {

        const data =
            await apiGet(
                `/api/search?q=${encodeURIComponent(query)}`
            );


        renderSearchResults(
            data.results || []
        );

    } catch (error) {

        console.error(
            "Search failed:",
            error
        );

        alert(
            "Search failed: " +
            error.message
        );
    }
}


function renderSearchResults(
    results
) {

    const container =
        document.getElementById(
            "searchResults"
        );

    if (!container) return;


    container.innerHTML = "";


    if (!results.length) {

        container.innerHTML =
            `<div class="result-meta">
                No matches.
            </div>`;

        return;
    }


    results.forEach(
        (satellite) => {

            const item =
                document.createElement(
                    "div"
                );

            item.className =
                "result-item";


            item.innerHTML = `
                <div>
                    <div class="result-name">
                        ${satellite.name}
                    </div>

                    <div class="result-meta">
                        NORAD ${satellite.norad_id}
                        · ${satellite.operator}
                    </div>
                </div>

                ${statusChipHtml(
                    satellite.status
                )}
            `;


            item.addEventListener(
                "click",
                () => {
                    openDetail(
                        satellite.norad_id
                    );
                }
            );


            container.appendChild(
                item
            );
        }
    );
}


// ============================================================
// SATELLITE DETAILS
// ============================================================

async function openDetail(
    noradId
) {

    try {

        const satellite =
            await apiGet(
                `/api/satellites/${noradId}`
            );


        const drawer =
            document.getElementById(
                "detailDrawer"
            );

        const content =
            document.getElementById(
                "detailContent"
            );


        if (!drawer || !content) return;


        const orbit =
            satellite.orbit_summary;


        content.innerHTML = `

            <div class="detail-name">
                ${satellite.name}
            </div>

            <div class="detail-id">
                NORAD ${satellite.norad_id}
                ·
                ${statusChipHtml(
                    satellite.status
                )}
            </div>


            <div class="detail-grid">

                <div class="detail-field">
                    <div class="detail-field-label">
                        Operator
                    </div>

                    <div class="detail-field-value">
                        ${satellite.operator}
                    </div>
                </div>


                <div class="detail-field">
                    <div class="detail-field-label">
                        Type
                    </div>

                    <div class="detail-field-value">
                        ${satellite.object_type}
                    </div>
                </div>


                <div class="detail-field">
                    <div class="detail-field-label">
                        Perigee alt
                    </div>

                    <div class="detail-field-value">
                        ${orbit.perigee_alt_km} km
                    </div>
                </div>


                <div class="detail-field">
                    <div class="detail-field-label">
                        Apogee alt
                    </div>

                    <div class="detail-field-value">
                        ${orbit.apogee_alt_km} km
                    </div>
                </div>


                <div class="detail-field">
                    <div class="detail-field-label">
                        Inclination
                    </div>

                    <div class="detail-field-value">
                        ${orbit.inclination_deg}°
                    </div>
                </div>


                <div class="detail-field">
                    <div class="detail-field-label">
                        Period
                    </div>

                    <div class="detail-field-value">
                        ${orbit.period_min} min
                    </div>
                </div>


                <div class="detail-field">
                    <div class="detail-field-label">
                        Population served
                    </div>

                    <div class="detail-field-value">
                        ${Number(
                            satellite.population_served
                        ).toLocaleString()}
                    </div>
                </div>


                <div class="detail-field">
                    <div class="detail-field-label">
                        Replacement cost
                    </div>

                    <div class="detail-field-value">
                        $${Number(
                            satellite.replacement_cost_usd
                        ).toLocaleString()}
                    </div>
                </div>

            </div>


            <div class="detail-actions">

                <button
                    class="btn btn-ghost small"
                    id="detailSetPrimary">
                    Set Primary
                </button>


                <button
                    class="btn btn-ghost small"
                    id="detailSetSecondary">
                    Set Secondary
                </button>

            </div>
        `;


        document
            .getElementById(
                "detailSetPrimary"
            )
            .addEventListener(
                "click",
                () => setPrimary(satellite)
            );


        document
            .getElementById(
                "detailSetSecondary"
            )
            .addEventListener(
                "click",
                () => setSecondary(satellite)
            );


        drawer.classList.remove(
            "hidden"
        );

    } catch (error) {

        console.error(
            "Detail loading failed:",
            error
        );

        alert(
            "Could not load satellite details: " +
            error.message
        );
    }
}


// ============================================================
// PAIR SELECTION
// ============================================================

function setPrimary(
    satellite
) {

    state.primary =
        satellite;


    const element =
        document.querySelector(
            "#primarySlot .pair-slot-value"
        );


    if (element) {

        element.textContent =
            `${satellite.name} (${satellite.norad_id})`;
    }


    updateAnalyzeButton();
}


function setSecondary(
    satellite
) {

    state.secondary =
        satellite;


    const element =
        document.querySelector(
            "#secondarySlot .pair-slot-value"
        );


    if (element) {

        element.textContent =
            `${satellite.name} (${satellite.norad_id})`;
    }


    updateAnalyzeButton();
}


function clearPair() {

    state.primary = null;
    state.secondary = null;
    state.lastConjunction = null;


    const primary =
        document.querySelector(
            "#primarySlot .pair-slot-value"
        );

    const secondary =
        document.querySelector(
            "#secondarySlot .pair-slot-value"
        );


    if (primary) {

        primary.textContent =
            "— none selected —";
    }


    if (secondary) {

        secondary.textContent =
            "— none selected —";
    }


    updateAnalyzeButton();

    hideAlertCard();

    hideWhatIfPanel();
}


function updateAnalyzeButton() {

    const button =
        document.getElementById(
            "analyzeBtn"
        );

    if (!button) return;


    button.disabled =
        !(
            state.primary &&
            state.secondary &&
            state.primary.norad_id !==
            state.secondary.norad_id
        );
}


// ============================================================
// QUICK SELECT
// ============================================================

function showQuickSelect(
    entity,
    screenPosition
) {

    const popup =
        document.getElementById(
            "quickSelectPopup"
        );

    if (!popup) return;


    const noradId =
        entity.id
            .replace("sat-", "")
            .split("-")[0];


    const name =
        document.getElementById(
            "quickSelectName"
        );


    if (name) {

        name.textContent =
            entity.name ||
            noradId;
    }


    popup.style.left =
        `${screenPosition.x + 14}px`;

    popup.style.top =
        `${screenPosition.y + 14}px`;


    popup.classList.remove(
        "hidden"
    );


    const primaryButton =
        document.getElementById(
            "qsPrimaryBtn"
        );


    const secondaryButton =
        document.getElementById(
            "qsSecondaryBtn"
        );


    if (primaryButton) {

        primaryButton.onclick =
            async () => {

                try {

                    const satellite =
                        await apiGet(
                            `/api/satellites/${noradId}`
                        );

                    setPrimary(
                        satellite
                    );

                    hideQuickSelect();

                } catch (error) {

                    alert(
                        error.message
                    );
                }
            };
    }


    if (secondaryButton) {

        secondaryButton.onclick =
            async () => {

                try {

                    const satellite =
                        await apiGet(
                            `/api/satellites/${noradId}`
                        );

                    setSecondary(
                        satellite
                    );

                    hideQuickSelect();

                } catch (error) {

                    alert(
                        error.message
                    );
                }
            };
    }
}


function hideQuickSelect() {

    const popup =
        document.getElementById(
            "quickSelectPopup"
        );


    if (popup) {

        popup.classList.add(
            "hidden"
        );
    }
}


// ============================================================
// CONJUNCTION ANALYSIS
// ============================================================

async function analyzeConjunction() {

    if (
        !state.primary ||
        !state.secondary
    ) {
        return;
    }


    const hoursInput =
        document.getElementById(
            "hoursInput"
        );


    const hours =
        hoursInput
            ? Number(hoursInput.value)
            : 24;


    const button =
        document.getElementById(
            "analyzeBtn"
        );


    if (button) {

        button.disabled = true;

        button.textContent =
            "Analyzing...";
    }


    setBackendStatus(
        "",
        "analyzing…"
    );


    try {

        const result =
            await apiGet(
                `/api/conjunction` +
                `?a=${state.primary.norad_id}` +
                `&b=${state.secondary.norad_id}` +
                `&hours=${hours}`
            );


        state.lastConjunction =
            result;


        await loadCzmlIntoViewer(
            result.czml,
            true
        );


        renderAlertCard(
            result
        );


        showWhatIfPanel();


        setBackendStatus(
            "ok",
            "online"
        );

    } catch (error) {

        console.error(
            "Conjunction analysis failed:",
            error
        );


        setBackendStatus(
            "error",
            "error"
        );


        alert(
            "Conjunction analysis failed: " +
            error.message
        );

    } finally {

        updateAnalyzeButton();

        if (button) {

            button.textContent =
                "Analyze";
        }
    }
}


// ============================================================
// TIME FORMAT
// ============================================================

function fmtTime(
    iso
) {

    if (!iso) {
        return "—";
    }


    const date =
        new Date(iso);


    if (Number.isNaN(
        date.getTime()
    )) {

        return "—";
    }


    return (
        date
            .toISOString()
            .replace("T", " ")
            .slice(0, 19)
        + " UTC"
    );
}


// ============================================================
// RISK BAR
// ============================================================

function riskBarRow(
    label,
    value
) {

    const safeValue =
        Math.max(
            0,
            Math.min(
                1,
                Number(value) || 0
            )
        );


    const percentage =
        Math.round(
            safeValue * 100
        );


    return `

        <div class="risk-bar-row">

            <div class="risk-bar-label">
                ${label}
            </div>

            <div class="risk-bar-track">

                <div
                    class="risk-bar-fill"
                    style="width:${percentage}%">
                </div>

            </div>

        </div>
    `;
}


// ============================================================
// ALERT CARD
// ============================================================

function renderAlertCard(
    result
) {

    const card =
        document.getElementById(
            "alertCard"
        );


    if (!card) return;


    const alertData =
        result.alert || {};


    const risk =
        result.risk || {};


    const components =
        risk.components || {};


    card.className =
        `alert-card ${
            alertData.risk_category || ""
        }`;


    card.innerHTML = `

        <div class="alert-header">

            <div class="alert-title">
                CONJUNCTION ALERT
            </div>

            <div
                class="alert-category ${
                    alertData.risk_category || ""
                }">

                ${
                    alertData.risk_category ||
                    "UNKNOWN"
                }

            </div>

        </div>


        <div class="alert-headline">

            ${
                alertData.headline ||
                "Conjunction detected"
            }

        </div>


        <div class="alert-metrics">

            <div>

                <div class="alert-metric-label">
                    Closest approach
                </div>

                <div class="alert-metric-value">

                    ${
                        alertData.closest_approach_km ??
                        "—"
                    }
                    km

                </div>

            </div>


            <div>

                <div class="alert-metric-label">
                    Risk score
                </div>

                <div class="alert-metric-value">

                    ${
                        alertData.risk_score ??
                        "—"
                    }
                    / 100

                </div>

            </div>


            <div>

                <div class="alert-metric-label">
                    Time of closest approach
                </div>

                <div
                    class="alert-metric-value"
                    style="font-size:11.5px">

                    ${
                        fmtTime(
                            alertData
                                .time_of_closest_approach_utc
                        )
                    }

                </div>

            </div>


            <div>

                <div class="alert-metric-label">
                    Confidence
                </div>

                <div class="alert-metric-value">

                    ${
                        alertData.confidence_pct ??
                        "—"
                    }%

                    ${
                        alertData.confidence_label
                            ? `(${alertData.confidence_label})`
                            : ""
                    }

                </div>

            </div>

        </div>


        <div class="risk-bars">

            ${riskBarRow(
                "Severity",
                components.conjunction_severity
            )}

            ${riskBarRow(
                "Op. status",
                components.operational_status
            )}

            ${riskBarRow(
                "Population",
                components.population_served
            )}

            ${riskBarRow(
                "Repl. cost",
                components.replacement_cost
            )}

        </div>


        <div class="legend-row">

            <span
                class="legend-swatch"
                style="background:#ff5d73">
            </span>

            Primary


            <span
                class="legend-swatch"
                style="background:#ffd166">
            </span>

            Secondary


            <span
                class="legend-swatch"
                style="background:#ff4d4d">
            </span>

            TCA marker

        </div>
    `;


    card.classList.remove(
        "hidden"
    );
}


function hideAlertCard() {

    const card =
        document.getElementById(
            "alertCard"
        );


    if (card) {

        card.classList.add(
            "hidden"
        );
    }
}


// ============================================================
// WHAT-IF PANEL
// ============================================================

function showWhatIfPanel() {

    const panel =
        document.getElementById(
            "whatIfPanel"
        );


    if (panel) {

        panel.classList.remove(
            "hidden"
        );
    }
}


function hideWhatIfPanel() {

    const panel =
        document.getElementById(
            "whatIfPanel"
        );


    const results =
        document.getElementById(
            "whatIfResults"
        );


    if (panel) {

        panel.classList.add(
            "hidden"
        );
    }


    if (results) {

        results.classList.add(
            "hidden"
        );
    }
}


// ============================================================
// WHAT-IF MODE
// ============================================================

function setWhatIfMode(
    mode
) {

    state.whatIfMode =
        mode;


    document
        .querySelectorAll(
            ".tab-btn"
        )
        .forEach(
            (button) => {

                button.classList.toggle(
                    "active",
                    button.dataset.mode === mode
                );
            }
        );


    const altitudeControls =
        document.getElementById(
            "altitudeControls"
        );


    const deltaVControls =
        document.getElementById(
            "deltavControls"
        );


    if (altitudeControls) {

        altitudeControls.classList.toggle(
            "hidden",
            mode !== "altitude"
        );
    }


    if (deltaVControls) {

        deltaVControls.classList.toggle(
            "hidden",
            mode !== "deltav"
        );
    }
}


// ============================================================
// RUN WHAT-IF
// ============================================================

async function runWhatIf() {

    if (
        !state.primary ||
        !state.secondary
    ) {
        return;
    }


    const hours =
        Number(
            document.getElementById(
                "hoursInput"
            ).value
        );


    const maneuverOffset =
        Number(
            document.getElementById(
                "maneuverOffset"
            ).value
        );


    const payload = {

        primary_id:
            state.primary.norad_id,

        secondary_id:
            state.secondary.norad_id,

        hours:
            hours,

        maneuver_offset_minutes:
            maneuverOffset
    };


    // --------------------------------------------------------
    // Altitude mode
    // --------------------------------------------------------

    if (
        state.whatIfMode ===
        "altitude"
    ) {

        payload.altitude_change_km =
            Number(
                document.getElementById(
                    "altitudeSlider"
                ).value
            );

    } else {

        // ----------------------------------------------------
        // Delta-V RTN mode
        // ----------------------------------------------------

        payload.delta_v_rtn_m_s = [

            Number(
                document.getElementById(
                    "dvRadial"
                ).value
            ),

            Number(
                document.getElementById(
                    "dvInTrack"
                ).value
            ),

            Number(
                document.getElementById(
                    "dvCrossTrack"
                ).value
            )
        ];
    }


    const runButton =
        document.getElementById(
            "runWhatIfBtn"
        );


    if (runButton) {

        runButton.disabled =
            true;

        runButton.textContent =
            "Simulating…";
    }


    try {

        const result =
            await apiPost(
                "/api/whatif",
                payload
            );


        await loadCzmlIntoViewer(
            result.czml,
            true
        );


        renderWhatIfResults(
            result
        );

    } catch (error) {

        console.error(
            "What-if simulation failed:",
            error
        );


        alert(
            "What-if simulation failed: " +
            error.message
        );

    } finally {

        if (runButton) {

            runButton.disabled =
                false;

            runButton.textContent =
                "Run Simulation";
        }
    }
}


// ============================================================
// DELTA CLASS
// ============================================================

function deltaClass(
    delta,
    higherIsBetter = true
) {

    const value =
        Number(delta) || 0;


    if (
        Math.abs(value) <
        1e-9
    ) {
        return "";
    }


    const better =
        higherIsBetter
            ? value > 0
            : value < 0;


    return better
        ? "delta-better"
        : "delta-worse";
}


// ============================================================
// WHAT-IF RESULTS
// ============================================================

function renderWhatIfResults(
    result
) {

    const box =
        document.getElementById(
            "whatIfResults"
        );


    if (!box) return;


    const original =
        result.original || {};


    const modified =
        result.modified || {};


    const comparison =
        result.comparison || {};


    const originalConjunction =
        original.conjunction || {};


    const modifiedConjunction =
        modified.conjunction || {};


    const originalRisk =
        original.risk || {};


    const modifiedRisk =
        modified.risk || {};


    const originalConfidence =
        original.confidence || {};


    const modifiedConfidence =
        modified.confidence || {};


    const missDelta =
        Number(
            comparison
                .miss_distance_delta_km
        ) || 0;


    const riskDelta =
        Number(
            comparison
                .risk_score_delta
        ) || 0;


    const missClass =
        deltaClass(
            missDelta,
            true
        );


    const riskClass =
        deltaClass(
            riskDelta,
            false
        );


    const confidenceOriginal =
        originalConfidence
            .confidence_pct ??
        "—";


    const confidenceModified =
        modifiedConfidence
            .confidence_pct ??
        "—";


    box.innerHTML = `

        <table class="compare-table">

            <tr>

                <th></th>

                <th>
                    Original
                </th>

                <th>
                    Modified
                </th>

                <th>
                    Δ
                </th>

            </tr>


            <tr>

                <td>
                    Miss dist. (km)
                </td>

                <td>
                    ${
                        originalConjunction
                            .miss_distance_km ??
                        "—"
                    }
                </td>

                <td>
                    ${
                        modifiedConjunction
                            .miss_distance_km ??
                        "—"
                    }
                </td>

                <td class="${missClass}">

                    ${
                        missDelta >= 0
                            ? "+"
                            : ""
                    }

                    ${missDelta.toFixed(4)}

                </td>

            </tr>


            <tr>

                <td>
                    Risk score
                </td>

                <td>
                    ${
                        originalRisk
                            .risk_score ??
                        "—"
                    }
                </td>

                <td>
                    ${
                        modifiedRisk
                            .risk_score ??
                        "—"
                    }
                </td>

                <td class="${riskClass}">

                    ${
                        riskDelta >= 0
                            ? "+"
                            : ""
                    }

                    ${riskDelta.toFixed(4)}

                </td>

            </tr>


            <tr>

                <td>
                    Confidence
                </td>

                <td>
                    ${confidenceOriginal}%
                </td>

                <td>
                    ${confidenceModified}%
                </td>

                <td>

                    ${
                        Number(
                            confidenceModified
                        ) -
                        Number(
                            confidenceOriginal
                        ) >= 0
                            ? "+"
                            : ""
                    }

                    ${
                        (
                            Number(
                                confidenceModified
                            ) -
                            Number(
                                confidenceOriginal
                            )
                        ).toFixed(2)
                    }

                </td>

            </tr>

        </table>


        <div class="legend-row">

            <span
                class="legend-swatch"
                style="background:#80ff8c">
            </span>

            Modified (what-if) trajectory
            — dashed on globe

        </div>


        <div class="whatif-note">

            Maneuver:

            ${
                result.maneuver &&
                result.maneuver.type ===
                "altitude_change"

                ?

                `altitude change of
                ${
                    result.maneuver
                        .requested_altitude_change_km
                }
                km
                (ΔV ≈
                ${
                    result.maneuver
                        .implied_delta_v_m_s
                }
                m/s)`

                :

                `ΔV of
                ${
                    result.maneuver
                        ?.delta_v_magnitude_m_s ??
                    "—"
                }
                m/s (RTN)`
            }


            at T+
            ${maneuverOffset}
            min.


            ${
                modifiedConjunction.note ||
                ""
            }

        </div>
    `;


    box.classList.remove(
        "hidden"
    );
}


// ============================================================
// UTC CLOCK
// ============================================================

function tickClock() {

    const element =
        document.getElementById(
            "utcClock"
        );


    if (!element) return;


    const now =
        new Date();


    element.textContent =
        now
            .toISOString()
            .slice(11, 19);
}


// ============================================================
// UI EVENT HANDLERS
// ============================================================

function wireUi() {

    // --------------------------------------------------------
    // Search
    // --------------------------------------------------------

    const searchButton =
        document.getElementById(
            "searchBtn"
        );


    if (searchButton) {

        searchButton.addEventListener(
            "click",
            doSearch
        );
    }


    const searchInput =
        document.getElementById(
            "searchInput"
        );


    if (searchInput) {

        searchInput.addEventListener(
            "keydown",
            (event) => {

                if (
                    event.key ===
                    "Enter"
                ) {

                    doSearch();
                }
            }
        );
    }


    // --------------------------------------------------------
    // Pair
    // --------------------------------------------------------

    const clearButton =
        document.getElementById(
            "clearPairBtn"
        );


    if (clearButton) {

        clearButton.addEventListener(
            "click",
            clearPair
        );
    }


    const analyzeButton =
        document.getElementById(
            "analyzeBtn"
        );


    if (analyzeButton) {

        analyzeButton.addEventListener(
            "click",
            analyzeConjunction
        );
    }


    // --------------------------------------------------------
    // Reset globe
    // --------------------------------------------------------

    const resetButton =
        document.getElementById(
            "resetViewBtn"
        );


    if (resetButton) {

        resetButton.addEventListener(
            "click",
            loadDefaultCatalogView
        );
    }


    // --------------------------------------------------------
    // Detail drawer close
    // --------------------------------------------------------

    const detailClose =
        document.getElementById(
            "detailCloseBtn"
        );


    if (detailClose) {

        detailClose.addEventListener(
            "click",
            () => {

                document
                    .getElementById(
                        "detailDrawer"
                    )
                    ?.classList.add(
                        "hidden"
                    );
            }
        );
    }


    // --------------------------------------------------------
    // What-if close
    // --------------------------------------------------------

    const whatIfClose =
        document.getElementById(
            "whatIfCloseBtn"
        );


    if (whatIfClose) {

        whatIfClose.addEventListener(
            "click",
            hideWhatIfPanel
        );
    }


    // --------------------------------------------------------
    // Run what-if
    // --------------------------------------------------------

    const runWhatIfButton =
        document.getElementById(
            "runWhatIfBtn"
        );


    if (runWhatIfButton) {

        runWhatIfButton.addEventListener(
            "click",
            runWhatIf
        );
    }


    // --------------------------------------------------------
    // What-if tabs
    // --------------------------------------------------------

    document
        .querySelectorAll(
            ".tab-btn"
        )
        .forEach(
            (button) => {

                button.addEventListener(
                    "click",
                    () => {

                        setWhatIfMode(
                            button.dataset.mode
                        );
                    }
                );
            }
        );


    // --------------------------------------------------------
    // Altitude slider
    // --------------------------------------------------------

    const altitudeSlider =
        document.getElementById(
            "altitudeSlider"
        );


    if (altitudeSlider) {

        altitudeSlider.addEventListener(
            "input",
            () => {

                const value =
                    Number(
                        altitudeSlider.value
                    );


                const output =
                    document.getElementById(
                        "altitudeValue"
                    );


                if (output) {

                    output.textContent =
                        (
                            value >= 0
                                ? "+"
                                : ""
                        )
                        +
                        value.toFixed(1);
                }
            }
        );
    }


    // --------------------------------------------------------
    // Maneuver time slider
    // --------------------------------------------------------

    const maneuverSlider =
        document.getElementById(
            "maneuverOffset"
        );


    if (maneuverSlider) {

        maneuverSlider.addEventListener(
            "input",
            () => {

                const output =
                    document.getElementById(
                        "maneuverOffsetValue"
                    );


                if (output) {

                    output.textContent =
                        maneuverSlider.value;
                }
            }
        );
    }


    // --------------------------------------------------------
    // UTC clock
    // --------------------------------------------------------

    setInterval(
        tickClock,
        1000
    );

    tickClock();
}


// ============================================================
// BOOT
// ============================================================

async function boot() {

    wireUi();

    initViewer();


    try {

        await loadDefaultCatalogView();

        setBackendStatus(
            "ok",
            "online"
        );


        // Load complete sample catalog

        const all =
            await apiGet(
                "/api/search?q="
            );


        renderSearchResults(
            all.results || []
        );


    } catch (error) {

        console.error(
            "Boot failed:",
            error
        );


        setBackendStatus(
            "error",
            "offline"
        );

    } finally {

        document
            .getElementById(
                "loadingOverlay"
            )
            ?.classList.add(
                "hidden"
            );
    }
}


// ============================================================
// START APPLICATION
// ============================================================

boot();