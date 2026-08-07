#ifndef KOHZU_ARIES_LYNX_SPEED_TABLE_H
#define KOHZU_ARIES_LYNX_SPEED_TABLE_H

#include <string>

struct KohzuSpeedTable0 {
    long startSpeed = 0;
    long topSpeed = 0;
    long accelerationUnits = 0;  // WTB units of 10 ms.
    long decelerationUnits = 0;
    int pattern = 2;             // Trapezoidal drive.
};

// Convert Model 3 step-domain values to a validated table-0 WTB command.
// No controller I/O is performed by this function.
bool buildKohzuSpeedTable0Command(int controllerAxisNo, double minVelocity,
                                  double maxVelocity, double acceleration,
                                  KohzuSpeedTable0* table,
                                  std::string* command,
                                  std::string* errorText);

#endif
