#include "KohzuAriesLynxProtocol.h"
#include "KohzuAriesLynxDiagnostics.h"
#include "KohzuAriesLynxSpeedTable.h"
#include "KohzuAriesLynxMotion.h"

#include <cassert>
#include <cmath>
#include <iostream>

int main() {
    // Version response with multiple information fields.
    KohzuResponse response =
        parseKohzuResponse("C\tIDN\tARIES\t1\t4\t3\r\n");
    assert(response.kind == KohzuResponseKind::Normal);
    assert(response.command == "IDN");
    assert(response.fields.size() == 4);
    assert(kohzuResponseMatches(response, "IDN"));

    // RAX returns device count, controllable axis count and connection bitmap.
    response = parseKohzuResponse("C\tRAX\t6\t6\t11111100\r\n");
    assert(response.kind == KohzuResponseKind::Normal);
    assert(response.fields[1] == "6");
    assert(kohzuResponseMatches(response, "RAX"));

    // Axis-specific errors retain the numeric code and match the base command.
    response = parseKohzuResponse("E\tAPS1\t304\r\n");
    assert(response.kind == KohzuResponseKind::Error);
    assert(response.hasCode && response.code == 304);
    assert(kohzuResponseMatches(response, "APS"));

    // SYS messages are asynchronous and must not satisfy a pending command.
    response = parseKohzuResponse("E\tSYS\t5\r\n");
    assert(response.systemEvent);
    assert(response.hasCode && response.code == 5);
    assert(!kohzuResponseMatches(response, "RAX"));

    response = parseKohzuResponse("W\tSYS\t52\r\n");
    assert(response.kind == KohzuResponseKind::Warning);
    assert(response.systemEvent && response.code == 52);

    // Malformed input remains invalid rather than being treated as success.
    response = parseKohzuResponse("unexpected response\r\n");
    assert(response.kind == KohzuResponseKind::Invalid);

    // Manual-derived operator text covers fixed codes, parameter-indexed
    // families and unknown future firmware codes.
    assert(kohzuDiagnosticText(false, 304) ==
           "CW hardware limit activated during motion");
    assert(kohzuDiagnosticText(false, 103) ==
           "Parameter 3 is out of range");
    assert(kohzuDiagnosticText(false, 502) ==
           "MPS axis 2 drive parameters are not set");
    assert(kohzuDiagnosticText(true, 52) ==
           "Motionnet device configuration increase detected");
    assert(kohzuDiagnosticText(false, 999) ==
           "Unknown ARIES error code");

    KohzuSpeedTable0 table;
    std::string command;
    std::string speedError;
    assert(buildKohzuSpeedTable0Command(
        1, 100.0, 1000.0, 4500.0, &table, &command, &speedError));
    assert(command == "WTB1/0/100/1000/20/20/2");
    assert(table.startSpeed == 100 && table.topSpeed == 1000);
    assert(table.accelerationUnits == 20 && table.pattern == 2);

    // Start speed above 50% and an acceleration time below the manual's
    // range must both be rejected before any controller transaction.
    assert(!buildKohzuSpeedTable0Command(
        1, 600.0, 1000.0, 4500.0, &table, &command, &speedError));
    assert(!buildKohzuSpeedTable0Command(
        1, 100.0, 1000.0, 1000000.0, &table, &command, &speedError));

    long roundedPosition = 0;
    std::string motionError;
    assert(buildKohzuPositionCommand(
        1, 1000.0, false, &command, &roundedPosition, &motionError));
    assert(command == "APS1/0/1000/1" && roundedPosition == 1000);
    assert(buildKohzuPositionCommand(
        32, -12.6, true, &command, &roundedPosition, &motionError));
    assert(command == "RPS32/0/-13/1" && roundedPosition == -13);
    assert(buildKohzuPositionCommand(
        1, -134217728.0, false, &command, &roundedPosition, &motionError));
    assert(buildKohzuPositionCommand(
        1, 134217727.0, true, &command, &roundedPosition, &motionError));
    assert(!buildKohzuPositionCommand(
        0, 0.0, false, &command, &roundedPosition, &motionError));
    assert(!buildKohzuPositionCommand(
        1, 134217728.0, false, &command, &roundedPosition, &motionError));

    double target = 0.0;
    assert(validateKohzuSoftLimitTarget(
        100.0, 500, false, -500.0, 500.0, &target, &motionError));
    assert(target == 500.0);
    assert(validateKohzuSoftLimitTarget(
        100.0, -600, true, -500.0, 500.0, &target, &motionError));
    assert(target == -500.0);
    // Decimal EGU/MRES conversion can put a nominal pulse boundary one ULP
    // inside the integer command.  The exact boundary must still be allowed.
    assert(validateKohzuSoftLimitTarget(
        0.0, 500, false, -500.0,
        std::nextafter(500.0, 0.0), &target, &motionError));
    assert(!validateKohzuSoftLimitTarget(
        0.0, 500, false, -500.0, 499.9999, &target, &motionError));
    assert(!validateKohzuSoftLimitTarget(
        100.0, 401, true, -500.0, 500.0, &target, &motionError));
    assert(!validateKohzuSoftLimitTarget(
        0.0, 0, false, 10.0, -10.0, &target, &motionError));

    bool clockwise = false;
    assert(buildKohzuFreeRotationCommand(
        1, 1000.0, &command, &clockwise, &motionError));
    assert(command == "FRP1/0/0" && clockwise);
    assert(buildKohzuFreeRotationCommand(
        32, -1000.0, &command, &clockwise, &motionError));
    assert(command == "FRP32/0/1" && !clockwise);
    assert(!buildKohzuFreeRotationCommand(
        1, 0.0, &command, &clockwise, &motionError));
    assert(validateKohzuJogStart(
        0.0, true, false, false, -100.0, 100.0, &motionError));
    assert(!validateKohzuJogStart(
        100.0, true, false, false, -100.0, 100.0, &motionError));
    assert(!validateKohzuJogStart(
        0.0, false, false, true, -100.0, 100.0, &motionError));

    assert(buildKohzuSetPositionCommand(
        1, 123.6, &command, &roundedPosition, &motionError));
    assert(command == "WRP1/124" && roundedPosition == 124);
    assert(buildKohzuSetPositionCommand(
        32, -134217728.0, &command, &roundedPosition, &motionError));
    assert(!buildKohzuSetPositionCommand(
        1, 134217728.0, &command, &roundedPosition, &motionError));

    std::cout << "KohzuAriesLynxProtocol tests passed\n";
    return 0;
}
