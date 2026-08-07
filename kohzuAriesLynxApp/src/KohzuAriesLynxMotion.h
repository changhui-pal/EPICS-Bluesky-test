#ifndef KOHZU_ARIES_LYNX_MOTION_H
#define KOHZU_ARIES_LYNX_MOTION_H

#include <string>

// Build an ARIES single-axis position command from Model 3 pulse units.
// This function performs no I/O and therefore cannot start motion.
bool buildKohzuPositionCommand(int controllerAxisNo, double position,
                               bool relative, std::string* command,
                               long* roundedPosition,
                               std::string* errorText);

// Resolve an absolute target and enforce the motor-record raw soft limits.
// currentPosition and limits are controller pulses at the Model 3 boundary.
bool validateKohzuSoftLimitTarget(double currentPosition, long commandPulses,
                                  bool relative, double lowLimit,
                                  double highLimit, double* target,
                                  std::string* errorText);

// Build an ARIES continuous-drive (FRP) command. Positive Model 3 velocity is
// provisionally mapped to controller CW, and negative velocity to CCW.
bool buildKohzuFreeRotationCommand(int controllerAxisNo, double maxVelocity,
                                   std::string* command, bool* clockwise,
                                   std::string* errorText);

// Reject a jog that starts at/beyond the motor-record soft limit in its
// requested direction. The motor record remains responsible for stopping an
// accepted jog as it approaches that limit.
bool validateKohzuJogStart(double currentPosition, bool clockwise,
                           bool cwLimit, bool ccwLimit, double lowLimit,
                           double highLimit, std::string* errorText);

// Build a coordinate-register write without starting motion.
bool buildKohzuSetPositionCommand(int controllerAxisNo, double position,
                                  std::string* command,
                                  long* roundedPosition,
                                  std::string* errorText);

#endif
