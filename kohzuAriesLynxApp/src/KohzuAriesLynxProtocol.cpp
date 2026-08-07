#include "KohzuAriesLynxProtocol.h"

#include <cerrno>
#include <cstdlib>

namespace {

// Split on TAB while preserving empty fields. ARIES uses TAB, not spaces, as
// the response field delimiter.
std::vector<std::string> splitTabs(const std::string& value) {
    std::vector<std::string> result;
    std::size_t start = 0;
    while (true) {
        const std::size_t tab = value.find('\t', start);
        if (tab == std::string::npos) {
            result.emplace_back(value.substr(start));
            return result;
        }
        result.emplace_back(value.substr(start, tab - start));
        start = tab + 1;
    }
}

bool parseInteger(const std::string& text, int* value) {
    if (text.empty()) {
        return false;
    }
    char* end = nullptr;
    errno = 0;
    const long parsed = std::strtol(text.c_str(), &end, 10);
    if (errno != 0 || end == text.c_str() || *end != '\0') {
        return false;
    }
    *value = static_cast<int>(parsed);
    return true;
}

}  // namespace

KohzuResponse parseKohzuResponse(const std::string& line) {
    KohzuResponse response;
    response.raw = line;

    // asyn normally removes EOS. Stripping it here also makes the parser safe
    // for direct use with captured wire data and unit-test strings.
    std::string content = line;
    while (!content.empty() &&
           (content.back() == '\r' || content.back() == '\n')) {
        content.pop_back();
    }

    const std::vector<std::string> tokens = splitTabs(content);
    if (tokens.size() < 2 || tokens[0].size() != 1) {
        return response;
    }

    switch (tokens[0][0]) {
        case 'C':
            response.kind = KohzuResponseKind::Normal;
            break;
        case 'E':
            response.kind = KohzuResponseKind::Error;
            break;
        case 'W':
            response.kind = KohzuResponseKind::Warning;
            break;
        default:
            return response;
    }

    response.command = tokens[1];
    response.systemEvent = response.command == "SYS";
    response.fields.assign(tokens.begin() + 2, tokens.end());

    // Error and warning responses place the numeric code in the final field.
    if ((response.kind == KohzuResponseKind::Error ||
         response.kind == KohzuResponseKind::Warning) &&
        !response.fields.empty()) {
        response.hasCode = parseInteger(response.fields.back(), &response.code);
    }
    return response;
}

bool kohzuResponseMatches(const KohzuResponse& response,
                          const std::string& expectedCommand) {
    if (response.kind == KohzuResponseKind::Invalid || response.systemEvent ||
        expectedCommand.empty()) {
        return false;
    }
    if (response.command == expectedCommand) {
        return true;
    }

    // Responses to axis commands look like APS1, RDP12, etc. Only decimal
    // digits may follow the expected three-letter command.
    if (response.command.compare(0, expectedCommand.size(), expectedCommand) != 0 ||
        response.command.size() == expectedCommand.size()) {
        return false;
    }
    for (std::size_t index = expectedCommand.size();
         index < response.command.size(); ++index) {
        if (response.command[index] < '0' || response.command[index] > '9') {
            return false;
        }
    }
    return true;
}
