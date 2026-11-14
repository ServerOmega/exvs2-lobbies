// Minimal Win32 stand-ins so the POC's banapass.cpp compiles natively on Linux for the unit harness only.
#pragma once
#include <cstdint>
#include <cstring>
typedef unsigned int UINT;
typedef unsigned long long ULONGLONG;
typedef unsigned long DWORD;
typedef const char* LPCSTR;
typedef void* HINSTANCE;
typedef void* FARPROC;
#define __declspec(x)
#define TEXT(x) x
#define _Printf_format_string_
inline HINSTANCE LoadLibrary(const char*) { return nullptr; }          // never loads anything
inline FARPROC GetProcAddress(HINSTANCE, const char*) { return nullptr; }
inline DWORD GetPrivateProfileStringA(LPCSTR, LPCSTR, LPCSTR def, char* out, DWORD n, LPCSTR)
{ std::strncpy(out, def ? def : "", n); out[n - 1] = 0; return (DWORD)std::strlen(out); }
inline int WritePrivateProfileStringA(LPCSTR, LPCSTR, LPCSTR, LPCSTR) { return 1; }  // never writes a card file
#include <cstdio>
inline int strncpy_s(char* d, size_t n, const char* s, size_t c) { std::strncpy(d, s, n < c ? n : c); if (n) d[n - 1] = 0; return 0; }
inline int fopen_s(FILE** f, const char* name, const char* mode) { *f = std::fopen(name, mode); return *f ? 0 : 1; }
