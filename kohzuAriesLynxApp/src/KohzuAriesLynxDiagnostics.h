#ifndef KOHZU_ARIES_LYNX_DIAGNOSTICS_H
#define KOHZU_ARIES_LYNX_DIAGNOSTICS_H

#include <string>

// Return a concise operator-facing interpretation of an ARIES error/warning.
// Unknown codes remain explicit instead of being silently discarded.
std::string kohzuDiagnosticText(bool warning, int code);

#endif
