"use strict";

let configuration;
const activePanels = new Map();

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

function isOn(value) {
  return value === "1" || value === "Yes" || value === "Active";
}

function renderStatus(panel, values) {
  panel.querySelector(".position").textContent = values[".RBV"];
  panel.querySelector(".unit").textContent = values[".EGU"];

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

  const lowHardware = isOn(values[".LLS"]) ? "ON" : "OFF";
  const highHardware = isOn(values[".HLS"]) ? "ON" : "OFF";
  panel.querySelector(".hard-limits").textContent = `− ${lowHardware} / + ${highHardware}`;
  panel.querySelector(".soft-limits").textContent =
    `${values[".LLM"]} ~ ${values[".HLM"]} ${values[".EGU"]}`;
  panel.querySelector(".velocity").textContent =
    `${values[".VELO"]} / max ${values[".VMAX"]} ${values[".EGU"]}/s`;
  panel.querySelector(".conversion").textContent =
    `${values[".DIR"]} / ${values[".MRES"]} ${values[".EGU"]}/pulse`;
  panel.querySelector(".origin-method").textContent =
    `Method ${values[":OriginMethodSelectedRBV"]}`;
  const connection = panel.querySelector(".connection-state");
  connection.textContent = "CA 연결됨";
  connection.className = "connection-state normal";
}

async function refreshPanel(axis) {
  const panel = activePanels.get(axis);
  if (!panel) return;
  try {
    const status = await request(`/api/panels/${axis}/status`);
    if (activePanels.get(axis) === panel) renderStatus(panel, status.values);
  } catch (error) {
    if (activePanels.get(axis) !== panel) return;
    const connection = panel.querySelector(".connection-state");
    connection.textContent = `연결 오류: ${error.message}`;
    connection.className = "connection-state error";
  }
}

function addPanel(result) {
  const existing = activePanels.get(result.axis);
  if (existing) existing.remove();

  const panel = document.getElementById("panel-template").content.firstElementChild.cloneNode(true);
  panel.querySelector("h2").textContent = `축 ${result.axis}`;
  panel.querySelector(".record").textContent = result.record;
  panel.querySelector(".model-name").textContent = result.model;
  panel.querySelector(".remove").onclick = async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await request(`/api/panels/${result.axis}`, {
        method: "DELETE",
        headers: {"X-Kohzu-Token": configuration.token}
      });
      activePanels.delete(result.axis);
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
  refreshPanel(result.axis);
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
  for (const panel of configuration.panels) addPanel(panel);
  document.getElementById("connection").textContent =
    `localhost · PV prefix ${configuration.prefix} · 활성 패널 ${configuration.panels.length}개`;
  window.setInterval(() => {
    for (const axis of activePanels.keys()) refreshPanel(axis);
  }, 1000);
}

start().catch(error => {
  const connection = document.getElementById("connection");
  connection.textContent = `시작 실패: ${error.message}`;
  connection.className = "error";
});
