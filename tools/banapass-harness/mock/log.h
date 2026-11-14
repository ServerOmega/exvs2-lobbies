#pragma once
#include <cstdio>
#include <cstdarg>
enum class LogLevel { NONE, ERR, WARN, INFO, DEBUG, TRACE };
inline void log(LogLevel, const char* fmt, ...) { if (!std::getenv("HARNESS_TRACE")) return;
  va_list a; va_start(a, fmt); std::vfprintf(stderr, fmt, a); va_end(a); std::fputc('\n', stderr); }
#define err(...) log(LogLevel::ERR, __VA_ARGS__)
#define warn(...) log(LogLevel::WARN, __VA_ARGS__)
#define info(...) log(LogLevel::INFO, __VA_ARGS__)
#define debug(...) log(LogLevel::DEBUG, __VA_ARGS__)
#define trace(...) log(LogLevel::TRACE, __VA_ARGS__)
