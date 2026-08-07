#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <limits>
#include <map>

#include "asynOctetSyncIO.h"
#include "epicsExport.h"
#include "iocsh.h"

#include "KohzuAriesLynxController.h"
#include "KohzuAriesLynxDiagnostics.h"
#include "KohzuAriesLynxMotion.h"
#include "KohzuAriesLynxSpeedTable.h"

namespace {
constexpr int kDriverParameterCount = 17;
constexpr int kMaximumAxes = 32;
constexpr double kCommunicationTimeout = 2.0;
constexpr int kMaximumLinesPerTransaction = 16;
constexpr std::size_t kResponseBufferSize = 2048;

// IOC shell configuration commands resolve a controller by its asyn port.
// The registry does not create or own controller instances.
std::map<std::string, KohzuAriesLynxController*> gControllers;

bool parseLong(const std::string& text, long* value) {
    if (!value || text.empty()) {
        return false;
    }
    char* end = nullptr;
    const long parsed = std::strtol(text.c_str(), &end, 10);
    if (end == text.c_str() || *end != '\0') {
        return false;
    }
    *value = parsed;
    return true;
}

}

KohzuAriesLynxController::KohzuAriesLynxController(
    const char* portName, const char* ioPortName, int numAxes,
    double movingPollPeriod, double idlePollPeriod)
    : asynMotorController(portName, numAxes, kDriverParameterCount,
                          0, 0, ASYN_CANBLOCK | ASYN_MULTIDEVICE,
                          1, 0, 0),
      ioPortName_(ioPortName ? ioPortName : ""),
      detectedAxes_(0),
      connectionStatus_(asynError),
      emergencyStates_(numAxes, false) {
    // Controller-level diagnostics use address 0 and are read-only to clients.
    createParam("LAST_ERROR_CODE", asynParamInt32, &lastErrorCode_);
    createParam("LAST_ERROR_TEXT", asynParamOctet, &lastErrorText_);
    createParam("LAST_ERROR_COMMAND", asynParamOctet, &lastErrorCommand_);
    createParam("LAST_ERROR_RAW", asynParamOctet, &lastErrorRaw_);
    createParam("LAST_WARNING_CODE", asynParamInt32, &lastWarningCode_);
    createParam("LAST_WARNING_TEXT", asynParamOctet, &lastWarningText_);
    createParam("LAST_WARNING_COMMAND", asynParamOctet, &lastWarningCommand_);
    createParam("LAST_WARNING_RAW", asynParamOctet, &lastWarningRaw_);
    createParam("EMERGENCY_ACTIVE", asynParamInt32, &emergencyActive_);
    createParam("RECOVERY_REM_REQUEST", asynParamInt32,
                &recoveryRemRequest_);
    createParam("RECOVERY_RAX_REQUEST", asynParamInt32,
                &recoveryRaxRequest_);
    createParam("RECOVERY_STATUS", asynParamOctet, &recoveryStatus_);
    createParam("SELECTED_HOME_METHOD", asynParamInt32,
                &selectedHomeMethodParam_);
    createParam("ACTUAL_HOME_METHOD", asynParamInt32,
                &actualHomeMethodParam_);
    createParam("HOME_STATUS", asynParamOctet, &homeStatusParam_);
    createParam("MOVE_STATUS", asynParamOctet, &moveStatusParam_);
    createParam("POSITION_STATUS", asynParamOctet, &positionStatusParam_);
    setIntegerParam(0, lastErrorCode_, 0);
    setIntegerParam(0, lastWarningCode_, 0);
    setStringParam(0, lastErrorText_, "No error received");
    setStringParam(0, lastWarningText_, "No warning received");
    setStringParam(0, lastErrorCommand_, "");
    setStringParam(0, lastErrorRaw_, "");
    setStringParam(0, lastWarningCommand_, "");
    setStringParam(0, lastWarningRaw_, "");
    setIntegerParam(0, emergencyActive_, 0);
    setIntegerParam(0, recoveryRemRequest_, 0);
    setIntegerParam(0, recoveryRaxRequest_, 0);
    setStringParam(0, recoveryStatus_, "No recovery requested");
    for (int axisNo = 0; axisNo < numAxes; ++axisNo) {
        new KohzuAriesLynxAxis(this, axisNo);
    }

    // Attach synchronous octet I/O to the drvAsynIPPort created by st.cmd.
    // connect() creates an asynUser; the underlying TCP port still follows
    // asyn's auto-connect and reconnect behavior.
    pasynUserController_ = nullptr;
    connectionStatus_ = pasynOctetSyncIO->connect(
        ioPortName_.c_str(), 0, &pasynUserController_, nullptr);
    if (connectionStatus_ == asynSuccess) {
        // ARIES Ethernet commands do not use STX. Both directions use CRLF as
        // their line delimiter, which asyn appends/removes for this client.
        connectionStatus_ = pasynOctetSyncIO->setOutputEos(
            pasynUserController_, "\r\n", 2);
        if (connectionStatus_ == asynSuccess) {
            connectionStatus_ = pasynOctetSyncIO->setInputEos(
                pasynUserController_, "\r\n", 2);
        }
    }

    // Only read-only discovery commands are issued at construction. Failure
    // leaves the skeleton in problem state; no motor command is attempted.
    if (connectionStatus_ == asynSuccess) {
        if (readIdentity(&identity_) != asynSuccess ||
            readAxisConfiguration(&detectedAxes_) != asynSuccess) {
            connectionStatus_ = asynError;
        }
    }

    if (connectionStatus_ == asynSuccess) {
        // RAX defines which of the pre-created maximum axes physically exist.
        // Inactive axes remain present for future expansion but the poller skips
        // them, avoiding repeated invalid-axis commands.
        for (int axisNo = 0; axisNo < numAxes_; ++axisNo) {
            KohzuAriesLynxAxis* axis = getAxis(axisNo);
            axis->setDisableFlag(axisNo >= detectedAxes_ ? 1 : 0);
        }
        startPoller(movingPollPeriod, idlePollPeriod, 2);
    } else {
        movingPollPeriod_ = movingPollPeriod;
        idlePollPeriod_ = idlePollPeriod;
    }
    gControllers[portName] = this;
}

KohzuAriesLynxController::~KohzuAriesLynxController() {
    const auto entry = gControllers.find(portName);
    if (entry != gControllers.end() && entry->second == this) {
        gControllers.erase(entry);
    }
    if (pasynUserController_) {
        pasynOctetSyncIO->disconnect(pasynUserController_);
        pasynUserController_ = nullptr;
    }
}

KohzuAriesLynxAxis* KohzuAriesLynxController::getAxis(asynUser* pasynUser) {
    return static_cast<KohzuAriesLynxAxis*>(
        asynMotorController::getAxis(pasynUser));
}

KohzuAriesLynxAxis* KohzuAriesLynxController::getAxis(int axisNo) {
    return static_cast<KohzuAriesLynxAxis*>(
        asynMotorController::getAxis(axisNo));
}

void KohzuAriesLynxController::report(FILE* fp, int details) {
    std::fprintf(fp, "KOHZU ARIES/LYNX Model 3 driver skeleton\n");
    std::fprintf(fp, "  motor port: %s\n", portName);
    std::fprintf(fp, "  I/O port: %s\n", ioPortName_.c_str());
    std::fprintf(fp, "  configured axes: %d\n", numAxes_);
    std::fprintf(fp, "  detected axes: %d\n", detectedAxes_);
    std::fprintf(fp, "  identity: %s\n",
                 identity_.empty() ? "not read" : identity_.c_str());
    std::fprintf(fp, "  communication: %s\n",
                 connectionStatus_ == asynSuccess ? "connected" : "not ready");
    // Reporting the retained event makes diagnostics available even when the
    // active asyn trace mask suppresses warning-level messages.
    std::fprintf(fp, "  last asynchronous event: %s\n",
                 lastSystemEvent_.raw.empty()
                     ? "none"
                     : lastSystemEvent_.raw.c_str());
    asynMotorController::report(fp, details);
}

asynStatus KohzuAriesLynxController::writeInt32(
    asynUser* pasynUser, epicsInt32 value) {
    if (!pasynUser) {
        return asynError;
    }

    const int function = pasynUser->reason;
    if (function == selectedHomeMethodParam_) {
        int address = 0;
        if (getAddress(pasynUser, &address) != asynSuccess ||
            address < 0 || address >= numAxes_) {
            return asynError;
        }
        // A PV write only stages the user's selection in the driver. SYS.2 is
        // written later as part of the guarded HOME transaction.
        return getAxis(address)->setSelectedHomeMethod(value);
    }
    if (value != 0 && function == recoveryRemRequest_) {
        const asynStatus status = releaseEmergencyStop();
        // Request records behave like momentary buttons, including on failure.
        setIntegerParam(0, recoveryRemRequest_, 0);
        callParamCallbacks(0);
        return status;
    }
    if (value != 0 && function == recoveryRaxRequest_) {
        const asynStatus status = refreshAxisConfiguration();
        setIntegerParam(0, recoveryRaxRequest_, 0);
        callParamCallbacks(0);
        return status;
    }
    return asynMotorController::writeInt32(pasynUser, value);
}

asynStatus KohzuAriesLynxController::transact(
    const std::string& command, const std::string& expectedResponse,
    KohzuResponse* response) {
    if (!pasynUserController_ || !response) {
        return asynError;
    }

    // Write exactly one command. Output EOS supplies CRLF, so the caller must
    // pass only the command body (for example, "IDN" or "RAX").
    std::size_t bytesWritten = 0;
    asynStatus status = pasynOctetSyncIO->write(
        pasynUserController_, command.c_str(), command.size(),
        kCommunicationTimeout, &bytesWritten);
    if (status != asynSuccess || bytesWritten != command.size()) {
        return asynError;
    }

    // A spontaneous E/W SYS line may precede the requested response. Consume
    // and record such events, then continue reading without resending command.
    for (int lineNo = 0; lineNo < kMaximumLinesPerTransaction; ++lineNo) {
        char input[kResponseBufferSize] = {};
        std::size_t bytesRead = 0;
        int eomReason = 0;
        status = pasynOctetSyncIO->read(
            pasynUserController_, input, sizeof(input) - 1,
            kCommunicationTimeout, &bytesRead, &eomReason);
        if (status != asynSuccess) {
            return status;
        }
        input[bytesRead] = '\0';

        KohzuResponse parsed = parseKohzuResponse(input);
        if (parsed.kind == KohzuResponseKind::Invalid) {
            return asynError;
        }
        if (parsed.systemEvent) {
            lastSystemEvent_ = parsed;
            updateDiagnostic(parsed);
            asynPrint(pasynUserSelf, ASYN_TRACE_WARNING,
                      "%s: asynchronous controller event: %s\n",
                      portName, parsed.raw.c_str());
            continue;
        }
        if (!kohzuResponseMatches(parsed, expectedResponse)) {
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                      "%s: expected %s response, received %s\n",
                      portName, expectedResponse.c_str(), parsed.raw.c_str());
            return asynError;
        }

        *response = parsed;
        updateDiagnostic(parsed);
        return parsed.kind == KohzuResponseKind::Normal
                   ? asynSuccess
                   : asynError;
    }
    return asynError;
}

void KohzuAriesLynxController::updateDiagnostic(
    const KohzuResponse& response) {
    if (!response.hasCode ||
        (response.kind != KohzuResponseKind::Error &&
         response.kind != KohzuResponseKind::Warning)) {
        return;
    }

    const bool warning = response.kind == KohzuResponseKind::Warning;
    const int codeParam = warning ? lastWarningCode_ : lastErrorCode_;
    const int textParam = warning ? lastWarningText_ : lastErrorText_;
    const int commandParam = warning ? lastWarningCommand_ : lastErrorCommand_;
    const int rawParam = warning ? lastWarningRaw_ : lastErrorRaw_;
    setIntegerParam(0, codeParam, response.code);
    setStringParam(0, textParam,
                   kohzuDiagnosticText(warning, response.code).c_str());
    setStringParam(0, commandParam, response.command.c_str());
    setStringParam(0, rawParam, response.raw.c_str());
    callParamCallbacks(0);
}

asynStatus KohzuAriesLynxController::readIdentity(std::string* identity) {
    if (!identity) {
        return asynError;
    }
    KohzuResponse response;
    const asynStatus status = transact("IDN", "IDN", &response);
    if (status != asynSuccess || response.fields.empty()) {
        return asynError;
    }

    // Preserve every IDN information field in a compact, readable string.
    identity->clear();
    for (std::size_t index = 0; index < response.fields.size(); ++index) {
        if (index != 0) {
            identity->append(" ");
        }
        identity->append(response.fields[index]);
    }
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::readAxisConfiguration(int* detectedAxes) {
    if (!detectedAxes) {
        return asynError;
    }
    KohzuResponse response;
    const asynStatus status = transact("RAX", "RAX", &response);
    if (status != asynSuccess || response.fields.size() < 2) {
        return asynError;
    }

    // RAX field 0 is total device count; field 1 is controllable axis count.
    long value = 0;
    if (!parseLong(response.fields[1], &value) ||
        value < 1 || value > kMaximumAxes) {
        return asynError;
    }
    *detectedAxes = static_cast<int>(value);
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::readAxisSnapshot(
    int controllerAxisNo, KohzuAxisSnapshot* snapshot) {
    if (!snapshot || controllerAxisNo < 1 ||
        controllerAxisNo > detectedAxes_) {
        return asynError;
    }

    KohzuResponse positionResponse;
    KohzuResponse statusResponse;
    KohzuResponse originResponse;
    const std::string axis = std::to_string(controllerAxisNo);

    if (transact("RDP" + axis, "RDP", &positionResponse) != asynSuccess ||
        positionResponse.fields.empty() ||
        transact("STR" + axis, "STR", &statusResponse) != asynSuccess ||
        statusResponse.fields.size() < 6 ||
        transact("ROG" + axis, "ROG", &originResponse) != asynSuccess ||
        originResponse.fields.empty()) {
        return asynError;
    }

    long position = 0;
    long drivingState = 0;
    long emergencyState = 0;
    long originState = 0;
    long limitState = 0;
    long homedState = 0;
    if (!parseLong(positionResponse.fields[0], &position) ||
        !parseLong(statusResponse.fields[0], &drivingState) ||
        !parseLong(statusResponse.fields[1], &emergencyState) ||
        !parseLong(statusResponse.fields[2], &originState) ||
        !parseLong(statusResponse.fields[3], &limitState) ||
        !parseLong(originResponse.fields[0], &homedState)) {
        return asynError;
    }

    snapshot->position = static_cast<double>(position);
    snapshot->moving = drivingState != 0;
    snapshot->emergencyStop = emergencyState != 0;
    // STR encodes ORG/NORG as a two-bit value; bit 1 is ORG.
    snapshot->originSensor = (originState & 0x2) != 0;
    // STR limit encoding: bit 0=CCW, bit 1=CW.
    snapshot->ccwLimit = (limitState & 0x1) != 0;
    snapshot->cwLimit = (limitState & 0x2) != 0;
    snapshot->homed = homedState == 1;
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::stopAxis(int controllerAxisNo) {
    if (controllerAxisNo < 1 || controllerAxisNo > detectedAxes_) {
        return asynError;
    }

    KohzuResponse response;
    // STP a/0 selects the controller's normal decelerating stop.  Mode 1 is
    // an emergency stop and must not be substituted for a routine motor-record
    // STOP request.  The acceleration argument is not used by this command.
    const std::string command =
        "STP" + std::to_string(controllerAxisNo) + "/0";
    return transact(command, "STP", &response);
}

asynStatus KohzuAriesLynxController::configureSpeedTable0(
    int controllerAxisNo, double minVelocity, double maxVelocity,
    double acceleration) {
    if (controllerAxisNo < 1 || controllerAxisNo > detectedAxes_) {
        return asynError;
    }

    KohzuSpeedTable0 table;
    std::string command;
    std::string errorText;
    if (!buildKohzuSpeedTable0Command(
            controllerAxisNo, minVelocity, maxVelocity, acceleration,
            &table, &command, &errorText)) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                  "%s: table 0 rejected for axis %d: %s\n",
                  portName, controllerAxisNo, errorText.c_str());
        return asynError;
    }

    // SYS.16 is an axis-specific ceiling and may be lower than the WTB
    // protocol maximum. Read it immediately before writing table 0 so a stale
    // assumption cannot cause an avoidable controller error 607.
    KohzuResponse limitResponse;
    const std::string axis = std::to_string(controllerAxisNo);
    if (transact("RSY" + axis + "/16", "RSY", &limitResponse) !=
            asynSuccess ||
        limitResponse.fields.size() < 2) {
        return asynError;
    }
    long topSpeedLimit = 0;
    if (!parseLong(limitResponse.fields[1], &topSpeedLimit) ||
        topSpeedLimit < 2 || table.topSpeed > topSpeedLimit) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                  "%s: axis %d table top speed %ld exceeds SYS.16 limit %ld\n",
                  portName, controllerAxisNo, table.topSpeed, topSpeedLimit);
        return asynError;
    }

    // WTB changes only speed-table data. It never starts an axis; callers send
    // APS/RPS/ORG/FRP only after this validation succeeds.
    KohzuResponse response;
    return transact(command, "WTB", &response);
}

asynStatus KohzuAriesLynxController::setSelectedHomeMethod(
    int controllerAxisNo, int method) {
    if (controllerAxisNo < 1 || controllerAxisNo > numAxes_ ||
        method < 1 || method > 15) {
        return asynError;
    }
    return getAxis(controllerAxisNo - 1)->setSelectedHomeMethod(method);
}

asynStatus KohzuAriesLynxController::homeAxis(
    int controllerAxisNo, int selectedMethod, double minVelocity,
    double maxVelocity, double acceleration) {
    if (controllerAxisNo < 1 || controllerAxisNo > detectedAxes_ ||
        selectedMethod < 1 || selectedMethod > 15) {
        return asynError;
    }

    const int address = controllerAxisNo - 1;
    const std::string axis = std::to_string(controllerAxisNo);
    KohzuResponse safetyResponse;
    if (transact("STR" + axis, "STR", &safetyResponse) != asynSuccess ||
        safetyResponse.fields.size() < 2) {
        setStringParam(address, homeStatusParam_,
                       "HOME blocked: unable to verify drive and EMG state");
        callParamCallbacks(address);
        return asynError;
    }
    long drivingState = 0;
    long emergencyState = 0;
    if (!parseLong(safetyResponse.fields[0], &drivingState) ||
        !parseLong(safetyResponse.fields[1], &emergencyState)) {
        setStringParam(address, homeStatusParam_,
                       "HOME blocked: invalid STR safety response");
        callParamCallbacks(address);
        return asynError;
    }
    if (drivingState != 0 || emergencyState != 0) {
        setStringParam(address, homeStatusParam_,
                       drivingState != 0
                           ? "HOME blocked: axis is already driving"
                           : "HOME blocked: emergency-stop input is active");
        callParamCallbacks(address);
        return asynError;
    }
    KohzuResponse methodResponse;
    if (transact("RSY" + axis + "/2", "RSY", &methodResponse) !=
            asynSuccess ||
        methodResponse.fields.size() < 2) {
        setStringParam(address, homeStatusParam_,
                       "HOME blocked: unable to read controller SYS.2");
        callParamCallbacks(address);
        return asynError;
    }

    long actualMethod = 0;
    if (!parseLong(methodResponse.fields[1], &actualMethod) ||
        actualMethod < 1 || actualMethod > 15) {
        setStringParam(address, homeStatusParam_,
                       "HOME blocked: invalid controller SYS.2 response");
        callParamCallbacks(address);
        return asynError;
    }
    setIntegerParam(address, actualHomeMethodParam_, actualMethod);
    callParamCallbacks(address);

    if (actualMethod != selectedMethod) {
        KohzuResponse writeResponse;
        const std::string writeCommand =
            "WSY" + axis + "/2/" + std::to_string(selectedMethod);
        if (transact(writeCommand, "WSY", &writeResponse) != asynSuccess) {
            setStringParam(address, homeStatusParam_,
                           "HOME blocked: controller rejected SYS.2 update");
            callParamCallbacks(address);
            return asynError;
        }

        // A normal WSY response is immediate. Read back SYS.2 before ORG so a
        // lost or rejected setting can never select a different search path.
        KohzuResponse verifyResponse;
        if (transact("RSY" + axis + "/2", "RSY", &verifyResponse) !=
                asynSuccess ||
            verifyResponse.fields.size() < 2 ||
            !parseLong(verifyResponse.fields[1], &actualMethod) ||
            actualMethod != selectedMethod) {
            setStringParam(address, homeStatusParam_,
                           "HOME blocked: SYS.2 readback did not match selection");
            callParamCallbacks(address);
            return asynError;
        }
        setIntegerParam(address, actualHomeMethodParam_, actualMethod);
        callParamCallbacks(address);
    }

    // Method 10 does not drive and ignores the speed table. Every other
    // method can move while searching for sensors, so validate and write table
    // 0 from the Model 3 HOME request before starting ORG.
    if (actualMethod != 10 &&
        configureSpeedTable0(controllerAxisNo, minVelocity, maxVelocity,
                             acceleration) != asynSuccess) {
        setStringParam(address, homeStatusParam_,
                       "HOME blocked: speed table 0 validation failed");
        callParamCallbacks(address);
        return asynError;
    }

    KohzuResponse response;
    const std::string command = "ORG" + axis + "/0/1";
    if (transact(command, "ORG", &response) != asynSuccess) {
        setStringParam(address, homeStatusParam_,
                       "HOME failed: inspect ARIES error diagnostics");
        callParamCallbacks(address);
        return asynError;
    }
    setStringParam(address, homeStatusParam_,
                   actualMethod == 10
                       ? "Method 10 accepted: present position set as origin"
                       : "ORG accepted: origin search in progress");
    callParamCallbacks(address);
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::moveAxis(
    int controllerAxisNo, double position, bool relative,
    double minVelocity, double maxVelocity, double acceleration,
    double lowLimit, double highLimit) {
    if (controllerAxisNo < 1 || controllerAxisNo > detectedAxes_ ||
        !std::isfinite(lowLimit) || !std::isfinite(highLimit) ||
        lowLimit >= highLimit) {
        return asynError;
    }

    const int address = controllerAxisNo - 1;
    std::string command;
    std::string errorText;
    long roundedPosition = 0;
    if (!buildKohzuPositionCommand(
            controllerAxisNo, position, relative, &command,
            &roundedPosition, &errorText)) {
        const std::string message = "MOVE blocked: " + errorText;
        setStringParam(address, moveStatusParam_, message.c_str());
        callParamCallbacks(address);
        return asynError;
    }

    // A fresh snapshot supplies both the pulse coordinate needed for a
    // relative target and the safety state. Do not trust an older poll cycle.
    KohzuAxisSnapshot snapshot;
    if (readAxisSnapshot(controllerAxisNo, &snapshot) != asynSuccess) {
        setStringParam(address, moveStatusParam_,
                       "MOVE blocked: unable to verify position and status");
        callParamCallbacks(address);
        return asynError;
    }
    if (snapshot.moving || snapshot.emergencyStop) {
        setStringParam(address, moveStatusParam_,
                       snapshot.moving
                           ? "MOVE blocked: axis is already driving"
                           : "MOVE blocked: emergency-stop input is active");
        callParamCallbacks(address);
        return asynError;
    }

    double target = 0.0;
    if (!validateKohzuSoftLimitTarget(
            snapshot.position, roundedPosition, relative, lowLimit,
            highLimit, &target, &errorText)) {
        const std::string message = "MOVE blocked: " + errorText +
            " (allowed " + std::to_string(lowLimit) + ".." +
            std::to_string(highLimit) + " pulse)";
        setStringParam(address, moveStatusParam_, message.c_str());
        callParamCallbacks(address);
        return asynError;
    }

    if (configureSpeedTable0(controllerAxisNo, minVelocity, maxVelocity,
                             acceleration) != asynSuccess) {
        setStringParam(address, moveStatusParam_,
                       "MOVE blocked: speed table 0 validation failed");
        callParamCallbacks(address);
        return asynError;
    }

    KohzuResponse response;
    const std::string expected = relative ? "RPS" : "APS";
    if (transact(command, expected, &response) != asynSuccess) {
        setStringParam(address, moveStatusParam_,
                       "MOVE failed: inspect ARIES error diagnostics");
        callParamCallbacks(address);
        return asynError;
    }
    const std::string message =
        expected + " accepted: target=" + std::to_string(target) + " pulse";
    setStringParam(address, moveStatusParam_, message.c_str());
    callParamCallbacks(address);
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::jogAxis(
    int controllerAxisNo, double minVelocity, double maxVelocity,
    double acceleration, double lowLimit, double highLimit) {
    if (controllerAxisNo < 1 || controllerAxisNo > detectedAxes_) {
        return asynError;
    }
    const int address = controllerAxisNo - 1;
    std::string command;
    std::string errorText;
    bool clockwise = false;
    if (!buildKohzuFreeRotationCommand(controllerAxisNo, maxVelocity,
                                        &command, &clockwise, &errorText)) {
        const std::string message = "JOG blocked: " + errorText;
        setStringParam(address, moveStatusParam_, message.c_str());
        callParamCallbacks(address);
        return asynError;
    }

    // Read immediately before FRP so an EMG assertion or limit transition
    // observed after the last poll cannot start continuous motion.
    KohzuAxisSnapshot snapshot;
    if (readAxisSnapshot(controllerAxisNo, &snapshot) != asynSuccess ||
        snapshot.moving || snapshot.emergencyStop ||
        !validateKohzuJogStart(snapshot.position, clockwise,
                               snapshot.cwLimit, snapshot.ccwLimit,
                               lowLimit, highLimit, &errorText)) {
        if (errorText.empty()) {
            errorText = snapshot.moving ? "axis is already driving" :
                snapshot.emergencyStop ? "emergency-stop input is active" :
                "unable to verify position and status";
        }
        const std::string message = "JOG blocked: " + errorText;
        setStringParam(address, moveStatusParam_, message.c_str());
        callParamCallbacks(address);
        return asynError;
    }

    // Velocity magnitude configures table 0; its original sign selects FRP
    // direction. Acceleration is converted by the shared table builder.
    if (configureSpeedTable0(controllerAxisNo, std::fabs(minVelocity),
                             std::fabs(maxVelocity),
                             std::fabs(acceleration)) != asynSuccess) {
        setStringParam(address, moveStatusParam_,
                       "JOG blocked: speed table 0 validation failed");
        callParamCallbacks(address);
        return asynError;
    }
    KohzuResponse response;
    if (transact(command, "FRP", &response) != asynSuccess) {
        setStringParam(address, moveStatusParam_,
                       "JOG failed: inspect ARIES error diagnostics");
        callParamCallbacks(address);
        return asynError;
    }
    const std::string message = std::string("FRP accepted: direction=") +
        (clockwise ? "CW" : "CCW") + "; release JOG to send STP/0";
    setStringParam(address, moveStatusParam_, message.c_str());
    callParamCallbacks(address);
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::setAxisPosition(
    int controllerAxisNo, double position) {
    if (controllerAxisNo < 1 || controllerAxisNo > detectedAxes_) {
        return asynError;
    }
    const int address = controllerAxisNo - 1;
    std::string command;
    std::string errorText;
    long requestedPulses = 0;
    if (!buildKohzuSetPositionCommand(controllerAxisNo, position, &command,
                                       &requestedPulses, &errorText)) {
        const std::string message = "SET position blocked: " + errorText;
        setStringParam(address, positionStatusParam_, message.c_str());
        callParamCallbacks(address);
        return asynError;
    }

    KohzuAxisSnapshot before;
    if (readAxisSnapshot(controllerAxisNo, &before) != asynSuccess ||
        before.moving || before.emergencyStop) {
        const char* reason = before.moving ? "axis is driving" :
            before.emergencyStop ? "emergency-stop input is active" :
            "unable to verify axis state";
        const std::string message = std::string("SET position blocked: ") + reason;
        setStringParam(address, positionStatusParam_, message.c_str());
        callParamCallbacks(address);
        return asynError;
    }

    // WRP changes the controller pulse coordinate only; it does not drive the
    // motor. Verify with RDP because a normal acknowledgement contains no value.
    KohzuResponse writeResponse;
    if (transact(command, "WRP", &writeResponse) != asynSuccess) {
        setStringParam(address, positionStatusParam_,
                       "SET position failed: inspect ARIES diagnostics");
        callParamCallbacks(address);
        return asynError;
    }
    KohzuResponse readbackResponse;
    if (transact("RDP" + std::to_string(controllerAxisNo), "RDP",
                 &readbackResponse) != asynSuccess ||
        readbackResponse.fields.empty()) {
        setStringParam(address, positionStatusParam_,
                       "SET position failed: RDP verification unavailable");
        callParamCallbacks(address);
        return asynError;
    }
    long actualPulses = 0;
    if (!parseLong(readbackResponse.fields[0], &actualPulses) ||
        actualPulses != requestedPulses) {
        setStringParam(address, positionStatusParam_,
                       "SET position failed: RDP did not match WRP");
        callParamCallbacks(address);
        return asynError;
    }
    setDoubleParam(address, motorPosition_, static_cast<double>(actualPulses));
    const std::string message =
        "WRP verified: position=" + std::to_string(actualPulses) + " pulse";
    setStringParam(address, positionStatusParam_, message.c_str());
    callParamCallbacks(address);
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::readEmergencyStopState(
    int controllerAxisNo, bool* active) {
    if (!active || controllerAxisNo < 1 ||
        controllerAxisNo > detectedAxes_) {
        return asynError;
    }
    KohzuResponse response;
    const std::string axis = std::to_string(controllerAxisNo);
    if (transact("STR" + axis, "STR", &response) != asynSuccess ||
        response.fields.size() < 2) {
        return asynError;
    }
    long emergencyState = 0;
    if (!parseLong(response.fields[1], &emergencyState)) {
        return asynError;
    }
    *active = emergencyState != 0;
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::releaseEmergencyStop() {
    // REM is allowed only after a fresh STR check confirms that the physical
    // emergency input is clear on every detected axis. A failed check is not
    // treated as safe; it blocks release without transmitting REM.
    for (int axis = 1; axis <= detectedAxes_; ++axis) {
        bool active = false;
        if (readEmergencyStopState(axis, &active) != asynSuccess) {
            setRecoveryStatus("REM blocked: unable to verify all EMG inputs");
            return asynError;
        }
        if (active) {
            setIntegerParam(0, emergencyActive_, 1);
            setRecoveryStatus("REM blocked: physical EMG input remains active");
            return asynError;
        }
    }

    KohzuResponse response;
    if (transact("REM", "REM", &response) != asynSuccess) {
        setRecoveryStatus("REM failed; inspect LastError diagnostics");
        return asynError;
    }
    setIntegerParam(0, emergencyActive_, 0);
    setRecoveryStatus("REM completed; position may be invalid, re-home required");
    return asynSuccess;
}

asynStatus KohzuAriesLynxController::refreshAxisConfiguration() {
    int axes = 0;
    if (readAxisConfiguration(&axes) != asynSuccess) {
        setRecoveryStatus("RAX failed; inspect LastError diagnostics");
        return asynError;
    }
    detectedAxes_ = axes;
    for (int axisNo = 0; axisNo < numAxes_; ++axisNo) {
        getAxis(axisNo)->setDisableFlag(axisNo >= detectedAxes_ ? 1 : 0);
    }
    setRecoveryStatus("RAX completed; axis map refreshed, verify and re-home");
    return asynSuccess;
}

void KohzuAriesLynxController::recordAxisEmergencyState(
    int controllerAxisNo, bool active) {
    const int index = controllerAxisNo - 1;
    if (index < 0 || index >= static_cast<int>(emergencyStates_.size())) {
        return;
    }
    emergencyStates_[index] = active;
    bool anyActive = false;
    for (int axis = 0; axis < detectedAxes_; ++axis) {
        anyActive = anyActive || emergencyStates_[axis];
    }
    setIntegerParam(0, emergencyActive_, anyActive ? 1 : 0);
    callParamCallbacks(0);
}

void KohzuAriesLynxController::setRecoveryStatus(const std::string& text) {
    setStringParam(0, recoveryStatus_, text.c_str());
    callParamCallbacks(0);
}

KohzuAriesLynxAxis::KohzuAriesLynxAxis(
    KohzuAriesLynxController* controller, int axisNo)
    : asynMotorAxis(controller, axisNo),
      controller_(controller),
      controllerAxisNo_(axisNo + 1),
      hasSnapshot_(false),
      selectedHomeMethod_(10) {
    setIntegerParam(controller_->motorStatusDone_, 1);
    setIntegerParam(controller_->motorStatusMoving_, 0);
    setIntegerParam(controller_->motorStatusProblem_, 1);
    setIntegerParam(controller_->selectedHomeMethodParam_,
                    selectedHomeMethod_);
    setIntegerParam(controller_->actualHomeMethodParam_, 0);
    setStringParam(controller_->homeStatusParam_,
                   "Select HOME Method 1..15; sensor suitability is user responsibility");
    setStringParam(controller_->moveStatusParam_, "MOVE not requested");
    setStringParam(controller_->positionStatusParam_, "SET position not requested");
    callParamCallbacks();
}

void KohzuAriesLynxAxis::report(FILE* fp, int details) {
    if (details > 0) {
        if (hasSnapshot_) {
            std::fprintf(
                fp,
                "  axis %d: position=%.0f moving=%s homed=%s "
                "CW-limit=%s CCW-limit=%s EMG=%s\n",
                controllerAxisNo_, snapshot_.position,
                snapshot_.moving ? "yes" : "no",
                snapshot_.homed ? "yes" : "no",
                snapshot_.cwLimit ? "yes" : "no",
                snapshot_.ccwLimit ? "yes" : "no",
                snapshot_.emergencyStop ? "yes" : "no");
        } else {
            std::fprintf(fp, "  axis %d: no readback yet\n", controllerAxisNo_);
        }
    }
    asynMotorAxis::report(fp, details);
}

asynStatus KohzuAriesLynxAxis::move(
    double position, int relative, double minVelocity, double maxVelocity,
    double acceleration) {
    double lowLimit = 0.0;
    double highLimit = 0.0;
    const int address = controllerAxisNo_ - 1;
    if (controller_->getDoubleParam(
            address, controller_->motorLowLimit_, &lowLimit) != asynSuccess ||
        controller_->getDoubleParam(
            address, controller_->motorHighLimit_, &highLimit) != asynSuccess) {
        return asynError;
    }
    const asynStatus status = controller_->moveAxis(
        controllerAxisNo_, position, relative != 0, minVelocity,
        maxVelocity, acceleration, lowLimit, highLimit);
    if (status == asynSuccess) {
        setIntegerParam(controller_->motorStatusDone_, 0);
        setIntegerParam(controller_->motorStatusMoving_, 1);
        callParamCallbacks();
    }
    return status;
}

asynStatus KohzuAriesLynxAxis::moveVelocity(
    double minVelocity, double maxVelocity, double acceleration) {
    double lowLimit = 0.0;
    double highLimit = 0.0;
    const int address = controllerAxisNo_ - 1;
    if (controller_->getDoubleParam(
            address, controller_->motorLowLimit_, &lowLimit) != asynSuccess ||
        controller_->getDoubleParam(
            address, controller_->motorHighLimit_, &highLimit) != asynSuccess) {
        return asynError;
    }
    const asynStatus status = controller_->jogAxis(
        controllerAxisNo_, minVelocity, maxVelocity, acceleration,
        lowLimit, highLimit);
    if (status == asynSuccess) {
        setIntegerParam(controller_->motorStatusDone_, 0);
        setIntegerParam(controller_->motorStatusMoving_, 1);
        callParamCallbacks();
    }
    return status;
}

asynStatus KohzuAriesLynxAxis::home(
    double minVelocity, double maxVelocity, double acceleration,
    int forwards) {
    // Direction is defined by the selected ARIES origin method and sensor
    // layout; the motor record's HOMF/HOMR distinction cannot override it.
    (void)forwards;
    // Clear the displayed cached homed bit while the new ORG request starts;
    // the normal poll path will publish the controller's next ROG readback.
    setIntegerParam(controller_->motorStatusHomed_, 0);
    callParamCallbacks();
    return controller_->homeAxis(controllerAxisNo_, selectedHomeMethod_,
                                 minVelocity, maxVelocity, acceleration);
}

asynStatus KohzuAriesLynxAxis::setSelectedHomeMethod(int method) {
    if (method < 1 || method > 15) {
        const std::string message = "OriginMethod rejected: valid range=1..15";
        setStringParam(controller_->homeStatusParam_, message.c_str());
        callParamCallbacks();
        return asynError;
    }
    selectedHomeMethod_ = method;
    setIntegerParam(controller_->selectedHomeMethodParam_, method);
    const std::string message =
        "HOME method selected=" + std::to_string(method) +
        "; controller SYS.2 will be checked before ORG";
    setStringParam(controller_->homeStatusParam_, message.c_str());
    callParamCallbacks();
    return asynSuccess;
}

asynStatus KohzuAriesLynxAxis::stop(double acceleration) {
    // ARIES chooses the deceleration from its active speed table; Model 3's
    // acceleration argument therefore cannot alter an already-running move.
    (void)acceleration;
    return controller_->stopAxis(controllerAxisNo_);
}

asynStatus KohzuAriesLynxAxis::poll(bool* moving) {
    if (getDisableFlag()) {
        *moving = false;
        return asynSuccess;
    }

    KohzuAxisSnapshot current;
    const asynStatus status =
        controller_->readAxisSnapshot(controllerAxisNo_, &current);
    if (status != asynSuccess) {
        *moving = false;
        setIntegerParam(controller_->motorStatusCommsError_, 1);
        setIntegerParam(controller_->motorStatusProblem_, 1);
        callParamCallbacks();
        return asynError;
    }

    snapshot_ = current;
    hasSnapshot_ = true;
    controller_->recordAxisEmergencyState(controllerAxisNo_,
                                          current.emergencyStop);
    *moving = current.moving;
    setDoubleParam(controller_->motorPosition_, current.position);
    setIntegerParam(controller_->motorStatusDone_, current.moving ? 0 : 1);
    setIntegerParam(controller_->motorStatusMoving_, current.moving ? 1 : 0);
    setIntegerParam(controller_->motorStatusAtHome_,
                    current.originSensor ? 1 : 0);
    setIntegerParam(controller_->motorStatusHighLimit_,
                    current.cwLimit ? 1 : 0);
    setIntegerParam(controller_->motorStatusLowLimit_,
                    current.ccwLimit ? 1 : 0);
    setIntegerParam(controller_->motorStatusHomed_, current.homed ? 1 : 0);
    setIntegerParam(controller_->motorStatusCommsError_, 0);
    setIntegerParam(controller_->motorStatusProblem_,
                    current.emergencyStop ? 1 : 0);
    callParamCallbacks();
    return asynSuccess;
}

asynStatus KohzuAriesLynxAxis::setPosition(double position) {
    return controller_->setAxisPosition(controllerAxisNo_, position);
}

extern "C" int KohzuAriesLynxCreateController(
    const char* portName, const char* ioPortName, int numAxes,
    int movingPollPeriodMs, int idlePollPeriodMs) {
    if (!portName || !ioPortName || numAxes < 1 || numAxes > kMaximumAxes ||
        movingPollPeriodMs < 1 || idlePollPeriodMs < 1) {
        return asynError;
    }

    new KohzuAriesLynxController(
        portName, ioPortName, numAxes,
        movingPollPeriodMs / 1000.0, idlePollPeriodMs / 1000.0);
    return asynSuccess;
}

static const iocshArg createArg0 = {"Motor port name", iocshArgString};
static const iocshArg createArg1 = {"TCP asyn port name", iocshArgString};
static const iocshArg createArg2 = {"Number of axes (1-32)", iocshArgInt};
static const iocshArg createArg3 = {"Moving poll period (ms)", iocshArgInt};
static const iocshArg createArg4 = {"Idle poll period (ms)", iocshArgInt};
static const iocshArg* const createArgs[] = {
    &createArg0, &createArg1, &createArg2, &createArg3, &createArg4};
static const iocshFuncDef createDef = {
    "KohzuAriesLynxCreateController", 5, createArgs};

static void createCall(const iocshArgBuf* args) {
    KohzuAriesLynxCreateController(
        args[0].sval, args[1].sval, args[2].ival,
        args[3].ival, args[4].ival);
}

static const iocshArg speedArg0 = {"Motor port name", iocshArgString};
static const iocshArg speedArg1 = {"Controller axis (1-32)", iocshArgInt};
static const iocshArg speedArg2 = {"Start speed (pulse/s)", iocshArgDouble};
static const iocshArg speedArg3 = {"Top speed (pulse/s)", iocshArgDouble};
static const iocshArg speedArg4 = {"Acceleration (pulse/s^2)", iocshArgDouble};
static const iocshArg* const speedArgs[] = {
    &speedArg0, &speedArg1, &speedArg2, &speedArg3, &speedArg4};
static const iocshFuncDef speedDef = {
    "KohzuAriesLynxConfigureSpeedTable0", 5, speedArgs};

static void speedCall(const iocshArgBuf* args) {
    const std::string name = args[0].sval ? args[0].sval : "";
    const auto entry = gControllers.find(name);
    if (entry == gControllers.end()) {
        std::fprintf(stderr, "No KOHZU controller port named %s\n", name.c_str());
        return;
    }
    const asynStatus status = entry->second->configureSpeedTable0(
        args[1].ival, args[2].dval, args[3].dval, args[4].dval);
    if (status != asynSuccess) {
        std::fprintf(stderr, "KOHZU table 0 configuration failed for axis %d\n",
                     args[1].ival);
    }
}

static const iocshArg homeMethodArg0 = {"Motor port name", iocshArgString};
static const iocshArg homeMethodArg1 = {"Controller axis (1-32)", iocshArgInt};
static const iocshArg homeMethodArg2 = {"Selected home method (1-15)", iocshArgInt};
static const iocshArg* const homeMethodArgs[] = {
    &homeMethodArg0, &homeMethodArg1, &homeMethodArg2};
static const iocshFuncDef homeMethodDef = {
    "KohzuAriesLynxSetOriginMethod", 3, homeMethodArgs};

static void homeMethodCall(const iocshArgBuf* args) {
    const std::string name = args[0].sval ? args[0].sval : "";
    const auto entry = gControllers.find(name);
    if (entry == gControllers.end() ||
        entry->second->setSelectedHomeMethod(
            args[1].ival, args[2].ival) != asynSuccess) {
        std::fprintf(stderr,
                     "KOHZU home method selection failed for port %s axis %d\n",
                     name.c_str(), args[1].ival);
    }
}

extern "C" void KohzuAriesLynxRegister(void) {
    iocshRegister(&createDef, createCall);
    iocshRegister(&speedDef, speedCall);
    iocshRegister(&homeMethodDef, homeMethodCall);
}

epicsExportRegistrar(KohzuAriesLynxRegister);
