#pragma once
#include <filesystem>
#include <string>
// Only the fields banapass.cpp reads. The v1/v2 proposal fields are always present; the original source ignores them.
struct StartupConfig {
    bool UseRealCardReader = false;
    bool UsePyBanapassReader = false;
    bool AutomaticCardButton = false;
    bool CardCancelCallback = true;
    int CardCancelStatus = 3;
    int CardWaitTimeoutMs = 0;
    bool SkipAutoCreateForPyBanapassReader = true;
    std::string CardReaderComPort;
    std::string CardFileBasePath;
};
extern StartupConfig globalConfig;
inline std::filesystem::path GetBasePath() { return std::filesystem::temp_directory_path() / "banapass-harness-nonexistent"; }
