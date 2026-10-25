#pragma once

// Copy this file to secrets.h and fill in the values for your networks.
// The board joins the first network in this list that it can see, and moves
// on to the next one when a network gives no route to the API for a minute.
// Every network must be 2.4 GHz with a password and no browser login.
#define ALIVE_WIFI_NETWORKS \
  {"YOUR_REPEATER", "YOUR_REPEATER_PASSWORD"}, \
  {"YOUR_LAPTOP_HOTSPOT", "YOUR_LAPTOP_HOTSPOT_PASSWORD"}, \
  {"YOUR_PHONE_HOTSPOT", "YOUR_PHONE_HOTSPOT_PASSWORD"}
#define ALIVE_SERVER_URL "https://api.example.com"
#define ALIVE_DEVICE_TOKEN "YOUR_SEPARATE_DEVICE_TOKEN"

// For an API with a trusted certificate, add its CA certificate as a
// PEM string here to verify the server during Wi-Fi polling. Keep the
// multi-line string in a C++ variable, then define the macro used by main.cpp:
// static constexpr char ALIVE_CA_PEM[] = R"PEM(-----BEGIN CERTIFICATE-----
// ...
// -----END CERTIFICATE-----
// )PEM";
// #define ALIVE_SERVER_CA_CERT ALIVE_CA_PEM
