#pragma once

// Copy this file to secrets.h and fill in the values for your demo network.
#define ALIVE_WIFI_SSID "YOUR_WIFI_NAME"
#define ALIVE_WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define ALIVE_SERVER_URL "https://api.example.com"
#define ALIVE_DEVICE_TOKEN "YOUR_SEPARATE_DEVICE_TOKEN"

// For a NAS domain with a trusted certificate, add its CA certificate as a
// PEM string here to verify the server during Wi-Fi polling. Keep the
// multi-line string in a C++ variable, then define the macro used by main.cpp:
// static constexpr char ALIVE_CA_PEM[] = R"PEM(-----BEGIN CERTIFICATE-----
// ...
// -----END CERTIFICATE-----
// )PEM";
// #define ALIVE_SERVER_CA_CERT ALIVE_CA_PEM
