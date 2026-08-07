"use strict";

let configuration;
const activePanels = new Map();
const shownFields = [
  [".RBV", "현재 위치"], [".VAL", "목표 위치"], [".EGU", "단위"],
  [".DMOV", "DMOV"], [".MOVN", "MOVN"], [".HLS", "CW/HLS"],
  [".LLS", "CCW/LLS"], [":OriginMethodSelectedRBV", "원점 방법"],
  [":Commissioning:ConfigApplied", "모델 설정"],
  [":Commissioning:DirectionVerified", "방향 확인"],
  [":Commissioning:SensorsVerified", "센서 확인"],
  [":Commissioning:LimitsVerified", "리미트 확인"],
  [":Commissioning:HomeEstablished", "원점 확인"],
  [":Commissioning:Ready", "Enable 준비"],
  [":HomeStatus", "HOME 상태"], [":MoveStatus", "이동 상태"]
];
const diagnosticFields = [
  ["Diag:LastErrorCode", "마지막 오류 번호"],
  ["Diag:LastErrorText", "오류 설명"],
  ["Diag:LastErrorCommand", "오류 명령"],
  ["Diag:LastErrorRaw", "오류 원문"],
  ["Diag:LastWarningCode", "마지막 경고 번호"],
  ["Diag:LastWarningText", "경고 설명"],
  ["Diag:LastWarningCommand", "경고 명령"],
  ["Diag:LastWarningRaw", "경고 원문"],
  ["Recovery:Status", "복구 상태"]
];

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

async function refreshPanel(axis) {
  const panel = activePanels.get(axis);
  if (!panel) return;
  try {
    const status = await request(`/api/axis/${axis}/status`);
    for (const [suffix] of shownFields)
      panel.querySelector(`[data-field="${suffix}"]`).textContent = status.values[suffix];
    const methods = Array.from({length: 15}, (_, index) => String(index + 1));
    const methodSelect = panel.querySelector(".origin-method");
    const signature = methods.join(",");
    if (methodSelect.dataset.methods !== signature) {
      methodSelect.replaceChildren(...methods.map(method => {
        const option = document.createElement("option"); option.value = method;
        option.textContent = `Method ${method}`; return option;
      }));
      methodSelect.dataset.methods = signature;
      methodSelect.value = status.values[":OriginMethodSelectedRBV"];
    }
    panel.querySelector(".home").disabled = status.values[":Commissioning:Ready"] !== "1";
    const confirmationFields = {
      direction: ":Commissioning:DirectionVerified",
      sensors: ":Commissioning:SensorsVerified",
      limits: ":Commissioning:LimitsVerified",
      home: ":Commissioning:HomeEstablished"
    };
    for (const button of panel.querySelectorAll("[data-confirm]")) {
      const verified = status.values[confirmationFields[button.dataset.confirm]] === "Verified";
      const requested = button.dataset.value === "true";
      button.disabled = requested === verified;
    }
    panel.querySelector(".result").textContent = "CA 연결됨";
  } catch (error) {
    panel.querySelector(".result").textContent = `연결 오류: ${error.message}`;
  }
}

async function guardedAction(axis, action, panel) {
  try {
    await request(`/api/axis/${axis}/${action}`, {
      method: "POST", headers: {"X-Kohzu-Token": configuration.token}
    });
    panel.querySelector(".result").textContent = `${action} 요청 전송됨`;
    setTimeout(() => refreshPanel(axis), 150);
  } catch (error) {
    panel.querySelector(".result").textContent = `요청 실패: ${error.message}`;
  }
}

async function applyOriginMethod(axis, panel) {
  const method = Number(panel.querySelector(".origin-method").value);
  if (!window.confirm(`축 ${axis}를 Disable하고 기존 원점 확인을 무효화한 뒤 Method ${method}를 선택합니까?`)) return;
  try {
    await request(`/api/axis/${axis}/origin-method`, {
      method: "POST",
      headers: {"X-Kohzu-Token": configuration.token, "Content-Type": "application/json"},
      body: JSON.stringify({method})
    });
    panel.querySelector(".result").textContent = `Method ${method} 선택 요청 완료; 재HOME 필요`;
    setTimeout(() => refreshPanel(axis), 150);
  } catch (error) {
    panel.querySelector(".result").textContent = `원점 방법 선택 실패: ${error.message}`;
  }
}

async function requestHome(axis, panel) {
  if (!window.confirm(`축 ${axis}에 선택한 Method로 HOME을 실행합니까? 센서 구성에 맞는 Method 선택은 사용자의 책임입니다.`)) return;
  try {
    await request(`/api/axis/${axis}/home`, {
      method: "POST", headers: {"X-Kohzu-Token": configuration.token}
    });
    panel.querySelector(".result").textContent = "HOME 요청 전송됨; HomeStatus 확인 필요";
    setTimeout(() => refreshPanel(axis), 200);
  } catch (error) {
    panel.querySelector(".result").textContent = `HOME 차단/실패: ${error.message}`;
  }
}

async function setConfirmation(axis, name, verified, panel) {
  const labels = {direction: "방향", sensors: "센서", limits: "리미트", home: "원점"};
  const detail = verified
    ? `축 ${axis}의 ${labels[name]} 상태를 실제 장비에서 확인했습니까? 이 기록은 물리적 검사를 대신하지 않습니다.`
    : `축 ${axis}의 ${labels[name]} 확인을 취소하고 축을 Disable합니까?`;
  if (!window.confirm(detail)) return;
  try {
    await request(`/api/axis/${axis}/confirmation`, {
      method: "POST",
      headers: {"X-Kohzu-Token": configuration.token, "Content-Type": "application/json"},
      body: JSON.stringify({name, verified})
    });
    panel.querySelector(".result").textContent = `${labels[name]} 확인 ${verified ? "승인" : "취소"} 완료`;
    setTimeout(() => refreshPanel(axis), 150);
  } catch (error) {
    panel.querySelector(".result").textContent = `확인 기록 실패: ${error.message}`;
  }
}

async function refreshDiagnostics() {
  try {
    const status = await request("/api/diagnostics");
    for (const [suffix] of diagnosticFields)
      document.querySelector(`[data-diagnostic="${suffix}"]`).textContent = status.values[suffix];
    const active = status.values["Recovery:EmergencyActive"];
    const emergency = document.getElementById("emergency");
    emergency.textContent = `EMG: ${active}`;
    emergency.className = active === "Active" ? "alarm" : "normal";
  } catch (error) {
    document.getElementById("recovery-result").textContent = `진단 연결 오류: ${error.message}`;
  }
}

async function recoveryAction(action) {
  const message = action === "release-emg"
    ? "물리적 긴급정지 원인을 해결했고 모든 EMG 입력이 해제됐는지 확인했습니까?"
    : "Motionnet 축 구성을 다시 읽으면 축 map을 검토하고 다시 HOME 해야 합니다. 계속합니까?";
  if (!window.confirm(message)) return;
  try {
    await request(`/api/recovery/${action}`, {
      method: "POST", headers: {"X-Kohzu-Token": configuration.token}
    });
    document.getElementById("recovery-result").textContent = `${action} 요청 전송됨`;
    setTimeout(refreshDiagnostics, 200);
  } catch (error) {
    document.getElementById("recovery-result").textContent = `복구 요청 실패: ${error.message}`;
  }
}

function createPanel() {
  const axis = Number(document.getElementById("axis").value);
  const model = document.getElementById("model").value;
  if (activePanels.has(axis)) {
    activePanels.get(axis).scrollIntoView({behavior: "smooth"});
    return;
  }
  const assigned = configuration.axes.find(item => item.axis === axis).assigned_model;
  const panel = document.getElementById("panel-template").content.firstElementChild.cloneNode(true);
  panel.querySelector("h2").textContent = `축 ${axis} — ${model}`;
  panel.querySelector(".model-warning").textContent = assigned === model
    ? `IOC assignment와 일치: ${assigned}`
    : `표시 선택 ${model}, 설정 assignment ${assigned || "없음"} — 모델 설정은 변경되지 않음`;
  const values = panel.querySelector(".values");
  for (const [suffix, label] of shownFields) {
    const term = document.createElement("dt"); term.textContent = label;
    const data = document.createElement("dd"); data.dataset.field = suffix; data.textContent = "—";
    values.append(term, data);
  }
  panel.querySelector(".remove").onclick = () => { activePanels.delete(axis); panel.remove(); };
  panel.querySelector(".enable").onclick = () => guardedAction(axis, "enable", panel);
  panel.querySelector(".disable").onclick = () => guardedAction(axis, "disable", panel);
  panel.querySelector(".apply-origin").onclick = () => applyOriginMethod(axis, panel);
  panel.querySelector(".home").onclick = () => requestHome(axis, panel);
  for (const button of panel.querySelectorAll("[data-confirm]"))
    button.onclick = () => setConfirmation(
      axis, button.dataset.confirm, button.dataset.value === "true", panel);
  activePanels.set(axis, panel);
  document.getElementById("panels").append(panel);
  refreshPanel(axis);
}

async function start() {
  configuration = await request("/api/config");
  const axisSelect = document.getElementById("axis");
  for (const item of configuration.axes) {
    const option = document.createElement("option"); option.value = item.axis;
    option.textContent = `${item.axis}${item.assigned_model ? ` (${item.assigned_model})` : ""}`;
    axisSelect.append(option);
  }
  const modelSelect = document.getElementById("model");
  for (const model of configuration.models) {
    const option = document.createElement("option"); option.value = model.name;
    option.textContent = `${model.name} — ${model.description}`; modelSelect.append(option);
  }
  axisSelect.onchange = () => {
    const assigned = configuration.axes.find(item => item.axis === Number(axisSelect.value)).assigned_model;
    if (assigned) modelSelect.value = assigned;
  };
  axisSelect.onchange();
  document.getElementById("create").onclick = createPanel;
  const diagnostics = document.getElementById("diagnostic-values");
  for (const [suffix, label] of diagnosticFields) {
    const term = document.createElement("dt"); term.textContent = label;
    const data = document.createElement("dd"); data.dataset.diagnostic = suffix; data.textContent = "—";
    diagnostics.append(term, data);
  }
  document.getElementById("release-emg").onclick = () => recoveryAction("release-emg");
  document.getElementById("refresh-axes").onclick = () => recoveryAction("refresh-axes");
  document.getElementById("connection").textContent =
    `localhost GUI · PV prefix ${configuration.prefix} · guarded HOME만 활성`;
  setInterval(() => activePanels.forEach((_, axis) => refreshPanel(axis)), 1000);
  refreshDiagnostics();
  setInterval(refreshDiagnostics, 1000);
}

start().catch(error => { document.getElementById("connection").textContent = error.message; });
