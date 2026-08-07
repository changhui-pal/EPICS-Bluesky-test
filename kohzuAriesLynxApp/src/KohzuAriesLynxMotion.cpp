#include "KohzuAriesLynxMotion.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace {
constexpr long kMinimumPulsePosition = -134217728L;
constexpr long kMaximumPulsePosition = 134217727L;
}

bool buildKohzuPositionCommand(
    int controllerAxisNo, double position, bool relative,
    std::string* command, long* roundedPosition, std::string* errorText) {
    if (!command || !roundedPosition || controllerAxisNo < 1 ||
        controllerAxisNo > 32) {
        if (errorText) {
            *errorText = "Invalid axis or output argument";
        }
        return false;
    }
    if (!std::isfinite(position) ||
        position < static_cast<double>(kMinimumPulsePosition) - 0.5 ||
        position > static_cast<double>(kMaximumPulsePosition) + 0.499999) {
        if (errorText) {
            *errorText = "Position is outside ARIES pulse coordinate range";
        }
        return false;
    }

    // motor record normally supplies an integral raw position, but Model 3's
    // interface is double. Round once here so the wire value is unambiguous.
    const long pulses = static_cast<long>(std::lround(position));
    if (pulses < kMinimumPulsePosition || pulses > kMaximumPulsePosition) {
        if (errorText) {
            *errorText = "Rounded position is outside ARIES pulse range";
        }
        return false;
    }

    const char* operation = relative ? "RPS" : "APS";
    // Project policy fixes speed table 0 and response method 1 (Quick).
    *command = std::string(operation) + std::to_string(controllerAxisNo) +
               "/0/" + std::to_string(pulses) + "/1";
    *roundedPosition = pulses;
    if (errorText) {
        errorText->clear();
    }
    return true;
}

bool validateKohzuSoftLimitTarget(
    double currentPosition, long commandPulses, bool relative,
    double lowLimit, double highLimit, double* target,
    std::string* errorText) {
    if (!target || !std::isfinite(currentPosition) ||
        !std::isfinite(lowLimit) || !std::isfinite(highLimit) ||
        lowLimit >= highLimit) {
        if (errorText) {
            *errorText = "Invalid current position or soft-limit configuration";
        }
        return false;
    }
    const double resolved = relative
        ? currentPosition + static_cast<double>(commandPulses)
        : static_cast<double>(commandPulses);
    // EGU-to-pulse conversion can leave a nominally integral record limit a
    // few ULP below its intended value (for example 7.35/0.0005).  Allow only
    // that representation error; this tolerance remains far below one pulse.
    const double comparisonScale = std::max(
        {1.0, std::fabs(resolved), std::fabs(lowLimit), std::fabs(highLimit)});
    const double comparisonTolerance =
        32.0 * std::numeric_limits<double>::epsilon() * comparisonScale;
    if (!std::isfinite(resolved) ||
        resolved < lowLimit - comparisonTolerance ||
        resolved > highLimit + comparisonTolerance) {
        if (errorText) {
            *errorText = "Resolved target is outside motor-record soft limits";
        }
        return false;
    }
    *target = resolved;
    if (errorText) {
        errorText->clear();
    }
    return true;
}

bool buildKohzuFreeRotationCommand(
    int controllerAxisNo, double maxVelocity, std::string* command,
    bool* clockwise, std::string* errorText) {
    if (!command || !clockwise || controllerAxisNo < 1 ||
        controllerAxisNo > 32 || !std::isfinite(maxVelocity) ||
        maxVelocity == 0.0) {
        if (errorText) *errorText = "Invalid axis, velocity, or output argument";
        return false;
    }
    *clockwise = maxVelocity > 0.0;
    // ARIES FRP direction: 0=CW and 1=CCW. Project policy uses table 0.
    *command = "FRP" + std::to_string(controllerAxisNo) + "/0/" +
               (*clockwise ? "0" : "1");
    if (errorText) errorText->clear();
    return true;
}

bool validateKohzuJogStart(
    double currentPosition, bool clockwise, bool cwLimit, bool ccwLimit,
    double lowLimit, double highLimit, std::string* errorText) {
    if (!std::isfinite(currentPosition) || !std::isfinite(lowLimit) ||
        !std::isfinite(highLimit) || lowLimit >= highLimit) {
        if (errorText) *errorText = "Invalid position or soft-limit configuration";
        return false;
    }
    if ((clockwise && cwLimit) || (!clockwise && ccwLimit)) {
        if (errorText) *errorText = clockwise
            ? "CW hardware limit is active" : "CCW hardware limit is active";
        return false;
    }
    if ((clockwise && currentPosition >= highLimit) ||
        (!clockwise && currentPosition <= lowLimit)) {
        if (errorText) *errorText = clockwise
            ? "Position is at/beyond the high motor-record soft limit"
            : "Position is at/beyond the low motor-record soft limit";
        return false;
    }
    if (errorText) errorText->clear();
    return true;
}

bool buildKohzuSetPositionCommand(
    int controllerAxisNo, double position, std::string* command,
    long* roundedPosition, std::string* errorText) {
    if (!command || !roundedPosition || controllerAxisNo < 1 ||
        controllerAxisNo > 32 || !std::isfinite(position) ||
        position < static_cast<double>(kMinimumPulsePosition) - 0.5 ||
        position > static_cast<double>(kMaximumPulsePosition) + 0.499999) {
        if (errorText) *errorText = "Position is outside ARIES pulse range";
        return false;
    }
    const long pulses = static_cast<long>(std::lround(position));
    if (pulses < kMinimumPulsePosition || pulses > kMaximumPulsePosition) {
        if (errorText) *errorText = "Rounded position is outside ARIES pulse range";
        return false;
    }
    *command = "WRP" + std::to_string(controllerAxisNo) + "/" +
               std::to_string(pulses);
    *roundedPosition = pulses;
    if (errorText) errorText->clear();
    return true;
}
