"use strict";

let configuration;
const activePanels = new Map();
const activeJogs = new Map();
const statusCache = new Map();
const pendingCommands = new Map();
let socket;
let nextCommandId = 1;
const VIEW_KEY = "kohzu-panel-view";
const VALID_VIEWS = new Set(["compact", "basic", "detail"]);

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || value.detail || `HTTP ${response.status}`);
  return value;
}

function command(type, axis, values = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN)
    return Promise.reject(new Error("제어 WebSocket이 연결되지 않았습니다."));
  const id = nextCommandId++;
  return new Promise((resolve, reject) => {
    pendingCommands.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, type, axis, ...values}));
  });
}

function isOn(value) {
  return value === "1" || value === "Yes" || value === "Active";
}

function renderFastStatus(panel, values) {
  panel.querySelector(".position").textContent = values[".RBV"];
  panel.querySelector(".unit").textContent = values[".EGU"];
  panel.querySelector(".compact-position").textContent = values[".RBV"];
  panel.querySelector(".compact-unit").textContent = values[".EGU"];
  const enabled = values["_able"] === "Enable" || values["_able"] === "0";
  const moving = isOn(values[".MOVN"]);
  const limited = isOn(values[".HLS"]) || isOn(values[".LLS"]);
  const violated = isOn(values[".LVIO"]);
  const compactState = panel.querySelector(".compact-state");
  compactState.textContent = "●";
  compactState.title = [enabled ? "Enabled" : "Disabled", moving ? "Moving" : "Stopped"].join(" · ");
  compactState.className = `compact-state ${limited || violated ? "alarm" : (moving ? "moving" : (enabled ? "normal" : "warning"))}`;
}

function syncFieldInputs(panel, values) {
  for (const input of panel.querySelectorAll("[data-field]")) {
    const value = values[input.dataset.field];
    if (value === undefined || input.dataset.dirty === "true" || document.activeElement === input) continue;
    input.value = value;
    input.dataset.lastValue = value;
  }
}

function renderStatus(panel, values) {
  renderFastStatus(panel, values);
  panel.querySelector(".position").textContent = values[".RBV"];
  panel.querySelector(".unit").textContent = values[".EGU"];
  panel.querySelector(".compact-position").textContent = values[".RBV"];
  panel.querySelector(".compact-unit").textContent = values[".EGU"];

  const enabled = values["_able"] === "Enable" || values["_able"] === "0";
  const moving = isOn(values[".MOVN"]);
  const done = isOn(values[".DMOV"]);
  const limited = isOn(values[".HLS"]) || isOn(values[".LLS"]);
  const violated = isOn(values[".LVIO"]);
  const state = panel.querySelector(".state");
  const labels = [enabled ? "Enabled" : "Disabled"];
  labels.push(moving ? "Moving" : (done ? "Stopped" : "Not done"));
  if (limited) labels.push("Hardware limit");
  if (violated) labels.push("Soft-limit violation");
  state.textContent = labels.join(" · ");
  state.className = `state ${limited || violated ? "alarm" : (enabled ? "normal" : "warning")}`;
  panel.querySelector(".compact-state").title = labels.join(" · ");

  const lowHardware = isOn(values[".LLS"]) ? "ON" : "OFF";
  const highHardware = isOn(values[".HLS"]) ? "ON" : "OFF";
  panel.querySelector(".hard-limits").textContent = `− ${lowHardware} / + ${highHardware}`;
  panel.querySelector(".soft-limits").textContent =
    `${values[".LLM"]} ~ ${values[".HLM"]} ${values[".EGU"]}`;
  panel.querySelector(".velocity").textContent =
    `move ${values[".VELO"]} / jog ${values[".JVEL"]} / max ${values[".VMAX"]} ${values[".EGU"]}/s`;
  panel.querySelector(".target").textContent =
    `${values[".VAL"]} ${values[".EGU"]}`;
  panel.querySelector(".dial").textContent =
    `DVAL ${values[".DVAL"]} / DRBV ${values[".DRBV"]}`;
  panel.querySelector(".raw").textContent =
    `RVAL ${values[".RVAL"]} / RRBV ${values[".RRBV"]}`;
  panel.querySelector(".conversion").textContent =
    `${values[".DIR"]} / ${values[".MRES"]} ${values[".EGU"]}/pulse`;
  panel.querySelector(".offset").textContent =
    `${values[".OFF"]} / ${values[".FOFF"]}`;
  panel.querySelector(".motion-config").textContent =
    `VBAS ${values[".VBAS"]} / JAR ${values[".JAR"]} / ACCL ${values[".ACCL"]} s`;
  panel.querySelector(".msta").textContent = values[".MSTA"];
  panel.querySelector(".set-mode").textContent = values[".SET"];
  panel.querySelector(".spmg-mode").textContent = values[".SPMG"];
  panel.querySelector(".origin-method").textContent =
    `Method ${values[":OriginMethodSelectedRBV"]}`;
  panel.querySelector(".home-method-state").textContent =
    `선택값 ${values[":OriginMethodSelectedRBV"]} / Controller ${values[":OriginMethodRBV"]}`;
  const homeMethod = panel.querySelector(".home-method");
  const selectedMethod = Number(values[":OriginMethodSelectedRBV"]);
  if (Number.isInteger(selectedMethod) && selectedMethod >= 1 && selectedMethod <= 15 &&
      homeMethod.dataset.dirty !== "true" && document.activeElement !== homeMethod) {
    homeMethod.value = String(selectedMethod);
  }
  syncFieldInputs(panel, values);
  const connection = panel.querySelector(".connection-state");
  connection.textContent = "CA 연결됨";
  connection.className = "connection-state normal";
}

async function stopAxis(axis, panel) {
  const buttons = panel.querySelectorAll(".stop");
  for (const button of buttons) button.disabled = true;
  try {
    await command("stop", axis);
    const connection = panel.querySelector(".connection-state");
    connection.textContent = "STOP 요청 완료";
    connection.className = "connection-state normal";
    activeJogs.delete(axis);
    for (const button of panel.querySelectorAll(".jog")) button.disabled = false;
  } catch (error) {
    const connection = panel.querySelector(".connection-state");
    connection.textContent = `STOP 실패: ${error.message}`;
    connection.className = "connection-state error";
  } finally {
    for (const button of buttons) button.disabled = false;
  }
}

function jogMessage(panel, text, className) {
  const connection = panel.querySelector(".connection-state");
  connection.textContent = text;
  connection.className = `connection-state ${className}`;
}

function startJog(axis, panel, direction) {
  if (activeJogs.has(axis)) return;
  const state = {released: false, stopSent: false};
  activeJogs.set(axis, state);
  for (const button of panel.querySelectorAll(".jog")) button.disabled = true;
  jogMessage(panel, `${direction.toUpperCase()} JOG 시작 중…`, "working");
  state.started = command("jog_start", axis, {direction}).then(() => {
    jogMessage(panel, `${direction.toUpperCase()} JOG 중 — 놓으면 정지`, "moving");
    if (state.released) window.queueMicrotask(() => releaseJog(axis, panel));
  }).catch(error => {
    jogMessage(panel, `JOG 시작 실패: ${error.message}`, "error");
    throw error;
  });
}

async function releaseJog(axis, panel) {
  const state = activeJogs.get(axis);
  if (!state || state.stopSent) return;
  state.released = true;
  state.stopSent = true;
  // Do not await the start acknowledgement.  Both messages share one ordered
  // WebSocket, so a short tap sends STOP immediately behind START.
  try {
    await command("jog_stop", axis);
    jogMessage(panel, "JOG 정지 완료", "normal");
  } catch (error) {
    jogMessage(panel, `JOG 정지 실패: ${error.message}`, "error");
  } finally {
    activeJogs.delete(axis);
    for (const button of panel.querySelectorAll(".jog")) button.disabled = false;
  }
}

function connectSocket() {
  return new Promise((resolve, reject) => {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}/ws?token=${encodeURIComponent(configuration.token)}`);
    socket.onopen = resolve;
    socket.onerror = () => reject(new Error("제어 WebSocket 연결 실패"));
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.type === "command_result" || message.type === "command_error") {
        const pending = pendingCommands.get(message.id);
        if (!pending) return;
        pendingCommands.delete(message.id);
        if (message.type === "command_result") pending.resolve(message.result);
        else pending.reject(new Error(message.error));
        return;
      }
      if (message.type === "hello") {
        for (const [axis, values] of Object.entries(message.snapshots || {})) {
          statusCache.set(Number(axis), values);
          const panel = activePanels.get(Number(axis));
          if (panel) renderStatus(panel, values);
        }
      } else if (message.type === "axis_update") {
        const current = statusCache.get(message.axis) || {};
        const values = {...current, ...message.values};
        statusCache.set(message.axis, values);
        const panel = activePanels.get(message.axis);
        if (panel) renderStatus(panel, values);
      } else if (message.type === "panel_ready") {
        addPanel(message.panel);
      } else if (message.type === "panel_removed") {
        const removed = activePanels.get(message.axis);
        if (removed) removed.remove();
        activePanels.delete(message.axis);
        statusCache.delete(message.axis);
      }
    };
    socket.onclose = () => {
      for (const pending of pendingCommands.values())
        pending.reject(new Error("제어 WebSocket 연결이 종료되었습니다."));
      pendingCommands.clear();
      activeJogs.clear();
      document.getElementById("connection").textContent = "제어 WebSocket 연결 끊김";
      document.getElementById("connection").className = "error";
    };
  });
}

function bindJogButton(button, axis, panel) {
  button.addEventListener("pointerdown", event => {
    event.preventDefault();
    button.setPointerCapture(event.pointerId);
    startJog(axis, panel, button.dataset.direction);
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    button.addEventListener(name, () => releaseJog(axis, panel));
  }
}

async function moveAxis(axis, panel, mode, value) {
  if (!Number.isFinite(value)) {
    const message = panel.querySelector(".motion-message");
    message.className = "motion-message error";
    message.textContent = "유한한 이동값을 입력하세요.";
    return;
  }
  const buttons = panel.querySelectorAll(".move-absolute, .compact-move-absolute, .move-negative, .move-positive");
  for (const button of buttons) button.disabled = true;
  const message = panel.querySelector(".motion-message");
  message.className = "motion-message working";
  message.textContent = `${mode === "absolute" ? "절대" : "상대"} 이동 중…`;
  try {
    const result = await command("move", axis, {mode, value});
    const adjusted = Math.abs(result.requested - result.target) > 1e-12;
    message.className = "motion-message success";
    message.textContent = adjusted
      ? `완료: 입력 목표 ${result.requested} → 실행 목표 ${result.target}, 최종 ${result.final} ${result.egu}`
      : `완료: ${result.final} ${result.egu}`;
  } catch (error) {
    message.className = "motion-message error";
    message.textContent = `이동 실패: ${error.message}`;
  } finally {
    for (const button of buttons) button.disabled = false;
  }
}

async function setHomeMethod(axis, panel) {
  const method = Number(panel.querySelector(".home-method").value);
  const message = panel.querySelector(".home-message");
  try {
    const result = await command("set_home_method", axis, {method});
    panel.querySelector(".home-method").dataset.dirty = "false";
    message.className = "home-message success";
    message.textContent = `Method ${result.home_method} 저장 완료`;
  } catch (error) {
    message.className = "home-message error";
    message.textContent = `Method 저장 실패: ${error.message}`;
  }
}

async function homeAxis(axis, panel) {
  const method = Number(panel.querySelector(".home-method").value);
  if (!window.confirm(`축 ${axis}을 Method ${method}로 HOME 실행할까요?`)) return;
  const button = panel.querySelector(".home");
  const message = panel.querySelector(".home-message");
  button.disabled = true;
  message.className = "home-message working";
  message.textContent = `Method ${method} 적용 후 HOME 진행 중… STOP으로 중단할 수 있습니다.`;
  try {
    await command("set_home_method", axis, {method});
    panel.querySelector(".home-method").dataset.dirty = "false";
    const result = await command("home", axis);
    message.className = "home-message success";
    message.textContent = `HOME 완료: ${result.final} ${result.egu}`;
  } catch (error) {
    message.className = "home-message error";
    message.textContent = `HOME 실패 또는 중단: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function markField(input, state) {
  input.classList.remove("field-dirty", "field-applying", "field-applied", "field-error");
  if (state) input.classList.add(`field-${state}`);
}

async function writeFields(axis, panel, fields) {
  const message = panel.querySelector(".field-message");
  if (!fields.length) {
    message.className = "field-message warning";
    message.textContent = "변경된 값이 없습니다.";
    return;
  }
  for (const button of panel.querySelectorAll(".field-controls button")) button.disabled = true;
  try {
    for (const input of fields) {
      markField(input, "applying");
      const value = input.tagName === "SELECT" ? input.value : Number(input.value);
      if (input.tagName !== "SELECT" && !Number.isFinite(value))
        throw new Error(`${input.dataset.field}: 유한한 값을 입력하세요.`);
      const result = await command("field_write", axis, {field: input.dataset.field, value});
      input.value = result.requested;
      input.dataset.lastValue = String(result.requested);
      input.dataset.dirty = "false";
      markField(input, "applied");
    }
    message.className = "field-message success";
    message.textContent = `${fields.length}개 필드 쓰기 완료 (monitor readback 대기)`;
  } catch (error) {
    const applying = fields.find(input => input.classList.contains("field-applying"));
    if (applying) markField(applying, "error");
    message.className = "field-message error";
    message.textContent = `필드 적용 실패: ${error.message}`;
  } finally {
    for (const button of panel.querySelectorAll(".field-controls button")) button.disabled = false;
  }
}

function writeChangedFields(axis, panel, section) {
  const fields = [...section.querySelectorAll("[data-field]")].filter(
    input => input.dataset.dirty === "true" || input.value !== input.dataset.lastValue
  );
  return writeFields(axis, panel, fields);
}

function numericInput(panel, selector) {
  const text = panel.querySelector(selector).value.trim();
  return text === "" ? Number.NaN : Number(text);
}

function addPanel(result) {
  const existing = activePanels.get(result.axis);
  if (existing) existing.remove();

  const panel = document.getElementById("panel-template").content.firstElementChild.cloneNode(true);
  panel.querySelector(".home-controls").hidden = document.body.dataset.view === "compact";
  panel.querySelector("h2").textContent = `축 ${result.axis}`;
  panel.querySelector(".compact-axis").textContent = `축 ${result.axis}`;
  panel.querySelector(".record").textContent = result.record;
  panel.querySelector(".model-name").textContent = result.model;
  const homeMethod = panel.querySelector(".home-method");
  homeMethod.value = String(result.home_method || 4);
  homeMethod.dataset.dirty = "false";
  homeMethod.addEventListener("change", () => {
    homeMethod.dataset.dirty = "true";
  });
  panel.querySelector(".set-home-method").onclick = () =>
    setHomeMethod(result.axis, panel);
  panel.querySelector(".home").onclick = () => homeAxis(result.axis, panel);
  for (const button of panel.querySelectorAll(".stop"))
    button.onclick = () => stopAxis(result.axis, panel);
  for (const button of panel.querySelectorAll(".jog"))
    bindJogButton(button, result.axis, panel);
  panel.querySelector(".move-absolute").onclick = () => moveAxis(
    result.axis, panel, "absolute",
    numericInput(panel, ".absolute-value")
  );
  panel.querySelector(".compact-move-absolute").onclick = () => moveAxis(
    result.axis, panel, "absolute",
    numericInput(panel, ".compact-absolute-value")
  );
  panel.querySelector(".move-negative").onclick = () => moveAxis(
    result.axis, panel, "relative",
    -Math.abs(numericInput(panel, ".relative-value"))
  );
  panel.querySelector(".move-positive").onclick = () => moveAxis(
    result.axis, panel, "relative",
    Math.abs(numericInput(panel, ".relative-value"))
  );
  for (const input of panel.querySelectorAll("[data-field]")) {
    const dirty = () => {
      input.dataset.dirty = "true";
      markField(input, "dirty");
    };
    input.addEventListener("input", dirty);
    input.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      dirty();
      writeFields(result.axis, panel, [input]);
    });
    input.addEventListener("change", () => {
      dirty();
      if (input.tagName === "SELECT") writeFields(result.axis, panel, [input]);
    });
  }
  panel.querySelector(".apply-basic-fields").onclick = event =>
    writeChangedFields(result.axis, panel, event.currentTarget.closest("section"));
  panel.querySelector(".apply-detail-fields").onclick = event =>
    writeChangedFields(result.axis, panel, event.currentTarget.closest("section"));
  panel.querySelector(".apply-coordinate-fields").onclick = event =>
    writeChangedFields(result.axis, panel, event.currentTarget.closest("section"));
  panel.querySelector(".remove").onclick = async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await request(`/api/panels/${result.axis}`, {
        method: "DELETE",
        headers: {"X-Kohzu-Token": configuration.token}
      });
      activePanels.delete(result.axis);
      activeJogs.delete(result.axis);
      panel.remove();
      const message = document.getElementById("create-result");
      message.className = "success";
      message.textContent = `축 ${result.axis} 패널 삭제 및 Disable 완료`;
    } catch (error) {
      button.disabled = false;
      const state = panel.querySelector(".state");
      state.className = "state error";
      state.textContent = `삭제 실패: ${error.message}`;
    }
  };
  activePanels.set(result.axis, panel);
  document.getElementById("panels").append(panel);
  const values = statusCache.get(result.axis);
  if (values) renderStatus(panel, values);
}

function setView(view) {
  if (!VALID_VIEWS.has(view)) view = "basic";
  document.body.dataset.view = view;
  for (const controls of document.querySelectorAll(".home-controls"))
    controls.hidden = view === "compact";
  window.localStorage.setItem(VIEW_KEY, view);
  for (const button of document.querySelectorAll("[data-view]")) {
    const selected = button.dataset.view === view;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  }
}

async function createPanel() {
  const axis = Number(document.getElementById("axis").value);
  const model = document.getElementById("model").value;
  const button = document.getElementById("create");
  const message = document.getElementById("create-result");
  button.disabled = true;
  message.className = "working";
  message.textContent = `축 ${axis}에 ${model} 적용 중…`;
  try {
    const result = await request("/api/panels", {
      method: "POST",
      headers: {
        "X-Kohzu-Token": configuration.token,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({axis, model})
    });
    addPanel(result);
    message.className = "success";
    message.textContent = `축 ${axis}: ${model} 적용 완료`;
  } catch (error) {
    message.className = "error";
    message.textContent = `생성 실패: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function start() {
  configuration = await request("/api/config");
  const axisSelect = document.getElementById("axis");
  for (const axis of configuration.axes) {
    const option = document.createElement("option");
    option.value = axis;
    option.textContent = `축 ${axis}`;
    axisSelect.append(option);
  }
  const modelSelect = document.getElementById("model");
  for (const model of configuration.models) {
    const option = document.createElement("option");
    option.value = model.name;
    option.textContent = `${model.name} — ${model.description}`;
    modelSelect.append(option);
  }
  document.getElementById("create").onclick = createPanel;
  for (const button of document.querySelectorAll("[data-view]"))
    button.onclick = () => setView(button.dataset.view);
  setView(window.localStorage.getItem(VIEW_KEY) || "basic");
  for (const panel of configuration.panels) addPanel(panel);
  await connectSocket();
  document.getElementById("connection").textContent =
    `PV prefix ${configuration.prefix} · WebSocket/EPICS monitor 연결됨 · UI ${configuration.ui_version}`;
  window.addEventListener("blur", () => {
    for (const [axis] of activeJogs) {
      const panel = activePanels.get(axis);
      if (panel) releaseJog(axis, panel);
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) return;
    for (const [axis] of activeJogs) {
      const panel = activePanels.get(axis);
      if (panel) releaseJog(axis, panel);
    }
  });
}

start().catch(error => {
  const connection = document.getElementById("connection");
  connection.textContent = `시작 실패: ${error.message}`;
  connection.className = "error";
});
