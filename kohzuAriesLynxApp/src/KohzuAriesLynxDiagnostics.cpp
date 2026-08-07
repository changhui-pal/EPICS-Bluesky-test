#include "KohzuAriesLynxDiagnostics.h"

#include <map>

namespace {
const std::map<int, const char*> kErrors = {
    {1, "Missing STX (RS-232C only)"},
    {3, "Invalid character in command"},
    {4, "Unsupported command"},
    {5, "Emergency-stop input detected; remove cause, then REM"},
    {6, "Motionnet disconnected during motion; restore, then RAX"},
    {100, "Incorrect parameter count"},
    {120, "Axis number exceeds configured axes"},
    {121, "Unknown system parameter number"},
    {304, "CW hardware limit activated during motion"},
    {305, "CCW hardware limit activated during motion"},
    {306, "Axis limit stopped multi-axis motion"},
    {307, "Both CW and CCW limits are active"},
    {308, "Drive requested while motor excitation is off"},
    {309, "Operation requested while axis is moving"},
    {310, "Target exceeds controller pulse coordinate range"},
    {311, "Pulse counter change requested while moving"},
    {312, "Encoder counter change requested while moving"},
    {313, "System parameter change requested while moving"},
    {314, "Axis stopped because emergency stop was detected"},
    {315, "Axis stopped because alarm was detected"},
    {316, "Negative soft limit is above positive soft limit"},
    {317, "Positive controller soft limit stopped motion"},
    {318, "Negative controller soft limit stopped motion"},
    {319, "Controller soft limit stopped multi-axis motion"},
    {320, "Main-axis displacement is zero in interpolation"},
    {321, "Servo-ready signal is off"},
    {322, "Motionnet disconnect stopped moving axis"},
    {323, "Stop command repeated while stopping"},
    {324, "Alarm stopped an axis in multi-axis motion"},
    {399, "Unexpected abnormal stop"},
    {401, "Encoder feedback retry limit exceeded"},
    {500, "MPS requested before MPI setup"},
    {505, "MPS first-axis target is outside pulse range"},
    {506, "MPS second-axis target is outside pulse range"},
    {507, "MPS third-axis target is outside pulse range"},
    {508, "MPS fourth-axis target is outside pulse range"},
    {510, "Duplicate axes in simultaneous motion"},
    {511, "First and second simultaneous axes are identical"},
    {512, "First and third simultaneous axes are identical"},
    {513, "First and fourth simultaneous axes are identical"},
    {514, "Second and third simultaneous axes are identical"},
    {515, "Second and fourth simultaneous axes are identical"},
    {516, "Third and fourth simultaneous axes are identical"},
    {601, "Speed-table acceleration time is too large"},
    {602, "Speed-table acceleration time is too small"},
    {603, "Speed-table deceleration time is too large"},
    {604, "Speed-table deceleration time is too small"},
    {605, "Start speed exceeds 50 percent of maximum speed"},
    {606, "Interpolated-axis speed exceeds system limit"},
    {607, "Requested maximum speed exceeds system limit"},
    {700, "Trigger type changed while trigger output is active"},
    {701, "TRS requested for a moving axis"},
    {702, "Trigger output did not stop by timeout"},
    {703, "Trigger output stopped too early"},
    {800, "Command rejected during emergency-stop lock"},
    {801, "Emergency-stop cause remains; REM rejected"},
    {802, "Command rejected after Motionnet shutdown; RAX required"},
    {803, "Command sent before previous response was received"},
    {901, "WIP/RIP requested while an axis is moving"},
};

const std::map<int, const char*> kWarnings = {
    {51, "Motionnet device configuration change detected"},
    {52, "Motionnet device configuration increase detected"},
    {350, "Target exceeds controller soft limit; motion stops at limit"},
};
}  // namespace

std::string kohzuDiagnosticText(bool warning, int code) {
    const auto& table = warning ? kWarnings : kErrors;
    const auto entry = table.find(code);
    if (entry != table.end()) {
        return entry->second;
    }

    // Parameter errors 101..109 identify the one-based invalid parameter.
    if (!warning && code >= 101 && code <= 109) {
        return "Parameter " + std::to_string(code - 100) + " is out of range";
    }
    // Errors 501..504 identify an MPS axis whose MPI data was not set.
    if (!warning && code >= 501 && code <= 504) {
        return "MPS axis " + std::to_string(code - 500) +
               " drive parameters are not set";
    }
    return warning ? "Unknown ARIES warning code" : "Unknown ARIES error code";
}
