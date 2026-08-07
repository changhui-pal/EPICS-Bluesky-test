#ifndef KOHZU_ARIES_LYNX_PROTOCOL_H
#define KOHZU_ARIES_LYNX_PROTOCOL_H

#include <string>
#include <vector>

// The first field of every ARIES response identifies its result category.
enum class KohzuResponseKind {
    Normal,
    Error,
    Warning,
    Invalid
};

// Parsed representation of one CRLF-terminated line received from ARIES.
struct KohzuResponse {
    KohzuResponseKind kind = KohzuResponseKind::Invalid;
    std::string command;
    std::vector<std::string> fields;
    int code = 0;
    bool hasCode = false;
    bool systemEvent = false;
    std::string raw;
};

// Parse one response line. The parser has no EPICS dependencies so it can be
// unit-tested without an IOC or physical controller.
KohzuResponse parseKohzuResponse(const std::string& line);

// Verify that a response belongs to the command currently awaiting a reply.
// Axis commands append an axis number to the three-letter command token.
bool kohzuResponseMatches(const KohzuResponse& response,
                          const std::string& expectedCommand);

#endif
