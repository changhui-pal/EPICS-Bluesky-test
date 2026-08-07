#include "KohzuAriesLynxSpeedTable.h"

#include <cmath>

namespace {
struct SpeedRegulation {
    double upperSpeed;
    long speedQuantum;
    long minimumTimeMs;
    long maximumTimeMs;
};

// ARIES manual section 3-1-3. Gaps between some ranges represent values that
// cannot be produced after applying the preceding range's speed quantum.
const SpeedRegulation kRegulations[] = {
    {20, 1, 10, 100},       {250, 1, 10, 1000},
    {500, 1, 10, 10000},    {1000, 1, 10, 10000},
    {2500, 1, 10, 10000},   {5000, 1, 10, 10000},
    {10000, 2, 10, 10000},  {25000, 5, 10, 10000},
    {50000, 10, 10, 10000}, {100000, 20, 10, 10000},
    {250000, 50, 10, 10000},{500000, 50, 10, 10000},
    {1000000, 50, 20, 20000},
    {2000000, 50, 40, 40000},
    {5000000, 50, 100, 100000},
};

const SpeedRegulation* regulationFor(double speed) {
    for (const auto& regulation : kRegulations) {
        if (speed <= regulation.upperSpeed) {
            return &regulation;
        }
    }
    return nullptr;
}

void fail(const std::string& text, std::string* errorText) {
    if (errorText) {
        *errorText = text;
    }
}
}  // namespace

bool buildKohzuSpeedTable0Command(
    int controllerAxisNo, double minVelocity, double maxVelocity,
    double acceleration, KohzuSpeedTable0* table, std::string* command,
    std::string* errorText) {
    if (!table || !command || controllerAxisNo < 1 || controllerAxisNo > 32) {
        fail("Invalid axis or output argument", errorText);
        return false;
    }
    if (!std::isfinite(minVelocity) || !std::isfinite(maxVelocity) ||
        !std::isfinite(acceleration) || minVelocity < 1.0 ||
        maxVelocity < 2.0 || maxVelocity > 5000000.0 ||
        minVelocity > 2500000.0 || acceleration <= 0.0) {
        fail("Velocity or acceleration is outside WTB range", errorText);
        return false;
    }

    const SpeedRegulation* regulation = regulationFor(maxVelocity);
    if (!regulation) {
        fail("No ARIES speed regulation matches top speed", errorText);
        return false;
    }
    const long topSpeed = static_cast<long>(std::lround(
        maxVelocity / regulation->speedQuantum)) * regulation->speedQuantum;
    const long startSpeed = static_cast<long>(std::lround(minVelocity));
    if (topSpeed < 2 || topSpeed > 5000000 || startSpeed < 1 ||
        startSpeed > 2500000 || startSpeed * 2 > topSpeed) {
        fail("Start speed must not exceed 50 percent of top speed", errorText);
        return false;
    }

    // Model 3 acceleration is steps/s^2. Time from start to top speed is
    // converted to WTB's integer units of 10 ms.
    const double accelerationSeconds =
        (static_cast<double>(topSpeed) - startSpeed) / acceleration;
    const long timeUnits =
        static_cast<long>(std::lround(accelerationSeconds * 100.0));
    const long timeMs = timeUnits * 10;
    if (timeUnits < 1 || timeUnits > 10000 ||
        timeMs < regulation->minimumTimeMs ||
        timeMs > regulation->maximumTimeMs) {
        fail("Acceleration time is outside the top-speed regulation", errorText);
        return false;
    }

    table->startSpeed = startSpeed;
    table->topSpeed = topSpeed;
    table->accelerationUnits = timeUnits;
    table->decelerationUnits = timeUnits;
    table->pattern = 2;
    *command = "WTB" + std::to_string(controllerAxisNo) + "/0/" +
               std::to_string(startSpeed) + "/" + std::to_string(topSpeed) +
               "/" + std::to_string(timeUnits) + "/" +
               std::to_string(timeUnits) + "/2";
    if (errorText) {
        errorText->clear();
    }
    return true;
}
